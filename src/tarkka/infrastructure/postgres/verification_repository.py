"""PostgreSQL persistence for immutable evidence-verification assessments."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from tarkka.domain.extraction import HumanReviewState
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)


class PostgresVerificationRepository:
    """Immutable PostgreSQL implementation of the evidence-relation persistence port."""

    def __init__(
        self, settings: PostgresSettings, *, connection_factory: ConnectionFactory = connect
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def save_relation(self, relation: EvidenceRelation) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tarkka.evidence_relation (
                    relation_id, claim_id, claim_document_id, evidence_id, citation_context_id,
                    kind, verifier_name, verifier_version, confidence, human_review_state,
                    reasoning_summary, created_at
                )
                SELECT %s, %s, extraction.document_id, %s, %s, %s, %s, %s, %s, %s, %s, %s
                FROM tarkka.research_extraction AS extraction
                WHERE extraction.extraction_id = %s
                ON CONFLICT (relation_id) DO NOTHING
                """,
                (
                    relation.relation_id,
                    relation.claim_id,
                    relation.evidence_id,
                    relation.citation_context_id,
                    relation.kind.value,
                    relation.verifier_name,
                    relation.verifier_version,
                    relation.confidence,
                    relation.human_review_state.value,
                    relation.reasoning_summary,
                    relation.created_at,
                    relation.claim_id,
                ),
            )
            if cursor.rowcount == 0:
                existing = self._get_relation(connection, relation.relation_id)
                if existing is None:
                    raise ValueError(f"claim not found: {relation.claim_id}")
                if _identity(existing) != _identity(relation):
                    raise ValueError(f"conflicting evidence relation: {relation.relation_id}")

    def get_relation(self, relation_id: UUID) -> EvidenceRelation | None:
        with self._connection() as connection:
            return self._get_relation(connection, relation_id)

    def count_relations(self, claim_id: UUID) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT count(*) FROM tarkka.evidence_relation WHERE claim_id = %s", (claim_id,)
            ).fetchone()
        return int(cast(tuple[Any, ...], row)[0])

    def list_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[EvidenceRelation, ...]:
        if offset < 0 or limit < 0:
            raise ValueError("verification offset and limit must be non-negative")
        with self._connection() as connection:
            rows = connection.execute(
                _SELECT_RELATIONS + " WHERE claim_id = %s ORDER BY relation_id OFFSET %s LIMIT %s",
                (claim_id, offset, limit),
            ).fetchall()
        return tuple(_from_row(row) for row in rows)

    def page_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        """Return total and page from one PostgreSQL statement snapshot."""
        with self._connection() as connection:
            return page_relations_with_connection(
                connection,
                claim_id,
                offset=offset,
                limit=limit,
            )

    @staticmethod
    def _get_relation(connection: Any, relation_id: UUID) -> EvidenceRelation | None:
        row = connection.execute(
            _SELECT_RELATIONS + " WHERE relation_id = %s", (relation_id,)
        ).fetchone()
        return _from_row(row) if row is not None else None

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with managed_connection(
            self._settings,
            connection_factory=self._connect,
        ) as connection:
            yield connection


def page_relations_with_connection(
    connection: Any,
    claim_id: UUID,
    *,
    offset: int = 0,
    limit: int = 100,
) -> tuple[int, tuple[EvidenceRelation, ...]]:
    """Read one relation page through a caller-owned PostgreSQL connection."""
    if offset < 0 or limit < 0:
        raise ValueError("verification offset and limit must be non-negative")
    rows = connection.execute(
        _SELECT_RELATION_PAGE,
        (claim_id, offset, limit, claim_id),
    ).fetchall()
    if not rows:
        raise RuntimeError("PostgreSQL relation page query returned no total row")
    first = cast(tuple[Any, ...], rows[0])
    total = int(first[0])
    relations = tuple(
        _from_row(cast(tuple[Any, ...], row)[1:])
        for row in rows
        if cast(tuple[Any, ...], row)[1] is not None
    )
    return total, relations


_SELECT_RELATIONS = """
SELECT relation_id, claim_id, kind, verifier_name, verifier_version, confidence,
       human_review_state, evidence_id, citation_context_id, reasoning_summary, created_at
FROM tarkka.evidence_relation
"""

_SELECT_RELATION_PAGE = """
WITH relation_page AS (
    SELECT relation_id, claim_id, kind, verifier_name, verifier_version, confidence,
           human_review_state, evidence_id, citation_context_id, reasoning_summary, created_at
    FROM tarkka.evidence_relation
    WHERE claim_id = %s
    ORDER BY relation_id
    OFFSET %s LIMIT %s
),
relation_total AS (
    SELECT count(*) AS total
    FROM tarkka.evidence_relation
    WHERE claim_id = %s
)
SELECT relation_total.total,
       relation_page.relation_id, relation_page.claim_id, relation_page.kind,
       relation_page.verifier_name, relation_page.verifier_version, relation_page.confidence,
       relation_page.human_review_state, relation_page.evidence_id,
       relation_page.citation_context_id, relation_page.reasoning_summary,
       relation_page.created_at
FROM relation_total
LEFT JOIN relation_page ON TRUE
ORDER BY relation_page.relation_id
"""


def _from_row(row: tuple[Any, ...]) -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=cast(UUID, row[0]), claim_id=cast(UUID, row[1]),
        kind=EvidenceRelationKind(cast(str, row[2])), verifier_name=cast(str, row[3]),
        verifier_version=cast(str, row[4]), confidence=float(row[5]),
        human_review_state=HumanReviewState(cast(str, row[6])),
        evidence_id=cast(UUID | None, row[7]),
        citation_context_id=cast(UUID | None, row[8]), reasoning_summary=cast(str | None, row[9]),
        created_at=cast(datetime, row[10]),
    )


def _identity(value: EvidenceRelation) -> tuple[object, ...]:
    return (
        value.claim_id, value.kind, value.verifier_name, value.verifier_version,
        value.confidence, value.human_review_state, value.evidence_id,
        value.citation_context_id, value.reasoning_summary,
    )
