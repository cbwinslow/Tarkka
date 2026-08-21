from pathlib import Path

MIGRATION = Path("migrations/0007_citations.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_schema_preserves_reference_and_document_identity() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS tarkka.bibliographic_reference" in sql
    assert "UNIQUE (document_id, ordinal)" in sql
    assert "UNIQUE (reference_id, document_id)" in sql


def test_schema_enforces_exact_citation_ranges() -> None:
    sql = _sql()
    assert "char_end > char_start" in sql
    assert "char_end - char_start = char_length(raw_text)" in sql
    assert "char_end - char_start = char_length(text)" in sql


def test_schema_fails_closed_for_resolution_state() -> None:
    sql = _sql()
    assert "reference_id uuid PRIMARY KEY" in sql
    assert "status IN ('unresolved', 'resolved', 'ambiguous', 'rejected')" in sql
    assert "cardinality(candidate_work_ids) >= 2" in sql
    assert "status IN ('unresolved', 'rejected')" in sql


def test_schema_requires_work_relation_provenance_and_distinct_endpoints() -> None:
    sql = _sql()
    assert "CHECK (subject_work_id <> object_work_id)" in sql
    assert "source_observation_id IS NOT NULL" in sql
    assert "OR source_document_id IS NOT NULL" in sql
    assert "OR source_reference_id IS NOT NULL" in sql


def test_schema_indexes_relation_traversal_paths() -> None:
    sql = _sql()
    assert "work_relation_subject_idx" in sql
    assert "work_relation_object_idx" in sql
    assert "citation_resolution_work_idx" in sql
