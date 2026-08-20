"""Offline evaluation helpers for Tarkka extraction workflows."""

from tarkka.evaluation.claims import (
    ClaimEvaluationReport,
    GoldClaim,
    GoldEvidenceSpan,
    evaluate_claims,
)

__all__ = [
    "ClaimEvaluationReport",
    "GoldClaim",
    "GoldEvidenceSpan",
    "evaluate_claims",
]
