from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from tarkka.application.http_acquisition import HttpAcquisitionResult
from tarkka.application.recursive_crawl import (
    RecursiveCrawlCoordinator,
    RecursiveCrawlGateStatus,
    RecursiveCrawlPolicyGate,
)
from tarkka.application.robots_refresh import RobotsRefreshResult
from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult
from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.models import Artifact
from tarkka.domain.resource_acquisition import AcquisitionBudgetState, ResourceAcquisitionPolicy
from tarkka.domain.rights_access import RightsAccessDecision
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_NOW = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)
_TARGET = "https://example.org/article"
_ROBOTS = "https://example.org/robots.txt"


@dataclass
class _Cache:
    entry: RobotsCacheEntry | None = None

    def get(self, robots_uri: str) -> RobotsCacheEntry | None:
        assert robots_uri == _ROBOTS
        return self.entry

    def save(self, entry: RobotsCacheEntry) -> None:
        self.entry = entry


class _Checkpoints:
    def __init__(self) -> None:
        self.saved: list[TraversalCheckpoint] = []

    def save(self, checkpoint: TraversalCheckpoint) -> None:
        self.saved.append(checkpoint)

    def get(self, checkpoint_id: UUID) -> TraversalCheckpoint | None:
        return next(
            (item for item in reversed(self.saved) if item.checkpoint_id == checkpoint_id),
            None,
        )


class _Refresher:
    def __init__(self, entry: RobotsCacheEntry, *, requests_spent: int = 1) -> None:
        self.entry = entry
        self.requests_spent = requests_spent
        self.calls = 0

    def refresh(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        *,
        robots_uri: str,
        depth: int,
        now: datetime,
        seconds_since_last_request: float | None = None,
    ) -> RobotsRefreshResult:
        del policy, depth, now, seconds_since_last_request
        assert robots_uri == _ROBOTS
        self.calls += 1
        updated = replace(
            checkpoint,
            budget=replace(
                checkpoint.budget,
                requests_used=checkpoint.budget.requests_used + self.requests_spent,
            ),
        )
        return RobotsRefreshResult(
            checkpoint=updated,
            entry=self.entry,
            refresh_entry=self.entry,
        )


class _Acquirer:
    def __init__(self) -> None:
        self.calls: list[tuple[TraversalCheckpoint, ResourceAcquisitionPolicy, float | None]] = []

    def acquire(
        self,
        checkpoint: TraversalCheckpoint,
        target_id: UUID,
        policy: ResourceAcquisitionPolicy,
        *,
        request_uri: str | None = None,
        seconds_since_last_request: float | None = None,
    ) -> HttpAcquisitionResult:
        del request_uri
        self.calls.append((checkpoint, policy, seconds_since_last_request))
        target = next(item for item in checkpoint.targets if item.target_id == target_id)
        body = b"article"
        digest = hashlib.sha256(body).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
        artifact = Artifact(
            artifact_id=artifact_id,
            sha256=digest,
            size_bytes=len(body),
            media_type="text/html",
            storage_key=PurePosixPath("sha256", digest[:2], digest),
            source_uri=target.uri,
            acquired_at=_NOW,
        )
        snapshot = HttpResponseSnapshot(
            requested_uri=target.uri,
            final_uri=target.uri,
            status_code=200,
            observed_at=_NOW,
        )
        observation = snapshot.to_source_observation(native_artifact_id=artifact_id)
        return HttpAcquisitionResult(
            checkpoint=checkpoint,
            artifact=artifact,
            observation=observation,
            response=snapshot,
        )


def _checkpoint(*, requests_used: int = 0) -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(
        checkpoint_id=uuid4(),
        budget=AcquisitionBudgetState(requests_used=requests_used),
    ).enqueue(_TARGET, depth=1)
    return checkpoint, checkpoint.targets[0].target_id


def _policy(*, min_interval: float = 0.0, max_requests: int = 10) -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_requests=max_requests,
        min_request_interval_seconds=min_interval,
    )


def _rights(*, retrieval: bool = True) -> RightsAccessDecision:
    return RightsAccessDecision(
        target_uri=_TARGET,
        retrieval_allowed=retrieval,
        storage_allowed=True,
        analysis_allowed=True,
        redistribution_allowed=False,
        source_name="test-rights",
        policy_reference="rights:test",
    )


def _robots(
    content: str = "User-agent: *\nAllow: /\n",
    *,
    fetched_at: datetime = _NOW,
) -> RobotsCacheEntry:
    return RobotsCacheEntry(
        result=RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.SUCCESS,
            content=content,
            status_code=200,
        ),
        fetched_at=fetched_at,
        expires_at=fetched_at + timedelta(hours=6),
    )


def _coordinator(cache: _Cache, refresher: _Refresher, acquirer: _Acquirer) -> RecursiveCrawlCoordinator:
    return RecursiveCrawlCoordinator(
        policy_gate=RecursiveCrawlPolicyGate(
            robots_cache=cache,
            checkpoint_repository=_Checkpoints(),
        ),
        robots_refresher=refresher,
        target_acquirer=acquirer,
    )


def test_missing_cache_refreshes_then_hands_updated_budget_to_target_acquirer() -> None:
    checkpoint, target_id = _checkpoint()
    refreshed = _robots()
    refresher = _Refresher(refreshed)
    acquirer = _Acquirer()

    result = _coordinator(_Cache(), refresher, acquirer).acquire(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
    )

    assert result.gate.status is RecursiveCrawlGateStatus.READY
    assert result.robots_refresh is not None
    assert result.gate.robots_entry == refreshed
    assert result.gate.eligibility is not None
    assert result.gate.eligibility.rights.policy_reference == "rights:test"
    assert len(acquirer.calls) == 1
    acquired_checkpoint, _, interval = acquirer.calls[0]
    assert acquired_checkpoint.budget.requests_used == 1
    assert interval == 0.0


def test_refresh_request_does_not_satisfy_robots_crawl_delay() -> None:
    checkpoint, target_id = _checkpoint()
    refreshed = _robots("User-agent: TarkkaBot\nCrawl-delay: 5\nAllow: /\n")
    refresher = _Refresher(refreshed)
    acquirer = _Acquirer()

    result = _coordinator(_Cache(), refresher, acquirer).acquire(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
    )

    assert result.gate.status is RecursiveCrawlGateStatus.DEFERRED_PACING
    assert result.acquisition is None
    assert acquirer.calls == []


def test_refresh_budget_exhaustion_defers_content_target_without_spending_attempt() -> None:
    checkpoint, target_id = _checkpoint()
    refresher = _Refresher(_robots(), requests_spent=1)
    acquirer = _Acquirer()

    result = _coordinator(_Cache(), refresher, acquirer).acquire(
        checkpoint,
        target_id,
        _policy(max_requests=1),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
    )

    target = result.gate.checkpoint.targets[0]
    assert result.gate.status is RecursiveCrawlGateStatus.DEFERRED_BUDGET
    assert target.status is TraversalStatus.QUEUED
    assert target.attempts == 0
    assert acquirer.calls == []


def test_rights_denial_after_refresh_skips_before_target_acquisition() -> None:
    checkpoint, target_id = _checkpoint()
    refresher = _Refresher(_robots())
    acquirer = _Acquirer()

    result = _coordinator(_Cache(), refresher, acquirer).acquire(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(retrieval=False),
        now=_NOW,
    )

    assert result.gate.status is RecursiveCrawlGateStatus.SKIPPED
    assert result.gate.checkpoint.targets[0].attempts == 0
    assert acquirer.calls == []


def test_fresh_cache_avoids_refresh_and_uses_existing_target_acquirer() -> None:
    checkpoint, target_id = _checkpoint()
    cached = _robots(fetched_at=_NOW - timedelta(minutes=5))
    refresher = _Refresher(_robots())
    acquirer = _Acquirer()

    result = _coordinator(_Cache(cached), refresher, acquirer).acquire(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
    )

    assert result.gate.status is RecursiveCrawlGateStatus.READY
    assert result.robots_refresh is None
    assert result.gate.robots_entry == cached
    assert refresher.calls == 0
    assert len(acquirer.calls) == 1
