from __future__ import annotations

from pathlib import Path

from tarkka.application.ingest import IngestResult, IngestService
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tests.contracts.research_repository import ResearchRepositoryContract


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
