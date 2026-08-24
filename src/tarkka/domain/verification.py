"""Auditable assessments of how exact evidence bears on a Claim."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from tarkka.domain.extraction import HumanReviewState
from tarkka.domain.models import utc_now


class EvidenceRelationKind(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    PARTIALLY_SUPPORTS = "partially_supports"
    QUALIFIES = "qualifies"
    MENTIONS = "mentions"
    NO_EVIDENCE = "no_evidence"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class EvidenceRelation:
    """One immutable, reviewable assessment from a Claim to exact source evidence.

    ``citation_context_id`` anchors an assessment in the citing document when a
    source-native citation context exists. It is not evidence itself and never
    substitutes for the separate evidence locator.
    """

    relation_id: UUID
    claim_id: UUID
    kind: EvidenceRelationKind
    verifier_name: str
    verifier_version: str
    confidence: float
    human_review_state: HumanReviewState = HumanReviewState.UNREVIEWED
    evidence_id: UUID | None = None
    citation_context_id: UUID | None = None
    reasoning_summary: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceRelationKind):
            raise ValueError("evidence relation kind must be an EvidenceRelationKind")
        if not self.verifier_name.strip() or not self.verifier_version.strip():
            raise ValueError("evidence verifier name/version must not be blank")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("evidence relation confidence must be between 0 and 1")
        if not isinstance(self.human_review_state, HumanReviewState):
            raise ValueError("evidence relation review state must be a HumanReviewState")
        if self.reasoning_summary is not None and not self.reasoning_summary.strip():
            raise ValueError("evidence relation reasoning summary must not be blank")
        if self.kind is EvidenceRelationKind.NO_EVIDENCE:
            if self.evidence_id is not None:
                raise ValueError("no_evidence relation must not identify evidence")
        elif self.evidence_id is None:
            raise ValueError("evidence relation must identify exact evidence")
