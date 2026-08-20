from pathlib import Path


MIGRATION = Path("migrations/0005_structured_extraction.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_schema_enforces_run_document_lineage() -> None:
    sql = _sql()
    assert "REFERENCES tarkka.extraction_run(run_id, document_id)" in sql
    assert "REFERENCES tarkka.evidence(evidence_id, run_id, document_id)" in sql
    assert (
        "REFERENCES tarkka.research_extraction(extraction_id, run_id, document_id)"
        in sql
    )


def test_schema_validates_evidence_against_normalized_passage() -> None:
    sql = _sql()
    assert "validate_evidence_source" in sql
    assert "evidence text does not match normalized passage span" in sql
    assert "REFERENCES tarkka.passage(passage_id, document_id, section_id)" in sql


def test_schema_guards_final_evidence_link() -> None:
    sql = _sql()
    assert "ensure_extraction_has_evidence" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "evidence_link_delete_guard_trigger" in sql


def test_schema_indexes_expected_run_access_paths() -> None:
    sql = _sql()
    assert "extraction_run_document_idx" in sql
    assert "evidence_run_idx" in sql
    assert "research_extraction_run_idx" in sql
