from pathlib import Path

MIGRATION = Path("migrations/0007_citations.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_schema_preserves_reference_and_document_identity() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS tarkka.bibliographic_reference" in sql
    assert "UNIQUE (document_id, ordinal)" in sql
    assert "UNIQUE (reference_id, document_id)" in sql


def test_schema_enforces_exact_citation_ranges_and_nonblank_context() -> None:
    sql = _sql()
    assert "char_end > char_start" in sql
    assert "char_end - char_start = char_length(raw_text)" in sql
    assert "char_end - char_start = char_length(text)" in sql
    assert "text text NOT NULL CHECK (length(btrim(text)) > 0)" in sql


def test_schema_enforces_citation_document_lineage() -> None:
    sql = _sql()
    assert "section_lineage_idx" in sql
    assert "FOREIGN KEY (reference_id, document_id)" in sql
    assert "REFERENCES tarkka.bibliographic_reference (reference_id, document_id)" in sql
    assert "FOREIGN KEY (mention_id, document_id)" in sql
    assert "REFERENCES tarkka.citation_mention (mention_id, document_id)" in sql
    assert "FOREIGN KEY (section_id, document_id)" in sql
    assert "REFERENCES tarkka.section (section_id, document_id)" in sql
    assert "FOREIGN KEY (passage_id, document_id, section_id)" in sql
    assert "REFERENCES tarkka.passage (passage_id, document_id, section_id)" in sql


def test_schema_fails_closed_for_resolution_state() -> None:
    sql = _sql()
    assert "reference_id uuid PRIMARY KEY" in sql
    assert "status IN ('unresolved', 'resolved', 'ambiguous', 'rejected')" in sql
    assert "cardinality(candidate_work_ids) >= 2" in sql
    assert "status IN ('unresolved', 'rejected')" in sql


def test_schema_requires_relation_provenance_and_allows_only_self_citation() -> None:
    sql = _sql()
    assert "CHECK (subject_work_id <> object_work_id OR kind = 'cites')" in sql
    assert "CHECK (source_reference_id IS NULL OR source_document_id IS NOT NULL)" in sql
    assert "source_observation_id IS NOT NULL" in sql
    assert "OR source_document_id IS NOT NULL" in sql
    assert "OR source_reference_id IS NOT NULL" in sql
    assert "FOREIGN KEY (source_reference_id, source_document_id)" in sql


def test_schema_deduplicates_nullable_relation_provenance() -> None:
    sql = _sql()
    assert "work_relation_logical_unique_idx" in sql
    assert "coalesce(source_observation_id::text, '')" in sql
    assert "coalesce(source_document_id::text, '')" in sql
    assert "coalesce(source_reference_id::text, '')" in sql


def test_schema_indexes_relation_traversal_paths() -> None:
    sql = _sql()
    assert "work_relation_subject_idx" in sql
    assert "work_relation_object_idx" in sql
    assert "citation_resolution_work_idx" in sql
