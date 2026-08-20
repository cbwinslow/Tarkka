from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

from tarkka.domain.models import Document, Passage, utc_now


class HumanReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    VERIFIED = "verified"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class AttributionKind(StrEnum):
    AUTHOR_STATED = "author_stated"
    EXTRACTOR_INFERRED = "extractor_inferred"
    SYNTHESIS = "synthesis"


class ResearchObjectKind(StrEnum):
    CLAIM = "claim"
    HYPOTHESIS = "hypothesis"
    METHOD = "method"
    DATASET = "dataset"
    VARIABLE = "variable"
    MODEL = "model"
    METRIC = "metric"
    RESULT = "result"
    LIMITATION = "limitation"


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    provider: str
    name: str
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.name.strip():
            raise ValueError("model provider/name must not be blank")
        if self.version is not None and not self.version.strip():
            raise ValueError("model version must not be blank when provided")


@dataclass(frozen=True, slots=True)
class ExtractionRun:
    """Immutable metadata shared by every record produced by one extractor call."""

    run_id: UUID
    document_id: UUID
    extractor_name: str
    extractor_version: str
    contract_version: str = "1"
    model: ModelProvenance | None = None
    extracted_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.extractor_name.strip() or not self.extractor_version.strip():
            raise ValueError("extractor name/version must not be blank")
        if not self.contract_version.strip():
            raise ValueError("extraction contract version must not be blank")


@dataclass(frozen=True, slots=True)
class ExtractionProvenance:
    """Record-level confidence/review metadata tied to an extraction run."""

    run_id: UUID
    confidence: float = 1.0
    human_review_state: HumanReviewState = HumanReviewState.UNREVIEWED
    reasoning_summary: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("extraction confidence must be between 0 and 1")
        if self.reasoning_summary is not None and not self.reasoning_summary.strip():
            raise ValueError("reasoning summary must not be blank when provided")


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: UUID
    document_id: UUID
    section_id: UUID
    passage_id: UUID
    passage_char_start: int
    passage_char_end: int
    text: str
    provenance: ExtractionProvenance

    def __post_init__(self) -> None:
        if self.passage_char_start < 0 or self.passage_char_end <= self.passage_char_start:
            raise ValueError("invalid evidence passage character range")
        if self.passage_char_end - self.passage_char_start != len(self.text):
            raise ValueError("evidence character range must match evidence text length")
        if not self.text.strip():
            raise ValueError("evidence text must not be blank")

    @classmethod
    def from_passage(
        cls,
        *,
        evidence_id: UUID,
        passage: Passage,
        passage_char_start: int,
        passage_char_end: int,
        provenance: ExtractionProvenance,
    ) -> Evidence:
        """Construct evidence by slicing an exact normalized passage span."""
        if passage_char_start < 0 or passage_char_end > len(passage.text):
            raise ValueError("evidence range must be contained within the passage")
        if passage_char_end <= passage_char_start:
            raise ValueError("evidence range must not be empty")
        return cls(
            evidence_id=evidence_id,
            document_id=passage.document_id,
            section_id=passage.section_id,
            passage_id=passage.passage_id,
            passage_char_start=passage_char_start,
            passage_char_end=passage_char_end,
            text=passage.text[passage_char_start:passage_char_end],
            provenance=provenance,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchExtractionBase:
    extraction_id: UUID
    document_id: UUID
    evidence_ids: tuple[UUID, ...]
    provenance: ExtractionProvenance
    attribution: AttributionKind = AttributionKind.AUTHOR_STATED

    def __post_init__(self) -> None:
        if not self.evidence_ids:
            raise ValueError("research extraction must reference evidence")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("research extraction evidence IDs must be unique")

    @property
    def kind(self) -> ResearchObjectKind:
        raise NotImplementedError


@dataclass(frozen=True, slots=True, kw_only=True)
class Claim(ResearchExtractionBase):
    text: str
    claim_type: str = "proposition"

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.text.strip() or not self.claim_type.strip():
            raise ValueError("claim text/type must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.CLAIM


@dataclass(frozen=True, slots=True, kw_only=True)
class Hypothesis(ResearchExtractionBase):
    text: str

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.text.strip():
            raise ValueError("hypothesis text must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.HYPOTHESIS


@dataclass(frozen=True, slots=True, kw_only=True)
class Method(ResearchExtractionBase):
    name: str
    description: str | None = None

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.name.strip():
            raise ValueError("method name must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.METHOD


@dataclass(frozen=True, slots=True, kw_only=True)
class Dataset(ResearchExtractionBase):
    name: str
    description: str | None = None

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.name.strip():
            raise ValueError("dataset name must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.DATASET


@dataclass(frozen=True, slots=True, kw_only=True)
class Variable(ResearchExtractionBase):
    name: str
    role: str | None = None

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.name.strip():
            raise ValueError("variable name must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.VARIABLE


@dataclass(frozen=True, slots=True, kw_only=True)
class Model(ResearchExtractionBase):
    name: str
    family: str | None = None

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.name.strip():
            raise ValueError("model name must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.MODEL


@dataclass(frozen=True, slots=True, kw_only=True)
class Metric(ResearchExtractionBase):
    name: str
    value_text: str | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.name.strip():
            raise ValueError("metric name must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.METRIC


@dataclass(frozen=True, slots=True, kw_only=True)
class Result(ResearchExtractionBase):
    text: str
    direction: str | None = None

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.text.strip():
            raise ValueError("result text must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.RESULT


@dataclass(frozen=True, slots=True, kw_only=True)
class Limitation(ResearchExtractionBase):
    text: str

    def __post_init__(self) -> None:
        ResearchExtractionBase.__post_init__(self)
        if not self.text.strip():
            raise ValueError("limitation text must not be blank")

    @property
    def kind(self) -> ResearchObjectKind:
        return ResearchObjectKind.LIMITATION


# TypeAlias remains necessary while Tarkka supports Python 3.11.
ResearchExtraction: TypeAlias = (
    Claim | Hypothesis | Method | Dataset | Variable | Model | Metric | Result | Limitation
)


@dataclass(frozen=True, slots=True)
class ExtractionBatch:
    """One validated, non-empty extraction run over one normalized document."""

    document: Document
    run: ExtractionRun
    evidence: tuple[Evidence, ...]
    extractions: tuple[ResearchExtraction, ...]

    @property
    def document_id(self) -> UUID:
        return self.document.document_id

    def __post_init__(self) -> None:
        if self.run.document_id != self.document_id:
            raise ValueError("extraction run does not belong to extraction batch document")
        if not self.evidence:
            raise ValueError("extraction batch must contain at least one evidence item")
        if not self.extractions:
            raise ValueError("extraction batch must contain at least one extraction")

        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("extraction batch evidence IDs must be unique")
        extraction_ids = {item.extraction_id for item in self.extractions}
        if len(extraction_ids) != len(self.extractions):
            raise ValueError("extraction batch extraction IDs must be unique")

        passages = {
            passage.passage_id: passage
            for section in self.document.sections
            for passage in section.passages
        }

        for item in self.evidence:
            if item.provenance.run_id != self.run.run_id:
                raise ValueError("evidence does not belong to extraction batch run")
            if item.document_id != self.document_id:
                raise ValueError("evidence does not belong to extraction batch document")
            passage = passages.get(item.passage_id)
            if passage is None or passage.section_id != item.section_id:
                raise ValueError("evidence does not resolve to a normalized passage")
            if item.passage_char_end > len(passage.text):
                raise ValueError("evidence range is outside its normalized passage")
            expected = passage.text[item.passage_char_start : item.passage_char_end]
            if item.text != expected:
                raise ValueError("evidence text does not match its normalized passage span")

        for item in self.extractions:
            if item.provenance.run_id != self.run.run_id:
                raise ValueError("extraction does not belong to extraction batch run")
            if item.document_id != self.document_id:
                raise ValueError("extraction does not belong to extraction batch document")
            missing = set(item.evidence_ids) - evidence_ids
            if missing:
                raise ValueError("extraction references evidence outside the batch")
