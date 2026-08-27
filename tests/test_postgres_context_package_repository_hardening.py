from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from tarkka.infrastructure.postgres.connection import (
    PostgresSettings,
    PostgresTransientOperationError,
)
from tarkka.infrastructure.postgres.context_package_repository import (
    PostgresDocumentContextPackageRepository,
)


class _Cursor:
    def fetchone(self) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        return _Cursor()

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_postgres_context_package_get_returns_none_for_unknown_handle() -> None:
    connection = _Connection()
    repository = PostgresDocumentContextPackageRepository(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )

    assert repository.get(uuid4()) is None
    assert connection.closed


def test_postgres_context_package_preserves_non_driver_connection_errors() -> None:
    expected = ValueError("invalid test connection")

    def fail_connection(_: PostgresSettings) -> object:
        raise expected

    repository = PostgresDocumentContextPackageRepository(
        PostgresSettings("postgresql://unused"), connection_factory=fail_connection
    )

    with pytest.raises(ValueError, match="invalid test connection") as raised:
        repository.get(uuid4())

    assert raised.value is expected


def test_postgres_context_package_translates_driver_connection_errors() -> None:
    psycopg = pytest.importorskip("psycopg")
    expected = psycopg.OperationalError("database unavailable")

    def fail_connection(_: PostgresSettings) -> object:
        raise expected

    repository = PostgresDocumentContextPackageRepository(
        PostgresSettings("postgresql://unused"), connection_factory=fail_connection
    )

    with pytest.raises(PostgresTransientOperationError, match="retry may succeed") as raised:
        repository.get(uuid4())

    assert raised.value.__cause__ is expected
