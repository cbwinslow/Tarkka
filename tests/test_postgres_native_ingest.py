from __future__ import annotations

from pathlib import Path

import pytest

from tarkka.application.ingest import IngestService
from tarkka.infrastructure.postgres.acquisition_recorder import PostgresAcquisitionRecorder
from tarkka.infrastructure.postgres.citation_context_repository import (
    PostgresCitationContextRepository,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.source_observation_repository import (
    PostgresSourceObservationRepository,
)
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.postgres]

_ROOT = Path(__file__).parents[1]


def _settings() -> PostgresSettings:
    return PostgresSettings.from_environment()


@pytest.fixture(autouse=True)
def _clean_tables(tarkka_postgres_settings: PostgresSettings) -> None:
    with connect(tarkka_postgres_settings) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


def test_native_jats_ingest_persists_the_completed_postgres_slice(tmp_path: Path) -> None:
    settings = _settings()
    citations = PostgresCitationContextRepository(settings)
    observations = PostgresSourceObservationRepository(settings)
    service = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=PostgresResearchRepository(settings),
        parsers=(JatsParser(),),
        acquisition_recorder=PostgresAcquisitionRecorder(settings),
        citation_repository=citations,
        source_observation_repository=observations,
    )

    result = service.ingest(_ROOT / "tests/fixtures/jats/sample_article.xml")

    assert result.native_parse is not None
    assert result.native_parse.document == result.document
    assert observations.get_observation(result.native_parse.observation.observation_id) == (
        result.native_parse.observation
    )
    assert observations.list_resource_links(result.native_parse.observation.observation_id) == (
        result.native_parse.resource_links
    )
    assert citations.list_references(result.document.document_id) == result.native_parse.references
    assert len(citations.list_mentions(result.document.document_id)) == len(
        result.native_parse.mentions
    )
    assert citations.list_contexts(result.document.document_id) == result.native_parse.contexts
