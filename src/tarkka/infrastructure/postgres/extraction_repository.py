"""PostgreSQL persistence for evidence-backed structured research extraction."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from uuid import UUID

from tarkka.domain.extraction import (
    AttributionKind,
    Claim,
    Dataset,
    EquationEvidence,
    Evidence,
    EvidenceRecord,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    FigureEvidence,
    HumanReviewState,
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
from tarkka.domain.models import Document
from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)


class PostgresExtractionConflictError(RuntimeError):
    """Raised when an immutable extraction run key is reused with changed content."""


class PostgresExtractionRepository:
    """Atomic, immutable persistence for structured extraction batches.

    The normalized document is intentionally a prerequisite rather than an implicit
    side effect: callers persist it through the research repository first.  This
    keeps extraction persistence focused on run provenance and derived records.
    """

    def __init__(
        self, settings: PostgresSettings, *, connection_factory: ConnectionFactory = connect
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def save_batch(self, batch: ExtractionBatch) -> None:
        with self._connection() as connection:
            self._require_document(connection, batch.document_id)
            inserted = connection.execute(_INSERT_RUN, _run_params(batch.run)).rowcount
            if inserted == 0:
                existing = self._load_batch(connection, batch.document, batch.run.run_id)
                if existing is None or not _batch_has_same_content(existing, batch):
                    raise PostgresExtractionConflictError(
                        "conflicting extraction batch for document/run: "
                        f"{batch.document_id}:{batch.run.run_id}"
                    )
                return

            for evidence in batch.evidence:
                connection.execute(_INSERT_EVIDENCE, _evidence_params(evidence))
            for extraction in batch.extractions:
                connection.execute(_INSERT_EXTRACTION, _extraction_params(extraction))
                for ordinal, evidence_id in enumerate(extraction.evidence_ids):
                    connection.execute(
                        _INSERT_EVIDENCE_LINK,
                        (
                            extraction.extraction_id,
                            evidence_id,
                            extraction.provenance.run_id,
                            extraction.document_id,
                            ordinal,
                        ),
                    )

    def list_evidence(
        self, document_id: UUID, *, run_id: UUID | None = None, offset: int = 0, limit: int = 100
    ) -> tuple[EvidenceRecord, ...]:
        _validate_page(offset, limit)
        query = _SELECT_EVIDENCE + " WHERE document_id = %s"
        params: list[object] = [document_id]
        if run_id is not None:
            query += " AND run_id = %s"
            params.append(run_id)
        query += " ORDER BY run_id, evidence_id OFFSET %s LIMIT %s"
        params.extend((offset, limit))
        with self._connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return tuple(_evidence_from_row(row) for row in rows)

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None:
        """Return one stable evidence record for verification and expansion."""
        with self._connection() as connection:
            return get_evidence_with_connection(connection, evidence_id)

    def get_run(self, run_id: UUID) -> ExtractionRun | None:
        """Return immutable extractor/model provenance for one extraction run."""
        with self._connection() as connection:
            return get_run_with_connection(connection, run_id)

    def list_extractions(
        self,
        document_id: UUID,
        *,
        run_id: UUID | None = None,
        kind: ResearchObjectKind | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[ResearchExtraction, ...]:
        _validate_page(offset, limit)
        query = _SELECT_EXTRACTION + " WHERE document_id = %s"
        params: list[object] = [document_id]
        if run_id is not None:
            query += " AND run_id = %s"
            params.append(run_id)
        if kind is not None:
            query += " AND kind = %s"
            params.append(kind.value)
        query += " ORDER BY run_id, extraction_id OFFSET %s LIMIT %s"
        params.extend((offset, limit))
        with self._connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            evidence_ids = _evidence_ids_by_extraction(
                connection, tuple(cast(UUID, row[0]) for row in rows)
            )
            return tuple(
                _extraction_from_row(row, evidence_ids[cast(UUID, row[0])]) for row in rows
            )

    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None:
        """Return one stable research object with its ordered evidence links."""
        with self._connection() as connection:
            return get_extraction_with_connection(connection, extraction_id)

    @staticmethod
    def _require_document(connection: Any, document_id: UUID) -> None:
        if (
            connection.execute(
                "SELECT 1 FROM tarkka.document WHERE document_id = %s", (document_id,)
            ).fetchone()
            is None
        ):
            raise ValueError(f"normalized document not found for extraction: {document_id}")

    @staticmethod
    def _load_batch(connection: Any, document: Document, run_id: UUID) -> ExtractionBatch | None:
        run_row = connection.execute(_SELECT_RUN + " WHERE run_id = %s", (run_id,)).fetchone()
        if run_row is None:
            return None
        run = _run_from_row(run_row)
        if run.document_id != document.document_id:
            return None
        evidence_rows = connection.execute(
            _SELECT_EVIDENCE + " WHERE document_id = %s AND run_id = %s ORDER BY evidence_id",
            (document.document_id, run_id),
        ).fetchall()
        extraction_rows = connection.execute(
            _SELECT_EXTRACTION + " WHERE document_id = %s AND run_id = %s ORDER BY extraction_id",
            (document.document_id, run_id),
        ).fetchall()
        evidence_ids = _evidence_ids_by_extraction(
            connection, tuple(cast(UUID, row[0]) for row in extraction_rows)
        )
        return ExtractionBatch(
            document=document,
            run=run,
            evidence=tuple(_evidence_from_row(row) for row in evidence_rows),
            extractions=tuple(
                _extraction_from_row(row, evidence_ids[cast(UUID, row[0])])
                for row in extraction_rows
            ),
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with managed_connection(
            self._settings,
            connection_factory=self._connect,
        ) as connection:
            yield connection


_INSERT_RUN = """INSERT INTO tarkka.extraction_run (
    run_id, document_id, extractor_name, extractor_version, contract_version,
    model_provider, model_name, model_version, extracted_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (run_id) DO NOTHING"""
_INSERT_EVIDENCE = """INSERT INTO tarkka.evidence (
    evidence_id, run_id, document_id, section_id, passage_id, passage_char_start,
    passage_char_end, text, confidence, human_review_state, reasoning_summary,
    source_kind, figure_id, table_id, table_row_start, table_row_end,
    table_column_start, table_column_end, equation_id
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
_INSERT_EXTRACTION = """INSERT INTO tarkka.research_extraction (
    extraction_id, run_id, document_id, kind, attribution, confidence,
    human_review_state, reasoning_summary, payload
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)"""
_INSERT_EVIDENCE_LINK = """INSERT INTO tarkka.research_extraction_evidence (
    extraction_id, evidence_id, run_id, document_id, ordinal
) VALUES (%s, %s, %s, %s, %s)"""
_SELECT_RUN = """SELECT run_id, document_id, extractor_name, extractor_version,
    contract_version, model_provider, model_name, model_version, extracted_at
FROM tarkka.extraction_run"""
_SELECT_EVIDENCE = """SELECT evidence_id, document_id, run_id, source_kind, section_id,
    passage_id, passage_char_start, passage_char_end, text, figure_id, table_id,
    table_row_start, table_row_end, table_column_start, table_column_end, equation_id,
    confidence, human_review_state, reasoning_summary
FROM tarkka.evidence"""
_SELECT_EXTRACTION = """SELECT extraction_id, document_id, run_id, kind, attribution,
    confidence, human_review_state, reasoning_summary, payload
FROM tarkka.research_extraction"""


def get_evidence_with_connection(connection: Any, evidence_id: UUID) -> EvidenceRecord | None:
    """Read one evidence record through a caller-owned PostgreSQL connection."""
    row = connection.execute(
        _SELECT_EVIDENCE + " WHERE evidence_id = %s",
        (evidence_id,),
    ).fetchone()
    return _evidence_from_row(row) if row is not None else None


def get_run_with_connection(connection: Any, run_id: UUID) -> ExtractionRun | None:
    """Read one extraction run through a caller-owned PostgreSQL connection."""
    row = connection.execute(_SELECT_RUN + " WHERE run_id = %s", (run_id,)).fetchone()
    return _run_from_row(row) if row is not None else None


def get_extraction_with_connection(
    connection: Any,
    extraction_id: UUID,
) -> ResearchExtraction | None:
    """Read one extraction and its ordered evidence links on a caller-owned connection."""
    row = connection.execute(
        _SELECT_EXTRACTION + " WHERE extraction_id = %s",
        (extraction_id,),
    ).fetchone()
    if row is None:
        return None
    evidence_ids = _evidence_ids_by_extraction(connection, (extraction_id,))
    return _extraction_from_row(row, evidence_ids[extraction_id])


def list_claims_with_connection(
    connection: Any,
    document_id: UUID,
    *,
    limit: int,
) -> tuple[Claim, ...]:
    """Read a bounded Claim set through a caller-owned PostgreSQL connection."""
    if limit < 0:
        raise ValueError("Claim snapshot limit must be non-negative")
    rows = connection.execute(
        _SELECT_EXTRACTION
        + " WHERE document_id = %s AND kind = %s"
        + " ORDER BY run_id, extraction_id LIMIT %s",
        (document_id, ResearchObjectKind.CLAIM.value, limit),
    ).fetchall()
    extraction_ids = tuple(cast(UUID, row[0]) for row in rows)
    evidence_ids = _evidence_ids_by_extraction(connection, extraction_ids)
    claims: list[Claim] = []
    for row in rows:
        extraction_id = cast(UUID, row[0])
        value = _extraction_from_row(row, evidence_ids[extraction_id])
        if not isinstance(value, Claim):
            raise RuntimeError("Claim-filtered PostgreSQL read returned a non-Claim record")
        claims.append(value)
    return tuple(claims)


def _batch_has_same_content(existing: ExtractionBatch, submitted: ExtractionBatch) -> bool:
    """Compare retry content without treating incidental tuple order as a conflict.

    No batch-level ordinal is part of the port contract.  Evidence links retain the
    only meaningful order (their per-extraction ordinal), so batch member tuples
    can be compared as sets while each extraction remains value-equal.
    """
    return (
        existing.run == submitted.run
        and set(existing.evidence) == set(submitted.evidence)
        and set(existing.extractions) == set(submitted.extractions)
    )


def _evidence_ids_by_extraction(
    connection: Any, extraction_ids: tuple[UUID, ...]
) -> dict[UUID, tuple[UUID, ...]]:
    if not extraction_ids:
        return {}
    placeholders = ", ".join("%s" for _ in extraction_ids)
    rows = connection.execute(
        f"""SELECT extraction_id, evidence_id FROM tarkka.research_extraction_evidence
        WHERE extraction_id IN ({placeholders}) ORDER BY extraction_id, ordinal""",
        extraction_ids,
    ).fetchall()
    result: dict[UUID, list[UUID]] = {item: [] for item in extraction_ids}
    for extraction_id, evidence_id in rows:
        result[cast(UUID, extraction_id)].append(cast(UUID, evidence_id))
    return {key: tuple(value) for key, value in result.items()}


def _run_params(value: ExtractionRun) -> tuple[object, ...]:
    model = value.model
    return (
        value.run_id,
        value.document_id,
        value.extractor_name,
        value.extractor_version,
        value.contract_version,
        model.provider if model else None,
        model.name if model else None,
        model.version if model else None,
        value.extracted_at,
    )


def _evidence_params(value: EvidenceRecord) -> tuple[object, ...]:
    if not isinstance(value, (Evidence, FigureEvidence, TableEvidence, EquationEvidence)):
        raise TypeError(f"unsupported evidence type: {type(value)!r}")

    provenance = value.provenance
    common = (value.evidence_id, provenance.run_id, value.document_id)
    if isinstance(value, Evidence):
        return common + (
            value.section_id,
            value.passage_id,
            value.passage_char_start,
            value.passage_char_end,
            value.text,
            provenance.confidence,
            provenance.human_review_state.value,
            provenance.reasoning_summary,
            "passage",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    if isinstance(value, FigureEvidence):
        return common + (
            None,
            None,
            None,
            None,
            None,
            provenance.confidence,
            provenance.human_review_state.value,
            provenance.reasoning_summary,
            "figure",
            value.figure_id,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    if isinstance(value, TableEvidence):
        return common + (
            None,
            None,
            None,
            None,
            None,
            provenance.confidence,
            provenance.human_review_state.value,
            provenance.reasoning_summary,
            "table",
            None,
            value.table_id,
            value.row_start,
            value.row_end,
            value.column_start,
            value.column_end,
            None,
        )
    return common + (
        None,
        None,
        None,
        None,
        None,
        provenance.confidence,
        provenance.human_review_state.value,
        provenance.reasoning_summary,
        "equation",
        None,
        None,
        None,
        None,
        None,
        None,
        value.equation_id,
    )


def _extraction_params(value: ResearchExtraction) -> tuple[object, ...]:
    provenance = value.provenance
    return (
        value.extraction_id,
        provenance.run_id,
        value.document_id,
        value.kind.value,
        value.attribution.value,
        provenance.confidence,
        provenance.human_review_state.value,
        provenance.reasoning_summary,
        json.dumps(_extraction_payload(value), sort_keys=True),
    )


def _extraction_payload(value: ResearchExtraction) -> dict[str, object]:
    if isinstance(value, Claim):
        return {"text": value.text, "claim_type": value.claim_type}
    if isinstance(value, Hypothesis):
        return {"text": value.text}
    if isinstance(value, (Method, Dataset)):
        return {"name": value.name, "description": value.description}
    if isinstance(value, Variable):
        return {"name": value.name, "role": value.role}
    if isinstance(value, Model):
        return {"name": value.name, "family": value.family}
    if isinstance(value, Metric):
        return {"name": value.name, "value_text": value.value_text, "unit": value.unit}
    if isinstance(value, Result):
        return {"text": value.text, "direction": value.direction}
    if isinstance(value, Limitation):
        return {"text": value.text}
    raise TypeError(f"unsupported extraction type: {type(value)!r}")


def _evidence_from_row(row: tuple[Any, ...]) -> EvidenceRecord:
    evidence_id, document_id, run_id, source_kind = cast(tuple[UUID, UUID, UUID, str], row[:4])
    provenance = ExtractionProvenance(
        run_id=run_id,
        confidence=float(row[16]),
        human_review_state=HumanReviewState(row[17]),
        reasoning_summary=cast(str | None, row[18]),
    )
    if source_kind == "passage":
        return Evidence(
            evidence_id,
            document_id,
            cast(UUID, row[4]),
            cast(UUID, row[5]),
            int(row[6]),
            int(row[7]),
            cast(str, row[8]),
            provenance,
        )
    if source_kind == "figure":
        return FigureEvidence(evidence_id, document_id, cast(UUID, row[9]), provenance)
    if source_kind == "table":
        return TableEvidence(
            evidence_id,
            document_id,
            cast(UUID, row[10]),
            int(row[11]),
            int(row[12]),
            int(row[13]),
            int(row[14]),
            provenance,
        )
    if source_kind == "equation":
        return EquationEvidence(evidence_id, document_id, cast(UUID, row[15]), provenance)
    raise RuntimeError(f"unsupported PostgreSQL evidence source_kind: {source_kind!r}")


def _extraction_from_row(
    row: tuple[Any, ...], evidence_ids: tuple[UUID, ...]
) -> ResearchExtraction:
    extraction_id, document_id, run_id, kind, attribution = row[:5]
    payload = _json_object(row[8])
    base: dict[str, Any] = {
        "extraction_id": extraction_id,
        "document_id": document_id,
        "evidence_ids": evidence_ids,
        "provenance": ExtractionProvenance(
            run_id=run_id,
            confidence=float(row[5]),
            human_review_state=HumanReviewState(row[6]),
            reasoning_summary=cast(str | None, row[7]),
        ),
        "attribution": AttributionKind(attribution),
    }
    if kind == ResearchObjectKind.CLAIM.value:
        return Claim(
            **base, text=cast(str, payload["text"]), claim_type=cast(str, payload["claim_type"])
        )
    if kind == ResearchObjectKind.HYPOTHESIS.value:
        return Hypothesis(**base, text=cast(str, payload["text"]))
    if kind == ResearchObjectKind.METHOD.value:
        return Method(
            **base,
            name=cast(str, payload["name"]),
            description=cast(str | None, payload.get("description")),
        )
    if kind == ResearchObjectKind.DATASET.value:
        return Dataset(
            **base,
            name=cast(str, payload["name"]),
            description=cast(str | None, payload.get("description")),
        )
    if kind == ResearchObjectKind.VARIABLE.value:
        return Variable(
            **base, name=cast(str, payload["name"]), role=cast(str | None, payload.get("role"))
        )
    if kind == ResearchObjectKind.MODEL.value:
        return Model(
            **base, name=cast(str, payload["name"]), family=cast(str | None, payload.get("family"))
        )
    if kind == ResearchObjectKind.METRIC.value:
        return Metric(
            **base,
            name=cast(str, payload["name"]),
            value_text=cast(str | None, payload.get("value_text")),
            unit=cast(str | None, payload.get("unit")),
        )
    if kind == ResearchObjectKind.RESULT.value:
        return Result(
            **base,
            text=cast(str, payload["text"]),
            direction=cast(str | None, payload.get("direction")),
        )
    if kind == ResearchObjectKind.LIMITATION.value:
        return Limitation(**base, text=cast(str, payload["text"]))
    raise RuntimeError(f"unsupported PostgreSQL extraction kind: {kind!r}")


def _run_from_row(row: tuple[Any, ...]) -> ExtractionRun:
    model = None
    if row[5] is not None:
        model = ModelProvenance(cast(str, row[5]), cast(str, row[6]), cast(str | None, row[7]))
    return ExtractionRun(
        cast(UUID, row[0]),
        cast(UUID, row[1]),
        cast(str, row[2]),
        cast(str, row[3]),
        cast(str, row[4]),
        model,
        row[8],
    )


def _json_object(value: Any) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("PostgreSQL extraction payload must decode to an object")
    return decoded


def _validate_page(offset: int, limit: int) -> None:
    if offset < 0 or limit <= 0:
        raise ValueError("offset must be non-negative and limit must be positive")
