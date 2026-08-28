from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tarkka.application.ingest import IngestResult, IngestService
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.infrastructure.storage import json_repository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser


def _ingest(tmp_path: Path, *, name: str, content: str) -> IngestResult:
    source = tmp_path / name
    source.write_text(content, encoding="utf-8")
    return IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=JsonResearchRepository(tmp_path / "catalog.json"),
        parsers=(PlainTextParser(),),
    ).ingest(source)


def test_read_rejects_invalid_work_document_links_bucket(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    repository = JsonResearchRepository(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["work_document_links"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="work_document_links must be a JSON object"):
        repository._read()


def test_link_rejects_missing_artifact(tmp_path: Path) -> None:
    result = _ingest(tmp_path, name="one.txt", content="one")
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    link = WorkDocumentLink(
        link_id=uuid4(),
        work_id=uuid4(),
        artifact_id=uuid4(),
        document_id=result.document.document_id,
    )

    with pytest.raises(ValueError, match="artifact not found for work document link"):
        repository.save_work_document_link(link)


def test_link_rejects_missing_document(tmp_path: Path) -> None:
    result = _ingest(tmp_path, name="one.txt", content="one")
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    link = WorkDocumentLink(
        link_id=uuid4(),
        work_id=uuid4(),
        artifact_id=result.artifact.artifact_id,
        document_id=uuid4(),
    )

    with pytest.raises(ValueError, match="document not found for work document link"):
        repository.save_work_document_link(link)


def test_link_rejects_artifact_document_mismatch(tmp_path: Path) -> None:
    first = _ingest(tmp_path, name="one.txt", content="one")
    second = _ingest(tmp_path, name="two.txt", content="two")
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    link = WorkDocumentLink(
        link_id=uuid4(),
        work_id=uuid4(),
        artifact_id=first.artifact.artifact_id,
        document_id=second.document.document_id,
    )

    with pytest.raises(ValueError, match="artifact does not match document artifact"):
        repository.save_work_document_link(link)


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(json_repository, "os", SimpleNamespace(name="nt"))

    json_repository._fsync_directory(tmp_path)
