from __future__ import annotations

from pathlib import Path

_MIGRATION = Path(__file__).parents[1] / "migrations" / "0008_work_external_ids.sql"


def test_work_external_ids_migration_is_additive_and_idempotent() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8").lower()

    assert "alter table tarkka.work" in sql
    assert "add column if not exists external_ids jsonb not null" in sql
    assert "default '{}'::jsonb" in sql
    assert "canonical identifier lookup uses tarkka.work_identifier" in sql
