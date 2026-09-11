from __future__ import annotations

from uuid import UUID

import pytest

from tarkka.application.scale import (
    JobKind,
    JobService,
    JobStatus,
    ScaleQuota,
    ScaleQuotaExceededError,
)
from tarkka.infrastructure.storage.json_job_store import JsonJobStore

pytestmark = pytest.mark.unit


def test_job_identity_is_atomic_scoped_and_returns_completed_result(tmp_path) -> None:
    service = JobService(JsonJobStore(tmp_path / "jobs.json"))
    first = service.start(
        kind=JobKind.COMPILE,
        input_digest="a" * 64,
        configuration_fingerprint="compiler@1",
        library_id=UUID(int=1),
        workspace_id=UUID(int=2),
    )
    completed = service.complete(first.job_id, {"edition_id": str(UUID(int=3))})
    same = service.start(
        kind=JobKind.COMPILE,
        input_digest="a" * 64,
        configuration_fingerprint="compiler@1",
        library_id=UUID(int=1),
        workspace_id=UUID(int=2),
    )
    other_library = service.start(
        kind=JobKind.COMPILE,
        input_digest="a" * 64,
        configuration_fingerprint="compiler@1",
        library_id=UUID(int=4),
        workspace_id=UUID(int=2),
    )

    assert same == completed
    assert other_library.job_id != first.job_id


def test_failed_job_retries_from_its_checkpoint(tmp_path) -> None:
    service = JobService(JsonJobStore(tmp_path / "jobs.json"))
    job = service.start(
        kind=JobKind.INDEX,
        input_digest="digest",
        configuration_fingerprint="segments@1",
    )
    failed = service.fail(job.job_id, {"last_segment": "passage:2"})
    retried = service.start(
        kind=JobKind.INDEX,
        input_digest="digest",
        configuration_fingerprint="segments@1",
    )

    assert failed.status is JobStatus.FAILED
    assert retried.status is JobStatus.RUNNING
    assert retried.checkpoint == {"last_segment": "passage:2"}


@pytest.mark.parametrize("digest,fingerprint", [("", "v1"), ("digest", " ")])
def test_jobs_reject_blank_identity_parts(tmp_path, digest: str, fingerprint: str) -> None:
    service = JobService(JsonJobStore(tmp_path / "jobs.json"))

    with pytest.raises(ValueError, match="must not be blank"):
        service.start(
            kind=JobKind.COMPILE,
            input_digest=digest,
            configuration_fingerprint=fingerprint,
        )


def test_scale_quota_fails_closed() -> None:
    quota = ScaleQuota(wallet_tokens=10, bytes_stored=20)
    quota.require_tokens(10)
    quota.require_bytes(20)

    with pytest.raises(ScaleQuotaExceededError, match="wallet_tokens"):
        quota.require_tokens(11)
    with pytest.raises(ScaleQuotaExceededError, match="bytes_stored"):
        quota.require_bytes(21)
