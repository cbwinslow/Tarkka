from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000d01")


def _policy() -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_depth=2,
        max_requests=4,
        max_bytes=1000,
        max_retries=1,
    )


def _started_checkpoint() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/paper",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id
    return checkpoint.start(target_id, _policy()), target_id


def test_failed_atomic_replace_preserves_last_durable_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "checkpoints.json"
    repository = JsonTraversalCheckpointRepository(path)
    started, target_id = _started_checkpoint()
    repository.save(started)
    evolved = started.complete(
        target_id,
        bytes_acquired=123,
        elapsed_seconds=2.0,
    )

    def fail_replace(source: object, destination: object) -> None:
        raise OSError(f"simulated replace failure: {source!r} -> {destination!r}")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            "tarkka.infrastructure.storage.json_traversal_checkpoint_repository.os.replace",
            fail_replace,
        )
        with pytest.raises(OSError, match="simulated replace failure"):
            repository.save(evolved)

    reopened = JsonTraversalCheckpointRepository(path)
    assert reopened.get(_CHECKPOINT_ID) == started
    assert not tuple(tmp_path.glob(".tarkka-traversal-checkpoints-*"))


def test_failed_recovery_save_is_retryable_without_double_counting_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "checkpoints.json"
    repository = JsonTraversalCheckpointRepository(path)
    started, _ = _started_checkpoint()
    repository.save(started)
    recovered = started.recover_interrupted()

    def fail_replace(source: object, destination: object) -> None:
        raise OSError(f"simulated recovery save failure: {source!r} -> {destination!r}")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            "tarkka.infrastructure.storage.json_traversal_checkpoint_repository.os.replace",
            fail_replace,
        )
        with pytest.raises(OSError, match="simulated recovery save failure"):
            repository.save(recovered)

    still_started = JsonTraversalCheckpointRepository(path).get(_CHECKPOINT_ID)
    assert still_started == started
    assert still_started is not None
    retried_recovery = still_started.recover_interrupted()
    assert retried_recovery == recovered
    assert retried_recovery.budget.requests_used == 1
    assert retried_recovery.targets[0].attempts == 1
    assert retried_recovery.targets[0].status is TraversalStatus.FAILED

    repository.save(retried_recovery)
    durable = JsonTraversalCheckpointRepository(path).get(_CHECKPOINT_ID)
    assert durable == recovered
    assert durable is not None
    assert durable.budget.requests_used == 1
    assert not tuple(tmp_path.glob(".tarkka-traversal-checkpoints-*"))
