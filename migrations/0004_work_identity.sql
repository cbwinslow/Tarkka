BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.work (
    work_id uuid PRIMARY KEY,
    title text NOT NULL,
    publication_type text NOT NULL DEFAULT 'unknown',
    language text,
    publication_year integer CHECK (publication_year IS NULL OR publication_year >= 0),
    abstract text,
    venue text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tarkka.work_identifier (
    identifier_id uuid PRIMARY KEY,
    work_id uuid NOT NULL REFERENCES tarkka.work(work_id) ON DELETE CASCADE,
    scheme text NOT NULL,
    value text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (scheme, value),
    UNIQUE (work_id, scheme, value)
);

CREATE INDEX IF NOT EXISTS work_identifier_work_idx
    ON tarkka.work_identifier (work_id);

CREATE TABLE IF NOT EXISTS tarkka.work_source_record (
    source_record_id uuid PRIMARY KEY,
    work_id uuid NOT NULL REFERENCES tarkka.work(work_id) ON DELETE CASCADE,
    provider text NOT NULL,
    provider_record_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    record jsonb NOT NULL,
    UNIQUE (provider, provider_record_id)
);

CREATE INDEX IF NOT EXISTS work_source_record_work_idx
    ON tarkka.work_source_record (work_id);

CREATE INDEX IF NOT EXISTS work_source_record_provider_idx
    ON tarkka.work_source_record (provider, provider_record_id);

COMMIT;
