from __future__ import annotations

from typing import TypeAlias
from uuid import UUID, uuid4, uuid5

from tarkka.domain.extraction import (
    Dataset,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    Hypothesis,
    Limitation,
    Method,
    Metric,
    Model,
    ModelProvenance,
    ResearchExtraction,
    Result,
    Variable,
)
from tarkka.domain.models import Document, Passage
from tarkka.infrastructure.extraction.model_batching import (
    ModelBatchingPolicy,
    build_model_requests,
    validate_candidate_batch_scope,
)
from tarkka.ports.model_research import (
    ModelDatasetCandidate,
    ModelHypothesisCandidate,
    ModelLimitationCandidate,
    ModelMethodCandidate,
    ModelMetricCandidate,
    ModelModelCandidate,
    ModelResearchCandidate,
    ModelResultCandidate,
    ModelVariableCandidate,
    StructuredResearchModel,
)

_TARKKA_MODEL_RESEARCH_NAMESPACE = UUID("83bb5e6c-d273-5dbd-8b70-76e75576ab31")
_EvidenceSignature: TypeAlias = tuple[str, int, int]
_DetailSignature: TypeAlias = tuple[str | None, ...]
_CandidateSignature: TypeAlias = tuple[
    str,
    str,
    str,
    _DetailSignature,
    tuple[_EvidenceSignature, ...],
]


class NoModelResearchFoundError(ValueError):
    """Raised when a model returns no supported structured research objects."""


class ModelResearchExtractor:
    """Extract bounded structured research records with exact evidence."""

    name: str = "model-research"
    version: str = "1.1.0"

    def __init__(
        self,
        model: StructuredResearchModel,
        *,
        batching: ModelBatchingPolicy | None = None,
    ) -> None:
        if not model.provider.strip() or not model.model_name.strip():
            raise ValueError("model provider/name must not be blank")
        if model.model_version is not None and not model.model_version.strip():
            raise ValueError("model version must not be blank when provided")
        self.model = model
        self.batching = batching or ModelBatchingPolicy()

    def extract(self, document: Document) -> ExtractionBatch:
        passages = tuple(
            passage for section in document.sections for passage in section.passages
        )
        requests = build_model_requests(document, passages, self.batching)
        all_passage_ids = {passage.passage_id for passage in passages}
        candidates: list[ModelResearchCandidate] = []
        candidate_index: dict[_CandidateSignature, int] = {}

        for request in requests:
            allowed_passage_ids = {passage.passage_id for passage in request.passages}
            for candidate in self.model.extract_research(request):
                validate_candidate_batch_scope(
                    candidate, allowed_passage_ids, all_passage_ids
                )
                signature = _candidate_signature(candidate)
                existing_index = candidate_index.get(signature)
                if existing_index is None:
                    candidate_index[signature] = len(candidates)
                    candidates.append(candidate)
                elif candidate.confidence > candidates[existing_index].confidence:
                    candidates[existing_index] = candidate
                # Equal-confidence duplicates intentionally retain the first occurrence.

        if not candidates:
            raise NoModelResearchFoundError(
                "model returned no supported research candidates"
            )

        run_id = uuid4()
        run = ExtractionRun(
            run_id=run_id,
            document_id=document.document_id,
            extractor_name=self.name,
            extractor_version=self.version,
            model=ModelProvenance(
                provider=self.model.provider,
                name=self.model.model_name,
                version=self.model.model_version,
            ),
        )
        passage_index = {passage.passage_id: passage for passage in passages}
        evidence: list[Evidence] = []
        extractions: list[ResearchExtraction] = []

        for candidate_number, candidate in enumerate(candidates):
            provenance = ExtractionProvenance(
                run_id=run_id,
                confidence=candidate.confidence,
                reasoning_summary=candidate.reasoning_summary,
            )
            evidence_ids: list[UUID] = []
            for selector_number, selector in enumerate(candidate.evidence):
                passage = _resolve_passage(passage_index, selector.passage_id)
                evidence_id = uuid5(
                    _TARKKA_MODEL_RESEARCH_NAMESPACE,
                    f"evidence:{run_id}:{candidate_number}:{selector_number}:"
                    f"{selector.passage_id}:{selector.char_start}:{selector.char_end}",
                )
                evidence.append(
                    Evidence.from_passage(
                        evidence_id=evidence_id,
                        passage=passage,
                        passage_char_start=selector.char_start,
                        passage_char_end=selector.char_end,
                        provenance=provenance,
                    )
                )
                evidence_ids.append(evidence_id)

            extraction_id = uuid5(
                _TARKKA_MODEL_RESEARCH_NAMESPACE,
                f"{_candidate_kind(candidate)}:{run_id}:{candidate_number}:"
                f"{_candidate_primary(candidate)}",
            )
            extractions.append(
                _to_domain_record(
                    candidate,
                    extraction_id=extraction_id,
                    document_id=document.document_id,
                    evidence_ids=tuple(evidence_ids),
                    provenance=provenance,
                )
            )

        return ExtractionBatch(
            document=document,
            run=run,
            evidence=tuple(evidence),
            extractions=tuple(extractions),
        )


def _candidate_kind(candidate: ModelResearchCandidate) -> str:
    if isinstance(candidate, ModelMethodCandidate):
        return "method"
    if isinstance(candidate, ModelDatasetCandidate):
        return "dataset"
    if isinstance(candidate, ModelVariableCandidate):
        return "variable"
    if isinstance(candidate, ModelModelCandidate):
        return "model"
    if isinstance(candidate, ModelMetricCandidate):
        return "metric"
    if isinstance(candidate, ModelHypothesisCandidate):
        return "hypothesis"
    if isinstance(candidate, ModelResultCandidate):
        return "result"
    if isinstance(candidate, ModelLimitationCandidate):
        return "limitation"
    raise TypeError(f"unsupported research candidate: {type(candidate)!r}")


def _candidate_primary(candidate: ModelResearchCandidate) -> str:
    named_types = (
        ModelMethodCandidate,
        ModelDatasetCandidate,
        ModelVariableCandidate,
        ModelModelCandidate,
        ModelMetricCandidate,
    )
    if isinstance(candidate, named_types):
        return candidate.name
    text_types = (
        ModelHypothesisCandidate,
        ModelResultCandidate,
        ModelLimitationCandidate,
    )
    if isinstance(candidate, text_types):
        return candidate.text
    raise TypeError(f"unsupported research candidate: {type(candidate)!r}")


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()).casefold()


def _candidate_details(candidate: ModelResearchCandidate) -> _DetailSignature:
    if isinstance(candidate, (ModelMethodCandidate, ModelDatasetCandidate)):
        return (_normalized_optional(candidate.description),)
    if isinstance(candidate, ModelVariableCandidate):
        return (_normalized_optional(candidate.role),)
    if isinstance(candidate, ModelModelCandidate):
        return (_normalized_optional(candidate.family),)
    if isinstance(candidate, ModelMetricCandidate):
        return (
            _normalized_optional(candidate.value_text),
            _normalized_optional(candidate.unit),
        )
    if isinstance(candidate, ModelResultCandidate):
        return (_normalized_optional(candidate.direction),)
    if isinstance(candidate, (ModelHypothesisCandidate, ModelLimitationCandidate)):
        return ()
    raise TypeError(f"unsupported research candidate: {type(candidate)!r}")


def _candidate_signature(candidate: ModelResearchCandidate) -> _CandidateSignature:
    evidence = tuple(
        sorted(
            (str(selector.passage_id), selector.char_start, selector.char_end)
            for selector in candidate.evidence
        )
    )
    normalized_primary = " ".join(_candidate_primary(candidate).split()).casefold()
    return (
        _candidate_kind(candidate),
        normalized_primary,
        candidate.attribution.value,
        _candidate_details(candidate),
        evidence,
    )


def _to_domain_record(
    candidate: ModelResearchCandidate,
    *,
    extraction_id: UUID,
    document_id: UUID,
    evidence_ids: tuple[UUID, ...],
    provenance: ExtractionProvenance,
) -> ResearchExtraction:
    if isinstance(candidate, ModelMethodCandidate):
        return Method(
            extraction_id=extraction_id,
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            attribution=candidate.attribution,
            name=candidate.name,
            description=candidate.description,
        )
    if isinstance(candidate, ModelDatasetCandidate):
        return Dataset(
            extraction_id=extraction_id,
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            attribution=candidate.attribution,
            name=candidate.name,
            description=candidate.description,
        )
    if isinstance(candidate, ModelVariableCandidate):
        return Variable(
            extraction_id=extraction_id,
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            attribution=candidate.attribution,
            name=candidate.name,
            role=candidate.role,
        )
    if isinstance(candidate, ModelModelCandidate):
        return Model(
            extraction_id=extraction_id,
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            attribution=candidate.attribution,
            name=candidate.name,
            family=candidate.family,
        )
    if isinstance(candidate, ModelMetricCandidate):
        return Metric(
            extraction_id=extraction_id,
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            attribution=candidate.attribution,
            name=candidate.name,
            value_text=candidate.value_text,
            unit=candidate.unit,
        )
    if isinstance(candidate, ModelHypothesisCandidate):
        return Hypothesis(
            extraction_id=extraction_id,
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            attribution=candidate.attribution,
            text=candidate.text,
        )
    if isinstance(candidate, ModelResultCandidate):
        return Result(
            extraction_id=extraction_id,
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            attribution=candidate.attribution,
            text=candidate.text,
            direction=candidate.direction,
        )
    if isinstance(candidate, ModelLimitationCandidate):
        return Limitation(
            extraction_id=extraction_id,
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            attribution=candidate.attribution,
            text=candidate.text,
        )
    raise TypeError(f"unsupported research candidate: {type(candidate)!r}")


def _resolve_passage(passages: dict[UUID, Passage], passage_id: UUID) -> Passage:
    return passages[passage_id]
