-- Separate later user declarations of the actual PDF from immutable application
-- events. Storage bytes are uploaded/deleted only through the Storage API.
-- Browser roles cannot forge verified hashes or bypass active-session checks.
INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
VALUES('application-materials','application-materials',false,67108864,ARRAY['application/pdf'])
ON CONFLICT(id) DO UPDATE SET public=false,file_size_limit=67108864,allowed_mime_types=ARRAY['application/pdf'];
-- Restrictive policies prevent an unrelated permissive browser policy from
-- opening this bucket. The trusted service role is not included here.
CREATE POLICY application_materials_no_browser_objects ON storage.objects
AS RESTRICTIVE FOR ALL TO anon,authenticated
USING(bucket_id <> 'application-materials') WITH CHECK(bucket_id <> 'application-materials');

CREATE TABLE public.material_artifacts(
 material_id uuid PRIMARY KEY,
 record_id uuid NOT NULL UNIQUE,
 owner_id uuid NOT NULL,
 application_event_id uuid NOT NULL,
 opportunity_id text NOT NULL,
 object_key text GENERATED ALWAYS AS ('pdf/' || material_id::text || '.pdf') STORED UNIQUE,
 status text NOT NULL CHECK(status IN ('staged','ready','deleted')),
 filename text,
 byte_length bigint,
 declared_sha256 text,
 sha256 text,
 created_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL,
 archived_at timestamptz,
 deleted_at timestamptz,
 stage_token uuid,
 stage_session_id uuid,
 authorized_until timestamptz,
 CHECK(byte_length IS NULL OR byte_length BETWEEN 1 AND 67108864),
 CHECK(declared_sha256 IS NULL OR declared_sha256 ~ '^[a-f0-9]{64}$'),
 CHECK(sha256 IS NULL OR sha256 ~ '^[a-f0-9]{64}$'),
 CHECK((status='deleted' AND filename IS NULL AND byte_length IS NULL AND declared_sha256 IS NULL AND sha256 IS NULL
    AND stage_token IS NULL AND stage_session_id IS NULL AND authorized_until IS NULL AND deleted_at IS NOT NULL)
   OR (status IN ('staged','ready') AND filename IS NOT NULL AND byte_length IS NOT NULL AND declared_sha256 IS NOT NULL
    AND stage_token IS NOT NULL AND stage_session_id IS NOT NULL AND authorized_until IS NOT NULL AND deleted_at IS NULL)),
 CHECK((status='staged' AND archived_at IS NULL AND sha256 IS NULL) OR (status='ready' AND archived_at IS NOT NULL AND sha256=declared_sha256) OR status='deleted')
);
CREATE INDEX material_artifacts_owner_idx ON public.material_artifacts(owner_id);
CREATE INDEX material_artifacts_expiry_idx ON public.material_artifacts(expires_at) WHERE status='staged';
CREATE TABLE public.application_material_records(
 record_id uuid PRIMARY KEY,
 material_id uuid NOT NULL UNIQUE REFERENCES public.material_artifacts(material_id) ON DELETE CASCADE,
 owner_id uuid NOT NULL,
 application_event_id uuid NOT NULL,
 opportunity_id text NOT NULL,
 recorded_at timestamptz NOT NULL,
 confirmation_source text NOT NULL DEFAULT 'user_reported' CHECK(confirmation_source='user_reported')
);
CREATE INDEX application_material_records_page_idx ON public.application_material_records(owner_id,application_event_id,opportunity_id,recorded_at DESC,record_id DESC);
CREATE TABLE private.material_cleanup_outbox(
 material_id uuid PRIMARY KEY,
 object_key text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 claim_token uuid,
 claimed_until timestamptz,
 attempts bigint NOT NULL DEFAULT 0,
 last_removed_at timestamptz,
 CHECK(object_key='pdf/' || material_id::text || '.pdf')
);
ALTER TABLE public.material_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_material_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.material_cleanup_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.material_artifacts,public.application_material_records,private.material_cleanup_outbox FROM PUBLIC,anon,authenticated,service_role;
-- Defense in depth only. No browser SELECT grant: bounded RPCs below also
-- validate auth.sessions, so sign-out cannot be bypassed by table reads.
CREATE POLICY material_artifacts_own ON public.material_artifacts FOR SELECT TO authenticated
 USING(owner_id=(SELECT auth.uid()) AND private.target_resume_owner_active((SELECT auth.uid())));
CREATE POLICY application_material_records_own ON public.application_material_records FOR SELECT TO authenticated
 USING(owner_id=(SELECT auth.uid()) AND private.target_resume_owner_active((SELECT auth.uid())));

-- Immutable content identity, with narrow lifecycle exceptions for staging
-- capabilities, verified finalization, ownership transfer and privacy erasure.
-- Generated object_key is unavailable in NEW during a BEFORE trigger; its
-- immutable material_id source is compared instead.
CREATE FUNCTION private.protect_material_artifact() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 IF (to_jsonb(OLD)-ARRAY['object_key','owner_id','status','filename','byte_length','declared_sha256','sha256','archived_at','deleted_at','stage_token','stage_session_id','authorized_until'])
   IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['object_key','owner_id','status','filename','byte_length','declared_sha256','sha256','archived_at','deleted_at','stage_token','stage_session_id','authorized_until'])
   OR (OLD.status='deleted' AND to_jsonb(OLD)-ARRAY['owner_id','object_key'] IS DISTINCT FROM to_jsonb(NEW)-ARRAY['owner_id','object_key'])
   OR (OLD.status='ready' AND NEW.status NOT IN ('ready','deleted'))
   OR (NEW.status<>'deleted' AND (NEW.filename IS DISTINCT FROM OLD.filename OR NEW.byte_length IS DISTINCT FROM OLD.byte_length OR NEW.declared_sha256 IS DISTINCT FROM OLD.declared_sha256))
   OR (OLD.status='ready' AND NEW.archived_at IS DISTINCT FROM OLD.archived_at)
   OR (OLD.status='ready' AND NEW.status='ready' AND to_jsonb(OLD)-ARRAY['owner_id','object_key'] IS DISTINCT FROM to_jsonb(NEW)-ARRAY['owner_id','object_key']) THEN
   RAISE EXCEPTION 'immutable_material_artifact' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION private.protect_material_artifact() FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER material_artifact_immutable BEFORE UPDATE ON public.material_artifacts FOR EACH ROW EXECUTE FUNCTION private.protect_material_artifact();

CREATE FUNCTION private.material_owner_session(p_owner uuid,p_session uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_owner IS NULL OR p_session IS NULL THEN RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || p_owner::text));
 IF NOT EXISTS(SELECT 1 FROM auth.users WHERE id=p_owner AND is_anonymous IS FALSE)
   OR EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=p_owner::text) THEN
   RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501';
 END IF;
 -- Hold the validated session against concurrent logout until this transaction
 -- completes. The auth-users BEFORE DELETE fence below preserves lock order.
 PERFORM id FROM auth.sessions WHERE id=p_session AND user_id=p_owner
   AND (not_after IS NULL OR not_after>clock_timestamp()) FOR KEY SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END IF;
END;
$$;
CREATE FUNCTION private.material_user(p_expected_owner text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid:=auth.uid(); sid uuid; claims jsonb:=auth.jwt(); exp text;
BEGIN
 IF uid IS NULL OR p_expected_owner IS DISTINCT FROM uid::text THEN RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END IF;
 BEGIN sid:=(claims->>'session_id')::uuid; EXCEPTION WHEN invalid_text_representation THEN RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END;
 exp:=claims->>'exp';
 IF exp IS NULL OR exp !~ '^[0-9]{1,12}$' THEN RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END IF;
 IF to_timestamp(exp::double precision)<=clock_timestamp() THEN RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END IF;
 PERFORM private.material_owner_session(uid,sid);
 RETURN uid;
END;
$$;
CREATE FUNCTION private.material_event(p_owner uuid,p_event uuid,p_opportunity text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_event IS NULL OR p_opportunity IS NULL OR length(p_opportunity) NOT BETWEEN 1 AND 200 OR p_opportunity !~ '[^[:space:]]' THEN
   RAISE EXCEPTION 'invalid_application_material' USING ERRCODE='22023'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.application_events WHERE device_id=p_owner::text AND event_id=p_event AND opportunity_id=p_opportunity) THEN
   RAISE EXCEPTION 'application_material_not_found' USING ERRCODE='P0002'; END IF;
END;
$$;
CREATE FUNCTION private.material_json(a public.material_artifacts) RETURNS jsonb
LANGUAGE sql STABLE SET search_path='' AS $$
 SELECT jsonb_build_object('material_id',a.material_id,'record_id',a.record_id,'application_event_id',a.application_event_id,
 'opportunity_id',a.opportunity_id,'owner_id',a.owner_id,'status',a.status,'filename',a.filename,
 'mime_type',CASE WHEN a.status='deleted' THEN NULL ELSE 'application/pdf' END,'byte_length',a.byte_length,'sha256',a.sha256,
 'created_at',a.created_at,'expires_at',a.expires_at,'archived_at',a.archived_at,
 'recorded_at',(SELECT recorded_at FROM public.application_material_records WHERE material_id=a.material_id),
 'deleted_at',a.deleted_at,'confirmation_source','user_reported');
$$;
CREATE FUNCTION private.revoke_material(p_id uuid) RETURNS public.material_artifacts
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE a public.material_artifacts%ROWTYPE;
BEGIN
 UPDATE public.material_artifacts SET status='deleted',filename=NULL,byte_length=NULL,declared_sha256=NULL,sha256=NULL,
   stage_token=NULL,stage_session_id=NULL,authorized_until=NULL,deleted_at=coalesce(deleted_at,clock_timestamp())
   WHERE material_id=p_id RETURNING * INTO a;
 IF FOUND THEN INSERT INTO private.material_cleanup_outbox(material_id,object_key) VALUES(a.material_id,a.object_key) ON CONFLICT(material_id) DO NOTHING; END IF;
 RETURN a;
END;
$$;

CREATE FUNCTION private.stage_application_material(p_expected_owner text,p_material_id uuid,p_record_id uuid,p_application_event_id uuid,
 p_opportunity_id text,p_filename text,p_byte_length bigint,p_sha256 text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; a public.material_artifacts%ROWTYPE; existed boolean; stamp timestamptz;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event(uid,p_application_event_id,p_opportunity_id);
 IF p_material_id IS NULL OR p_record_id IS NULL OR p_filename IS NULL OR length(p_filename) NOT BETWEEN 1 AND 200
   OR p_filename !~ '[^[:space:]]' OR p_filename ~ '[[:cntrl:]/\\]' OR p_filename !~* '\.pdf$'
   OR p_byte_length IS NULL OR p_byte_length NOT BETWEEN 1 AND 67108864 OR p_sha256 IS NULL OR p_sha256 !~ '^[0-9a-f]{64}$' THEN
   RAISE EXCEPTION 'invalid_application_material' USING ERRCODE='22023'; END IF;
 -- Global ID lock prevents cross-owner races without exposing another owner's
 -- row or changing the sorted owner locks used by merge.
 PERFORM pg_advisory_xact_lock(hashtext('ofe-material:' || p_material_id::text));
 SELECT * INTO a FROM public.material_artifacts WHERE material_id=p_material_id FOR UPDATE;
 existed:=FOUND;
 IF existed THEN
   IF a.owner_id<>uid OR a.record_id<>p_record_id OR a.application_event_id<>p_application_event_id OR a.opportunity_id<>p_opportunity_id THEN
     RAISE EXCEPTION 'application_material_conflict' USING ERRCODE='23505'; END IF;
   IF a.status='deleted' THEN RETURN jsonb_build_object('artifact',private.material_json(a),'upload',NULL,'replayed',true); END IF;
   IF a.filename<>p_filename OR a.byte_length<>p_byte_length OR a.declared_sha256<>p_sha256 THEN
     RAISE EXCEPTION 'application_material_conflict' USING ERRCODE='23505'; END IF;
   IF a.status='ready' THEN RETURN jsonb_build_object('artifact',private.material_json(a),'upload',NULL,'replayed',true); END IF;
   IF a.expires_at<=clock_timestamp() THEN a:=private.revoke_material(a.material_id); RETURN jsonb_build_object('artifact',private.material_json(a),'upload',NULL,'replayed',true); END IF;
 ELSE
   IF EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id=p_material_id)
     OR EXISTS(SELECT 1 FROM public.material_artifacts WHERE record_id=p_record_id) THEN RAISE EXCEPTION 'application_material_conflict' USING ERRCODE='23505'; END IF;
   stamp:=clock_timestamp();
   INSERT INTO public.material_artifacts(material_id,record_id,owner_id,application_event_id,opportunity_id,status,filename,byte_length,
     declared_sha256,created_at,expires_at,stage_token,stage_session_id,authorized_until)
     VALUES(p_material_id,p_record_id,uid,p_application_event_id,p_opportunity_id,'staged',p_filename,p_byte_length,p_sha256,
       stamp,stamp+interval '24 hours',gen_random_uuid(),(auth.jwt()->>'session_id')::uuid,to_timestamp((auth.jwt()->>'exp')::double precision)) RETURNING * INTO a;
 END IF;
 UPDATE public.material_artifacts SET stage_token=gen_random_uuid(),stage_session_id=(auth.jwt()->>'session_id')::uuid,
   authorized_until=least(expires_at,to_timestamp((auth.jwt()->>'exp')::double precision)) WHERE material_id=p_material_id RETURNING * INTO a;
 RETURN jsonb_build_object('artifact',private.material_json(a),'upload',jsonb_build_object('bucket','application-materials',
   'object_key',a.object_key,'stage_token',a.stage_token,'session_id',a.stage_session_id,'authorized_until',a.authorized_until),'replayed',existed);
EXCEPTION WHEN unique_violation THEN RAISE EXCEPTION 'application_material_conflict' USING ERRCODE='23505';
END;
$$;

CREATE FUNCTION private.get_application_material(p_expected_owner text,p_record_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; a public.material_artifacts%ROWTYPE;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event(uid,p_application_event_id,p_opportunity_id);
 SELECT * INTO a FROM public.material_artifacts WHERE record_id=p_record_id AND owner_id=uid AND application_event_id=p_application_event_id AND opportunity_id=p_opportunity_id FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('artifact',NULL); END IF;
 IF a.status='staged' AND a.expires_at<=clock_timestamp() THEN a:=private.revoke_material(a.material_id); END IF;
 RETURN jsonb_build_object('artifact',private.material_json(a));
END;
$$;
CREATE FUNCTION private.list_application_materials(p_expected_owner text,p_application_event_id uuid,p_opportunity_id text,
 p_before_recorded_at timestamptz DEFAULT NULL,p_before_record_id uuid DEFAULT NULL,p_limit integer DEFAULT 20) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; items jsonb; last_item jsonb;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event(uid,p_application_event_id,p_opportunity_id);
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 OR (p_before_recorded_at IS NULL)<>(p_before_record_id IS NULL)
   OR (p_before_recorded_at IS NOT NULL AND NOT isfinite(p_before_recorded_at)) THEN RAISE EXCEPTION 'invalid_application_material' USING ERRCODE='22023'; END IF;
 SELECT coalesce(jsonb_agg(private.material_json(a) ORDER BY r.recorded_at DESC,r.record_id DESC),'[]'::jsonb) INTO items
 FROM (SELECT * FROM public.application_material_records WHERE owner_id=uid AND application_event_id=p_application_event_id AND opportunity_id=p_opportunity_id
   AND (p_before_recorded_at IS NULL OR (recorded_at,record_id)<(p_before_recorded_at,p_before_record_id)) ORDER BY recorded_at DESC,record_id DESC LIMIT p_limit+1) r
 JOIN public.material_artifacts a USING(material_id);
 IF jsonb_array_length(items)>p_limit THEN items:=items-p_limit; last_item:=items->(p_limit-1);
   RETURN jsonb_build_object('items',items,'next_cursor',jsonb_build_object('recorded_at',last_item->'recorded_at','record_id',last_item->'record_id')); END IF;
 RETURN jsonb_build_object('items',items,'next_cursor',NULL);
END;
$$;
CREATE FUNCTION private.authorize_application_material_download(p_expected_owner text,p_record_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; a public.material_artifacts%ROWTYPE;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event(uid,p_application_event_id,p_opportunity_id);
 SELECT * INTO a FROM public.material_artifacts WHERE record_id=p_record_id AND owner_id=uid AND application_event_id=p_application_event_id AND opportunity_id=p_opportunity_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'application_material_not_found' USING ERRCODE='P0002'; END IF;
 IF a.status<>'ready' THEN RAISE EXCEPTION 'application_material_unavailable' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('artifact',private.material_json(a),'bucket','application-materials','object_key',a.object_key);
END;
$$;
CREATE FUNCTION private.delete_application_material(p_expected_owner text,p_record_id uuid,p_material_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid; a public.material_artifacts%ROWTYPE; replay boolean; stamp timestamptz;
BEGIN
 uid:=private.material_user(p_expected_owner); PERFORM private.material_event(uid,p_application_event_id,p_opportunity_id);
 IF p_material_id IS NULL OR p_record_id IS NULL THEN RAISE EXCEPTION 'invalid_application_material' USING ERRCODE='22023'; END IF;
 -- Same owner -> global material lock order as stage. Reserve a revoked ID even
 -- if the original HTTP upload has not reached stage yet; late arrivals must
 -- never revive an explicitly cancelled attempt.
 PERFORM pg_advisory_xact_lock(hashtext('ofe-material:' || p_material_id::text));
 SELECT * INTO a FROM public.material_artifacts WHERE material_id=p_material_id FOR UPDATE;
 IF FOUND THEN
   IF a.record_id<>p_record_id OR a.owner_id<>uid OR a.application_event_id<>p_application_event_id OR a.opportunity_id<>p_opportunity_id THEN
     RAISE EXCEPTION 'application_material_conflict' USING ERRCODE='23505'; END IF;
   replay:=a.status='deleted';
 ELSE
   IF EXISTS(SELECT 1 FROM public.material_artifacts WHERE record_id=p_record_id)
     OR EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id=p_material_id) THEN
     RAISE EXCEPTION 'application_material_conflict' USING ERRCODE='23505'; END IF;
   stamp:=clock_timestamp();
   INSERT INTO public.material_artifacts(material_id,record_id,owner_id,application_event_id,opportunity_id,status,created_at,expires_at,deleted_at)
     VALUES(p_material_id,p_record_id,uid,p_application_event_id,p_opportunity_id,'deleted',stamp,stamp+interval '24 hours',stamp);
   replay:=false;
 END IF;
 a:=private.revoke_material(p_material_id);
 RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',replay);
EXCEPTION WHEN unique_violation THEN RAISE EXCEPTION 'application_material_conflict' USING ERRCODE='23505';
END;
$$;
CREATE FUNCTION private.finalize_application_material(p_verified_owner uuid,p_verified_session_id uuid,p_material_id uuid,p_stage_token uuid,
 p_verified_byte_length bigint,p_verified_sha256 text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE a public.material_artifacts%ROWTYPE; stamp timestamptz;
BEGIN
 PERFORM private.material_owner_session(p_verified_owner,p_verified_session_id);
 SELECT * INTO a FROM public.material_artifacts WHERE material_id=p_material_id AND owner_id=p_verified_owner FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'application_material_not_found' USING ERRCODE='P0002'; END IF;
 PERFORM private.material_event(p_verified_owner,a.application_event_id,a.opportunity_id);
 IF a.status='deleted' THEN RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',true); END IF;
 IF a.status='staged' AND a.expires_at<=clock_timestamp() THEN a:=private.revoke_material(a.material_id); RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',true); END IF;
 IF a.stage_token IS DISTINCT FROM p_stage_token OR a.stage_session_id IS DISTINCT FROM p_verified_session_id OR a.authorized_until<=clock_timestamp() THEN
   RAISE EXCEPTION 'material_identity_unavailable' USING ERRCODE='42501'; END IF;
 IF p_verified_byte_length IS DISTINCT FROM a.byte_length OR p_verified_sha256 IS DISTINCT FROM a.declared_sha256 THEN
   RAISE EXCEPTION 'application_material_conflict' USING ERRCODE='23505'; END IF;
 IF a.status='ready' THEN RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',true); END IF;
 stamp:=clock_timestamp();
 UPDATE public.material_artifacts SET status='ready',sha256=p_verified_sha256,archived_at=stamp WHERE material_id=p_material_id RETURNING * INTO a;
 INSERT INTO public.application_material_records(record_id,material_id,owner_id,application_event_id,opportunity_id,recorded_at)
   VALUES(a.record_id,a.material_id,a.owner_id,a.application_event_id,a.opportunity_id,stamp);
 RETURN jsonb_build_object('artifact',private.material_json(a),'replayed',false);
END;
$$;
CREATE FUNCTION private.claim_material_cleanup(p_limit integer DEFAULT 20) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE a record; items jsonb;
BEGIN
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'invalid_application_material' USING ERRCODE='22023'; END IF;
 FOR a IN SELECT material_id,owner_id FROM public.material_artifacts WHERE status='staged' AND expires_at<=clock_timestamp() ORDER BY owner_id,material_id LIMIT p_limit LOOP
   IF pg_try_advisory_xact_lock(hashtext('ofe-profile:' || a.owner_id::text)) THEN
     PERFORM material_id FROM public.material_artifacts WHERE material_id=a.material_id AND status='staged' AND expires_at<=clock_timestamp() FOR UPDATE;
     IF FOUND THEN PERFORM private.revoke_material(a.material_id); END IF;
   END IF;
 END LOOP;
 WITH due AS (SELECT material_id FROM private.material_cleanup_outbox WHERE next_attempt_at<=clock_timestamp()
     AND (claimed_until IS NULL OR claimed_until<=clock_timestamp()) ORDER BY next_attempt_at,material_id LIMIT p_limit FOR UPDATE SKIP LOCKED),
 claimed AS (UPDATE private.material_cleanup_outbox o SET claim_token=gen_random_uuid(),claimed_until=clock_timestamp()+interval '5 minutes',attempts=attempts+1
   FROM due WHERE o.material_id=due.material_id RETURNING o.*)
 SELECT coalesce(jsonb_agg(jsonb_build_object('material_id',material_id,'bucket','application-materials','object_key',object_key,
   'claim_token',claim_token,'claimed_until',claimed_until)),'[]'::jsonb) INTO items FROM claimed;
 RETURN jsonb_build_object('jobs',items);
END;
$$;
CREATE FUNCTION private.ack_material_cleanup(p_material_id uuid,p_claim_token uuid,p_success boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE n integer;
BEGIN
 IF p_success IS NULL THEN RAISE EXCEPTION 'invalid_application_material' USING ERRCODE='22023'; END IF;
 UPDATE private.material_cleanup_outbox SET next_attempt_at=clock_timestamp()+CASE WHEN p_success THEN interval '24 hours' ELSE interval '5 minutes' END,
   last_removed_at=CASE WHEN p_success THEN clock_timestamp() ELSE last_removed_at END,claim_token=NULL,claimed_until=NULL
   WHERE material_id=p_material_id AND claim_token=p_claim_token AND claimed_until>clock_timestamp();
 GET DIAGNOSTICS n=ROW_COUNT;
 RETURN jsonb_build_object('accepted',n=1);
END;
$$;

CREATE FUNCTION private.protect_application_material_record() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 IF TG_OP='DELETE' THEN
   IF NOT EXISTS(SELECT 1 FROM auth.users WHERE id=OLD.owner_id) THEN RETURN OLD; END IF;
   RAISE EXCEPTION 'immutable_application_material_record' USING ERRCODE='42501'; END IF;
 IF to_jsonb(OLD)-ARRAY['owner_id','object_key'] IS DISTINCT FROM to_jsonb(NEW)-ARRAY['owner_id','object_key'] THEN RAISE EXCEPTION 'immutable_application_material_record' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER application_material_record_immutable BEFORE UPDATE OR DELETE ON public.application_material_records FOR EACH ROW EXECUTE FUNCTION private.protect_application_material_record();
CREATE FUNCTION private.merge_application_materials() RETURNS trigger
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
 RETURN NEW;
END;
$$;
CREATE TRIGGER merged_devices_application_materials AFTER INSERT ON public.merged_devices FOR EACH ROW EXECUTE FUNCTION private.merge_application_materials();
CREATE FUNCTION private.material_auth_delete_fence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || OLD.id::text)); RETURN OLD; END;
$$;
CREATE TRIGGER auth_user_material_delete_fence BEFORE DELETE ON auth.users FOR EACH ROW EXECUTE FUNCTION private.material_auth_delete_fence();
CREATE FUNCTION private.delete_materials_with_auth_user() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || OLD.id::text));
 INSERT INTO private.material_cleanup_outbox(material_id,object_key) SELECT material_id,object_key FROM public.material_artifacts WHERE owner_id=OLD.id ON CONFLICT(material_id) DO NOTHING;
 DELETE FROM public.material_artifacts WHERE owner_id=OLD.id;
 RETURN OLD;
END;
$$;
CREATE TRIGGER auth_user_delete_materials AFTER DELETE ON auth.users FOR EACH ROW EXECUTE FUNCTION private.delete_materials_with_auth_user();

GRANT USAGE ON SCHEMA private TO service_role;
REVOKE ALL ON FUNCTION private.material_owner_session(uuid,uuid) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION private.material_user(text) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION private.material_event(uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION private.material_json(public.material_artifacts) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION private.revoke_material(uuid) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION private.protect_application_material_record() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION private.merge_application_materials() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION private.material_auth_delete_fence() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION private.delete_materials_with_auth_user() FROM PUBLIC,anon,authenticated,service_role;
CREATE FUNCTION public.stage_application_material(p_expected_owner text,p_material_id uuid,p_record_id uuid,p_application_event_id uuid,p_opportunity_id text,p_filename text,p_byte_length bigint,p_sha256 text) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.stage_application_material(p_expected_owner,p_material_id,p_record_id,p_application_event_id,p_opportunity_id,p_filename,p_byte_length,p_sha256); $$;
REVOKE ALL ON FUNCTION private.stage_application_material(text,uuid,uuid,uuid,text,text,bigint,text),public.stage_application_material(text,uuid,uuid,uuid,text,text,bigint,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.stage_application_material(text,uuid,uuid,uuid,text,text,bigint,text),public.stage_application_material(text,uuid,uuid,uuid,text,text,bigint,text) TO authenticated;
CREATE FUNCTION public.get_application_material(p_expected_owner text,p_record_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.get_application_material(p_expected_owner,p_record_id,p_application_event_id,p_opportunity_id); $$;
REVOKE ALL ON FUNCTION private.get_application_material(text,uuid,uuid,text),public.get_application_material(text,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.get_application_material(text,uuid,uuid,text),public.get_application_material(text,uuid,uuid,text) TO authenticated;
CREATE FUNCTION public.list_application_materials(p_expected_owner text,p_application_event_id uuid,p_opportunity_id text,p_before_recorded_at timestamptz DEFAULT NULL,p_before_record_id uuid DEFAULT NULL,p_limit integer DEFAULT 20) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.list_application_materials(p_expected_owner,p_application_event_id,p_opportunity_id,p_before_recorded_at,p_before_record_id,p_limit); $$;
REVOKE ALL ON FUNCTION private.list_application_materials(text,uuid,text,timestamptz,uuid,integer),public.list_application_materials(text,uuid,text,timestamptz,uuid,integer) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.list_application_materials(text,uuid,text,timestamptz,uuid,integer),public.list_application_materials(text,uuid,text,timestamptz,uuid,integer) TO authenticated;
CREATE FUNCTION public.authorize_application_material_download(p_expected_owner text,p_record_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.authorize_application_material_download(p_expected_owner,p_record_id,p_application_event_id,p_opportunity_id); $$;
REVOKE ALL ON FUNCTION private.authorize_application_material_download(text,uuid,uuid,text),public.authorize_application_material_download(text,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.authorize_application_material_download(text,uuid,uuid,text),public.authorize_application_material_download(text,uuid,uuid,text) TO authenticated;
CREATE FUNCTION public.delete_application_material(p_expected_owner text,p_record_id uuid,p_material_id uuid,p_application_event_id uuid,p_opportunity_id text) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.delete_application_material(p_expected_owner,p_record_id,p_material_id,p_application_event_id,p_opportunity_id); $$;
REVOKE ALL ON FUNCTION private.delete_application_material(text,uuid,uuid,uuid,text),public.delete_application_material(text,uuid,uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.delete_application_material(text,uuid,uuid,uuid,text),public.delete_application_material(text,uuid,uuid,uuid,text) TO authenticated;
CREATE FUNCTION public.finalize_application_material(p_verified_owner uuid,p_verified_session_id uuid,p_material_id uuid,p_stage_token uuid,p_verified_byte_length bigint,p_verified_sha256 text) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.finalize_application_material(p_verified_owner,p_verified_session_id,p_material_id,p_stage_token,p_verified_byte_length,p_verified_sha256); $$;
REVOKE ALL ON FUNCTION private.finalize_application_material(uuid,uuid,uuid,uuid,bigint,text),public.finalize_application_material(uuid,uuid,uuid,uuid,bigint,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.finalize_application_material(uuid,uuid,uuid,uuid,bigint,text),public.finalize_application_material(uuid,uuid,uuid,uuid,bigint,text) TO service_role;
CREATE FUNCTION public.claim_material_cleanup(p_limit integer DEFAULT 20) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.claim_material_cleanup(p_limit); $$;
REVOKE ALL ON FUNCTION private.claim_material_cleanup(integer),public.claim_material_cleanup(integer) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.claim_material_cleanup(integer),public.claim_material_cleanup(integer) TO service_role;
CREATE FUNCTION public.ack_material_cleanup(p_material_id uuid,p_claim_token uuid,p_success boolean) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.ack_material_cleanup(p_material_id,p_claim_token,p_success); $$;
REVOKE ALL ON FUNCTION private.ack_material_cleanup(uuid,uuid,boolean),public.ack_material_cleanup(uuid,uuid,boolean) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION private.ack_material_cleanup(uuid,uuid,boolean),public.ack_material_cleanup(uuid,uuid,boolean) TO service_role;
COMMENT ON TABLE public.application_material_records IS 'Later user-reported PDF association; not proof of institutional delivery. Original application event is unchanged.';
COMMENT ON TABLE private.material_cleanup_outbox IS 'Permanent opaque revoked-key tombstones. Storage API deletion is retried even after success to catch extremely late uploads; no personal metadata retained.';
