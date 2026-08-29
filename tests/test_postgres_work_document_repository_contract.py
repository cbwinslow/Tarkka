from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from tarkka.domain.manifest import build_document_manifest
from tarkka.domain.models import Artifact, Document, Work
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.infrastructure.postgres.connection import (
    PostgresOperationError,
    PostgresSettings,
    connect,
)
from tarkka.infrastructure.postgres.migrations import upgrade
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.work_document_repository import (
    PostgresWorkDocumentRepository,
)
from tarkka.infrastructure.postgres.work_repository import PostgresWorkRepository

pytestmark = [pytest.mark.integration, pytest.mark.external]

_CREATED_AT = datetime(2026, 8, 29, tzinfo=UTC)
_WORK = Work(
    work_id=UUID("00000000-0000-0000-0000-00000000fd11"),
    title="PostgreSQL work-document fixture",
    created_at=_CREATED_AT,
)
_ARTIFACT = Artifact(
    artifact_id=UUID("00000000-0000-0000-0000-00000000fd12"),
    sha256="d" * 64,
    size_bytes=7,
    media_type="text/plain",
    storage_key=PurePosixPath("artifacts/dd/fixture.txt"),
    original_name="fixture.txt",
    acquired_at=_CREATED_AT,
)
_DOCUMENT = Document(
    document_id=UUID("00000000-0000-0000-0000-00000000fd13"),
    artifact_id=_ARTIFACT.artifact_id,
    title="Fixture",
    parser_name="fixture",
    parser_version="1",
    sections=(),
    normalized_at=_CREATED_AT,
)
_LINK = WorkDocumentLink(
    link_id=UUID("00000000-0000-0000-0000-00000000fd14"),
    work_id=_WORK.work_id,
    artifact_id=_ARTIFACT.artifact_id,
    document_id=_DOCUMENT.document_id,
    linked_at=_CREATED_AT,
)
_SECOND_LINK = replace(
    _LINK,
    link_id=UUID("00000000-0000-0000-0000-00000000fd15"),
)


def _settings() -> PostgresSettings:
    return PostgresSettings.from_environment()


@pytest.fixture(scope="module", autouse=True)
def _apply_migrations() -> None:
    upgrade(_settings())


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    with connect(_settings()) as connection:
        connection.execute("TRUNCATE TABLE tarkka.work, tarkka.artifact CASCADE")


def _seed_document_graph(settings: PostgresSettings) -> None:
    PostgresWorkRepository(settings).save_work(_WORK)
    documents = PostgresResearchRepository(settings)
    documents.save_artifact(_ARTIFACT)
    documents.save_document(_DOCUMENT, build_document_manifest(_DOCUMENT, _ARTIFACT))


def test_postgres_work_document_repository_round_trips_and_preserves_first_link_time() -> None:
    settings = _settings()
    _seed_document_graph(settings)
    links = PostgresWorkDocumentRepository(settings)

    links.save_work_document_link(_LINK)
    links.save_work_document_link(
        replace(_LINK, linked_at=datetime(2027, 1, 1, tzinfo=UTC))
    )
    links.save_work_document_link(_SECOND_LINK)

    assert links.list_work_document_links(_WORK.work_id) == (_LINK, _SECOND_LINK)
    assert links.list_document_work_links(_DOCUMENT.document_id) == (_LINK, _SECOND_LINK)


def test_postgres_work_document_repository_rejects_artifact_document_mismatch() -> None:
    settings = _settings()
    _seed_document_graph(settings)
    links = PostgresWorkDocumentRepository(settings)
    mismatched = replace(
        _LINK,
        link_id=UUID("00000000-0000-0000-0000-00000000fd16"),
        artifact_id=UUID("00000000-0000-0000-0000-00000000fd99"),
    )

    with pytest.raises(PostgresOperationError):
        links.save_work_document_link(mismatched)
