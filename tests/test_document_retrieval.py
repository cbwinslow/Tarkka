import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.document_context_packages import DocumentContextPackageService
from tarkka.application.document_retrieval import (
    DocumentNotFoundError,
    DocumentRetrievalService,
    DocumentSectionNotFoundError,
)
from tarkka.application.ingest import IngestResult, IngestService
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces.main import main


def _ingest_document(tmp_path: Path) -> tuple[IngestResult, JsonResearchRepository]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "paper.md"
    source.write_text(
        "# Abstract\nEvidence first.\n\n# Methods\nTemporal validation.\n", encoding="utf-8"
    )
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    ).ingest(source)
    return result, documents


def test_document_retrieval_preserves_a_bounded_manifest_to_section_ladder(tmp_path: Path) -> None:
    result, documents = _ingest_document(tmp_path)
    service = DocumentRetrievalService(documents=documents)

    manifest = service.manifest(result.document.document_id)
    page = service.sections(result.document.document_id, offset=1, limit=1)
    section = service.section(result.document.document_id, page.sections[0].section_id)

    assert manifest == result.manifest
    assert page.total == 2
    assert [(item.ordinal, item.title, item.passage_count) for item in page.sections] == [
        (1, "Methods", 1)
    ]
    assert page.sections[0].estimated_tokens > 0
    assert section.section_id == page.sections[0].section_id
    assert [passage.text for passage in section.passages] == ["Temporal validation."]


def test_document_retrieval_fails_closed_for_unknown_or_cross_document_handles(
    tmp_path: Path,
) -> None:
    first, documents = _ingest_document(tmp_path)
    second_source = tmp_path / "second.md"
    second_source.write_text("# Other\nDifferent source.\n", encoding="utf-8")
    second = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    ).ingest(second_source)
    service = DocumentRetrievalService(documents=documents)

    with pytest.raises(DocumentNotFoundError, match="document not found"):
        service.sections(uuid4())
    with pytest.raises(DocumentSectionNotFoundError, match="section not found"):
        service.section(first.document.document_id, second.document.sections[0].section_id)
    with pytest.raises(ValueError, match="non-negative"):
        service.sections(first.document.document_id, offset=-1)
    with pytest.raises(ValueError, match="configured maximum"):
        service.sections(first.document.document_id, limit=101)


def test_document_context_package_requires_explicit_unique_bounded_sections(tmp_path: Path) -> None:
    result, documents = _ingest_document(tmp_path)
    retrieval = DocumentRetrievalService(documents=documents)
    service = DocumentContextPackageService(documents=retrieval)
    section_ids = tuple(section.section_id for section in result.document.sections)

    package = service.build(result.document.document_id, section_ids)

    assert package.manifest == result.manifest
    assert [section.section_id for section in package.sections] == list(section_ids)
    assert package.estimated_tokens > 0
    with pytest.raises(ValueError, match="at least one"):
        service.build(result.document.document_id, ())
    with pytest.raises(ValueError, match="unique"):
        service.build(result.document.document_id, (section_ids[0], section_ids[0]))
    with pytest.raises(DocumentSectionNotFoundError, match="section not found"):
        service.build(result.document.document_id, (uuid4(),))


def test_documents_cli_progressively_lists_and_expands_one_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    result, _ = _ingest_document(home)

    assert main(["documents", "manifest", str(result.document.document_id)]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["id"] == f"doc:{result.document.document_id}"

    assert main(["documents", "sections", str(result.document.document_id), "--limit", "1"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["total"] == 2
    assert len(listing["sections"]) == 1
    assert "text" not in listing["sections"][0]

    assert (
        main(
            [
                "documents",
                "section",
                str(result.document.document_id),
                listing["sections"][0]["section_id"],
            ]
        )
        == 0
    )
    detail = json.loads(capsys.readouterr().out)
    assert detail["section_id"] == listing["sections"][0]["section_id"]
    assert detail["passages"][0]["text"] == "Evidence first."
