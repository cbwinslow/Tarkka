from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from os import environ
from typing import Any


class PostgresDependencyError(RuntimeError):
    pass


class PostgresOperationError(RuntimeError):
    """A PostgreSQL driver failure safe to surface at an interface boundary."""


class PostgresTransientOperationError(PostgresOperationError, OSError):
    """A connection-level PostgreSQL interruption that callers may safely retry."""


@dataclass(frozen=True, slots=True)
class PostgresSettings:
    dsn: str

    @classmethod
    def from_environment(cls) -> PostgresSettings:
        dsn = environ.get("TARKKA_DATABASE_URL", "").strip()
        if not dsn:
            raise ValueError("TARKKA_DATABASE_URL is required for PostgreSQL operations")
        return cls(dsn=dsn)


ConnectionFactory = Callable[[PostgresSettings], Any]


def connect(settings: PostgresSettings) -> Any:
    """Create a psycopg connection without making psycopg a core runtime dependency."""
    try:
        psycopg = import_module("psycopg")
    except ImportError as exc:
        raise PostgresDependencyError(
            "PostgreSQL support requires `pip install tarkka[postgres]`"
        ) from exc
    try:
        return psycopg.connect(settings.dsn)
    except psycopg.Error as exc:
        if _is_transient_driver_error(psycopg, exc):
            raise PostgresTransientOperationError(
                "PostgreSQL connection failed; retry may succeed"
            ) from exc
        raise PostgresOperationError("PostgreSQL connection failed") from exc


def translate_driver_error(
    exc: Exception,
) -> PostgresOperationError | PostgresTransientOperationError | None:
    """Translate optional psycopg errors without importing it in the base profile."""
    try:
        psycopg = import_module("psycopg")
    except ImportError:
        return None
    if _is_transient_driver_error(psycopg, exc):
        return PostgresTransientOperationError("PostgreSQL operation failed; retry may succeed")
    if isinstance(exc, psycopg.Error):
        return PostgresOperationError("PostgreSQL operation failed")
    return None


@contextmanager
def translate_postgres_errors() -> Iterator[None]:
    """Translate driver failures without taking ownership of a caller's connection."""
    try:
        yield
    except Exception as exc:
        translated = translate_driver_error(exc)
        if translated is not None:
            raise translated from exc
        raise


@contextmanager
def managed_connection(
    settings: PostgresSettings,
    *,
    connection_factory: ConnectionFactory = connect,
    transactional: bool = True,
) -> Iterator[Any]:
    """Own one PostgreSQL connection with consistent transactions, errors, and cleanup.

    Body failures remain primary when transaction or connection cleanup also fails.
    Cleanup-only driver failures still use the normal PostgreSQL error taxonomy.
    """
    with translate_postgres_errors():
        connection = connection_factory(settings)

    primary_error: BaseException | None = None
    try:
        if transactional:
            with translate_postgres_errors():
                connection.__enter__()
        try:
            with translate_postgres_errors():
                yield connection
        except BaseException as body_error:
            primary_error = body_error
            if transactional:
                try:
                    connection.__exit__(type(body_error), body_error, body_error.__traceback__)
                except BaseException as transaction_error:
                    body_error.add_note(
                        "PostgreSQL transaction cleanup also failed "
                        f"({type(transaction_error).__name__}); primary exception preserved"
                    )
            raise
        else:
            if transactional:
                with translate_postgres_errors():
                    connection.__exit__(None, None, None)
    except BaseException as exc:
        if primary_error is None:
            primary_error = exc
        raise
    finally:
        try:
            connection.close()
        except BaseException as close_exc:
            if primary_error is not None:
                primary_error.add_note(
                    "PostgreSQL connection cleanup also failed "
                    f"({type(close_exc).__name__}); primary exception preserved"
                )
            elif isinstance(close_exc, Exception):
                translated = translate_driver_error(close_exc)
                if translated is not None:
                    raise translated from close_exc
                raise
            else:
                raise


def _is_transient_driver_error(psycopg: Any, exc: Exception) -> bool:
    transient_types = tuple(
        error_type
        for error_type in (
            getattr(psycopg, "OperationalError", None),
            getattr(psycopg, "InterfaceError", None),
        )
        if isinstance(error_type, type) and issubclass(error_type, Exception)
    )
    return bool(transient_types) and isinstance(exc, transient_types)
