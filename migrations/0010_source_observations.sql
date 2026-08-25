BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.source_observation (
    observation_id uuid PRIMARY KEY,
    source_name text NOT NULL CHECK (length(btrim(source_name)) > 0),
    basis text NOT NULL CHECK (basis IN ('native', 'reconstructed', 'inferred')),
    source_version text CHECK (source_version IS NULL OR length(btrim(source_version)) > 0),
    provider_record_id text CHECK (
        provider_record_id IS NULL OR length(btrim(provider_record_id)) > 0
    ),
    media_type text CHECK (media_type IS NULL OR length(btrim(media_type)) > 0),
    native_artifact_id uuid REFERENCES tarkka.artifact (artifact_id) ON DELETE RESTRICT,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    observed_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS source_observation_artifact_idx
ON tarkka.source_observation (native_artifact_id, source_name, observation_id)
WHERE native_artifact_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS tarkka.resource_link_observation (
    link_id uuid PRIMARY KEY,
    observation_id uuid NOT NULL
    REFERENCES tarkka.source_observation (observation_id) ON DELETE CASCADE,
    target_uri text NOT NULL CHECK (length(btrim(target_uri)) > 0),
    resource_relation text NOT NULL CHECK (resource_relation IN (
        'canonical', 'alternate', 'full_text', 'supplement', 'dataset', 'software',
        'citation', 'related', 'version', 'correction', 'retraction'
    )),
    media_type text CHECK (media_type IS NULL OR length(btrim(media_type)) > 0),
    link_label text CHECK (link_label IS NULL OR length(btrim(link_label)) > 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS resource_link_observation_source_idx
ON tarkka.resource_link_observation (observation_id, resource_relation, target_uri, link_id);

COMMIT;
