BEGIN;

-- The claim document is stored explicitly so a citation context can be proven
-- document-local while evidence remains free to come from a separately acquired source.
CREATE UNIQUE INDEX IF NOT EXISTS citation_context_lineage_idx
ON tarkka.citation_context (context_id, document_id);
CREATE UNIQUE INDEX IF NOT EXISTS research_extraction_document_lineage_idx
ON tarkka.research_extraction (extraction_id, document_id);

CREATE TABLE IF NOT EXISTS tarkka.evidence_relation (
    relation_id uuid PRIMARY KEY,
    claim_id uuid NOT NULL,
    claim_document_id uuid NOT NULL,
    evidence_id uuid,
    citation_context_id uuid,
    kind text NOT NULL CHECK (kind IN (
        'supports', 'contradicts', 'partially_supports', 'qualifies',
        'mentions', 'no_evidence', 'uncertain'
    )),
    verifier_name text NOT NULL CHECK (length(btrim(verifier_name)) > 0),
    verifier_version text NOT NULL CHECK (length(btrim(verifier_version)) > 0),
    confidence double precision NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    human_review_state text NOT NULL CHECK (human_review_state IN (
        'unreviewed', 'verified', 'corrected', 'rejected'
    )),
    reasoning_summary text CHECK (
        reasoning_summary IS NULL OR length(btrim(reasoning_summary)) > 0
    ),
    created_at timestamptz NOT NULL,
    CHECK (
        (kind = 'no_evidence' AND evidence_id IS NULL)
        OR (kind <> 'no_evidence' AND evidence_id IS NOT NULL)
    ),
    FOREIGN KEY (claim_id, claim_document_id)
    REFERENCES tarkka.research_extraction (extraction_id, document_id)
    ON DELETE CASCADE,
    FOREIGN KEY (evidence_id)
    REFERENCES tarkka.evidence (evidence_id) ON DELETE RESTRICT,
    FOREIGN KEY (citation_context_id, claim_document_id)
    REFERENCES tarkka.citation_context (context_id, document_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS evidence_relation_claim_idx
ON tarkka.evidence_relation (claim_id, relation_id);
CREATE INDEX IF NOT EXISTS evidence_relation_evidence_idx
ON tarkka.evidence_relation (evidence_id)
WHERE evidence_id IS NOT NULL;

CREATE OR REPLACE FUNCTION tarkka.validate_evidence_relation_claim()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    extraction_kind text;
BEGIN
    SELECT kind INTO extraction_kind
      FROM tarkka.research_extraction
     WHERE extraction_id = NEW.claim_id
       AND document_id = NEW.claim_document_id;
    IF extraction_kind IS DISTINCT FROM 'claim' THEN
        RAISE EXCEPTION 'evidence relation must reference a claim extraction';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS validate_evidence_relation_claim_trigger
ON tarkka.evidence_relation;
CREATE TRIGGER validate_evidence_relation_claim_trigger
BEFORE INSERT OR UPDATE OF claim_id, claim_document_id
ON tarkka.evidence_relation
FOR EACH ROW EXECUTE FUNCTION tarkka.validate_evidence_relation_claim();

CREATE OR REPLACE FUNCTION tarkka.reject_evidence_relation_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'evidence relations are immutable';
END;
$$;

DROP TRIGGER IF EXISTS evidence_relation_immutable_trigger
ON tarkka.evidence_relation;
CREATE TRIGGER evidence_relation_immutable_trigger
BEFORE UPDATE ON tarkka.evidence_relation
FOR EACH ROW EXECUTE FUNCTION tarkka.reject_evidence_relation_update();

COMMIT;
