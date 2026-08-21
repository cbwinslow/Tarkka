from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.ingest import IngestService, NativePersistenceError
from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore

FIXTURE = Path("tests/fixtures/jats/sample_article.xml")


class _FailOneResourceLink:
    def __init__(self, delegate: JsonSourceObservationRepository) -> None:
        self.delegate = delegate
        self.failed = False

    def save_observation(self, observation: SourceObservation) -> None:
        self.delegate.save_observation(observation)

    def save_resource_link(self, link: ResourceLinkObservation) -> None:
        if not self.failed:
            self.failed = True
            raise OSError("simulated interrupted resource-link write")
        self.delegate.save_resource_link(link)

    def get_observation(self, observation_id: UUID) -> SourceObservation | None:
        return self.delegate.get_observation(observation_id)

    def list_resource_links(
        self, observation_id: UUID
    ) -> tuple[ResourceLinkObservation, ...]:
        return self.delegate.list_resource_links(observation_id)


def _service(
    tmp_path: Path,
    *,
    observations: JsonSourceObservationRepository | _FailOneResourceLink | None = None,
) -> IngestService:
    return IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=JsonResearchRepository(tmp_path / "catalog.json"),
        parsers=(JatsParser(),),
        citation_repository=JsonCitationRepository(tmp_path / "citations.json"),
        source_observation_repository=(
            observations
            if observations is not None
            else JsonSourceObservationRepository(tmp_path / "source_observations.json")
        ),
    )


def test_native_ingest_persists_provenance_citations_and_resources(tmp_path: Path) -> None:
    result = _service(tmp_path).ingest(FIXTURE)

    assert result.native_parse is not None
    observation_id = result.native_parse.observation.observation_id
    document_id = result.document.document_id

    reopened_citations = JsonCitationRepository(tmp_path / "citations.json")
    reopened_observations = JsonSourceObservationRepository(
        tmp_path / "source_observations.json"
    )
    observation = reopened_observations.get_observation(observation_id)

    assert observation is not None
    assert observation.provider_record_id == "pmcid:PMC123456"
    assert len(reopened_observations.list_resource_links(observation_id)) == 1
    assert len(reopened_citations.list_references(document_id)) == 2
    assert len(reopened_citations.list_mentions(document_id)) == 3


def test_reingesting_unchanged_native_source_is_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path)

    first = service.ingest(FIXTURE)
    second = service.ingest(FIXTURE)

    assert first.document.document_id == second.document.document_id
    assert first.native_parse is not None
    observation_id = first.native_parse.observation.observation_id
    observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    assert observations.get_observation(observation_id) is not None
    assert len(observations.list_resource_links(observation_id)) == 1


def test_interrupted_native_persistence_can_resume_by_retry(tmp_path: Path) -> None:
    underlying = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    failing = _FailOneResourceLink(underlying)
    service = _service(tmp_path, observations=failing)

    with pytest.raises(NativePersistenceError, match="retry the same source"):
        service.ingest(FIXTURE)

    result = service.ingest(FIXTURE)

    assert result.native_parse is not None
    observation_id = result.native_parse.observation.observation_id
    assert len(underlying.list_resource_links(observation_id)) == 1
    citations = JsonCitationRepository(tmp_path / "citations.json")
    assert len(citations.list_references(result.document.document_id)) == 2
    assert len(citations.list_mentions(result.document.document_id)) == 3
