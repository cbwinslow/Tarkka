BEGIN;

CREATE TABLE IF NOT EXISTS tarkka.extraction_run (
    run_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    extractor_name text NOT NULL,
    extractor_version text NOT NULL,
    contract_version text NOT NULL,
    model_provider text,
    model_name text,
    model_version text,
    extracted_at timestamptz NOT NULL,
    CHECK ((model_provider IS NULL AND model_name IS NULL AND model_version IS NULL)
        OR (model_provider IS NOT NULL AND model_name IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS tarkka.evidence (
    evidence_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES tarkka.extraction_run(run_id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    section_id uuid NOT NULL REFERENCES tarkka.section(section_id) ON DELETE CASCADE,
    passage_id uuid NOT NULL REFERENCES tarkka.passage(passage_id) ON DELETE CASCADE,
    passage_char_start integer NOT NULL CHECK (passage_char_start >= 0),
    passage_char_end integer NOT NULL CHECK (passage_char_end > passage_char_start),
    text text NOT NULL CHECK (length(text) > 0),
    confidence double precision NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    human_review_state text NOT NULL CHECK (human_review_state IN (
        'unreviewed', 'verified', 'corrected', 'rejected'
    )),
    reasoning_summary text,
    UNIQUE (run_id, passage_id, passage_char_start, passage_char_end)
);

CREATE TABLE IF NOT EXISTS tarkka.research_extraction (
    extraction_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES tarkka.extraction_run(run_id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN (
        'claim', 'hypothesis', 'method', 'dataset', 'variable',
        'model', 'metric', 'result', 'limitation'
    )),
    attribution text NOT NULL CHECK (attribution IN (
        'author_stated', 'extractor_inferred', 'synthesis'
    )),
    confidence double precision NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    human_review_state text NOT NULL CHECK (human_review_state IN (
        'unreviewed', 'verified', 'corrected', 'rejected'
    )),
    reasoning_summary text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tarkka.research_extraction_evidence (
    extraction_id uuid NOT NULL
        REFERENCES tarkka.research_extraction(extraction_id) ON DELETE CASCADE,
    evidence_id uuid NOT NULL REFERENCES tarkka.evidence(evidence_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (extraction_id, evidence_id),
    UNIQUE (extraction_id, ordinal)
);

CREATE INDEX IF NOT EXISTS evidence_document_idx
    ON tarkka.evidence(document_id, passage_id);

CREATE INDEX IF NOT EXISTS research_extraction_document_kind_idx
    ON tarkka.research_extraction(document_id, kind);

COMMIT;
