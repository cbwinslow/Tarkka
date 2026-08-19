BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.acquisition (
    acquisition_id uuid PRIMARY KEY,
    artifact_id uuid NOT NULL REFERENCES tarkka.artifact(artifact_id) ON DELETE CASCADE,
    source_uri text NOT NULL,
    original_name text,
    acquired_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS acquisition_artifact_time_idx
    ON tarkka.acquisition (artifact_id, acquired_at DESC);

COMMENT ON TABLE tarkka.acquisition IS
    'Append-oriented provenance events describing where/how immutable artifact content was acquired.';

COMMIT;
