from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from tarkka.application.citation_context import build_citation_contexts
from tarkka.domain.manifest import build_document_manifest
from tarkka.domain.models import Artifact
from tarkka.infrastructure.postgres.citation_context_repository import (
    PostgresCitationConflictError,
    PostgresCitationContextRepository,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.migrations import upgrade
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.ports.parsing import NativeDocumentParseResult

pytestmark = [pytest.mark.integration, pytest.mark.external]

_ROOT = Path(__file__).parents[1]
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000c701")
_ACQUIRED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _settings() -> PostgresSettings:
    return PostgresSettings.from_environment()


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="c" * 64,
        size_bytes=2048,
        media_type="application/xml",
        storage_key=PurePosixPath("artifacts/cc/sample_article.xml"),
        original_name="sample_article.xml",
        acquired_at=_ACQUIRED_AT,
        source_uri="https://example.test/sample_article.xml",
    )


@pytest.fixture(scope="module", autouse=True)
def _apply_migrations() -> None:
    upgrade(_settings())


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    with connect(_settings()) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


@pytest.fixture
def native_parse() -> NativeDocumentParseResult:
    artifact = _artifact()
    result = JatsParser().parse_native(artifact, _ROOT / "tests/fixtures/jats/sample_article.xml")
    documents = PostgresResearchRepository(_settings())
    documents.save_artifact(artifact)
    documents.save_document(result.document, build_document_manifest(result.document, artifact))
    return result


@pytest.fixture
def repository() -> PostgresCitationContextRepository:
    return PostgresCitationContextRepository(_settings())


def test_postgres_native_citation_context_persistence_round_trips(
    repository: PostgresCitationContextRepository, native_parse: NativeDocumentParseResult
) -> None:
    for reference in native_parse.references:
        repository.save_reference(reference)
        repository.save_reference(reference)
    for mention in native_parse.mentions:
        repository.save_mention(mention)
        repository.save_mention(mention)
    for context in native_parse.contexts:
        repository.save_context(context)
        repository.save_context(context)

    document_id = native_parse.document.document_id
    assert repository.list_references(document_id) == native_parse.references
    assert repository.list_mentions(document_id) == tuple(
        sorted(
            native_parse.mentions,
            key=lambda mention: (
                mention.char_start is None,
                mention.char_start if mention.char_start is not None else 0,
                mention.source_anchor or "",
                mention.mention_id,
            ),
        )
    )
    assert repository.list_contexts(document_id) == native_parse.contexts


def test_postgres_native_citation_context_persistence_rejects_conflicts(
    repository: PostgresCitationContextRepository, native_parse: NativeDocumentParseResult
) -> None:
    reference = native_parse.references[0]
    repository.save_reference(reference)

    with pytest.raises(PostgresCitationConflictError, match="bibliographic_reference"):
        repository.save_reference(replace(reference, raw_text="different source-native reference"))


def test_postgres_context_persistence_derives_section_from_anchored_passage(
    repository: PostgresCitationContextRepository, native_parse: NativeDocumentParseResult
) -> None:
    for reference in native_parse.references:
        repository.save_reference(reference)
    for mention in native_parse.mentions:
        repository.save_mention(mention)
    original = build_citation_contexts(native_parse.document, native_parse.mentions)[0]
    assert original.passage_id is not None
    assert original.section_id is not None

    repository.save_context(replace(original, section_id=None))

    assert repository.list_contexts(native_parse.document.document_id) == (original,)
