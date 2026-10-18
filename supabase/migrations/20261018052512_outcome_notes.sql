-- Later outcomes and corrections on a tracked target's contact and application
-- records: one append-only list per target. Each note is one sentence in the
-- student's own words and the time the database saved it; a correction is a
-- new note. Browser roles only SELECT their own rows; the append RPC is the
-- only writer and only INSERTs. The shared snapshot trigger refuses UPDATE and
-- DELETE from every role, except a Flow B ownership move and the cleanup that
-- follows auth-account deletion. Nothing is backfilled from interactions.notes.
CREATE TABLE public.outcome_notes (
  device_id text NOT NULL,
  note_id uuid NOT NULL,
  opportunity_id text NOT NULL CHECK (length(opportunity_id) BETWEEN 1 AND 200 AND btrim(opportunity_id) <> ''),
  body text NOT NULL CHECK (length(body) BETWEEN 1 AND 300 AND body ~ '[^[:space:]]' AND body !~ '[[:cntrl:]]'),
  outcome text CHECK (outcome IN ('replied','interviewing','rejected','dismissed')),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (device_id,note_id)
);
CREATE INDEX outcome_notes_owner_target_time_idx
  ON public.outcome_notes(device_id,opportunity_id,recorded_at DESC,note_id DESC);
ALTER TABLE public.outcome_notes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.outcome_notes FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.outcome_notes TO authenticated;
CREATE POLICY outcome_notes_select_own ON public.outcome_notes FOR SELECT TO authenticated
  USING (device_id = (SELECT auth.uid())::text
    AND private.target_resume_owner_active((SELECT auth.uid())));
CREATE TRIGGER outcome_notes_immutable BEFORE UPDATE OR DELETE ON public.outcome_notes
  FOR EACH ROW EXECUTE FUNCTION private.protect_contact_event_snapshot();

-- Same shape as confirm_application_event: a private auth/expected-owner
-- guarded definer behind a public invoker RPC. An outcome is the status the
-- student chose with the note; it sets interaction_type as the status menu
-- does, so the reminder cron's status filter (contacted/applied only) stops a
-- follow-up on replied, interviewing, rejected or dismissed. Notes, reminder
-- date and contact date on the summary stay as they are.
CREATE FUNCTION private.append_outcome_note(
  p_expected_device_id text,p_note_id uuid,p_opportunity_id text,p_body text,p_outcome text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  uid uuid := auth.uid(); stamp timestamptz;
  saved public.outcome_notes%ROWTYPE; summary public.interactions%ROWTYPE;
BEGIN
  IF uid IS NULL OR p_expected_device_id IS DISTINCT FROM uid::text THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  IF p_note_id IS NULL OR p_opportunity_id IS NULL OR length(p_opportunity_id) NOT BETWEEN 1 AND 200
    OR p_opportunity_id !~ '[^[:space:]]' OR p_body IS NULL OR length(p_body) NOT BETWEEN 1 AND 300
    OR p_body !~ '[^[:space:]]' OR p_body ~ '[[:cntrl:]]'
    OR (p_outcome IS NOT NULL AND p_outcome NOT IN ('replied','interviewing','rejected','dismissed')) THEN
    RAISE EXCEPTION 'invalid_outcome_note' USING ERRCODE = '22023';
  END IF;
  -- Lock order as confirm_application_event: auth row, then owner advisory.
  PERFORM 1 FROM auth.users WHERE id=uid FOR KEY SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501'; END IF;
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || uid::text));
  IF EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=uid::text) THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  SELECT * INTO saved FROM public.outcome_notes WHERE device_id=uid::text AND note_id=p_note_id;
  IF FOUND THEN
    IF saved.opportunity_id IS DISTINCT FROM p_opportunity_id OR saved.body IS DISTINCT FROM p_body
      OR saved.outcome IS DISTINCT FROM p_outcome THEN
      RAISE EXCEPTION 'outcome_note_conflict' USING ERRCODE = '23505';
    END IF;
    -- An exact retry returns the saved note and does not apply its outcome
    -- again over a status the student changed since.
    SELECT * INTO summary FROM public.interactions WHERE device_id=uid::text AND opportunity_id=p_opportunity_id;
    RETURN jsonb_build_object('note',to_jsonb(saved),'interaction',
      CASE WHEN summary.id IS NULL THEN NULL ELSE to_jsonb(summary) END,'replayed',true);
  END IF;
  IF p_opportunity_id LIKE 'private-import:%' THEN
    PERFORM 1 FROM public.private_import_targets
      WHERE id=p_opportunity_id AND owner_id=uid AND deleted_at IS NULL FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'private_target_unavailable' USING ERRCODE = 'P0002'; END IF;
  END IF;
  stamp := clock_timestamp();
  INSERT INTO public.outcome_notes(device_id,note_id,opportunity_id,body,outcome,recorded_at)
    VALUES(uid::text,p_note_id,p_opportunity_id,p_body,p_outcome,stamp)
    RETURNING * INTO saved;
  IF p_outcome IS NOT NULL THEN
    INSERT INTO public.interactions(device_id,opportunity_id,interaction_type,updated_at)
      VALUES(uid::text,p_opportunity_id,p_outcome,stamp)
      ON CONFLICT(device_id,opportunity_id) DO UPDATE SET
        interaction_type=EXCLUDED.interaction_type,
        updated_at=greatest(public.interactions.updated_at,EXCLUDED.updated_at)
      RETURNING * INTO summary;
  ELSE
    SELECT * INTO summary FROM public.interactions WHERE device_id=uid::text AND opportunity_id=p_opportunity_id;
  END IF;
  RETURN jsonb_build_object('note',to_jsonb(saved),'interaction',
    CASE WHEN summary.id IS NULL THEN NULL ELSE to_jsonb(summary) END,'replayed',false);
END;
$$;
REVOKE ALL ON FUNCTION private.append_outcome_note(text,uuid,text,text,text) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION private.append_outcome_note(text,uuid,text,text,text) TO authenticated;
CREATE FUNCTION public.append_outcome_note(
  p_expected_device_id text,p_note_id uuid,p_opportunity_id text,p_body text,p_outcome text DEFAULT NULL
) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT private.append_outcome_note(p_expected_device_id,p_note_id,p_opportunity_id,p_body,p_outcome);
$$;
REVOKE ALL ON FUNCTION public.append_outcome_note(text,uuid,text,text,text) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.append_outcome_note(text,uuid,text,text,text) TO authenticated;

-- Flow B moves ownership only, as for application_events; a note ID both
-- accounts hold aborts the whole merge rather than drop or rewrite a note.
CREATE FUNCTION private.merge_outcome_notes()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM public.outcome_notes WHERE device_id=NEW.source_device_id) THEN RETURN NEW; END IF;
  IF NEW.source_device_id=NEW.target_device_id OR auth.uid()::text IS DISTINCT FROM NEW.target_device_id
    OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id::text=NEW.target_device_id) THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || least(NEW.source_device_id,NEW.target_device_id)));
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || greatest(NEW.source_device_id,NEW.target_device_id)));
  IF EXISTS(SELECT 1 FROM public.outcome_notes source JOIN public.outcome_notes target USING(note_id)
    WHERE source.device_id=NEW.source_device_id AND target.device_id=NEW.target_device_id) THEN
    RAISE EXCEPTION 'outcome_note_merge_conflict' USING ERRCODE = '23505';
  END IF;
  UPDATE public.outcome_notes SET device_id=NEW.target_device_id WHERE device_id=NEW.source_device_id;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION private.merge_outcome_notes() FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER merged_devices_outcome_notes AFTER INSERT ON public.merged_devices
  FOR EACH ROW EXECUTE FUNCTION private.merge_outcome_notes();

CREATE FUNCTION private.delete_outcome_notes_with_auth_user()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || OLD.id::text));
  DELETE FROM public.outcome_notes WHERE device_id=OLD.id::text;
  RETURN OLD;
END;
$$;
REVOKE ALL ON FUNCTION private.delete_outcome_notes_with_auth_user() FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER auth_user_delete_outcome_notes AFTER DELETE ON auth.users
  FOR EACH ROW EXECUTE FUNCTION private.delete_outcome_notes_with_auth_user();
COMMENT ON TABLE public.outcome_notes IS 'Append-only student-written outcome notes per tracked target; a correction is a new note. Not evidence that a reply, interview or rejection happened. Trusted Flow B transfers ownership; auth-account deletion removes them.';
