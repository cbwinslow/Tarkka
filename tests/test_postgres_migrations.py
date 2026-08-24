from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.migrations import (
    MigrationCatalogError,
    MigrationHistoryError,
    default_migrations_directory,
    discover_migrations,
    upgrade,
)
from tarkka.interfaces.main import main


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self._rows = rows or []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Connection:
    def __init__(self, history: list[tuple[Any, ...]] | None = None) -> None:
        self.history = history or []
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []
        self.closed = False
        self.autocommit = False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None, **_: Any) -> _Cursor:
        self.calls.append((sql, params))
        if sql.startswith("SELECT version"):
            return _Cursor(self.history)
        return _Cursor()

    def close(self) -> None:
        self.closed = True


def test_discovers_committed_migrations_in_numeric_order() -> None:
    migrations = discover_migrations(Path("migrations"))
    versions = [item.version for item in migrations]

    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert all(len(item.checksum) == 64 for item in migrations)


def test_sorts_unpadded_versions_numerically(tmp_path: Path) -> None:
    (tmp_path / "10_tenth.sql").write_text("SELECT 10;", encoding="utf-8")
    (tmp_path / "2_second.sql").write_text("SELECT 2;", encoding="utf-8")

    assert [item.version for item in discover_migrations(tmp_path)] == [2, 10]


def test_default_migration_directory_contains_the_committed_history() -> None:
    assert default_migrations_directory().joinpath("0001_core.sql").is_file()


def test_rejects_invalid_or_duplicate_migration_names(tmp_path: Path) -> None:
    (tmp_path / "not-a-migration.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationCatalogError, match="invalid migration filename"):
        discover_migrations(tmp_path)

    (tmp_path / "not-a-migration.sql").unlink()
    (tmp_path / "0001_one.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0001_two.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(MigrationCatalogError, match="duplicate migration version"):
        discover_migrations(tmp_path)


def test_upgrade_applies_unrecorded_sql_and_records_checksums(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    connection = _Connection()

    result = upgrade(
        PostgresSettings("postgresql://unused"),
        directory=tmp_path,
        connection_factory=lambda _: connection,
    )

    assert [item.version for item in result.applied] == [1, 2]
    assert result.skipped == ()
    assert connection.autocommit
    assert connection.closed
    assert [params[0] for _, params in connection.calls if params] == [1, 2]


def test_upgrade_rejects_changed_or_unknown_history(tmp_path: Path) -> None:
    path = tmp_path / "0001_first.sql"
    path.write_text("SELECT 1;", encoding="utf-8")
    migration = discover_migrations(tmp_path)[0]
    changed = _Connection([(1, migration.name, "0" * 64)])

    with pytest.raises(MigrationHistoryError, match="history mismatch"):
        upgrade(
            PostgresSettings("postgresql://unused"),
            directory=tmp_path,
            connection_factory=lambda _: changed,
        )

    unknown = _Connection([(2, "0002_unknown.sql", "0" * 64)])
    with pytest.raises(MigrationHistoryError, match="unknown migration versions"):
        upgrade(
            PostgresSettings("postgresql://unused"),
            directory=tmp_path,
            connection_factory=lambda _: unknown,
        )


def test_upgrade_skips_a_matching_recorded_migration(tmp_path: Path) -> None:
    path = tmp_path / "0001_first.sql"
    path.write_text("SELECT 1;", encoding="utf-8")
    migration = discover_migrations(tmp_path)[0]
    connection = _Connection([(1, migration.name, migration.checksum)])

    result = upgrade(
        PostgresSettings("postgresql://unused"),
        directory=tmp_path,
        connection_factory=lambda _: connection,
    )

    assert result.applied == ()
    assert result.skipped == (migration,)


def test_db_upgrade_cli_reports_missing_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("TARKKA_DATABASE_URL", raising=False)

    assert main(["db", "upgrade"]) == 2
    assert "TARKKA_DATABASE_URL is required" in capsys.readouterr().err
