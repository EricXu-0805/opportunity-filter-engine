-- Share the private PDF lifecycle; keep contact declarations separate from
-- application declarations and preserve every existing application RPC receipt.
ALTER TABLE public.material_artifacts
 ADD COLUMN artifact_kind text NOT NULL DEFAULT 'application',
 ADD COLUMN contact_event_id uuid,
 ALTER COLUMN application_event_id DROP NOT NULL,
 ADD CONSTRAINT material_artifact_event_kind CHECK(
   (artifact_kind='application' AND application_event_id IS NOT NULL AND contact_event_id IS NULL)
   OR (artifact_kind='contact' AND contact_event_id IS NOT NULL AND application_event_id IS NULL));
CREATE TABLE public.contact_material_records(
 record_id uuid PRIMARY KEY,
 material_id uuid NOT NULL UNIQUE REFERENCES public.material_artifacts(material_id) ON DELETE CASCADE,
 owner_id uuid NOT NULL,
 contact_event_id uuid NOT NULL,
 opportunity_id text NOT NULL,
 recorded_at timestamptz NOT NULL,
 confirmation_source text NOT NULL DEFAULT 'user_reported' CHECK(confirmation_source='user_reported')
);
CREATE INDEX contact_material_records_page_idx ON public.contact_material_records(owner_id,contact_event_id,opportunity_id,recorded_at DESC,record_id DESC);
ALTER TABLE public.contact_material_records ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.contact_material_records FROM PUBLIC,anon,authenticated,service_role;
CREATE POLICY contact_material_records_own ON public.contact_material_records FOR SELECT TO authenticated
 USING(owner_id=(SELECT auth.uid()) AND private.target_resume_owner_active((SELECT auth.uid())));
COMMENT ON TABLE public.contact_material_records IS 'Later user-reported PDF attachment; not proof of email delivery. Immutable contact event remains unchanged.';

CREATE FUNCTION private.material_event_for_kind(p_kind text,p_owner uuid,p_event uuid,p_opportunity text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_kind='application' THEN PERFORM private.material_event(p_owner,p_event,p_opportunity); RETURN; END IF;
 IF p_kind IS DISTINCT FROM 'contact' OR p_event IS NULL OR p_opportunity IS NULL OR length(p_opportunity) NOT BETWEEN 1 AND 200 OR p_opportunity !~ '[^[:space:]]' THEN
   RAISE EXCEPTION 'invalid_contact_material' USING ERRCODE='22023'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=p_owner::text AND event_id=p_event AND opportunity_id=p_opportunity) THEN
   RAISE EXCEPTION 'contact_material_not_found' USING ERRCODE='P0002'; END IF;
END;
$$;
REVOKE ALL ON FUNCTION private.material_event_for_kind(text,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;

-- This helper does not add a receipt key to old application responses.


CREATE OR REPLACE FUNCTION private.material_json(a public.material_artifacts) RETURNS jsonb
LANGUAGE sql STABLE SET search_path='' AS $$
 SELECT jsonb_build_object('material_id',a.material_id,'record_id',a.record_id,CASE WHEN a.artifact_kind='contact' THEN 'contact_event_id' ELSE 'application_event_id' END,
 CASE WHEN a.artifact_kind='contact' THEN a.contact_event_id ELSE a.application_event_id END,
 'opportunity_id',a.opportunity_id,'owner_id',a.owner_id,'status',a.status,'filename',a.filename,
 'mime_type',CASE WHEN a.status='deleted' THEN NULL ELSE 'application/pdf' END,'byte_length',a.byte_length,'sha256',a.sha256,
 'created_at',a.created_at,'expires_at',a.expires_at,'archived_at',a.archived_at,
 'recorded_at',CASE WHEN a.artifact_kind='contact' THEN (SELECT recorded_at FROM public.contact_material_records WHERE material_id=a.material_id)
   ELSE (SELECT recorded_at FROM public.application_material_records WHERE material_id=a.material_id) END,
 'deleted_at',a.deleted_at,'confirmation_source','user_reported');
$$;

CREATE FUNCTION private.stage_material(p_kind text,p_expected_owner text,p_material_id uuid,p_record_id uuid,p_event_id uuid,
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

CREATE OR REPLACE FUNCTION private.stage_application_material(p_expected_owner text,p_material_id uuid,p_record_id uuid,p_application_event_id uuid,
 p_opportunity_id text,p_filename text,p_byte_length bigint,p_sha256 text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.stage_material('application',p_expected_owner,p_material_id,p_record_id,p_application_event_id,p_opportunity_id,p_filename,p_byte_length,p_sha256); $$;

CREATE FUNCTION private.stage_contact_material(p_expected_owner text,p_material_id uuid,p_record_id uuid,p_contact_event_id uuid,
 p_opportunity_id text,p_filename text,p_byte_length bigint,p_sha256 text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.stage_material('contact',p_expected_owner,p_material_id,p_record_id,p_contact_event_id,p_opportunity_id,p_filename,p_byte_length,p_sha256); $$;

CREATE FUNCTION public.stage_contact_material(p_expected_owner text,p_material_id uuid,p_record_id uuid,p_contact_event_id uuid,
 p_opportunity_id text,p_filename text,p_byte_length bigint,p_sha256 text) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.stage_contact_material(p_expected_owner,p_material_id,p_record_id,p_contact_event_id,p_opportunity_id,p_filename,p_byte_length,p_sha256); $$;

REVOKE ALL ON FUNCTION private.stage_contact_material(text,uuid,uuid,uuid,text,text,bigint,text),public.stage_contact_material(text,uuid,uuid,uuid,text,text,bigint,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.stage_contact_material(text,uuid,uuid,uuid,text,text,bigint,text),public.stage_contact_material(text,uuid,uuid,uuid,text,text,bigint,text) TO authenticated;

CREATE FUNCTION private.get_material(p_kind text,p_expected_owner text,p_record_id uuid,p_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; a public.material_artifacts%ROWTYPE;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event_for_kind(p_kind,uid,p_event_id,p_opportunity_id);
 SELECT * INTO a FROM public.material_artifacts WHERE record_id=p_record_id AND owner_id=uid AND artifact_kind=p_kind AND (CASE WHEN p_kind='contact' THEN contact_event_id ELSE application_event_id END)=p_event_id AND opportunity_id=p_opportunity_id FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('artifact',NULL); END IF;
 IF a.status='staged' AND a.expires_at<=clock_timestamp() THEN a:=private.revoke_material(a.material_id); END IF;
 RETURN jsonb_build_object('artifact',private.material_json(a));
END;
$$;

REVOKE ALL ON FUNCTION private.get_material(text,text,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION private.get_application_material(p_expected_owner text,p_record_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.get_material('application',p_expected_owner,p_record_id,p_application_event_id,p_opportunity_id); $$;

CREATE FUNCTION private.get_contact_material(p_expected_owner text,p_record_id uuid,p_contact_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.get_material('contact',p_expected_owner,p_record_id,p_contact_event_id,p_opportunity_id); $$;

CREATE FUNCTION public.get_contact_material(p_expected_owner text,p_record_id uuid,p_contact_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.get_contact_material(p_expected_owner,p_record_id,p_contact_event_id,p_opportunity_id); $$;

REVOKE ALL ON FUNCTION private.get_contact_material(text,uuid,uuid,text),public.get_contact_material(text,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.get_contact_material(text,uuid,uuid,text),public.get_contact_material(text,uuid,uuid,text) TO authenticated;

CREATE FUNCTION private.list_materials(p_kind text,p_expected_owner text,p_event_id uuid,p_opportunity_id text,
 p_before_recorded_at timestamptz DEFAULT NULL,p_before_record_id uuid DEFAULT NULL,p_limit integer DEFAULT 20) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; items jsonb; last_item jsonb;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event_for_kind(p_kind,uid,p_event_id,p_opportunity_id);
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 OR (p_before_recorded_at IS NULL)<>(p_before_record_id IS NULL)
   OR (p_before_recorded_at IS NOT NULL AND NOT isfinite(p_before_recorded_at)) THEN RAISE EXCEPTION USING MESSAGE='invalid_' || p_kind || '_material', ERRCODE='22023'; END IF;
 SELECT coalesce(jsonb_agg(private.material_json(a) ORDER BY r.recorded_at DESC,r.record_id DESC),'[]'::jsonb) INTO items
 FROM (SELECT * FROM (
   SELECT record_id,material_id,owner_id,application_event_id AS event_id,opportunity_id,recorded_at FROM public.application_material_records WHERE p_kind='application'
   UNION ALL
   SELECT record_id,material_id,owner_id,contact_event_id AS event_id,opportunity_id,recorded_at FROM public.contact_material_records WHERE p_kind='contact'
 ) records WHERE owner_id=uid AND event_id=p_event_id AND opportunity_id=p_opportunity_id
   AND (p_before_recorded_at IS NULL OR (recorded_at,record_id)<(p_before_recorded_at,p_before_record_id)) ORDER BY recorded_at DESC,record_id DESC LIMIT p_limit+1) r
 JOIN public.material_artifacts a ON a.material_id=r.material_id AND a.record_id=r.record_id
   AND a.owner_id=uid AND a.artifact_kind=p_kind AND a.opportunity_id=p_opportunity_id
   AND (CASE WHEN p_kind='contact' THEN a.contact_event_id ELSE a.application_event_id END)=p_event_id;
 IF jsonb_array_length(items)>p_limit THEN items:=items-p_limit; last_item:=items->(p_limit-1);
   RETURN jsonb_build_object('items',items,'next_cursor',jsonb_build_object('recorded_at',last_item->'recorded_at','record_id',last_item->'record_id')); END IF;
 RETURN jsonb_build_object('items',items,'next_cursor',NULL);
END;
$$;

REVOKE ALL ON FUNCTION private.list_materials(text,text,uuid,text,timestamptz,uuid,integer) FROM PUBLIC,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION private.list_application_materials(p_expected_owner text,p_application_event_id uuid,p_opportunity_id text,
 p_before_recorded_at timestamptz DEFAULT NULL,p_before_record_id uuid DEFAULT NULL,p_limit integer DEFAULT 20) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.list_materials('application',p_expected_owner,p_application_event_id,p_opportunity_id,p_before_recorded_at,p_before_record_id,p_limit); $$;

CREATE FUNCTION private.list_contact_materials(p_expected_owner text,p_contact_event_id uuid,p_opportunity_id text,
 p_before_recorded_at timestamptz DEFAULT NULL,p_before_record_id uuid DEFAULT NULL,p_limit integer DEFAULT 20) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.list_materials('contact',p_expected_owner,p_contact_event_id,p_opportunity_id,p_before_recorded_at,p_before_record_id,p_limit); $$;

CREATE FUNCTION public.list_contact_materials(p_expected_owner text,p_contact_event_id uuid,p_opportunity_id text,
 p_before_recorded_at timestamptz DEFAULT NULL,p_before_record_id uuid DEFAULT NULL,p_limit integer DEFAULT 20) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.list_contact_materials(p_expected_owner,p_contact_event_id,p_opportunity_id,p_before_recorded_at,p_before_record_id,p_limit); $$;

REVOKE ALL ON FUNCTION private.list_contact_materials(text,uuid,text,timestamptz,uuid,integer),public.list_contact_materials(text,uuid,text,timestamptz,uuid,integer) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.list_contact_materials(text,uuid,text,timestamptz,uuid,integer),public.list_contact_materials(text,uuid,text,timestamptz,uuid,integer) TO authenticated;

CREATE FUNCTION private.authorize_material_download(p_kind text,p_expected_owner text,p_record_id uuid,p_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; a public.material_artifacts%ROWTYPE;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event_for_kind(p_kind,uid,p_event_id,p_opportunity_id);
 SELECT * INTO a FROM public.material_artifacts WHERE record_id=p_record_id AND owner_id=uid AND artifact_kind=p_kind AND (CASE WHEN p_kind='contact' THEN contact_event_id ELSE application_event_id END)=p_event_id AND opportunity_id=p_opportunity_id;
 IF NOT FOUND THEN RAISE EXCEPTION USING MESSAGE=p_kind || '_material_not_found', ERRCODE='P0002'; END IF;
 IF a.status<>'ready' THEN RAISE EXCEPTION USING MESSAGE=p_kind || '_material_unavailable', ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('artifact',private.material_json(a),'bucket','application-materials','object_key',a.object_key);
END;
$$;

REVOKE ALL ON FUNCTION private.authorize_material_download(text,text,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION private.authorize_application_material_download(p_expected_owner text,p_record_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.authorize_material_download('application',p_expected_owner,p_record_id,p_application_event_id,p_opportunity_id); $$;

CREATE FUNCTION private.authorize_contact_material_download(p_expected_owner text,p_record_id uuid,p_contact_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.authorize_material_download('contact',p_expected_owner,p_record_id,p_contact_event_id,p_opportunity_id); $$;

CREATE FUNCTION public.authorize_contact_material_download(p_expected_owner text,p_record_id uuid,p_contact_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.authorize_contact_material_download(p_expected_owner,p_record_id,p_contact_event_id,p_opportunity_id); $$;

REVOKE ALL ON FUNCTION private.authorize_contact_material_download(text,uuid,uuid,text),public.authorize_contact_material_download(text,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.authorize_contact_material_download(text,uuid,uuid,text),public.authorize_contact_material_download(text,uuid,uuid,text) TO authenticated;

CREATE FUNCTION private.delete_material(p_kind text,p_expected_owner text,p_record_id uuid,p_material_id uuid,p_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; a public.material_artifacts%ROWTYPE; replay boolean; stamp timestamptz;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event_for_kind(p_kind,uid,p_event_id,p_opportunity_id);
 IF p_material_id IS NULL OR p_record_id IS NULL THEN RAISE EXCEPTION USING MESSAGE='invalid_' || p_kind || '_material', ERRCODE='22023'; END IF;
 -- Same owner -> global material lock order as stage. Reserve a revoked ID even
 -- if the original HTTP upload has not reached stage yet; late arrivals must
 -- never revive an explicitly cancelled attempt.
 PERFORM pg_advisory_xact_lock(hashtext('ofe-material:' || p_material_id::text));
 SELECT * INTO a FROM public.material_artifacts WHERE material_id=p_material_id FOR UPDATE;
 IF FOUND THEN
   IF a.record_id IS DISTINCT FROM p_record_id OR a.owner_id IS DISTINCT FROM uid OR a.artifact_kind IS DISTINCT FROM p_kind OR (CASE WHEN p_kind='contact' THEN a.contact_event_id ELSE a.application_event_id END) IS DISTINCT FROM p_event_id OR a.opportunity_id IS DISTINCT FROM p_opportunity_id THEN
     RAISE EXCEPTION USING MESSAGE=p_kind || '_material_conflict', ERRCODE='23505'; END IF;
   replay:=a.status='deleted';
 ELSE
   IF EXISTS(SELECT 1 FROM public.material_artifacts WHERE record_id=p_record_id)
     OR EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id=p_material_id) THEN
     RAISE EXCEPTION USING MESSAGE=p_kind || '_material_conflict', ERRCODE='23505'; END IF;
   stamp:=clock_timestamp();
   INSERT INTO public.material_artifacts(material_id,record_id,owner_id,artifact_kind,application_event_id,contact_event_id,opportunity_id,status,created_at,expires_at,deleted_at)
     VALUES(p_material_id,p_record_id,uid,p_kind,CASE WHEN p_kind='application' THEN p_event_id END,CASE WHEN p_kind='contact' THEN p_event_id END,p_opportunity_id,'deleted',stamp,stamp+interval '24 hours',stamp);
   replay:=false;
 END IF;
 a:=private.revoke_material(p_material_id);
 RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',replay);
EXCEPTION WHEN unique_violation THEN RAISE EXCEPTION USING MESSAGE=p_kind || '_material_conflict', ERRCODE='23505';
END;
$$;

REVOKE ALL ON FUNCTION private.delete_material(text,text,uuid,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION private.delete_application_material(p_expected_owner text,p_record_id uuid,p_material_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.delete_material('application',p_expected_owner,p_record_id,p_material_id,p_application_event_id,p_opportunity_id); $$;

CREATE FUNCTION private.delete_contact_material(p_expected_owner text,p_record_id uuid,p_material_id uuid,p_contact_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.delete_material('contact',p_expected_owner,p_record_id,p_material_id,p_contact_event_id,p_opportunity_id); $$;

CREATE FUNCTION public.delete_contact_material(p_expected_owner text,p_record_id uuid,p_material_id uuid,p_contact_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.delete_contact_material(p_expected_owner,p_record_id,p_material_id,p_contact_event_id,p_opportunity_id); $$;

REVOKE ALL ON FUNCTION private.delete_contact_material(text,uuid,uuid,uuid,text),public.delete_contact_material(text,uuid,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.delete_contact_material(text,uuid,uuid,uuid,text),public.delete_contact_material(text,uuid,uuid,uuid,text) TO authenticated;

CREATE FUNCTION private.finalize_material(p_kind text,p_verified_owner uuid,p_verified_session_id uuid,p_material_id uuid,p_stage_token uuid,
 p_verified_byte_length bigint,p_verified_sha256 text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE a public.material_artifacts%ROWTYPE; stamp timestamptz;
BEGIN
 PERFORM private.material_owner_session(p_verified_owner,p_verified_session_id);
 SELECT * INTO a FROM public.material_artifacts WHERE material_id=p_material_id AND owner_id=p_verified_owner AND artifact_kind=p_kind FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION USING MESSAGE=p_kind || '_material_not_found', ERRCODE='P0002'; END IF;
 PERFORM private.material_event_for_kind(p_kind,p_verified_owner,CASE WHEN p_kind='contact' THEN a.contact_event_id ELSE a.application_event_id END,a.opportunity_id);
 IF a.status='deleted' THEN RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',true); END IF;
 IF a.status='staged' AND a.expires_at<=clock_timestamp() THEN a:=private.revoke_material(a.material_id); RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',true); END IF;
 IF p_verified_byte_length IS DISTINCT FROM a.byte_length OR p_verified_sha256 IS DISTINCT FROM a.declared_sha256 THEN
   RAISE EXCEPTION USING MESSAGE=p_kind || '_material_conflict', ERRCODE='23505'; END IF;
 -- A retried stage rotates the token; the request that lost that race verified
 -- the same bytes, so once ready it is a replay whatever token it holds.
 IF a.status='ready' THEN RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',true); END IF;
 -- Superseded or past its window: retryable by staging again, not an auth failure.
 IF a.stage_token IS DISTINCT FROM p_stage_token OR a.authorized_until<=clock_timestamp() THEN
   RAISE EXCEPTION 'material_stage_superseded' USING ERRCODE='55006'; END IF;
 IF a.stage_session_id IS DISTINCT FROM p_verified_session_id THEN RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END IF;
 stamp:=clock_timestamp();
 UPDATE public.material_artifacts SET status='ready',sha256=p_verified_sha256,archived_at=stamp WHERE material_id=p_material_id RETURNING * INTO a;
 IF p_kind='contact' THEN
   INSERT INTO public.contact_material_records(record_id,material_id,owner_id,contact_event_id,opportunity_id,recorded_at)
     VALUES(a.record_id,a.material_id,a.owner_id,a.contact_event_id,a.opportunity_id,stamp);
 ELSE
 INSERT INTO public.application_material_records(record_id,material_id,owner_id,application_event_id,opportunity_id,recorded_at)
   VALUES(a.record_id,a.material_id,a.owner_id,a.application_event_id,a.opportunity_id,stamp);
 END IF;
 RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',false);
END;
$$;

REVOKE ALL ON FUNCTION private.finalize_material(text,uuid,uuid,uuid,uuid,bigint,text) FROM PUBLIC,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION private.finalize_application_material(p_verified_owner uuid,p_verified_session_id uuid,p_material_id uuid,p_stage_token uuid,
 p_verified_byte_length bigint,p_verified_sha256 text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.finalize_material('application',p_verified_owner,p_verified_session_id,p_material_id,p_stage_token,p_verified_byte_length,p_verified_sha256); $$;

CREATE FUNCTION private.finalize_contact_material(p_verified_owner uuid,p_verified_session_id uuid,p_material_id uuid,p_stage_token uuid,
 p_verified_byte_length bigint,p_verified_sha256 text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$ SELECT private.finalize_material('contact',p_verified_owner,p_verified_session_id,p_material_id,p_stage_token,p_verified_byte_length,p_verified_sha256); $$;

CREATE FUNCTION public.finalize_contact_material(p_verified_owner uuid,p_verified_session_id uuid,p_material_id uuid,p_stage_token uuid,
 p_verified_byte_length bigint,p_verified_sha256 text) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.finalize_contact_material(p_verified_owner,p_verified_session_id,p_material_id,p_stage_token,p_verified_byte_length,p_verified_sha256); $$;

REVOKE ALL ON FUNCTION private.finalize_contact_material(uuid,uuid,uuid,uuid,bigint,text),public.finalize_contact_material(uuid,uuid,uuid,uuid,bigint,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.finalize_contact_material(uuid,uuid,uuid,uuid,bigint,text),public.finalize_contact_material(uuid,uuid,uuid,uuid,bigint,text) TO service_role;

CREATE FUNCTION private.protect_contact_material_record() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 IF TG_OP='DELETE' THEN
   IF NOT EXISTS(SELECT 1 FROM auth.users WHERE id=OLD.owner_id) THEN RETURN OLD; END IF;
   RAISE EXCEPTION 'immutable_contact_material_record' USING ERRCODE='42501'; END IF;
 IF to_jsonb(OLD)-ARRAY['owner_id','object_key'] IS DISTINCT FROM to_jsonb(NEW)-ARRAY['owner_id','object_key'] THEN RAISE EXCEPTION 'immutable_contact_material_record' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION private.protect_contact_material_record() FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER contact_material_record_immutable BEFORE UPDATE OR DELETE ON public.contact_material_records FOR EACH ROW EXECUTE FUNCTION private.protect_contact_material_record();

-- The existing merged_devices trigger already moves all artifact kinds and
-- revokes every unfinished stage under sorted owner locks. Contact events move
-- later in the same transaction; a ledger conflict rolls everything back.
CREATE OR REPLACE FUNCTION private.merge_application_materials() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE a record;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.material_artifacts WHERE owner_id::text=NEW.source_device_id) THEN RETURN NEW; END IF;
 IF auth.uid()::text IS DISTINCT FROM NEW.target_device_id OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id::text=NEW.target_device_id AND is_anonymous IS FALSE) THEN
   RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || least(NEW.source_device_id,NEW.target_device_id)));
 PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || greatest(NEW.source_device_id,NEW.target_device_id)));
 FOR a IN SELECT material_id FROM public.material_artifacts WHERE owner_id::text=NEW.source_device_id AND status='staged' LOOP PERFORM private.revoke_material(a.material_id); END LOOP;
 UPDATE public.material_artifacts SET owner_id=NEW.target_device_id::uuid WHERE owner_id::text=NEW.source_device_id;
 UPDATE public.application_material_records SET owner_id=NEW.target_device_id::uuid WHERE owner_id::text=NEW.source_device_id;
 UPDATE public.contact_material_records SET owner_id=NEW.target_device_id::uuid WHERE owner_id::text=NEW.source_device_id;
 RETURN NEW;
END;
$$;

-- Account deletion and the cleanup outbox already operate on all artifact
-- kinds. Cascading deletion now removes the appropriate independent record.
-- No Storage objects are mutated in SQL. Existing pending uploads/deletions keep
-- their object key, capability, session and permanent cleanup tombstone.
NOTIFY pgrst, 'reload schema';
