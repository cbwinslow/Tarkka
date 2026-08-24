from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.ingest import IngestService
from tarkka.domain.models import Work
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.domain.work_identity import WorkIdentifier
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces.cli import _ingest_service, _runtime
from tarkka.interfaces.main import _parse_work_id, main

_JATS_FIXTURE = Path("tests/fixtures/jats/sample_article.xml")


def test_citations_resolve_cli_infers_citing_work_from_document_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    store, documents, acquisitions = _runtime()
    ingest = _ingest_service(store, documents, acquisitions)
    result = ingest.ingest(_JATS_FIXTURE)

    works = JsonWorkRepository(home / "works.json")
    citing = Work(work_id=uuid4(), title="Citing fixture")
    cited = Work(work_id=uuid4(), title="First cited fixture")
    unrelated = Work(work_id=uuid4(), title="Unrelated fixture")
    with works.transaction():
        works.save_work(citing)
        works.save_work(cited)
        works.save_work(unrelated)
        works.save_identifier(
            WorkIdentifier(
                identifier_id=uuid4(),
                work_id=cited.work_id,
                scheme="doi",
                value="10.1000/first",
            )
        )
    documents.save_work_document_link(
        WorkDocumentLink(
            link_id=uuid4(),
            work_id=citing.work_id,
            artifact_id=result.artifact.artifact_id,
            document_id=result.document.document_id,
        )
    )

    assert main(["citations", "resolve", str(result.document.document_id)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["citing_work_id"] == str(citing.work_id)
    assert payload["offset"] == 0
    assert payload["limit"] == 100
    assert payload["total"] == 2
    assert [item["status"] for item in payload["resolutions"]] == ["resolved", "unresolved"]
    assert payload["resolutions"][0]["work_id"] == str(cited.work_id)
    assert len(payload["relations"]) == 1
    relation = payload["relations"][0]
    assert relation["kind"] == "cites"
    assert relation["subject_work_id"] == str(citing.work_id)
    assert relation["object_work_id"] == str(cited.work_id)

    assert main(
        [
            "citations",
            "resolve",
            str(result.document.document_id),
            "--citing-work",
            str(uuid4()),
        ]
    ) == 2
    assert "citing work not found" in capsys.readouterr().err

    assert main(
        [
            "citations",
            "resolve",
            str(result.document.document_id),
            "--citing-work",
            str(unrelated.work_id),
        ]
    ) == 2
    assert "not linked to the source document" in capsys.readouterr().err

    assert main(
        ["citations", "resolve", str(result.document.document_id), "--offset", "1", "--limit", "1"]
    ) == 0
    page = json.loads(capsys.readouterr().out)
    assert page["total"] == 2
    assert len(page["resolutions"]) == 1


def test_citations_resolve_cli_rejects_unknown_document_and_missing_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))

    assert main(["citations", "resolve", str(uuid4())]) == 2
    assert "document not found" in capsys.readouterr().err

    store, catalog, acquisitions = _runtime()
    source = tmp_path / "source.md"
    source.write_text("# No citations\n", encoding="utf-8")
    document = IngestService(
        artifact_store=store,
        repository=catalog,
        parsers=(PlainTextParser(),),
    ).ingest(source)
    del acquisitions

    assert main(["citations", "resolve", str(document.document.document_id)]) == 2
    assert "no preserved citations found" in capsys.readouterr().err


def test_citation_resolution_work_id_parser_accepts_prefix_and_rejects_invalid() -> None:
    work_id = uuid4()

    assert _parse_work_id(f"work:{work_id}") == work_id
    with pytest.raises(SystemExit):
        main(["citations", "resolve", str(uuid4()), "--citing-work", "not-a-uuid"])
