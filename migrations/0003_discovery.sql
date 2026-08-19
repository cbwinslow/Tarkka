BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.search_snapshot (
    snapshot_id uuid PRIMARY KEY,
    query jsonb NOT NULL,
    providers_used text[] NOT NULL,
    records jsonb NOT NULL,
    next_cursors jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS search_snapshot_created_at_idx
    ON tarkka.search_snapshot (created_at DESC);

CREATE INDEX IF NOT EXISTS search_snapshot_query_gin_idx
    ON tarkka.search_snapshot USING gin (query);

CREATE INDEX IF NOT EXISTS search_snapshot_providers_gin_idx
    ON tarkka.search_snapshot USING gin (providers_used);

CREATE INDEX IF NOT EXISTS search_snapshot_records_gin_idx
    ON tarkka.search_snapshot USING gin (records);

COMMENT ON TABLE tarkka.search_snapshot IS
    'Immutable scholarly discovery result snapshots for reproducibility and audit.';

COMMIT;
