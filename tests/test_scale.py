from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.scale import (
    JobInProgressError,
    JobKind,
    JobService,
    JobStatus,
    ResearchJob,
    ScaleQuota,
    ScaleQuotaExceededError,
    job_view,
)
from tarkka.infrastructure.storage import json_job_store
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


def test_job_acquire_only_allows_one_worker_to_execute_a_running_job(tmp_path) -> None:
    service = JobService(JsonJobStore(tmp_path / "jobs.json"))
    first = service.acquire(
        kind=JobKind.COMPILE,
        input_digest="digest",
        configuration_fingerprint="compiler@1",
    )
    second = service.acquire(
        kind=JobKind.COMPILE,
        input_digest="digest",
        configuration_fingerprint="compiler@1",
    )

    assert first.acquired is True
    assert second.acquired is False
    assert second.job == first.job
    with pytest.raises(JobInProgressError, match="already in progress") as raised:
        service.start(
            kind=JobKind.COMPILE,
            input_digest="digest",
            configuration_fingerprint="compiler@1",
        )
    assert raised.value.job == second.job


def test_job_acquire_claims_a_failed_job_and_preserves_its_checkpoint(tmp_path) -> None:
    service = JobService(JsonJobStore(tmp_path / "jobs.json"))
    initial = service.acquire(
        kind=JobKind.INDEX,
        input_digest="digest",
        configuration_fingerprint="segments@1",
    )
    service.fail(initial.job.job_id, {"last_segment": "passage:2"})

    retry = service.acquire(
        kind=JobKind.INDEX,
        input_digest="digest",
        configuration_fingerprint="segments@1",
    )

    assert retry.acquired is True
    assert retry.job.status is JobStatus.RUNNING
    assert retry.job.checkpoint == {"last_segment": "passage:2"}


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
    quota.require_expansions(0)
    quota.require_provider_calls(0)
    quota.require_bytes(20)
    quota.require_crawl_depth(0)

    with pytest.raises(ScaleQuotaExceededError, match="wallet_tokens"):
        quota.require_tokens(11)
    with pytest.raises(ScaleQuotaExceededError, match="bytes_stored"):
        quota.require_bytes(21)


@pytest.mark.parametrize("usage", [True, -1, 1.5, "1"])
def test_scale_quota_rejects_invalid_usage(usage: object) -> None:
    quota = ScaleQuota(wallet_tokens=10)

    with pytest.raises(ValueError, match="usage wallet_tokens"):
        quota.require_tokens(usage)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    ["wallet_tokens", "expansions", "provider_calls", "bytes_stored", "crawl_depth"],
)
@pytest.mark.parametrize("value", [True, -1, 1.5, "1"])
def test_scale_quota_rejects_invalid_limits(field: str, value: object) -> None:
    values: dict[str, object] = {"wallet_tokens": 1}
    values[field] = value

    with pytest.raises(ValueError, match=field):
        ScaleQuota(**values)  # type: ignore[arg-type]


def test_json_job_store_fsyncs_parent_directory_after_atomic_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "jobs.json"
    flushed: list[Path] = []
    monkeypatch.setattr(json_job_store, "_fsync_directory", flushed.append)

    store = JsonJobStore(path)
    JobService(store).start(
        kind=JobKind.COMPILE,
        input_digest="digest",
        configuration_fingerprint="compiler@1",
    )

    assert flushed == [path.parent, path.parent]


def test_job_store_directory_fsync_is_skipped_when_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "open", lambda path, flags: opened.append(Path(path)))

    json_job_store._fsync_directory(tmp_path)

    assert opened == []


def test_job_store_directory_fsync_opens_and_closes_posix_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Path] = []
    synced: list[int] = []
    closed: list[int] = []
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(os, "open", lambda path, flags: opened.append(Path(path)) or 42)
    monkeypatch.setattr(os, "fsync", synced.append)
    monkeypatch.setattr(os, "close", closed.append)

    json_job_store._fsync_directory(tmp_path)

    assert opened == [tmp_path]
    assert synced == [42]
    assert closed == [42]


@pytest.mark.parametrize(
    "contents,error",
    [
        ("[1]", "unsupported job store schema"),
        ('{"schema_version": 2, "jobs": {}}', "unsupported job store schema"),
        ('{"schema_version": 1, "jobs": []}', "jobs must be a JSON object"),
        ("{", "unable to read job store"),
    ],
)
def test_job_store_rejects_corrupt_catalogs(
    tmp_path: Path, contents: str, error: str
) -> None:
    store = JsonJobStore(tmp_path / "jobs.json")
    store.path.write_text(contents, encoding="utf-8")

    with pytest.raises(RuntimeError, match=error):
        store.get(UUID(int=1))


def test_job_store_reports_missing_catalog_and_invalid_job_record(tmp_path: Path) -> None:
    store = JsonJobStore(tmp_path / "jobs.json")
    store.path.unlink()
    with pytest.raises(RuntimeError, match="unable to read job store"):
        store.get(UUID(int=1))

    store = JsonJobStore(tmp_path / "invalid-jobs.json")
    store.path.write_text(
        '{"schema_version": 1, "jobs": {"not-a-job": {}}}', encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="invalid job record"):
        store.acquire(
            ResearchJob(
                job_id=UUID(int=1),
                kind=JobKind.INDEX,
                input_digest="digest",
                configuration_fingerprint="index@1",
            )
        )


def test_job_store_does_not_reinitialize_an_existing_catalog(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    first = JsonJobStore(path)
    second = JsonJobStore(path)

    assert first.path == second.path


def test_job_store_write_removes_a_temporary_file_after_serialization_failure(
    tmp_path: Path,
) -> None:
    store = JsonJobStore(tmp_path / "jobs.json")

    with pytest.raises(TypeError):
        store._write({"not_json": object()})

    assert list(tmp_path.glob(".tarkka-jobs-*")) == []


def test_job_view_and_missing_job_are_explicit(tmp_path) -> None:
    service = JobService(JsonJobStore(tmp_path / "jobs.json"))
    job = ResearchJob(
        job_id=UUID(int=1),
        kind=JobKind.INGEST,
        input_digest="digest",
        configuration_fingerprint="ingest@1",
        checkpoint={"step": 1},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert json_job_store._job_from_dict(json_job_store._job_to_dict(job)) == job
    assert job_view(job)["checkpoint"] == {"step": 1}
    with pytest.raises(LookupError, match="job not found"):
        service.show(UUID(int=2))
