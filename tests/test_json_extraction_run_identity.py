from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.domain.extraction import (
    Claim,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.storage.json_extraction_repository import (
    ExtractionConflictError,
    JsonExtractionRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _id(value: int) -> UUID:
    return UUID(int=value)


def _batch(*, base: int, run_id: UUID) -> ExtractionBatch:
    document_id = _id(base)
    section_id = _id(base + 1)
    passage = Passage(
        passage_id=_id(base + 2),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text="alpha",
        char_start=0,
        char_end=5,
    )
    document = Document(
        document_id=document_id,
        artifact_id=_id(base + 3),
        title="Fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(
            Section(
                section_id=section_id,
                document_id=document_id,
                ordinal=0,
                title="Results",
                passages=(passage,),
            ),
        ),
    )
    run = ExtractionRun(
        run_id=run_id,
        document_id=document_id,
        extractor_name="fixture",
        extractor_version="1",
    )
    provenance = ExtractionProvenance(run_id=run_id, confidence=1.0)
    evidence = Evidence.from_passage(
        evidence_id=_id(base + 4),
        passage=passage,
        passage_char_start=0,
        passage_char_end=5,
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=_id(base + 5),
        document_id=document_id,
        evidence_ids=(evidence.evidence_id,),
        provenance=provenance,
        text="alpha",
    )
    return ExtractionBatch(
        document=document,
        run=run,
        evidence=(evidence,),
        extractions=(claim,),
    )


def test_save_batch_rejects_run_id_reused_by_another_document(tmp_path: Path) -> None:
    path = tmp_path / "extractions.json"
    repository = JsonExtractionRepository(path)
    run_id = _id(900)
    repository.save_batch(_batch(base=100, run_id=run_id))

    with pytest.raises(ExtractionConflictError, match="already belongs to another batch"):
        repository.save_batch(_batch(base=200, run_id=run_id))


def test_get_run_rejects_ambiguous_legacy_run_id(tmp_path: Path) -> None:
    path = tmp_path / "extractions.json"
    repository = JsonExtractionRepository(path)
    run_id = _id(900)
    first = _batch(base=100, run_id=run_id)
    second = _batch(base=200, run_id=run_id)
    repository.save_batch(first)

    data = json.loads(path.read_text(encoding="utf-8"))
    data["batches"][f"{second.document_id}:{run_id}"] = {
        "run": {
            "run_id": str(run_id),
            "document_id": str(second.document_id),
            "extractor_name": second.run.extractor_name,
            "extractor_version": second.run.extractor_version,
            "contract_version": second.run.contract_version,
            "model": None,
            "extracted_at": second.run.extracted_at.isoformat(),
        },
        "evidence": [],
        "extractions": [],
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ExtractionConflictError, match="ambiguous extraction run id"):
        repository.get_run(run_id)
