from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.conformance import ExtractionRepositoryContract
from tarkka.domain.extraction import (
    Claim,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    Limitation,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.storage import json_extraction_repository
from tarkka.infrastructure.storage.json_extraction_repository import (
    ExtractionConflictError,
    JsonExtractionRepository,
)

pytestmark = pytest.mark.contract

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000a01")
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000a02")
_SECTION_ID = UUID("00000000-0000-0000-0000-000000000a03")
_PASSAGE_ID = UUID("00000000-0000-0000-0000-000000000a04")
_RUN_ID = UUID("00000000-0000-0000-0000-000000000a05")
_EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000a06")
_CLAIM_ID = UUID("00000000-0000-0000-0000-000000000a07")
_LIMITATION_ID = UUID("00000000-0000-0000-0000-000000000a08")
_MISSING_RUN_ID = UUID("00000000-0000-0000-0000-000000000aff")
_TEXT = "The model improved log loss by 8% on the held-out season."


def _batch() -> ExtractionBatch:
    passage = Passage(
        passage_id=_PASSAGE_ID,
        document_id=_DOCUMENT_ID,
        section_id=_SECTION_ID,
        ordinal=0,
        text=_TEXT,
        char_start=0,
        char_end=len(_TEXT),
    )
    document = Document(
        document_id=_DOCUMENT_ID,
        artifact_id=_ARTIFACT_ID,
        title="Fixture paper",
        parser_name="fixture-parser",
        parser_version="1",
        sections=(
            Section(
                section_id=_SECTION_ID,
                document_id=_DOCUMENT_ID,
                ordinal=0,
                title="Results",
                passages=(passage,),
            ),
        ),
    )
    run = ExtractionRun(
        run_id=_RUN_ID,
        document_id=_DOCUMENT_ID,
        extractor_name="fixture-extractor",
        extractor_version="1",
    )
    provenance = ExtractionProvenance(run_id=_RUN_ID, confidence=0.95)
    evidence = Evidence.from_passage(
        evidence_id=_EVIDENCE_ID,
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(_TEXT),
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=_CLAIM_ID,
        document_id=_DOCUMENT_ID,
        evidence_ids=(_EVIDENCE_ID,),
        provenance=provenance,
        text="The model improved held-out log loss.",
    )
    limitation = Limitation(
        extraction_id=_LIMITATION_ID,
        document_id=_DOCUMENT_ID,
        evidence_ids=(_EVIDENCE_ID,),
        provenance=provenance,
        text="Evaluation covers one held-out season.",
    )
    return ExtractionBatch(
        document=document,
        run=run,
        evidence=(evidence,),
        extractions=(claim, limitation),
    )


def test_json_extraction_repository_satisfies_missing_read_contract(tmp_path: Path) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")

    ExtractionRepositoryContract.assert_missing_reads_are_empty(
        repository,
        _batch(),
        _MISSING_RUN_ID,
    )


def test_json_extraction_repository_satisfies_round_trip_contract(tmp_path: Path) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")

    ExtractionRepositoryContract.assert_batch_round_trip(repository, _batch())


def test_json_extraction_repository_satisfies_idempotent_save_contract(
    tmp_path: Path,
) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")

    ExtractionRepositoryContract.assert_repeated_save_is_idempotent(repository, _batch())


def test_json_extraction_repository_preserves_kind_and_evidence_links(tmp_path: Path) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")

    ExtractionRepositoryContract.assert_kind_filter_preserves_evidence_links(
        repository,
        _batch(),
    )


def test_extraction_contract_rejects_single_kind_fixture(tmp_path: Path) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")
    batch = _batch()
    single_kind = replace(batch, extractions=batch.extractions[:1])

    with pytest.raises(AssertionError, match="at least two extraction kinds"):
        ExtractionRepositoryContract.assert_kind_filter_preserves_evidence_links(
            repository,
            single_kind,
        )


def test_json_extraction_repository_rejects_conflicting_run_content(tmp_path: Path) -> None:
    repository = JsonExtractionRepository(tmp_path / "extractions.json")
    original = _batch()
    claim = original.extractions[0]
    assert isinstance(claim, Claim)
    conflicting = replace(
        original,
        extractions=(
            replace(claim, text="Conflicting claim content."),
            *original.extractions[1:],
        ),
    )

    ExtractionRepositoryContract.assert_conflicting_batch_fails_closed(
        repository,
        original,
        conflicting,
        ExtractionConflictError,
    )


def test_json_extraction_repository_fsyncs_parent_directory_after_atomic_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed: list[Path] = []
    monkeypatch.setattr(json_extraction_repository, "_fsync_directory", flushed.append)

    repository = JsonExtractionRepository(tmp_path / "extractions.json")
    repository.save_batch(_batch())

    assert flushed == [repository.path.parent, repository.path.parent]
