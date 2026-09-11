"""Local JSON persistence for resumable research jobs."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.application.scale import JobKind, JobStatus, ResearchJob
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonJobStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "jobs": {}})

    def save(self, job: ResearchJob) -> None:
        with exclusive_lock(self.path):
            data = self._read()
            jobs = cast(dict[str, Any], data["jobs"])
            jobs[str(job.job_id)] = _job_to_dict(job)
            self._write(data)

    def get(self, job_id: UUID) -> ResearchJob | None:
        with exclusive_lock(self.path):
            payload = cast(dict[str, Any], self._read()["jobs"]).get(str(job_id))
        if payload is None:
            return None
        return _job_from_dict(payload)

    def create_or_get(self, job: ResearchJob) -> ResearchJob:
        with exclusive_lock(self.path):
            data = self._read()
            jobs = cast(dict[str, Any], data["jobs"])
            for payload in jobs.values():
                existing = _job_from_dict(payload)
                if _same_identity(existing, job):
                    return existing
            jobs[str(job.job_id)] = _job_to_dict(job)
            self._write(data)
        return job

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read job store {self.path}: {exc}") from exc
        if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
            raise RuntimeError("unsupported job store schema")
        if not isinstance(decoded.get("jobs"), dict):
            raise RuntimeError("invalid job store: jobs must be a JSON object")
        return cast(dict[str, Any], decoded)

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-jobs-", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


def _job_to_dict(job: ResearchJob) -> dict[str, Any]:
    return {
        "job_id": str(job.job_id),
        "kind": job.kind.value,
        "input_digest": job.input_digest,
        "configuration_fingerprint": job.configuration_fingerprint,
        "library_id": str(job.library_id) if job.library_id is not None else None,
        "workspace_id": str(job.workspace_id) if job.workspace_id is not None else None,
        "checkpoint": dict(job.checkpoint),
        "status": job.status.value,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _job_from_dict(payload: dict[str, Any]) -> ResearchJob:
    try:
        return ResearchJob(
            job_id=UUID(payload["job_id"]),
            kind=JobKind(payload["kind"]),
            input_digest=str(payload["input_digest"]),
            configuration_fingerprint=str(payload["configuration_fingerprint"]),
            library_id=(
                UUID(payload["library_id"]) if payload.get("library_id") is not None else None
            ),
            workspace_id=(
                UUID(payload["workspace_id"]) if payload.get("workspace_id") is not None else None
            ),
            checkpoint=dict(payload.get("checkpoint") or {}),
            status=JobStatus(payload["status"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid job record: {exc}") from exc


def _same_identity(left: ResearchJob, right: ResearchJob) -> bool:
    return (
        left.kind is right.kind
        and left.input_digest == right.input_digest
        and left.configuration_fingerprint == right.configuration_fingerprint
        and left.library_id == right.library_id
        and left.workspace_id == right.workspace_id
    )
