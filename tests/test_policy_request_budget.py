from __future__ import annotations

from uuid import uuid4

import pytest

from tarkka.domain.policy_requests import (
    begin_policy_request,
    record_policy_failure,
    record_policy_response,
)
from tarkka.domain.resource_acquisition import AcquisitionBudgetState, ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 2,
        "max_requests": 3,
        "max_bytes": 100,
        "max_elapsed_seconds": 30.0,
        "min_request_interval_seconds": 2.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def _checkpoint() -> tuple[TraversalCheckpoint, object]:
    checkpoint = TraversalCheckpoint(uuid4()).enqueue(
        "https://example.org/article",
        depth=1,
    )
    return checkpoint, checkpoint.targets[0].target_id


def test_policy_request_charges_request_without_starting_frontier_target() -> None:
    checkpoint, target_id = _checkpoint()

    charged = begin_policy_request(
        checkpoint,
        _policy(min_request_interval_seconds=0.0),
        depth=1,
    )

    target = next(item for item in charged.targets if item.target_id == target_id)
    assert charged.budget.requests_used == 1
    assert charged.budget.bytes_used == 0
    assert target.status is TraversalStatus.QUEUED
    assert target.attempts == 0


def test_policy_request_respects_shared_request_budget() -> None:
    checkpoint, _ = _checkpoint()
    checkpoint = TraversalCheckpoint(
        checkpoint_id=checkpoint.checkpoint_id,
        targets=checkpoint.targets,
        budget=AcquisitionBudgetState(requests_used=3),
    )

    with pytest.raises(ValueError, match="exceeds the acquisition budget"):
        begin_policy_request(checkpoint, _policy(), depth=1)


def test_policy_request_respects_shared_pacing() -> None:
    checkpoint, _ = _checkpoint()
    checkpoint = TraversalCheckpoint(
        checkpoint_id=checkpoint.checkpoint_id,
        targets=checkpoint.targets,
        budget=AcquisitionBudgetState(requests_used=1),
    )

    with pytest.raises(ValueError, match="exceeds the acquisition budget"):
        begin_policy_request(
            checkpoint,
            _policy(),
            depth=1,
            seconds_since_last_request=1.0,
        )


def test_policy_response_charges_bytes_and_monotonic_elapsed_time() -> None:
    checkpoint, _ = _checkpoint()
    charged = begin_policy_request(
        checkpoint,
        _policy(min_request_interval_seconds=0.0),
        depth=1,
    )

    updated = record_policy_response(
        charged,
        bytes_acquired=23,
        elapsed_seconds=4.5,
    )

    assert updated.budget.requests_used == 1
    assert updated.budget.bytes_used == 23
    assert updated.budget.elapsed_seconds == 4.5


def test_policy_failure_preserves_spent_request_and_updates_elapsed_time() -> None:
    checkpoint, _ = _checkpoint()
    charged = begin_policy_request(
        checkpoint,
        _policy(min_request_interval_seconds=0.0),
        depth=1,
    )

    failed = record_policy_failure(charged, elapsed_seconds=3.0)

    assert failed.budget.requests_used == 1
    assert failed.budget.bytes_used == 0
    assert failed.budget.elapsed_seconds == 3.0


def test_policy_response_rejects_elapsed_time_rollback() -> None:
    checkpoint, _ = _checkpoint()
    checkpoint = TraversalCheckpoint(
        checkpoint_id=checkpoint.checkpoint_id,
        targets=checkpoint.targets,
        budget=AcquisitionBudgetState(elapsed_seconds=5.0),
    )

    with pytest.raises(ValueError, match="finite and monotonic"):
        record_policy_response(checkpoint, bytes_acquired=1, elapsed_seconds=4.9)
