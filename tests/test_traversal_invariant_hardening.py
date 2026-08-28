from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from tarkka.domain.resource_acquisition import AcquisitionBudgetState, ResourceAcquisitionPolicy
from tarkka.domain.traversal import (
    TraversalCheckpoint,
    TraversalStatus,
    TraversalTarget,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_URI = "https://example.org/article"
_SHA256 = "a" * 64


def _policy(**overrides: Any) -> ResourceAcquisitionPolicy:
    values: dict[str, Any] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 3,
        "max_requests": 10,
        "max_bytes": 10_000,
        "max_retries": 2,
        "max_elapsed_seconds": 100.0,
        "min_request_interval_seconds": 0.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)


def _target(**overrides: Any) -> TraversalTarget:
    values: dict[str, Any] = {
        "target_id": uuid4(),
        "uri": _URI,
        "depth": 0,
    }
    values.update(overrides)
    return TraversalTarget(**values)


def _checkpoint(uri: str = _URI) -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(uuid4()).enqueue(uri, depth=0)
    return checkpoint, checkpoint.targets[0].target_id


def _started_checkpoint(
    *,
    policy: ResourceAcquisitionPolicy | None = None,
) -> tuple[TraversalCheckpoint, UUID, ResourceAcquisitionPolicy]:
    effective_policy = policy or _policy()
    checkpoint, target_id = _checkpoint()
    return checkpoint.start(target_id, effective_policy), target_id, effective_policy


def _finalizing_checkpoint() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint, target_id, _ = _started_checkpoint()
    checkpoint = checkpoint.begin_finalization(
        target_id,
        artifact_sha256=_SHA256,
        observation_id=uuid4(),
        elapsed_seconds=1.0,
    )
    return checkpoint, target_id


def test_traversal_target_rejects_invalid_identity_and_scalar_state() -> None:
    with pytest.raises(ValueError, match="target ID must be a UUID"):
        _target(target_id="not-a-uuid")
    with pytest.raises(ValueError, match="status must be a TraversalStatus"):
        _target(status="queued")

    for field_name in ("attempts", "bytes_acquired"):
        for value in (-1, True, 1.5):
            with pytest.raises(ValueError, match="non-negative integer"):
                _target(**{field_name: value})

    for depth in (-1, True, 1.5):
        with pytest.raises(ValueError, match="depth must be a non-negative integer"):
            _target(depth=depth)


def test_traversal_target_validates_error_state_contract() -> None:
    with pytest.raises(ValueError, match="last_error must be non-blank"):
        _target(status=TraversalStatus.FAILED, attempts=1, last_error=" ")
    with pytest.raises(ValueError, match="require a reason"):
        _target(status=TraversalStatus.FAILED, attempts=1)
    with pytest.raises(ValueError, match="require a reason"):
        _target(status=TraversalStatus.SKIPPED)
    with pytest.raises(ValueError, match="only failed or skipped"):
        _target(last_error="unexpected")


def test_attempted_traversal_states_require_attempt_count() -> None:
    for status in (
        TraversalStatus.IN_PROGRESS,
        TraversalStatus.FINALIZING,
        TraversalStatus.COMPLETED,
        TraversalStatus.FAILED,
    ):
        kwargs: dict[str, Any] = {"status": status}
        if status is TraversalStatus.FAILED:
            kwargs["last_error"] = "failed"
        if status is TraversalStatus.FINALIZING:
            kwargs["final_artifact_sha256"] = _SHA256
            kwargs["final_observation_id"] = uuid4()
        with pytest.raises(ValueError, match="at least one attempt"):
            _target(**kwargs)


def test_traversal_target_validates_finalization_identity_pair() -> None:
    with pytest.raises(ValueError, match="provided together"):
        _target(final_artifact_sha256=_SHA256)
    with pytest.raises(ValueError, match="provided together"):
        _target(final_observation_id=uuid4())
    with pytest.raises(ValueError, match="require output identifiers"):
        _target(status=TraversalStatus.FINALIZING, attempts=1)
    with pytest.raises(ValueError, match="only finalizing or completed"):
        _target(
            final_artifact_sha256=_SHA256,
            final_observation_id=uuid4(),
        )
    with pytest.raises(ValueError, match="SHA-256"):
        _target(
            status=TraversalStatus.FINALIZING,
            attempts=1,
            final_artifact_sha256="bad",
            final_observation_id=uuid4(),
        )
    with pytest.raises(ValueError, match="final observation ID must be a UUID"):
        _target(
            status=TraversalStatus.FINALIZING,
            attempts=1,
            final_artifact_sha256=_SHA256,
            final_observation_id="bad",
        )


def test_traversal_target_validates_and_deduplicates_provenance_ids() -> None:
    discovery_id = uuid4()
    parent_id = uuid4()
    target = _target(
        discovery_link_ids=(discovery_id, discovery_id),
        parent_target_ids=(parent_id, parent_id),
    )
    assert target.discovery_link_ids == (discovery_id,)
    assert target.parent_target_ids == (parent_id,)

    with pytest.raises(ValueError, match="provenance IDs must be UUID"):
        _target(discovery_link_ids=cast(tuple[UUID, ...], ("bad",)))

    target_id = uuid4()
    with pytest.raises(ValueError, match="cannot be its own parent"):
        _target(target_id=target_id, parent_target_ids=(target_id,))


def test_traversal_checkpoint_validates_identity_targets_and_budget() -> None:
    with pytest.raises(ValueError, match="checkpoint ID must be a UUID"):
        TraversalCheckpoint(cast(UUID, "bad"))
    with pytest.raises(ValueError, match="targets must be TraversalTarget"):
        TraversalCheckpoint(uuid4(), targets=cast(tuple[TraversalTarget, ...], (object(),)))
    with pytest.raises(ValueError, match="target IDs must be unique"):
        shared_id = uuid4()
        TraversalCheckpoint(
            uuid4(),
            targets=(
                _target(target_id=shared_id, uri="https://example.org/a"),
                _target(target_id=shared_id, uri="https://example.org/b"),
            ),
        )
    with pytest.raises(ValueError, match="target URIs must be unique"):
        TraversalCheckpoint(
            uuid4(),
            targets=(_target(uri=_URI), _target(uri=_URI)),
        )
    with pytest.raises(ValueError, match="parent targets must exist"):
        TraversalCheckpoint(uuid4(), targets=(_target(parent_target_ids=(uuid4(),)),))
    with pytest.raises(ValueError, match="budget must be AcquisitionBudgetState"):
        TraversalCheckpoint(uuid4(), budget=cast(AcquisitionBudgetState, object()))


def test_enqueue_validates_depth_and_optional_provenance_ids() -> None:
    checkpoint = TraversalCheckpoint(uuid4())
    with pytest.raises(ValueError, match="depth must be a non-negative integer"):
        checkpoint.enqueue(_URI, depth=-1)
    with pytest.raises(ValueError, match="discovery link ID"):
        checkpoint.enqueue(_URI, depth=0, discovery_link_id=cast(UUID, "bad"))
    with pytest.raises(ValueError, match="parent target ID"):
        checkpoint.enqueue(_URI, depth=0, parent_target_id=cast(UUID, "bad"))
    with pytest.raises(ValueError, match="parent traversal target must already exist"):
        checkpoint.enqueue(_URI, depth=0, parent_target_id=uuid4())


def test_enqueue_rejects_existing_and_new_self_parent_paths() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="cannot be its own parent"):
        checkpoint.enqueue(_URI, depth=0, parent_target_id=target_id)

    checkpoint_id = uuid4()
    child_uri = "https://example.org/child"
    probe = TraversalCheckpoint(checkpoint_id).enqueue(child_uri, depth=0)
    deterministic_child_id = probe.targets[0].target_id
    synthetic_parent = _target(
        target_id=deterministic_child_id,
        uri="https://example.org/synthetic-parent",
    )
    checkpoint = TraversalCheckpoint(checkpoint_id, targets=(synthetic_parent,))
    with pytest.raises(ValueError, match="cannot be its own parent"):
        checkpoint.enqueue(
            child_uri,
            depth=0,
            parent_target_id=deterministic_child_id,
        )


def test_enqueue_deduplicates_provenance_and_only_lowers_queued_depth() -> None:
    checkpoint, parent_id = _checkpoint("https://example.org/parent")
    discovery_id = uuid4()
    child_uri = "https://example.org/child"
    checkpoint = checkpoint.enqueue(
        child_uri,
        depth=2,
        discovery_link_id=discovery_id,
        parent_target_id=parent_id,
    )
    checkpoint = checkpoint.enqueue(
        child_uri,
        depth=1,
        discovery_link_id=discovery_id,
        parent_target_id=parent_id,
    )
    child = next(target for target in checkpoint.targets if target.uri == child_uri)
    assert child.depth == 1
    assert child.discovery_link_ids == (discovery_id,)
    assert child.parent_target_ids == (parent_id,)

    checkpoint = checkpoint.start(child.target_id, _policy())
    checkpoint = checkpoint.enqueue(child_uri, depth=0)
    child = next(target for target in checkpoint.targets if target.uri == child_uri)
    assert child.depth == 1


def test_next_eligible_skips_nonqueued_disallowed_and_budget_blocked_targets() -> None:
    skipped = _target(status=TraversalStatus.SKIPPED, last_error="skip")
    queued = _target(uri="https://example.org/eligible")
    checkpoint = TraversalCheckpoint(uuid4(), targets=(skipped, queued))
    assert checkpoint.next_eligible(_policy()) == queued

    disallowed = _policy(allowed_domains=frozenset({"other.org"}))
    assert checkpoint.next_eligible(disallowed) is None

    exhausted = _policy(max_requests=0)
    assert checkpoint.next_eligible(exhausted) is None

    with pytest.raises(ValueError, match="traversal policy"):
        checkpoint.next_eligible(cast(ResourceAcquisitionPolicy, object()))


def test_start_rejects_wrong_state_disallowed_uri_and_exhausted_budget() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="not eligible"):
        checkpoint.start(target_id, _policy(allowed_domains=frozenset({"other.org"})))
    with pytest.raises(ValueError, match="not eligible"):
        checkpoint.start(target_id, _policy(max_requests=0))
    with pytest.raises(ValueError, match="traversal policy"):
        checkpoint.start(target_id, cast(ResourceAcquisitionPolicy, object()))

    started = checkpoint.start(target_id, _policy())
    with pytest.raises(ValueError, match="only queued"):
        started.start(target_id, _policy())


def test_target_lookup_rejects_invalid_or_unknown_ids() -> None:
    checkpoint, _ = _checkpoint()
    with pytest.raises(ValueError, match="target ID must be a UUID"):
        checkpoint.start(cast(UUID, "bad"), _policy())
    with pytest.raises(ValueError, match="does not exist"):
        checkpoint.start(uuid4(), _policy())


def test_followup_request_requires_in_progress_and_available_budget() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="in-progress"):
        checkpoint.record_followup_request(target_id, _policy())
    with pytest.raises(ValueError, match="traversal policy"):
        checkpoint.record_followup_request(
            target_id,
            cast(ResourceAcquisitionPolicy, object()),
        )

    started = checkpoint.start(target_id, _policy())
    with pytest.raises(ValueError, match="exceeds the acquisition budget"):
        started.record_followup_request(target_id, _policy(max_requests=1))

    updated = started.record_followup_request(target_id, _policy(), expected_bytes=5)
    assert updated.budget.requests_used == 2
    assert updated.targets[0].attempts == 1


def test_response_byte_accounting_validates_state_and_count() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="in-progress"):
        checkpoint.record_response_bytes(target_id, bytes_acquired=1)

    started = checkpoint.start(target_id, _policy())
    for value in (-1, True, 1.5):
        with pytest.raises(ValueError, match="non-negative integer"):
            started.record_response_bytes(target_id, bytes_acquired=cast(int, value))

    updated = started.record_response_bytes(target_id, bytes_acquired=7)
    assert updated.targets[0].bytes_acquired == 7
    assert updated.budget.bytes_used == 7


def test_begin_finalization_validates_state_identity_and_elapsed() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="only in-progress"):
        checkpoint.begin_finalization(
            target_id,
            artifact_sha256=_SHA256,
            observation_id=uuid4(),
            elapsed_seconds=0.0,
        )

    started = checkpoint.start(target_id, _policy())
    with pytest.raises(ValueError, match="SHA-256"):
        started.begin_finalization(
            target_id,
            artifact_sha256="bad",
            observation_id=uuid4(),
            elapsed_seconds=0.0,
        )
    with pytest.raises(ValueError, match="final observation ID"):
        started.begin_finalization(
            target_id,
            artifact_sha256=_SHA256,
            observation_id=cast(UUID, "bad"),
            elapsed_seconds=0.0,
        )

    advanced = started.complete(target_id, bytes_acquired=0, elapsed_seconds=2.0)
    with pytest.raises(ValueError, match="only in-progress"):
        advanced.begin_finalization(
            target_id,
            artifact_sha256=_SHA256,
            observation_id=uuid4(),
            elapsed_seconds=1.0,
        )

    started = TraversalCheckpoint(
        started.checkpoint_id,
        targets=started.targets,
        budget=AcquisitionBudgetState(requests_used=1, elapsed_seconds=2.0),
    )
    with pytest.raises(ValueError, match="must not move backwards"):
        started.begin_finalization(
            target_id,
            artifact_sha256=_SHA256,
            observation_id=uuid4(),
            elapsed_seconds=1.0,
        )


def test_complete_finalization_requires_finalizing_state_and_monotonic_elapsed() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="only finalizing"):
        checkpoint.complete_finalization(target_id, elapsed_seconds=0.0)

    finalizing, target_id = _finalizing_checkpoint()
    with pytest.raises(ValueError, match="must not move backwards"):
        finalizing.complete_finalization(target_id, elapsed_seconds=0.5)

    completed = finalizing.complete_finalization(target_id, elapsed_seconds=2.0)
    assert completed.targets[0].status is TraversalStatus.COMPLETED
    assert completed.targets[0].final_artifact_sha256 == _SHA256


def test_complete_validates_state_bytes_and_elapsed() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="only in-progress"):
        checkpoint.complete(target_id, bytes_acquired=0, elapsed_seconds=0.0)

    started = checkpoint.start(target_id, _policy())
    with pytest.raises(ValueError, match="non-negative integer"):
        started.complete(target_id, bytes_acquired=-1, elapsed_seconds=0.0)

    started = TraversalCheckpoint(
        started.checkpoint_id,
        targets=started.targets,
        budget=AcquisitionBudgetState(requests_used=1, elapsed_seconds=2.0),
    )
    with pytest.raises(ValueError, match="must not move backwards"):
        started.complete(target_id, bytes_acquired=0, elapsed_seconds=1.0)


def test_fail_validates_state_reason_bytes_and_elapsed() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="only in-progress"):
        checkpoint.fail(target_id, error="failed", elapsed_seconds=0.0)

    started = checkpoint.start(target_id, _policy())
    with pytest.raises(ValueError, match="non-blank string"):
        started.fail(target_id, error=" ", elapsed_seconds=0.0)
    with pytest.raises(ValueError, match="non-negative integer"):
        started.fail(target_id, error="failed", elapsed_seconds=0.0, bytes_acquired=-1)

    started = TraversalCheckpoint(
        started.checkpoint_id,
        targets=started.targets,
        budget=AcquisitionBudgetState(requests_used=1, elapsed_seconds=2.0),
    )
    with pytest.raises(ValueError, match="must not move backwards"):
        started.fail(target_id, error="failed", elapsed_seconds=1.0)

    failed = started.fail(target_id, error="  failed cleanly  ", elapsed_seconds=3.0)
    assert failed.targets[0].last_error == "failed cleanly"


def test_recover_interrupted_fails_only_in_progress_targets() -> None:
    checkpoint = TraversalCheckpoint(uuid4())
    checkpoint = checkpoint.enqueue("https://example.org/a", depth=0)
    checkpoint = checkpoint.enqueue("https://example.org/b", depth=0)
    first_id, second_id = (target.target_id for target in checkpoint.targets)
    checkpoint = checkpoint.start(first_id, _policy())
    checkpoint = checkpoint.begin_finalization(
        first_id,
        artifact_sha256=_SHA256,
        observation_id=uuid4(),
        elapsed_seconds=1.0,
    )
    checkpoint = checkpoint.start(second_id, _policy())

    recovered = checkpoint.recover_interrupted(reason="  process restarted  ")
    first = next(target for target in recovered.targets if target.target_id == first_id)
    second = next(target for target in recovered.targets if target.target_id == second_id)
    assert first.status is TraversalStatus.FINALIZING
    assert second.status is TraversalStatus.FAILED
    assert second.last_error == "process restarted"

    with pytest.raises(ValueError, match="non-blank string"):
        checkpoint.recover_interrupted(reason=" ")


def test_requeue_failed_validates_state_policy_and_retry_budget() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="only failed"):
        checkpoint.requeue_failed(target_id, _policy())
    with pytest.raises(ValueError, match="traversal policy"):
        checkpoint.requeue_failed(target_id, cast(ResourceAcquisitionPolicy, object()))

    started = checkpoint.start(target_id, _policy())
    failed = started.fail(target_id, error="failed", elapsed_seconds=1.0)
    with pytest.raises(ValueError, match="retry budget is exhausted"):
        failed.requeue_failed(target_id, _policy(max_retries=0))

    requeued = failed.requeue_failed(target_id, _policy(max_retries=1))
    assert requeued.targets[0].status is TraversalStatus.QUEUED
    assert requeued.targets[0].last_error is None


def test_skip_validates_state_and_reason_without_spending_budget() -> None:
    checkpoint, target_id = _checkpoint()
    with pytest.raises(ValueError, match="non-blank string"):
        checkpoint.skip(target_id, reason=" ")

    skipped = checkpoint.skip(target_id, reason="  out of scope  ")
    assert skipped.targets[0].status is TraversalStatus.SKIPPED
    assert skipped.targets[0].last_error == "out of scope"
    assert skipped.budget == checkpoint.budget

    started = checkpoint.start(target_id, _policy())
    with pytest.raises(ValueError, match="only queued"):
        started.skip(target_id, reason="late")
