from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.resource_acquisition import AcquisitionBudgetState
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus, TraversalTarget
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonTraversalCheckpointRepository:
    """Atomic local persistence for evolving resumable traversal checkpoints."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"traversal checkpoint path is a directory: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "checkpoints": {}})

    def save(self, checkpoint: TraversalCheckpoint) -> None:
        if not isinstance(checkpoint, TraversalCheckpoint):
            raise ValueError("checkpoint must be a TraversalCheckpoint")
        with exclusive_lock(self.path):
            data = self._read()
            data["checkpoints"][str(checkpoint.checkpoint_id)] = _checkpoint_to_dict(checkpoint)
            self._write(data)

    def get(self, checkpoint_id: UUID) -> TraversalCheckpoint | None:
        if not isinstance(checkpoint_id, UUID):
            raise ValueError("checkpoint ID must be a UUID")
        payload = self._read()["checkpoints"].get(str(checkpoint_id))
        return _checkpoint_from_dict(payload) if payload is not None else None

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise OSError(f"unable to read traversal checkpoint catalog {self.path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid traversal checkpoint JSON {self.path}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid traversal checkpoint catalog: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("invalid or unsupported traversal checkpoint catalog")
        if "checkpoints" not in data or not isinstance(data["checkpoints"], dict):
            raise RuntimeError("invalid traversal checkpoint catalog bucket: checkpoints")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=".tarkka-traversal-checkpoints-",
            dir=self.path.parent,
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(
                json.dumps(data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            with temp_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            temp_path.unlink(missing_ok=True)


def _checkpoint_to_dict(checkpoint: TraversalCheckpoint) -> dict[str, Any]:
    return {
        "checkpoint_id": str(checkpoint.checkpoint_id),
        "budget": {
            "requests_used": checkpoint.budget.requests_used,
            "bytes_used": checkpoint.budget.bytes_used,
            "elapsed_seconds": checkpoint.budget.elapsed_seconds,
        },
        "targets": [_target_to_dict(target) for target in checkpoint.targets],
    }


def _target_to_dict(target: TraversalTarget) -> dict[str, Any]:
    return {
        "target_id": str(target.target_id),
        "uri": target.uri,
        "depth": target.depth,
        "status": target.status.value,
        "attempts": target.attempts,
        "bytes_acquired": target.bytes_acquired,
        "discovery_link_ids": [str(value) for value in target.discovery_link_ids],
        "parent_target_ids": [str(value) for value in target.parent_target_ids],
        "last_error": target.last_error,
    }


def _checkpoint_from_dict(raw: dict[str, Any]) -> TraversalCheckpoint:
    budget_raw = raw["budget"]
    return TraversalCheckpoint(
        checkpoint_id=UUID(raw["checkpoint_id"]),
        budget=AcquisitionBudgetState(
            requests_used=budget_raw["requests_used"],
            bytes_used=budget_raw["bytes_used"],
            elapsed_seconds=budget_raw["elapsed_seconds"],
        ),
        targets=tuple(_target_from_dict(item) for item in raw["targets"]),
    )


def _target_from_dict(raw: dict[str, Any]) -> TraversalTarget:
    return TraversalTarget(
        target_id=UUID(raw["target_id"]),
        uri=raw["uri"],
        depth=raw["depth"],
        status=TraversalStatus(raw["status"]),
        attempts=raw["attempts"],
        bytes_acquired=raw["bytes_acquired"],
        discovery_link_ids=tuple(UUID(value) for value in raw["discovery_link_ids"]),
        parent_target_ids=tuple(UUID(value) for value in raw["parent_target_ids"]),
        last_error=raw.get("last_error"),
    )
