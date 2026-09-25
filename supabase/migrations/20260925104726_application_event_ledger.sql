-- Separate user-reported formal submissions from contact emails and manual
-- status changes. No opened link, generated material or status pick creates an
-- application event. Snapshot fields are immutable; no legacy backfill.
CREATE TABLE public.application_events (
  device_id text NOT NULL,
  event_id uuid NOT NULL,
  opportunity_id text NOT NULL CHECK (length(opportunity_id) BETWEEN 1 AND 200 AND btrim(opportunity_id) <> ''),
  channel text NOT NULL CHECK (channel IN ('web_form','email','other')),
  destination text NOT NULL,
  actual_submitted_at timestamptz,
  confirmed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  confirmation_source text NOT NULL DEFAULT 'user_reported' CHECK (confirmation_source = 'user_reported'),
  notes text,
  result_note text,
  next_step text,
  PRIMARY KEY (device_id,event_id)
);
CREATE INDEX application_events_owner_target_time_idx
  ON public.application_events(device_id,opportunity_id,confirmed_at DESC,event_id DESC);
ALTER TABLE public.application_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.application_events FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.application_events TO authenticated;
CREATE POLICY application_events_select_own ON public.application_events FOR SELECT TO authenticated
  USING (device_id = (SELECT auth.uid())::text
    AND private.target_resume_owner_active((SELECT auth.uid())));

-- Share the existing immutable-snapshot guard: only trusted ownership transfer
-- may change device_id, and auth-account deletion may remove its private data.
CREATE TRIGGER application_events_immutable BEFORE UPDATE OR DELETE ON public.application_events
  FOR EACH ROW EXECUTE FUNCTION private.protect_contact_event_snapshot();

-- A deliberately bounded address grammar, also checked by the client. This
-- only records an address: it does not fetch a URL or submit an application.
CREATE FUNCTION private.application_web_destination_valid(value text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE authority text; host text; port text; label text; octets text[];
BEGIN
  IF value IS NULL OR value !~* '^https?://' OR value ~ '[[:space:][:cntrl:]\\]' THEN RETURN false; END IF;
  authority := substring(value FROM '(?i)^https?://([^/?#]+)');
  IF authority IS NULL OR authority = '' OR strpos(authority,'@') > 0 THEN RETURN false; END IF;
  IF left(authority,1) = '[' THEN
    IF authority !~ '^\[[0-9a-fA-F:.]+\](:[0-9]{1,5})?$' THEN RETURN false; END IF;
    host := substring(authority FROM '^\[([^]]+)\]');
    BEGIN
      IF family(host::inet) <> 6 THEN RETURN false; END IF;
    EXCEPTION WHEN invalid_text_representation THEN RETURN false;
    END;
    port := substring(authority FROM '\]:([0-9]+)$');
  ELSE
    IF authority !~ '^[a-zA-Z0-9.-]+(:[0-9]{1,5})?$' THEN RETURN false; END IF;
    host := split_part(authority,':',1);
    IF length(host) > 253 THEN RETURN false; END IF;
    FOREACH label IN ARRAY string_to_array(host,'.') LOOP
      IF length(label) NOT BETWEEN 1 AND 63
        OR label !~ '^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$' THEN RETURN false; END IF;
    END LOOP;
    -- Numeric dotted hosts must be complete unambiguous IPv4 addresses.
    IF host ~ '^[0-9.]+$' THEN
      octets := string_to_array(host,'.');
      IF cardinality(octets) <> 4 THEN RETURN false; END IF;
      FOREACH label IN ARRAY octets LOOP
        IF length(label) > 3 OR (length(label) > 1 AND left(label,1) = '0')
          OR label::integer > 255 THEN RETURN false; END IF;
      END LOOP;
    END IF;
    port := substring(authority FROM ':([0-9]+)$');
  END IF;
  RETURN port IS NULL OR port::integer <= 65535;
END;
$$;
REVOKE ALL ON FUNCTION private.application_web_destination_valid(text) FROM PUBLIC,anon,authenticated,service_role;

-- Privileged writes are required because browser roles have no table DML.
-- Keep that capability private, auth/expected-owner guarded, explicitly granted,
-- with empty search_path and fully qualified relations. Public RPC is INVOKER.
CREATE FUNCTION private.confirm_application_event(
  p_expected_device_id text,p_event_id uuid,p_opportunity_id text,p_channel text,p_destination text,
  p_actual_submitted_at timestamptz DEFAULT NULL,p_notes text DEFAULT NULL,
  p_result_note text DEFAULT NULL,p_next_step text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  uid uuid := auth.uid(); stamp timestamptz; detail text;
  saved public.application_events%ROWTYPE; summary public.interactions%ROWTYPE;
BEGIN
  IF uid IS NULL OR p_expected_device_id IS DISTINCT FROM uid::text THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  IF p_event_id IS NULL OR p_opportunity_id IS NULL OR length(p_opportunity_id) NOT BETWEEN 1 AND 200
    OR p_opportunity_id !~ '[^[:space:]]' OR p_channel IS NULL OR p_channel NOT IN ('web_form','email','other')
    OR p_destination IS NULL OR length(p_destination) NOT BETWEEN 1 AND 2000
    OR p_destination !~ '[^[:space:]]' OR p_destination ~ '[[:cntrl:]]' THEN
    RAISE EXCEPTION 'invalid_application_event' USING ERRCODE = '22023';
  END IF;
  IF (p_channel = 'web_form' AND NOT private.application_web_destination_valid(p_destination))
    OR (p_channel = 'email' AND (length(p_destination) > 320
      OR p_destination !~ '^[^[:space:]@,;<>"\\]+@[^[:space:]@,;<>"\\]+\.[^[:space:]@,;<>"\\]+$')) THEN
    RAISE EXCEPTION 'invalid_application_event' USING ERRCODE = '22023';
  END IF;
  FOREACH detail IN ARRAY ARRAY[p_notes,p_result_note,p_next_step] LOOP
    IF detail IS NOT NULL AND (length(detail) > 4000 OR detail !~ '[^[:space:]]') THEN
      RAISE EXCEPTION 'invalid_application_event' USING ERRCODE = '22023';
    END IF;
  END LOOP;
  -- Same lock as profile CAS, account merge and auth deletion; source writes
  -- cannot land after their owner was transferred or deleted.
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || uid::text));
  IF EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=uid::text)
    OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id=uid) THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  stamp := clock_timestamp();
  IF p_actual_submitted_at IS NOT NULL AND (NOT isfinite(p_actual_submitted_at) OR p_actual_submitted_at > stamp) THEN
    RAISE EXCEPTION 'invalid_application_event' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO saved FROM public.application_events WHERE device_id=uid::text AND event_id=p_event_id;
  IF FOUND THEN
    IF saved.opportunity_id IS DISTINCT FROM p_opportunity_id OR saved.channel IS DISTINCT FROM p_channel
      OR saved.destination IS DISTINCT FROM p_destination OR saved.actual_submitted_at IS DISTINCT FROM p_actual_submitted_at
      OR saved.notes IS DISTINCT FROM p_notes OR saved.result_note IS DISTINCT FROM p_result_note
      OR saved.next_step IS DISTINCT FROM p_next_step THEN
      RAISE EXCEPTION 'application_event_conflict' USING ERRCODE = '23505';
    END IF;
    SELECT * INTO summary FROM public.interactions WHERE device_id=uid::text AND opportunity_id=p_opportunity_id;
    RETURN jsonb_build_object('event',to_jsonb(saved),'interaction',
      CASE WHEN summary.id IS NULL THEN NULL ELSE to_jsonb(summary) END,'replayed',true);
  END IF;
  INSERT INTO public.application_events(device_id,event_id,opportunity_id,channel,destination,
    actual_submitted_at,confirmed_at,notes,result_note,next_step)
    VALUES(uid::text,p_event_id,p_opportunity_id,p_channel,p_destination,p_actual_submitted_at,stamp,p_notes,p_result_note,p_next_step)
    RETURNING * INTO saved;
  -- Only a prior contact is promoted to an application. Later status, notes,
  -- reminder and contact date remain untouched. Result/next-step text stays in
  -- the event snapshot: it is not a command to rewrite the Tracker's state.
  INSERT INTO public.interactions(device_id,opportunity_id,interaction_type,updated_at)
    VALUES(uid::text,p_opportunity_id,'applied',stamp)
    ON CONFLICT(device_id,opportunity_id) DO UPDATE SET
      interaction_type=CASE WHEN public.interactions.interaction_type='contacted' THEN 'applied' ELSE public.interactions.interaction_type END,
      updated_at=greatest(public.interactions.updated_at,EXCLUDED.updated_at)
    RETURNING * INTO summary;
  RETURN jsonb_build_object('event',to_jsonb(saved),'interaction',to_jsonb(summary),'replayed',false);
END;
$$;
REVOKE ALL ON FUNCTION private.confirm_application_event(text,uuid,text,text,text,timestamptz,text,text,text) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION private.confirm_application_event(text,uuid,text,text,text,timestamptz,text,text,text) TO authenticated;
CREATE FUNCTION public.confirm_application_event(
  p_expected_device_id text,p_event_id uuid,p_opportunity_id text,p_channel text,p_destination text,
  p_actual_submitted_at timestamptz DEFAULT NULL,p_notes text DEFAULT NULL,
  p_result_note text DEFAULT NULL,p_next_step text DEFAULT NULL
) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT private.confirm_application_event(p_expected_device_id,p_event_id,p_opportunity_id,p_channel,p_destination,
    p_actual_submitted_at,p_notes,p_result_note,p_next_step);
$$;
REVOKE ALL ON FUNCTION public.confirm_application_event(text,uuid,text,text,text,timestamptz,text,text,text) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.confirm_application_event(text,uuid,text,text,text,timestamptz,text,text,text) TO authenticated;

CREATE FUNCTION private.merge_application_events()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM public.application_events WHERE device_id=NEW.source_device_id) THEN RETURN NEW; END IF;
  IF NEW.source_device_id=NEW.target_device_id OR auth.uid()::text IS DISTINCT FROM NEW.target_device_id
    OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id::text=NEW.target_device_id) THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || least(NEW.source_device_id,NEW.target_device_id)));
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || greatest(NEW.source_device_id,NEW.target_device_id)));
  IF EXISTS(SELECT 1 FROM public.application_events source JOIN public.application_events target USING(event_id)
    WHERE source.device_id=NEW.source_device_id AND target.device_id=NEW.target_device_id) THEN
    RAISE EXCEPTION 'application_event_merge_conflict' USING ERRCODE = '23505';
  END IF;
  UPDATE public.application_events SET device_id=NEW.target_device_id WHERE device_id=NEW.source_device_id;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION private.merge_application_events() FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER merged_devices_application_events AFTER INSERT ON public.merged_devices
  FOR EACH ROW EXECUTE FUNCTION private.merge_application_events();

CREATE FUNCTION private.delete_application_events_with_auth_user()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || OLD.id::text));
  DELETE FROM public.application_events WHERE device_id=OLD.id::text;
  RETURN OLD;
END;
$$;
REVOKE ALL ON FUNCTION private.delete_application_events_with_auth_user() FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER auth_user_delete_application_events AFTER DELETE ON auth.users
  FOR EACH ROW EXECUTE FUNCTION private.delete_application_events_with_auth_user();
COMMENT ON TABLE public.application_events IS 'Immutable user-reported formal submissions, not institution/provider acceptance proof. No inferred attachments or material versions; no status/link backfill.';
