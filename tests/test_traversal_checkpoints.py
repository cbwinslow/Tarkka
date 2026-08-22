from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000444")
_LINK_A = UUID("00000000-0000-0000-0000-000000000445")
_LINK_B = UUID("00000000-0000-0000-0000-000000000446")


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 2,
        "max_requests": 4,
        "max_bytes": 1000,
        "max_retries": 1,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def test_enqueue_normalizes_deduplicates_and_preserves_multi_source_provenance() -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID)
    checkpoint = checkpoint.enqueue(
        "HTTPS://EXAMPLE.org:443/paper?token=secret",
        depth=2,
        discovery_link_id=_LINK_A,
    )
    parent_id = checkpoint.targets[0].target_id
    checkpoint = checkpoint.enqueue(
        "https://example.org/paper?token=different",
        depth=1,
        discovery_link_id=_LINK_B,
        parent_target_id=parent_id,
    )

    assert len(checkpoint.targets) == 1
    target = checkpoint.targets[0]
    assert target.uri == "https://example.org/paper?token=%5BREDACTED%5D"
    assert target.depth == 1
    assert target.discovery_link_ids == (_LINK_A, _LINK_B)
    assert target.parent_target_ids == (parent_id,)


def test_next_eligible_reuses_scope_depth_and_request_budget_policy() -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID)
    checkpoint = checkpoint.enqueue("https://outside.test/no", depth=0)
    checkpoint = checkpoint.enqueue("https://example.org/too-deep", depth=3)
    checkpoint = checkpoint.enqueue("https://example.org/eligible", depth=1)

    target = checkpoint.next_eligible(_policy())

    assert target is not None
    assert target.uri == "https://example.org/eligible"


def test_start_complete_and_retry_transitions_account_for_budget() -> None:
    policy = _policy()
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/a",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id

    checkpoint = checkpoint.start(target_id, policy)
    assert checkpoint.targets[0].status is TraversalStatus.IN_PROGRESS
    assert checkpoint.targets[0].attempts == 1
    assert checkpoint.budget.requests_used == 1

    checkpoint = checkpoint.fail(target_id, error="timeout", elapsed_seconds=1.5)
    assert checkpoint.targets[0].status is TraversalStatus.FAILED
    assert checkpoint.targets[0].last_error == "timeout"

    checkpoint = checkpoint.requeue_failed(target_id, policy)
    checkpoint = checkpoint.start(target_id, policy)
    checkpoint = checkpoint.complete(target_id, bytes_acquired=120, elapsed_seconds=2.5)

    target = checkpoint.targets[0]
    assert target.status is TraversalStatus.COMPLETED
    assert target.attempts == 2
    assert target.bytes_acquired == 120
    assert checkpoint.budget.requests_used == 2
    assert checkpoint.budget.bytes_used == 120
    assert checkpoint.budget.elapsed_seconds == 2.5


def test_retry_budget_and_rate_limit_fail_closed() -> None:
    policy = _policy(max_retries=0, min_request_interval_seconds=2.0)
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/a",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id
    checkpoint = checkpoint.start(target_id, policy)
    checkpoint = checkpoint.fail(target_id, error="boom", elapsed_seconds=0.5)

    with pytest.raises(ValueError, match="retry budget"):
        checkpoint.requeue_failed(target_id, policy)

    second = checkpoint.enqueue("https://example.org/b", depth=0)
    assert second.next_eligible(policy, seconds_since_last_request=1.0) is None
    assert second.next_eligible(policy, seconds_since_last_request=2.0) is not None


def test_skip_does_not_consume_request_budget() -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/skip",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id

    checkpoint = checkpoint.skip(target_id, reason="robots denied")

    assert checkpoint.targets[0].status is TraversalStatus.SKIPPED
    assert checkpoint.targets[0].last_error == "robots denied"
    assert checkpoint.budget.requests_used == 0


def test_json_checkpoint_repository_round_trips_evolving_state(tmp_path: Path) -> None:
    repository = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    policy = _policy()
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID)
    checkpoint = checkpoint.enqueue(
        "https://example.org/root",
        depth=0,
        discovery_link_id=_LINK_A,
    )
    root_id = checkpoint.targets[0].target_id
    checkpoint = checkpoint.start(root_id, policy)
    checkpoint = checkpoint.complete(root_id, bytes_acquired=50, elapsed_seconds=1.0)
    checkpoint = checkpoint.enqueue(
        "https://example.org/child",
        depth=1,
        discovery_link_id=_LINK_B,
        parent_target_id=root_id,
    )

    repository.save(checkpoint)
    restored = repository.get(_CHECKPOINT_ID)

    assert restored == checkpoint
    assert restored is not None
    assert restored.next_eligible(policy) is not None
    assert restored.next_eligible(policy).uri == "https://example.org/child"  # type: ignore[union-attr]


def test_checkpoint_rejects_invalid_transitions_and_non_monotonic_time() -> None:
    policy = _policy()
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/a",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id

    with pytest.raises(ValueError, match="in-progress"):
        checkpoint.complete(target_id, bytes_acquired=1, elapsed_seconds=1.0)

    checkpoint = checkpoint.start(target_id, policy)
    checkpoint = checkpoint.fail(target_id, error="fail", elapsed_seconds=2.0)
    checkpoint = checkpoint.requeue_failed(target_id, policy)
    checkpoint = checkpoint.start(target_id, policy)
    with pytest.raises(ValueError, match="must not move backwards"):
        checkpoint.complete(target_id, bytes_acquired=1, elapsed_seconds=1.0)
