-- The previous guard shipped briefly in source. Fresh installations never
-- install it. Remove only this project's named legacy triggers when already
-- present, so a preview that applied that migration can upgrade in place.
DO $$
DECLARE existing record;
BEGIN
  FOR existing IN SELECT t.tgname FROM pg_catalog.pg_trigger t
    JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
    WHERE t.tgrelid='storage.objects'::regclass AND NOT t.tgisinternal
    AND t.tgname IN ('tracker_attachment_reject_recreation','tracker_attachment_check_revision')
    AND p.pronamespace='public'::regnamespace AND p.proname='guard_tracker_attachment_replacement'
  LOOP
    EXECUTE format('DROP TRIGGER %I ON storage.objects',existing.tgname);
  END LOOP;
END $$;
DROP FUNCTION IF EXISTS public.guard_tracker_attachment_replacement();
DROP FUNCTION IF EXISTS public.tracker_attachment_replace_version(text,uuid,text,timestamptz,text);

-- The existing object identifies the logical attachment. Replacements write new
-- keys through the Storage API; published pointers and deletion receipts live here.
CREATE SCHEMA IF NOT EXISTS private;
CREATE TABLE private.tracker_attachment_edits (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL,
  path text,
  anchor_id uuid,
  expected_revision text,
  mime text,
  byte_size integer CHECK (byte_size BETWEEN 0 AND 5242880),
  state text NOT NULL DEFAULT 'staged' CHECK (state IN ('staged','current','retired','garbage')),
  physical_revision text,
  cleanup_after timestamptz NOT NULL DEFAULT now() + interval '1 day',
  CHECK (state='garbage' OR (path IS NOT NULL AND anchor_id IS NOT NULL AND expected_revision IS NOT NULL
    AND mime IS NOT NULL AND byte_size IS NOT NULL))
);
CREATE UNIQUE INDEX tracker_attachment_current ON private.tracker_attachment_edits(owner_id, path, anchor_id)
  WHERE state = 'current';
CREATE INDEX tracker_attachment_cleanup ON private.tracker_attachment_edits(cleanup_after);
CREATE INDEX tracker_attachment_owner_stage ON private.tracker_attachment_edits(owner_id, state);
CREATE TABLE private.tracker_attachment_deletions (
  owner_id uuid NOT NULL, path_hash bytea NOT NULL, anchor_id uuid NOT NULL,
  PRIMARY KEY (owner_id, path_hash, anchor_id)
);
REVOKE ALL ON private.tracker_attachment_edits, private.tracker_attachment_deletions FROM PUBLIC, anon, authenticated;
ALTER TABLE private.tracker_attachment_edits ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.tracker_attachment_deletions ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION private.tracker_object_revision(p_id uuid,p_version text,p_updated_at timestamptz,p_etag text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
  SELECT p_id::text || ':' || coalesce(p_version, '') || ':' ||
         coalesce(extract(epoch FROM p_updated_at)::text, '') || ':' || coalesce(p_etag,'')
$$;

CREATE FUNCTION private.tracker_attachment_view(u uuid, p text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE a storage.objects; physical storage.objects; edit private.tracker_attachment_edits; rev text;
BEGIN
  IF u IS NULL OR split_part(p,'/',1) <> u::text THEN RAISE EXCEPTION 'invalid attachment owner'; END IF;
  SELECT * INTO a FROM storage.objects WHERE bucket_id='tracker-attachments' AND name=p;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM private.tracker_attachment_deletions
    WHERE owner_id=u AND path_hash=sha256(convert_to(p,'UTF8')) AND anchor_id=a.id) THEN RETURN NULL; END IF;
  SELECT * INTO edit FROM private.tracker_attachment_edits
    WHERE owner_id=u AND path=p AND anchor_id=a.id AND state='current';
  IF FOUND THEN
    SELECT * INTO physical FROM storage.objects WHERE bucket_id='tracker-attachment-versions'
      AND name=u::text||'/'||edit.id::text;
    IF NOT FOUND OR private.tracker_object_revision(physical.id,physical.version,physical.updated_at,physical.metadata->>'eTag') IS DISTINCT FROM edit.physical_revision
      THEN RAISE EXCEPTION 'attachment version unavailable'; END IF;
    rev := 'v:'||edit.id::text;
  ELSE
    physical := a; rev := 'o:'||private.tracker_object_revision(a.id,a.version,a.updated_at,a.metadata->>'eTag');
  END IF;
  RETURN jsonb_build_object('path',p,'anchorId',a.id,'revision',rev,'storageBucket',physical.bucket_id,
    'storagePath',physical.name,'sizeBytes',coalesce((physical.metadata->>'size')::bigint,0),
    'mimeType',coalesce(physical.metadata->>'mimetype','application/octet-stream'),
    'etag',physical.metadata->>'eTag','updatedAt',physical.updated_at);
END $$;

CREATE FUNCTION public.resolve_tracker_attachment_versions(p_paths text[]) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE u uuid := auth.uid(); p text; result jsonb := '{}';
BEGIN
  IF u IS NULL OR p_paths IS NULL OR cardinality(p_paths)>100 THEN RAISE EXCEPTION 'invalid attachment request'; END IF;
  FOREACH p IN ARRAY p_paths LOOP
    IF p IS NULL OR p='' THEN RAISE EXCEPTION 'invalid attachment path'; END IF;
    result := result || jsonb_build_object(p,private.tracker_attachment_view(u,p));
  END LOOP;
  RETURN result;
END $$;

CREATE FUNCTION public.stage_tracker_attachment(p_path text, p_revision text, p_mime text, p_size integer) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE u uuid:=auth.uid(); current_view jsonb; op uuid;
BEGIN
  IF u IS NULL OR (auth.jwt()->>'is_anonymous')::boolean IS TRUE THEN RAISE EXCEPTION 'sign in required'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(u::text, 717));
  current_view := private.tracker_attachment_view(u,p_path);
  IF current_view IS NULL OR current_view->>'revision' IS DISTINCT FROM p_revision THEN RETURN NULL; END IF;
  IF p_mime IS NULL OR p_mime IS DISTINCT FROM current_view->>'mimeType' OR p_size NOT BETWEEN 0 AND 5242880
    OR NOT EXISTS (SELECT 1 FROM storage.buckets WHERE id='tracker-attachment-versions'
      AND NOT public AND file_size_limit=5242880 AND p_mime=ANY(allowed_mime_types))
    THEN RAISE EXCEPTION 'invalid replacement'; END IF;
  IF (SELECT count(*) FROM private.tracker_attachment_edits WHERE owner_id=u AND state='staged' AND cleanup_after>now())>=32
    THEN RAISE EXCEPTION 'pending attachment limit'; END IF;
  INSERT INTO private.tracker_attachment_edits(owner_id,path,anchor_id,expected_revision,mime,byte_size)
    VALUES(u,p_path,(current_view->>'anchorId')::uuid,p_revision,p_mime,p_size) RETURNING id INTO op;
  RETURN op;
END $$;

CREATE FUNCTION public.publish_tracker_attachment(p_id uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE u uuid:=auth.uid(); e private.tracker_attachment_edits; obj storage.objects; v jsonb;
BEGIN
  IF u IS NULL OR (auth.jwt()->>'is_anonymous')::boolean IS TRUE THEN RAISE EXCEPTION 'sign in required'; END IF;
  SELECT * INTO e FROM private.tracker_attachment_edits WHERE id=p_id AND owner_id=u;
  IF NOT FOUND THEN RETURN false; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(e.path, 279));
  SELECT * INTO e FROM private.tracker_attachment_edits WHERE id=p_id FOR UPDATE;
  v:=private.tracker_attachment_view(u,e.path);
  IF e.state='current' THEN RETURN coalesce(v->>'revision'='v:'||e.id::text,false); END IF;
  IF e.state<>'staged' OR e.cleanup_after<=now() THEN RETURN false; END IF;
  IF v IS NULL OR v->>'revision' IS DISTINCT FROM e.expected_revision THEN
    UPDATE private.tracker_attachment_edits SET state='retired' WHERE id=p_id; RETURN false;
  END IF;
  SELECT * INTO obj FROM storage.objects WHERE bucket_id='tracker-attachment-versions' AND name=u::text||'/'||p_id::text;
  IF NOT FOUND OR obj.metadata->>'mimetype' IS DISTINCT FROM e.mime OR (obj.metadata->>'size')::bigint IS DISTINCT FROM e.byte_size
    THEN RAISE EXCEPTION 'uploaded attachment unavailable'; END IF;
  UPDATE private.tracker_attachment_edits SET state='retired',cleanup_after=now()+interval '1 day'
    WHERE owner_id=u AND path=e.path AND anchor_id=e.anchor_id AND state='current';
  UPDATE private.tracker_attachment_edits SET state='current',physical_revision=private.tracker_object_revision(obj.id,obj.version,obj.updated_at,obj.metadata->>'eTag')
    WHERE id=p_id;
  RETURN true;
END $$;

CREATE FUNCTION public.delete_tracker_attachment(p_path text,p_revision text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE u uuid:=auth.uid(); v jsonb;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_path,279));
  v:=private.tracker_attachment_view(u,p_path);
  IF v IS NULL OR v->>'revision' IS DISTINCT FROM p_revision THEN RETURN false; END IF;
  INSERT INTO private.tracker_attachment_deletions VALUES (u,sha256(convert_to(p_path,'UTF8')),(v->>'anchorId')::uuid);
  UPDATE private.tracker_attachment_edits SET state='retired',cleanup_after=now()+interval '1 day'
    WHERE owner_id=u AND path=p_path AND anchor_id=(v->>'anchorId')::uuid AND state='current';
  RETURN true;
END $$;

-- Storage batch DELETE runs with the caller's RLS. Once a path has had a
-- tombstone, an old or delayed DELETE can only remove a tombstoned incarnation.
CREATE FUNCTION public.tracker_anchor_removable(p_path text,p_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT split_part(p_path,'/',1)=auth.uid()::text AND (
    EXISTS(SELECT 1 FROM private.tracker_attachment_deletions WHERE owner_id=auth.uid() AND path_hash=sha256(convert_to(p_path,'UTF8')) AND anchor_id=p_id)
    OR NOT EXISTS(SELECT 1 FROM private.tracker_attachment_deletions WHERE owner_id=auth.uid() AND path_hash=sha256(convert_to(p_path,'UTF8'))))
$$;
CREATE POLICY tracker_delete_incarnation ON storage.objects AS RESTRICTIVE FOR DELETE TO authenticated
  USING (bucket_id<>'tracker-attachments' OR public.tracker_anchor_removable(name,id));

CREATE FUNCTION public.tracker_version_access(p_name text,p_write boolean) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (SELECT 1 FROM private.tracker_attachment_edits e WHERE owner_id=auth.uid()
    AND p_name=owner_id::text||'/'||id::text AND CASE WHEN p_write THEN
      e.state='staged' AND e.cleanup_after>now() AND coalesce((auth.jwt()->>'is_anonymous')::boolean,false)=false
    ELSE e.state='current' AND EXISTS (SELECT 1 FROM storage.objects a
      WHERE a.bucket_id='tracker-attachments' AND a.name=e.path AND a.id=e.anchor_id) END)
$$;
CREATE POLICY tracker_version_create ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (bucket_id='tracker-attachment-versions' AND public.tracker_version_access(name,true));
CREATE POLICY tracker_version_read ON storage.objects FOR SELECT TO authenticated
  USING (bucket_id='tracker-attachment-versions' AND public.tracker_version_access(name,false));

-- Retired immutable keys stay valid for the five-minute signed URL lifetime.
-- A late upload after an ambiguous network timeout is rediscovered by its key.
CREATE FUNCTION public.claim_tracker_attachment_cleanup(p_limit integer) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $$
  WITH candidates AS (
    SELECT e.id FROM private.tracker_attachment_edits e WHERE
      (e.state IN ('staged','retired') AND e.cleanup_after<=now())
      OR (e.state='current' AND e.cleanup_after<=now() AND NOT EXISTS (SELECT 1 FROM storage.objects a
        WHERE a.bucket_id='tracker-attachments' AND a.name=e.path AND a.id=e.anchor_id))
      OR (e.state='garbage' AND e.cleanup_after<=now() AND EXISTS (SELECT 1 FROM storage.objects o
        WHERE o.bucket_id='tracker-attachment-versions' AND o.name=e.owner_id::text||'/'||e.id::text))
    ORDER BY e.cleanup_after LIMIT least(greatest(p_limit,0),20) FOR UPDATE OF e SKIP LOCKED
  ), claimed AS (
    UPDATE private.tracker_attachment_edits e SET state='garbage', path=NULL, anchor_id=NULL,
      expected_revision=NULL, mime=NULL, byte_size=NULL, physical_revision=NULL, cleanup_after=now()+interval '10 minutes'
      FROM candidates c WHERE e.id=c.id RETURNING e.owner_id,e.id)
  SELECT jsonb_build_object('jobs',coalesce(jsonb_agg(jsonb_build_object('owner_id',owner_id,'id',id)), '[]'::jsonb)) FROM claimed
$$;
REVOKE ALL ON FUNCTION private.tracker_object_revision(uuid,text,timestamptz,text), private.tracker_attachment_view(uuid,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.resolve_tracker_attachment_versions(text[]), public.stage_tracker_attachment(text,text,text,integer),
 public.publish_tracker_attachment(uuid), public.delete_tracker_attachment(text,text), public.tracker_anchor_removable(text,uuid),
 public.tracker_version_access(text,boolean), public.claim_tracker_attachment_cleanup(integer) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.resolve_tracker_attachment_versions(text[]), public.stage_tracker_attachment(text,text,text,integer),
 public.publish_tracker_attachment(uuid), public.delete_tracker_attachment(text,text), public.tracker_anchor_removable(text,uuid),
 public.tracker_version_access(text,boolean) TO authenticated;
GRANT EXECUTE ON FUNCTION public.claim_tracker_attachment_cleanup(integer) TO service_role;

CREATE FUNCTION public.pending_tracker_attachment_deletions(p_paths text[]) RETURNS text[]
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF auth.uid() IS NULL OR p_paths IS NULL OR cardinality(p_paths)>100
    OR EXISTS(SELECT 1 FROM unnest(p_paths) p WHERE split_part(p,'/',1) IS DISTINCT FROM auth.uid()::text)
    THEN RAISE EXCEPTION 'invalid attachment request'; END IF;
  RETURN ARRAY(SELECT a.name FROM storage.objects a JOIN private.tracker_attachment_deletions d
    ON d.owner_id=auth.uid() AND d.path_hash=sha256(convert_to(a.name,'UTF8')) AND d.anchor_id=a.id
    WHERE a.bucket_id='tracker-attachments' AND a.name=ANY(p_paths));
END $$;
REVOKE ALL ON FUNCTION public.pending_tracker_attachment_deletions(text[]) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.pending_tracker_attachment_deletions(text[]) TO authenticated;
