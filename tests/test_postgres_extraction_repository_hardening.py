from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import ModuleType
from typing import Any, cast
from uuid import UUID

import pytest

from tarkka.domain.extraction import (
    Claim,
    Evidence,
    EvidenceRecord,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    ResearchExtraction,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.postgres.connection import PostgresOperationError, PostgresSettings
from tarkka.infrastructure.postgres.extraction_repository import (
    PostgresExtractionConflictError,
    PostgresExtractionRepository,
    _batch_has_same_content,
    _evidence_from_row,
    _evidence_params,
    _extraction_payload,
    _run_params,
)

_SETTINGS = PostgresSettings("postgresql://unused")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000f201")
_OTHER_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000f202")
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000f203")
_SECTION_ID = UUID("00000000-0000-0000-0000-00000000f204")
_PASSAGE_ID = UUID("00000000-0000-0000-0000-00000000f205")
_RUN_ID = UUID("00000000-0000-0000-0000-00000000f206")
_EVIDENCE_ID = UUID("00000000-0000-0000-0000-00000000f207")
_EXTRACTION_ID = UUID("00000000-0000-0000-0000-00000000f208")
_EXTRACTED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_TEXT = "evidence"


@dataclass
class _Cursor:
    row: tuple[Any, ...] | None = None
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    rowcount: int = 1

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


@dataclass
class _Connection:
    cursors: list[_Cursor]
    calls: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)
    closed: bool = False
    commits: int = 0
    rollbacks: int = 0

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        if not self.cursors:
            raise AssertionError(f"unexpected SQL execution: {sql}")
        return self.cursors.pop(0)

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_: Any) -> None:
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _FailingConnection(_Connection):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        raise self.error


def _document() -> Document:
    passage = Passage(
        passage_id=_PASSAGE_ID,
        document_id=_DOCUMENT_ID,
        section_id=_SECTION_ID,
        ordinal=0,
        text=_TEXT,
        char_start=0,
        char_end=len(_TEXT),
    )
    section = Section(
        section_id=_SECTION_ID,
        document_id=_DOCUMENT_ID,
        ordinal=0,
        title="Fixture",
        passages=(passage,),
    )
    return Document(
        document_id=_DOCUMENT_ID,
        artifact_id=_ARTIFACT_ID,
        title="Fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
    )


def _batch() -> ExtractionBatch:
    document = _document()
    run = ExtractionRun(
        run_id=_RUN_ID,
        document_id=_DOCUMENT_ID,
        extractor_name="fixture",
        extractor_version="1",
        extracted_at=_EXTRACTED_AT,
    )
    provenance = ExtractionProvenance(run_id=_RUN_ID, confidence=0.75)
    evidence = Evidence(
        evidence_id=_EVIDENCE_ID,
        document_id=_DOCUMENT_ID,
        section_id=_SECTION_ID,
        passage_id=_PASSAGE_ID,
        passage_char_start=0,
        passage_char_end=len(_TEXT),
        text=_TEXT,
        provenance=provenance,
    )
    extraction = Claim(
        extraction_id=_EXTRACTION_ID,
        document_id=_DOCUMENT_ID,
        evidence_ids=(_EVIDENCE_ID,),
        provenance=provenance,
        text="fixture claim",
    )
    return ExtractionBatch(
        document=document,
        run=run,
        evidence=(evidence,),
        extractions=(extraction,),
    )


def _evidence_row(value: Evidence) -> tuple[Any, ...]:
    params = _evidence_params(value)
    return (
        params[0],
        params[2],
        params[1],
        params[11],
        params[3],
        params[4],
        params[5],
        params[6],
        params[7],
        params[12],
        params[13],
        params[14],
        params[15],
        params[16],
        params[17],
        params[18],
        params[8],
        params[9],
        params[10],
    )


def _extraction_row(value: Claim) -> tuple[Any, ...]:
    return (
        value.extraction_id,
        value.document_id,
        value.provenance.run_id,
        value.kind.value,
        value.attribution.value,
        value.provenance.confidence,
        value.provenance.human_review_state.value,
        value.provenance.reasoning_summary,
        json.dumps(_extraction_payload(value)),
    )


def _repository(connection: _Connection) -> PostgresExtractionRepository:
    return PostgresExtractionRepository(_SETTINGS, connection_factory=lambda _: connection)


def test_fresh_batch_persists_run_evidence_extraction_and_link() -> None:
    batch = _batch()
    connection = _Connection(
        [
            _Cursor(row=(1,)),
            _Cursor(rowcount=1),
            _Cursor(),
            _Cursor(),
            _Cursor(),
        ]
    )

    _repository(connection).save_batch(batch)

    sql_calls = [sql for sql, _ in connection.calls]
    assert "SELECT 1 FROM tarkka.document" in sql_calls[0]
    assert "INSERT INTO tarkka.extraction_run" in sql_calls[1]
    assert "INSERT INTO tarkka.evidence" in sql_calls[2]
    assert "INSERT INTO tarkka.research_extraction (" in sql_calls[3]
    assert "INSERT INTO tarkka.research_extraction_evidence" in sql_calls[4]
    assert connection.calls[-1][1] == (
        _EXTRACTION_ID,
        _EVIDENCE_ID,
        _RUN_ID,
        _DOCUMENT_ID,
        0,
    )
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed


def test_list_evidence_without_run_filter_uses_document_scope_only() -> None:
    evidence = cast(Evidence, _batch().evidence[0])
    connection = _Connection([_Cursor(rows=[_evidence_row(evidence)])])

    assert _repository(connection).list_evidence(_DOCUMENT_ID, offset=2, limit=3) == (evidence,)

    sql, params = connection.calls[0]
    assert "AND run_id = %s" not in sql
    assert params == (_DOCUMENT_ID, 2, 3)
    assert connection.closed


def test_list_extractions_without_optional_filters_preserves_evidence_links() -> None:
    extraction = cast(Claim, _batch().extractions[0])
    connection = _Connection(
        [
            _Cursor(rows=[_extraction_row(extraction)]),
            _Cursor(rows=[(_EXTRACTION_ID, _EVIDENCE_ID)]),
        ]
    )

    assert _repository(connection).list_extractions(_DOCUMENT_ID, offset=2, limit=3) == (
        extraction,
    )

    sql, params = connection.calls[0]
    assert "AND run_id = %s" not in sql
    assert "AND kind = %s" not in sql
    assert params == (_DOCUMENT_ID, 2, 3)
    assert connection.closed


def test_save_batch_requires_existing_document_and_rolls_back() -> None:
    connection = _Connection([_Cursor(row=None)])

    with pytest.raises(ValueError, match="normalized document not found"):
        _repository(connection).save_batch(_batch())

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed


def test_retry_without_existing_run_fails_closed() -> None:
    connection = _Connection(
        [
            _Cursor(row=(1,)),
            _Cursor(rowcount=0),
            _Cursor(row=None),
        ]
    )

    with pytest.raises(PostgresExtractionConflictError, match="conflicting extraction batch"):
        _repository(connection).save_batch(_batch())

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed


def test_retry_run_for_other_document_fails_closed() -> None:
    batch = _batch()
    wrong_run = replace(batch.run, document_id=_OTHER_DOCUMENT_ID)
    connection = _Connection(
        [
            _Cursor(row=(1,)),
            _Cursor(rowcount=0),
            _Cursor(row=cast(tuple[Any, ...], _run_params(wrong_run))),
        ]
    )

    with pytest.raises(PostgresExtractionConflictError, match="conflicting extraction batch"):
        _repository(connection).save_batch(batch)

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed


def test_exact_retry_loads_existing_batch_and_commits_without_rewriting() -> None:
    batch = _batch()
    evidence = cast(Evidence, batch.evidence[0])
    extraction = cast(Claim, batch.extractions[0])
    connection = _Connection(
        [
            _Cursor(row=(1,)),
            _Cursor(rowcount=0),
            _Cursor(row=cast(tuple[Any, ...], _run_params(batch.run))),
            _Cursor(rows=[_evidence_row(evidence)]),
            _Cursor(rows=[_extraction_row(extraction)]),
            _Cursor(rows=[(_EXTRACTION_ID, _EVIDENCE_ID)]),
        ]
    )

    _repository(connection).save_batch(batch)

    assert len(connection.calls) == 6
    assert "SELECT run_id" in connection.calls[2][0]
    assert "ORDER BY evidence_id" in connection.calls[3][0]
    assert "ORDER BY extraction_id" in connection.calls[4][0]
    assert "research_extraction_evidence" in connection.calls[5][0]
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed


@pytest.mark.parametrize("changed_component", ["run", "evidence", "extraction"])
def test_retry_comparison_rejects_each_changed_batch_component(changed_component: str) -> None:
    original = _batch()
    submitted = original
    if changed_component == "run":
        submitted = replace(original, run=replace(original.run, extractor_version="2"))
    elif changed_component == "evidence":
        evidence = cast(Evidence, original.evidence[0])
        submitted = replace(
            original,
            evidence=(
                replace(
                    evidence,
                    provenance=replace(evidence.provenance, confidence=0.5),
                ),
            ),
        )
    else:
        extraction = cast(Claim, original.extractions[0])
        submitted = replace(original, extractions=(replace(extraction, text="changed claim"),))

    assert not _batch_has_same_content(original, submitted)


def test_unsupported_evidence_serializer_type_fails_explicitly() -> None:
    with pytest.raises(TypeError, match="unsupported evidence type"):
        _evidence_params(cast(EvidenceRecord, object()))


def test_unsupported_extraction_serializer_type_fails_explicitly() -> None:
    with pytest.raises(TypeError, match="unsupported extraction type"):
        _extraction_payload(cast(ResearchExtraction, object()))


def test_unknown_database_evidence_kind_fails_closed() -> None:
    evidence = cast(Evidence, _batch().evidence[0])
    row = list(_evidence_row(evidence))
    row[3] = "video"

    with pytest.raises(RuntimeError, match="unsupported PostgreSQL evidence source_kind"):
        _evidence_from_row(tuple(row))


def test_non_driver_error_is_reraised_after_rollback_and_close() -> None:
    original = RuntimeError("query failed")
    connection = _FailingConnection(original)

    with pytest.raises(RuntimeError, match="query failed") as raised:
        _repository(connection).list_evidence(_DOCUMENT_ID)

    assert raised.value is original
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed


def test_driver_error_uses_shared_classifier_and_preserves_original_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DriverError(Exception):
        pass

    driver = ModuleType("psycopg")
    driver.Error = DriverError
    monkeypatch.setitem(sys.modules, "psycopg", driver)

    original = DriverError("query failed")
    connection = _FailingConnection(original)

    with pytest.raises(PostgresOperationError, match="PostgreSQL operation failed") as raised:
        _repository(connection).list_evidence(_DOCUMENT_ID)

    assert raised.value.__cause__ is original
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed
