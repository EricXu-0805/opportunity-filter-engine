-- ONLY a fresh scratch database. Do not run in postgres/application schema.
DO $$ BEGIN IF current_database() NOT LIKE 'ofe_b60_%' THEN RAISE EXCEPTION 'scratch database required'; END IF; END $$;
CREATE SCHEMA auth;
CREATE SCHEMA private;
CREATE TABLE auth.users(id uuid PRIMARY KEY,is_anonymous boolean NOT NULL DEFAULT false);
CREATE TABLE auth.sessions(id uuid PRIMARY KEY,user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,not_after timestamptz);
CREATE TABLE public.merged_devices(source_device_id text PRIMARY KEY,target_device_id text NOT NULL);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('test.uid',true),'')::uuid $$;
CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT coalesce(nullif(current_setting('test.jwt',true),''),'{}')::jsonb $$;
GRANT USAGE ON SCHEMA auth,private TO authenticated;
REVOKE ALL ON SCHEMA private FROM PUBLIC,anon;
CREATE FUNCTION private.target_resume_json_bytes(value jsonb)
RETURNS bigint LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
  SELECT CASE jsonb_typeof(value)
    WHEN 'object' THEN (SELECT 2 + coalesce(sum(octet_length(to_jsonb(key)::text) + 1
      + private.target_resume_json_bytes(val)), 0) + greatest(count(*) - 1, 0)
      FROM jsonb_each(value) AS e(key, val))
    WHEN 'array' THEN (SELECT 2 + coalesce(sum(private.target_resume_json_bytes(val)), 0)
      + greatest(count(*) - 1, 0) FROM jsonb_array_elements(value) AS e(val))
    ELSE octet_length(value::text) END::bigint;
$$;
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
REVOKE ALL ON FUNCTION private.target_resume_json_bytes(jsonb),private.material_owner_session(uuid,uuid),private.material_user(text) FROM PUBLIC,anon,authenticated,service_role;
