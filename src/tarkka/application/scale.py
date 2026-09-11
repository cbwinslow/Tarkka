"""Library isolation, resumable jobs, and fail-closed scale quotas."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from tarkka.domain.models import new_id, utc_now


class ScaleQuotaExceededError(ValueError):
    """Raised when a quota would be exceeded; sources must remain unchanged."""

    def __init__(self, *, dimension: str, used: int, limit: int) -> None:
        super().__init__(f"scale quota exceeded: {dimension} used={used} limit={limit}")
        self.dimension = dimension
        self.used = used
        self.limit = limit


class JobInProgressError(RuntimeError):
    """Raised when another worker owns the matching local job."""

    def __init__(self, job: ResearchJob) -> None:
        super().__init__(f"research job already in progress: {job.job_id}")
        self.job = job


class JobKind(StrEnum):
    INGEST = "ingest"
    EXTRACT = "extract"
    INDEX = "index"
    COMPILE = "compile"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScaleQuota:
    """Shared vocabulary with the agent context wallet, plus stored-bytes and crawl depth."""

    wallet_tokens: int
    expansions: int = 0
    provider_calls: int = 0
    bytes_stored: int = 0
    crawl_depth: int = 0

    def __post_init__(self) -> None:
        for name in (
            "wallet_tokens",
            "expansions",
            "provider_calls",
            "bytes_stored",
            "crawl_depth",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"scale quota {name} must be a non-negative integer")

    def require_tokens(self, estimated: int) -> None:
        _require("wallet_tokens", estimated, self.wallet_tokens)

    def require_expansions(self, count: int) -> None:
        _require("expansions", count, self.expansions)

    def require_provider_calls(self, count: int) -> None:
        _require("provider_calls", count, self.provider_calls)

    def require_bytes(self, size: int) -> None:
        _require("bytes_stored", size, self.bytes_stored)

    def require_crawl_depth(self, depth: int) -> None:
        _require("crawl_depth", depth, self.crawl_depth)


@dataclass(frozen=True, slots=True)
class ResearchJob:
    job_id: UUID
    kind: JobKind
    input_digest: str
    configuration_fingerprint: str
    library_id: UUID | None = None
    workspace_id: UUID | None = None
    checkpoint: Mapping[str, object] = field(default_factory=dict)
    status: JobStatus = JobStatus.RUNNING
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.input_digest.strip():
            raise ValueError("research job input_digest must not be blank")
        if not self.configuration_fingerprint.strip():
            raise ValueError("research job configuration_fingerprint must not be blank")
        object.__setattr__(self, "checkpoint", MappingProxyType(dict(self.checkpoint)))


@dataclass(frozen=True, slots=True)
class JobClaim:
    """The result of atomically acquiring permission to execute a job."""

    job: ResearchJob
    acquired: bool


class JobStore(Protocol):
    def save(self, job: ResearchJob) -> None: ...

    def get(self, job_id: UUID) -> ResearchJob | None: ...

    def acquire(self, job: ResearchJob) -> JobClaim: ...


class JobService:
    """Idempotent jobs keyed by kind + input digest + configuration fingerprint."""

    def __init__(self, store: JobStore) -> None:
        self._store = store

    def start(
        self,
        *,
        kind: JobKind,
        input_digest: str,
        configuration_fingerprint: str,
        library_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> ResearchJob:
        claim = self.acquire(
            kind=kind,
            input_digest=input_digest,
            configuration_fingerprint=configuration_fingerprint,
            library_id=library_id,
            workspace_id=workspace_id,
        )
        if not claim.acquired and claim.job.status is JobStatus.RUNNING:
            raise JobInProgressError(claim.job)
        return claim.job

    def acquire(
        self,
        *,
        kind: JobKind,
        input_digest: str,
        configuration_fingerprint: str,
        library_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> JobClaim:
        return self._store.acquire(
            ResearchJob(
                job_id=new_id(),
                kind=kind,
                input_digest=input_digest,
                configuration_fingerprint=configuration_fingerprint,
                library_id=library_id,
                workspace_id=workspace_id,
            )
        )

    def complete(self, job_id: UUID, checkpoint: Mapping[str, object]) -> ResearchJob:
        return self._update(job_id, status=JobStatus.COMPLETED, checkpoint=checkpoint)

    def checkpoint(self, job_id: UUID, checkpoint: Mapping[str, object]) -> ResearchJob:
        """Durably record resumable progress without changing the job status."""
        current = self.show(job_id)
        return self._update(job_id, status=current.status, checkpoint=checkpoint)

    def fail(self, job_id: UUID, checkpoint: Mapping[str, object] | None = None) -> ResearchJob:
        return self._update(
            job_id,
            status=JobStatus.FAILED,
            checkpoint={} if checkpoint is None else checkpoint,
        )

    def show(self, job_id: UUID) -> ResearchJob:
        job = self._store.get(job_id)
        if job is None:
            raise LookupError(f"job not found: {job_id}")
        return job

    def _update(
        self,
        job_id: UUID,
        *,
        status: JobStatus,
        checkpoint: Mapping[str, object],
    ) -> ResearchJob:
        current = self.show(job_id)
        updated = replace(
            current,
            status=status,
            checkpoint=dict(checkpoint),
            updated_at=utc_now(),
        )
        self._store.save(updated)
        return updated


def job_view(job: ResearchJob) -> dict[str, object]:
    return {
        "job_id": str(job.job_id),
        "kind": job.kind.value,
        "status": job.status.value,
        "input_digest": job.input_digest,
        "configuration_fingerprint": job.configuration_fingerprint,
        "library_id": str(job.library_id) if job.library_id is not None else None,
        "workspace_id": str(job.workspace_id) if job.workspace_id is not None else None,
        "checkpoint": dict(job.checkpoint),
    }


def _require(dimension: str, used: int, limit: int) -> None:
    if not isinstance(used, int) or isinstance(used, bool) or used < 0:
        raise ValueError(f"scale quota usage {dimension} must be a non-negative integer")
    if used > limit:
        raise ScaleQuotaExceededError(dimension=dimension, used=used, limit=limit)
