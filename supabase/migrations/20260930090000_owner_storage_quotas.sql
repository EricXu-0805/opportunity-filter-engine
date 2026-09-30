-- Per-account storage quotas for user-reported PDFs and private imports.
-- Both checks run after material_user() has taken the owner advisory lock, so
-- concurrent requests from one account cannot each pass a stale count.
-- SQLSTATE 54000 is the existing "too large" class for these RPC families.

-- Live = staged or ready. Created-in-24h also counts deleted rows: a
-- delete/re-upload loop would otherwise refill Storage faster than cleanup
-- removes the revoked objects.
CREATE FUNCTION private.material_quota(p_owner uuid,p_kind text,p_event uuid,p_byte_length bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE live_count bigint; live_bytes numeric; event_count bigint; recent_count bigint;
BEGIN
 SELECT count(*) FILTER (WHERE status IN ('staged','ready')),
   coalesce(sum(byte_length) FILTER (WHERE status IN ('staged','ready')),0),
   count(*) FILTER (WHERE status IN ('staged','ready') AND artifact_kind=p_kind
     AND (CASE WHEN p_kind='contact' THEN contact_event_id ELSE application_event_id END)=p_event),
   count(*) FILTER (WHERE created_at>clock_timestamp()-interval '24 hours')
   INTO live_count,live_bytes,event_count,recent_count
   FROM public.material_artifacts WHERE owner_id=p_owner;
 IF live_count>=100 OR live_bytes+p_byte_length>268435456 OR event_count>=10 OR recent_count>=30 THEN
   RAISE EXCEPTION 'material_quota_exceeded' USING ERRCODE='54000'; END IF;
END;
$$;
REVOKE ALL ON FUNCTION private.material_quota(uuid,text,uuid,bigint) FROM PUBLIC,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION private.stage_material(p_kind text,p_expected_owner text,p_material_id uuid,p_record_id uuid,p_event_id uuid,
 p_opportunity_id text,p_filename text,p_byte_length bigint,p_sha256 text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; a public.material_artifacts%ROWTYPE; existed boolean; stamp timestamptz;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event_for_kind(p_kind,uid,p_event_id,p_opportunity_id);
 IF p_material_id IS NULL OR p_record_id IS NULL OR p_filename IS NULL OR length(p_filename) NOT BETWEEN 1 AND 200
   OR p_filename !~ '[^[:space:]]' OR p_filename ~ '[[:cntrl:]/\\]' OR p_filename !~* '\.pdf$'
   OR p_byte_length IS NULL OR p_byte_length NOT BETWEEN 1 AND 67108864 OR p_sha256 IS NULL OR p_sha256 !~ '^[0-9a-f]{64}$' THEN
   RAISE EXCEPTION USING MESSAGE='invalid_' || p_kind || '_material', ERRCODE='22023'; END IF;
 -- Global ID lock prevents cross-owner races without exposing another owner's
 -- row or changing the sorted owner locks used by merge.
 PERFORM pg_advisory_xact_lock(hashtext('ofe-material:' || p_material_id::text));
 SELECT * INTO a FROM public.material_artifacts WHERE material_id=p_material_id FOR UPDATE;
 existed:=FOUND;
 IF existed THEN
   IF a.owner_id IS DISTINCT FROM uid OR a.record_id IS DISTINCT FROM p_record_id OR a.artifact_kind IS DISTINCT FROM p_kind OR (CASE WHEN p_kind='contact' THEN a.contact_event_id ELSE a.application_event_id END) IS DISTINCT FROM p_event_id OR a.opportunity_id IS DISTINCT FROM p_opportunity_id THEN
     RAISE EXCEPTION USING MESSAGE=p_kind || '_material_conflict', ERRCODE='23505'; END IF;
   IF a.status='deleted' THEN RETURN jsonb_build_object('artifact',private.material_json(a),'upload',NULL,'replayed',true); END IF;
   IF a.filename IS DISTINCT FROM p_filename OR a.byte_length IS DISTINCT FROM p_byte_length OR a.declared_sha256 IS DISTINCT FROM p_sha256 THEN
     RAISE EXCEPTION USING MESSAGE=p_kind || '_material_conflict', ERRCODE='23505'; END IF;
   IF a.status='ready' THEN RETURN jsonb_build_object('artifact',private.material_json(a),'upload',NULL,'replayed',true); END IF;
   IF a.expires_at<=clock_timestamp() THEN a:=private.revoke_material(a.material_id); RETURN jsonb_build_object('artifact',private.material_json(a),'upload',NULL,'replayed',true); END IF;
 ELSE
   IF EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id=p_material_id)
     OR EXISTS(SELECT 1 FROM public.material_artifacts WHERE record_id=p_record_id) THEN RAISE EXCEPTION USING MESSAGE=p_kind || '_material_conflict', ERRCODE='23505'; END IF;
   -- Only a new material consumes quota; an exact retry above never does.
   PERFORM private.material_quota(uid,p_kind,p_event_id,p_byte_length);
   stamp:=clock_timestamp();
   INSERT INTO public.material_artifacts(material_id,record_id,owner_id,artifact_kind,application_event_id,contact_event_id,opportunity_id,status,filename,byte_length,
     declared_sha256,created_at,expires_at,stage_token,stage_session_id,authorized_until)
     VALUES(p_material_id,p_record_id,uid,p_kind,CASE WHEN p_kind='application' THEN p_event_id END,CASE WHEN p_kind='contact' THEN p_event_id END,p_opportunity_id,'staged',p_filename,p_byte_length,p_sha256,
       stamp,stamp+interval '24 hours',gen_random_uuid(),(auth.jwt()->>'session_id')::uuid,stamp+interval '10 minutes') RETURNING * INTO a;
 END IF;
 -- Server time bounds the upload and readback, which the backend finishes within
 -- its request timeout. The caller's access token may expire and be refreshed
 -- meanwhile; finalize still requires the stage session to be active.
 UPDATE public.material_artifacts SET stage_token=gen_random_uuid(),stage_session_id=(auth.jwt()->>'session_id')::uuid,
   authorized_until=least(expires_at,clock_timestamp()+interval '10 minutes') WHERE material_id=p_material_id RETURNING * INTO a;
 RETURN jsonb_build_object('artifact',private.material_json(a),'upload',jsonb_build_object('bucket','application-materials',
   'object_key',a.object_key,'stage_token',a.stage_token,'session_id',a.stage_session_id,'authorized_until',a.authorized_until),'replayed',existed);
EXCEPTION WHEN unique_violation THEN RAISE EXCEPTION USING MESSAGE=p_kind || '_material_conflict', ERRCODE='23505';
END;
$$;
REVOKE ALL ON FUNCTION private.stage_material(text,text,uuid,uuid,uuid,text,text,bigint,text) FROM PUBLIC,anon,authenticated,service_role;

-- Stored (post-compression) size is what fills the database disk. The new
-- value is measured uncompressed, which can only overestimate it.
CREATE OR REPLACE FUNCTION private.save_private_import_target(p_expected_owner text,p_id text,p_expected_revision bigint,p_opportunity jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid:=private.material_user(p_expected_owner); r public.private_import_targets%ROWTYPE; stamp timestamptz:=clock_timestamp();
 live_count bigint; other_bytes bigint;
BEGIN
 PERFORM private.validate_private_import(p_id,p_opportunity);
 IF p_expected_revision IS NULL OR p_expected_revision<0 OR p_expected_revision>9007199254740990 THEN RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023'; END IF;
 -- Serialize stable client IDs, including two owners racing the same ID.
 PERFORM pg_advisory_xact_lock(hashtext('ofe-private-target:'||p_id));
 SELECT * INTO r FROM public.private_import_targets WHERE id=p_id FOR UPDATE;
 IF FOUND THEN
  IF r.owner_id<>uid THEN RAISE EXCEPTION 'private_target_not_found' USING ERRCODE='P0002'; END IF;
  IF r.deleted_at IS NOT NULL THEN RAISE EXCEPTION 'private_target_deleted' USING ERRCODE='55000'; END IF;
  IF r.revision=p_expected_revision+1 AND r.opportunity=p_opportunity THEN RETURN jsonb_build_object('target',to_jsonb(r),'replayed',true); END IF;
  IF r.revision<>p_expected_revision THEN RAISE EXCEPTION 'private_target_conflict' USING ERRCODE='23505'; END IF;
 ELSIF p_expected_revision<>0 THEN RAISE EXCEPTION 'private_target_not_found' USING ERRCODE='P0002';
 END IF;
 SELECT count(*),coalesce(sum(pg_column_size(opportunity)),0) INTO live_count,other_bytes
   FROM public.private_import_targets WHERE owner_id=uid AND deleted_at IS NULL AND id<>p_id;
 IF live_count>=200 OR other_bytes+pg_column_size(p_opportunity)>67108864 THEN
  RAISE EXCEPTION 'private_target_quota_exceeded' USING ERRCODE='54000'; END IF;
 IF r.id IS NOT NULL THEN
  UPDATE public.private_import_targets SET opportunity=p_opportunity,revision=revision+1,updated_at=stamp WHERE id=p_id RETURNING * INTO r;
 ELSE
  INSERT INTO public.private_import_targets(id,owner_id,revision,opportunity,created_at,updated_at) VALUES(p_id,uid,1,p_opportunity,stamp,stamp) RETURNING * INTO r;
 END IF;
 RETURN jsonb_build_object('target',to_jsonb(r),'replayed',false);
END; $$;
