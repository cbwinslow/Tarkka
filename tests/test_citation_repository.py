from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

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


def test_json_citation_repository_round_trips_full_citation_graph(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document_id,
        ordinal=2,
        raw_text="Example reference",
        identifiers={"doi": "10.1000/example"},
        source_observation_id=uuid4(),
    )
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document_id,
        raw_text="[2]",
        reference_id=reference.reference_id,
        char_start=10,
        char_end=13,
    )
    context = CitationContext(
        context_id=uuid4(),
        mention_id=mention.mention_id,
        document_id=document_id,
        text="See [2]",
        char_start=6,
        char_end=13,
    )
    cited_work_id = uuid4()
    resolution = CitationResolution(
        resolution_id=uuid4(),
        reference_id=reference.reference_id,
        status=CitationResolutionStatus.RESOLVED,
        work_id=cited_work_id,
        resolver="exact_identifier",
        source_observation_id=reference.source_observation_id,
    )
    citing_work_id = uuid4()
    relation = WorkRelation(
        relation_id=uuid4(),
        subject_work_id=citing_work_id,
        object_work_id=cited_work_id,
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_document_id=document_id,
        source_reference_id=reference.reference_id,
    )

    repository.save_reference(reference)
    repository.save_mention(mention)
    repository.save_context(context)
    repository.save_resolution(resolution)
    repository.save_relation(relation)

    reopened = JsonCitationRepository(tmp_path / "citations.json")
    assert reopened.list_references(document_id) == (reference,)
    assert reopened.list_mentions(document_id) == (mention,)
    assert reopened.list_contexts(document_id) == (context,)
    assert reopened.get_resolution(reference.reference_id) == resolution
    assert reopened.list_relations_from(citing_work_id) == (relation,)
    assert reopened.list_relations_to(cited_work_id) == (relation,)


def test_json_citation_repository_is_idempotent_for_identical_content(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Example reference",
    )

    repository.save_reference(reference)
    repository.save_reference(reference)

    assert repository.list_references(reference.document_id) == (reference,)


def test_json_citation_repository_rejects_conflicting_stable_ids(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Example reference",
    )
    repository.save_reference(reference)

    with pytest.raises(CitationConflictError, match="conflicting reference"):
        repository.save_reference(replace(reference, raw_text="Different reference"))


def test_resolution_key_is_reference_identity_not_resolution_identity(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    reference_id = uuid4()
    first = CitationResolution(
        resolution_id=uuid4(),
        reference_id=reference_id,
        status=CitationResolutionStatus.UNRESOLVED,
        resolver="exact_identifier",
    )
    repository.save_resolution(first)

    with pytest.raises(CitationConflictError, match="conflicting resolution"):
        repository.save_resolution(
            CitationResolution(
                resolution_id=uuid4(),
                reference_id=reference_id,
                status=CitationResolutionStatus.RESOLVED,
                work_id=uuid4(),
                resolver="manual_review",
            )
        )


def test_repository_orders_references_and_mentions_deterministically(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    later_reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document_id,
        ordinal=5,
        raw_text="Later",
    )
    earlier_reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document_id,
        ordinal=1,
        raw_text="Earlier",
    )
    later_mention = CitationMention(
        mention_id=uuid4(),
        document_id=document_id,
        raw_text="[5]",
        char_start=20,
        char_end=23,
    )
    earlier_mention = CitationMention(
        mention_id=uuid4(),
        document_id=document_id,
        raw_text="[1]",
        char_start=2,
        char_end=5,
    )

    repository.save_reference(later_reference)
    repository.save_reference(earlier_reference)
    repository.save_mention(later_mention)
    repository.save_mention(earlier_mention)

    assert repository.list_references(document_id) == (earlier_reference, later_reference)
    assert repository.list_mentions(document_id) == (earlier_mention, later_mention)
