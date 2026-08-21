from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.extraction import (
    Claim,
    EquationEvidence,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    FigureEvidence,
    TableEvidence,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.domain.source_artifacts import (
    Equation,
    EquationRef,
    Figure,
    FigureRef,
    PassageSpan,
    Table,
    TableCellRange,
)
from tarkka.evaluation.claims import evaluate_claims
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository


def _document() -> Document:
    document_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text="The model improved log loss.",
        char_start=0,
        char_end=len("The model improved log loss."),
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
        title="Generalized evidence fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
        figures=(
            Figure(
                figure_id=uuid4(),
                document_id=document_id,
                ordinal=0,
                page_number=3,
                label="Figure 1",
                caption="Calibration by inning",
                figure_type="chart",
            ),
        ),
        tables=(
            Table(
                table_id=uuid4(),
                document_id=document_id,
                ordinal=0,
                page_number=4,
                label="Table 1",
                caption="Model comparison",
                row_count=5,
                column_count=4,
            ),
        ),
        equations=(
            Equation(
                equation_id=uuid4(),
                document_id=document_id,
                ordinal=0,
                page_number=5,
                label="Eq. 1",
                source_text="p = 1 / (1 + exp(-x))",
            ),
        ),
    )


def _run(document: Document) -> tuple[ExtractionRun, ExtractionProvenance]:
    run = ExtractionRun(
        run_id=uuid4(),
        document_id=document.document_id,
        extractor_name="fixture",
        extractor_version="1",
    )
    return run, ExtractionProvenance(run_id=run.run_id, confidence=0.9)


def test_locator_contracts_are_typed_and_exact() -> None:
    document = _document()
    passage = document.sections[0].passages[0]
    run, provenance = _run(document)

    passage_evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=4,
        passage_char_end=9,
        provenance=provenance,
    )
    figure_evidence = FigureEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        figure_id=document.figures[0].figure_id,
        provenance=provenance,
    )
    table_evidence = TableEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        table_id=document.tables[0].table_id,
        row_start=1,
        row_end=3,
        column_start=0,
        column_end=2,
        provenance=provenance,
    )
    equation_evidence = EquationEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        equation_id=document.equations[0].equation_id,
        provenance=provenance,
    )

    assert passage_evidence.locator == PassageSpan(passage.section_id, passage.passage_id, 4, 9)
    assert figure_evidence.locator == FigureRef(document.figures[0].figure_id)
    assert table_evidence.locator == TableCellRange(document.tables[0].table_id, 1, 3, 0, 2)
    assert equation_evidence.locator == EquationRef(document.equations[0].equation_id)

    claim = Claim(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=(
            passage_evidence.evidence_id,
            figure_evidence.evidence_id,
            table_evidence.evidence_id,
            equation_evidence.evidence_id,
        ),
        provenance=provenance,
        text="The study reports a model improvement.",
    )
    batch = ExtractionBatch(
        document=document,
        run=run,
        evidence=(passage_evidence, figure_evidence, table_evidence, equation_evidence),
        extractions=(claim,),
    )

    assert batch.evidence == (
        passage_evidence,
        figure_evidence,
        table_evidence,
        equation_evidence,
    )


def test_generalized_evidence_fails_closed_on_unknown_source() -> None:
    document = _document()
    run, provenance = _run(document)
    bad = FigureEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        figure_id=uuid4(),
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=(bad.evidence_id,),
        provenance=provenance,
        text="Unsupported figure claim",
    )

    with pytest.raises(ValueError, match="normalized figure"):
        ExtractionBatch(document=document, run=run, evidence=(bad,), extractions=(claim,))


def test_table_evidence_fails_closed_outside_known_shape() -> None:
    document = _document()
    run, provenance = _run(document)
    bad = TableEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        table_id=document.tables[0].table_id,
        row_start=0,
        row_end=6,
        column_start=0,
        column_end=1,
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=(bad.evidence_id,),
        provenance=provenance,
        text="Out-of-range table claim",
    )

    with pytest.raises(ValueError, match="row range"):
        ExtractionBatch(document=document, run=run, evidence=(bad,), extractions=(claim,))


def test_document_rejects_cross_document_source_artifact() -> None:
    document_id = uuid4()
    foreign = Figure(figure_id=uuid4(), document_id=uuid4(), ordinal=0)

    with pytest.raises(ValueError, match="figure does not belong"):
        Document(
            document_id=document_id,
            artifact_id=uuid4(),
            title="Invalid",
            parser_name="fixture",
            parser_version="1",
            sections=(),
            figures=(foreign,),
        )


def test_document_rejects_duplicate_source_artifact_ordinals() -> None:
    document_id = uuid4()
    figures = (
        Figure(figure_id=uuid4(), document_id=document_id, ordinal=0),
        Figure(figure_id=uuid4(), document_id=document_id, ordinal=0),
    )

    with pytest.raises(ValueError, match="figure ordinals must be unique"):
        Document(
            document_id=document_id,
            artifact_id=uuid4(),
            title="Duplicate ordinals",
            parser_name="fixture",
            parser_version="1",
            sections=(),
            figures=figures,
        )


def test_claim_evaluation_explicitly_rejects_non_passage_evidence() -> None:
    document = _document()
    run, provenance = _run(document)
    figure_evidence = FigureEvidence(
        evidence_id=uuid4(),
        document_id=document.document_id,
        figure_id=document.figures[0].figure_id,
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=(figure_evidence.evidence_id,),
        provenance=provenance,
        text="Figure-backed claim",
    )
    batch = ExtractionBatch(
        document=document,
        run=run,
        evidence=(figure_evidence,),
        extractions=(claim,),
    )

    with pytest.raises(ValueError, match="supports passage evidence only"):
        evaluate_claims(batch, ())


def test_json_repository_round_trips_mixed_evidence(tmp_path: Path) -> None:
    document = _document()
    passage = document.sections[0].passages[0]
    run, provenance = _run(document)
    evidence = (
        Evidence.from_passage(
            evidence_id=uuid4(),
            passage=passage,
            passage_char_start=0,
            passage_char_end=3,
            provenance=provenance,
        ),
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
            column_start=1,
            column_end=3,
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
        text="Mixed evidence claim",
    )
    batch = ExtractionBatch(document=document, run=run, evidence=evidence, extractions=(claim,))
    repository = JsonExtractionRepository(tmp_path / "extractions.json")

    repository.save_batch(batch)

    assert repository.list_evidence(document.document_id, run_id=run.run_id) == tuple(
        sorted(evidence, key=lambda item: str(item.evidence_id))
    )


def test_json_repository_reads_legacy_passage_evidence_without_source_kind(tmp_path: Path) -> None:
    document = _document()
    passage = document.sections[0].passages[0]
    run, provenance = _run(document)
    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=3,
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=(evidence.evidence_id,),
        provenance=provenance,
        text="Legacy evidence claim",
    )
    path = tmp_path / "extractions.json"
    repository = JsonExtractionRepository(path)
    repository.save_batch(
        ExtractionBatch(document=document, run=run, evidence=(evidence,), extractions=(claim,))
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    batch_payload = next(iter(raw["batches"].values()))
    batch_payload["evidence"][0].pop("source_kind")
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = repository.get_evidence(evidence.evidence_id)

    assert loaded == evidence
