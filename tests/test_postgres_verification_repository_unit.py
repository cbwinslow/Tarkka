from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from tarkka.domain.extraction import HumanReviewState
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.verification_repository import (
    PostgresVerificationRepository,
    _from_row,
    _identity,
)


class _Cursor:
    def __init__(
        self,
        *,
        row: tuple[Any, ...] | None = None,
        rows: tuple[tuple[Any, ...], ...] = (),
        rowcount: int = 1,
    ) -> None:
        self.row, self.rows, self.rowcount = row, rows, rowcount

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> tuple[tuple[Any, ...], ...]:
        return self.rows


class _Connection:
    def __init__(self, cursors: list[_Cursor]) -> None:
        self.cursors = cursors
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []
        self.closed = False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0)

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _repository(connection: _Connection) -> PostgresVerificationRepository:
    return PostgresVerificationRepository(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )


def _relation() -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=uuid4(),
        claim_id=uuid4(),
        evidence_id=uuid4(),
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="fixture",
        verifier_version="1",
        confidence=0.8,
    )


def _row(relation: EvidenceRelation) -> tuple[Any, ...]:
    return (
        relation.relation_id,
        relation.claim_id,
        relation.kind.value,
        relation.verifier_name,
        relation.verifier_version,
        relation.confidence,
        relation.human_review_state.value,
        relation.evidence_id,
        relation.citation_context_id,
        relation.reasoning_summary,
        relation.created_at,
    )


def test_postgres_verification_row_round_trips_domain_fields() -> None:
    relation = _from_row(
        (
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
            "supports",
            "human-review",
            "1",
            0.9,
            "verified",
            UUID("00000000-0000-0000-0000-000000000003"),
            None,
            "Exact span supports the claim.",
            datetime(2026, 1, 1, tzinfo=UTC),
        )
    )

    assert relation == EvidenceRelation(
        relation_id=UUID("00000000-0000-0000-0000-000000000001"),
        claim_id=UUID("00000000-0000-0000-0000-000000000002"),
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="human-review",
        verifier_version="1",
        confidence=0.9,
        human_review_state=HumanReviewState.VERIFIED,
        evidence_id=UUID("00000000-0000-0000-0000-000000000003"),
        reasoning_summary="Exact span supports the claim.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_verification_identity_excludes_created_timestamp_only() -> None:
    base = EvidenceRelation(
        relation_id=UUID("00000000-0000-0000-0000-000000000001"),
        claim_id=UUID("00000000-0000-0000-0000-000000000002"),
        kind=EvidenceRelationKind.NO_EVIDENCE,
        verifier_name="human-review",
        verifier_version="1",
        confidence=0.9,
    )
    changed = replace(base, confidence=0.1)

    assert _identity(base) != _identity(changed)


def test_save_relation_is_idempotent_and_rejects_conflicting_content() -> None:
    relation = _relation()
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_row(relation))])

    _repository(connection).save_relation(relation)

    assert connection.closed
    params = connection.calls[0][1]
    assert params is not None
    assert params[-1] == relation.claim_id

    conflicting = replace(relation, confidence=0.1)
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_row(relation))])
    with pytest.raises(ValueError, match="conflicting evidence relation"):
        _repository(connection).save_relation(conflicting)


def test_repository_reads_are_bounded_and_return_domain_records() -> None:
    relation = _relation()
    connection = _Connection([_Cursor(row=(2,)), _Cursor(rows=(_row(relation),))])
    repository = _repository(connection)

    assert repository.count_relations(relation.claim_id) == 2
    assert repository.list_relations(relation.claim_id, offset=1, limit=3) == (relation,)
    assert connection.calls[1][1] == (relation.claim_id, 1, 3)


def test_repository_rejects_invalid_page_before_connecting() -> None:
    connection = _Connection([])

    with pytest.raises(ValueError, match="non-negative"):
        _repository(connection).list_relations(uuid4(), offset=-1)

    assert connection.calls == []
