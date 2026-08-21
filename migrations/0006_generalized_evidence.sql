BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.figure (
    figure_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    page_number integer CHECK (page_number IS NULL OR page_number >= 1),
    label text,
    caption text,
    figure_type text NOT NULL DEFAULT 'unknown' CHECK (length(btrim(figure_type)) > 0),
    UNIQUE (document_id, ordinal),
    UNIQUE (figure_id, document_id)
);

CREATE TABLE IF NOT EXISTS tarkka.document_table (
    table_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    page_number integer CHECK (page_number IS NULL OR page_number >= 1),
    label text,
    caption text,
    row_count integer CHECK (row_count IS NULL OR row_count >= 0),
    column_count integer CHECK (column_count IS NULL OR column_count >= 0),
    UNIQUE (document_id, ordinal),
    UNIQUE (table_id, document_id)
);

CREATE TABLE IF NOT EXISTS tarkka.equation (
    equation_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    page_number integer CHECK (page_number IS NULL OR page_number >= 1),
    label text,
    source_text text,
    UNIQUE (document_id, ordinal),
    UNIQUE (equation_id, document_id)
);

ALTER TABLE tarkka.evidence
    ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'passage',
    ADD COLUMN IF NOT EXISTS figure_id uuid,
    ADD COLUMN IF NOT EXISTS table_id uuid,
    ADD COLUMN IF NOT EXISTS table_row_start integer,
    ADD COLUMN IF NOT EXISTS table_row_end integer,
    ADD COLUMN IF NOT EXISTS table_column_start integer,
    ADD COLUMN IF NOT EXISTS table_column_end integer,
    ADD COLUMN IF NOT EXISTS equation_id uuid;

ALTER TABLE tarkka.evidence
    ALTER COLUMN section_id DROP NOT NULL,
    ALTER COLUMN passage_id DROP NOT NULL,
    ALTER COLUMN passage_char_start DROP NOT NULL,
    ALTER COLUMN passage_char_end DROP NOT NULL,
    ALTER COLUMN text DROP NOT NULL;

ALTER TABLE tarkka.evidence
    DROP CONSTRAINT IF EXISTS evidence_passage_id_document_id_section_id_fkey;

ALTER TABLE tarkka.evidence
    DROP CONSTRAINT IF EXISTS evidence_source_kind_check;
ALTER TABLE tarkka.evidence
    ADD CONSTRAINT evidence_source_kind_check CHECK (
        source_kind IN ('passage', 'figure', 'table', 'equation')
    );

ALTER TABLE tarkka.evidence
    DROP CONSTRAINT IF EXISTS evidence_locator_shape_check;
ALTER TABLE tarkka.evidence
    ADD CONSTRAINT evidence_locator_shape_check CHECK (
        (
            source_kind = 'passage'
            AND section_id IS NOT NULL
            AND passage_id IS NOT NULL
            AND passage_char_start IS NOT NULL
            AND passage_char_end IS NOT NULL
            AND text IS NOT NULL
            AND figure_id IS NULL AND table_id IS NULL AND equation_id IS NULL
            AND table_row_start IS NULL AND table_row_end IS NULL
            AND table_column_start IS NULL AND table_column_end IS NULL
        ) OR (
            source_kind = 'figure'
            AND figure_id IS NOT NULL
            AND section_id IS NULL AND passage_id IS NULL
            AND passage_char_start IS NULL AND passage_char_end IS NULL AND text IS NULL
            AND table_id IS NULL AND equation_id IS NULL
            AND table_row_start IS NULL AND table_row_end IS NULL
            AND table_column_start IS NULL AND table_column_end IS NULL
        ) OR (
            source_kind = 'table'
            AND table_id IS NOT NULL
            AND table_row_start IS NOT NULL AND table_row_start >= 0
            AND table_row_end IS NOT NULL AND table_row_end > table_row_start
            AND table_column_start IS NOT NULL AND table_column_start >= 0
            AND table_column_end IS NOT NULL AND table_column_end > table_column_start
            AND section_id IS NULL AND passage_id IS NULL
            AND passage_char_start IS NULL AND passage_char_end IS NULL AND text IS NULL
            AND figure_id IS NULL AND equation_id IS NULL
        ) OR (
            source_kind = 'equation'
            AND equation_id IS NOT NULL
            AND section_id IS NULL AND passage_id IS NULL
            AND passage_char_start IS NULL AND passage_char_end IS NULL AND text IS NULL
            AND figure_id IS NULL AND table_id IS NULL
            AND table_row_start IS NULL AND table_row_end IS NULL
            AND table_column_start IS NULL AND table_column_end IS NULL
        )
    );

CREATE UNIQUE INDEX IF NOT EXISTS evidence_passage_unique_idx
    ON tarkka.evidence(run_id, passage_id, passage_char_start, passage_char_end)
    WHERE source_kind = 'passage';
CREATE UNIQUE INDEX IF NOT EXISTS evidence_figure_unique_idx
    ON tarkka.evidence(run_id, figure_id)
    WHERE source_kind = 'figure';
CREATE UNIQUE INDEX IF NOT EXISTS evidence_table_unique_idx
    ON tarkka.evidence(
        run_id, table_id, table_row_start, table_row_end,
        table_column_start, table_column_end
    ) WHERE source_kind = 'table';
CREATE UNIQUE INDEX IF NOT EXISTS evidence_equation_unique_idx
    ON tarkka.evidence(run_id, equation_id)
    WHERE source_kind = 'equation';

CREATE OR REPLACE FUNCTION tarkka.validate_evidence_source()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    passage_text text;
    target_rows integer;
    target_columns integer;
BEGIN
    IF NEW.source_kind = 'passage' THEN
        SELECT p.text INTO passage_text
          FROM tarkka.passage AS p
         WHERE p.passage_id = NEW.passage_id
           AND p.document_id = NEW.document_id
           AND p.section_id = NEW.section_id;
        IF passage_text IS NULL THEN
            RAISE EXCEPTION 'evidence does not resolve to normalized passage lineage';
        END IF;
        IF NEW.passage_char_end > char_length(passage_text) THEN
            RAISE EXCEPTION 'evidence range is outside normalized passage';
        END IF;
        IF substring(
            passage_text FROM NEW.passage_char_start + 1
            FOR NEW.passage_char_end - NEW.passage_char_start
        ) <> NEW.text THEN
            RAISE EXCEPTION 'evidence text does not match normalized passage span';
        END IF;
    ELSIF NEW.source_kind = 'figure' THEN
        IF NOT EXISTS (
            SELECT 1 FROM tarkka.figure
             WHERE figure_id = NEW.figure_id AND document_id = NEW.document_id
        ) THEN
            RAISE EXCEPTION 'evidence does not resolve to normalized figure';
        END IF;
    ELSIF NEW.source_kind = 'table' THEN
        SELECT row_count, column_count INTO target_rows, target_columns
          FROM tarkka.document_table
         WHERE table_id = NEW.table_id AND document_id = NEW.document_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'evidence does not resolve to normalized table';
        END IF;
        IF target_rows IS NOT NULL AND NEW.table_row_end > target_rows THEN
            RAISE EXCEPTION 'evidence row range is outside normalized table';
        END IF;
        IF target_columns IS NOT NULL AND NEW.table_column_end > target_columns THEN
            RAISE EXCEPTION 'evidence column range is outside normalized table';
        END IF;
    ELSIF NEW.source_kind = 'equation' THEN
        IF NOT EXISTS (
            SELECT 1 FROM tarkka.equation
             WHERE equation_id = NEW.equation_id AND document_id = NEW.document_id
        ) THEN
            RAISE EXCEPTION 'evidence does not resolve to normalized equation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS validate_evidence_source_trigger ON tarkka.evidence;
CREATE TRIGGER validate_evidence_source_trigger
BEFORE INSERT OR UPDATE ON tarkka.evidence
FOR EACH ROW EXECUTE FUNCTION tarkka.validate_evidence_source();

COMMIT;
