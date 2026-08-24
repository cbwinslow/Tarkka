from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.ingest import IngestResult, IngestService
from tarkka.application.research_packages import ResearchPackageService
from tarkka.domain.source_observations import ResourceRelation
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.interfaces.main import main

_FIXTURE = Path("tests/fixtures/jats/sample_article.xml")


def _ingest_native_document(
    tmp_path: Path,
) -> tuple[IngestResult, JsonResearchRepository, JsonSourceObservationRepository]:
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(JatsParser(),),
        source_observation_repository=observations,
    ).ingest(_FIXTURE)
    documents.save_work_document_link(
        WorkDocumentLink(
            link_id=uuid4(),
            work_id=uuid4(),
            artifact_id=result.artifact.artifact_id,
            document_id=result.document.document_id,
        )
    )
    return result, documents, observations


def test_research_package_groups_native_resources_without_resolving_them(tmp_path: Path) -> None:
    result, documents, observations = _ingest_native_document(tmp_path)

    inspection = ResearchPackageService(
        documents=documents,
        work_documents=documents,
        observations=observations,
    ).inspect(result.document.document_id)

    assert inspection.artifact_id == result.artifact.artifact_id
    assert len(inspection.work_documents) == 1
    assert len(inspection.source_observations) == 1
    assert [(link.relation, link.target_uri) for link in inspection.resource_links] == [
        (ResourceRelation.SUPPLEMENT, "supplement/data.csv")
    ]


def test_resources_cli_progressively_expands_native_package_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    result, _, _ = _ingest_native_document(home)

    assert main(["resources", "list", str(result.document.document_id), "--limit", "1"]) == 0
    listing = json.loads(capsys.readouterr().out)

    assert listing["artifact_id"] == str(result.artifact.artifact_id)
    assert len(listing["work_representations"]) == 1
    assert listing["resources"]["total"] == 1
    resource = listing["resources"]["items"][0]
    assert resource["relation"] == "supplement"
    assert resource["metadata_keys"] == ["native_id"]

    assert main(
        ["resources", "show", str(result.document.document_id), resource["link_id"]]
    ) == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["target_uri"] == "supplement/data.csv"
    assert detail["metadata"] == {"native_id": None}


def test_resources_cli_unknown_document_fails_without_initializing_source_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))

    assert main(["resources", "list", str(uuid4())]) == 2

    assert "document not found" in capsys.readouterr().err
    assert not (tmp_path / "home" / "catalog.json").exists()
    assert not (tmp_path / "home" / "source_observations.json").exists()
