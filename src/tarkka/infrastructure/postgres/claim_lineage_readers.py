"""Connection-bound PostgreSQL readers for coherent Claim-lineage snapshots.

These adapters intentionally reuse the PostgreSQL repositories' package-private query
and row-decoding helpers. They do not own transactions or connections; callers supply
one already-open connection so multiple repository reads share one snapshot boundary.
Caches are scoped to the reader/transaction because repeatable-read state cannot change
underneath the export.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import (
    Claim,
    EvidenceRecord,
    ExtractionRun,
    ResearchExtraction,
    ResearchObjectKind,
)
from tarkka.domain.models import Artifact, Document
from tarkka.domain.verification import EvidenceRelation
from tarkka.infrastructure.postgres.citation_context_repository import (
    _SELECT_CONTEXT,
    _context_from_row,
)
from tarkka.infrastructure.postgres.extraction_repository import (
    _SELECT_EVIDENCE,
    _SELECT_EXTRACTION,
    _SELECT_RUN,
    _evidence_from_row,
    _evidence_ids_by_extraction,
    _extraction_from_row,
    _run_from_row,
)
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.verification_repository import (
    _SELECT_RELATION_PAGE,
)
from tarkka.infrastructure.postgres.verification_repository import (
    _from_row as _relation_from_row,
)


class PostgresClaimLineageSourceReader:
    """Read extraction state through a caller-owned PostgreSQL connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._extractions: dict[UUID, ResearchExtraction | None] = {}
        self._runs: dict[UUID, ExtractionRun | None] = {}
        self._evidence: dict[UUID, EvidenceRecord | None] = {}

    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None:
        if extraction_id not in self._extractions:
            row = self._connection.execute(
                _SELECT_EXTRACTION + " WHERE extraction_id = %s",
                (extraction_id,),
            ).fetchone()
            if row is None:
                self._extractions[extraction_id] = None
            else:
                evidence_ids = _evidence_ids_by_extraction(self._connection, (extraction_id,))
                self._extractions[extraction_id] = _extraction_from_row(
                    row,
                    evidence_ids[extraction_id],
                )
        return self._extractions[extraction_id]

    def get_run(self, run_id: UUID) -> ExtractionRun | None:
        if run_id not in self._runs:
            row = self._connection.execute(
                _SELECT_RUN + " WHERE run_id = %s",
                (run_id,),
            ).fetchone()
            self._runs[run_id] = _run_from_row(row) if row is not None else None
        return self._runs[run_id]

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None:
        if evidence_id not in self._evidence:
            row = self._connection.execute(
                _SELECT_EVIDENCE + " WHERE evidence_id = %s",
                (evidence_id,),
            ).fetchone()
            self._evidence[evidence_id] = _evidence_from_row(row) if row is not None else None
        return self._evidence[evidence_id]

    def list_claims(self, document_id: UUID, *, limit: int) -> tuple[Claim, ...]:
        if limit < 0:
            raise ValueError("Claim snapshot limit must be non-negative")
        rows = self._connection.execute(
            _SELECT_EXTRACTION
            + " WHERE document_id = %s AND kind = %s"
            + " ORDER BY run_id, extraction_id LIMIT %s",
            (document_id, ResearchObjectKind.CLAIM.value, limit),
        ).fetchall()
        extraction_ids = tuple(cast(UUID, row[0]) for row in rows)
        evidence_ids = _evidence_ids_by_extraction(self._connection, extraction_ids)
        claims: list[Claim] = []
        for row in rows:
            extraction_id = cast(UUID, row[0])
            value = _extraction_from_row(row, evidence_ids[extraction_id])
            if not isinstance(value, Claim):
                raise RuntimeError("Claim-filtered PostgreSQL read returned a non-Claim record")
            self._extractions[extraction_id] = value
            claims.append(value)
        return tuple(claims)


class PostgresClaimLineageRelationReader:
    """Read verification relation pages through a caller-owned connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def page_relations(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        if offset < 0 or limit < 0:
            raise ValueError("verification offset and limit must be non-negative")
        rows = self._connection.execute(
            _SELECT_RELATION_PAGE,
            (claim_id, offset, limit, claim_id),
        ).fetchall()
        first = cast(tuple[Any, ...], rows[0])
        total = int(first[0])
        relations = tuple(
            _relation_from_row(cast(tuple[Any, ...], row)[1:])
            for row in rows
            if cast(tuple[Any, ...], row)[1] is not None
        )
        return total, relations


class PostgresClaimLineageDocumentReader:
    """Read normalized Document/Artifact state through a caller-owned connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._documents: dict[UUID, Document | None] = {}
        self._artifacts: dict[UUID, Artifact | None] = {}

    def get_document(self, document_id: UUID) -> Document | None:
        if document_id not in self._documents:
            self._documents[document_id] = PostgresResearchRepository._get_document(
                self._connection,
                document_id,
            )
        return self._documents[document_id]

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        if artifact_id not in self._artifacts:
            self._artifacts[artifact_id] = PostgresResearchRepository._get_artifact(
                self._connection,
                artifact_id,
            )
        return self._artifacts[artifact_id]


class PostgresClaimLineageCitationReader:
    """Read Claim-document-scoped citation contexts through a caller-owned connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._contexts: dict[tuple[UUID, UUID], CitationContext | None] = {}

    def get_context(self, document_id: UUID, context_id: UUID) -> CitationContext | None:
        key = (document_id, context_id)
        if key not in self._contexts:
            row = self._connection.execute(
                _SELECT_CONTEXT + " WHERE document_id = %s AND context_id = %s",
                key,
            ).fetchone()
            self._contexts[key] = _context_from_row(row) if row is not None else None
        return self._contexts[key]
