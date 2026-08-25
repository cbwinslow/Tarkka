from __future__ import annotations

from dataclasses import replace
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
    SourceObservationConflictError,
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

    def list_resource_links(self, observation_id: UUID) -> tuple[ResourceLinkObservation, ...]:
        return self.delegate.list_resource_links(observation_id)


class _FailCitationWrite:
    def save_reference(self, _: object) -> None:
        raise OSError("simulated transient database interruption")

    def save_mention(self, _: object) -> None:
        raise AssertionError("citation writes stop after the first interruption")

    def save_context(self, _: object) -> None:
        raise AssertionError("citation writes stop after the first interruption")


def _service(
    tmp_path: Path,
    *,
    observations: JsonSourceObservationRepository | _FailOneResourceLink | None = None,
    citations: JsonCitationRepository | _FailCitationWrite | None = None,
) -> IngestService:
    return IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=JsonResearchRepository(tmp_path / "catalog.json"),
        parsers=(JatsParser(),),
        citation_repository=(
            citations
            if citations is not None
            else JsonCitationRepository(tmp_path / "citations.json")
        ),
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
    reopened_observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    observation = reopened_observations.get_observation(observation_id)

    assert observation is not None
    assert observation.provider_record_id == "pmcid:PMC123456"
    assert len(reopened_observations.list_resource_links(observation_id)) == 1
    assert len(reopened_citations.list_references(document_id)) == 2
    assert len(reopened_citations.list_mentions(document_id)) == 3

    contexts = reopened_citations.list_contexts(document_id)
    assert len(contexts) == 3
    assert [context.text for context in contexts].count(
        "We preserve native structure and cite [1]."
    ) == 1
    assert [context.text for context in contexts].count("The model follows [1,2].") == 2
    assert all(context.passage_id is not None for context in contexts)
    assert all(context.section_id is not None for context in contexts)
    assert {context.context_id for context in result.native_parse.contexts} == {
        context.context_id for context in contexts
    }


def test_reingesting_unchanged_native_source_is_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path)

    first = service.ingest(FIXTURE)
    second = service.ingest(FIXTURE)

    assert first.document.document_id == second.document.document_id
    assert first.native_parse is not None
    assert second.native_parse is not None
    assert {context.context_id for context in first.native_parse.contexts} == {
        context.context_id for context in second.native_parse.contexts
    }
    observation_id = first.native_parse.observation.observation_id
    observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    assert observations.get_observation(observation_id) is not None
    assert len(observations.list_resource_links(observation_id)) == 1
    citations = JsonCitationRepository(tmp_path / "citations.json")
    assert len(citations.list_contexts(first.document.document_id)) == 3


def test_conflicting_stable_observation_is_not_retryable(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.ingest(FIXTURE)
    assert result.native_parse is not None

    observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    conflicting = replace(result.native_parse.observation, source_name="different-parser")

    with pytest.raises(SourceObservationConflictError, match="conflicting observations"):
        observations.save_observation(conflicting)


def test_interrupted_native_persistence_can_resume_by_retry(tmp_path: Path) -> None:
    underlying = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    failing = _FailOneResourceLink(underlying)
    service = _service(tmp_path, observations=failing)

    with pytest.raises(NativePersistenceError, match="retry the same immutable source"):
        service.ingest(FIXTURE)

    result = service.ingest(FIXTURE)

    assert result.native_parse is not None
    observation_id = result.native_parse.observation.observation_id
    assert len(underlying.list_resource_links(observation_id)) == 1
    citations = JsonCitationRepository(tmp_path / "citations.json")
    assert len(citations.list_references(result.document.document_id)) == 2
    assert len(citations.list_mentions(result.document.document_id)) == 3
    assert len(citations.list_contexts(result.document.document_id)) == 3


def test_transient_native_repository_errors_are_retryable(tmp_path: Path) -> None:
    service = _service(tmp_path, citations=_FailCitationWrite())

    with pytest.raises(NativePersistenceError, match="retry the same immutable source"):
        service.ingest(FIXTURE)
