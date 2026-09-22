BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.table_cell (
    table_id uuid NOT NULL REFERENCES tarkka.document_table (table_id) ON DELETE CASCADE,
    row_start integer NOT NULL CHECK (row_start >= 0),
    row_end integer NOT NULL CHECK (row_end > row_start),
    column_start integer NOT NULL CHECK (column_start >= 0),
    column_end integer NOT NULL CHECK (column_end > column_start),
    cell_text text NOT NULL CHECK (length(btrim(cell_text)) > 0),
    cell_role text NOT NULL CHECK (cell_role IN ('header', 'data', 'note')),
    source_anchor text,
    PRIMARY KEY (table_id, row_start, column_start),
    CHECK (source_anchor IS NULL OR length(btrim(source_anchor)) > 0)
);

COMMIT;
