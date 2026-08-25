from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

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
    ResearchExtraction,
    ResearchObjectKind,
    Result,
    TableEvidence,
    Variable,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.extraction_repository import (
    PostgresExtractionRepository,
    _batch_has_same_content,
    _evidence_from_row,
    _evidence_ids_by_extraction,
    _evidence_params,
    _extraction_from_row,
    _extraction_payload,
    _json_object,
    _run_from_row,
    _run_params,
    _validate_page,
)

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000d001")
_RUN_ID = UUID("00000000-0000-0000-0000-00000000d002")
_SECTION_ID = UUID("00000000-0000-0000-0000-00000000d003")
_PASSAGE_ID = UUID("00000000-0000-0000-0000-00000000d004")
_FIGURE_ID = UUID("00000000-0000-0000-0000-00000000d005")
_TABLE_ID = UUID("00000000-0000-0000-0000-00000000d006")
_EQUATION_ID = UUID("00000000-0000-0000-0000-00000000d007")
_EVIDENCE_IDS = tuple(
    UUID(f"00000000-0000-0000-0000-00000000d0{ordinal:02d}") for ordinal in range(8, 12)
)


def _provenance() -> ExtractionProvenance:
    return ExtractionProvenance(run_id=_RUN_ID, confidence=0.75, reasoning_summary="fixture")


def _evidence_records() -> tuple[Evidence | FigureEvidence | TableEvidence | EquationEvidence, ...]:
    provenance = _provenance()
    return (
        Evidence(
            _EVIDENCE_IDS[0], _DOCUMENT_ID, _SECTION_ID, _PASSAGE_ID, 1, 5, "text", provenance
        ),
        FigureEvidence(_EVIDENCE_IDS[1], _DOCUMENT_ID, _FIGURE_ID, provenance),
        TableEvidence(_EVIDENCE_IDS[2], _DOCUMENT_ID, _TABLE_ID, 0, 1, 1, 2, provenance),
        EquationEvidence(_EVIDENCE_IDS[3], _DOCUMENT_ID, _EQUATION_ID, provenance),
    )


def _extractions() -> tuple[ResearchExtraction, ...]:
    base: dict[str, Any] = {
        "document_id": _DOCUMENT_ID,
        "evidence_ids": (_EVIDENCE_IDS[0],),
        "provenance": _provenance(),
    }
    ids = iter(UUID(f"00000000-0000-0000-0000-00000000d1{ordinal:02d}") for ordinal in range(9))
    return (
        Claim(extraction_id=next(ids), **base, text="claim"),
        Hypothesis(extraction_id=next(ids), **base, text="hypothesis"),
        Method(extraction_id=next(ids), **base, name="method", description="description"),
        Dataset(extraction_id=next(ids), **base, name="dataset", description="description"),
        Variable(extraction_id=next(ids), **base, name="variable", role="outcome"),
        Model(extraction_id=next(ids), **base, name="model", family="linear"),
        Metric(extraction_id=next(ids), **base, name="metric", value_text="0.8", unit="score"),
        Result(extraction_id=next(ids), **base, text="result", direction="improved"),
        Limitation(extraction_id=next(ids), **base, text="limitation"),
    )


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]], rowcount: int = 1) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[object, ...] | None]] = []
        self.closed = False

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> _Cursor:
        self.queries.append((query, params))
        if "research_extraction_evidence" in query:
            assert params is not None
            return _Cursor([(params[0], _EVIDENCE_IDS[0])])
        return _Cursor(self.rows)

    def close(self) -> None:
        self.closed = True

    @contextmanager
    def __enter__(self) -> Iterator[_Connection]:
        yield self

    def __exit__(self, *args: object) -> None:
        return None


def _evidence_row(
    value: Evidence | FigureEvidence | TableEvidence | EquationEvidence,
) -> tuple[object, ...]:
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


@pytest.mark.parametrize("value", _evidence_records())
def test_evidence_serialization_round_trips_each_locator(
    value: Evidence | FigureEvidence | TableEvidence | EquationEvidence,
) -> None:
    assert len(_evidence_params(value)) == 19
    assert _evidence_from_row(_evidence_row(value)) == value


@pytest.mark.parametrize("value", _extractions())
def test_extraction_serialization_round_trips_each_supported_kind(
    value: ResearchExtraction,
) -> None:
    payload = _extraction_payload(value)
    row = (
        value.extraction_id,
        value.document_id,
        _RUN_ID,
        value.kind.value,
        value.attribution.value,
        value.provenance.confidence,
        value.provenance.human_review_state.value,
        value.provenance.reasoning_summary,
        json.dumps(payload),
    )

    assert _extraction_from_row(row, (_EVIDENCE_IDS[0],)) == value


def test_run_serialization_preserves_optional_model_provenance() -> None:
    run = ExtractionRun(
        _RUN_ID,
        _DOCUMENT_ID,
        "extractor",
        "1",
        model=ModelProvenance("provider", "model", "version"),
        extracted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert _run_from_row(_run_params(run)) == run


def test_list_methods_apply_scoping_filtering_and_pagination() -> None:
    evidence = _evidence_records()[0]
    extraction = _extractions()[0]
    evidence_row = _evidence_row(evidence)
    extraction_row = (
        extraction.extraction_id,
        extraction.document_id,
        _RUN_ID,
        extraction.kind.value,
        extraction.attribution.value,
        extraction.provenance.confidence,
        extraction.provenance.human_review_state.value,
        extraction.provenance.reasoning_summary,
        json.dumps(_extraction_payload(extraction)),
    )
    evidence_connection = _Connection([evidence_row])
    evidence_repository = PostgresExtractionRepository(
        PostgresSettings("unused"), connection_factory=lambda _: evidence_connection
    )
    assert evidence_repository.list_evidence(_DOCUMENT_ID, run_id=_RUN_ID, offset=2, limit=3) == (
        evidence,
    )
    assert evidence_connection.queries[0][1] == (_DOCUMENT_ID, _RUN_ID, 2, 3)

    extraction_connection = _Connection([extraction_row])
    extraction_repository = PostgresExtractionRepository(
        PostgresSettings("unused"), connection_factory=lambda _: extraction_connection
    )
    assert extraction_repository.list_extractions(
        _DOCUMENT_ID, run_id=_RUN_ID, kind=ResearchObjectKind.CLAIM, offset=2, limit=3
    ) == (extraction,)
    assert extraction_connection.queries[0][1] == (_DOCUMENT_ID, _RUN_ID, "claim", 2, 3)
    assert len(extraction_connection.queries) == 2


@pytest.mark.parametrize("offset, limit", [(-1, 1), (0, 0)])
def test_invalid_pagination_is_rejected(offset: int, limit: int) -> None:
    with pytest.raises(ValueError, match="offset"):
        _validate_page(offset, limit)


def test_invalid_extraction_payload_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="must decode to an object"):
        _json_object("[]")


def test_empty_extraction_page_skips_link_query() -> None:
    connection = _Connection([])

    assert _evidence_ids_by_extraction(connection, ()) == {}
    assert connection.queries == []


def test_retry_comparison_ignores_batch_member_order() -> None:
    original = cast(
        ExtractionBatch,
        SimpleNamespace(run="run", evidence=("first", "second"), extractions=("claim", "result")),
    )
    reordered = cast(
        ExtractionBatch,
        SimpleNamespace(run="run", evidence=("second", "first"), extractions=("result", "claim")),
    )

    assert _batch_has_same_content(original, reordered)
