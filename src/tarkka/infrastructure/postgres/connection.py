from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Any


class PostgresDependencyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PostgresSettings:
    dsn: str

    @classmethod
    def from_environment(cls) -> "PostgresSettings":
        dsn = environ.get("TARKKA_DATABASE_URL", "").strip()
        if not dsn:
            raise ValueError("TARKKA_DATABASE_URL is required for PostgreSQL operations")
        return cls(dsn=dsn)


def connect(settings: PostgresSettings) -> Any:
    """Create a psycopg connection without making psycopg a core runtime dependency."""
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PostgresDependencyError(
            "PostgreSQL support requires `pip install tarkka[postgres]`"
        ) from exc
    return psycopg.connect(settings.dsn)
