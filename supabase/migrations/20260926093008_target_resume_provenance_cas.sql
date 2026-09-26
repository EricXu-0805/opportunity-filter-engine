-- Optional client-recorded editing provenance. This is NOT a signed server
-- attestation and does not certify a model invocation or factual correctness.
-- The strict V1 document and its independent 2 MiB limit are unchanged.
ALTER TABLE public.target_resumes ADD COLUMN provenance jsonb;
ALTER TABLE public.target_resume_versions ADD COLUMN provenance jsonb;

CREATE FUNCTION private.target_resume_provenance_shape(value jsonb, keys text[])
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
 SELECT coalesce(jsonb_typeof(value) = 'object' AND value ?& keys AND value - keys = '{}'::jsonb, false);
$$;
CREATE FUNCTION private.target_resume_provenance_string(value jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
 SELECT coalesce(jsonb_typeof(value) = 'string' AND btrim(value #>> '{}',
   E' \t\n\r\f' || chr(11) || chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194)
   || chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199) || chr(8200)
   || chr(8201) || chr(8202) || chr(8232) || chr(8233) || chr(8239) || chr(8287) || chr(12288) || chr(65279)) <> '', false);
$$;
CREATE FUNCTION private.target_resume_provenance_integer(value jsonb, minimum numeric)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path = '' AS $$
DECLARE n numeric;
BEGIN
 IF jsonb_typeof(value) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
 n := (value #>> '{}')::numeric;
 RETURN n = trunc(n) AND n >= minimum AND n <= 9007199254740991;
END;
$$;
-- Deliberately validates schema/types/document binding only. Exact replay,
-- original-line and quote checks remain the frontend protocol's responsibility.
CREATE FUNCTION private.target_resume_provenance_valid(doc jsonb, value jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path = '' AS $$
DECLARE event jsonb; change jsonb; quote jsonb; check_record jsonb; atom jsonb;
  key text; ids text[] := ARRAY[]::text[];
BEGIN
 IF value IS NULL THEN RETURN true; END IF;
 IF NOT private.target_resume_provenance_shape(value, ARRAY['version','document_id','opportunity_id','base','events'])
   OR value->'version' IS DISTINCT FROM '1'::jsonb
   OR NOT private.target_resume_provenance_string(value->'document_id')
   OR NOT private.target_resume_provenance_string(value->'opportunity_id')
   OR length(value->>'document_id') > 200 OR length(value->>'opportunity_id') > 200
   OR value->'document_id' IS DISTINCT FROM doc->'id'
   OR value->'opportunity_id' IS DISTINCT FROM doc->'opportunity_id'
   OR value->'base' IS DISTINCT FROM doc->'base'
   OR NOT private.target_resume_provenance_shape(value->'base', ARRAY['master_id','master_revision','profile_signature','source_signature','target_signature'])
   OR jsonb_typeof(value->'events') IS DISTINCT FROM 'array'
   OR private.target_resume_json_bytes(value) > 262144 THEN RETURN false; END IF;
 IF jsonb_array_length(value->'events') NOT BETWEEN 1 AND 512 THEN RETURN false; END IF;
 FOREACH key IN ARRAY ARRAY['master_id','profile_signature','source_signature','target_signature'] LOOP
   IF NOT private.target_resume_provenance_string(value->'base'->key) THEN RETURN false; END IF;
 END LOOP;
 IF NOT private.target_resume_provenance_integer(value->'base'->'master_revision', 1) THEN RETURN false; END IF;
 FOR event IN SELECT x FROM jsonb_array_elements(value->'events') AS e(x) LOOP
   IF NOT private.target_resume_provenance_shape(event, ARRAY['id','kind','changes'])
     OR NOT private.target_resume_provenance_string(event->'id') OR length(event->>'id') > 200
     OR event->>'id' = ANY(ids)
     OR jsonb_typeof(event->'kind') IS DISTINCT FROM 'string'
     OR event->>'kind' NOT IN ('manual','ai_rewrite','plan','target_order')
     OR jsonb_typeof(event->'changes') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
   ids := array_append(ids, event->>'id');
   IF jsonb_array_length(event->'changes') NOT BETWEEN 1 AND 1024 THEN RETURN false; END IF;
   FOR change IN SELECT x FROM jsonb_array_elements(event->'changes') AS c(x) LOOP
     IF NOT private.target_resume_provenance_shape(change, ARRAY['section_id','block_id','line_id','field','before','after','reason','target_evidence','source_evidence','check'])
       OR jsonb_typeof(change->'field') IS DISTINCT FROM 'string'
       OR change->>'field' NOT IN ('text','included','order')
       OR jsonb_typeof(change->'target_evidence') IS DISTINCT FROM 'array'
       OR jsonb_typeof(change->'source_evidence') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
     FOREACH key IN ARRAY ARRAY['section_id','block_id','line_id'] LOOP
       IF change->key <> 'null'::jsonb AND (NOT private.target_resume_provenance_string(change->key)
         OR length(change->>key) > 200) THEN RETURN false; END IF;
     END LOOP;
     IF change->'reason' <> 'null'::jsonb AND jsonb_typeof(change->'reason') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
     IF (change->'block_id' <> 'null'::jsonb AND change->'section_id' = 'null'::jsonb)
       OR (change->'line_id' <> 'null'::jsonb AND change->'block_id' = 'null'::jsonb)
       OR (change->>'field' = 'text' AND change->'line_id' = 'null'::jsonb)
       OR (change->>'field' = 'included' AND change->'section_id' = 'null'::jsonb)
       OR (change->>'field' = 'order' AND change->'line_id' <> 'null'::jsonb)
       OR (event->>'kind' = 'target_order' AND change->>'field' <> 'order')
       OR (event->>'kind' = 'ai_rewrite' AND change->>'field' = 'included')
       OR (event->>'kind' = 'plan' AND change->>'field' = 'order')
       OR (event->>'kind' <> 'manual' AND change->'before' = change->'after') THEN RETURN false; END IF;
     IF event->>'kind' IN ('manual','target_order') AND (change->'reason' <> 'null'::jsonb
       OR change->'target_evidence' <> '[]'::jsonb OR change->'source_evidence' <> '[]'::jsonb
       OR change->'check' <> 'null'::jsonb) THEN RETURN false; END IF;
     IF change->>'field' = 'text' THEN
       IF jsonb_typeof(change->'before') IS DISTINCT FROM 'string' OR jsonb_typeof(change->'after') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
     ELSIF change->>'field' = 'included' THEN
       IF jsonb_typeof(change->'before') IS DISTINCT FROM 'boolean' OR jsonb_typeof(change->'after') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
     ELSE
       IF jsonb_typeof(change->'before') IS DISTINCT FROM 'array' OR jsonb_typeof(change->'after') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
       IF (SELECT count(*) <> count(DISTINCT x) FROM jsonb_array_elements(change->'before') AS a(x))
         OR (SELECT count(*) <> count(DISTINCT x) FROM jsonb_array_elements(change->'after') AS a(x)) THEN RETURN false; END IF;
       FOR atom IN SELECT x FROM jsonb_array_elements((change->'before') || (change->'after')) AS a(x) LOOP
         IF NOT private.target_resume_provenance_string(atom) OR length(atom #>> '{}') > 200 THEN RETURN false; END IF;
       END LOOP;
     END IF;
     FOR quote IN SELECT x FROM jsonb_array_elements(change->'target_evidence') AS q(x) LOOP
       IF NOT private.target_resume_provenance_shape(quote, ARRAY['field','requirement_index','start','end','quote'])
         OR jsonb_typeof(quote->'field') IS DISTINCT FROM 'string'
         OR quote->>'field' NOT IN ('description','requirement')
         OR NOT private.target_resume_provenance_integer(quote->'start',0)
         OR NOT private.target_resume_provenance_integer(quote->'end',1)
         OR NOT private.target_resume_provenance_string(quote->'quote') THEN RETURN false; END IF;
       IF (quote->>'end')::numeric <= (quote->>'start')::numeric THEN RETURN false; END IF;
       IF quote->>'field' = 'description' THEN
         IF quote->'requirement_index' IS DISTINCT FROM 'null'::jsonb THEN RETURN false; END IF;
       ELSIF NOT private.target_resume_provenance_integer(quote->'requirement_index',0) THEN RETURN false;
       END IF;
     END LOOP;
     FOR quote IN SELECT x FROM jsonb_array_elements(change->'source_evidence') AS q(x) LOOP
       IF NOT private.target_resume_provenance_shape(quote, ARRAY['unit_id','start','end','quote'])
         OR NOT private.target_resume_provenance_string(quote->'unit_id') OR length(quote->>'unit_id') > 200
         OR NOT private.target_resume_provenance_integer(quote->'start',0)
         OR NOT private.target_resume_provenance_integer(quote->'end',1)
         OR NOT private.target_resume_provenance_string(quote->'quote') THEN RETURN false; END IF;
       IF (quote->>'end')::numeric <= (quote->>'start')::numeric THEN RETURN false; END IF;
     END LOOP;
     check_record := change->'check';
     IF check_record <> 'null'::jsonb THEN
       IF change->>'field' <> 'text' OR event->>'kind' NOT IN ('ai_rewrite','plan')
         OR NOT private.target_resume_provenance_shape(check_record, ARRAY['version','pipeline_version','request_id','document_signature','original','evidence'])
         OR NOT private.target_resume_provenance_shape(check_record->'evidence', ARRAY['kind','id','revision'])
         OR check_record->'evidence'->'kind' IS DISTINCT FROM '"experience"'::jsonb
         OR NOT private.target_resume_provenance_string(check_record->'evidence'->'id')
         OR length(check_record->'evidence'->>'id') > 200
         OR NOT private.target_resume_provenance_integer(check_record->'evidence'->'revision',1)
         OR jsonb_typeof(check_record->'original') IS DISTINCT FROM 'string'
         OR (check_record->>'document_signature') !~ '^v1:sha256:[a-f0-9]{64}$' THEN RETURN false; END IF;
       FOREACH key IN ARRAY ARRAY['version','pipeline_version','request_id','document_signature'] LOOP
         IF NOT private.target_resume_provenance_string(check_record->key) THEN RETURN false; END IF;
       END LOOP;
     END IF;
   END LOOP;
 END LOOP;
 RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION private.target_resume_provenance_shape(jsonb,text[]),
 private.target_resume_provenance_string(jsonb), private.target_resume_provenance_integer(jsonb,numeric),
 private.target_resume_provenance_valid(jsonb,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION private.target_resume_provenance_shape(jsonb,text[]),
 private.target_resume_provenance_string(jsonb), private.target_resume_provenance_integer(jsonb,numeric),
 private.target_resume_provenance_valid(jsonb,jsonb) TO service_role;
ALTER TABLE public.target_resumes ADD CONSTRAINT target_resumes_provenance_valid
 CHECK (private.target_resume_provenance_valid(doc, provenance));
ALTER TABLE public.target_resume_versions ADD CONSTRAINT target_resume_versions_provenance_valid
 CHECK (private.target_resume_provenance_valid(doc, provenance));

CREATE FUNCTION private.commit_target_resume_pair(
  p_expected_owner text, p_opportunity_id text, p_expected_revision bigint, p_doc jsonb, p_provenance jsonb, p_legacy boolean
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  uid uuid := auth.uid(); current_row public.target_resumes%ROWTYPE;
  next_revision bigint; stamp timestamptz := clock_timestamp();
BEGIN
  IF uid IS NULL OR p_expected_owner IS DISTINCT FROM uid::text THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  IF p_expected_revision IS NULL OR p_expected_revision < 0 OR p_expected_revision > 9007199254740991
    OR p_opportunity_id IS NULL OR length(p_opportunity_id) NOT BETWEEN 1 AND 200 OR btrim(p_opportunity_id) = ''
    OR p_doc IS NULL OR jsonb_typeof(p_doc) IS DISTINCT FROM 'object'
    OR p_doc->>'kind' IS DISTINCT FROM 'full_resume' OR p_doc->'version' IS DISTINCT FROM '1'::jsonb
    OR p_doc->>'opportunity_id' IS DISTINCT FROM p_opportunity_id
    OR jsonb_typeof(p_doc->'base') IS DISTINCT FROM 'object'
    OR jsonb_typeof(p_doc->'base_snapshot') IS DISTINCT FROM 'object'
    OR jsonb_typeof(p_doc->'target_snapshot') IS DISTINCT FROM 'object'
    OR jsonb_typeof(p_doc->'document'->'sections') IS DISTINCT FROM 'array'
    OR private.target_resume_json_bytes(p_doc) > 2097152 THEN
    RAISE EXCEPTION 'invalid_target_resume' USING ERRCODE = '22023';
  END IF;
  IF NOT private.target_resume_provenance_valid(p_doc, p_provenance) THEN
    RAISE EXCEPTION 'invalid_target_resume_provenance' USING ERRCODE = '22023';
  END IF;
  -- Shared with Flow B, which holds both owner keys in sorted order.
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || uid::text));
  IF EXISTS (SELECT 1 FROM public.merged_devices WHERE source_device_id = uid::text) THEN
    RETURN jsonb_build_object('status', 'missing');
  END IF;
  SELECT * INTO current_row FROM public.target_resumes
    WHERE owner_id = uid AND opportunity_id = p_opportunity_id FOR UPDATE;
  IF NOT FOUND THEN
    IF p_expected_revision <> 0 THEN RETURN jsonb_build_object('status', 'missing'); END IF;
    next_revision := 1;
  ELSE
    IF current_row.doc = p_doc AND (p_legacy OR current_row.provenance IS NOT DISTINCT FROM p_provenance)
      AND current_row.revision IN (p_expected_revision, p_expected_revision + 1) THEN
      RETURN jsonb_build_object('status', 'unchanged', 'revision', current_row.revision,
        'doc', current_row.doc, 'updated_at', current_row.updated_at, 'provenance', current_row.provenance);
    END IF;
    IF current_row.revision <> p_expected_revision THEN
      RETURN jsonb_build_object('status', 'conflict', 'revision', current_row.revision,
        'doc', current_row.doc, 'updated_at', current_row.updated_at, 'provenance', current_row.provenance);
    END IF;
    IF current_row.revision >= 9007199254740991 THEN RAISE EXCEPTION 'revision_limit' USING ERRCODE = '22023'; END IF;
    next_revision := current_row.revision + 1;
  END IF;
  INSERT INTO public.target_resumes(owner_id, opportunity_id, revision, doc, updated_at, provenance)
    VALUES (uid, p_opportunity_id, next_revision, p_doc, stamp, p_provenance)
    ON CONFLICT (owner_id, opportunity_id) DO UPDATE SET
      revision = EXCLUDED.revision, doc = EXCLUDED.doc, updated_at = EXCLUDED.updated_at, provenance = EXCLUDED.provenance;
  INSERT INTO public.target_resume_versions(owner_id, opportunity_id, revision, doc, updated_at, provenance)
    VALUES (uid, p_opportunity_id, next_revision, p_doc, stamp, p_provenance);
  RETURN jsonb_build_object('status', 'saved', 'revision', next_revision, 'doc', p_doc, 'updated_at', stamp, 'provenance', p_provenance);
END;
$$;
REVOKE ALL ON FUNCTION private.commit_target_resume_pair(text,text,bigint,jsonb,jsonb,boolean) FROM PUBLIC, anon, authenticated, service_role;
-- Legacy callers preserve a true no-op, but a changed document has unknown
-- provenance; old clients cannot accidentally inherit an AI check record.
CREATE OR REPLACE FUNCTION private.commit_target_resume_cas(
 p_expected_owner text, p_opportunity_id text, p_expected_revision bigint, p_doc jsonb
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $$
 SELECT private.commit_target_resume_pair(p_expected_owner,p_opportunity_id,p_expected_revision,p_doc,NULL,true);
$$;
CREATE FUNCTION private.commit_target_resume_with_provenance_cas(
 p_expected_owner text, p_opportunity_id text, p_expected_revision bigint, p_doc jsonb, p_provenance jsonb
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $$
 SELECT private.commit_target_resume_pair(p_expected_owner,p_opportunity_id,p_expected_revision,p_doc,p_provenance,false);
$$;
REVOKE ALL ON FUNCTION private.commit_target_resume_cas(text,text,bigint,jsonb),
 private.commit_target_resume_with_provenance_cas(text,text,bigint,jsonb,jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.commit_target_resume_cas(text,text,bigint,jsonb),
 private.commit_target_resume_with_provenance_cas(text,text,bigint,jsonb,jsonb) TO authenticated;
CREATE FUNCTION public.commit_target_resume_with_provenance_cas(
 p_expected_owner text, p_opportunity_id text, p_expected_revision bigint, p_doc jsonb, p_provenance jsonb
) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
 SELECT private.commit_target_resume_with_provenance_cas(p_expected_owner,p_opportunity_id,p_expected_revision,p_doc,p_provenance);
$$;
REVOKE ALL ON FUNCTION public.commit_target_resume_with_provenance_cas(text,text,bigint,jsonb,jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.commit_target_resume_with_provenance_cas(text,text,bigint,jsonb,jsonb) TO authenticated;

CREATE OR REPLACE FUNCTION private.merge_target_resumes()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  source_uid uuid; target_uid uuid;
  source_row public.target_resumes%ROWTYPE; target_row public.target_resumes%ROWTYPE;
  version_row record; next_revision bigint; stamp timestamptz := clock_timestamp();
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.target_resumes WHERE owner_id::text = NEW.source_device_id) THEN RETURN NEW; END IF;
  source_uid := NEW.source_device_id::uuid; target_uid := NEW.target_device_id::uuid;
  IF source_uid = target_uid OR auth.uid() IS DISTINCT FROM target_uid THEN
    RAISE EXCEPTION 'invalid_target_resume_merge' USING ERRCODE = '42501';
  END IF;
  -- Also serialize trusted direct tombstone insertions; same sorted order.
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || least(source_uid::text, target_uid::text)));
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || greatest(source_uid::text, target_uid::text)));
  FOR source_row IN SELECT * FROM public.target_resumes WHERE owner_id = source_uid ORDER BY opportunity_id LOOP
    SELECT * INTO target_row FROM public.target_resumes WHERE owner_id = target_uid
      AND opportunity_id = source_row.opportunity_id FOR UPDATE;
    IF NOT FOUND THEN
      INSERT INTO public.target_resumes(owner_id,opportunity_id,revision,doc,updated_at,provenance)
        VALUES (target_uid, source_row.opportunity_id, source_row.revision, source_row.doc, source_row.updated_at, source_row.provenance);
      INSERT INTO public.target_resume_versions(owner_id, opportunity_id, revision, doc, updated_at, source_revision, source_updated_at, provenance)
        SELECT target_uid, opportunity_id, revision, doc, updated_at, source_revision, source_updated_at, provenance FROM public.target_resume_versions
        WHERE owner_id = source_uid AND opportunity_id = source_row.opportunity_id;
    ELSE
      next_revision := target_row.revision;
      -- Revisions now belong to the destination sequence. Documents stay exact.
      FOR version_row IN SELECT * FROM public.target_resume_versions WHERE owner_id = source_uid
        AND opportunity_id = source_row.opportunity_id ORDER BY revision LOOP
        next_revision := next_revision + 1;
        INSERT INTO public.target_resume_versions(owner_id, opportunity_id, revision, doc, updated_at, source_revision, source_updated_at, provenance)
          VALUES (target_uid, source_row.opportunity_id, next_revision, version_row.doc, stamp,
            coalesce(version_row.source_revision, version_row.revision),
            coalesce(version_row.source_updated_at, version_row.updated_at), version_row.provenance);
      END LOOP;
      next_revision := next_revision + 1;
      -- The destination's current document wins; its new after-image is last.
      INSERT INTO public.target_resume_versions(owner_id,opportunity_id,revision,doc,updated_at,provenance)
        VALUES (target_uid, source_row.opportunity_id, next_revision, target_row.doc, stamp, target_row.provenance);
      UPDATE public.target_resumes SET revision = next_revision, updated_at = stamp
        WHERE owner_id = target_uid AND opportunity_id = source_row.opportunity_id;
    END IF;
    -- Versions cascade only after their exact documents have been copied.
    DELETE FROM public.target_resumes WHERE owner_id = source_uid AND opportunity_id = source_row.opportunity_id;
  END LOOP;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION private.merge_target_resumes() FROM PUBLIC, anon, authenticated;
