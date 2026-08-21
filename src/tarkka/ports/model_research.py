from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

from tarkka.domain.extraction import AttributionKind
from tarkka.ports.model_claims import EvidenceSelector, ModelClaimRequest

ModelResearchRequest: TypeAlias = ModelClaimRequest


@dataclass(frozen=True, slots=True)
class ModelMethodCandidate:
    name: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    description: str | None = None
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            label="method",
            primary=self.name,
            evidence=self.evidence,
            confidence=self.confidence,
            reasoning_summary=self.reasoning_summary,
        )
        if self.description is not None and not self.description.strip():
            raise ValueError("model method description must not be blank when provided")


@dataclass(frozen=True, slots=True)
class ModelDatasetCandidate:
    name: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    description: str | None = None
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            label="dataset",
            primary=self.name,
            evidence=self.evidence,
            confidence=self.confidence,
            reasoning_summary=self.reasoning_summary,
        )
        if self.description is not None and not self.description.strip():
            raise ValueError("model dataset description must not be blank when provided")


@dataclass(frozen=True, slots=True)
class ModelResultCandidate:
    text: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    direction: str | None = None
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            label="result",
            primary=self.text,
            evidence=self.evidence,
            confidence=self.confidence,
            reasoning_summary=self.reasoning_summary,
        )
        if self.direction is not None and not self.direction.strip():
            raise ValueError("model result direction must not be blank when provided")


ModelResearchCandidate: TypeAlias = ModelMethodCandidate | ModelDatasetCandidate | ModelResultCandidate


class StructuredResearchModel(Protocol):
    """Provider-neutral structured-output boundary for research-object extraction."""

    provider: str
    model_name: str
    model_version: str | None

    def extract_research(
        self, request: ModelResearchRequest
    ) -> tuple[ModelResearchCandidate, ...]:
        """Return evidence-grounded method, dataset, and result candidates."""
        ...


def _validate_candidate(
    *,
    label: str,
    primary: str,
    evidence: tuple[EvidenceSelector, ...],
    confidence: float,
    reasoning_summary: str | None,
) -> None:
    if not primary.strip():
        raise ValueError(f"model {label} primary text must not be blank")
    if not evidence:
        raise ValueError(f"model {label} candidate must cite evidence")
    if len(set(evidence)) != len(evidence):
        raise ValueError(f"model {label} evidence selectors must be unique")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"model {label} confidence must be between 0 and 1")
    if reasoning_summary is not None and not reasoning_summary.strip():
        raise ValueError("model reasoning summary must not be blank when provided")
