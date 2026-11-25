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

-- Exercise the metadata mutations issued by Storage, including its upsert.
-- A content write either swaps the same revision atomically or leaves it intact.
BEGIN;
CREATE UNIQUE INDEX test_tracker_attachment_key ON storage.objects(bucket_id, name);
DO $$
DECLARE
  uid text := '3a000000-0000-4000-8000-000000000002';
  obj uuid := gen_random_uuid();
  path text := uid || '/opp-1/guarded.pdf';
  meta jsonb := '{"mimetype":"application/pdf","eTag":"first"}';
  guard jsonb := jsonb_build_object('ofe_replace', jsonb_build_object('id', obj, 'version','v1','mime','application/pdf'));
BEGIN
  INSERT INTO storage.objects(id, bucket_id, name, version, metadata, user_metadata)
    VALUES(obj,'tracker-attachments',path,'v1',meta,'{"label":"saved"}');
  IF public.tracker_attachment_replace_version(path,obj,'first',null,'application/pdf') IS DISTINCT FROM 'v1'
     OR public.tracker_attachment_replace_version(path,obj,'stale',null,'application/pdf') IS NOT NULL THEN
    RAISE EXCEPTION 'wrong replacement preflight';
  END IF;
  PERFORM set_config('test.jwt','{"is_anonymous":true}',true);
  IF public.tracker_attachment_replace_version(path,obj,'first',null,'application/pdf') IS NOT NULL THEN
    RAISE EXCEPTION 'guest replacement preflight';
  END IF;
  PERFORM set_config('test.jwt','{"is_anonymous":false}',true);
  BEGIN
    UPDATE storage.objects SET version='wrong-type',metadata='{"mimetype":"text/plain"}',user_metadata=guard WHERE id=obj;
    RAISE EXCEPTION 'replacement changed the MIME type of the original key';
  EXCEPTION WHEN serialization_failure THEN NULL; END;
  PERFORM set_config('test.uid',gen_random_uuid()::text,true);
  IF public.tracker_attachment_replace_version(path,obj,'first',null,'application/pdf') IS NOT NULL THEN
    RAISE EXCEPTION 'cross owner preflight';
  END IF;
  PERFORM set_config('test.uid',uid,true);
  INSERT INTO storage.objects(bucket_id, name, version, metadata, user_metadata)
    VALUES('tracker-attachments',path,'v2',meta || '{"eTag":"second"}',guard)
    ON CONFLICT(bucket_id,name) DO UPDATE SET version=EXCLUDED.version, metadata=EXCLUDED.metadata, user_metadata=EXCLUDED.user_metadata;
  IF NOT EXISTS (SELECT 1 FROM storage.objects WHERE id=obj AND version='v2' AND metadata->>'eTag'='second'
                 AND user_metadata='{"label":"saved"}') THEN RAISE EXCEPTION 'valid replacement lost identity/metadata'; END IF;
  BEGIN
    UPDATE storage.objects SET version='stale-write',user_metadata=guard WHERE id=obj;
    RAISE EXCEPTION 'stale replacement accepted';
  EXCEPTION WHEN serialization_failure THEN NULL; END;
  DELETE FROM storage.objects WHERE id=obj;
  BEGIN
    INSERT INTO storage.objects(bucket_id,name,version,metadata,user_metadata)
      VALUES('tracker-attachments',path,'recreated',meta,guard)
      ON CONFLICT(bucket_id,name) DO UPDATE SET version=EXCLUDED.version, user_metadata=EXCLUDED.user_metadata;
    RAISE EXCEPTION 'deleted destination was recreated';
  EXCEPTION WHEN serialization_failure THEN NULL; END;
  IF EXISTS(SELECT 1 FROM storage.objects WHERE name=path) THEN RAISE EXCEPTION 'deleted key returned'; END IF;
  INSERT INTO storage.objects(bucket_id,name,version,metadata) VALUES('tracker-attachments',path,'v1',meta);
  BEGIN
    UPDATE storage.objects SET version='different-person-file',user_metadata=guard WHERE name=path;
    RAISE EXCEPTION 'new object at reused name overwritten';
  EXCEPTION WHEN serialization_failure THEN NULL; END;
  IF NOT EXISTS(SELECT 1 FROM storage.objects WHERE name=path AND id<>obj AND version='v1') THEN
    RAISE EXCEPTION 'recreated file changed on stale replace';
  END IF;
END $$;
ROLLBACK;
\echo PASS tracker_attachment_replacement
