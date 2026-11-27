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

-- Future database rebuilds and previously upgraded previews must not retain
-- application triggers on Supabase-managed storage objects.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='storage.objects'::regclass
    AND tgname IN ('tracker_attachment_reject_recreation','tracker_attachment_check_revision')) THEN
    RAISE EXCEPTION 'unexpected retired tracker storage trigger';
  END IF;
END $$;

-- The bucket is provisioned by an administrator. Every following storage
-- operation and application RPC runs with the actual signed-in client role.
INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
  VALUES ('tracker-attachment-versions','tracker-attachment-versions',false,5242880,ARRAY['application/pdf'])
  ON CONFLICT (id) DO NOTHING;
SET ROLE authenticated;
SELECT set_config('test.jwt', '{"is_anonymous": false}', false);
DO $$
DECLARE u uuid:='3a000000-0000-4000-8000-000000000002'; a uuid:=gen_random_uuid();
 p text:=u::text||'/opp-2/revision.pdf'; op uuid; other_op uuid; initial jsonb; selected jsonb;
BEGIN
  PERFORM set_config('test.uid',u::text,false);
  INSERT INTO storage.objects(id,bucket_id,name,metadata,version)
    VALUES (a,'tracker-attachments',p,'{"mimetype":"application/pdf","size":8}',gen_random_uuid()::text);
  initial:=public.resolve_tracker_attachment_versions(ARRAY[p])->p;
  op:=public.stage_tracker_attachment(p,initial->>'revision','application/pdf',9);
  other_op:=public.stage_tracker_attachment(p,initial->>'revision','application/pdf',9);
  IF op=other_op OR op IS NULL OR other_op IS NULL THEN RAISE EXCEPTION 'expected two distinct private keys'; END IF;
  INSERT INTO storage.objects(bucket_id,name,metadata,version)
    VALUES('tracker-attachment-versions',u::text||'/'||op::text,'{"mimetype":"application/pdf","size":9}',gen_random_uuid()::text);
  IF NOT public.publish_tracker_attachment(op) OR public.publish_tracker_attachment(other_op)
    THEN RAISE EXCEPTION 'expected only one publication for a selected revision'; END IF;
  selected:=public.resolve_tracker_attachment_versions(ARRAY[p])->p;
  IF selected->>'storageBucket'<>'tracker-attachment-versions' OR selected->>'anchorId'<>a::text
    OR selected->>'revision' IS NOT DISTINCT FROM initial->>'revision' OR (selected->>'sizeBytes')::int<>9
    THEN RAISE EXCEPTION 'unexpected published attachment'; END IF;
  IF public.delete_tracker_attachment(p,initial->>'revision') THEN RAISE EXCEPTION 'stale delete was accepted'; END IF;
  IF NOT public.delete_tracker_attachment(p,selected->>'revision') THEN RAISE EXCEPTION 'selected delete was refused'; END IF;
  IF (public.resolve_tracker_attachment_versions(ARRAY[p])->p) IS DISTINCT FROM 'null'::jsonb
    OR NOT public.tracker_anchor_removable(p,a) OR public.tracker_anchor_removable(p,gen_random_uuid())
    THEN RAISE EXCEPTION 'expected deletion of one selected incarnation'; END IF;
END $$;
RESET ROLE;
