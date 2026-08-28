from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

import tarkka.infrastructure.postgres.citation_context_repository as citation_module
import tarkka.infrastructure.postgres.verification_repository as verification_module
import tarkka.infrastructure.postgres.work_repository as work_module
from tarkka.domain.citations import BibliographicReference, CitationContext
from tarkka.domain.models import Work
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.postgres.citation_context_repository import (
    PostgresCitationContextRepository,
)
from tarkka.infrastructure.postgres.connection import PostgresOperationError, PostgresSettings
from tarkka.infrastructure.postgres.verification_repository import PostgresVerificationRepository
from tarkka.infrastructure.postgres.work_repository import PostgresWorkRepository

_SETTINGS = PostgresSettings("postgresql://unused")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000d901")
_REFERENCE_ID = UUID("00000000-0000-0000-0000-00000000d902")
_MENTION_ID = UUID("00000000-0000-0000-0000-00000000d903")
_CONTEXT_ID = UUID("00000000-0000-0000-0000-00000000d904")
_PASSAGE_ID = UUID("00000000-0000-0000-0000-00000000d905")
_WORK_ID = UUID("00000000-0000-0000-0000-00000000d906")
_RELATION_ID = UUID("00000000-0000-0000-0000-00000000d907")
_CLAIM_ID = UUID("00000000-0000-0000-0000-00000000d908")
_EVIDENCE_ID = UUID("00000000-0000-0000-0000-00000000d909")
_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class _Cursor:
    row: tuple[Any, ...] | None = None
    rows: tuple[tuple[Any, ...], ...] = ()
    rowcount: int = 1

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> tuple[tuple[Any, ...], ...]:
        return self.rows


@dataclass
class _Connection:
    cursors: list[_Cursor]
    calls: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)
    closed: bool = False
    entered: int = 0

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        **_: Any,
    ) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0) if self.cursors else _Cursor()

    def __enter__(self) -> _Connection:
        self.entered += 1
        return self

    def __exit__(self, *_: Any) -> None:
        self.entered -= 1

    def close(self) -> None:
        self.closed = True


class _FailingConnection(_Connection):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        **_: Any,
    ) -> _Cursor:
        self.calls.append((sql, params))
        raise self.error


def _reference() -> BibliographicReference:
    return BibliographicReference(
        _REFERENCE_ID,
        _DOCUMENT_ID,
        0,
        "A. Author. Evidence first.",
        {"doi": "10.1000/example"},
        "Evidence first",
        ("A. Author",),
        2026,
        "ref-1",
        None,
    )


def _reference_row(value: BibliographicReference) -> tuple[Any, ...]:
    return (
        value.reference_id,
        value.document_id,
        value.ordinal,
        value.raw_text,
        dict(value.identifiers),
        value.title,
        list(value.authors),
        value.publication_year,
        value.source_anchor,
        value.source_observation_id,
    )


def _context() -> CitationContext:
    return CitationContext(
        _CONTEXT_ID,
        _MENTION_ID,
        _DOCUMENT_ID,
        "cite [1]",
        0,
        8,
        passage_id=_PASSAGE_ID,
    )


def _context_row(value: CitationContext) -> tuple[Any, ...]:
    return (
        value.context_id,
        value.mention_id,
        value.document_id,
        value.text,
        value.char_start,
        value.char_end,
        value.section_id,
        value.passage_id,
    )


def _work() -> Work:
    return Work(
        work_id=_WORK_ID,
        title="Evidence-first research",
        publication_type="journal-article",
        language="en",
        external_ids={"doi": "10.1000/example"},
        publication_year=2026,
        abstract="Abstract",
        venue="Journal",
        created_at=_CREATED_AT,
    )


def _relation() -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=_RELATION_ID,
        claim_id=_CLAIM_ID,
        evidence_id=_EVIDENCE_ID,
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="fixture",
        verifier_version="1",
        confidence=0.8,
        created_at=_CREATED_AT,
    )


def _relation_row(value: EvidenceRelation) -> tuple[Any, ...]:
    return (
        value.relation_id,
        value.claim_id,
        value.kind.value,
        value.verifier_name,
        value.verifier_version,
        value.confidence,
        value.human_review_state.value,
        value.evidence_id,
        value.citation_context_id,
        value.reasoning_summary,
        value.created_at,
    )


def test_citation_repository_accepts_exact_idempotent_retry() -> None:
    reference = _reference()
    connection = _Connection(
        [_Cursor(rowcount=0), _Cursor(row=_reference_row(reference))]
    )
    repository = PostgresCitationContextRepository(
        _SETTINGS, connection_factory=lambda _: connection
    )

    repository.save_reference(reference)

    assert connection.closed
    assert len(connection.calls) == 2


def test_citation_repository_shortcuts_empty_pages_and_supports_unbounded_query() -> None:
    context = _context()
    connection = _Connection([_Cursor(rows=(_context_row(context),))])
    repository = PostgresCitationContextRepository(
        _SETTINGS, connection_factory=lambda _: connection
    )

    assert repository.list_contexts_for_passages(_DOCUMENT_ID, frozenset(), limit=5) == ()
    assert repository.page_contexts_for_passages(
        _DOCUMENT_ID, frozenset((_PASSAGE_ID,)), limit=0
    ) == (0, ())
    assert repository.list_contexts_for_passages(
        _DOCUMENT_ID, frozenset((_PASSAGE_ID,)), offset=2, limit=None
    ) == (context,)

    query, params = connection.calls[0]
    assert "LIMIT" not in query
    assert params == (_DOCUMENT_ID, _PASSAGE_ID, 2)


def test_citation_repository_translates_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("driver failure")
    translated = PostgresOperationError("translated")
    monkeypatch.setattr(citation_module, "translate_driver_error", lambda exc: translated)
    repository = PostgresCitationContextRepository(
        _SETTINGS,
        connection_factory=lambda _: (_ for _ in ()).throw(original),
    )

    with pytest.raises(PostgresOperationError, match="translated") as raised:
        repository.list_references(_DOCUMENT_ID)

    assert raised.value is translated
    assert raised.value.__cause__ is original


def test_work_transaction_preserves_application_failure_and_resets_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection([])
    repository = PostgresWorkRepository(_SETTINGS, connection_factory=lambda _: connection)
    monkeypatch.setattr(work_module, "translate_driver_error", lambda exc: None)

    with pytest.raises(RuntimeError, match="application failure"), repository.transaction():
        raise RuntimeError("application failure")

    assert connection.closed
    assert connection.entered == 0
    assert repository._transaction_connection.get() is None


def test_work_transaction_translates_query_failure_on_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DriverFailure(RuntimeError):
        pass

    original = _DriverFailure("query failed")
    translated = PostgresOperationError("translated")
    connection = _FailingConnection(original)
    repository = PostgresWorkRepository(_SETTINGS, connection_factory=lambda _: connection)

    def _translate(exc: Exception) -> PostgresOperationError | None:
        return translated if isinstance(exc, _DriverFailure) else None

    monkeypatch.setattr(work_module, "translate_driver_error", _translate)

    with pytest.raises(PostgresOperationError, match="translated") as raised:
        with repository.transaction():
            repository.save_work(_work())

    assert raised.value is translated
    assert raised.value.__cause__ is original
    assert connection.closed
    assert repository._transaction_connection.get() is None


def test_verification_repository_covers_success_missing_claim_and_get_paths() -> None:
    relation = _relation()

    success = _Connection([_Cursor(rowcount=1)])
    PostgresVerificationRepository(
        _SETTINGS, connection_factory=lambda _: success
    ).save_relation(relation)
    assert success.closed

    missing_claim = _Connection([_Cursor(rowcount=0), _Cursor(row=None)])
    with pytest.raises(ValueError, match="claim not found"):
        PostgresVerificationRepository(
            _SETTINGS, connection_factory=lambda _: missing_claim
        ).save_relation(relation)

    found = _Connection([_Cursor(row=_relation_row(relation))])
    missing = _Connection([_Cursor(row=None)])
    assert PostgresVerificationRepository(
        _SETTINGS, connection_factory=lambda _: found
    ).get_relation(_RELATION_ID) == relation
    assert PostgresVerificationRepository(
        _SETTINGS, connection_factory=lambda _: missing
    ).get_relation(_RELATION_ID) is None


def test_verification_repository_translates_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("driver failure")
    translated = PostgresOperationError("translated")
    monkeypatch.setattr(verification_module, "translate_driver_error", lambda exc: translated)
    repository = PostgresVerificationRepository(
        _SETTINGS,
        connection_factory=lambda _: (_ for _ in ()).throw(original),
    )

    with pytest.raises(PostgresOperationError, match="translated") as raised:
        repository.get_relation(_RELATION_ID)

    assert raised.value is translated
    assert raised.value.__cause__ is original
