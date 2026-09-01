from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from tarkka.conformance import ResearchRepositoryContract
from tarkka.domain.manifest import ResourceManifest, build_document_manifest
from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.migrations import upgrade
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.storage.latex_parser import LatexParser

pytestmark = [pytest.mark.integration, pytest.mark.external]

_ROOT = Path(__file__).parents[1]
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000f001")
_MISSING_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
_ACQUIRED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _settings() -> PostgresSettings:
    return PostgresSettings.from_environment()


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="a" * 64,
        size_bytes=1024,
        media_type="text/x-tex",
        storage_key=PurePosixPath("artifacts/aa/fixture.tex"),
        original_name="structured_article.tex",
        acquired_at=_ACQUIRED_AT,
        source_uri="https://example.test/structured_article.tex",
    )


def _document_fixture() -> tuple[Artifact, Document, ResourceManifest]:
    artifact = _artifact()
    document = LatexParser().parse(artifact, _ROOT / "tests/fixtures/latex/structured_article.tex")
    return artifact, document, build_document_manifest(document, artifact)


@pytest.fixture(scope="module", autouse=True)
def _apply_migrations() -> None:
    upgrade(_settings())


@pytest.fixture(autouse=True)
def _clean_document_tables() -> None:
    with connect(_settings()) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


@pytest.fixture
def repository() -> PostgresResearchRepository:
    return PostgresResearchRepository(_settings())


def test_postgres_research_repository_satisfies_missing_read_contract(
    repository: PostgresResearchRepository,
) -> None:
    ResearchRepositoryContract.assert_missing_reads_return_none(repository)


def test_postgres_research_repository_round_trips_native_document_structure(
    repository: PostgresResearchRepository,
) -> None:
    artifact, document, manifest = _document_fixture()
    repository.save_artifact(artifact)

    ResearchRepositoryContract.assert_document_manifest_round_trip(repository, document, manifest)

    restored = repository.get_document(document.document_id)
    assert restored is not None
    assert restored.figures == document.figures
    assert restored.tables == document.tables
    assert restored.equations == document.equations


def test_postgres_research_repository_satisfies_idempotent_save_contract(
    repository: PostgresResearchRepository,
) -> None:
    artifact, document, manifest = _document_fixture()

    ResearchRepositoryContract.assert_repeated_saves_are_idempotent(
        repository, artifact, document, manifest
    )


def test_postgres_research_repository_requires_the_document_artifact(
    repository: PostgresResearchRepository,
) -> None:
    _, document, manifest = _document_fixture()

    with pytest.raises(ValueError, match="artifact not found"):
        repository.save_document(document, manifest)

    assert repository.get_artifact(_MISSING_ID) is None


def test_postgres_research_repository_rejects_conflicting_immutable_records(
    repository: PostgresResearchRepository,
) -> None:
    artifact, document, manifest = _document_fixture()
    repository.save_artifact(artifact)
    repository.save_document(document, manifest)

    repository.save_artifact(
        replace(
            artifact,
            original_name="reacquired.tex",
            source_uri="https://example.test/reacquired.tex",
            acquired_at=datetime(2027, 1, 1, tzinfo=UTC),
        )
    )
    repository.save_document(
        replace(document, normalized_at=datetime(2027, 1, 1, tzinfo=UTC)), manifest
    )

    with pytest.raises(ValueError, match="conflicting artifact"):
        repository.save_artifact(replace(artifact, media_type="application/x-tex"))
    with pytest.raises(ValueError, match="conflicting document"):
        repository.save_document(replace(document, parser_version="different"), manifest)

    assert repository.get_artifact(artifact.artifact_id) == artifact
    assert repository.get_document(document.document_id) == document
