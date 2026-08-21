from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from tarkka.domain.extraction import (
    Dataset,
    Hypothesis,
    Limitation,
    Method,
    Metric,
    Model,
    Result,
    Variable,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.extraction.model_batching import ModelBatchingPolicy
from tarkka.infrastructure.extraction.model_research import (
    ModelResearchExtractor,
    NoModelResearchFoundError,
)
from tarkka.ports.model_claims import EvidenceSelector, ModelClaimRequest
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
)


@dataclass
class RecordingResearchModel:
    provider: str = "fixture"
    model_name: str = "research-model"
    model_version: str | None = "1"
    responses: list[tuple[ModelResearchCandidate, ...]] = field(default_factory=list)
    requests: list[ModelClaimRequest] = field(default_factory=list)

    def extract_research(self, request: ModelClaimRequest) -> tuple[ModelResearchCandidate, ...]:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else ()


def _document() -> Document:
    document_id = uuid4()
    section_id = uuid4()
    texts = (
        "We hypothesized starter rest would improve outcomes and trained gradient boosted trees on Statcast data using rest_days.",
        "Log loss improved from 0.61 to 0.57, although the sample was limited to one season.",
        "Additional discussion followed the reported result.",
    )
    offset = 0
    passages = []
    for ordinal, text in enumerate(texts):
        passages.append(
            Passage(
                passage_id=uuid4(),
                document_id=document_id,
                section_id=section_id,
                ordinal=ordinal,
                text=text,
                char_start=offset,
                char_end=offset + len(text),
            )
        )
        offset += len(text)
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Research fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(
            Section(
                section_id=section_id,
                document_id=document_id,
                ordinal=0,
                title="Methods and results",
                passages=tuple(passages),
            ),
        ),
    )


def test_extracts_complete_research_vocabulary_in_one_run() -> None:
    document = _document()
    first, second, _ = document.sections[0].passages
    first_span = (EvidenceSelector(first.passage_id, 0, len(first.text)),)
    second_span = (EvidenceSelector(second.passage_id, 0, len(second.text)),)
    model = RecordingResearchModel(
        responses=[
            (
                ModelHypothesisCandidate(text="starter rest would improve outcomes", evidence=first_span, confidence=0.9),
                ModelMethodCandidate(name="gradient boosted trees", description="Tree boosting", evidence=first_span, confidence=0.95),
                ModelDatasetCandidate(name="Statcast", evidence=first_span, confidence=0.98),
                ModelVariableCandidate(name="rest_days", role="predictor", evidence=first_span, confidence=0.97),
                ModelModelCandidate(name="gradient boosted trees", family="tree ensemble", evidence=first_span, confidence=0.96),
                ModelMetricCandidate(name="log loss", value_text="0.57", evidence=second_span, confidence=0.99),
                ModelResultCandidate(text="Log loss improved from 0.61 to 0.57", direction="improved", evidence=second_span, confidence=0.99),
                ModelLimitationCandidate(text="the sample was limited to one season", evidence=second_span, confidence=0.93),
            )
        ]
    )

    batch = ModelResearchExtractor(model).extract(document)

    assert [type(item) for item in batch.extractions] == [
        Hypothesis,
        Method,
        Dataset,
        Variable,
        Model,
        Metric,
        Result,
        Limitation,
    ]
    assert len(batch.evidence) == 8
    assert {item.provenance.run_id for item in batch.extractions} == {batch.run.run_id}
    assert batch.run.model is not None
    assert batch.run.model.name == "research-model"


def test_bounded_research_extraction_deduplicates_overlap_by_exact_signature() -> None:
    document = _document()
    shared = document.sections[0].passages[1]
    low = ModelMethodCandidate(
        name="gradient boosted trees",
        evidence=(EvidenceSelector(shared.passage_id, 4, 9),),
        confidence=0.6,
    )
    high = ModelMethodCandidate(
        name="Gradient Boosted Trees",
        evidence=(EvidenceSelector(shared.passage_id, 4, 9),),
        confidence=0.9,
    )
    model = RecordingResearchModel(responses=[(low,), (high,)])

    batch = ModelResearchExtractor(
        model,
        batching=ModelBatchingPolicy(max_chars=300, max_passages=2, overlap_passages=1),
    ).extract(document)

    assert len(model.requests) == 2
    assert model.requests[0].passages[1].passage_id == shared.passage_id
    assert model.requests[1].passages[0].passage_id == shared.passage_id
    assert len(batch.extractions) == 1
    assert batch.extractions[0].provenance.confidence == 0.9


def test_rejects_candidate_evidence_outside_current_batch() -> None:
    document = _document()
    third = document.sections[0].passages[2]
    model = RecordingResearchModel(
        responses=[
            (
                ModelResultCandidate(
                    text="Out of scope",
                    evidence=(EvidenceSelector(third.passage_id, 0, 3),),
                    confidence=0.5,
                ),
            )
        ]
    )

    with pytest.raises(ValueError, match="outside request batch"):
        ModelResearchExtractor(
            model,
            batching=ModelBatchingPolicy(max_chars=300, max_passages=2, overlap_passages=1),
        ).extract(document)


def test_rejects_candidate_evidence_beyond_passage_bounds() -> None:
    document = _document()
    first = document.sections[0].passages[0]
    model = RecordingResearchModel(
        responses=[
            (
                ModelMethodCandidate(
                    name="gradient boosted trees",
                    evidence=(EvidenceSelector(first.passage_id, 0, len(first.text) + 1),),
                    confidence=0.8,
                ),
            )
        ]
    )

    with pytest.raises(ValueError, match="evidence range must be contained within the passage"):
        ModelResearchExtractor(model).extract(document)


def test_no_candidates_fails_closed_without_partial_batch() -> None:
    with pytest.raises(NoModelResearchFoundError):
        ModelResearchExtractor(RecordingResearchModel()).extract(_document())
