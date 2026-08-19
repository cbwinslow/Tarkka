BEGIN;

CREATE SCHEMA IF NOT EXISTS tarkka;

CREATE TABLE IF NOT EXISTS tarkka.artifact (
    artifact_id uuid PRIMARY KEY,
    sha256 text NOT NULL CHECK (length(sha256) = 64),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_type text NOT NULL,
    storage_key text NOT NULL,
    original_name text,
    source_uri text,
    acquired_at timestamptz NOT NULL,
    UNIQUE (sha256)
);

CREATE TABLE IF NOT EXISTS tarkka.document (
    document_id uuid PRIMARY KEY,
    artifact_id uuid NOT NULL REFERENCES tarkka.artifact(artifact_id),
    title text NOT NULL,
    parser_name text NOT NULL,
    parser_version text NOT NULL,
    normalized_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS tarkka.section (
    section_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    parent_section_id uuid REFERENCES tarkka.section(section_id),
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    level integer NOT NULL CHECK (level >= 1),
    title text NOT NULL,
    UNIQUE (document_id, ordinal)
);

CREATE TABLE IF NOT EXISTS tarkka.passage (
    passage_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    section_id uuid NOT NULL REFERENCES tarkka.section(section_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    text text NOT NULL,
    char_start integer NOT NULL CHECK (char_start >= 0),
    char_end integer NOT NULL CHECK (char_end >= char_start),
    UNIQUE (section_id, ordinal)
);

CREATE TABLE IF NOT EXISTS tarkka.resource_manifest (
    document_id uuid PRIMARY KEY REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    manifest jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
