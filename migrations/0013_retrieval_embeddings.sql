BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE tarkka.retrieval_embedding (
    embedding_id uuid PRIMARY KEY,
    segment_id uuid NOT NULL,
    segment_digest text NOT NULL CHECK (length(segment_digest) = 64),
    segment_derivation_version text NOT NULL,
    segment_configuration_fingerprint text NOT NULL,
    model_identifier text NOT NULL,
    model_revision text NOT NULL,
    configuration_fingerprint text NOT NULL,
    normalization text NOT NULL CHECK (normalization IN ('none', 'l2')),
    embedding vector NOT NULL,
    dimension integer NOT NULL CHECK (dimension > 0),
    CHECK (vector_dims(embedding) = dimension)
);

CREATE INDEX retrieval_embedding_segment_idx
ON tarkka.retrieval_embedding (
    segment_id,
    model_identifier,
    model_revision,
    configuration_fingerprint,
    embedding_id
);

COMMIT;
