BEGIN;

-- Composite uniqueness supports lineage-preserving foreign keys below.
CREATE UNIQUE INDEX IF NOT EXISTS passage_lineage_idx
    ON tarkka.passage(passage_id, document_id, section_id);

CREATE TABLE IF NOT EXISTS tarkka.extraction_run (
    run_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES tarkka.document(document_id) ON DELETE CASCADE,
    extractor_name text NOT NULL CHECK (length(btrim(extractor_name)) > 0),
    extractor_version text NOT NULL CHECK (length(btrim(extractor_version)) > 0),
    contract_version text NOT NULL CHECK (length(btrim(contract_version)) > 0),
    model_provider text,
    model_name text,
    model_version text,
    extracted_at timestamptz NOT NULL,
    CHECK ((model_provider IS NULL AND model_name IS NULL AND model_version IS NULL)
        OR (model_provider IS NOT NULL AND model_name IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS extraction_run_lineage_idx
    ON tarkka.extraction_run(run_id, document_id);

CREATE INDEX IF NOT EXISTS extraction_run_document_idx
    ON tarkka.extraction_run(document_id);

CREATE TABLE IF NOT EXISTS tarkka.evidence (
    evidence_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    document_id uuid NOT NULL,
    section_id uuid NOT NULL,
    passage_id uuid NOT NULL,
    passage_char_start integer NOT NULL CHECK (passage_char_start >= 0),
    passage_char_end integer NOT NULL CHECK (passage_char_end > passage_char_start),
    text text NOT NULL CHECK (length(text) > 0),
    confidence double precision NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    human_review_state text NOT NULL CHECK (human_review_state IN (
        'unreviewed', 'verified', 'corrected', 'rejected'
    )),
    reasoning_summary text,
    FOREIGN KEY (run_id, document_id)
        REFERENCES tarkka.extraction_run(run_id, document_id) ON DELETE CASCADE,
    FOREIGN KEY (passage_id, document_id, section_id)
        REFERENCES tarkka.passage(passage_id, document_id, section_id) ON DELETE CASCADE,
    UNIQUE (run_id, passage_id, passage_char_start, passage_char_end)
);

CREATE UNIQUE INDEX IF NOT EXISTS evidence_lineage_idx
    ON tarkka.evidence(evidence_id, run_id, document_id);

CREATE INDEX IF NOT EXISTS evidence_document_idx
    ON tarkka.evidence(document_id, passage_id);

CREATE INDEX IF NOT EXISTS evidence_run_idx
    ON tarkka.evidence(run_id);

CREATE TABLE IF NOT EXISTS tarkka.research_extraction (
    extraction_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    document_id uuid NOT NULL,
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
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (run_id, document_id)
        REFERENCES tarkka.extraction_run(run_id, document_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS research_extraction_lineage_idx
    ON tarkka.research_extraction(extraction_id, run_id, document_id);

CREATE INDEX IF NOT EXISTS research_extraction_document_kind_idx
    ON tarkka.research_extraction(document_id, kind);

CREATE INDEX IF NOT EXISTS research_extraction_run_idx
    ON tarkka.research_extraction(run_id);

CREATE TABLE IF NOT EXISTS tarkka.research_extraction_evidence (
    extraction_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    run_id uuid NOT NULL,
    document_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (extraction_id, evidence_id),
    UNIQUE (extraction_id, ordinal),
    FOREIGN KEY (extraction_id, run_id, document_id)
        REFERENCES tarkka.research_extraction(extraction_id, run_id, document_id)
        ON DELETE CASCADE,
    FOREIGN KEY (evidence_id, run_id, document_id)
        REFERENCES tarkka.evidence(evidence_id, run_id, document_id)
        ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION tarkka.validate_evidence_source()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    passage_text text;
    section_document_id uuid;
BEGIN
    SELECT p.text, s.document_id
      INTO passage_text, section_document_id
      FROM tarkka.passage AS p
      JOIN tarkka.section AS s ON s.section_id = p.section_id
     WHERE p.passage_id = NEW.passage_id
       AND p.document_id = NEW.document_id
       AND p.section_id = NEW.section_id;

    IF passage_text IS NULL OR section_document_id <> NEW.document_id THEN
        RAISE EXCEPTION 'evidence does not resolve to normalized passage lineage';
    END IF;
    IF NEW.passage_char_end > char_length(passage_text) THEN
        RAISE EXCEPTION 'evidence range is outside normalized passage';
    END IF;
    IF substring(
        passage_text
        FROM NEW.passage_char_start + 1
        FOR NEW.passage_char_end - NEW.passage_char_start
    ) <> NEW.text THEN
        RAISE EXCEPTION 'evidence text does not match normalized passage span';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS validate_evidence_source_trigger ON tarkka.evidence;
CREATE TRIGGER validate_evidence_source_trigger
BEFORE INSERT OR UPDATE OF document_id, section_id, passage_id,
    passage_char_start, passage_char_end, text
ON tarkka.evidence
FOR EACH ROW EXECUTE FUNCTION tarkka.validate_evidence_source();

CREATE OR REPLACE FUNCTION tarkka.ensure_extraction_has_evidence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_id uuid;
BEGIN
    target_id := COALESCE(NEW.extraction_id, OLD.extraction_id);
    IF EXISTS (
        SELECT 1 FROM tarkka.research_extraction
        WHERE extraction_id = target_id
    ) AND NOT EXISTS (
        SELECT 1 FROM tarkka.research_extraction_evidence
        WHERE extraction_id = target_id
    ) THEN
        RAISE EXCEPTION 'research extraction must retain at least one evidence link';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS extraction_requires_evidence_trigger
    ON tarkka.research_extraction;
CREATE CONSTRAINT TRIGGER extraction_requires_evidence_trigger
AFTER INSERT OR UPDATE OF run_id, document_id ON tarkka.research_extraction
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION tarkka.ensure_extraction_has_evidence();

DROP TRIGGER IF EXISTS evidence_link_delete_guard_trigger
    ON tarkka.research_extraction_evidence;
CREATE CONSTRAINT TRIGGER evidence_link_delete_guard_trigger
AFTER DELETE ON tarkka.research_extraction_evidence
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION tarkka.ensure_extraction_has_evidence();

COMMIT;
