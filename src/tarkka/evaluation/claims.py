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
        """Validate the evidence span's character range.
        
        Raises:
            ValueError: If the start is negative or the end does not follow the start.
        """
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("invalid gold evidence character range")


@dataclass(frozen=True, slots=True)
class GoldClaim:
    """Gold claim label keyed by exact supporting evidence rather than wording."""

    evidence: tuple[GoldEvidenceSpan, ...]
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED

    def __post_init__(self) -> None:
        """Validate that the gold claim contains unique evidence spans.
        
        Raises:
            ValueError: If the claim contains no evidence or contains duplicate
                evidence spans.
        """
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


def _validate_gold(batch: ExtractionBatch, gold: tuple[GoldClaim, ...]) -> None:
    """Validate gold claims against the source document.

    Args:
        batch: Extraction batch containing the source document.
        gold: Gold claims to validate.

    Raises:
        ValueError: If any gold evidence span references an unknown passage ID,
            has char_end beyond the passage text length, or if duplicate complete
            evidence sets exist across gold claims.
    """
    # Build passage index
    passages_by_id = {}
    for section in batch.document.sections:
        for passage in section.passages:
            passages_by_id[passage.passage_id] = passage

    # Validate each evidence span
    for gold_claim in gold:
        for span in gold_claim.evidence:
            if span.passage_id not in passages_by_id:
                raise ValueError(
                    f"gold evidence span references unknown passage {span.passage_id}"
                )
            passage = passages_by_id[span.passage_id]
            if span.char_end > len(passage.text):
                raise ValueError(
                    f"gold evidence span char_end {span.char_end} exceeds "
                    f"passage text length {len(passage.text)} "
                    f"for passage {span.passage_id}"
                )

    # Check for duplicate evidence sets
    evidence_sets = [frozenset(claim.evidence) for claim in gold]
    if len(set(evidence_sets)) != len(evidence_sets):
        raise ValueError("duplicate complete evidence sets found in gold claims")


def evaluate_claims(
    batch: ExtractionBatch,
    gold: tuple[GoldClaim, ...],
) -> ClaimEvaluationReport:
    """Evaluate claim predictions against gold labels using exact evidence-set matching.

    Claim wording is excluded from matching, and each gold claim can match at most one
    prediction. Unmatched predictions count as false positives, while unmatched gold
    claims count as false negatives.

    Args:
        batch: Extraction results containing predicted claims and their evidence.
        gold: Gold claims with passage-local evidence spans and attribution labels.

    Returns:
        A report containing detection counts, precision, recall, F1, and attribution
        accuracy. Attribution accuracy is ``None`` when no claims are matched.

    Raises:
        ValueError: If gold claims contain invalid evidence spans or duplicate evidence sets.
    """
    _validate_gold(batch, gold)
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
    """Build predicted claim records from an extraction batch.
    
    Args:
        batch: Extraction batch containing claims and their referenced evidence.
    
    Returns:
        A tuple of predicted claims with resolved passage-local evidence spans.
    """
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
    """Find the first gold claim whose evidence spans exactly match the prediction.
    
    Args:
        prediction: Predicted claim with its normalized evidence-span set.
        gold: Gold claims to search.
    
    Returns:
        The index of the first matching gold claim, or `None` if no claim matches.
    """
    for index, expected in enumerate(gold):
        if prediction.evidence == frozenset(expected.evidence):
            return index
    return None


def _ratio(numerator: int, denominator: int) -> float:
    """
    Calculate the ratio of two integers.
    
    Args:
        numerator: The value to divide.
        denominator: The divisor.
    
    Returns:
        The quotient, or `0.0` when the denominator is zero.
    """
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    """
    Compute the F1 score from precision and recall.
    
    Args:
        precision: The precision score.
        recall: The recall score.
    
    Returns:
        The harmonic mean of precision and recall, or 0.0 when both are zero.
    """
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0
