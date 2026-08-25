BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.document_context_package (
    context_package_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document (document_id) ON DELETE RESTRICT,
    estimated_tokens integer NOT NULL CHECK (estimated_tokens >= 0),
    created_at timestamptz NOT NULL,
    is_finalized boolean NOT NULL DEFAULT false,
    UNIQUE (context_package_id, document_id)
);

CREATE INDEX IF NOT EXISTS document_context_package_document_idx
ON tarkka.document_context_package (document_id, created_at, context_package_id);

ALTER TABLE tarkka.section
ADD CONSTRAINT section_id_document_id_unique UNIQUE (section_id, document_id);

CREATE TABLE IF NOT EXISTS tarkka.document_context_package_section (
    context_package_id uuid NOT NULL
    REFERENCES tarkka.document_context_package (context_package_id) ON DELETE CASCADE,
    document_id uuid NOT NULL,
    section_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (context_package_id, ordinal),
    UNIQUE (context_package_id, section_id),
    FOREIGN KEY (context_package_id, document_id)
    REFERENCES tarkka.document_context_package (context_package_id, document_id)
    ON DELETE CASCADE,
    FOREIGN KEY (section_id, document_id)
    REFERENCES tarkka.section (section_id, document_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION tarkka.reject_document_context_package_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.is_finalized = false
       AND NEW.is_finalized = true
       AND NEW.context_package_id = OLD.context_package_id
       AND NEW.document_id = OLD.document_id
       AND NEW.estimated_tokens = OLD.estimated_tokens
       AND NEW.created_at = OLD.created_at THEN
        RETURN NEW;
    END IF;
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

CREATE OR REPLACE FUNCTION tarkka.reject_finalized_context_package_section_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    package_finalized boolean;
BEGIN
    SELECT is_finalized INTO package_finalized
    FROM tarkka.document_context_package
    WHERE context_package_id = NEW.context_package_id;
    IF package_finalized THEN
        RAISE EXCEPTION 'document context packages are immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS document_context_package_section_insert_guard_trigger
ON tarkka.document_context_package_section;
CREATE TRIGGER document_context_package_section_insert_guard_trigger
BEFORE INSERT ON tarkka.document_context_package_section
FOR EACH ROW EXECUTE FUNCTION tarkka.reject_finalized_context_package_section_insert();

COMMENT ON TABLE tarkka.document_context_package IS
'Immutable stable handles for explicit bounded document-section context selections.';

COMMIT;
