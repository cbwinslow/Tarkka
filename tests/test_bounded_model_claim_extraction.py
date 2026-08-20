from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.extraction.model_claims import (
    ModelBatchingPolicy,
    ModelClaimExtractor,
    NoModelClaimsFoundError,
)
from tarkka.ports.model_claims import (
    EvidenceSelector,
    ModelClaimCandidate,
    ModelClaimRequest,
)


def _document(*texts: str) -> Document:
    document_id = uuid4()
    section_id = uuid4()
    passages = tuple(
        Passage(
            passage_id=uuid4(),
            document_id=document_id,
            section_id=section_id,
            ordinal=index,
            text=text,
            char_start=sum(len(item) for item in texts[:index]),
            char_end=sum(len(item) for item in texts[: index + 1]),
        )
        for index, text in enumerate(texts)
    )
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Bounded fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(
            Section(
                section_id=section_id,
                document_id=document_id,
                ordinal=0,
                title="Results",
                passages=passages,
            ),
        ),
    )


@dataclass
class RecordingModel:
    responses: list[tuple[ModelClaimCandidate, ...]]
    provider: str = "fixture"
    model_name: str = "fixture-model"
    model_version: str | None = "1"
    requests: list[ModelClaimRequest] = field(default_factory=list)

    def extract_claims(self, request: ModelClaimRequest) -> tuple[ModelClaimCandidate, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        return self.responses[index] if index < len(self.responses) else ()


def test_bounded_extractor_splits_requests_with_overlap() -> None:
    document = _document("aaaaaaaa", "bbbbbbbb", "cccccccc", "dddddddd")
    first = document.sections[0].passages[0]
    model = RecordingModel(
        responses=[
            (
                ModelClaimCandidate(
                    text="First claim",
                    evidence=(EvidenceSelector(first.passage_id, 0, 4),),
                    confidence=0.8,
                ),
            ),
            (),
            (),
        ]
    )
    extractor = ModelClaimExtractor(
        model,
        batching=ModelBatchingPolicy(max_chars=16, max_passages=3, overlap_passages=1),
    )

    extractor.extract(document)

    assert [[item.ordinal for item in request.passages] for request in model.requests] == [
        [0, 1],
        [1, 2],
        [2, 3],
    ]
    assert all(sum(len(item.text) for item in request.passages) <= 16 for request in model.requests)


def test_oversized_single_passage_remains_atomic() -> None:
    document = _document("0123456789", "tiny")
    first = document.sections[0].passages[0]
    model = RecordingModel(
        responses=[
            (
                ModelClaimCandidate(
                    text="Oversized passage claim",
                    evidence=(EvidenceSelector(first.passage_id, 0, 5),),
                    confidence=0.7,
                ),
            ),
            (),
        ]
    )
    extractor = ModelClaimExtractor(
        model,
        batching=ModelBatchingPolicy(max_chars=5, max_passages=2, overlap_passages=0),
    )

    extractor.extract(document)

    assert [len(request.passages) for request in model.requests] == [1, 1]
    assert model.requests[0].passages[0].text == "0123456789"


def test_model_candidate_cannot_reference_passage_outside_its_request_batch() -> None:
    document = _document("first", "second")
    second = document.sections[0].passages[1]
    model = RecordingModel(
        responses=[
            (
                ModelClaimCandidate(
                    text="Cross-batch claim",
                    evidence=(EvidenceSelector(second.passage_id, 0, 3),),
                    confidence=0.5,
                ),
            )
        ]
    )
    extractor = ModelClaimExtractor(
        model,
        batching=ModelBatchingPolicy(max_chars=5, max_passages=1, overlap_passages=0),
    )

    with pytest.raises(ValueError, match="outside request batch"):
        extractor.extract(document)


def test_overlap_duplicates_are_collapsed_and_keep_higher_confidence() -> None:
    document = _document("aaaaaaaa", "shared result", "cccccccc")
    shared = document.sections[0].passages[1]
    selector = EvidenceSelector(shared.passage_id, 0, len(shared.text))
    low = ModelClaimCandidate(
        text=" Shared   Result ",
        evidence=(selector,),
        confidence=0.6,
    )
    high = ModelClaimCandidate(
        text="shared result",
        evidence=(selector,),
        confidence=0.9,
    )
    model = RecordingModel(responses=[(low,), (high,)])
    extractor = ModelClaimExtractor(
        model,
        batching=ModelBatchingPolicy(max_chars=21, max_passages=2, overlap_passages=1),
    )

    batch = extractor.extract(document)

    assert len(model.requests) == 2
    assert len(batch.extractions) == 1
    assert batch.extractions[0].provenance.confidence == 0.9
    assert len(batch.evidence) == 1


def test_all_empty_bounded_responses_remain_no_claims() -> None:
    document = _document("first", "second")
    model = RecordingModel(responses=[(), ()])
    extractor = ModelClaimExtractor(
        model,
        batching=ModelBatchingPolicy(max_chars=5, max_passages=1, overlap_passages=0),
    )

    with pytest.raises(NoModelClaimsFoundError, match="no structured claim"):
        extractor.extract(document)

    assert len(model.requests) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_chars": 0},
        {"max_passages": 0},
        {"overlap_passages": -1},
        {"max_passages": 2, "overlap_passages": 2},
    ],
)
def test_batching_policy_rejects_invalid_bounds(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        ModelBatchingPolicy(**kwargs)
