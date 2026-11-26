-- Compare changes as the caller of the REST RPC, including anonymous sessions
-- that own legacy files. The prior attachment role test provisions the bucket.
\set ON_ERROR_STOP on
SET ROLE authenticated;
SELECT set_config('test.jwt', '{"is_anonymous": false}', false);
DO $$
DECLARE
  u uuid := '3b000000-0000-4000-8000-000000000001';
  other_uid uuid := '3b000000-0000-4000-8000-000000000002';
  anchor uuid := '3b000000-0000-4000-8000-000000000003';
  p text := u::text || '/retired/é.pdf';
  empty_hash text := 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
  legacy_hash text := '905256d7e66e23e42435de6bcc517df70bcec4ca8649a4d6081faee7d33cc003';
  marker jsonb; original jsonb; published jsonb; item jsonb; op uuid;
BEGIN
  IF has_function_privilege('anon','public.tracker_attachment_export_marker()','execute')
    OR has_function_privilege('service_role','public.tracker_attachment_export_marker()','execute') THEN
    RAISE EXCEPTION 'unexpected export marker grant';
  END IF;
  PERFORM set_config('test.uid', u::text, false);
  marker := public.tracker_attachment_export_marker();
  IF marker->>'digest' IS DISTINCT FROM empty_hash OR (marker->>'count')::int IS DISTINCT FROM 0
    OR (marker->>'observedAt')::timestamptz IS DISTINCT FROM statement_timestamp() THEN
    RAISE EXCEPTION 'expected timestamped empty inventory';
  END IF;
  INSERT INTO storage.objects(bucket_id, name, metadata) VALUES
    ('tracker-attachments',u::text||'/retired/.emptyFolderPlaceholder','{"size":0}');
  INSERT INTO storage.objects(id,bucket_id,name,metadata,version,updated_at)
    VALUES(anchor,'tracker-attachments',p,'{"mimetype":"application/pdf","size":8,"eTag":"one"}','legacy-1','2026-01-01 00:00:00Z');
  original := public.tracker_attachment_export_marker();
  -- Known digest independently computed in JavaScript over UTF-8 and NUL separators.
  IF (original->>'count')::int IS DISTINCT FROM 1 OR original->>'digest' IS DISTINCT FROM legacy_hash THEN
    RAISE EXCEPTION 'legacy name, anchor revision or placeholder handling differs: %', original;
  END IF;
  INSERT INTO storage.objects(id,bucket_id,name,metadata,version,updated_at)
    VALUES('3b000000-0000-4000-8000-000000000004','tracker-attachments',u::text||'/active/bar.pdf',
           '{"mimetype":"application/pdf","size":8,"eTag":"one"}','legacy-1','2026-01-01 00:00:00Z');
  marker := public.tracker_attachment_export_marker();
  IF (marker->>'count')::int IS DISTINCT FROM 2 OR marker->>'digest' IS DISTINCT FROM
    '11bdabccd0a9eed173326c2ff19ffa6982cfdeb484e115213010cc2f317f8118' THEN RAISE EXCEPTION 'independent two-file digest differs'; END IF;
  DELETE FROM storage.objects WHERE bucket_id='tracker-attachments' AND name=u::text||'/active/bar.pdf';
  PERFORM set_config('test.uid', other_uid::text, false);
  IF public.tracker_attachment_export_marker()->>'digest' IS DISTINCT FROM empty_hash THEN
    RAISE EXCEPTION 'empty second account inherited a marker';
  END IF;
  INSERT INTO storage.objects(bucket_id,name,metadata)
    VALUES('tracker-attachments',other_uid::text||'/other.pdf','{"size":8}');
  PERFORM set_config('test.uid', u::text, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  IF public.tracker_attachment_export_marker()->>'digest' IS DISTINCT FROM legacy_hash THEN
    RAISE EXCEPTION 'another account affected the marker or a guest lost its old file';
  END IF;
  PERFORM set_config('test.jwt', '{"is_anonymous": false}', false);
  item := public.resolve_tracker_attachment_versions(ARRAY[p])->p;
  op := public.stage_tracker_attachment(p,item->>'revision','application/pdf',8);
  INSERT INTO storage.objects(bucket_id,name,metadata,version)
    VALUES('tracker-attachment-versions',u::text||'/'||op::text,'{"mimetype":"application/pdf","size":8}',gen_random_uuid()::text);
  IF public.tracker_attachment_export_marker()->>'digest' IS DISTINCT FROM legacy_hash THEN
    RAISE EXCEPTION 'unpublished bytes changed the marker';
  END IF;
  IF NOT public.publish_tracker_attachment(op) THEN RAISE EXCEPTION 'fixture publication failed'; END IF;
  published := public.tracker_attachment_export_marker();
  IF published->>'digest' IS NOT DISTINCT FROM legacy_hash OR (published->>'count')::int IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'same-size published replacement escaped the marker';
  END IF;
  item := public.resolve_tracker_attachment_versions(ARRAY[p])->p;
  IF NOT public.delete_tracker_attachment(p,item->>'revision') THEN RAISE EXCEPTION 'fixture deletion failed'; END IF;
  IF public.tracker_attachment_export_marker()->>'digest' IS DISTINCT FROM empty_hash THEN
    RAISE EXCEPTION 'tombstoned anchor contributed to the marker';
  END IF;
  DELETE FROM storage.objects WHERE bucket_id='tracker-attachments' AND name=p;
  INSERT INTO storage.objects(bucket_id,name,metadata,version,updated_at)
    VALUES('tracker-attachments',p,'{"mimetype":"application/pdf","size":8,"eTag":"one"}','legacy-1','2026-01-01 00:00:00Z');
  marker := public.tracker_attachment_export_marker();
  IF (marker->>'count')::int IS DISTINCT FROM 1 OR marker->>'digest' IN (legacy_hash, published->>'digest') THEN
    RAISE EXCEPTION 'recreated anchor ID escaped the marker';
  END IF;
END $$;
RESET ROLE;
\echo PASS tracker_attachment_export_marker_test
