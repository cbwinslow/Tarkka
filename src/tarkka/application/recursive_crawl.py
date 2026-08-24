from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from tarkka.application.crawl_eligibility import (
    CrawlEligibilityDecision,
    combine_crawl_eligibility,
)
from tarkka.application.http_acquisition import HttpAcquisitionResult
from tarkka.application.robots_access import evaluate_robots_access, robots_uri_for
from tarkka.application.robots_refresh import RobotsRefreshResult
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.rights_access import RightsAccessDecision
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus, TraversalTarget
from tarkka.ports.robots_cache import RobotsCache
from tarkka.ports.traversal import TraversalCheckpointRepository


class RecursiveCrawlGateStatus(StrEnum):
    READY = "ready"
    ROBOTS_REFRESH_REQUIRED = "robots_refresh_required"
    DEFERRED_BUDGET = "deferred_budget"
    DEFERRED_PACING = "deferred_pacing"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class RecursiveCrawlGateResult:
    """Policy-gate result before recursive network acquisition begins."""

    status: RecursiveCrawlGateStatus
    checkpoint: TraversalCheckpoint
    target_id: UUID
    robots_uri: str | None = None
    robots_entry: RobotsCacheEntry | None = None
    eligibility: CrawlEligibilityDecision | None = None
    effective_policy: ResourceAcquisitionPolicy | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RecursiveCrawlGateStatus):
            raise ValueError("recursive crawl gate status must be a RecursiveCrawlGateStatus")
        if not isinstance(self.checkpoint, TraversalCheckpoint):
            raise ValueError("recursive crawl gate checkpoint must be a TraversalCheckpoint")
        if not isinstance(self.target_id, UUID):
            raise ValueError("recursive crawl gate target_id must be a UUID")
        if self.robots_entry is not None and not isinstance(self.robots_entry, RobotsCacheEntry):
            raise ValueError("recursive crawl robots_entry must be a RobotsCacheEntry")
        if self.robots_entry is not None and self.robots_uri != self.robots_entry.robots_uri:
            raise ValueError("recursive crawl robots entry must match robots URI")
        if self.status is RecursiveCrawlGateStatus.READY:
            if self.eligibility is None or self.effective_policy is None:
                raise ValueError("ready recursive crawl gate requires eligibility and policy")
            if not self.eligibility.allowed:
                raise ValueError("ready recursive crawl gate requires allowed eligibility")
            if self.robots_entry is None:
                raise ValueError("ready recursive crawl gate requires robots provenance")
        elif self.effective_policy is not None:
            raise ValueError("only a ready recursive crawl gate may expose an effective policy")
        if self.status is RecursiveCrawlGateStatus.ROBOTS_REFRESH_REQUIRED:
            if self.robots_uri is None:
                raise ValueError("robots refresh result requires a robots URI")
            if self.eligibility is not None:
                raise ValueError("robots refresh result must not claim final eligibility")


class RecursiveTargetAcquirer(Protocol):
    """Existing target-acquisition behavior required by the recursive coordinator."""

    def acquire(
        self,
        checkpoint: TraversalCheckpoint,
        target_id: UUID,
        policy: ResourceAcquisitionPolicy,
        *,
        request_uri: str | None = None,
        seconds_since_last_request: float | None = None,
    ) -> HttpAcquisitionResult: ...


class RobotsRefresher(Protocol):
    """Bounded robots refresh behavior required by the recursive coordinator."""

    def refresh(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        *,
        robots_uri: str,
        depth: int,
        now: datetime,
        seconds_since_last_request: float | None = None,
    ) -> RobotsRefreshResult: ...


@dataclass(frozen=True, slots=True)
class RecursiveCrawlResult:
    """One recursive target decision, optional robots refresh, and optional acquisition."""

    gate: RecursiveCrawlGateResult
    acquisition: HttpAcquisitionResult | None = None
    robots_refresh: RobotsRefreshResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.gate, RecursiveCrawlGateResult):
            raise ValueError("recursive crawl result requires a gate result")
        if self.acquisition is not None and not isinstance(self.acquisition, HttpAcquisitionResult):
            raise ValueError("recursive crawl acquisition must be an HttpAcquisitionResult")
        if self.robots_refresh is not None and not isinstance(
            self.robots_refresh, RobotsRefreshResult
        ):
            raise ValueError("recursive crawl refresh must be a RobotsRefreshResult")
        if self.acquisition is not None and self.gate.status is not RecursiveCrawlGateStatus.READY:
            raise ValueError("only a ready recursive crawl gate may produce an acquisition")

    @property
    def checkpoint(self) -> TraversalCheckpoint:
        """Return the newest checkpoint produced by this orchestration result."""
        if self.acquisition is not None:
            return self.acquisition.checkpoint
        return self.gate.checkpoint


class RecursiveCrawlPolicyGate:
    """Gate queued discovered targets before handing them to HTTP acquisition."""

    def __init__(
        self,
        *,
        robots_cache: RobotsCache,
        checkpoint_repository: TraversalCheckpointRepository,
    ) -> None:
        self._robots_cache = robots_cache
        self._checkpoint_repository = checkpoint_repository

    def evaluate(
        self,
        checkpoint: TraversalCheckpoint,
        target_id: UUID,
        policy: ResourceAcquisitionPolicy,
        *,
        product_token: str,
        rights: RightsAccessDecision,
        now: datetime,
        seconds_since_last_request: float | None = None,
    ) -> RecursiveCrawlGateResult:
        target = _queued_target(checkpoint, target_id)
        _validate_rights_for_target(target, rights)
        early = self._evaluate_early_policy(
            checkpoint,
            target,
            policy,
            seconds_since_last_request=seconds_since_last_request,
        )
        if early is not None:
            return early

        robots_uri = robots_uri_for(target.uri)
        cached = self._robots_cache.get(robots_uri)
        if cached is None or not cached.is_fresh(now):
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.ROBOTS_REFRESH_REQUIRED,
                checkpoint=checkpoint,
                target_id=target_id,
                robots_uri=robots_uri,
                robots_entry=cached,
            )

        return self._evaluate_entry_after_precheck(
            checkpoint,
            target,
            policy,
            product_token=product_token,
            rights=rights,
            entry=cached,
            seconds_since_last_request=seconds_since_last_request,
        )

    def evaluate_refreshed_entry(
        self,
        checkpoint: TraversalCheckpoint,
        target_id: UUID,
        policy: ResourceAcquisitionPolicy,
        *,
        product_token: str,
        rights: RightsAccessDecision,
        entry: RobotsCacheEntry,
        seconds_since_last_request: float | None = None,
    ) -> RecursiveCrawlGateResult:
        """Re-evaluate after a bounded refresh using the explicitly selected robots entry."""
        target = _queued_target(checkpoint, target_id)
        _validate_rights_for_target(target, rights)
        early = self._evaluate_early_policy(
            checkpoint,
            target,
            policy,
            seconds_since_last_request=seconds_since_last_request,
        )
        if early is not None:
            return early
        expected_uri = robots_uri_for(target.uri)
        if entry.robots_uri != expected_uri:
            raise ValueError("robots entry does not belong to the recursive target authority")
        return self._evaluate_entry_after_precheck(
            checkpoint,
            target,
            policy,
            product_token=product_token,
            rights=rights,
            entry=entry,
            seconds_since_last_request=seconds_since_last_request,
        )

    def _evaluate_early_policy(
        self,
        checkpoint: TraversalCheckpoint,
        target: TraversalTarget,
        policy: ResourceAcquisitionPolicy,
        *,
        seconds_since_last_request: float | None,
    ) -> RecursiveCrawlGateResult | None:
        if not policy.allows_uri(target.uri):
            skipped = checkpoint.skip(
                target.target_id,
                reason="technical acquisition policy denied target",
            )
            self._save(skipped)
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.SKIPPED,
                checkpoint=skipped,
                target_id=target.target_id,
            )

        if not checkpoint.budget.allows_request(
            policy,
            depth=target.depth,
            seconds_since_last_request=seconds_since_last_request,
        ):
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.DEFERRED_BUDGET,
                checkpoint=checkpoint,
                target_id=target.target_id,
            )
        return None

    def _evaluate_entry_after_precheck(
        self,
        checkpoint: TraversalCheckpoint,
        target: TraversalTarget,
        policy: ResourceAcquisitionPolicy,
        *,
        product_token: str,
        rights: RightsAccessDecision,
        entry: RobotsCacheEntry,
        seconds_since_last_request: float | None,
    ) -> RecursiveCrawlGateResult:
        crawl = evaluate_robots_access(
            target_uri=target.uri,
            product_token=product_token,
            policy=policy,
            robots=entry.result,
        )
        eligibility = combine_crawl_eligibility(crawl, rights)
        if not eligibility.allowed:
            skipped = checkpoint.skip(
                target.target_id,
                reason=f"recursive crawl policy denied target: {eligibility.reason.value}",
            )
            self._save(skipped)
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.SKIPPED,
                checkpoint=skipped,
                target_id=target.target_id,
                robots_uri=entry.robots_uri,
                robots_entry=entry,
                eligibility=eligibility,
            )

        effective_policy = replace(
            policy,
            min_request_interval_seconds=max(
                policy.min_request_interval_seconds,
                crawl.effective_min_request_interval_seconds,
            ),
        )
        if not checkpoint.budget.allows_request(
            effective_policy,
            depth=target.depth,
            seconds_since_last_request=seconds_since_last_request,
        ):
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.DEFERRED_PACING,
                checkpoint=checkpoint,
                target_id=target.target_id,
                robots_uri=entry.robots_uri,
                robots_entry=entry,
                eligibility=eligibility,
            )

        return RecursiveCrawlGateResult(
            status=RecursiveCrawlGateStatus.READY,
            checkpoint=checkpoint,
            target_id=target.target_id,
            robots_uri=entry.robots_uri,
            robots_entry=entry,
            eligibility=eligibility,
            effective_policy=effective_policy,
        )

    def _save(self, checkpoint: TraversalCheckpoint) -> None:
        try:
            self._checkpoint_repository.save(checkpoint)
        except Exception as exc:
            raise RuntimeError("unable to persist recursive crawl policy decision") from exc


class RecursiveCrawlCoordinator:
    """Run the recursive policy gate, bounded robots refresh, and existing HTTP acquisition."""

    def __init__(
        self,
        *,
        policy_gate: RecursiveCrawlPolicyGate,
        robots_refresher: RobotsRefresher,
        target_acquirer: RecursiveTargetAcquirer,
    ) -> None:
        self._policy_gate = policy_gate
        self._robots_refresher = robots_refresher
        self._target_acquirer = target_acquirer

    def acquire(
        self,
        checkpoint: TraversalCheckpoint,
        target_id: UUID,
        policy: ResourceAcquisitionPolicy,
        *,
        product_token: str,
        rights: RightsAccessDecision,
        now: datetime,
        request_uri: str | None = None,
        seconds_since_last_request: float | None = None,
    ) -> RecursiveCrawlResult:
        gate = self._policy_gate.evaluate(
            checkpoint,
            target_id,
            policy,
            product_token=product_token,
            rights=rights,
            now=now,
            seconds_since_last_request=seconds_since_last_request,
        )
        refresh: RobotsRefreshResult | None = None
        acquisition_interval = seconds_since_last_request

        if gate.status is RecursiveCrawlGateStatus.ROBOTS_REFRESH_REQUIRED:
            target = _queued_target(gate.checkpoint, target_id)
            if gate.robots_uri is None:
                raise RuntimeError("robots refresh gate did not provide a robots URI")
            refresh = self._robots_refresher.refresh(
                gate.checkpoint,
                policy,
                robots_uri=gate.robots_uri,
                depth=target.depth,
                now=now,
                seconds_since_last_request=seconds_since_last_request,
            )
            # A robots refresh just performed (or attempted) network I/O. Re-gate conservatively
            # from zero elapsed time so the policy fetch cannot accidentally satisfy target pacing.
            acquisition_interval = 0.0
            gate = self._policy_gate.evaluate_refreshed_entry(
                refresh.checkpoint,
                target_id,
                policy,
                product_token=product_token,
                rights=rights,
                entry=refresh.entry,
                seconds_since_last_request=acquisition_interval,
            )

        if gate.status is not RecursiveCrawlGateStatus.READY:
            return RecursiveCrawlResult(gate=gate, robots_refresh=refresh)

        effective_policy = gate.effective_policy
        if effective_policy is None:
            raise RuntimeError("ready recursive crawl gate did not provide an effective policy")
        acquisition = self._target_acquirer.acquire(
            gate.checkpoint,
            target_id,
            effective_policy,
            request_uri=request_uri,
            seconds_since_last_request=acquisition_interval,
        )
        return RecursiveCrawlResult(
            gate=gate,
            acquisition=acquisition,
            robots_refresh=refresh,
        )


def _queued_target(checkpoint: TraversalCheckpoint, target_id: UUID) -> TraversalTarget:
    if not isinstance(checkpoint, TraversalCheckpoint):
        raise ValueError("checkpoint must be a TraversalCheckpoint")
    if not isinstance(target_id, UUID):
        raise ValueError("target_id must be a UUID")
    target = next((item for item in checkpoint.targets if item.target_id == target_id), None)
    if target is None:
        raise ValueError("recursive crawl target does not exist")
    if target.status is not TraversalStatus.QUEUED:
        raise ValueError("recursive crawl policy gate requires a queued target")
    return target


def _validate_rights_for_target(
    target: TraversalTarget,
    rights: RightsAccessDecision,
) -> None:
    if not isinstance(rights, RightsAccessDecision):
        raise ValueError("rights must be a RightsAccessDecision")
    if rights.target_uri != target.uri:
        raise ValueError("rights decision does not belong to the recursive crawl target")
