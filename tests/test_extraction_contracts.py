from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from tarkka.domain.extraction import (
    AttributionKind,
    Claim,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    HumanReviewState,
    Limitation,
    ModelProvenance,
    ResearchObjectKind,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.ports.extraction import validate_extractor_output


def _document(
    text: str = "The model improved log loss by 8% on the held-out season.",
) -> tuple[Document, Passage]:
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
    document = Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Fixture paper",
        parser_name="fixture-parser",
        parser_version="1",
        sections=(section,),
    )
    return document, passage


def _run(document_id: UUID, *, run_id: UUID | None = None) -> ExtractionRun:
    return ExtractionRun(
        run_id=run_id or uuid4(),
        document_id=document_id,
        extractor_name="fixture-extractor",
        extractor_version="1.0.0",
        model=ModelProvenance(
            provider="openai-compatible",
            name="fixture-model",
            version="v1",
        ),
    )


def _provenance(
    *,
    run_id: UUID | None = None,
    confidence: float = 0.93,
) -> ExtractionProvenance:
    return ExtractionProvenance(
        run_id=run_id or uuid4(),
        confidence=confidence,
    )


def _valid_batch() -> tuple[ExtractionBatch, Evidence, Claim]:
    document, passage = _document()
    run = _run(document.document_id)
    provenance = _provenance(run_id=run.run_id)
    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=(evidence.evidence_id,),
        provenance=provenance,
        text="The model improved held-out log loss.",
    )
    return (
        ExtractionBatch(
            document=document,
            run=run,
            evidence=(evidence,),
            extractions=(claim,),
        ),
        evidence,
        claim,
    )


def test_evidence_from_passage_preserves_exact_local_span() -> None:
    _, passage = _document()
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
    _, passage = _document("short")

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
    document, passage = _document()
    run = _run(document.document_id)
    provenance = ExtractionProvenance(
        run_id=run.run_id,
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
        document_id=document.document_id,
        evidence_ids=(evidence.evidence_id,),
        provenance=provenance,
        text="The model improved held-out log loss.",
    )

    assert claim.kind is ResearchObjectKind.CLAIM
    assert run.model is not None
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


def test_extraction_batch_rejects_empty_batch() -> None:
    document, _ = _document()
    with pytest.raises(ValueError, match="at least one evidence"):
        ExtractionBatch(
            document=document,
            run=_run(document.document_id),
            evidence=(),
            extractions=(),
        )


def test_extraction_batch_rejects_run_for_another_document() -> None:
    batch, _, _ = _valid_batch()
    wrong_document_id = uuid4()
    wrong_run = replace(batch.run, document_id=wrong_document_id)

    with pytest.raises(ValueError, match="run does not belong"):
        replace(batch, run=wrong_run)


def test_extraction_batch_rejects_evidence_from_another_document() -> None:
    _, passage = _document()
    other_document, _ = _document("Other document")
    run = _run(other_document.document_id)
    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=_provenance(run_id=run.run_id),
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=other_document.document_id,
        evidence_ids=(evidence.evidence_id,),
        provenance=_provenance(run_id=run.run_id),
        text="Wrong document.",
    )

    with pytest.raises(ValueError, match="does not belong"):
        ExtractionBatch(
            document=other_document,
            run=run,
            evidence=(evidence,),
            extractions=(claim,),
        )


def test_extraction_batch_rejects_fabricated_evidence_text() -> None:
    batch, evidence, claim = _valid_batch()
    fabricated = replace(evidence, text="x" * len(evidence.text))

    with pytest.raises(ValueError, match="does not match"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(fabricated,),
            extractions=(claim,),
        )


def test_extraction_batch_rejects_unknown_evidence_reference() -> None:
    batch, evidence, claim = _valid_batch()
    invalid_claim = replace(claim, evidence_ids=(uuid4(),))

    with pytest.raises(ValueError, match="outside the batch"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(evidence,),
            extractions=(invalid_claim,),
        )


def test_extraction_batch_rejects_mixed_run_records() -> None:
    batch, evidence, claim = _valid_batch()
    invalid_claim = replace(claim, provenance=_provenance())

    with pytest.raises(ValueError, match="batch run"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(evidence,),
            extractions=(invalid_claim,),
        )


def test_extraction_batch_rejects_duplicate_extraction_ids() -> None:
    batch, evidence, claim = _valid_batch()
    with pytest.raises(ValueError, match="extraction IDs must be unique"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(evidence,),
            extractions=(claim, claim),
        )


def test_validate_extractor_output_checks_document_and_run_metadata() -> None:
    batch, _, _ = _valid_batch()

    class FixtureExtractor:
        name = "fixture-extractor"
        version = "1.0.0"

        def extract(self, document: Document) -> ExtractionBatch:
            return batch

    extractor = FixtureExtractor()
    assert validate_extractor_output(extractor, batch.document, batch) is batch

    mismatched_run = replace(batch.run, extractor_version="2.0.0")
    mismatched_batch = replace(batch, run=mismatched_run)
    with pytest.raises(ValueError, match="version"):
        validate_extractor_output(extractor, batch.document, mismatched_batch)


def test_provenance_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        _provenance(confidence=1.1)
    with pytest.raises(ValueError, match="between 0 and 1"):
        _provenance(confidence=-0.1)
