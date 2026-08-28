from __future__ import annotations

from typing import Any

import pytest

import tarkka.infrastructure.postgres.connection as postgres_connection
from tarkka.infrastructure.postgres.connection import (
    PostgresDependencyError,
    PostgresOperationError,
    PostgresSettings,
    PostgresTransientOperationError,
    _is_transient_driver_error,
    connect,
    translate_driver_error,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _DriverError(Exception):
    pass


class _OperationalError(_DriverError):
    pass


class _InterfaceError(_DriverError):
    pass


class _Driver:
    Error = _DriverError
    OperationalError = _OperationalError
    InterfaceError = _InterfaceError

    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.dsns: list[str] = []

    def connect(self, dsn: str) -> object:
        self.dsns.append(dsn)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _missing_module(_: str) -> Any:
    raise ImportError("psycopg unavailable")


def test_postgres_settings_reads_trimmed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_DATABASE_URL", "  postgresql://example/db  ")

    assert PostgresSettings.from_environment() == PostgresSettings("postgresql://example/db")


def test_connect_reports_missing_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(postgres_connection, "import_module", _missing_module)

    with pytest.raises(PostgresDependencyError, match="tarkka\\[postgres\\]"):
        connect(PostgresSettings("postgresql://unused"))


def test_connect_returns_connection_and_passes_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = object()
    driver = _Driver(expected)
    monkeypatch.setattr(postgres_connection, "import_module", lambda _: driver)

    assert connect(PostgresSettings("postgresql://example/db")) is expected
    assert driver.dsns == ["postgresql://example/db"]


@pytest.mark.parametrize(
    "error",
    [_OperationalError("offline"), _InterfaceError("disconnected")],
)
def test_connect_translates_retryable_driver_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: _DriverError,
) -> None:
    monkeypatch.setattr(postgres_connection, "import_module", lambda _: _Driver(error))

    with pytest.raises(PostgresTransientOperationError, match="retry may succeed") as raised:
        connect(PostgresSettings("postgresql://unused"))

    assert raised.value.__cause__ is error


def test_connect_translates_permanent_driver_error(monkeypatch: pytest.MonkeyPatch) -> None:
    error = _DriverError("constraint")
    monkeypatch.setattr(postgres_connection, "import_module", lambda _: _Driver(error))

    with pytest.raises(PostgresOperationError, match="connection failed") as raised:
        connect(PostgresSettings("postgresql://unused"))

    assert not isinstance(raised.value, PostgresTransientOperationError)
    assert raised.value.__cause__ is error


def test_translate_driver_error_is_optional_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(postgres_connection, "import_module", _missing_module)

    assert translate_driver_error(RuntimeError("boom")) is None


def test_translate_driver_error_classifies_transient_permanent_and_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _Driver(object())
    monkeypatch.setattr(postgres_connection, "import_module", lambda _: driver)

    transient = translate_driver_error(_OperationalError("offline"))
    permanent = translate_driver_error(_DriverError("constraint"))
    unrelated = translate_driver_error(RuntimeError("application"))

    assert isinstance(transient, PostgresTransientOperationError)
    assert isinstance(permanent, PostgresOperationError)
    assert not isinstance(permanent, PostgresTransientOperationError)
    assert unrelated is None


def test_transient_detection_ignores_missing_or_invalid_driver_error_types() -> None:
    class _MalformedDriver:
        OperationalError = None
        InterfaceError = "not-a-type"

    assert not _is_transient_driver_error(_MalformedDriver(), RuntimeError("boom"))
