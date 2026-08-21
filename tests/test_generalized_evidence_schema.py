from pathlib import Path

MIGRATION = Path("migrations/0006_generalized_evidence.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_schema_adds_first_class_source_artifacts() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS tarkka.figure" in sql
    assert "CREATE TABLE IF NOT EXISTS tarkka.document_table" in sql
    assert "CREATE TABLE IF NOT EXISTS tarkka.equation" in sql
    assert "REFERENCES tarkka.document(document_id)" in sql


def test_schema_generalizes_evidence_locator_shape() -> None:
    sql = _sql()
    assert "source_kind IN ('passage', 'figure', 'table', 'equation')" in sql
    assert "evidence_locator_shape_check" in sql
    assert "table_row_start" in sql
    assert "table_column_end" in sql


def test_schema_validates_every_source_kind_against_owning_document() -> None:
    sql = _sql()
    assert "evidence does not resolve to normalized passage lineage" in sql
    assert "evidence does not resolve to normalized figure" in sql
    assert "evidence does not resolve to normalized table" in sql
    assert "evidence does not resolve to normalized equation" in sql
    assert "document_id = NEW.document_id" in sql


def test_schema_keeps_locator_specific_uniqueness() -> None:
    sql = _sql()
    assert "evidence_passage_unique_idx" in sql
    assert "evidence_figure_unique_idx" in sql
    assert "evidence_table_unique_idx" in sql
    assert "evidence_equation_unique_idx" in sql
