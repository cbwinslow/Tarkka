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
    managed_connection,
    translate_driver_error,
    translate_postgres_errors,
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


class _Connection:
    def __init__(
        self,
        *,
        close_error: BaseException | None = None,
        exit_error: Exception | None = None,
    ) -> None:
        self.close_error = close_error
        self.exit_error = exit_error
        self.entered = 0
        self.exited = 0
        self.closed = 0

    def __enter__(self) -> _Connection:
        self.entered += 1
        return self

    def __exit__(self, *_: object) -> None:
        self.exited += 1
        if self.exit_error is not None:
            raise self.exit_error

    def close(self) -> None:
        self.closed += 1
        if self.close_error is not None:
            raise self.close_error


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


def test_translate_postgres_errors_translates_only_driver_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _Driver(object())
    monkeypatch.setattr(postgres_connection, "import_module", lambda _: driver)
    driver_error = _DriverError("constraint")

    with pytest.raises(PostgresOperationError) as raised:
        with translate_postgres_errors():
            raise driver_error
    assert raised.value.__cause__ is driver_error

    application_error = RuntimeError("application")
    with pytest.raises(RuntimeError) as unmodified:
        with translate_postgres_errors():
            raise application_error
    assert unmodified.value is application_error


def test_managed_connection_owns_transaction_and_close() -> None:
    connection = _Connection()

    with managed_connection(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    ) as yielded:
        assert yielded is connection

    assert (connection.entered, connection.exited, connection.closed) == (1, 1, 1)


def test_managed_connection_supports_nontransactional_ownership() -> None:
    connection = _Connection()

    with managed_connection(
        PostgresSettings("postgresql://unused"),
        connection_factory=lambda _: connection,
        transactional=False,
    ) as yielded:
        assert yielded is connection

    assert (connection.entered, connection.exited, connection.closed) == (0, 0, 1)


def test_managed_connection_translates_factory_and_transaction_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _Driver(object())
    monkeypatch.setattr(postgres_connection, "import_module", lambda _: driver)
    factory_error = _DriverError("factory")

    with pytest.raises(PostgresOperationError) as factory_raised:
        with managed_connection(
            PostgresSettings("postgresql://unused"),
            connection_factory=lambda _: (_ for _ in ()).throw(factory_error),
        ):
            pass
    assert factory_raised.value.__cause__ is factory_error

    exit_error = _OperationalError("commit")
    connection = _Connection(exit_error=exit_error)
    with pytest.raises(PostgresTransientOperationError) as transaction_raised:
        with managed_connection(
            PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
        ):
            pass
    assert transaction_raised.value.__cause__ is exit_error
    assert connection.closed == 1


def test_managed_connection_preserves_primary_error_when_close_also_fails() -> None:
    close_error = RuntimeError("close")
    connection = _Connection(close_error=close_error)
    primary = ValueError("primary")

    with pytest.raises(ValueError) as raised:
        with managed_connection(
            PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
        ):
            raise primary

    assert raised.value is primary
    assert raised.value.__notes__ == [
        "PostgreSQL connection cleanup also failed (RuntimeError); primary exception preserved"
    ]
    assert connection.closed == 1


def test_managed_connection_surfaces_and_translates_cleanup_only_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _Driver(object())
    monkeypatch.setattr(postgres_connection, "import_module", lambda _: driver)
    close_error = _DriverError("close")
    connection = _Connection(close_error=close_error)

    with pytest.raises(PostgresOperationError) as translated:
        with managed_connection(
            PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
        ):
            pass
    assert translated.value.__cause__ is close_error

    application_close = RuntimeError("close")
    connection = _Connection(close_error=application_close)
    with pytest.raises(RuntimeError) as unmodified:
        with managed_connection(
            PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
        ):
            pass
    assert unmodified.value is application_close


def test_managed_connection_does_not_swallow_baseexception_cleanup() -> None:
    cleanup = KeyboardInterrupt()
    connection = _Connection(close_error=cleanup)

    with pytest.raises(KeyboardInterrupt) as raised:
        with managed_connection(
            PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
        ):
            pass

    assert raised.value is cleanup


def test_transient_detection_ignores_missing_or_invalid_driver_error_types() -> None:
    class _MalformedDriver:
        OperationalError = None
        InterfaceError = "not-a-type"

    assert not _is_transient_driver_error(_MalformedDriver(), RuntimeError("boom"))
