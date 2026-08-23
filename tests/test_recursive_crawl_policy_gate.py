from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tarkka.application.recursive_crawl import (
    RecursiveCrawlGateStatus,
    RecursiveCrawlPolicyGate,
)
from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult
from tarkka.domain.resource_acquisition import AcquisitionBudgetState, ResourceAcquisitionPolicy
from tarkka.domain.rights_access import RightsAccessDecision
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_NOW = datetime(2026, 8, 23, 20, 0, tzinfo=UTC)
_TARGET = "https://example.org/article"
_ROBOTS = "https://example.org/robots.txt"


@dataclass
class _Cache:
    entry: RobotsCacheEntry | None
    requested_uri: str | None = None

    def get(self, robots_uri: str) -> RobotsCacheEntry | None:
        self.requested_uri = robots_uri
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


def _checkpoint(*, requests_used: int = 0) -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(
        checkpoint_id=uuid4(),
        budget=AcquisitionBudgetState(requests_used=requests_used),
    ).enqueue(_TARGET, depth=1)
    return checkpoint, checkpoint.targets[0].target_id


def _policy(*, domains: frozenset[str] = frozenset({"example.org"})) -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=domains,
        max_requests=10,
        min_request_interval_seconds=0.0,
    )


def _rights(*, retrieval: bool = True) -> RightsAccessDecision:
    return RightsAccessDecision(
        target_uri=_TARGET,
        retrieval_allowed=retrieval,
        storage_allowed=True,
        analysis_allowed=True,
        redistribution_allowed=False,
        source_name="test-rights",
    )


def _robots(
    content: str = "User-agent: *\nAllow: /\n",
    *,
    fetched_at: datetime = _NOW - timedelta(minutes=5),
    expires_at: datetime = _NOW + timedelta(hours=1),
) -> RobotsCacheEntry:
    return RobotsCacheEntry(
        result=RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.SUCCESS,
            content=content,
            status_code=200,
        ),
        fetched_at=fetched_at,
        expires_at=expires_at,
    )


def _gate(cache: _Cache, repository: _Checkpoints) -> RecursiveCrawlPolicyGate:
    return RecursiveCrawlPolicyGate(
        robots_cache=cache,
        checkpoint_repository=repository,
    )


def test_technical_policy_denial_skips_without_spending_target_attempt() -> None:
    checkpoint, target_id = _checkpoint()
    repository = _Checkpoints()
    cache = _Cache(_robots())

    result = _gate(cache, repository).evaluate(
        checkpoint,
        target_id,
        _policy(domains=frozenset({"other.example"})),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
    )

    target = result.checkpoint.targets[0]
    assert result.status is RecursiveCrawlGateStatus.SKIPPED
    assert target.status is TraversalStatus.SKIPPED
    assert target.attempts == 0
    assert result.checkpoint.budget.requests_used == 0
    assert len(repository.saved) == 1
    assert cache.requested_uri is None


def test_exhausted_request_budget_defers_without_mutating_checkpoint() -> None:
    checkpoint, target_id = _checkpoint(requests_used=10)
    repository = _Checkpoints()

    result = _gate(_Cache(_robots()), repository).evaluate(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
    )

    assert result.status is RecursiveCrawlGateStatus.DEFERRED_BUDGET
    assert result.checkpoint == checkpoint
    assert repository.saved == []


def test_missing_or_stale_robots_cache_requests_refresh() -> None:
    for entry in (
        None,
        _robots(
            fetched_at=_NOW - timedelta(hours=2),
            expires_at=_NOW - timedelta(hours=1),
        ),
    ):
        checkpoint, target_id = _checkpoint()
        result = _gate(_Cache(entry), _Checkpoints()).evaluate(
            checkpoint,
            target_id,
            _policy(),
            product_token="TarkkaBot",
            rights=_rights(),
            now=_NOW,
        )

        assert result.status is RecursiveCrawlGateStatus.ROBOTS_REFRESH_REQUIRED
        assert result.robots_uri == _ROBOTS
        assert result.eligibility is None
        assert result.checkpoint == checkpoint


def test_robots_denial_skips_target_without_spending_attempt() -> None:
    checkpoint, target_id = _checkpoint()
    repository = _Checkpoints()

    result = _gate(
        _Cache(_robots("User-agent: *\nDisallow: /article\n")),
        repository,
    ).evaluate(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
    )

    target = result.checkpoint.targets[0]
    assert result.status is RecursiveCrawlGateStatus.SKIPPED
    assert result.eligibility is not None
    assert result.eligibility.allowed is False
    assert target.status is TraversalStatus.SKIPPED
    assert target.attempts == 0
    assert result.checkpoint.budget.requests_used == 0


def test_rights_retrieval_denial_skips_target() -> None:
    checkpoint, target_id = _checkpoint()

    result = _gate(_Cache(_robots()), _Checkpoints()).evaluate(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(retrieval=False),
        now=_NOW,
    )

    assert result.status is RecursiveCrawlGateStatus.SKIPPED
    assert result.eligibility is not None
    assert result.eligibility.allowed is False
    assert result.checkpoint.targets[0].status is TraversalStatus.SKIPPED


def test_allowed_target_exposes_tightened_effective_policy() -> None:
    checkpoint, target_id = _checkpoint()
    robots = _robots("User-agent: TarkkaBot\nCrawl-delay: 5\nAllow: /\n")

    result = _gate(_Cache(robots), _Checkpoints()).evaluate(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
    )

    assert result.status is RecursiveCrawlGateStatus.READY
    assert result.eligibility is not None and result.eligibility.allowed is True
    assert result.effective_policy is not None
    assert result.effective_policy.min_request_interval_seconds == 5.0
    assert result.checkpoint.targets[0].status is TraversalStatus.QUEUED


def test_crawl_delay_defers_when_previous_request_is_too_recent() -> None:
    checkpoint, target_id = _checkpoint(requests_used=1)
    robots = _robots("User-agent: TarkkaBot\nCrawl-delay: 5\nAllow: /\n")

    result = _gate(_Cache(robots), _Checkpoints()).evaluate(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
        seconds_since_last_request=2.0,
    )

    assert result.status is RecursiveCrawlGateStatus.DEFERRED_PACING
    assert result.checkpoint == checkpoint
    assert result.eligibility is not None and result.eligibility.allowed is True


def test_crawl_delay_allows_target_after_required_interval() -> None:
    checkpoint, target_id = _checkpoint(requests_used=1)
    robots = _robots("User-agent: TarkkaBot\nCrawl-delay: 5\nAllow: /\n")

    result = _gate(_Cache(robots), _Checkpoints()).evaluate(
        checkpoint,
        target_id,
        _policy(),
        product_token="TarkkaBot",
        rights=_rights(),
        now=_NOW,
        seconds_since_last_request=5.0,
    )

    assert result.status is RecursiveCrawlGateStatus.READY
    assert result.effective_policy is not None
    assert result.effective_policy.min_request_interval_seconds == 5.0
