BEGIN;

-- Composite uniqueness supports document-lineage foreign keys below.
CREATE UNIQUE INDEX IF NOT EXISTS section_lineage_idx
ON tarkka.section (section_id, document_id);

CREATE TABLE IF NOT EXISTS tarkka.bibliographic_reference (
    reference_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document (document_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    raw_text text NOT NULL CHECK (length(btrim(raw_text)) > 0),
    identifiers jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(identifiers) = 'object'),
    title text CHECK (title IS NULL OR length(btrim(title)) > 0),
    authors jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(authors) = 'array'),
    publication_year integer CHECK (publication_year IS NULL OR publication_year >= 0),
    source_anchor text CHECK (source_anchor IS NULL OR length(btrim(source_anchor)) > 0),
    source_observation_id uuid,
    UNIQUE (document_id, ordinal),
    UNIQUE (reference_id, document_id)
);

CREATE INDEX IF NOT EXISTS bibliographic_reference_document_idx
ON tarkka.bibliographic_reference (document_id, ordinal);

CREATE TABLE IF NOT EXISTS tarkka.citation_mention (
    mention_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document (document_id) ON DELETE CASCADE,
    reference_id uuid,
    section_id uuid,
    passage_id uuid,
    raw_text text NOT NULL CHECK (length(btrim(raw_text)) > 0),
    char_start integer,
    char_end integer,
    source_anchor text CHECK (source_anchor IS NULL OR length(btrim(source_anchor)) > 0),
    source_observation_id uuid,
    CHECK (passage_id IS NULL OR section_id IS NOT NULL),
    CHECK (
        (char_start IS NULL AND char_end IS NULL)
        OR (
            char_start IS NOT NULL
            AND char_end IS NOT NULL
            AND char_start >= 0
            AND char_end > char_start
            AND char_end - char_start = char_length(raw_text)
        )
    ),
    FOREIGN KEY (reference_id, document_id)
    REFERENCES tarkka.bibliographic_reference (reference_id, document_id)
    ON DELETE RESTRICT,
    FOREIGN KEY (section_id, document_id)
    REFERENCES tarkka.section (section_id, document_id)
    ON DELETE RESTRICT,
    FOREIGN KEY (passage_id, document_id, section_id)
    REFERENCES tarkka.passage (passage_id, document_id, section_id)
    ON DELETE RESTRICT,
    UNIQUE (mention_id, document_id)
);

CREATE INDEX IF NOT EXISTS citation_mention_document_idx
ON tarkka.citation_mention (document_id, char_start, mention_id);
CREATE INDEX IF NOT EXISTS citation_mention_reference_idx
ON tarkka.citation_mention (reference_id)
WHERE reference_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS tarkka.citation_context (
    context_id uuid PRIMARY KEY,
    mention_id uuid NOT NULL,
    document_id uuid NOT NULL REFERENCES tarkka.document (document_id) ON DELETE CASCADE,
    section_id uuid,
    passage_id uuid,
    text text NOT NULL CHECK (length(btrim(text)) > 0),  -- noqa: RF04
    char_start integer NOT NULL CHECK (char_start >= 0),
    char_end integer NOT NULL,
    CHECK (char_end > char_start),
    CHECK (char_end - char_start = char_length(text)),
    CHECK (passage_id IS NULL OR section_id IS NOT NULL),
    FOREIGN KEY (mention_id, document_id)
    REFERENCES tarkka.citation_mention (mention_id, document_id)
    ON DELETE CASCADE,
    FOREIGN KEY (section_id, document_id)
    REFERENCES tarkka.section (section_id, document_id)
    ON DELETE RESTRICT,
    FOREIGN KEY (passage_id, document_id, section_id)
    REFERENCES tarkka.passage (passage_id, document_id, section_id)
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS citation_context_document_idx
ON tarkka.citation_context (document_id, char_start, context_id);
CREATE INDEX IF NOT EXISTS citation_context_mention_idx
ON tarkka.citation_context (mention_id);

CREATE TABLE IF NOT EXISTS tarkka.citation_resolution (
    reference_id uuid PRIMARY KEY
    REFERENCES tarkka.bibliographic_reference (reference_id) ON DELETE CASCADE,
    resolution_id uuid NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('unresolved', 'resolved', 'ambiguous', 'rejected')),
    work_id uuid REFERENCES tarkka.work (work_id) ON DELETE RESTRICT,
    candidate_work_ids uuid[] NOT NULL DEFAULT '{}',
    resolver text CHECK (resolver IS NULL OR length(btrim(resolver)) > 0),
    source_observation_id uuid,
    resolved_at timestamptz NOT NULL,
    CHECK (
        (
            status = 'resolved'
            AND work_id IS NOT NULL
            AND cardinality(candidate_work_ids) = 0
        ) OR (
            status = 'ambiguous'
            AND work_id IS NULL
            AND cardinality(candidate_work_ids) >= 2
        ) OR (
            status IN ('unresolved', 'rejected')
            AND work_id IS NULL
            AND cardinality(candidate_work_ids) = 0
        )
    )
);

CREATE INDEX IF NOT EXISTS citation_resolution_work_idx
ON tarkka.citation_resolution (work_id)
WHERE work_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS tarkka.work_relation (
    relation_id uuid PRIMARY KEY,
    subject_work_id uuid NOT NULL REFERENCES tarkka.work (work_id) ON DELETE CASCADE,
    object_work_id uuid NOT NULL REFERENCES tarkka.work (work_id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (
        kind IN (
            'cites', 'is_version_of', 'is_preprint_of', 'is_correction_of',
            'is_retraction_of', 'uses_dataset', 'uses_software', 'supplements',
            'has_part', 'related'
        )
    ),
    basis text NOT NULL CHECK (basis IN ('native', 'reconstructed', 'inferred')),
    source_observation_id uuid,
    source_document_id uuid REFERENCES tarkka.document (document_id) ON DELETE RESTRICT,
    source_reference_id uuid,
    created_at timestamptz NOT NULL,
    CHECK (subject_work_id <> object_work_id OR kind = 'cites'),
    CHECK (source_reference_id IS NULL OR source_document_id IS NOT NULL),
    CHECK (
        source_observation_id IS NOT NULL
        OR source_document_id IS NOT NULL
        OR source_reference_id IS NOT NULL
    ),
    FOREIGN KEY (source_reference_id, source_document_id)
    REFERENCES tarkka.bibliographic_reference (reference_id, document_id)
    ON DELETE RESTRICT
);

-- UUID text is never empty, so coalesce provides NULLS-NOT-DISTINCT semantics
-- without requiring a PostgreSQL-version-specific UNIQUE NULLS NOT DISTINCT clause.
CREATE UNIQUE INDEX IF NOT EXISTS work_relation_logical_unique_idx
ON tarkka.work_relation (
    subject_work_id,
    object_work_id,
    kind,
    basis,
    coalesce(source_observation_id::text, ''),
    coalesce(source_document_id::text, ''),
    coalesce(source_reference_id::text, '')
);

CREATE INDEX IF NOT EXISTS work_relation_subject_idx
ON tarkka.work_relation (subject_work_id, kind);
CREATE INDEX IF NOT EXISTS work_relation_object_idx
ON tarkka.work_relation (object_work_id, kind);

COMMIT;
