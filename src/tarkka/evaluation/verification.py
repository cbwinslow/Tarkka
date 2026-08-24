"""Deterministic, source-handle-grounded evaluation of evidence assessments."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind


@dataclass(frozen=True, slots=True)
class GoldEvidenceRelation:
    """Expected label for one exact Claim-to-Evidence/context target."""

    claim_id: UUID
    kind: EvidenceRelationKind
    evidence_id: UUID | None = None
    citation_context_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceRelationKind):
            raise ValueError("gold evidence relation kind must be an EvidenceRelationKind")
        if self.kind is EvidenceRelationKind.NO_EVIDENCE:
            if self.evidence_id is not None:
                raise ValueError("gold no_evidence relation must not identify evidence")
        elif self.evidence_id is None:
            raise ValueError("gold evidence relation must identify exact evidence")

    @property
    def target(self) -> tuple[UUID, UUID | None, UUID | None]:
        return (self.claim_id, self.evidence_id, self.citation_context_id)


@dataclass(frozen=True, slots=True)
class EvidenceRelationEvaluationReport:
    """Exact-target and relation-label metrics for one deterministic corpus."""

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    label_accuracy: float | None


def evaluate_evidence_relations(
    relations: tuple[EvidenceRelation, ...],
    gold: tuple[GoldEvidenceRelation, ...],
) -> EvidenceRelationEvaluationReport:
    """Score immutable assessments against exact Claim/Evidence/context gold labels.

    Matching excludes verifier metadata, confidence, review state, and reasoning
    summaries. A duplicate assessment or a wrong label is a false positive; its
    unmatched gold label is a false negative.
    """
    _validate_gold(gold)
    unmatched = list(gold)
    true_positives = 0
    label_comparisons = 0
    correct_labels = 0

    for relation in relations:
        target = (relation.claim_id, relation.evidence_id, relation.citation_context_id)
        target_matches = [item for item in unmatched if item.target == target]
        if target_matches:
            label_comparisons += 1
            if target_matches[0].kind is relation.kind:
                correct_labels += 1
        match_index = next(
            (
                index
                for index, expected in enumerate(unmatched)
                if expected.target == target and expected.kind is relation.kind
            ),
            None,
        )
        if match_index is not None:
            unmatched.pop(match_index)
            true_positives += 1

    false_positives = len(relations) - true_positives
    false_negatives = len(unmatched)
    precision = _ratio(true_positives, true_positives + false_positives)
    recall = _ratio(true_positives, true_positives + false_negatives)
    return EvidenceRelationEvaluationReport(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        label_accuracy=_ratio(correct_labels, label_comparisons) if label_comparisons else None,
    )


def _validate_gold(gold: tuple[GoldEvidenceRelation, ...]) -> None:
    targets = [item.target for item in gold]
    if len(set(targets)) != len(targets):
        raise ValueError("duplicate gold evidence relation targets")


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0
