-- 20261011090000: a guest (is_anonymous JWT) cannot add a tracker attachment,
-- a signed-in account can, and the guest can still read and delete what it
-- already has. Platform stubs (test.uid/test.jwt); no Storage bytes or HTTP.
\set ON_ERROR_STOP on
SET client_min_messages = warning;
GRANT USAGE ON SCHEMA storage TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON storage.objects TO authenticated;
-- A file the guest uploaded before the gate existed.
INSERT INTO storage.objects(bucket_id, name) VALUES
  ('tracker-attachments', '3a000000-0000-4000-8000-000000000001/opp-1/old.pdf');
SET ROLE authenticated;

SELECT set_config('test.uid', '3a000000-0000-4000-8000-000000000001', false);
SELECT set_config('test.jwt', '{"is_anonymous": true}', false);
DO $$
BEGIN
  BEGIN
    INSERT INTO storage.objects(bucket_id, name) VALUES
      ('tracker-attachments', '3a000000-0000-4000-8000-000000000001/opp-1/new.pdf');
    RAISE EXCEPTION 'TEST FAIL attachments-guest: a guest upload was accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  IF (SELECT count(*) FROM storage.objects WHERE bucket_id = 'tracker-attachments') <> 1 THEN
    RAISE EXCEPTION 'TEST FAIL attachments-guest: a guest can no longer read its existing file';
  END IF;
  DELETE FROM storage.objects WHERE name LIKE '%/old.pdf';
  IF EXISTS (SELECT 1 FROM storage.objects WHERE name LIKE '%/old.pdf') THEN
    RAISE EXCEPTION 'TEST FAIL attachments-guest: a guest cannot delete its existing file';
  END IF;
END $$;

SELECT set_config('test.uid', '3a000000-0000-4000-8000-000000000002', false);
SELECT set_config('test.jwt', '{"is_anonymous": false}', false);
DO $$
BEGIN
  INSERT INTO storage.objects(bucket_id, name) VALUES
    ('tracker-attachments', '3a000000-0000-4000-8000-000000000002/opp-1/new.pdf');
  BEGIN
    INSERT INTO storage.objects(bucket_id, name) VALUES
      ('tracker-attachments', '3a000000-0000-4000-8000-000000000001/opp-1/other.pdf');
    RAISE EXCEPTION 'TEST FAIL attachments-guest: an account wrote under another uid';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
-- A session whose JWT carries no claim at all is an account, not a guest.
SELECT set_config('test.jwt', '{}', false);
INSERT INTO storage.objects(bucket_id, name) VALUES
  ('tracker-attachments', '3a000000-0000-4000-8000-000000000002/opp-2/no-claim.pdf');
RESET ROLE;
\echo PASS tracker_attachments_guest_test
