from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from tarkka.domain.context_packages import SavedDocumentContextPackage
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.context_package_repository import (
    PostgresDocumentContextPackageRepository,
    _identity,
)


class _Cursor:
    def __init__(
        self,
        *,
        row: tuple[Any, ...] | None = None,
        rows: tuple[tuple[Any, ...], ...] = (),
    ) -> None:
        self.row = row
        self.rows = rows

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


def _repository(connection: _Connection) -> PostgresDocumentContextPackageRepository:
    return PostgresDocumentContextPackageRepository(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )


def _package() -> SavedDocumentContextPackage:
    return SavedDocumentContextPackage(
        context_package_id=UUID("00000000-0000-0000-0000-000000000101"),
        document_id=UUID("00000000-0000-0000-0000-000000000102"),
        section_ids=(
            UUID("00000000-0000-0000-0000-000000000103"),
            UUID("00000000-0000-0000-0000-000000000104"),
        ),
        estimated_tokens=42,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _header(package: SavedDocumentContextPackage) -> tuple[Any, ...]:
    return (
        package.context_package_id,
        package.document_id,
        package.estimated_tokens,
        package.created_at,
    )


def _section_rows(package: SavedDocumentContextPackage) -> tuple[tuple[Any, ...], ...]:
    return tuple((section_id,) for section_id in package.section_ids)


def test_postgres_context_package_store_writes_exact_ordered_selection() -> None:
    package = _package()
    connection = _Connection(
        [
            _Cursor(),  # existing package
            _Cursor(row=(1,)),  # document exists
            _Cursor(rows=_section_rows(package)),  # sections belong to document
            _Cursor(),  # package insert
            _Cursor(),  # first section insert
            _Cursor(),  # second section insert
        ]
    )

    _repository(connection).save(package)

    assert connection.closed
    section_insert_params = [
        params
        for sql, params in connection.calls
        if "INSERT INTO tarkka.document_context_package_section" in sql
    ]
    assert section_insert_params == [
        (package.context_package_id, package.section_ids[0], 0),
        (package.context_package_id, package.section_ids[1], 1),
    ]


def test_postgres_context_package_store_reads_and_rejects_conflicts() -> None:
    package = _package()
    connection = _Connection([_Cursor(row=_header(package)), _Cursor(rows=_section_rows(package))])

    assert _repository(connection).get(package.context_package_id) == package

    connection = _Connection([_Cursor(row=_header(package)), _Cursor(rows=_section_rows(package))])
    with pytest.raises(ValueError, match="conflicting context package"):
        _repository(connection).save(replace(package, estimated_tokens=43))


def test_postgres_context_package_store_fails_closed_for_missing_document_or_section() -> None:
    package = _package()
    connection = _Connection([_Cursor(), _Cursor()])
    with pytest.raises(ValueError, match="document not found"):
        _repository(connection).save(package)

    connection = _Connection([_Cursor(), _Cursor(row=(1,)), _Cursor(rows=((uuid4(),),))])
    with pytest.raises(ValueError, match="sections do not belong"):
        _repository(connection).save(package)


def test_context_package_identity_excludes_creation_time_only() -> None:
    package = _package()

    assert _identity(package) == _identity(
        replace(package, created_at=datetime(2027, 1, 1, tzinfo=UTC))
    )
    assert _identity(package) != _identity(replace(package, section_ids=(uuid4(),)))
