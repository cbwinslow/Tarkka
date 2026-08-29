from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from tarkka.domain.extraction import (
    Claim,
    Dataset,
    EquationEvidence,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    FigureEvidence,
    Hypothesis,
    Limitation,
    Method,
    Metric,
    Model,
    ModelProvenance,
    ResearchExtractionBase,
    ResearchObjectKind,
    Result,
    TableEvidence,
    Variable,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.domain.source_artifacts import Equation, Figure, Table

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _document() -> tuple[Document, Passage]:
    document_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text="The model improved calibration.",
        char_start=0,
        char_end=len("The model improved calibration."),
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
        title="Extraction invariant fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
        figures=(Figure(figure_id=uuid4(), document_id=document_id, ordinal=0),),
        tables=(
            Table(
                table_id=uuid4(),
                document_id=document_id,
                ordinal=0,
                row_count=3,
                column_count=2,
            ),
        ),
        equations=(Equation(equation_id=uuid4(), document_id=document_id, ordinal=0),),
    )
    return document, passage


def _run(document_id: UUID) -> ExtractionRun:
    return ExtractionRun(
        run_id=uuid4(),
        document_id=document_id,
        extractor_name="fixture",
        extractor_version="1",
    )


def _provenance(run_id: UUID) -> ExtractionProvenance:
    return ExtractionProvenance(run_id=run_id, confidence=0.9)


def _passage_evidence(passage: Passage, run_id: UUID) -> Evidence:
    return Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=_provenance(run_id),
    )


def _claim(document_id: UUID, evidence_id: UUID, run_id: UUID) -> Claim:
    return Claim(
        extraction_id=uuid4(),
        document_id=document_id,
        evidence_ids=(evidence_id,),
        provenance=_provenance(run_id),
        text="Calibration improved.",
    )


def _valid_batch() -> tuple[ExtractionBatch, Passage, Evidence, Claim]:
    document, passage = _document()
    run = _run(document.document_id)
    evidence = _passage_evidence(passage, run.run_id)
    claim = _claim(document.document_id, evidence.evidence_id, run.run_id)
    return (
        ExtractionBatch(
            document=document,
            run=run,
            evidence=(evidence,),
            extractions=(claim,),
        ),
        passage,
        evidence,
        claim,
    )


@pytest.mark.parametrize(
    ("provider", "name"),
    [(" ", "model"), ("provider", " ")],
)
def test_model_provenance_rejects_blank_provider_or_name(provider: str, name: str) -> None:
    with pytest.raises(ValueError, match="provider/name"):
        ModelProvenance(provider=provider, name=name)


def test_model_provenance_rejects_blank_version_when_provided() -> None:
    with pytest.raises(ValueError, match="version"):
        ModelProvenance(provider="provider", name="model", version=" ")


@pytest.mark.parametrize(
    ("extractor_name", "extractor_version"),
    [(" ", "1"), ("fixture", " ")],
)
def test_extraction_run_rejects_blank_extractor_identity(
    extractor_name: str,
    extractor_version: str,
) -> None:
    with pytest.raises(ValueError, match="name/version"):
        ExtractionRun(
            run_id=uuid4(),
            document_id=uuid4(),
            extractor_name=extractor_name,
            extractor_version=extractor_version,
        )


def test_extraction_run_rejects_blank_contract_version() -> None:
    with pytest.raises(ValueError, match="contract version"):
        ExtractionRun(
            run_id=uuid4(),
            document_id=uuid4(),
            extractor_name="fixture",
            extractor_version="1",
            contract_version=" ",
        )


def test_extraction_provenance_rejects_blank_reasoning_summary() -> None:
    with pytest.raises(ValueError, match="reasoning summary"):
        ExtractionProvenance(run_id=uuid4(), reasoning_summary=" ")


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 1), (1, 1)],
)
def test_evidence_rejects_invalid_character_ranges(start: int, end: int) -> None:
    with pytest.raises(ValueError, match="invalid evidence passage character range"):
        Evidence(
            evidence_id=uuid4(),
            document_id=uuid4(),
            section_id=uuid4(),
            passage_id=uuid4(),
            passage_char_start=start,
            passage_char_end=end,
            text="x",
            provenance=_provenance(uuid4()),
        )


def test_evidence_rejects_range_length_mismatch() -> None:
    with pytest.raises(ValueError, match="range must match"):
        Evidence(
            evidence_id=uuid4(),
            document_id=uuid4(),
            section_id=uuid4(),
            passage_id=uuid4(),
            passage_char_start=0,
            passage_char_end=2,
            text="x",
            provenance=_provenance(uuid4()),
        )


def test_evidence_rejects_blank_text() -> None:
    with pytest.raises(ValueError, match="text must not be blank"):
        Evidence(
            evidence_id=uuid4(),
            document_id=uuid4(),
            section_id=uuid4(),
            passage_id=uuid4(),
            passage_char_start=0,
            passage_char_end=1,
            text=" ",
            provenance=_provenance(uuid4()),
        )


def test_evidence_from_passage_rejects_empty_range() -> None:
    _, passage = _document()
    with pytest.raises(ValueError, match="must not be empty"):
        Evidence.from_passage(
            evidence_id=uuid4(),
            passage=passage,
            passage_char_start=1,
            passage_char_end=1,
            provenance=_provenance(uuid4()),
        )


def test_research_extraction_rejects_duplicate_evidence_ids() -> None:
    evidence_id = uuid4()
    with pytest.raises(ValueError, match="evidence IDs must be unique"):
        Claim(
            extraction_id=uuid4(),
            document_id=uuid4(),
            evidence_ids=(evidence_id, evidence_id),
            provenance=_provenance(uuid4()),
            text="Duplicate evidence reference.",
        )


def test_research_extraction_base_kind_requires_concrete_type() -> None:
    base = ResearchExtractionBase(
        extraction_id=uuid4(),
        document_id=uuid4(),
        evidence_ids=(uuid4(),),
        provenance=_provenance(uuid4()),
    )
    with pytest.raises(NotImplementedError):
        _ = base.kind


def _common_extraction_fields() -> dict[str, Any]:
    return {
        "extraction_id": uuid4(),
        "document_id": uuid4(),
        "evidence_ids": (uuid4(),),
        "provenance": _provenance(uuid4()),
    }


@pytest.mark.parametrize(
    ("extraction_type", "field_name", "message"),
    [
        (Claim, "text", "claim text/type"),
        (Claim, "claim_type", "claim text/type"),
        (Hypothesis, "text", "hypothesis text"),
        (Method, "name", "method name"),
        (Dataset, "name", "dataset name"),
        (Variable, "name", "variable name"),
        (Model, "name", "model name"),
        (Metric, "name", "metric name"),
        (Result, "text", "result text"),
        (Limitation, "text", "limitation text"),
    ],
)
def test_research_extractions_reject_blank_required_fields(
    extraction_type: type[ResearchExtractionBase],
    field_name: str,
    message: str,
) -> None:
    values = _common_extraction_fields()
    if extraction_type is Claim:
        values.update(text="claim", claim_type="proposition")
    elif extraction_type in {Hypothesis, Result, Limitation}:
        values["text"] = "statement"
    else:
        values["name"] = "name"
    values[field_name] = " "

    with pytest.raises(ValueError, match=message):
        extraction_type(**values)


@pytest.mark.parametrize(
    ("item", "kind"),
    [
        (Hypothesis, ResearchObjectKind.HYPOTHESIS),
        (Method, ResearchObjectKind.METHOD),
        (Dataset, ResearchObjectKind.DATASET),
        (Variable, ResearchObjectKind.VARIABLE),
        (Model, ResearchObjectKind.MODEL),
        (Metric, ResearchObjectKind.METRIC),
        (Result, ResearchObjectKind.RESULT),
        (Limitation, ResearchObjectKind.LIMITATION),
    ],
)
def test_research_extraction_kinds_are_stable(
    item: type[ResearchExtractionBase],
    kind: ResearchObjectKind,
) -> None:
    values = _common_extraction_fields()
    if item in {Hypothesis, Result, Limitation}:
        values["text"] = "statement"
    else:
        values["name"] = "name"
    extraction = item(**values)
    assert extraction.kind is kind


def test_extraction_batch_rejects_empty_extractions_with_valid_evidence() -> None:
    document, passage = _document()
    run = _run(document.document_id)
    evidence = _passage_evidence(passage, run.run_id)
    with pytest.raises(ValueError, match="at least one extraction"):
        ExtractionBatch(document=document, run=run, evidence=(evidence,), extractions=())


def test_extraction_batch_rejects_duplicate_evidence_ids() -> None:
    batch, _, evidence, claim = _valid_batch()
    with pytest.raises(ValueError, match="evidence IDs must be unique"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(evidence, evidence),
            extractions=(claim,),
        )


def test_extraction_batch_rejects_evidence_from_another_run() -> None:
    batch, _, evidence, claim = _valid_batch()
    wrong_run = replace(evidence, provenance=_provenance(uuid4()))
    with pytest.raises(ValueError, match="evidence does not belong to extraction batch run"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(wrong_run,),
            extractions=(claim,),
        )


def test_extraction_batch_rejects_evidence_from_another_document() -> None:
    batch, _, evidence, claim = _valid_batch()
    foreign = replace(evidence, document_id=uuid4())
    with pytest.raises(ValueError, match="evidence does not belong to extraction batch document"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(foreign,),
            extractions=(claim,),
        )


@pytest.mark.parametrize("field_name", ["passage_id", "section_id"])
def test_extraction_batch_rejects_unresolvable_passage_evidence(field_name: str) -> None:
    batch, _, evidence, claim = _valid_batch()
    invalid = replace(evidence, **{field_name: uuid4()})
    with pytest.raises(ValueError, match="does not resolve to a normalized passage"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(invalid,),
            extractions=(claim,),
        )


def test_extraction_batch_rejects_passage_range_beyond_normalized_text() -> None:
    batch, passage, evidence, claim = _valid_batch()
    invalid = replace(
        evidence,
        passage_char_end=len(passage.text) + 1,
        text=passage.text + "x",
    )
    with pytest.raises(ValueError, match="range is outside"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(invalid,),
            extractions=(claim,),
        )


def test_extraction_batch_rejects_missing_table_and_equation_targets() -> None:
    document, _ = _document()
    run = _run(document.document_id)
    provenance = _provenance(run.run_id)

    missing_table = TableEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        table_id=uuid4(),
        row_start=0,
        row_end=1,
        column_start=0,
        column_end=1,
        provenance=provenance,
    )
    table_claim = _claim(document.document_id, missing_table.evidence_id, run.run_id)
    with pytest.raises(ValueError, match="normalized table"):
        ExtractionBatch(
            document=document,
            run=run,
            evidence=(missing_table,),
            extractions=(table_claim,),
        )

    missing_equation = EquationEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        equation_id=uuid4(),
        provenance=provenance,
    )
    equation_claim = _claim(document.document_id, missing_equation.evidence_id, run.run_id)
    with pytest.raises(ValueError, match="normalized equation"):
        ExtractionBatch(
            document=document,
            run=run,
            evidence=(missing_equation,),
            extractions=(equation_claim,),
        )


def test_extraction_batch_rejects_table_column_range_outside_shape() -> None:
    document, _ = _document()
    run = _run(document.document_id)
    evidence = TableEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        table_id=document.tables[0].table_id,
        row_start=0,
        row_end=1,
        column_start=0,
        column_end=3,
        provenance=_provenance(run.run_id),
    )
    claim = _claim(document.document_id, evidence.evidence_id, run.run_id)
    with pytest.raises(ValueError, match="column range"):
        ExtractionBatch(document=document, run=run, evidence=(evidence,), extractions=(claim,))


def test_extraction_batch_accepts_table_evidence_when_shape_is_unknown() -> None:
    document, _ = _document()
    unbounded_table = replace(document.tables[0], row_count=None, column_count=None)
    document = replace(document, tables=(unbounded_table,))
    run = _run(document.document_id)
    evidence = TableEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        table_id=unbounded_table.table_id,
        row_start=10,
        row_end=20,
        column_start=10,
        column_end=20,
        provenance=_provenance(run.run_id),
    )
    claim = _claim(document.document_id, evidence.evidence_id, run.run_id)

    batch = ExtractionBatch(document=document, run=run, evidence=(evidence,), extractions=(claim,))
    assert batch.evidence == (evidence,)


def test_extraction_batch_rejects_extraction_from_another_document() -> None:
    batch, _, evidence, claim = _valid_batch()
    foreign = replace(claim, document_id=uuid4())
    with pytest.raises(ValueError, match="extraction does not belong to extraction batch document"):
        ExtractionBatch(
            document=batch.document,
            run=batch.run,
            evidence=(evidence,),
            extractions=(foreign,),
        )


def test_extraction_batch_accepts_all_generalized_evidence_types() -> None:
    document, passage = _document()
    run = _run(document.document_id)
    provenance = _provenance(run.run_id)
    evidence = (
        _passage_evidence(passage, run.run_id),
        FigureEvidence(
            evidence_id=uuid4(),
            document_id=document.document_id,
            figure_id=document.figures[0].figure_id,
            provenance=provenance,
        ),
        TableEvidence(
            evidence_id=uuid4(),
            document_id=document.document_id,
            table_id=document.tables[0].table_id,
            row_start=0,
            row_end=1,
            column_start=0,
            column_end=1,
            provenance=provenance,
        ),
        EquationEvidence(
            evidence_id=uuid4(),
            document_id=document.document_id,
            equation_id=document.equations[0].equation_id,
            provenance=provenance,
        ),
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        provenance=provenance,
        text="All evidence types resolve.",
    )
    batch = ExtractionBatch(document=document, run=run, evidence=evidence, extractions=(claim,))
    assert len(batch.evidence) == 4
