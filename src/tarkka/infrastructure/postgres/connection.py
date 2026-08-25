from __future__ import annotations

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
