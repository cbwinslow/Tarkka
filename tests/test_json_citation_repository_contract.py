from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from tarkka.domain.citations import (
    BibliographicReference,
    CitationContext,
    CitationMention,
    CitationResolution,
    CitationResolutionStatus,
    WorkRelation,
    WorkRelationKind,
)
from tarkka.domain.source_observations import ObservationBasis
from tarkka.infrastructure.storage.json_citation_repository import (
    CitationConflictError,
    JsonCitationRepository,
)
from tests.contracts.citation_repository import CitationRepositoryContract

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000b01")
_REFERENCE_ID = UUID("00000000-0000-0000-0000-000000000b02")
_MENTION_ID = UUID("00000000-0000-0000-0000-000000000b03")
_CONTEXT_ID = UUID("00000000-0000-0000-0000-000000000b04")
_RESOLUTION_ID = UUID("00000000-0000-0000-0000-000000000b05")
_CITING_WORK_ID = UUID("00000000-0000-0000-0000-000000000b06")
_CITED_WORK_ID = UUID("00000000-0000-0000-0000-000000000b07")
_DATASET_WORK_ID = UUID("00000000-0000-0000-0000-000000000b08")
_RELATION_ID = UUID("00000000-0000-0000-0000-000000000b09")
_OUTBOUND_RELATION_ID = UUID("00000000-0000-0000-0000-000000000b0a")
_CONFLICTING_RESOLUTION_ID = UUID("00000000-0000-0000-0000-000000000b0b")
_SOURCE_OBSERVATION_ID = UUID("00000000-0000-0000-0000-000000000b0c")
_SECTION_ID = UUID("00000000-0000-0000-0000-000000000b0d")
_PASSAGE_ID = UUID("00000000-0000-0000-0000-000000000b0e")
_CANDIDATE_WORK_A = UUID("00000000-0000-0000-0000-000000000b0f")
_CANDIDATE_WORK_B = UUID("00000000-0000-0000-0000-000000000b10")
_OTHER_CITING_WORK_ID = UUID("00000000-0000-0000-0000-000000000b11")
_INBOUND_RELATION_ID = UUID("00000000-0000-0000-0000-000000000b12")
_MISSING_REFERENCE_ID = UUID("00000000-0000-0000-0000-000000000b13")
_MISSING_RELATION_ID = UUID("00000000-0000-0000-0000-000000000b14")
_OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _reference() -> BibliographicReference:
    return BibliographicReference(
        reference_id=_REFERENCE_ID,
        document_id=_DOCUMENT_ID,
        ordinal=2,
        raw_text="Example reference",
        identifiers={"doi": "10.1000/example"},
        title="Evidence first",
        authors=("A. Researcher",),
        publication_year=2026,
        source_anchor="ref-2",
        source_observation_id=_SOURCE_OBSERVATION_ID,
    )


def _mention() -> CitationMention:
    return CitationMention(
        mention_id=_MENTION_ID,
        document_id=_DOCUMENT_ID,
        raw_text="[2]",
        reference_id=_REFERENCE_ID,
        section_id=_SECTION_ID,
        passage_id=_PASSAGE_ID,
        char_start=10,
        char_end=13,
        source_anchor="cite-2",
        source_observation_id=_SOURCE_OBSERVATION_ID,
    )


def _context() -> CitationContext:
    return CitationContext(
        context_id=_CONTEXT_ID,
        mention_id=_MENTION_ID,
        document_id=_DOCUMENT_ID,
        text="See [2]",
        char_start=6,
        char_end=13,
        section_id=_SECTION_ID,
        passage_id=_PASSAGE_ID,
    )


def _resolution() -> CitationResolution:
    return CitationResolution(
        resolution_id=_RESOLUTION_ID,
        reference_id=_REFERENCE_ID,
        status=CitationResolutionStatus.RESOLVED,
        work_id=_CITED_WORK_ID,
        resolver="exact_identifier",
        source_observation_id=_SOURCE_OBSERVATION_ID,
        resolved_at=_OBSERVED_AT,
    )


def _relation() -> WorkRelation:
    return WorkRelation(
        relation_id=_RELATION_ID,
        subject_work_id=_CITING_WORK_ID,
        object_work_id=_CITED_WORK_ID,
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_observation_id=_SOURCE_OBSERVATION_ID,
        source_document_id=_DOCUMENT_ID,
        source_reference_id=_REFERENCE_ID,
        created_at=_OBSERVED_AT,
    )


def _outbound_peer() -> WorkRelation:
    return WorkRelation(
        relation_id=_OUTBOUND_RELATION_ID,
        subject_work_id=_CITING_WORK_ID,
        object_work_id=_DATASET_WORK_ID,
        kind=WorkRelationKind.USES_DATASET,
        basis=ObservationBasis.NATIVE,
        source_observation_id=_SOURCE_OBSERVATION_ID,
        source_document_id=_DOCUMENT_ID,
        created_at=_OBSERVED_AT + timedelta(seconds=1),
    )


def _inbound_peer() -> WorkRelation:
    return WorkRelation(
        relation_id=_INBOUND_RELATION_ID,
        subject_work_id=_OTHER_CITING_WORK_ID,
        object_work_id=_CITED_WORK_ID,
        kind=WorkRelationKind.RELATED,
        basis=ObservationBasis.NATIVE,
        source_observation_id=_SOURCE_OBSERVATION_ID,
        source_document_id=_DOCUMENT_ID,
        created_at=_OBSERVED_AT + timedelta(seconds=2),
    )


def test_json_citation_repository_satisfies_missing_read_contract(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")

    CitationRepositoryContract.assert_missing_reads_are_empty(
        repository,
        _MISSING_REFERENCE_ID,
        _MISSING_RELATION_ID,
    )


def test_json_citation_repository_satisfies_graph_round_trip_contract(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")

    CitationRepositoryContract.assert_graph_round_trip(
        repository,
        _reference(),
        _mention(),
        _context(),
        _resolution(),
        _relation(),
    )


def test_json_citation_repository_reference_save_is_idempotent(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")

    CitationRepositoryContract.assert_reference_save_is_idempotent(repository, _reference())


def test_json_citation_repository_fails_closed_on_reference_conflict(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    original = _reference()

    CitationRepositoryContract.assert_reference_conflict_fails_closed(
        repository,
        original,
        replace(original, raw_text="Different reference"),
        CitationConflictError,
    )


def test_json_citation_repository_allows_resolution_state_evolution(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    first = CitationResolution(
        resolution_id=_RESOLUTION_ID,
        reference_id=_REFERENCE_ID,
        status=CitationResolutionStatus.UNRESOLVED,
        resolver="exact_identifier",
        source_observation_id=_SOURCE_OBSERVATION_ID,
        resolved_at=_OBSERVED_AT,
    )
    ambiguous = CitationResolution(
        resolution_id=_RESOLUTION_ID,
        reference_id=_REFERENCE_ID,
        status=CitationResolutionStatus.AMBIGUOUS,
        candidate_work_ids=(_CANDIDATE_WORK_A, _CANDIDATE_WORK_B),
        resolver="fuzzy_identity",
        source_observation_id=_SOURCE_OBSERVATION_ID,
        resolved_at=_OBSERVED_AT + timedelta(seconds=1),
    )
    evolved = _resolution()
    conflicting_identity = replace(
        evolved,
        resolution_id=_CONFLICTING_RESOLUTION_ID,
    )

    CitationRepositoryContract.assert_resolution_can_evolve(
        repository,
        first,
        ambiguous,
        evolved,
        conflicting_identity,
        CitationConflictError,
    )


def test_json_citation_repository_get_or_create_relation_is_idempotent(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    first = _relation()
    later = replace(first, created_at=_OBSERVED_AT + timedelta(days=1))

    CitationRepositoryContract.assert_relation_get_or_create_is_idempotent(
        repository,
        first,
        later,
    )


def test_json_citation_repository_get_or_create_relation_is_atomic(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")

    CitationRepositoryContract.assert_relation_get_or_create_is_atomic(
        repository,
        _relation(),
    )


def test_json_citation_repository_rejects_incompatible_relation_identity(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    original = _relation()
    conflicting = replace(original, object_work_id=_DATASET_WORK_ID)

    CitationRepositoryContract.assert_relation_conflict_fails_closed(
        repository,
        original,
        conflicting,
        CitationConflictError,
    )


def test_json_citation_repository_enforces_bidirectional_query_bounds(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")

    CitationRepositoryContract.assert_relation_query_bounds(
        repository,
        _relation(),
        _outbound_peer(),
        _inbound_peer(),
    )
