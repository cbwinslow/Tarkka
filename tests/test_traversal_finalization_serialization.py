from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus, TraversalTarget
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000880")
_OBSERVATION_ID = UUID("00000000-0000-0000-0000-000000000881")
_ARTIFACT_SHA256 = "a" * 64
_URI = "https://example.org/paper"


def _policy() -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_requests=2,
        max_bytes=1024,
        max_elapsed_seconds=30.0,
    )


def _queued_checkpoint() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(_URI, depth=0)
    return checkpoint, checkpoint.targets[0].target_id


def _finalizing_checkpoint() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint, target_id = _queued_checkpoint()
    checkpoint = checkpoint.start(target_id, _policy())
    checkpoint = checkpoint.record_response_bytes(target_id, bytes_acquired=8)
    checkpoint = checkpoint.begin_finalization(
        target_id,
        artifact_sha256=_ARTIFACT_SHA256,
        observation_id=_OBSERVATION_ID,
        elapsed_seconds=2.5,
    )
    return checkpoint, target_id


def _target_by_id(checkpoint: TraversalCheckpoint, target_id: UUID) -> TraversalTarget:
    target = next((item for item in checkpoint.targets if item.target_id == target_id), None)
    assert target is not None
    return target


def test_finalizing_checkpoint_round_trip_preserves_recovery_identifiers(tmp_path: Path) -> None:
    repository = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    checkpoint, target_id = _finalizing_checkpoint()

    repository.save(checkpoint)
    restored = repository.get(_CHECKPOINT_ID)

    assert restored == checkpoint
    assert restored is not None
    target = _target_by_id(restored, target_id)
    assert target.status is TraversalStatus.FINALIZING
    assert target.final_artifact_sha256 == _ARTIFACT_SHA256
    assert target.final_observation_id == _OBSERVATION_ID
    assert restored.budget.requests_used == 1
    assert restored.budget.bytes_used == 8
    assert restored.budget.elapsed_seconds == 2.5


def test_completed_finalization_round_trip_keeps_commit_markers(tmp_path: Path) -> None:
    repository = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    checkpoint, target_id = _finalizing_checkpoint()
    completed = checkpoint.complete_finalization(target_id, elapsed_seconds=3.0)

    repository.save(completed)
    restored = repository.get(_CHECKPOINT_ID)

    assert restored == completed
    assert restored is not None
    target = _target_by_id(restored, target_id)
    assert target.status is TraversalStatus.COMPLETED
    assert target.final_artifact_sha256 == _ARTIFACT_SHA256
    assert target.final_observation_id == _OBSERVATION_ID


def test_schema_v1_checkpoint_without_finalization_fields_remains_readable(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.json"
    _, target_id = _queued_checkpoint()
    legacy_payload = {
        "schema_version": 1,
        "checkpoints": {
            str(_CHECKPOINT_ID): {
                "checkpoint_id": str(_CHECKPOINT_ID),
                "budget": {
                    "requests_used": 1,
                    "bytes_used": 8,
                    "elapsed_seconds": 2.5,
                },
                "targets": [
                    {
                        "target_id": str(target_id),
                        "uri": _URI,
                        "depth": 0,
                        "status": "completed",
                        "attempts": 1,
                        "bytes_acquired": 8,
                        "discovery_link_ids": [],
                        "parent_target_ids": [],
                        "last_error": None,
                    }
                ],
            }
        },
    }
    path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    restored = JsonTraversalCheckpointRepository(path).get(_CHECKPOINT_ID)

    assert restored is not None
    target = _target_by_id(restored, target_id)
    assert target.status is TraversalStatus.COMPLETED
    assert target.final_artifact_sha256 is None
    assert target.final_observation_id is None
    assert restored.budget.requests_used == 1
    assert restored.budget.bytes_used == 8
    assert restored.budget.elapsed_seconds == 2.5
