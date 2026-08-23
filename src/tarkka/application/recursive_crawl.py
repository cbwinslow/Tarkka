from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from tarkka.application.crawl_eligibility import (
    CrawlEligibilityDecision,
    combine_crawl_eligibility,
)
from tarkka.application.robots_access import evaluate_robots_access, robots_uri_for
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.rights_access import RightsAccessDecision
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
    eligibility: CrawlEligibilityDecision | None = None
    effective_policy: ResourceAcquisitionPolicy | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RecursiveCrawlGateStatus):
            raise ValueError("recursive crawl gate status must be a RecursiveCrawlGateStatus")
        if not isinstance(self.checkpoint, TraversalCheckpoint):
            raise ValueError("recursive crawl gate checkpoint must be a TraversalCheckpoint")
        if not isinstance(self.target_id, UUID):
            raise ValueError("recursive crawl gate target_id must be a UUID")
        if self.status is RecursiveCrawlGateStatus.READY:
            if self.eligibility is None or self.effective_policy is None:
                raise ValueError("ready recursive crawl gate requires eligibility and policy")
            if not self.eligibility.allowed:
                raise ValueError("ready recursive crawl gate requires allowed eligibility")
        elif self.effective_policy is not None:
            raise ValueError("only a ready recursive crawl gate may expose an effective policy")
        if self.status is RecursiveCrawlGateStatus.ROBOTS_REFRESH_REQUIRED:
            if self.robots_uri is None:
                raise ValueError("robots refresh result requires a robots URI")
            if self.eligibility is not None:
                raise ValueError("robots refresh result must not claim final eligibility")


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

        if not policy.allows_uri(target.uri):
            skipped = checkpoint.skip(
                target_id,
                reason="technical acquisition policy denied target",
            )
            self._save(skipped)
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.SKIPPED,
                checkpoint=skipped,
                target_id=target_id,
            )

        if not checkpoint.budget.allows_request(
            policy,
            depth=target.depth,
            seconds_since_last_request=seconds_since_last_request,
        ):
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.DEFERRED_BUDGET,
                checkpoint=checkpoint,
                target_id=target_id,
            )

        robots_uri = robots_uri_for(target.uri)
        cached = self._robots_cache.get(robots_uri)
        if cached is None or not cached.is_fresh(now):
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.ROBOTS_REFRESH_REQUIRED,
                checkpoint=checkpoint,
                target_id=target_id,
                robots_uri=robots_uri,
            )

        crawl = evaluate_robots_access(
            target_uri=target.uri,
            product_token=product_token,
            policy=policy,
            robots=cached.result,
        )
        eligibility = combine_crawl_eligibility(crawl, rights)
        if not eligibility.allowed:
            skipped = checkpoint.skip(
                target_id,
                reason=f"recursive crawl policy denied target: {eligibility.reason.value}",
            )
            self._save(skipped)
            return RecursiveCrawlGateResult(
                status=RecursiveCrawlGateStatus.SKIPPED,
                checkpoint=skipped,
                target_id=target_id,
                robots_uri=robots_uri,
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
                target_id=target_id,
                robots_uri=robots_uri,
                eligibility=eligibility,
            )

        return RecursiveCrawlGateResult(
            status=RecursiveCrawlGateStatus.READY,
            checkpoint=checkpoint,
            target_id=target_id,
            robots_uri=robots_uri,
            eligibility=eligibility,
            effective_policy=effective_policy,
        )

    def _save(self, checkpoint: TraversalCheckpoint) -> None:
        try:
            self._checkpoint_repository.save(checkpoint)
        except Exception as exc:
            raise RuntimeError("unable to persist recursive crawl policy decision") from exc


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
