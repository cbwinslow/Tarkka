BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.document_context_package (
    context_package_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document (document_id) ON DELETE RESTRICT,
    estimated_tokens integer NOT NULL CHECK (estimated_tokens >= 0),
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS document_context_package_document_idx
ON tarkka.document_context_package (document_id, created_at, context_package_id);

CREATE TABLE IF NOT EXISTS tarkka.document_context_package_section (
    context_package_id uuid NOT NULL
    REFERENCES tarkka.document_context_package (context_package_id) ON DELETE CASCADE,
    section_id uuid NOT NULL REFERENCES tarkka.section (section_id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (context_package_id, ordinal),
    UNIQUE (context_package_id, section_id)
);

CREATE OR REPLACE FUNCTION tarkka.reject_document_context_package_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'document context packages are immutable';
END;
$$;

DROP TRIGGER IF EXISTS document_context_package_immutable_trigger
ON tarkka.document_context_package;
CREATE TRIGGER document_context_package_immutable_trigger
BEFORE UPDATE OR DELETE ON tarkka.document_context_package
FOR EACH ROW EXECUTE FUNCTION tarkka.reject_document_context_package_update();

DROP TRIGGER IF EXISTS document_context_package_section_immutable_trigger
ON tarkka.document_context_package_section;
CREATE TRIGGER document_context_package_section_immutable_trigger
BEFORE UPDATE OR DELETE ON tarkka.document_context_package_section
FOR EACH ROW EXECUTE FUNCTION tarkka.reject_document_context_package_update();

COMMENT ON TABLE tarkka.document_context_package IS
'Immutable stable handles for explicit bounded document-section context selections.';

COMMIT;
