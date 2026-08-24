"""Offline evaluation helpers for Tarkka extraction workflows."""

from tarkka.evaluation.claims import (
    ClaimEvaluationReport,
    GoldClaim,
    GoldEvidenceSpan,
    evaluate_claims,
)
from tarkka.evaluation.verification import (
    EvidenceRelationEvaluationReport,
    GoldEvidenceRelation,
    evaluate_evidence_relations,
)

__all__ = [
    "ClaimEvaluationReport",
    "GoldClaim",
    "GoldEvidenceSpan",
    "evaluate_claims",
    "EvidenceRelationEvaluationReport",
    "GoldEvidenceRelation",
    "evaluate_evidence_relations",
]
