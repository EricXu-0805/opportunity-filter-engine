-- A manually confirmed contact is a user's report, not provider delivery proof.
-- The public invoker RPC delegates to one private definer because authenticated
-- callers must not INSERT event rows directly or choose the server timestamp.
-- Definer access is limited to an explicit auth.uid/expected-owner guard, empty
-- search_path, qualified objects and revoked PUBLIC/anon EXECUTE. No dynamic SQL.
-- Browser roles only SELECT their own immutable event snapshots. The immutable
-- trigger only lets a trusted Flow B merge move ownership, drop the later of two
-- identical snapshots, or re-key a colliding source snapshot; every kept
-- payload/timestamp field survives byte-for-byte. No synthetic history backfill.
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

-- The ID a colliding source snapshot takes during a merge. Deterministic so
-- the immutable trigger can verify the re-key instead of trusting its caller.
CREATE FUNCTION private.contact_event_merge_key(p_source_device_id text, p_event_id uuid)
RETURNS uuid LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
  SELECT md5('ofe-contact-event-merge:' || p_source_device_id || ':' || p_event_id::text)::uuid;
$$;
REVOKE ALL ON FUNCTION private.contact_event_merge_key(text,uuid) FROM PUBLIC, anon, authenticated, service_role;

-- Shared with application_events: the contact-only merge exceptions sit in a
-- nested IF so their contact_events queries are never planned for that table.
-- Both exceptions need a merged_devices row, which only Flow B inserts, and a
-- counterpart row that exists only until that merge moves the source rows.
CREATE FUNCTION private.protect_contact_event_snapshot()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    -- Trusted auth-account deletion is the only retention exception.
    IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id::text = OLD.device_id) THEN RETURN OLD; END IF;
    IF TG_TABLE_NAME = 'contact_events' THEN
      -- The merge keeps the earlier of two identical snapshots (target on a tie).
      IF EXISTS (SELECT 1 FROM public.merged_devices m JOIN public.contact_events kept
          ON kept.event_id = OLD.event_id
         AND kept.device_id = CASE WHEN m.source_device_id = OLD.device_id THEN m.target_device_id ELSE m.source_device_id END
        WHERE OLD.device_id IN (m.source_device_id, m.target_device_id)
          AND (to_jsonb(kept) - 'device_id' - 'confirmed_at') = (to_jsonb(OLD) - 'device_id' - 'confirmed_at')
          AND (kept.confirmed_at < OLD.confirmed_at
            OR (kept.confirmed_at = OLD.confirmed_at AND kept.device_id = m.target_device_id))) THEN
        RETURN OLD;
      END IF;
    END IF;
    RAISE EXCEPTION 'immutable_contact_event' USING ERRCODE = '42501';
  END IF;
  IF (to_jsonb(OLD) - 'device_id') IS DISTINCT FROM (to_jsonb(NEW) - 'device_id') THEN
    IF TG_TABLE_NAME = 'contact_events' THEN
      -- A merge source snapshot whose ID its target already holds keeps every
      -- other field and takes the derived ID.
      IF NEW.device_id = OLD.device_id AND (to_jsonb(NEW) - 'event_id') = (to_jsonb(OLD) - 'event_id')
        AND NEW.event_id = private.contact_event_merge_key(OLD.device_id, OLD.event_id)
        AND EXISTS (SELECT 1 FROM public.merged_devices m JOIN public.contact_events held
          ON held.device_id = m.target_device_id AND held.event_id = OLD.event_id
          WHERE m.source_device_id = OLD.device_id) THEN
        RETURN NEW;
      END IF;
    END IF;
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
  -- Private imports are owner rows created by a later migration. A new event
  -- needs the caller's live import; FOR SHARE makes a concurrent delete either
  -- commit first (refused here) or wait until this event is recorded.
  IF p_opportunity_id LIKE 'private-import:%' THEN
    PERFORM 1 FROM public.private_import_targets
      WHERE id = p_opportunity_id AND owner_id = uid AND deleted_at IS NULL FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'private_target_unavailable' USING ERRCODE = 'P0002'; END IF;
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
-- every snapshot/time intact. Event IDs omit the owner (a transferred event
-- stays retryable), so both accounts can hold one ID. Aborting would fail the
-- whole merge on every retry, so: an identical snapshot is one contact and
-- keeps its earlier confirmation; a different one keeps both, the source copy
-- under its derived ID. Nothing is overwritten or guessed. Contact material
-- records are immutable and keep their event ID, so a PDF recorded on a
-- re-keyed source snapshot lists under the target's same-ID snapshot.
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
  DELETE FROM public.contact_events target USING public.contact_events source
    WHERE target.device_id = NEW.target_device_id AND source.device_id = NEW.source_device_id
      AND source.event_id = target.event_id AND source.confirmed_at < target.confirmed_at
      AND (to_jsonb(source) - 'device_id' - 'confirmed_at') = (to_jsonb(target) - 'device_id' - 'confirmed_at');
  DELETE FROM public.contact_events source USING public.contact_events target
    WHERE source.device_id = NEW.source_device_id AND target.device_id = NEW.target_device_id
      AND source.event_id = target.event_id AND source.confirmed_at >= target.confirmed_at
      AND (to_jsonb(source) - 'device_id' - 'confirmed_at') = (to_jsonb(target) - 'device_id' - 'confirmed_at');
  UPDATE public.contact_events source SET event_id = private.contact_event_merge_key(NEW.source_device_id, source.event_id)
    FROM public.contact_events target
    WHERE source.device_id = NEW.source_device_id AND target.device_id = NEW.target_device_id
      AND target.event_id = source.event_id;
  UPDATE public.contact_events SET device_id = NEW.target_device_id WHERE device_id = NEW.source_device_id;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION private.merge_contact_events() FROM PUBLIC, anon, authenticated, service_role;
CREATE TRIGGER merged_devices_contact_events AFTER INSERT ON public.merged_devices
  FOR EACH ROW EXECUTE FUNCTION private.merge_contact_events();
COMMENT ON TABLE public.contact_events IS 'Immutable user-reported email snapshots; not transport delivery receipts. No legacy backfill. Trusted Flow B transfers ownership; a same-ID collision keeps the earlier identical snapshot or re-keys a different source snapshot.';

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
