"""Append-only PostgreSQL migration discovery and integrity checks.

Execution is deliberately kept outside normal application startup.  The future
deployment runner consumes this catalog to apply the SQL files explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any

from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)

_MIGRATION_ADVISORY_LOCK = 5_788_907_137


class MigrationCatalogError(RuntimeError):
    """Raised when the committed migration history is malformed."""


class MigrationHistoryError(RuntimeError):
    """Raised when database migration history disagrees with packaged SQL."""


@dataclass(frozen=True, slots=True)
class PostgresMigration:
    version: int
    name: str
    path: Path
    checksum: str


@dataclass(frozen=True, slots=True)
class MigrationUpgradeResult:
    applied: tuple[PostgresMigration, ...]
    skipped: tuple[PostgresMigration, ...]


def default_migrations_directory() -> Path:
    """Locate the SQL history bundled with the Tarkka package."""
    bundled = Path(str(files("tarkka").joinpath("migrations")))
    if any(bundled.glob("*.sql")):
        return bundled
    # Editable source trees do not contain the wheel's force-included files.
    return Path(__file__).parents[4] / "migrations"


def discover_migrations(directory: Path) -> tuple[PostgresMigration, ...]:
    """Return immutable migration metadata in strict numeric order."""
    migrations: list[PostgresMigration] = []
    versions: set[int] = set()
    for path in directory.glob("*.sql"):
        prefix, separator, name = path.stem.partition("_")
        if not separator or not prefix.isdecimal() or not name:
            raise MigrationCatalogError(f"invalid migration filename: {path.name}")
        version = int(prefix)
        if version in versions:
            raise MigrationCatalogError(f"duplicate migration version: {version:04d}")
        versions.add(version)
        content = path.read_bytes()
        migrations.append(
            PostgresMigration(
                version=version,
                name=path.name,
                path=path,
                checksum=sha256(content).hexdigest(),
            )
        )
    if not migrations:
        raise MigrationCatalogError(f"no PostgreSQL migrations found in {directory}")
    return tuple(sorted(migrations, key=lambda migration: migration.version))


def upgrade(
    settings: PostgresSettings,
    *,
    directory: Path | None = None,
    connection_factory: ConnectionFactory = connect,
) -> MigrationUpgradeResult:
    """Explicitly apply missing migrations and record their immutable checksums.

    Historical migration files own their transactions, so this operation uses an
    autocommit connection and records each successfully applied file afterward.
    The SQL history is intentionally never executed during normal application
    startup.
    """
    migrations = discover_migrations(directory or default_migrations_directory())
    with managed_connection(
        settings,
        connection_factory=connection_factory,
        transactional=False,
    ) as connection:
        connection.autocommit = True
        connection.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_ADVISORY_LOCK,))
        primary_error: BaseException | None = None
        try:
            _ensure_history_table(connection)
            history = _read_history(connection)
            catalog_versions = {migration.version for migration in migrations}
            unexpected = sorted(set(history) - catalog_versions)
            if unexpected:
                raise MigrationHistoryError(
                    f"database has unknown migration versions: {unexpected}"
                )
            applied: list[PostgresMigration] = []
            skipped: list[PostgresMigration] = []
            for migration in migrations:
                recorded = history.get(migration.version)
                if recorded is not None:
                    if recorded != (migration.name, migration.checksum):
                        raise MigrationHistoryError(
                            f"migration history mismatch for version {migration.version:04d}"
                        )
                    skipped.append(migration)
                    continue
                connection.execute(migration.path.read_text(encoding="utf-8"), prepare=False)
                connection.execute(
                    """
                    INSERT INTO tarkka.schema_migration (version, name, checksum)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum),
                )
                applied.append(migration)
            return MigrationUpgradeResult(tuple(applied), tuple(skipped))
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                connection.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_ADVISORY_LOCK,))
            except BaseException as unlock_exc:
                if primary_error is not None:
                    primary_error.add_note(
                        "PostgreSQL migration advisory-lock cleanup also failed "
                        f"({type(unlock_exc).__name__}); primary exception preserved"
                    )
                else:
                    raise


def _ensure_history_table(connection: Any) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS tarkka")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tarkka.schema_migration (
            version integer PRIMARY KEY,
            name text NOT NULL,
            checksum text NOT NULL CHECK (length(checksum) = 64),
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def _read_history(connection: Any) -> dict[int, tuple[str, str]]:
    rows = connection.execute(
        "SELECT version, name, checksum FROM tarkka.schema_migration ORDER BY version"
    ).fetchall()
    return {int(version): (str(name), str(checksum)) for version, name, checksum in rows}
