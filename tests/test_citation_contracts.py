from __future__ import annotations

from dataclasses import FrozenInstanceError
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


def test_bibliographic_reference_preserves_native_representation_immutably() -> None:
    identifiers = {"doi": "10.1000/example"}
    authors = ["Ada Lovelace", "Grace Hopper"]

    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=3,
        raw_text="Lovelace A, Hopper G. Example paper. 2024.",
        identifiers=identifiers,
        title="Example paper",
        authors=authors,
        publication_year=2024,
        source_anchor="ref-4",
        source_observation_id=uuid4(),
    )

    identifiers["pmid"] = "123"
    authors.append("New Author")

    assert dict(reference.identifiers) == {"doi": "10.1000/example"}
    assert reference.authors == ("Ada Lovelace", "Grace Hopper")
    with pytest.raises(TypeError):
        reference.identifiers["pmid"] = "123"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        reference.raw_text = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"ordinal": -1}, "ordinal"),
        ({"raw_text": "   "}, "raw_text"),
        ({"title": ""}, "title"),
        ({"publication_year": -1}, "publication_year"),
        ({"source_anchor": ""}, "source_anchor"),
        ({"identifiers": {"": "x"}}, "identifier schemes"),
        ({"identifiers": {"doi": ""}}, "identifier values"),
        ({"authors": ("",)}, "authors"),
    ],
)
def test_bibliographic_reference_rejects_invalid_source_data(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "reference_id": uuid4(),
        "document_id": uuid4(),
        "ordinal": 0,
        "raw_text": "Reference text",
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        BibliographicReference(**values)  # type: ignore[arg-type]


def test_citation_mention_can_remain_unlinked_to_bibliography() -> None:
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=uuid4(),
        raw_text="[17]",
        char_start=10,
        char_end=14,
        source_anchor="xref-17",
    )

    assert mention.reference_id is None


def test_citation_mention_requires_complete_valid_character_bounds() -> None:
    with pytest.raises(ValueError, match="supplied together"):
        CitationMention(
            mention_id=uuid4(),
            document_id=uuid4(),
            raw_text="[1]",
            char_start=1,
        )

    with pytest.raises(ValueError, match="invalid citation mention"):
        CitationMention(
            mention_id=uuid4(),
            document_id=uuid4(),
            raw_text="[1]",
            char_start=4,
            char_end=3,
        )


def test_citation_context_range_must_match_text_exactly() -> None:
    context = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=uuid4(),
        text="prior work [4] supports this",
        char_start=20,
        char_end=48,
    )

    assert context.char_end - context.char_start == len(context.text)

    with pytest.raises(ValueError, match="match text length"):
        CitationContext(
            context_id=uuid4(),
            mention_id=uuid4(),
            document_id=uuid4(),
            text="abc",
            char_start=5,
            char_end=9,
        )


def test_resolved_citation_requires_exactly_one_canonical_work() -> None:
    work_id = uuid4()
    resolution = CitationResolution(
        resolution_id=uuid4(),
        reference_id=uuid4(),
        status=CitationResolutionStatus.RESOLVED,
        work_id=work_id,
        resolver="doi_exact",
    )

    assert resolution.work_id == work_id
    assert resolution.candidate_work_ids == ()

    with pytest.raises(ValueError, match="identify a canonical work"):
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=uuid4(),
            status=CitationResolutionStatus.RESOLVED,
        )


def test_ambiguous_citation_fails_closed_and_retains_candidates() -> None:
    first = uuid4()
    second = uuid4()
    resolution = CitationResolution(
        resolution_id=uuid4(),
        reference_id=uuid4(),
        status=CitationResolutionStatus.AMBIGUOUS,
        candidate_work_ids=(first, second),
        resolver="title_author_candidate",
    )

    assert resolution.work_id is None
    assert resolution.candidate_work_ids == (first, second)

    with pytest.raises(ValueError, match="at least two candidates"):
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=uuid4(),
            status=CitationResolutionStatus.AMBIGUOUS,
            candidate_work_ids=(first,),
        )

    with pytest.raises(ValueError, match="must not select"):
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=uuid4(),
            status=CitationResolutionStatus.AMBIGUOUS,
            work_id=first,
            candidate_work_ids=(first, second),
        )


def test_unresolved_and_rejected_citations_cannot_smuggle_identity() -> None:
    for status in (CitationResolutionStatus.UNRESOLVED, CitationResolutionStatus.REJECTED):
        with pytest.raises(ValueError, match="must not select"):
            CitationResolution(
                resolution_id=uuid4(),
                reference_id=uuid4(),
                status=status,
                work_id=uuid4(),
            )


def test_work_relation_requires_distinct_works_and_provenance() -> None:
    subject = uuid4()
    object_work = uuid4()
    observation_id = uuid4()

    relation = WorkRelation(
        relation_id=uuid4(),
        subject_work_id=subject,
        object_work_id=object_work,
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_observation_id=observation_id,
    )

    assert relation.source_observation_id == observation_id

    with pytest.raises(ValueError, match="endpoints must be distinct"):
        WorkRelation(
            relation_id=uuid4(),
            subject_work_id=subject,
            object_work_id=subject,
            kind=WorkRelationKind.RELATED,
            basis=ObservationBasis.INFERRED,
            source_observation_id=observation_id,
        )

    with pytest.raises(ValueError, match="provenance source"):
        WorkRelation(
            relation_id=uuid4(),
            subject_work_id=subject,
            object_work_id=object_work,
            kind=WorkRelationKind.RELATED,
            basis=ObservationBasis.INFERRED,
        )


def test_work_relation_can_trace_to_document_reference_without_provider_observation() -> None:
    reference_id = uuid4()
    document_id = uuid4()
    relation = WorkRelation(
        relation_id=uuid4(),
        subject_work_id=uuid4(),
        object_work_id=uuid4(),
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_document_id=document_id,
        source_reference_id=reference_id,
    )

    assert relation.source_document_id == document_id
    assert relation.source_reference_id == reference_id
