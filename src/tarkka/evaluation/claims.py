from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.domain.extraction import AttributionKind, Claim, ExtractionBatch


@dataclass(frozen=True, slots=True, order=True)
class GoldEvidenceSpan:
    """Expected exact normalized passage-local evidence span."""

    passage_id: UUID
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("invalid gold evidence character range")


@dataclass(frozen=True, slots=True)
class GoldClaim:
    """Gold claim label keyed by exact supporting evidence rather than wording."""

    evidence: tuple[GoldEvidenceSpan, ...]
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("gold claim must contain evidence")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("gold claim evidence spans must be unique")


@dataclass(frozen=True, slots=True)
class ClaimEvaluationReport:
    """Exact-evidence claim detection metrics for one extraction batch."""

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    attribution_accuracy: float | None


@dataclass(frozen=True, slots=True)
class _PredictedClaim:
    claim: Claim
    evidence: frozenset[GoldEvidenceSpan]


def evaluate_claims(
    batch: ExtractionBatch,
    gold: tuple[GoldClaim, ...],
) -> ClaimEvaluationReport:
    """Evaluate claim detection by exact evidence-set matching.

    Claim wording is intentionally excluded from matching so deterministic
    extracts and model paraphrases can be compared using the same source-grounded
    labels. Each gold item can match at most one prediction; duplicate predictions
    therefore count as false positives.
    """
    predictions = _claim_predictions(batch)
    unmatched_gold = list(gold)
    matched_attribution = 0
    true_positives = 0

    for prediction in predictions:
        match_index = _find_gold_match(prediction, unmatched_gold)
        if match_index is None:
            continue
        expected = unmatched_gold.pop(match_index)
        true_positives += 1
        if prediction.claim.attribution is expected.attribution:
            matched_attribution += 1

    false_positives = len(predictions) - true_positives
    false_negatives = len(unmatched_gold)
    precision = _ratio(true_positives, true_positives + false_positives)
    recall = _ratio(true_positives, true_positives + false_negatives)
    f1 = _f1(precision, recall)
    attribution_accuracy = (
        _ratio(matched_attribution, true_positives) if true_positives else None
    )
    return ClaimEvaluationReport(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=f1,
        attribution_accuracy=attribution_accuracy,
    )


def _claim_predictions(batch: ExtractionBatch) -> tuple[_PredictedClaim, ...]:
    evidence_by_id = {item.evidence_id: item for item in batch.evidence}
    predictions: list[_PredictedClaim] = []
    for extraction in batch.extractions:
        if not isinstance(extraction, Claim):
            continue
        spans = frozenset(
            GoldEvidenceSpan(
                passage_id=evidence_by_id[evidence_id].passage_id,
                char_start=evidence_by_id[evidence_id].passage_char_start,
                char_end=evidence_by_id[evidence_id].passage_char_end,
            )
            for evidence_id in extraction.evidence_ids
        )
        predictions.append(_PredictedClaim(claim=extraction, evidence=spans))
    return tuple(predictions)


def _find_gold_match(
    prediction: _PredictedClaim,
    gold: list[GoldClaim],
) -> int | None:
    for index, expected in enumerate(gold):
        if prediction.evidence == frozenset(expected.evidence):
            return index
    return None


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0
