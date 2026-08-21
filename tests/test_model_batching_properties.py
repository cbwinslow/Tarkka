from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.extraction.model_claims import ModelBatchingPolicy, ModelClaimExtractor
from tarkka.ports.model_claims import EvidenceSelector, ModelClaimCandidate, ModelClaimRequest


@dataclass
class RecordingModel:
    provider: str = "property-fixture"
    model_name: str = "property-model"
    model_version: str | None = "1"
    requests: list[ModelClaimRequest] = field(default_factory=list)

    def extract_claims(self, request: ModelClaimRequest) -> tuple[ModelClaimCandidate, ...]:
        self.requests.append(request)
        if len(self.requests) != 1:
            return ()
        passage = request.passages[0]
        return (
            ModelClaimCandidate(
                text="Fixture claim",
                evidence=(EvidenceSelector(passage.passage_id, 0, 1),),
                confidence=1.0,
            ),
        )


def _document(lengths: list[int]) -> Document:
    document_id = uuid4()
    section_id = uuid4()
    offset = 0
    passages: list[Passage] = []
    for ordinal, length in enumerate(lengths):
        text = "x" * length
        passages.append(
            Passage(
                passage_id=uuid4(),
                document_id=document_id,
                section_id=section_id,
                ordinal=ordinal,
                text=text,
                char_start=offset,
                char_end=offset + length,
            )
        )
        offset += length
    section = Section(
        section_id=section_id,
        document_id=document_id,
        ordinal=0,
        title="Generated",
        passages=tuple(passages),
    )
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Generated batching fixture",
        parser_name="property-fixture",
        parser_version="1",
        sections=(section,),
    )


@pytest.mark.property
@given(
    lengths=st.lists(st.integers(min_value=1, max_value=80), min_size=1, max_size=20),
    max_chars=st.integers(min_value=1, max_value=120),
    max_passages=st.integers(min_value=1, max_value=8),
    overlap=st.integers(min_value=0, max_value=7),
)
@settings(max_examples=150, deadline=None)
def test_model_batching_preserves_passages_and_bounds(
    lengths: list[int],
    max_chars: int,
    max_passages: int,
    overlap: int,
) -> None:
    assume(overlap < max_passages)

    document = _document(lengths)
    model = RecordingModel()
    extractor = ModelClaimExtractor(
        model,
        batching=ModelBatchingPolicy(
            max_chars=max_chars,
            max_passages=max_passages,
            overlap_passages=overlap,
        ),
    )

    extractor.extract(document)

    original = list(document.sections[0].passages)
    original_ids = [passage.passage_id for passage in original]
    seen_ids = {
        passage.passage_id
        for request in model.requests
        for passage in request.passages
    }
    assert seen_ids == set(original_ids)

    for request in model.requests:
        assert 1 <= len(request.passages) <= max_passages
        ordinals = [passage.ordinal for passage in request.passages]
        assert ordinals == list(range(ordinals[0], ordinals[0] + len(ordinals)))

        request_chars = sum(len(passage.text) for passage in request.passages)
        if request_chars > max_chars:
            assert len(request.passages) == 1
            assert len(request.passages[0].text) > max_chars

    starts = [request.passages[0].ordinal for request in model.requests]
    assert starts == sorted(set(starts))
