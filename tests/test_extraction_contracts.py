from __future__ import annotations

from uuid import uuid4

import pytest

from tarkka.domain.extraction import (
    AttributionKind,
    Claim,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    HumanReviewState,
    Limitation,
    ModelProvenance,
    ResearchObjectKind,
)
from tarkka.domain.models import Passage


def _passage(text: str = "The model improved log loss by 8% on the held-out season.") -> Passage:
    return Passage(
        passage_id=uuid4(),
        document_id=uuid4(),
        section_id=uuid4(),
        ordinal=0,
        text=text,
        char_start=0,
        char_end=len(text),
    )


def _provenance(*, confidence: float = 0.93) -> ExtractionProvenance:
    return ExtractionProvenance(
        run_id=uuid4(),
        extractor_name="fixture-extractor",
        extractor_version="1.0.0",
        model=ModelProvenance(provider="openai-compatible", name="fixture-model", version="v1"),
        confidence=confidence,
    )


def test_evidence_from_passage_preserves_exact_local_span() -> None:
    passage = _passage()
    start = passage.text.index("improved")
    end = passage.text.index(" on the")

    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=start,
        passage_char_end=end,
        provenance=_provenance(),
    )

    assert evidence.document_id == passage.document_id
    assert evidence.section_id == passage.section_id
    assert evidence.passage_id == passage.passage_id
    assert evidence.text == "improved log loss by 8%"
    assert evidence.passage_char_start == start
    assert evidence.passage_char_end == end


def test_evidence_rejects_span_outside_passage() -> None:
    passage = _passage("short")

    with pytest.raises(ValueError, match="contained within"):
        Evidence.from_passage(
            evidence_id=uuid4(),
            passage=passage,
            passage_char_start=0,
            passage_char_end=99,
            provenance=_provenance(),
        )


def test_extraction_requires_at_least_one_evidence_reference() -> None:
    with pytest.raises(ValueError, match="must reference evidence"):
        Claim(
            extraction_id=uuid4(),
            document_id=uuid4(),
            evidence_ids=(),
            provenance=_provenance(),
            text="A claim without evidence must fail.",
        )


def test_claim_exposes_typed_kind_and_review_provenance() -> None:
    passage = _passage()
    provenance = ExtractionProvenance(
        run_id=uuid4(),
        extractor_name="rules",
        extractor_version="2",
        confidence=1.0,
        human_review_state=HumanReviewState.VERIFIED,
    )
    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=passage.document_id,
        evidence_ids=(evidence.evidence_id,),
        provenance=provenance,
        text="The model improved held-out log loss.",
    )

    assert claim.kind is ResearchObjectKind.CLAIM
    assert claim.provenance.model is None
    assert claim.provenance.human_review_state is HumanReviewState.VERIFIED


def test_author_stated_and_inferred_limitations_are_distinct() -> None:
    document_id = uuid4()
    evidence_id = uuid4()
    provenance = _provenance()

    author_stated = Limitation(
        extraction_id=uuid4(),
        document_id=document_id,
        evidence_ids=(evidence_id,),
        provenance=provenance,
        attribution=AttributionKind.AUTHOR_STATED,
        text="The sample contains only one season.",
    )
    inferred = Limitation(
        extraction_id=uuid4(),
        document_id=document_id,
        evidence_ids=(evidence_id,),
        provenance=provenance,
        attribution=AttributionKind.EXTRACTOR_INFERRED,
        text="External validity may be limited.",
    )

    assert author_stated.attribution is AttributionKind.AUTHOR_STATED
    assert inferred.attribution is AttributionKind.EXTRACTOR_INFERRED


def test_extraction_batch_rejects_evidence_from_another_document() -> None:
    passage = _passage()
    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=_provenance(),
    )

    with pytest.raises(ValueError, match="does not belong"):
        ExtractionBatch(document_id=uuid4(), evidence=(evidence,), extractions=())


def test_extraction_batch_rejects_unknown_evidence_reference() -> None:
    passage = _passage()
    provenance = _provenance()
    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=passage.document_id,
        evidence_ids=(uuid4(),),
        provenance=provenance,
        text="This references evidence outside the batch.",
    )

    with pytest.raises(ValueError, match="outside the batch"):
        ExtractionBatch(
            document_id=passage.document_id,
            evidence=(evidence,),
            extractions=(claim,),
        )


def test_provenance_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        _provenance(confidence=1.1)
