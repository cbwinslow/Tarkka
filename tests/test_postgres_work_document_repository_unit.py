from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

import tarkka.infrastructure.postgres.work_document_repository as repository_module
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.work_document_repository import (
    PostgresWorkDocumentRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_SETTINGS = PostgresSettings("postgresql://unused")
_LINK = WorkDocumentLink(
    link_id=UUID("00000000-0000-0000-0000-00000000fd01"),
    work_id=UUID("00000000-0000-0000-0000-00000000fd02"),
    artifact_id=UUID("00000000-0000-0000-0000-00000000fd03"),
    document_id=UUID("00000000-0000-0000-0000-00000000fd04"),
    linked_at=datetime(2026, 8, 29, tzinfo=UTC),
)


@dataclass
class _Cursor:
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    rowcount: int = 1

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


@dataclass
class _Connection:
    cursors: list[_Cursor]
    calls: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)
    closed: bool = False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0)

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FailingConnection(_Connection):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        del sql, params
        raise self.error


def _row(link: WorkDocumentLink = _LINK) -> tuple[Any, ...]:
    return (
        link.link_id,
        link.work_id,
        link.artifact_id,
        link.document_id,
        link.linked_at,
    )


def _repository(connection: _Connection) -> PostgresWorkDocumentRepository:
    return PostgresWorkDocumentRepository(_SETTINGS, connection_factory=lambda _: connection)


def test_postgres_work_document_repository_saves_idempotently_and_rejects_conflicts() -> None:
    success = _Connection([_Cursor(rowcount=1)])
    _repository(success).save_work_document_link(_LINK)

    assert "INSERT INTO tarkka.work_document_link" in success.calls[0][0]
    assert success.calls[0][1] == (
        _LINK.link_id,
        _LINK.work_id,
        _LINK.artifact_id,
        _LINK.document_id,
        _LINK.linked_at,
    )
    assert success.closed is True

    conflict = _Connection([_Cursor(rowcount=0)])
    with pytest.raises(ValueError, match="conflicting work document link"):
        _repository(conflict).save_work_document_link(_LINK)
    assert conflict.closed is True


def test_postgres_work_document_repository_lists_by_work_and_document() -> None:
    by_work = _Connection([_Cursor(rows=[_row()])])
    by_document = _Connection([_Cursor(rows=[_row()])])
    connections = [by_work, by_document]
    repository = PostgresWorkDocumentRepository(
        _SETTINGS,
        connection_factory=lambda _: connections.pop(0),
    )

    assert repository.list_work_document_links(_LINK.work_id) == (_LINK,)
    assert repository.list_document_work_links(_LINK.document_id) == (_LINK,)
    assert "WHERE work_id = %s" in by_work.calls[0][0]
    assert by_work.calls[0][1] == (_LINK.work_id,)
    assert "WHERE document_id = %s" in by_document.calls[0][0]
    assert by_document.calls[0][1] == (_LINK.document_id,)
    assert by_work.closed is True
    assert by_document.closed is True


def test_postgres_work_document_repository_translates_driver_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FailingConnection(RuntimeError("driver failure"))
    monkeypatch.setattr(
        repository_module,
        "translate_driver_error",
        lambda exc: ValueError("translated") if isinstance(exc, RuntimeError) else None,
    )

    with pytest.raises(ValueError, match="translated"):
        _repository(connection).list_document_work_links(_LINK.document_id)

    assert connection.closed is True


def test_postgres_work_document_repository_preserves_untranslated_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FailingConnection(RuntimeError("boom"))
    monkeypatch.setattr(repository_module, "translate_driver_error", lambda exc: None)

    with pytest.raises(RuntimeError, match="boom"):
        _repository(connection).list_work_document_links(_LINK.work_id)

    assert connection.closed is True
