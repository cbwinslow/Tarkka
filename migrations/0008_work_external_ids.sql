BEGIN;

ALTER TABLE tarkka.work
ADD COLUMN IF NOT EXISTS external_ids jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN tarkka.work.external_ids IS
'Work metadata only; canonical identifier lookup uses tarkka.work_identifier.';

COMMIT;
