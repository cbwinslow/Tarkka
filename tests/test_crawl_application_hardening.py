from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from tarkka.application.crawl_eligibility import (
    CrawlEligibilityReason,
    combine_crawl_eligibility,
)
from tarkka.application.http_acquisition import HttpAcquisitionResult
from tarkka.application.http_policy_fetch import HttpPolicyFetchResult
from tarkka.application.recursive_crawl import (
    RecursiveCrawlGateResult,
    RecursiveCrawlGateStatus,
    RecursiveCrawlPolicyGate,
    RecursiveCrawlResult,
)
from tarkka.application.robots_refresh import RobotsRefreshResult, RobotsRefreshService
from tarkka.domain.crawl_access import (
    CrawlAccessDecision,
    CrawlAccessReason,
    RobotsFetchOutcome,
    RobotsFetchResult,
)
from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.models import Artifact
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.rights_access import RightsAccessDecision
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.domain.traversal import TraversalCheckpoint

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_NOW = datetime(2026, 8, 28, 4, 30, tzinfo=UTC)
_TARGET = "https://example.org/article"
_OTHER_TARGET = "https://other.example/article"
_ROBOTS = "https://example.org/robots.txt"
_OTHER_ROBOTS = "https://other.example/robots.txt"


def _empty_checkpoint() -> TraversalCheckpoint:
    return TraversalCheckpoint(uuid4())


def _queued_checkpoint() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = _empty_checkpoint().enqueue(_TARGET, depth=1)
    return checkpoint, checkpoint.targets[0].target_id


def _policy(*, domains: frozenset[str] = frozenset({"example.org"})) -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=domains,
        max_requests=10,
        min_request_interval_seconds=0.0,
    )


def _crawl(
    *,
    allowed: bool = True,
    target_uri: str = _TARGET,
) -> CrawlAccessDecision:
    return CrawlAccessDecision(
        target_uri=target_uri,
        robots_uri=_ROBOTS if target_uri == _TARGET else _OTHER_ROBOTS,
        product_token="TarkkaBot",
        allowed=allowed,
        reason=(CrawlAccessReason.ROBOTS_ALLOW if allowed else CrawlAccessReason.ROBOTS_DISALLOW),
        robots_outcome=RobotsFetchOutcome.SUCCESS,
        effective_min_request_interval_seconds=0.0,
    )


def _rights(
    *,
    retrieval: bool = True,
    target_uri: str = _TARGET,
) -> RightsAccessDecision:
    return RightsAccessDecision(
        target_uri=target_uri,
        retrieval_allowed=retrieval,
        storage_allowed=True,
        analysis_allowed=True,
        redistribution_allowed=False,
        source_name="test-rights",
    )


def _robots_entry(
    *,
    outcome: RobotsFetchOutcome = RobotsFetchOutcome.SUCCESS,
    robots_uri: str = _ROBOTS,
) -> RobotsCacheEntry:
    content = "User-agent: *\nAllow: /\n" if outcome is RobotsFetchOutcome.SUCCESS else None
    return RobotsCacheEntry(
        result=RobotsFetchResult(
            robots_uri=robots_uri,
            outcome=outcome,
            content=content,
            status_code=200 if outcome is RobotsFetchOutcome.SUCCESS else None,
        ),
        fetched_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
    )


def _ready_gate() -> RecursiveCrawlGateResult:
    checkpoint, target_id = _queued_checkpoint()
    crawl = _crawl()
    rights = _rights()
    return RecursiveCrawlGateResult(
        status=RecursiveCrawlGateStatus.READY,
        checkpoint=checkpoint,
        target_id=target_id,
        robots_uri=_ROBOTS,
        robots_entry=_robots_entry(),
        eligibility=combine_crawl_eligibility(crawl, rights),
        effective_policy=_policy(),
    )


def _http_result(status_code: int) -> HttpPolicyFetchResult:
    body = b"redirect"
    checkpoint = _empty_checkpoint()
    snapshot = HttpResponseSnapshot(
        requested_uri=_ROBOTS,
        final_uri=_ROBOTS,
        status_code=status_code,
        observed_at=_NOW,
    )
    digest = hashlib.sha256(body).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
    artifact = Artifact(
        artifact_id=artifact_id,
        sha256=digest,
        size_bytes=len(body),
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", digest[:2], digest),
        source_uri=_ROBOTS,
        acquired_at=_NOW,
    )
    return HttpPolicyFetchResult(
        checkpoint=checkpoint,
        artifact=artifact,
        observation=snapshot.to_source_observation(native_artifact_id=artifact_id),
        response=snapshot,
        body=body,
    )


def _acquisition_result(checkpoint: TraversalCheckpoint) -> HttpAcquisitionResult:
    body = b"article"
    digest = hashlib.sha256(body).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
    artifact = Artifact(
        artifact_id=artifact_id,
        sha256=digest,
        size_bytes=len(body),
        media_type="text/html",
        storage_key=PurePosixPath("sha256", digest[:2], digest),
        source_uri=_TARGET,
        acquired_at=_NOW,
    )
    snapshot = HttpResponseSnapshot(
        requested_uri=_TARGET,
        final_uri=_TARGET,
        status_code=200,
        observed_at=_NOW,
    )
    return HttpAcquisitionResult(
        checkpoint=checkpoint,
        artifact=artifact,
        observation=snapshot.to_source_observation(native_artifact_id=artifact_id),
        response=snapshot,
    )


class _Cache:
    def __init__(self, entry: RobotsCacheEntry | None = None) -> None:
        self.entry = entry

    def get(self, robots_uri: str) -> RobotsCacheEntry | None:
        del robots_uri
        return self.entry

    def save(self, entry: RobotsCacheEntry) -> None:
        self.entry = entry


class _NeverFetcher:
    def fetch(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        *,
        uri: str,
        depth: int,
        seconds_since_last_request: float | None = None,
    ) -> HttpPolicyFetchResult:
        del checkpoint, policy, uri, depth, seconds_since_last_request
        raise AssertionError("fetch must not run")


class _StaticFetcher:
    def __init__(self, result: HttpPolicyFetchResult) -> None:
        self.result = result

    def fetch(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        *,
        uri: str,
        depth: int,
        seconds_since_last_request: float | None = None,
    ) -> HttpPolicyFetchResult:
        del checkpoint, policy, uri, depth, seconds_since_last_request
        return self.result


class _FailingCheckpoints:
    def save(self, checkpoint: TraversalCheckpoint) -> None:
        del checkpoint
        raise OSError("disk unavailable")

    def get(self, checkpoint_id: UUID) -> TraversalCheckpoint | None:
        del checkpoint_id
        return None


def test_crawl_eligibility_decision_rejects_invalid_field_types() -> None:
    decision = combine_crawl_eligibility(_crawl(), _rights())

    with pytest.raises(ValueError, match="allowed must be boolean"):
        replace(decision, allowed=cast(bool, 1))
    with pytest.raises(ValueError, match="reason must be a CrawlEligibilityReason"):
        replace(decision, reason=cast(CrawlEligibilityReason, "allowed"))
    with pytest.raises(ValueError, match="crawl decision must be a CrawlAccessDecision"):
        replace(decision, crawl=cast(CrawlAccessDecision, object()))
    with pytest.raises(ValueError, match="rights decision must be a RightsAccessDecision"):
        replace(decision, rights=cast(RightsAccessDecision, object()))


def test_crawl_eligibility_decision_rejects_each_target_mismatch() -> None:
    decision = combine_crawl_eligibility(_crawl(), _rights())

    with pytest.raises(ValueError, match="same target URI"):
        replace(decision, crawl=_crawl(target_uri=_OTHER_TARGET))
    with pytest.raises(ValueError, match="same target URI"):
        replace(decision, rights=_rights(target_uri=_OTHER_TARGET))


def test_combine_crawl_eligibility_validates_inputs_and_precedence() -> None:
    with pytest.raises(ValueError, match="crawl decision must be a CrawlAccessDecision"):
        combine_crawl_eligibility(cast(CrawlAccessDecision, object()), _rights())
    with pytest.raises(ValueError, match="rights decision must be a RightsAccessDecision"):
        combine_crawl_eligibility(_crawl(), cast(RightsAccessDecision, object()))
    with pytest.raises(ValueError, match="same target URI"):
        combine_crawl_eligibility(_crawl(), _rights(target_uri=_OTHER_TARGET))

    robots_denied = combine_crawl_eligibility(_crawl(allowed=False), _rights(retrieval=False))
    rights_denied = combine_crawl_eligibility(_crawl(), _rights(retrieval=False))
    allowed = combine_crawl_eligibility(_crawl(), _rights())

    assert robots_denied.reason is CrawlEligibilityReason.ROBOTS_OR_TECHNICAL_DENY
    assert rights_denied.reason is CrawlEligibilityReason.RIGHTS_RETRIEVAL_DENY
    assert allowed.reason is CrawlEligibilityReason.ALLOWED


def test_robots_refresh_result_rejects_invalid_field_types_and_mismatch() -> None:
    checkpoint = _empty_checkpoint()
    entry = _robots_entry()
    result = RobotsRefreshResult(checkpoint=checkpoint, entry=entry, refresh_entry=entry)

    with pytest.raises(ValueError, match="checkpoint must be a TraversalCheckpoint"):
        replace(result, checkpoint=cast(TraversalCheckpoint, object()))
    with pytest.raises(ValueError, match="entry must be a RobotsCacheEntry"):
        replace(result, entry=cast(RobotsCacheEntry, object()))
    with pytest.raises(ValueError, match="attempt must be a RobotsCacheEntry"):
        replace(result, refresh_entry=cast(RobotsCacheEntry, object()))
    with pytest.raises(ValueError, match="stale-success flag must be boolean"):
        replace(result, used_stale_success=cast(bool, 1))
    with pytest.raises(ValueError, match="same canonical URI"):
        replace(result, refresh_entry=_robots_entry(robots_uri=_OTHER_ROBOTS))


def test_robots_refresh_result_validates_stale_success_contract() -> None:
    checkpoint = _empty_checkpoint()
    success = _robots_entry()
    unreachable = _robots_entry(outcome=RobotsFetchOutcome.UNREACHABLE)

    valid = RobotsRefreshResult(
        checkpoint=checkpoint,
        entry=success,
        refresh_entry=unreachable,
        used_stale_success=True,
    )
    assert valid.used_stale_success is True

    with pytest.raises(ValueError, match="must use a successful cached result"):
        RobotsRefreshResult(
            checkpoint=checkpoint,
            entry=unreachable,
            refresh_entry=unreachable,
            used_stale_success=True,
        )
    with pytest.raises(ValueError, match="requires an unreachable refresh"):
        RobotsRefreshResult(
            checkpoint=checkpoint,
            entry=success,
            refresh_entry=success,
            used_stale_success=True,
        )


def test_robots_refresh_rejects_invalid_time_before_fetching() -> None:
    service = RobotsRefreshService(policy_fetcher=_NeverFetcher(), robots_cache=_Cache())

    with pytest.raises(ValueError, match="time must be timezone-aware"):
        service.refresh(
            _empty_checkpoint(),
            _policy(),
            robots_uri=_ROBOTS,
            depth=0,
            now=datetime(2026, 8, 28, 4, 30),
        )
    with pytest.raises(ValueError, match="time must be timezone-aware"):
        service.refresh(
            _empty_checkpoint(),
            _policy(),
            robots_uri=_ROBOTS,
            depth=0,
            now=cast(datetime, "now"),
        )


def test_robots_refresh_unexpected_http_status_fails_closed() -> None:
    fetched = _http_result(302)
    cache = _Cache()

    result = RobotsRefreshService(
        policy_fetcher=_StaticFetcher(fetched),
        robots_cache=cache,
    ).refresh(
        fetched.checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=0,
        now=_NOW,
    )

    assert result.entry.result.outcome is RobotsFetchOutcome.UNREACHABLE
    assert result.entry.result.status_code is None
    assert cache.entry == result.entry


def test_recursive_gate_result_rejects_invalid_core_fields() -> None:
    gate = _ready_gate()

    with pytest.raises(ValueError, match="status must be a RecursiveCrawlGateStatus"):
        replace(gate, status=cast(RecursiveCrawlGateStatus, "ready"))
    with pytest.raises(ValueError, match="checkpoint must be a TraversalCheckpoint"):
        replace(gate, checkpoint=cast(TraversalCheckpoint, object()))
    with pytest.raises(ValueError, match="target_id must be a UUID"):
        replace(gate, target_id=cast(UUID, "bad"))
    with pytest.raises(ValueError, match="robots_entry must be a RobotsCacheEntry"):
        replace(gate, robots_entry=cast(RobotsCacheEntry, object()))
    with pytest.raises(ValueError, match="robots entry must match robots URI"):
        replace(gate, robots_uri=_OTHER_ROBOTS)


def test_recursive_ready_gate_requires_complete_allowed_evidence() -> None:
    gate = _ready_gate()

    with pytest.raises(ValueError, match="requires eligibility and policy"):
        replace(gate, eligibility=None)
    with pytest.raises(ValueError, match="requires eligibility and policy"):
        replace(gate, effective_policy=None)
    with pytest.raises(ValueError, match="requires allowed eligibility"):
        replace(gate, eligibility=combine_crawl_eligibility(_crawl(allowed=False), _rights()))
    with pytest.raises(ValueError, match="requires robots provenance"):
        replace(gate, robots_entry=None)


def test_recursive_non_ready_gate_contracts_are_consistent() -> None:
    gate = _ready_gate()
    checkpoint = gate.checkpoint
    target_id = gate.target_id

    with pytest.raises(ValueError, match="only a ready recursive crawl gate"):
        RecursiveCrawlGateResult(
            status=RecursiveCrawlGateStatus.SKIPPED,
            checkpoint=checkpoint,
            target_id=target_id,
            effective_policy=_policy(),
        )
    with pytest.raises(ValueError, match="requires a robots URI"):
        RecursiveCrawlGateResult(
            status=RecursiveCrawlGateStatus.ROBOTS_REFRESH_REQUIRED,
            checkpoint=checkpoint,
            target_id=target_id,
        )
    with pytest.raises(ValueError, match="must not claim final eligibility"):
        RecursiveCrawlGateResult(
            status=RecursiveCrawlGateStatus.ROBOTS_REFRESH_REQUIRED,
            checkpoint=checkpoint,
            target_id=target_id,
            robots_uri=_ROBOTS,
            eligibility=gate.eligibility,
        )


def test_recursive_result_rejects_invalid_component_types() -> None:
    gate = _ready_gate()

    with pytest.raises(ValueError, match="requires a gate result"):
        RecursiveCrawlResult(gate=cast(RecursiveCrawlGateResult, object()))
    with pytest.raises(ValueError, match="acquisition must be an HttpAcquisitionResult"):
        RecursiveCrawlResult(gate=gate, acquisition=cast(HttpAcquisitionResult, object()))
    with pytest.raises(ValueError, match="refresh must be a RobotsRefreshResult"):
        RecursiveCrawlResult(gate=gate, robots_refresh=cast(RobotsRefreshResult, object()))


def test_recursive_result_rejects_acquisition_from_non_ready_gate() -> None:
    ready = _ready_gate()
    skipped = RecursiveCrawlGateResult(
        status=RecursiveCrawlGateStatus.SKIPPED,
        checkpoint=ready.checkpoint,
        target_id=ready.target_id,
    )

    with pytest.raises(ValueError, match="only a ready recursive crawl gate"):
        RecursiveCrawlResult(
            gate=skipped,
            acquisition=_acquisition_result(ready.checkpoint),
        )


def test_recursive_refreshed_entry_must_match_target_authority() -> None:
    checkpoint, target_id = _queued_checkpoint()
    gate = RecursiveCrawlPolicyGate(
        robots_cache=_Cache(),
        checkpoint_repository=_FailingCheckpoints(),
    )

    with pytest.raises(ValueError, match="does not belong"):
        gate.evaluate_refreshed_entry(
            checkpoint,
            target_id,
            _policy(),
            product_token="TarkkaBot",
            rights=_rights(),
            entry=_robots_entry(robots_uri=_OTHER_ROBOTS),
        )


def test_recursive_policy_persistence_failure_is_stable_runtime_error() -> None:
    checkpoint, target_id = _queued_checkpoint()
    gate = RecursiveCrawlPolicyGate(
        robots_cache=_Cache(),
        checkpoint_repository=_FailingCheckpoints(),
    )

    with pytest.raises(
        RuntimeError,
        match="unable to persist recursive crawl policy decision",
    ) as exc:
        gate.evaluate(
            checkpoint,
            target_id,
            _policy(domains=frozenset({"other.example"})),
            product_token="TarkkaBot",
            rights=_rights(),
            now=_NOW,
        )

    assert isinstance(exc.value.__cause__, OSError)


def test_recursive_gate_validates_checkpoint_target_and_rights_boundaries() -> None:
    checkpoint, target_id = _queued_checkpoint()
    gate = RecursiveCrawlPolicyGate(
        robots_cache=_Cache(),
        checkpoint_repository=_FailingCheckpoints(),
    )

    with pytest.raises(ValueError, match="checkpoint must be a TraversalCheckpoint"):
        gate.evaluate(
            cast(TraversalCheckpoint, object()),
            target_id,
            _policy(),
            product_token="TarkkaBot",
            rights=_rights(),
            now=_NOW,
        )
    with pytest.raises(ValueError, match="target_id must be a UUID"):
        gate.evaluate(
            checkpoint,
            cast(UUID, "bad"),
            _policy(),
            product_token="TarkkaBot",
            rights=_rights(),
            now=_NOW,
        )
    with pytest.raises(ValueError, match="target does not exist"):
        gate.evaluate(
            checkpoint,
            uuid4(),
            _policy(),
            product_token="TarkkaBot",
            rights=_rights(),
            now=_NOW,
        )
    with pytest.raises(ValueError, match="rights must be a RightsAccessDecision"):
        gate.evaluate(
            checkpoint,
            target_id,
            _policy(),
            product_token="TarkkaBot",
            rights=cast(RightsAccessDecision, object()),
            now=_NOW,
        )

    skipped = checkpoint.skip(target_id, reason="already handled")
    with pytest.raises(ValueError, match="requires a queued target"):
        gate.evaluate(
            skipped,
            target_id,
            _policy(),
            product_token="TarkkaBot",
            rights=_rights(),
            now=_NOW,
        )
