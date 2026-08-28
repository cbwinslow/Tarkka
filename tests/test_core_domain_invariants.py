from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest

from tarkka.domain.extraction import HumanReviewState
from tarkka.domain.identity_candidates import (
    IdentityCandidate,
    IdentityDecision,
    IdentityDecisionRecord,
    IdentityEvidence,
)
from tarkka.domain.source_artifacts import (
    Equation,
    Figure,
    PassageSpan,
    Table,
    TableCellRange,
)
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind


def _identity_evidence() -> IdentityEvidence:
    return IdentityEvidence(
        signal="title_similarity",
        score=0.9,
        detail="normalized titles overlap",
    )


def _identity_candidate() -> IdentityCandidate:
    return IdentityCandidate(
        candidate_id=uuid4(),
        left_provider="openalex",
        left_provider_id="W1",
        right_provider="crossref",
        right_provider_id="10.1000/example",
        confidence=0.9,
        evidence=(_identity_evidence(),),
        left_index=0,
        right_index=1,
    )


def _identity_decision_record() -> IdentityDecisionRecord:
    return IdentityDecisionRecord(
        candidate_id=uuid4(),
        decision=IdentityDecision.ACCEPT,
        snapshot_id=uuid4(),
        left_index=0,
        right_index=1,
        confidence=0.9,
        evidence=(_identity_evidence(),),
        matcher_version="title-year-v1",
    )


def _evidence_relation() -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=uuid4(),
        claim_id=uuid4(),
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="fixture-reviewer",
        verifier_version="1",
        confidence=0.8,
        evidence_id=uuid4(),
    )


@pytest.mark.parametrize("score", [0.0, 1.0])
def test_identity_evidence_accepts_confidence_boundaries(score: float) -> None:
    evidence = replace(_identity_evidence(), score=score)

    assert evidence.score == score


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: replace(_identity_evidence(), signal=" "),
            "signal must not be blank",
        ),
        (
            lambda: replace(_identity_evidence(), score=-0.01),
            "score must be between 0 and 1",
        ),
        (
            lambda: replace(_identity_evidence(), score=1.01),
            "score must be between 0 and 1",
        ),
        (
            lambda: replace(_identity_evidence(), detail=" "),
            "detail must not be blank",
        ),
    ],
)
def test_identity_evidence_rejects_invalid_values(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_identity_candidate_preserves_review_only_contract() -> None:
    candidate = _identity_candidate()

    assert candidate.review_required is True
    assert candidate.matcher_version == "title-year-v1"


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_identity_candidate_accepts_confidence_boundaries(confidence: float) -> None:
    candidate = replace(_identity_candidate(), confidence=confidence)

    assert candidate.confidence == confidence


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: replace(_identity_candidate(), left_provider=" "),
            "providers must not be blank",
        ),
        (
            lambda: replace(_identity_candidate(), right_provider=" "),
            "providers must not be blank",
        ),
        (
            lambda: replace(_identity_candidate(), left_provider_id=" "),
            "provider IDs must not be blank",
        ),
        (
            lambda: replace(_identity_candidate(), right_provider_id=" "),
            "provider IDs must not be blank",
        ),
        (
            lambda: replace(_identity_candidate(), confidence=-0.01),
            "confidence must be between 0 and 1",
        ),
        (
            lambda: replace(_identity_candidate(), confidence=1.01),
            "confidence must be between 0 and 1",
        ),
        (
            lambda: replace(_identity_candidate(), evidence=()),
            "must include evidence",
        ),
        (
            lambda: replace(_identity_candidate(), matcher_version=" "),
            "matcher version must not be blank",
        ),
        (
            lambda: replace(_identity_candidate(), left_index=0, right_index=None),
            "indexes must be supplied together",
        ),
        (
            lambda: replace(_identity_candidate(), left_index=None, right_index=1),
            "indexes must be supplied together",
        ),
        (
            lambda: replace(_identity_candidate(), left_index=-1, right_index=1),
            "indexes must be non-negative",
        ),
        (
            lambda: replace(_identity_candidate(), left_index=0, right_index=-1),
            "indexes must be non-negative",
        ),
        (
            lambda: replace(_identity_candidate(), left_index=1, right_index=1),
            "indexes must be different",
        ),
    ],
)
def test_identity_candidate_rejects_invalid_invariants(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_identity_candidate_allows_omitting_both_snapshot_indexes() -> None:
    candidate = replace(_identity_candidate(), left_index=None, right_index=None)

    assert candidate.left_index is None
    assert candidate.right_index is None


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_identity_decision_accepts_confidence_boundaries(confidence: float) -> None:
    record = replace(_identity_decision_record(), confidence=confidence)

    assert record.confidence == confidence


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: replace(_identity_decision_record(), left_index=-1),
            "indexes must be non-negative",
        ),
        (
            lambda: replace(_identity_decision_record(), right_index=-1),
            "indexes must be non-negative",
        ),
        (
            lambda: replace(_identity_decision_record(), left_index=1, right_index=1),
            "indexes must be different",
        ),
        (
            lambda: replace(_identity_decision_record(), confidence=-0.01),
            "confidence must be between 0 and 1",
        ),
        (
            lambda: replace(_identity_decision_record(), confidence=1.01),
            "confidence must be between 0 and 1",
        ),
        (
            lambda: replace(_identity_decision_record(), evidence=()),
            "must preserve evidence",
        ),
        (
            lambda: replace(_identity_decision_record(), matcher_version=" "),
            "matcher version must not be blank",
        ),
        (
            lambda: replace(_identity_decision_record(), actor=" "),
            "actor must not be blank",
        ),
    ],
)
def test_identity_decision_rejects_invalid_invariants(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: Figure(
                figure_id=uuid4(),
                document_id=uuid4(),
                ordinal=-1,
            ),
            "figure ordinal must be non-negative",
        ),
        (
            lambda: Figure(
                figure_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                page_number=0,
            ),
            "figure page_number must be positive",
        ),
        (
            lambda: Figure(
                figure_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                label=" ",
            ),
            "figure label must not be blank",
        ),
        (
            lambda: Figure(
                figure_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                caption=" ",
            ),
            "figure caption must not be blank",
        ),
        (
            lambda: Figure(
                figure_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                figure_type=" ",
            ),
            "figure type must not be blank",
        ),
    ],
)
def test_figure_rejects_invalid_metadata(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_figure_accepts_minimal_and_boundary_valid_metadata() -> None:
    figure = Figure(
        figure_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        page_number=1,
        label="Figure 1",
        caption="Calibration",
        figure_type="chart",
    )

    assert figure.ordinal == 0
    assert figure.page_number == 1


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: Table(table_id=uuid4(), document_id=uuid4(), ordinal=-1),
            "table ordinal must be non-negative",
        ),
        (
            lambda: Table(
                table_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                page_number=0,
            ),
            "table page_number must be positive",
        ),
        (
            lambda: Table(
                table_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                label=" ",
            ),
            "table label must not be blank",
        ),
        (
            lambda: Table(
                table_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                caption=" ",
            ),
            "table caption must not be blank",
        ),
        (
            lambda: Table(
                table_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                row_count=-1,
            ),
            "table row_count must be non-negative",
        ),
        (
            lambda: Table(
                table_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                column_count=-1,
            ),
            "table column_count must be non-negative",
        ),
    ],
)
def test_table_rejects_invalid_metadata(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_table_accepts_zero_dimensions_and_first_page() -> None:
    table = Table(
        table_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        page_number=1,
        row_count=0,
        column_count=0,
    )

    assert table.row_count == 0
    assert table.column_count == 0


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: Equation(
                equation_id=uuid4(),
                document_id=uuid4(),
                ordinal=-1,
            ),
            "equation ordinal must be non-negative",
        ),
        (
            lambda: Equation(
                equation_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                page_number=0,
            ),
            "equation page_number must be positive",
        ),
        (
            lambda: Equation(
                equation_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                label=" ",
            ),
            "equation label must not be blank",
        ),
        (
            lambda: Equation(
                equation_id=uuid4(),
                document_id=uuid4(),
                ordinal=0,
                source_text=" ",
            ),
            "equation source_text must not be blank",
        ),
    ],
)
def test_equation_rejects_invalid_metadata(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_equation_accepts_first_page_and_nonblank_source() -> None:
    equation = Equation(
        equation_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        page_number=1,
        source_text="p = 1 / (1 + exp(-x))",
    )

    assert equation.page_number == 1


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 1), (0, 0), (1, 0)],
)
def test_passage_span_rejects_invalid_ranges(start: int, end: int) -> None:
    with pytest.raises(ValueError, match="invalid passage span"):
        PassageSpan(
            section_id=uuid4(),
            passage_id=uuid4(),
            char_start=start,
            char_end=end,
        )


def test_passage_span_accepts_smallest_nonempty_range() -> None:
    span = PassageSpan(
        section_id=uuid4(),
        passage_id=uuid4(),
        char_start=0,
        char_end=1,
    )

    assert (span.char_start, span.char_end) == (0, 1)


@pytest.mark.parametrize(
    ("row_start", "row_end", "column_start", "column_end", "message"),
    [
        (-1, 1, 0, 1, "starts must be non-negative"),
        (0, 1, -1, 1, "starts must be non-negative"),
        (0, 0, 0, 1, "must be non-empty"),
        (1, 0, 0, 1, "must be non-empty"),
        (0, 1, 0, 0, "must be non-empty"),
        (0, 1, 1, 0, "must be non-empty"),
    ],
)
def test_table_cell_range_rejects_invalid_ranges(
    row_start: int,
    row_end: int,
    column_start: int,
    column_end: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        TableCellRange(
            table_id=uuid4(),
            row_start=row_start,
            row_end=row_end,
            column_start=column_start,
            column_end=column_end,
        )


def test_table_cell_range_accepts_smallest_nonempty_range() -> None:
    cell_range = TableCellRange(
        table_id=uuid4(),
        row_start=0,
        row_end=1,
        column_start=0,
        column_end=1,
    )

    assert cell_range.row_end - cell_range.row_start == 1
    assert cell_range.column_end - cell_range.column_start == 1


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_evidence_relation_accepts_confidence_boundaries(confidence: float) -> None:
    relation = replace(_evidence_relation(), confidence=confidence)

    assert relation.confidence == confidence


def test_no_evidence_relation_requires_absent_evidence_id() -> None:
    relation = replace(
        _evidence_relation(),
        kind=EvidenceRelationKind.NO_EVIDENCE,
        evidence_id=None,
    )

    assert relation.kind is EvidenceRelationKind.NO_EVIDENCE
    assert relation.evidence_id is None


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: replace(
                _evidence_relation(),
                kind=cast(EvidenceRelationKind, "supports"),
            ),
            "kind must be an EvidenceRelationKind",
        ),
        (
            lambda: replace(_evidence_relation(), verifier_name=" "),
            "verifier name/version must not be blank",
        ),
        (
            lambda: replace(_evidence_relation(), verifier_version=" "),
            "verifier name/version must not be blank",
        ),
        (
            lambda: replace(_evidence_relation(), confidence=-0.01),
            "confidence must be between 0 and 1",
        ),
        (
            lambda: replace(_evidence_relation(), confidence=1.01),
            "confidence must be between 0 and 1",
        ),
        (
            lambda: replace(
                _evidence_relation(),
                human_review_state=cast(HumanReviewState, "verified"),
            ),
            "review state must be a HumanReviewState",
        ),
        (
            lambda: replace(_evidence_relation(), reasoning_summary=" "),
            "reasoning summary must not be blank",
        ),
        (
            lambda: replace(
                _evidence_relation(),
                kind=EvidenceRelationKind.NO_EVIDENCE,
                evidence_id=uuid4(),
            ),
            "no_evidence relation must not identify evidence",
        ),
        (
            lambda: replace(_evidence_relation(), evidence_id=None),
            "must identify exact evidence",
        ),
    ],
)
def test_evidence_relation_rejects_invalid_invariants(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
