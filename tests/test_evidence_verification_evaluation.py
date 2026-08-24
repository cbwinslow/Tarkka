from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.evaluation.verification import GoldEvidenceRelation, evaluate_evidence_relations


def _relation(
    claim_id: UUID,
    evidence_id: UUID | None,
    kind: EvidenceRelationKind,
) -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=uuid4(),
        claim_id=claim_id,
        evidence_id=evidence_id,
        kind=kind,
        verifier_name="fixture",
        verifier_version="1",
        confidence=0.8,
    )


def test_evidence_relation_evaluation_scores_exact_targets_and_labels() -> None:
    claim, evidence, missing = uuid4(), uuid4(), uuid4()
    report = evaluate_evidence_relations(
        (
            _relation(claim, evidence, EvidenceRelationKind.SUPPORTS),
            _relation(claim, missing, EvidenceRelationKind.MENTIONS),
        ),
        (
            GoldEvidenceRelation(claim, EvidenceRelationKind.SUPPORTS, evidence),
            GoldEvidenceRelation(claim, EvidenceRelationKind.CONTRADICTS, missing),
        ),
    )

    assert report.true_positives == 1
    assert report.false_positives == 1
    assert report.false_negatives == 1
    assert report.precision == 0.5
    assert report.recall == 0.5
    assert report.f1 == 0.5
    assert report.label_accuracy == 0.5


def test_evidence_relation_evaluation_handles_no_evidence_and_duplicate_predictions() -> None:
    claim = uuid4()
    report = evaluate_evidence_relations(
        (
            _relation(claim, None, EvidenceRelationKind.NO_EVIDENCE),
            _relation(claim, None, EvidenceRelationKind.NO_EVIDENCE),
        ),
        (GoldEvidenceRelation(claim, EvidenceRelationKind.NO_EVIDENCE),),
    )

    assert report.true_positives == 1
    assert report.false_positives == 1
    assert report.false_negatives == 0
    assert report.label_accuracy == 1.0


def test_evidence_relation_evaluation_rejects_invalid_or_duplicate_gold_targets() -> None:
    claim, evidence = uuid4(), uuid4()
    with pytest.raises(ValueError, match="must not identify evidence"):
        GoldEvidenceRelation(claim, EvidenceRelationKind.NO_EVIDENCE, evidence)
    with pytest.raises(ValueError, match="duplicate gold"):
        evaluate_evidence_relations(
            (),
            (
                GoldEvidenceRelation(claim, EvidenceRelationKind.SUPPORTS, evidence),
                GoldEvidenceRelation(claim, EvidenceRelationKind.CONTRADICTS, evidence),
            ),
        )
