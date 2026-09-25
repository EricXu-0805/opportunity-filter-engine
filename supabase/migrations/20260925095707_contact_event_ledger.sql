-- A manually confirmed contact is a user's report, not provider delivery proof.
-- The public invoker RPC delegates to one private definer because authenticated
-- callers must not INSERT event rows directly or choose the server timestamp.
-- Definer access is limited to an explicit auth.uid/expected-owner guard, empty
-- search_path, qualified objects and revoked PUBLIC/anon EXECUTE. No dynamic SQL.
-- Browser roles only SELECT their own immutable event snapshots. The only update
-- allowed by the immutable trigger is a trusted Flow B ownership transfer; all
-- payload/timestamp fields survive byte-for-byte. No synthetic history backfill.
CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC, anon;
GRANT USAGE ON SCHEMA private TO authenticated;

CREATE TABLE public.contact_events (
  device_id text NOT NULL,
  event_id uuid NOT NULL,
  opportunity_id text NOT NULL CHECK (length(opportunity_id) BETWEEN 1 AND 200 AND btrim(opportunity_id) <> ''),
  recipient text NOT NULL,
  subject text NOT NULL,
  body text NOT NULL,
  materials jsonb NOT NULL DEFAULT '[]'::jsonb,
  actual_sent_at timestamptz,
  confirmed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  confirmation_source text NOT NULL DEFAULT 'user_reported' CHECK (confirmation_source = 'user_reported'),
  PRIMARY KEY (device_id, event_id)
);
CREATE INDEX contact_events_owner_target_time_idx
  ON public.contact_events (device_id, opportunity_id, confirmed_at DESC, event_id DESC);
ALTER TABLE public.contact_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.contact_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.contact_events TO authenticated;
-- Existing helper also blocks a stale token from reading a merged-away owner.
CREATE POLICY contact_events_select_own ON public.contact_events FOR SELECT TO authenticated
  USING (device_id = (SELECT auth.uid())::text
    AND private.target_resume_owner_active((SELECT auth.uid())));

CREATE FUNCTION private.protect_contact_event_snapshot()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    -- Trusted auth-account deletion is the only retention exception.
    IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id::text = OLD.device_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'immutable_contact_event' USING ERRCODE = '42501';
  END IF;
  IF (to_jsonb(OLD) - 'device_id') IS DISTINCT FROM (to_jsonb(NEW) - 'device_id') THEN
    RAISE EXCEPTION 'immutable_contact_event' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION private.protect_contact_event_snapshot() FROM PUBLIC, anon, authenticated, service_role;
CREATE TRIGGER contact_events_immutable BEFORE UPDATE OR DELETE ON public.contact_events
  FOR EACH ROW EXECUTE FUNCTION private.protect_contact_event_snapshot();

CREATE FUNCTION private.confirm_contact_event(
  p_expected_device_id text, p_event_id uuid, p_opportunity_id text,
  p_recipient text, p_subject text, p_body text,
  p_materials jsonb DEFAULT '[]'::jsonb, p_actual_sent_at timestamptz DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  uid uuid := auth.uid(); stamp timestamptz;
  saved public.contact_events%ROWTYPE; summary public.interactions%ROWTYPE;
  material jsonb;
BEGIN
  IF uid IS NULL OR p_expected_device_id IS DISTINCT FROM uid::text THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  IF p_event_id IS NULL OR p_opportunity_id IS NULL OR length(p_opportunity_id) NOT BETWEEN 1 AND 200
    OR btrim(p_opportunity_id) = '' OR p_recipient IS NULL OR length(p_recipient) NOT BETWEEN 1 AND 320
    OR p_recipient ~ '[[:cntrl:]]'
    OR p_recipient !~ '^[^[:space:]@,;<>"\\]+@[^[:space:]@,;<>"\\]+\.[^[:space:]@,;<>"\\]+$'
    OR p_subject IS NULL OR length(p_subject) NOT BETWEEN 1 AND 1000 OR p_subject !~ '[^[:space:]]' OR p_subject ~ '[[:cntrl:]]'
    OR p_body IS NULL OR length(p_body) NOT BETWEEN 1 AND 100000 OR p_body !~ '[^[:space:]]'
    OR p_materials IS NULL OR jsonb_typeof(p_materials) IS DISTINCT FROM 'array'
    OR octet_length(p_materials::text) > 32768 THEN
    RAISE EXCEPTION 'invalid_contact_event' USING ERRCODE = '22023';
  END IF;
  IF jsonb_array_length(p_materials) > 32 THEN
    RAISE EXCEPTION 'invalid_contact_event' USING ERRCODE = '22023';
  END IF;
  FOR material IN SELECT value FROM jsonb_array_elements(p_materials) LOOP
    IF jsonb_typeof(material) IS DISTINCT FROM 'object'
      OR jsonb_typeof(material->'kind') IS DISTINCT FROM 'string'
      OR material->>'kind' NOT IN ('profile','target','contact_context','resume')
      OR jsonb_typeof(material->'version') IS DISTINCT FROM 'string'
      OR length(material->>'version') NOT BETWEEN 1 AND 200 OR btrim(material->>'version') = ''
      OR (material - 'kind' - 'version') <> '{}'::jsonb THEN
      RAISE EXCEPTION 'invalid_contact_event' USING ERRCODE = '22023';
    END IF;
  END LOOP;
  IF (SELECT count(*) FROM jsonb_array_elements(p_materials)) <>
     (SELECT count(DISTINCT value) FROM jsonb_array_elements(p_materials)) THEN
    RAISE EXCEPTION 'invalid_contact_event' USING ERRCODE = '22023';
  END IF;
  -- Shared with profile CAS and Flow B, preventing a write racing an ownership
  -- merge from stranding a new event on the retired source account.
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || uid::text));
  IF EXISTS (SELECT 1 FROM public.merged_devices WHERE source_device_id = uid::text)
    OR NOT EXISTS (SELECT 1 FROM auth.users WHERE id = uid) THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  stamp := clock_timestamp();
  IF p_actual_sent_at IS NOT NULL AND (NOT isfinite(p_actual_sent_at) OR p_actual_sent_at > stamp) THEN
    RAISE EXCEPTION 'invalid_contact_event' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO saved FROM public.contact_events WHERE device_id = uid::text AND event_id = p_event_id;
  IF FOUND THEN
    IF saved.opportunity_id IS DISTINCT FROM p_opportunity_id OR saved.recipient IS DISTINCT FROM p_recipient
      OR saved.subject IS DISTINCT FROM p_subject OR saved.body IS DISTINCT FROM p_body
      OR saved.materials IS DISTINCT FROM p_materials OR saved.actual_sent_at IS DISTINCT FROM p_actual_sent_at THEN
      RAISE EXCEPTION 'contact_event_conflict' USING ERRCODE = '23505';
    END IF;
    -- An exact retry never refreshes dates/reminders or re-creates a summary
    -- subsequently removed by the user. Its confirmed_at remains unchanged.
    SELECT * INTO summary FROM public.interactions WHERE device_id = uid::text AND opportunity_id = p_opportunity_id;
    RETURN jsonb_build_object('event', to_jsonb(saved), 'interaction',
      CASE WHEN summary.id IS NULL THEN NULL ELSE to_jsonb(summary) END, 'replayed', true);
  END IF;
  INSERT INTO public.contact_events(device_id,event_id,opportunity_id,recipient,subject,body,materials,actual_sent_at,confirmed_at)
    VALUES (uid::text,p_event_id,p_opportunity_id,p_recipient,p_subject,p_body,p_materials,p_actual_sent_at,stamp)
    RETURNING * INTO saved;
  -- Preserve advanced status, notes and reminders. last_contacted_at continues
  -- to mean confirmation time; actual send time belongs to the separate event.
  INSERT INTO public.interactions(device_id,opportunity_id,interaction_type,last_contacted_at,updated_at)
    VALUES (uid::text,p_opportunity_id,'contacted',stamp,stamp)
    ON CONFLICT (device_id,opportunity_id) DO UPDATE SET
      last_contacted_at = greatest(public.interactions.last_contacted_at, EXCLUDED.last_contacted_at),
      updated_at = greatest(public.interactions.updated_at, EXCLUDED.updated_at)
    RETURNING * INTO summary;
  RETURN jsonb_build_object('event', to_jsonb(saved), 'interaction', to_jsonb(summary), 'replayed', false);
END;
$$;
REVOKE ALL ON FUNCTION private.confirm_contact_event(text,uuid,text,text,text,text,jsonb,timestamptz) FROM PUBLIC, anon, service_role;
GRANT EXECUTE ON FUNCTION private.confirm_contact_event(text,uuid,text,text,text,text,jsonb,timestamptz) TO authenticated;
CREATE FUNCTION public.confirm_contact_event(
  p_expected_device_id text, p_event_id uuid, p_opportunity_id text,
  p_recipient text, p_subject text, p_body text,
  p_materials jsonb DEFAULT '[]'::jsonb, p_actual_sent_at timestamptz DEFAULT NULL
) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT private.confirm_contact_event(p_expected_device_id,p_event_id,p_opportunity_id,
    p_recipient,p_subject,p_body,p_materials,p_actual_sent_at);
$$;
REVOKE ALL ON FUNCTION public.confirm_contact_event(text,uuid,text,text,text,text,jsonb,timestamptz) FROM PUBLIC, anon, service_role;
GRANT EXECUTE ON FUNCTION public.confirm_contact_event(text,uuid,text,text,text,text,jsonb,timestamptz) TO authenticated;

-- Flow B writes the tombstone at the end of its authenticated, proof-bound
-- transaction after acquiring both owner locks. Moving only device_id keeps
-- every snapshot/time intact. Collision aborts the ENTIRE merge, rather than
-- dropping, overwriting or guessing which original confirmation to retain.
CREATE FUNCTION private.merge_contact_events()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.contact_events WHERE device_id = NEW.source_device_id) THEN RETURN NEW; END IF;
  IF NEW.source_device_id = NEW.target_device_id OR auth.uid()::text IS DISTINCT FROM NEW.target_device_id
    OR NOT EXISTS (SELECT 1 FROM auth.users WHERE id::text = NEW.target_device_id) THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || least(NEW.source_device_id, NEW.target_device_id)));
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || greatest(NEW.source_device_id, NEW.target_device_id)));
  IF EXISTS (SELECT 1 FROM public.contact_events source JOIN public.contact_events target USING (event_id)
    WHERE source.device_id = NEW.source_device_id AND target.device_id = NEW.target_device_id) THEN
    RAISE EXCEPTION 'contact_event_merge_conflict' USING ERRCODE = '23505';
  END IF;
  UPDATE public.contact_events SET device_id = NEW.target_device_id WHERE device_id = NEW.source_device_id;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION private.merge_contact_events() FROM PUBLIC, anon, authenticated, service_role;
CREATE TRIGGER merged_devices_contact_events AFTER INSERT ON public.merged_devices
  FOR EACH ROW EXECUTE FUNCTION private.merge_contact_events();
COMMENT ON TABLE public.contact_events IS 'Immutable user-reported email snapshots; not transport delivery receipts. No legacy backfill. Trusted Flow B transfers ownership only; event-id collisions abort the merge.';

-- New email PII must not outlive a deleted auth account. This trigger is only
-- invoked by a trusted delete from auth.users; it cannot be called as an RPC.
-- Share the writer/merge owner lock so a simultaneous request either commits
-- before cleanup or observes the deleted identity and fails without a write.
CREATE FUNCTION private.delete_contact_events_with_auth_user()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || OLD.id::text));
  DELETE FROM public.contact_events WHERE device_id = OLD.id::text;
  RETURN OLD;
END;
$$;
REVOKE ALL ON FUNCTION private.delete_contact_events_with_auth_user() FROM PUBLIC, anon, authenticated, service_role;
CREATE TRIGGER auth_user_delete_contact_events AFTER DELETE ON auth.users
  FOR EACH ROW EXECUTE FUNCTION private.delete_contact_events_with_auth_user();

-- This existing helper is used by the same Flow B transaction. Its operations
-- are only pg_catalog text built-ins; pin lookup rather than inherit a caller's
-- mutable search_path (reported by the local Supabase security advisor).
ALTER FUNCTION public.merge_interaction_notes(text,text) SET search_path = '';
