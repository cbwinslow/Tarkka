from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.ingest import IngestService
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.context_package_repository import (
    PostgresDocumentContextPackageRepository,
)
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.storage.json_context_package_repository import (
    JsonDocumentContextPackageRepository,
)
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces.main import (
    _document_context_package_store,
    _document_retrieval_repository,
    main,
)


def test_document_backend_defaults_to_local_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    monkeypatch.setenv("TARKKA_DATABASE_URL", "postgresql://must-not-be-used")

    repository = _document_retrieval_repository()
    store = _document_context_package_store()

    assert isinstance(repository, JsonResearchRepository)
    assert repository.path == tmp_path / "catalog.json"
    assert isinstance(store, JsonDocumentContextPackageRepository)
    assert store.path == tmp_path / "context_packages.json"


def test_document_backend_selects_postgres_only_when_explicitly_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", " postgres ")
    monkeypatch.setenv("TARKKA_DATABASE_URL", "postgresql://configured")

    assert isinstance(_document_retrieval_repository(), PostgresResearchRepository)
    assert isinstance(_document_context_package_store(), PostgresDocumentContextPackageRepository)


def test_document_backend_rejects_invalid_or_incomplete_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "sqlite")
    with pytest.raises(ValueError, match="unsupported TARKKA_DOCUMENT_BACKEND 'sqlite'"):
        _document_retrieval_repository()

    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "postgres")
    monkeypatch.delenv("TARKKA_DATABASE_URL", raising=False)
    assert main(["documents", "manifest", str(uuid4())]) == 2
    assert "TARKKA_DATABASE_URL is required" in capsys.readouterr().err


@pytest.mark.usefixtures("tarkka_postgres_settings")
@pytest.mark.integration
@pytest.mark.external
def test_postgres_document_cli_round_trips_a_saved_context_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tarkka_postgres_settings: PostgresSettings,
) -> None:
    with connect(tarkka_postgres_settings) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")
    source = tmp_path / "paper.md"
    source.write_text(
        "# Abstract\nEvidence first.\n\n# Methods\nTemporal validation.\n",
        encoding="utf-8",
    )
    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=PostgresResearchRepository(tarkka_postgres_settings),
        parsers=(PlainTextParser(),),
    ).ingest(source)
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "postgres")

    assert main(["documents", "manifest", str(result.document.document_id)]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["id"] == f"doc:{result.document.document_id}"

    assert main(["documents", "sections", str(result.document.document_id)]) == 0
    sections = json.loads(capsys.readouterr().out)["sections"]
    assert len(sections) == 2

    assert (
        main(
            [
                "documents",
                "package",
                str(result.document.document_id),
                "--section",
                sections[0]["section_id"],
                "--save",
            ]
        )
        == 0
    )
    package = json.loads(capsys.readouterr().out)
    assert package["context_package_id"].startswith("context_package:")

    assert main(["documents", "saved-package", package["context_package_id"]]) == 0
    restored = json.loads(capsys.readouterr().out)
    assert restored["context_package_id"] == package["context_package_id"]
