from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from tarkka.domain.extraction import (
    AttributionKind,
    Claim,
    Dataset,
    Evidence,
    EvidenceRecord,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    Hypothesis,
    Limitation,
    Method,
    Metric,
    Model,
    ResearchExtraction,
    ResearchObjectKind,
    Result,
    Variable,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.storage import json_extraction_repository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _batch() -> ExtractionBatch:
    document_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text="Evidence text.",
        char_start=0,
        char_end=len("Evidence text."),
    )
    document = Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Extraction coverage fixture",
        parser_name="fixture-parser",
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
        run_id=uuid4(),
        document_id=document_id,
        extractor_name="coverage-extractor",
        extractor_version="1",
    )
    provenance = ExtractionProvenance(
        run_id=run.run_id,
        confidence=0.9,
        reasoning_summary="coverage fixture",
    )
    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=provenance,
    )
    evidence_ids = (evidence.evidence_id,)
    extractions: tuple[ResearchExtraction, ...] = (
        Claim(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            text="Claim text",
        ),
        Hypothesis(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            text="Hypothesis text",
        ),
        Method(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            name="Method",
            description="Method description",
        ),
        Dataset(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            name="Dataset",
            description="Dataset description",
        ),
        Variable(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            name="Variable",
            role="predictor",
        ),
        Model(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            name="Model",
            family="linear",
        ),
        Metric(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            name="Accuracy",
            value_text="0.91",
            unit="ratio",
        ),
        Result(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            text="Result text",
            direction="positive",
        ),
        Limitation(
            extraction_id=uuid4(),
            document_id=document_id,
            evidence_ids=evidence_ids,
            provenance=provenance,
            text="Limitation text",
        ),
    )
    return ExtractionBatch(
        document=document,
        run=run,
        evidence=(evidence,),
        extractions=extractions,
    )


def test_all_extraction_kinds_round_trip(tmp_path: Path) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")
    batch = _batch()

    repository.save_batch(batch)

    loaded = repository.list_extractions(batch.document_id, run_id=batch.run.run_id)
    assert {item.extraction_id: item for item in loaded} == {
        item.extraction_id: item for item in batch.extractions
    }


def test_missing_getters_and_foreign_document_queries_are_empty(tmp_path: Path) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")
    batch = _batch()
    repository.save_batch(batch)

    assert repository.get_extraction(uuid4()) is None
    assert repository.get_evidence(uuid4()) is None
    assert repository.list_extractions(uuid4()) == ()
    assert repository.list_evidence(uuid4()) == ()


def test_extraction_query_validation_rejects_invalid_pages(tmp_path: Path) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")

    with pytest.raises(ValueError, match="offset must be non-negative"):
        repository.list_evidence(uuid4(), offset=-1)
    with pytest.raises(ValueError, match="limit must be positive"):
        repository.list_extractions(uuid4(), limit=0)


def test_evidence_serialization_rejects_unsupported_runtime_type() -> None:
    provenance = ExtractionProvenance(run_id=uuid4())
    unsupported = cast(
        EvidenceRecord,
        SimpleNamespace(
            evidence_id=uuid4(),
            document_id=uuid4(),
            provenance=provenance,
        ),
    )

    with pytest.raises(TypeError, match="unsupported evidence type"):
        json_extraction_repository._evidence_to_dict(unsupported)


def test_evidence_deserialization_rejects_unknown_source_kind() -> None:
    provenance = ExtractionProvenance(run_id=uuid4())
    raw = {
        "evidence_id": str(uuid4()),
        "document_id": str(uuid4()),
        "provenance": json_extraction_repository._provenance_to_dict(provenance),
        "source_kind": "audio",
    }

    with pytest.raises(ValueError, match="unsupported evidence source_kind"):
        json_extraction_repository._evidence_from_dict(raw)


def test_extraction_serialization_rejects_unsupported_runtime_type() -> None:
    provenance = ExtractionProvenance(run_id=uuid4())
    unsupported = cast(
        ResearchExtraction,
        SimpleNamespace(
            extraction_id=uuid4(),
            document_id=uuid4(),
            evidence_ids=(uuid4(),),
            provenance=provenance,
            attribution=AttributionKind.AUTHOR_STATED,
            kind=ResearchObjectKind.CLAIM,
        ),
    )

    with pytest.raises(TypeError, match="unsupported extraction type"):
        json_extraction_repository._extraction_to_dict(unsupported)


def test_extraction_deserialization_rejects_unknown_kind() -> None:
    provenance = ExtractionProvenance(run_id=uuid4())
    raw = {
        "extraction_id": str(uuid4()),
        "document_id": str(uuid4()),
        "evidence_ids": [str(uuid4())],
        "provenance": json_extraction_repository._provenance_to_dict(provenance),
        "attribution": AttributionKind.AUTHOR_STATED.value,
        "kind": "future_kind",
    }

    with pytest.raises(ValueError, match="unsupported extraction kind"):
        json_extraction_repository._extraction_from_dict(raw)


def test_extraction_deserialization_rejects_non_string_kind() -> None:
    provenance = ExtractionProvenance(run_id=uuid4())
    raw = {
        "extraction_id": str(uuid4()),
        "document_id": str(uuid4()),
        "evidence_ids": [str(uuid4())],
        "provenance": json_extraction_repository._provenance_to_dict(provenance),
        "attribution": AttributionKind.AUTHOR_STATED.value,
        "kind": 7,
    }

    with pytest.raises(TypeError, match="extraction kind must be a string"):
        json_extraction_repository._extraction_from_dict(raw)


def test_directory_fsync_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    open_calls: list[Path] = []

    def record_open(path: Path, flags: int) -> int:
        open_calls.append(path)
        return flags

    monkeypatch.setattr(json_extraction_repository.os, "name", "nt")
    monkeypatch.setattr(json_extraction_repository.os, "open", record_open)

    json_extraction_repository._fsync_directory(tmp_path)

    assert open_calls == []
