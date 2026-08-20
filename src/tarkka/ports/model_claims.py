from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from tarkka.domain.extraction import AttributionKind


@dataclass(frozen=True, slots=True)
class ModelPassage:
    """Normalized passage exposed to a model adapter."""

    passage_id: UUID
    section_id: UUID
    ordinal: int
    text: str

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("model passage ordinal must be non-negative")
        if not self.text:
            raise ValueError("model passage text must not be empty")


@dataclass(frozen=True, slots=True)
class ModelClaimRequest:
    """Provider-neutral claim extraction request."""

    document_id: UUID
    title: str
    passages: tuple[ModelPassage, ...]

    def __post_init__(self) -> None:
        if not self.passages:
            raise ValueError("model claim request must contain passages")
        passage_ids = {item.passage_id for item in self.passages}
        if len(passage_ids) != len(self.passages):
            raise ValueError("model claim request passage IDs must be unique")


@dataclass(frozen=True, slots=True)
class EvidenceSelector:
    """Exact normalized passage span selected by a model."""

    passage_id: UUID
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("invalid model evidence character range")


@dataclass(frozen=True, slots=True)
class ModelClaimCandidate:
    """Structured model output before Tarkka converts it into domain records."""

    text: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    claim_type: str = "proposition"
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip() or not self.claim_type.strip():
            raise ValueError("model claim text/type must not be blank")
        if not self.evidence:
            raise ValueError("model claim candidate must cite evidence")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("model claim evidence selectors must be unique")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("model claim confidence must be between 0 and 1")
        if self.reasoning_summary is not None and not self.reasoning_summary.strip():
            raise ValueError("model reasoning summary must not be blank when provided")


class StructuredClaimModel(Protocol):
    """Provider-neutral structured-output model boundary for claim extraction."""

    provider: str
    model_name: str
    model_version: str | None

    def extract_claims(self, request: ModelClaimRequest) -> tuple[ModelClaimCandidate, ...]:
        """Return structured claim candidates grounded by passage-local selectors."""
        ...
