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
            "method", self.name, self.evidence, self.confidence, self.reasoning_summary
        )
        _validate_optional("model method description", self.description)


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
            "dataset", self.name, self.evidence, self.confidence, self.reasoning_summary
        )
        _validate_optional("model dataset description", self.description)


@dataclass(frozen=True, slots=True)
class ModelVariableCandidate:
    name: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    role: str | None = None
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            "variable", self.name, self.evidence, self.confidence, self.reasoning_summary
        )
        _validate_optional("model variable role", self.role)


@dataclass(frozen=True, slots=True)
class ModelModelCandidate:
    name: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    family: str | None = None
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            "model", self.name, self.evidence, self.confidence, self.reasoning_summary
        )
        _validate_optional("model family", self.family)


@dataclass(frozen=True, slots=True)
class ModelMetricCandidate:
    name: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    value_text: str | None = None
    unit: str | None = None
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            "metric", self.name, self.evidence, self.confidence, self.reasoning_summary
        )
        _validate_optional("model metric value_text", self.value_text)
        _validate_optional("model metric unit", self.unit)


@dataclass(frozen=True, slots=True)
class ModelHypothesisCandidate:
    text: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            "hypothesis", self.text, self.evidence, self.confidence, self.reasoning_summary
        )


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
            "result", self.text, self.evidence, self.confidence, self.reasoning_summary
        )
        _validate_optional("model result direction", self.direction)


@dataclass(frozen=True, slots=True)
class ModelLimitationCandidate:
    text: str
    evidence: tuple[EvidenceSelector, ...]
    confidence: float
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_candidate(
            "limitation", self.text, self.evidence, self.confidence, self.reasoning_summary
        )


ModelResearchCandidate: TypeAlias = (
    ModelMethodCandidate
    | ModelDatasetCandidate
    | ModelVariableCandidate
    | ModelModelCandidate
    | ModelMetricCandidate
    | ModelHypothesisCandidate
    | ModelResultCandidate
    | ModelLimitationCandidate
)


class StructuredResearchModel(Protocol):
    """Provider-neutral structured-output boundary for research-object extraction."""

    provider: str
    model_name: str
    model_version: str | None

    def extract_research(
        self, request: ModelResearchRequest
    ) -> tuple[ModelResearchCandidate, ...]:
        """Return evidence-grounded structured research candidates."""
        ...


def _validate_candidate(
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


def _validate_optional(label: str, value: str | None) -> None:
    if value is not None and not value.strip():
        raise ValueError(f"{label} must not be blank when provided")
