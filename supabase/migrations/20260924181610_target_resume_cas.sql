-- Independent complete target resumes. Legacy resume_renovations stays revoked.
-- Current + immutable after-images commit together; browser roles cannot DML.
CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC, anon;
GRANT USAGE ON SCHEMA private TO authenticated, service_role;

-- Compact JSON UTF-8 size, matching JSON.stringify for the document's string,
-- boolean and safe-integer fields. jsonb::text alone adds separator whitespace.
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
REVOKE ALL ON FUNCTION private.target_resume_json_bytes(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION private.target_resume_json_bytes(jsonb) TO service_role;

CREATE TABLE public.target_resumes (
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  opportunity_id text NOT NULL CHECK (length(opportunity_id) BETWEEN 1 AND 200 AND btrim(opportunity_id) <> ''),
  revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
  doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object' AND doc->>'kind' = 'full_resume'
    AND doc->'version' = '1'::jsonb AND doc->>'opportunity_id' = opportunity_id
    AND private.target_resume_json_bytes(doc) <= 2097152),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (owner_id, opportunity_id)
);
CREATE TABLE public.target_resume_versions (
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  opportunity_id text NOT NULL,
  revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
  doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object' AND doc->>'kind' = 'full_resume'
    AND doc->'version' = '1'::jsonb AND doc->>'opportunity_id' = opportunity_id
    AND private.target_resume_json_bytes(doc) <= 2097152),
  updated_at timestamptz NOT NULL DEFAULT now(),
  source_revision bigint,
  source_updated_at timestamptz,
  CHECK ((source_revision IS NULL) = (source_updated_at IS NULL)
    AND (source_revision IS NULL OR source_revision BETWEEN 1 AND 9007199254740991)),
  PRIMARY KEY (owner_id, opportunity_id, revision),
  FOREIGN KEY (owner_id, opportunity_id) REFERENCES public.target_resumes(owner_id, opportunity_id) ON DELETE CASCADE
);
ALTER TABLE public.target_resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.target_resume_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.target_resumes, public.target_resume_versions FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.target_resumes, public.target_resume_versions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.target_resumes, public.target_resume_versions TO service_role;

-- The tombstone table is deliberately inaccessible to browser roles.
CREATE FUNCTION private.target_resume_owner_active(owner uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT owner = (SELECT auth.uid()) AND NOT EXISTS (
    SELECT 1 FROM public.merged_devices WHERE source_device_id = owner::text
  );
$$;
REVOKE ALL ON FUNCTION private.target_resume_owner_active(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.target_resume_owner_active(uuid) TO authenticated;
CREATE POLICY target_resumes_select_own ON public.target_resumes FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = owner_id AND private.target_resume_owner_active(owner_id));
CREATE POLICY target_resume_versions_select_own ON public.target_resume_versions FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = owner_id AND private.target_resume_owner_active(owner_id));

CREATE FUNCTION private.commit_target_resume_cas(
  p_expected_owner text, p_opportunity_id text, p_expected_revision bigint, p_doc jsonb
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
    IF current_row.doc = p_doc AND current_row.revision IN (p_expected_revision, p_expected_revision + 1) THEN
      RETURN jsonb_build_object('status', 'unchanged', 'revision', current_row.revision,
        'doc', current_row.doc, 'updated_at', current_row.updated_at);
    END IF;
    IF current_row.revision <> p_expected_revision THEN
      RETURN jsonb_build_object('status', 'conflict', 'revision', current_row.revision,
        'doc', current_row.doc, 'updated_at', current_row.updated_at);
    END IF;
    IF current_row.revision >= 9007199254740991 THEN RAISE EXCEPTION 'revision_limit' USING ERRCODE = '22023'; END IF;
    next_revision := current_row.revision + 1;
  END IF;
  INSERT INTO public.target_resumes(owner_id, opportunity_id, revision, doc, updated_at)
    VALUES (uid, p_opportunity_id, next_revision, p_doc, stamp)
    ON CONFLICT (owner_id, opportunity_id) DO UPDATE SET
      revision = EXCLUDED.revision, doc = EXCLUDED.doc, updated_at = EXCLUDED.updated_at;
  INSERT INTO public.target_resume_versions(owner_id, opportunity_id, revision, doc, updated_at)
    VALUES (uid, p_opportunity_id, next_revision, p_doc, stamp);
  RETURN jsonb_build_object('status', 'saved', 'revision', next_revision, 'doc', p_doc, 'updated_at', stamp);
END;
$$;
REVOKE ALL ON FUNCTION private.commit_target_resume_cas(text,text,bigint,jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.commit_target_resume_cas(text,text,bigint,jsonb) TO authenticated;
CREATE FUNCTION public.commit_target_resume_cas(
  p_expected_owner text, p_opportunity_id text, p_expected_revision bigint, p_doc jsonb
) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT private.commit_target_resume_cas(p_expected_owner, p_opportunity_id, p_expected_revision, p_doc);
$$;
REVOKE ALL ON FUNCTION public.commit_target_resume_cas(text,text,bigint,jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.commit_target_resume_cas(text,text,bigint,jsonb) TO authenticated;

-- Flow B appends its tombstone inside the same transaction after acquiring
-- both profile-owner locks. This trigger extends that transaction without
-- changing the existing merge RPC or reopening the legacy renovation tables.
CREATE FUNCTION private.merge_target_resumes()
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
      INSERT INTO public.target_resumes VALUES (target_uid, source_row.opportunity_id, source_row.revision, source_row.doc, source_row.updated_at);
      INSERT INTO public.target_resume_versions(owner_id, opportunity_id, revision, doc, updated_at, source_revision, source_updated_at)
        SELECT target_uid, opportunity_id, revision, doc, updated_at, source_revision, source_updated_at FROM public.target_resume_versions
        WHERE owner_id = source_uid AND opportunity_id = source_row.opportunity_id;
    ELSE
      next_revision := target_row.revision;
      -- Revisions now belong to the destination sequence. Documents stay exact.
      FOR version_row IN SELECT * FROM public.target_resume_versions WHERE owner_id = source_uid
        AND opportunity_id = source_row.opportunity_id ORDER BY revision LOOP
        next_revision := next_revision + 1;
        INSERT INTO public.target_resume_versions(owner_id, opportunity_id, revision, doc, updated_at, source_revision, source_updated_at)
          VALUES (target_uid, source_row.opportunity_id, next_revision, version_row.doc, stamp,
            coalesce(version_row.source_revision, version_row.revision),
            coalesce(version_row.source_updated_at, version_row.updated_at));
      END LOOP;
      next_revision := next_revision + 1;
      -- The destination's current document wins; its new after-image is last.
      INSERT INTO public.target_resume_versions VALUES (target_uid, source_row.opportunity_id,
        next_revision, target_row.doc, stamp);
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
CREATE TRIGGER merge_target_resumes_after_tombstone AFTER INSERT ON public.merged_devices
  FOR EACH ROW EXECUTE FUNCTION private.merge_target_resumes();
