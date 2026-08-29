BEGIN;

ALTER TABLE tarkka.document
    ADD CONSTRAINT document_artifact_identity_unique UNIQUE (document_id, artifact_id);

CREATE TABLE tarkka.work_document_link (
    link_id uuid PRIMARY KEY,
    work_id uuid NOT NULL REFERENCES tarkka.work(work_id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    document_id uuid NOT NULL,
    linked_at timestamptz NOT NULL,
    CONSTRAINT work_document_link_document_artifact_fk
        FOREIGN KEY (document_id, artifact_id)
        REFERENCES tarkka.document(document_id, artifact_id)
        ON DELETE CASCADE
);

CREATE INDEX work_document_link_work_idx
    ON tarkka.work_document_link (work_id, link_id);

CREATE INDEX work_document_link_document_idx
    ON tarkka.work_document_link (document_id, link_id);

COMMIT;
