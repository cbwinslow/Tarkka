from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.library import LibraryRecord
from tarkka.application.scale import JobInProgressError, JobKind, JobService
from tarkka.application.workspace import WorkspaceNotFoundError, WorkspaceRecord
from tarkka.application.workspace_lexical_index import (
    WorkspaceLexicalIndexCheckpointError,
    WorkspaceLexicalIndexScopeError,
    WorkspaceLexicalIndexService,
)
from tarkka.domain.models import Workspace
from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.infrastructure.storage.json_job_store import JsonJobStore

_WORKSPACE_ID = UUID(int=1)
_LIBRARY_ID = UUID(int=2)
_DOCUMENT_ID = UUID(int=3)


@dataclass
class _Workspaces:
    record: WorkspaceRecord | None

    def get(self, workspace_id: UUID) -> WorkspaceRecord | None:
        return self.record if self.record is not None and workspace_id == _WORKSPACE_ID else None


@dataclass
class _Libraries:
    record: LibraryRecord | None

    def get(self, library_id: UUID) -> LibraryRecord | None:
        return (
            self.record
            if self.record is not None and library_id == self.record.library_id
            else None
        )


class _Lexical:
    def __init__(self) -> None:
        self.index = RetrievalSegmentIndex(_DOCUMENT_ID, "v1", "config", ())
        self.persisted: RetrievalSegmentIndex | None = None
        self.fail = False
        self.prepare_calls = 0

    def prepare_index(self, *_args: object, **_kwargs: object) -> RetrievalSegmentIndex:
        self.prepare_calls += 1
        return self.index

    def input_digest(self, *_args: object, **_kwargs: object) -> str:
        return self.index.digest

    def persist_index(self, index: RetrievalSegmentIndex) -> RetrievalSegmentIndex:
        if self.fail:
            raise OSError("index store unavailable")
        self.persisted = index
        return index

    def get_index(self, *_args: object, **_kwargs: object) -> RetrievalSegmentIndex | None:
        return self.persisted


def _workspace(
    *, library_id: UUID | None = _LIBRARY_ID, documents: tuple[UUID, ...] = (_DOCUMENT_ID,)
) -> WorkspaceRecord:
    return WorkspaceRecord(
        workspace=Workspace(workspace_id=_WORKSPACE_ID, name="index"),
        spec_digest="spec",
        questions=(),
        document_ids=documents,
        library_id=library_id,
    )


def _service(
    tmp_path: Path,
    *,
    workspace: WorkspaceRecord | None = None,
    library: LibraryRecord | None = None,
    missing_workspace: bool = False,
) -> tuple[WorkspaceLexicalIndexService, _Lexical, JobService]:
    lexical = _Lexical()
    catalog = library or LibraryRecord(_LIBRARY_ID, "index-library", document_ids=(_DOCUMENT_ID,))
    jobs = JobService(JsonJobStore(tmp_path / "jobs.json"))
    record = None if missing_workspace else workspace or _workspace()
    return (
        WorkspaceLexicalIndexService(
            workspaces=_Workspaces(record),  # type: ignore[arg-type]
            libraries=_Libraries(catalog),  # type: ignore[arg-type]
            lexical=lexical,  # type: ignore[arg-type]
            jobs=jobs,
        ),
        lexical,
        jobs,
    )


def test_workspace_index_persists_and_reuses_one_completed_job(tmp_path: Path) -> None:
    service, lexical, _jobs = _service(tmp_path)
    first = service.index(
        _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
    )
    second = service.index(
        _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
    )
    assert first == second
    assert lexical.persisted == first
    assert lexical.prepare_calls == 1


@pytest.mark.parametrize(
    ("workspace", "library", "message"),
    [
        (None, None, "workspace not found"),
        (_workspace(library_id=None), None, "no library_id"),
        (_workspace(), LibraryRecord(UUID(int=9), "other"), "library not found"),
        (_workspace(documents=()), None, "workspace"),
        (_workspace(), LibraryRecord(_LIBRARY_ID, "missing"), "library"),
    ],
)
def test_workspace_index_fails_closed_for_invalid_scope(
    tmp_path: Path,
    workspace: WorkspaceRecord | None,
    library: LibraryRecord | None,
    message: str,
) -> None:
    service, _lexical, _jobs = _service(
        tmp_path,
        workspace=workspace,
        library=library,
        missing_workspace=workspace is None,
    )
    error = WorkspaceNotFoundError if workspace is None else WorkspaceLexicalIndexScopeError
    with pytest.raises(error, match=message):
        service.index(
            _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
        )


def test_workspace_index_rejects_another_running_job(tmp_path: Path) -> None:
    service, lexical, jobs = _service(tmp_path)
    jobs.acquire(
        kind=JobKind.INDEX,
        input_digest=lexical.input_digest(),
        configuration_fingerprint="lexical-index-job@1",
        library_id=_LIBRARY_ID,
        workspace_id=_WORKSPACE_ID,
    )
    with pytest.raises(JobInProgressError):
        service.index(
            _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
        )
    assert lexical.prepare_calls == 0


def test_workspace_index_fails_job_and_retries_after_storage_failure(tmp_path: Path) -> None:
    service, lexical, _jobs = _service(tmp_path)
    lexical.fail = True
    with pytest.raises(OSError, match="unavailable"):
        service.index(
            _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
        )
    lexical.fail = False
    assert (
        service.index(
            _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
        )
        == lexical.index
    )


def test_workspace_index_recovers_persisted_projection_after_finalization_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, lexical, jobs = _service(tmp_path)
    complete = jobs.complete
    fail = jobs.fail

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError("job store unavailable")

    monkeypatch.setattr(jobs, "complete", unavailable)
    monkeypatch.setattr(jobs, "fail", unavailable)
    with pytest.raises(OSError, match="job store unavailable"):
        service.index(
            _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
        )
    assert lexical.persisted == lexical.index

    monkeypatch.setattr(jobs, "complete", complete)
    monkeypatch.setattr(jobs, "fail", fail)
    assert (
        service.index(
            _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
        )
        == lexical.index
    )
    assert lexical.prepare_calls == 1


def test_workspace_index_rejects_bad_or_missing_completed_checkpoint(tmp_path: Path) -> None:
    service, lexical, jobs = _service(tmp_path)
    claim = jobs.acquire(
        kind=JobKind.INDEX,
        input_digest=lexical.input_digest(),
        configuration_fingerprint="lexical-index-job@1",
        library_id=_LIBRARY_ID,
        workspace_id=_WORKSPACE_ID,
    )
    jobs.complete(claim.job.job_id, {"index_id": "bad", "index_digest": "bad"})
    with pytest.raises(WorkspaceLexicalIndexCheckpointError, match="persisted index"):
        service.index(
            _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
        )


def test_workspace_index_rejects_a_missing_completed_projection(tmp_path: Path) -> None:
    service, lexical, jobs = _service(tmp_path)
    claim = jobs.acquire(
        kind=JobKind.INDEX,
        input_digest=lexical.input_digest(),
        configuration_fingerprint="lexical-index-job@1",
        library_id=_LIBRARY_ID,
        workspace_id=_WORKSPACE_ID,
    )
    jobs.complete(
        claim.job.job_id,
        {"index_id": str(lexical.index.index_id), "index_digest": lexical.index.digest},
    )
    with pytest.raises(WorkspaceLexicalIndexCheckpointError, match="persisted index"):
        service.index(
            _WORKSPACE_ID, _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="config"
        )
