from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from tarkka.application.extraction import ExtractionService
from tarkka.domain.extraction import Claim
from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.extraction.model_claims import (
    ModelClaimExtractor,
    NoModelClaimsFoundError,
)
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.ports.model_claims import (
    EvidenceSelector,
    ModelClaimCandidate,
    ModelClaimRequest,
)


@dataclass
class FakeStructuredClaimModel:
    candidates: tuple[ModelClaimCandidate, ...]
    provider: str = "fixture"
    model_name: str = "fixture-model"
    model_version: str | None = "1"
    last_request: ModelClaimRequest | None = None

    def extract_claims(self, request: ModelClaimRequest) -> tuple[ModelClaimCandidate, ...]:
        self.last_request = request
        return self.candidates


def _document(text: str) -> Document:
    document_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text=text,
        char_start=0,
        char_end=len(text),
    )
    section = Section(
        section_id=section_id,
        document_id=document_id,
        ordinal=0,
        title="Results",
        passages=(passage,),
    )
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Fixture study",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
    )


def _selector(document: Document, text: str) -> EvidenceSelector:
    passage = document.sections[0].passages[0]
    start = passage.text.index(text)
    return EvidenceSelector(
        passage_id=passage.passage_id,
        char_start=start,
        char_end=start + len(text),
    )


def test_model_extractor_preserves_exact_evidence_and_model_provenance(tmp_path) -> None:
    evidence_text = "Held-out log loss improved by 8%."
    document = _document(f"Background. {evidence_text} Discussion follows.")
    model = FakeStructuredClaimModel(
        candidates=(
            ModelClaimCandidate(
                text="The evaluated model improved held-out log loss.",
                evidence=(_selector(document, evidence_text),),
                confidence=0.93,
                reasoning_summary="Direct quantitative result statement.",
            ),
        )
    )
    repository = JsonExtractionRepository(tmp_path / "extractions.json")

    batch = ExtractionService(repository).extract(document, ModelClaimExtractor(model))

    assert model.last_request is not None
    assert model.last_request.document_id == document.document_id
    assert model.last_request.passages[0].text == document.sections[0].passages[0].text
    assert batch.run.model is not None
    assert batch.run.model.provider == "fixture"
    assert batch.run.model.name == "fixture-model"
    assert batch.run.model.version == "1"
    claim = batch.extractions[0]
    assert isinstance(claim, Claim)
    assert claim.text == "The evaluated model improved held-out log loss."
    assert claim.provenance.confidence == 0.93
    assert batch.evidence[0].text == evidence_text

    persisted = repository.get_extraction(claim.extraction_id)
    assert persisted == claim


def test_model_extractor_rejects_unknown_evidence_passage() -> None:
    document = _document("The study reports a significant improvement.")
    model = FakeStructuredClaimModel(
        candidates=(
            ModelClaimCandidate(
                text="The study reports an improvement.",
                evidence=(EvidenceSelector(uuid4(), 0, 10),),
                confidence=0.8,
            ),
        )
    )

    with pytest.raises(ValueError, match="unknown passage"):
        ModelClaimExtractor(model).extract(document)


def test_model_extractor_rejects_out_of_range_evidence() -> None:
    document = _document("The study reports a significant improvement.")
    passage = document.sections[0].passages[0]
    model = FakeStructuredClaimModel(
        candidates=(
            ModelClaimCandidate(
                text="The study reports an improvement.",
                evidence=(EvidenceSelector(passage.passage_id, 0, len(passage.text) + 10),),
                confidence=0.8,
            ),
        )
    )

    with pytest.raises(ValueError, match="contained within the passage"):
        ModelClaimExtractor(model).extract(document)


def test_model_extractor_rejects_empty_model_response() -> None:
    document = _document("The study reports a significant improvement.")
    model = FakeStructuredClaimModel(candidates=())

    with pytest.raises(NoModelClaimsFoundError, match="no structured claim"):
        ModelClaimExtractor(model).extract(document)


def test_model_candidate_requires_evidence() -> None:
    with pytest.raises(ValueError, match="must cite evidence"):
        ModelClaimCandidate(text="Unsupported claim", evidence=(), confidence=0.5)


def test_model_extractor_validates_model_identity() -> None:
    model = FakeStructuredClaimModel(candidates=(), provider=" ")
    with pytest.raises(ValueError, match="provider/name"):
        ModelClaimExtractor(model)


def test_selector_is_document_local_not_global_offset() -> None:
    document = _document("The model improves accuracy.")
    passage_id: UUID = document.sections[0].passages[0].passage_id
    selector = EvidenceSelector(passage_id=passage_id, char_start=4, char_end=9)
    assert selector.char_start == 4
    assert selector.char_end == 9
