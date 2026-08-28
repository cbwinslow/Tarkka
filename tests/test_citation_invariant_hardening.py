from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest

from tarkka.domain.citations import (
    CitationContext,
    CitationMention,
    CitationResolution,
    CitationResolutionStatus,
    WorkRelation,
    WorkRelationKind,
)
from tarkka.domain.source_observations import ObservationBasis

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_citation_mention_rejects_blank_text_and_source_anchor() -> None:
    with pytest.raises(ValueError, match="raw_text"):
        CitationMention(mention_id=uuid4(), document_id=uuid4(), raw_text=" ")

    with pytest.raises(ValueError, match="source_anchor"):
        CitationMention(
            mention_id=uuid4(),
            document_id=uuid4(),
            raw_text="[1]",
            source_anchor=" ",
        )


def test_citation_context_rejects_blank_text_and_invalid_range() -> None:
    with pytest.raises(ValueError, match="text must not be blank"):
        CitationContext(
            context_id=uuid4(),
            mention_id=uuid4(),
            document_id=uuid4(),
            text=" ",
            char_start=0,
            char_end=1,
        )

    with pytest.raises(ValueError, match="invalid citation context"):
        CitationContext(
            context_id=uuid4(),
            mention_id=uuid4(),
            document_id=uuid4(),
            text="abc",
            char_start=-1,
            char_end=2,
        )

    with pytest.raises(ValueError, match="invalid citation context"):
        CitationContext(
            context_id=uuid4(),
            mention_id=uuid4(),
            document_id=uuid4(),
            text="abc",
            char_start=4,
            char_end=3,
        )


def test_citation_resolution_validates_enum_resolver_and_candidate_uniqueness() -> None:
    with pytest.raises(ValueError, match="CitationResolutionStatus"):
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=uuid4(),
            status=cast(CitationResolutionStatus, "resolved"),
        )

    with pytest.raises(ValueError, match="resolver"):
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=uuid4(),
            status=CitationResolutionStatus.UNRESOLVED,
            resolver=" ",
        )

    candidate = uuid4()
    with pytest.raises(ValueError, match="candidates must be unique"):
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=uuid4(),
            status=CitationResolutionStatus.AMBIGUOUS,
            candidate_work_ids=(candidate, candidate),
        )


def test_resolved_citation_cannot_retain_candidates() -> None:
    with pytest.raises(ValueError, match="must not retain ambiguous candidates"):
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=uuid4(),
            status=CitationResolutionStatus.RESOLVED,
            work_id=uuid4(),
            candidate_work_ids=(uuid4(), uuid4()),
        )


@pytest.mark.parametrize(
    "status",
    [CitationResolutionStatus.UNRESOLVED, CitationResolutionStatus.REJECTED],
)
def test_unresolved_or_rejected_citation_cannot_retain_candidates(
    status: CitationResolutionStatus,
) -> None:
    with pytest.raises(ValueError, match="must not retain candidates"):
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=uuid4(),
            status=status,
            candidate_work_ids=(uuid4(),),
        )


def test_work_relation_validates_enums_and_allows_source_self_citation() -> None:
    subject = uuid4()
    source_observation_id = uuid4()

    relation = WorkRelation(
        relation_id=uuid4(),
        subject_work_id=subject,
        object_work_id=subject,
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_observation_id=source_observation_id,
    )
    assert relation.subject_work_id == relation.object_work_id

    with pytest.raises(ValueError, match="WorkRelationKind"):
        WorkRelation(
            relation_id=uuid4(),
            subject_work_id=uuid4(),
            object_work_id=uuid4(),
            kind=cast(WorkRelationKind, "related"),
            basis=ObservationBasis.NATIVE,
            source_observation_id=source_observation_id,
        )

    with pytest.raises(ValueError, match="ObservationBasis"):
        WorkRelation(
            relation_id=uuid4(),
            subject_work_id=uuid4(),
            object_work_id=uuid4(),
            kind=WorkRelationKind.RELATED,
            basis=cast(ObservationBasis, "native"),
            source_observation_id=source_observation_id,
        )
