from __future__ import annotations

from pathlib import Path

from tarkka.application.ingest import IngestService
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore

FIXTURE = Path("tests/fixtures/jats/sample_article.xml")


def test_native_ingest_persists_provenance_citations_and_resources(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    citations_path = tmp_path / "citations.json"
    observations_path = tmp_path / "source_observations.json"
    citations = JsonCitationRepository(citations_path)
    observations = JsonSourceObservationRepository(observations_path)
    service = IngestService(
        artifact_store=store,
        repository=documents,
        parsers=(JatsParser(),),
        citation_repository=citations,
        source_observation_repository=observations,
    )

    result = service.ingest(FIXTURE)

    assert result.native_parse is not None
    observation_id = result.native_parse.observation.observation_id
    document_id = result.document.document_id

    reopened_citations = JsonCitationRepository(citations_path)
    reopened_observations = JsonSourceObservationRepository(observations_path)
    observation = reopened_observations.get_observation(observation_id)

    assert observation is not None
    assert observation.provider_record_id == "pmcid:PMC123456"
    assert len(reopened_observations.list_resource_links(observation_id)) == 1
    assert len(reopened_citations.list_references(document_id)) == 2
    assert len(reopened_citations.list_mentions(document_id)) == 3
