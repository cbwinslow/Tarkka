"""Connection-bound PostgreSQL readers for coherent Claim-lineage snapshots.

These adapters intentionally reuse the PostgreSQL repositories' package-private query
and row-decoding helpers.  They do not own transactions or connections; callers supply
one already-open connection so multiple repository reads share one snapshot boundary.
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

    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None:
        row = self._connection.execute(
            _SELECT_EXTRACTION + " WHERE extraction_id = %s",
            (extraction_id,),
        ).fetchone()
        if row is None:
            return None
        evidence_ids = _evidence_ids_by_extraction(self._connection, (extraction_id,))
        return _extraction_from_row(row, evidence_ids[extraction_id])

    def get_run(self, run_id: UUID) -> ExtractionRun | None:
        row = self._connection.execute(
            _SELECT_RUN + " WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        return _run_from_row(row) if row is not None else None

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None:
        row = self._connection.execute(
            _SELECT_EVIDENCE + " WHERE evidence_id = %s",
            (evidence_id,),
        ).fetchone()
        return _evidence_from_row(row) if row is not None else None

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

    def get_document(self, document_id: UUID) -> Document | None:
        return PostgresResearchRepository._get_document(self._connection, document_id)

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        return PostgresResearchRepository._get_artifact(self._connection, artifact_id)


class PostgresClaimLineageCitationReader:
    """Read Claim-document-scoped citation contexts through a caller-owned connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def get_context(self, document_id: UUID, context_id: UUID) -> CitationContext | None:
        row = self._connection.execute(
            _SELECT_CONTEXT + " WHERE document_id = %s AND context_id = %s",
            (document_id, context_id),
        ).fetchone()
        return _context_from_row(row) if row is not None else None
