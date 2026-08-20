from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class IdentityDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    signal: str
    score: float
    detail: str

    def __post_init__(self) -> None:
        if not self.signal.strip():
            raise ValueError("identity evidence signal must not be blank")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("identity evidence score must be between 0 and 1")
        if not self.detail.strip():
            raise ValueError("identity evidence detail must not be blank")


@dataclass(frozen=True, slots=True)
class IdentityCandidate:
    candidate_id: UUID
    left_provider: str
    left_provider_id: str
    right_provider: str
    right_provider_id: str
    confidence: float
    evidence: tuple[IdentityEvidence, ...]
    review_required: bool = True

    def __post_init__(self) -> None:
        if not self.left_provider.strip() or not self.right_provider.strip():
            raise ValueError("candidate providers must not be blank")
        if not self.left_provider_id.strip() or not self.right_provider_id.strip():
            raise ValueError("candidate provider IDs must not be blank")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("candidate confidence must be between 0 and 1")
        if not self.evidence:
            raise ValueError("identity candidate must include evidence")
        if not self.review_required:
            raise ValueError("fuzzy identity candidates must require review")


@dataclass(frozen=True, slots=True)
class IdentityDecisionRecord:
    candidate_id: UUID
    decision: IdentityDecision
    snapshot_id: UUID
    left_index: int
    right_index: int
    actor: str = "cli"
    rationale: str | None = None
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.left_index < 0 or self.right_index < 0:
            raise ValueError("identity decision indexes must be non-negative")
        if self.left_index == self.right_index:
            raise ValueError("identity decision indexes must be different")
        if not self.actor.strip():
            raise ValueError("identity decision actor must not be blank")
