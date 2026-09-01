from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from tarkka.application.ingest import IngestResult, IngestService
from tarkka.conformance import ResearchRepositoryContract
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.infrastructure.storage import json_repository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.latex_parser import LatexParser
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser


def _ingest_sample(tmp_path: Path) -> IngestResult:
    """Build a fully valid domain fixture using production identity/manifest builders."""
    source = tmp_path / "sample.md"
    source.write_text(
        "# Abstract\nEvidence first.\n\n# Methods\nTemporal validation.\n",
        encoding="utf-8",
    )
    producer = JsonResearchRepository(tmp_path / "catalog.json")
    service = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=producer,
        parsers=(PlainTextParser(),),
    )
    return service.ingest(source)


def test_json_repository_satisfies_missing_read_contract(tmp_path: Path) -> None:
    repository = JsonResearchRepository(tmp_path / "catalog.json")

    ResearchRepositoryContract.assert_missing_reads_return_none(repository)


def test_json_repository_satisfies_round_trip_contract(tmp_path: Path) -> None:
    result = _ingest_sample(tmp_path)
    repository = JsonResearchRepository(tmp_path / "catalog.json")

    ResearchRepositoryContract.assert_artifact_round_trip(repository, result.artifact)
    ResearchRepositoryContract.assert_document_manifest_round_trip(
        repository,
        result.document,
        result.manifest,
    )


def test_json_repository_satisfies_idempotent_save_contract(tmp_path: Path) -> None:
    result = _ingest_sample(tmp_path)
    repository = JsonResearchRepository(tmp_path / "catalog.json")

    ResearchRepositoryContract.assert_repeated_saves_are_idempotent(
        repository,
        result.artifact,
        result.document,
        result.manifest,
    )


def test_json_repository_preserves_first_class_source_artifacts_on_reload(tmp_path: Path) -> None:
    source = Path("tests/fixtures/latex/structured_article.tex")
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=repository,
        parsers=(LatexParser(),),
    ).ingest(source)

    restored = JsonResearchRepository(tmp_path / "catalog.json").get_document(
        result.document.document_id
    )

    assert restored is not None
    assert restored.figures == result.document.figures
    assert restored.tables == result.document.tables
    assert restored.equations == result.document.equations


def test_json_repository_fsyncs_parent_directory_after_atomic_write(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "catalog.json"
    flushed: list[Path] = []
    monkeypatch.setattr(json_repository, "_fsync_directory", flushed.append)

    repository = JsonResearchRepository(path)
    result = _ingest_sample(tmp_path)
    flushed.clear()
    repository.save_artifact(result.artifact)

    assert flushed == [path.parent]


def test_json_repository_adds_links_without_invalidating_existing_catalogs(tmp_path: Path) -> None:
    result = _ingest_sample(tmp_path)
    catalog = tmp_path / "catalog.json"
    # Simulate the pre-link schema-1 shape written by earlier Tarkka versions.
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    del payload["work_document_links"]
    catalog.write_text(json.dumps(payload), encoding="utf-8")

    repository = JsonResearchRepository(catalog)
    link = WorkDocumentLink(
        link_id=uuid4(),
        work_id=uuid4(),
        artifact_id=result.artifact.artifact_id,
        document_id=result.document.document_id,
    )
    repository.save_work_document_link(link)

    assert repository.get_document(result.document.document_id) == result.document
    assert repository.list_work_document_links(link.work_id) == (link,)
