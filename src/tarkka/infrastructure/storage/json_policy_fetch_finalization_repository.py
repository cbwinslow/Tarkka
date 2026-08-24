from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.policy_fetch_finalization import (
    PolicyFetchFinalization,
    policy_fetch_finalization_id,
)
from tarkka.infrastructure.storage.locking import exclusive_lock


class PolicyFetchFinalizationConflictError(RuntimeError):
    """Raised when one stable policy-finalization slot is reused incompatibly."""


class JsonPolicyFetchFinalizationRepository:
    """Atomic local journal for restart-recoverable policy HTTP output commits."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"policy finalization path is a directory: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write(_empty_catalog())

    def save(self, finalization: PolicyFetchFinalization) -> None:
        if not isinstance(finalization, PolicyFetchFinalization):
            raise ValueError("finalization must be a PolicyFetchFinalization")
        key = str(finalization.finalization_id)
        payload = _finalization_to_dict(finalization)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data["finalizations"].get(key)
            if existing is not None:
                if existing == payload:
                    return
                raise PolicyFetchFinalizationConflictError(
                    "conflicting policy fetch finalization already exists"
                )
            data["finalizations"][key] = payload
            self._write(data)

    def get(
        self,
        checkpoint_id: UUID,
        requested_uri: str,
    ) -> PolicyFetchFinalization | None:
        key = str(policy_fetch_finalization_id(checkpoint_id, requested_uri))
        payload = self._read()["finalizations"].get(key)
        return _finalization_from_dict(payload) if payload is not None else None

    def delete(self, finalization: PolicyFetchFinalization) -> None:
        if not isinstance(finalization, PolicyFetchFinalization):
            raise ValueError("finalization must be a PolicyFetchFinalization")
        key = str(finalization.finalization_id)
        expected = _finalization_to_dict(finalization)
        with exclusive_lock(self.path):
            data = self._read()
            current = data["finalizations"].get(key)
            if current is None:
                return
            if current != expected:
                raise PolicyFetchFinalizationConflictError(
                    "policy fetch finalization changed before deletion"
                )
            del data["finalizations"][key]
            self._write(data)

    def _read(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(
                f"unable to read policy finalization journal {self.path}: {exc}"
            ) from exc
        try:
            decoded: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"invalid policy finalization journal JSON {self.path}: {exc}"
            ) from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid policy finalization journal: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("invalid or unsupported policy finalization journal")
        if not isinstance(data.get("finalizations"), dict):
            raise RuntimeError("invalid policy finalization journal bucket")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=".tarkka-policy-finalizations-",
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
            _fsync_directory(self.path.parent)
        finally:
            temp_path.unlink(missing_ok=True)


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, "finalizations": {}}


def _finalization_to_dict(value: PolicyFetchFinalization) -> dict[str, Any]:
    response = value.response
    return {
        "checkpoint_id": str(value.checkpoint_id),
        "requested_uri": value.requested_uri,
        "artifact_sha256": value.artifact_sha256,
        "observation_id": str(value.observation_id),
        "response": {
            "requested_uri": response.requested_uri,
            "final_uri": response.final_uri,
            "status_code": response.status_code,
            "headers": {name: list(values) for name, values in response.headers.items()},
            "redirect_chain": list(response.redirect_chain),
            "depth": response.depth,
            "observed_at": response.observed_at.isoformat(),
        },
    }


def _finalization_from_dict(raw: dict[str, Any]) -> PolicyFetchFinalization:
    if not isinstance(raw, dict):
        raise RuntimeError("invalid policy finalization record")
    try:
        response_raw = raw["response"]
        if not isinstance(response_raw, dict):
            raise ValueError("response must be an object")
        headers_raw = response_raw["headers"]
        if not isinstance(headers_raw, dict):
            raise ValueError("response headers must be an object")
        response = HttpResponseSnapshot(
            requested_uri=response_raw["requested_uri"],
            final_uri=response_raw["final_uri"],
            status_code=response_raw["status_code"],
            headers={name: tuple(values) for name, values in headers_raw.items()},
            redirect_chain=tuple(response_raw["redirect_chain"]),
            depth=response_raw["depth"],
            observed_at=datetime.fromisoformat(response_raw["observed_at"]),
        )
        return PolicyFetchFinalization(
            checkpoint_id=UUID(raw["checkpoint_id"]),
            requested_uri=raw["requested_uri"],
            artifact_sha256=raw["artifact_sha256"],
            observation_id=UUID(raw["observation_id"]),
            response=response,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid policy finalization record: {exc}") from exc


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
