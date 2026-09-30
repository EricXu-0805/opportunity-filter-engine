-- Owner-bound private import storage only; no public target or model authority.
-- Dependencies: target_resume_json_bytes and material_user/material_owner_session.
CREATE TABLE public.private_import_targets (
  id text PRIMARY KEY CHECK (id ~ '^private-import:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
  opportunity jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  deleted_at timestamptz,
  CHECK ((deleted_at IS NULL AND opportunity IS NOT NULL) OR (deleted_at IS NOT NULL AND opportunity IS NULL))
);
CREATE INDEX private_import_targets_owner_page ON public.private_import_targets(owner_id, updated_at DESC, id DESC) WHERE deleted_at IS NULL;
ALTER TABLE public.private_import_targets ENABLE ROW LEVEL SECURITY;
-- No browser table access: reads also require a live non-anonymous session.
REVOKE ALL ON public.private_import_targets FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION private.private_import_json_depth(value jsonb, depth integer DEFAULT 0) RETURNS void
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE child jsonb;
BEGIN
 IF depth>32 THEN RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023'; END IF;
 IF jsonb_typeof(value)='object' THEN
   FOR child IN SELECT v FROM jsonb_each(value) e(k,v) LOOP PERFORM private.private_import_json_depth(child,depth+1); END LOOP;
 ELSIF jsonb_typeof(value)='array' THEN
   FOR child IN SELECT v FROM jsonb_array_elements(value) e(v) LOOP PERFORM private.private_import_json_depth(child,depth+1); END LOOP;
 END IF;
END; $$;
REVOKE ALL ON FUNCTION private.private_import_json_depth(jsonb,integer) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION private.validate_private_import(p_id text,p_value jsonb) RETURNS void
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE key text; field_limit int;
BEGIN
 IF p_id IS NULL OR p_id !~ '^private-import:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR p_value IS NULL OR jsonb_typeof(p_value) IS DISTINCT FROM 'object'
   OR NOT p_value ?& ARRAY['source','title','description_raw']
   OR (p_value-ARRAY['source','title','description_raw','source_url','url','organization','deadline','posted_date','location','raw_html','extra_fields'])<>'{}'::jsonb
   OR p_value->>'source' NOT IN ('url_parser','text_parser') THEN
   RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023';
 END IF;
 FOREACH key IN ARRAY ARRAY['source','title','description_raw','source_url','url'] LOOP
  IF p_value ? key AND jsonb_typeof(p_value->key) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023'; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['organization','deadline','posted_date','location','raw_html'] LOOP
  IF p_value ? key AND jsonb_typeof(p_value->key) NOT IN ('null','string') THEN RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023'; END IF;
 END LOOP;
 IF p_value->>'title' !~ '[^[:space:]]' OR length(p_value->>'title')>1000 OR p_value->>'description_raw' !~ '[^[:space:]]'
  OR length(coalesce(p_value->>'source_url',''))>8192 OR length(coalesce(p_value->>'url',''))>8192
  OR (p_value ? 'extra_fields' AND jsonb_typeof(p_value->'extra_fields') IS DISTINCT FROM 'object') THEN
  RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023';
 END IF;
 FOREACH key IN ARRAY ARRAY['organization','location','deadline','posted_date'] LOOP
  field_limit:=CASE WHEN key IN ('organization','location') THEN 2000 ELSE 128 END;
  IF length(p_value->>key)>field_limit THEN RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023'; END IF;
 END LOOP;
 -- jsonb::text is at most twice the compact size: refuse before any node walk.
 IF octet_length(p_value::text)>16777216 THEN RAISE EXCEPTION 'private_target_too_large' USING ERRCODE='54000'; END IF;
 PERFORM private.private_import_json_depth(p_value);
 IF length(p_value->>'description_raw')>5242880 OR private.target_resume_json_bytes(p_value)>8388608
  OR private.target_resume_json_bytes(coalesce(p_value->'extra_fields','{}'::jsonb))>262144 THEN
  RAISE EXCEPTION 'private_target_too_large' USING ERRCODE='54000';
 END IF;
END; $$;
REVOKE ALL ON FUNCTION private.validate_private_import(text,jsonb) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION private.save_private_import_target(p_expected_owner text,p_id text,p_expected_revision bigint,p_opportunity jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid:=private.material_user(p_expected_owner); r public.private_import_targets%ROWTYPE; stamp timestamptz:=clock_timestamp();
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
  UPDATE public.private_import_targets SET opportunity=p_opportunity,revision=revision+1,updated_at=stamp WHERE id=p_id RETURNING * INTO r;
 ELSE
  IF p_expected_revision<>0 THEN RAISE EXCEPTION 'private_target_not_found' USING ERRCODE='P0002'; END IF;
  INSERT INTO public.private_import_targets(id,owner_id,revision,opportunity,created_at,updated_at) VALUES(p_id,uid,1,p_opportunity,stamp,stamp) RETURNING * INTO r;
 END IF;
 RETURN jsonb_build_object('target',to_jsonb(r),'replayed',false);
END; $$;

CREATE FUNCTION private.read_private_import_target(p_expected_owner text,p_id text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid:=private.material_user(p_expected_owner); r public.private_import_targets%ROWTYPE;
BEGIN
 SELECT * INTO r FROM public.private_import_targets WHERE id=p_id AND owner_id=uid;
 RETURN jsonb_build_object('target',CASE WHEN r.id IS NULL THEN NULL ELSE to_jsonb(r) END);
END; $$;

CREATE FUNCTION private.delete_private_import_target(p_expected_owner text,p_id text,p_expected_revision bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid:=private.material_user(p_expected_owner); r public.private_import_targets%ROWTYPE; stamp timestamptz:=clock_timestamp();
BEGIN
 IF p_expected_revision IS NULL OR p_expected_revision<1 OR p_expected_revision>9007199254740990 THEN RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ofe-private-target:'||p_id));
 SELECT * INTO r FROM public.private_import_targets WHERE id=p_id AND owner_id=uid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'private_target_not_found' USING ERRCODE='P0002'; END IF;
 IF r.deleted_at IS NOT NULL AND r.revision=p_expected_revision+1 THEN RETURN jsonb_build_object('target',to_jsonb(r),'replayed',true); END IF;
 IF r.revision<>p_expected_revision THEN RAISE EXCEPTION 'private_target_conflict' USING ERRCODE='23505'; END IF;
 IF r.deleted_at IS NOT NULL THEN RAISE EXCEPTION 'private_target_deleted' USING ERRCODE='55000'; END IF;
 UPDATE public.private_import_targets SET opportunity=NULL,revision=revision+1,updated_at=stamp,deleted_at=stamp WHERE id=p_id RETURNING * INTO r;
 RETURN jsonb_build_object('target',to_jsonb(r),'replayed',false);
END; $$;

CREATE FUNCTION private.list_private_import_targets(p_expected_owner text,p_before_updated_at timestamptz DEFAULT NULL,p_before_id text DEFAULT NULL,p_limit integer DEFAULT 20) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid:=private.material_user(p_expected_owner); items jsonb; last_item jsonb; more boolean;
BEGIN
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 OR (p_before_updated_at IS NULL)<>(p_before_id IS NULL)
  OR (p_before_updated_at IS NOT NULL AND NOT isfinite(p_before_updated_at)) THEN RAISE EXCEPTION 'invalid_private_target' USING ERRCODE='22023'; END IF;
 SELECT coalesce(jsonb_agg(item ORDER BY updated_at DESC,id DESC),'[]'::jsonb) INTO items FROM (
  SELECT id,updated_at,(to_jsonb(t)-'opportunity')||jsonb_build_object('title',opportunity->>'title','organization',opportunity->'organization',
    'source_url',coalesce(opportunity->>'source_url',''),'url',coalesce(opportunity->>'url',''),'source',opportunity->>'source') AS item
  FROM public.private_import_targets t WHERE owner_id=uid AND deleted_at IS NULL
    AND (p_before_updated_at IS NULL OR (updated_at,id)<(p_before_updated_at,p_before_id))
  ORDER BY updated_at DESC,id DESC LIMIT p_limit+1
 ) page;
 more:=jsonb_array_length(items)>p_limit;
 IF more THEN items:=items-p_limit; END IF;
 last_item:=items->(jsonb_array_length(items)-1);
 RETURN jsonb_build_object('items',items,'next_cursor',CASE WHEN more THEN jsonb_build_object('updated_at',last_item->'updated_at','id',last_item->'id') ELSE NULL END);
END; $$;

-- Preserve private targets during the existing explicit proof-bound account merge.
CREATE FUNCTION private.merge_private_import_targets() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.private_import_targets WHERE owner_id::text=NEW.source_device_id) THEN RETURN NEW; END IF;
 IF NEW.source_device_id=NEW.target_device_id OR auth.uid()::text IS DISTINCT FROM NEW.target_device_id
  OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id::text=NEW.target_device_id AND is_anonymous IS FALSE) THEN
  RAISE EXCEPTION 'private_target_identity_changed' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:'||least(NEW.source_device_id,NEW.target_device_id)));
 PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:'||greatest(NEW.source_device_id,NEW.target_device_id)));
 UPDATE public.private_import_targets SET owner_id=NEW.target_device_id::uuid WHERE owner_id::text=NEW.source_device_id;
 RETURN NEW;
END; $$;
REVOKE ALL ON FUNCTION private.merge_private_import_targets() FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER merge_private_import_targets AFTER INSERT ON public.merged_devices FOR EACH ROW EXECUTE FUNCTION private.merge_private_import_targets();

REVOKE ALL ON FUNCTION private.save_private_import_target(text,text,bigint,jsonb) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION private.save_private_import_target(text,text,bigint,jsonb) TO authenticated;
CREATE FUNCTION public.save_private_import_target(p_expected_owner text,p_id text,p_expected_revision bigint,p_opportunity jsonb) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.save_private_import_target(p_expected_owner,p_id,p_expected_revision,p_opportunity); $$;
REVOKE ALL ON FUNCTION public.save_private_import_target(text,text,bigint,jsonb) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.save_private_import_target(text,text,bigint,jsonb) TO authenticated;

REVOKE ALL ON FUNCTION private.read_private_import_target(text,text) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION private.read_private_import_target(text,text) TO authenticated;
CREATE FUNCTION public.read_private_import_target(p_expected_owner text,p_id text) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.read_private_import_target(p_expected_owner,p_id); $$;
REVOKE ALL ON FUNCTION public.read_private_import_target(text,text) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.read_private_import_target(text,text) TO authenticated;

REVOKE ALL ON FUNCTION private.delete_private_import_target(text,text,bigint) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION private.delete_private_import_target(text,text,bigint) TO authenticated;
CREATE FUNCTION public.delete_private_import_target(p_expected_owner text,p_id text,p_expected_revision bigint) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.delete_private_import_target(p_expected_owner,p_id,p_expected_revision); $$;
REVOKE ALL ON FUNCTION public.delete_private_import_target(text,text,bigint) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.delete_private_import_target(text,text,bigint) TO authenticated;

REVOKE ALL ON FUNCTION private.list_private_import_targets(text,timestamptz,text,integer) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION private.list_private_import_targets(text,timestamptz,text,integer) TO authenticated;
CREATE FUNCTION public.list_private_import_targets(p_expected_owner text,p_before_updated_at timestamptz DEFAULT NULL,p_before_id text DEFAULT NULL,p_limit integer DEFAULT 20) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT private.list_private_import_targets(p_expected_owner,p_before_updated_at,p_before_id,p_limit); $$;
REVOKE ALL ON FUNCTION public.list_private_import_targets(text,timestamptz,text,integer) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.list_private_import_targets(text,timestamptz,text,integer) TO authenticated;
