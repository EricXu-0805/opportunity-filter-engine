-- 023_merge_professor_tracking.sql
-- Fold the 022 tables (professor_follows, professor_update_reads) into the
-- cross-device merge. Without this, a device that followed professors while
-- anonymous and then signed into an existing account would strand those
-- follows under the tombstoned source uid (invisible under RLS) — exactly the
-- orphaning 017/018 exist to prevent.
--
-- This CREATE OR REPLACE reproduces migration 021's redeem_merge_grant(uuid,text)
-- body VERBATIM and only appends two table moves before the tombstone step,
-- mirroring how 021 itself appended the 020 resume tables to 018's body. The
-- 1-arg delegate (redeem_merge_grant(uuid)) resolves the 2-arg by name at
-- call time, so it picks up this body automatically — no need to redefine it.
-- mint_merge_grant and all grants/REVOKEs are unchanged. The Flow B test
-- harness re-runs every prior scenario against this replaced function, so a
-- transcription error fails CI rather than silently shipping.

CREATE OR REPLACE FUNCTION public.redeem_merge_grant(p_token uuid, p_secret text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_target       text := auth.uid()::text;
  v_target_email text := nullif(lower(trim(auth.jwt() ->> 'email')), '');
  v_source       text;
  v_bound_email  text;
  v_secret_hash  text;
  v_expires      timestamptz;
  v_consumed     timestamptz;
  v_summary      jsonb := '{}'::jsonb;
  n int;
BEGIN
  IF v_target IS NULL THEN
    RAISE EXCEPTION 'redeem_merge_grant: no authenticated session';
  END IF;

  -- Lock the grant so two concurrent redeems can't both consume it.
  SELECT source_device_id, target_email, secret_hash, expires_at, consumed_at
    INTO v_source, v_bound_email, v_secret_hash, v_expires, v_consumed
    FROM merge_grants WHERE token = p_token FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'redeem_merge_grant: invalid grant';
  END IF;
  IF v_consumed IS NOT NULL THEN
    RAISE EXCEPTION 'redeem_merge_grant: grant already used';
  END IF;
  IF v_expires < now() THEN
    RAISE EXCEPTION 'redeem_merge_grant: grant expired';
  END IF;
  -- Binding is mandatory (mint enforces exactly one). An unbound grant must
  -- never be redeemable — reject outright rather than fall through to an
  -- unchecked move (defense in depth against a row created any other way).
  IF v_bound_email IS NULL AND v_secret_hash IS NULL THEN
    RAISE EXCEPTION 'redeem_merge_grant: unbound grant is not redeemable';
  END IF;
  -- Secret-bound: only the browser holding the raw secret may redeem —
  -- defeats a stolen/leaked token. Email-bound: only the account whose email
  -- the grant was bound to may redeem.
  IF v_secret_hash IS NOT NULL THEN
    IF p_secret IS NULL
       OR encode(sha256(convert_to(p_secret, 'UTF8')), 'hex') <> v_secret_hash THEN
      RAISE EXCEPTION 'redeem_merge_grant: grant not bound to this session';
    END IF;
  ELSIF v_bound_email IS DISTINCT FROM v_target_email THEN
    RAISE EXCEPTION 'redeem_merge_grant: grant not bound to this account';
  END IF;

  -- No-op cases: consume the grant and report why (not an error — the
  -- client just skips the summary UI).
  IF v_source = v_target THEN
    UPDATE merge_grants SET consumed_at = now() WHERE token = p_token;
    RETURN jsonb_build_object('merged', false, 'reason', 'same_device');
  END IF;
  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_source) THEN
    UPDATE merge_grants SET consumed_at = now() WHERE token = p_token;
    RETURN jsonb_build_object('merged', false, 'reason', 'source_already_merged');
  END IF;

  -- ---- per-table merge (byte-identical to 021) --------------------------
  -- Rows are moved by re-keying device_id (an UPDATE), never re-inserted, so
  -- the interactions status-change trigger (fires only on interaction_type
  -- change) stays quiet and row identities/histories are preserved.

  -- favorites: set union on (device_id, opportunity_id). Drop source dupes,
  -- move the rest.
  DELETE FROM favorites b USING favorites a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.opportunity_id = b.opportunity_id;
  UPDATE favorites SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('favorites', n);

  -- interactions: last-writer-wins by updated_at on (device_id, opportunity_id).
  -- NULL-safe: updated_at is nullable, so coalesce a floor in so a real
  -- timestamp always beats NULL (and NULL vs NULL keeps the target). The
  -- status-change history is kept COHERENT with the surviving row — on each
  -- conflict we drop the LOSER's status history for that opportunity, so the
  -- merged timeline never shows phantom transitions from a dropped row.

  -- (1) source-wins conflicts: drop the target's LOSING status history first,
  --     then the losing target interaction row itself.
  DELETE FROM interaction_status_changes t
    USING interactions a, interactions b
    WHERE t.device_id = v_target AND t.opportunity_id = a.opportunity_id
      AND a.device_id = v_target AND b.device_id = v_source
      AND a.opportunity_id = b.opportunity_id
      AND coalesce(b.updated_at, '-infinity'::timestamptz)
        > coalesce(a.updated_at, '-infinity'::timestamptz);
  DELETE FROM interactions a USING interactions b
    WHERE a.device_id = v_target AND b.device_id = v_source
      AND a.opportunity_id = b.opportunity_id
      AND coalesce(b.updated_at, '-infinity'::timestamptz)
        > coalesce(a.updated_at, '-infinity'::timestamptz);

  -- (2) remaining conflicts are target-wins: drop the source's LOSING status
  --     history for those opportunities, then the losing source interaction row.
  DELETE FROM interaction_status_changes s
    USING interactions b, interactions a
    WHERE s.device_id = v_source AND s.opportunity_id = b.opportunity_id
      AND b.device_id = v_source AND a.device_id = v_target
      AND b.opportunity_id = a.opportunity_id;
  DELETE FROM interactions b USING interactions a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND b.opportunity_id = a.opportunity_id;

  -- move the survivors + their now-coherent status history.
  UPDATE interactions SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('interactions', n);
  UPDATE interaction_status_changes SET device_id = v_target WHERE device_id = v_source;

  -- profiles (id = uid): keep target's; if target has none, adopt source's;
  -- otherwise preserve source's as a profile_version so nothing is lost.
  IF NOT EXISTS (SELECT 1 FROM profiles WHERE id = v_target) THEN
    UPDATE profiles SET id = v_target WHERE id = v_source;
    GET DIAGNOSTICS n = ROW_COUNT;
    v_summary := v_summary || jsonb_build_object('profile',
      CASE WHEN n > 0 THEN 'adopted' ELSE 'none' END);
  ELSE
    INSERT INTO profile_versions (device_id, profile_data, created_at)
      SELECT v_target, profile_data, now() FROM profiles WHERE id = v_source;
    DELETE FROM profiles WHERE id = v_source;
    IF FOUND THEN
      v_summary := v_summary || jsonb_build_object('profile', 'kept_target_saved_other_as_version');
    ELSE
      v_summary := v_summary || jsonb_build_object('profile', 'kept_target');
    END IF;
  END IF;

  -- profile_versions: append-only; move all.
  UPDATE profile_versions SET device_id = v_target WHERE device_id = v_source;

  -- saved_searches: no per-name uniqueness; move all (union).
  UPDATE saved_searches SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('saved_searches', n);

  -- match_feedback: keep target's verdict on conflict (no reliable recency
  -- column); move non-conflicting votes.
  DELETE FROM match_feedback b USING match_feedback a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.opportunity_id = b.opportunity_id;
  UPDATE match_feedback SET device_id = v_target WHERE device_id = v_source;

  -- push_subscriptions: dedup by endpoint.
  DELETE FROM push_subscriptions b USING push_subscriptions a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.endpoint = b.endpoint;
  UPDATE push_subscriptions SET device_id = v_target WHERE device_id = v_source;

  -- analytics_events: append-only; move all (keeps the tombstoned uid clean).
  UPDATE analytics_events SET device_id = v_target WHERE device_id = v_source;

  -- waitlist: dedup by (email, intent); move the rest.
  DELETE FROM waitlist b USING waitlist a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND coalesce(b.email, '') = coalesce(a.email, '') AND b.intent = a.intent;
  UPDATE waitlist SET device_id = v_target WHERE device_id = v_source;

  -- feedback: append-only; move all.
  UPDATE feedback SET device_id = v_target WHERE device_id = v_source;

  -- resume_renovations (021): set union on (device_id, opportunity_id). The
  -- target's working doc for an opportunity is the user's active edit on the
  -- destination account, so keep it on conflict; drop source dupes, move the
  -- rest. (Symmetric with favorites/match_feedback conflict handling.)
  DELETE FROM resume_renovations b USING resume_renovations a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.opportunity_id = b.opportunity_id;
  UPDATE resume_renovations SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('resume_renovations', n);

  -- resume_renovation_versions (021): append-only; move all.
  UPDATE resume_renovation_versions SET device_id = v_target WHERE device_id = v_source;

  -- usage_events (021): append-only ledger; move all so post-merge quota
  -- accounting stays coherent under the surviving account.
  UPDATE usage_events SET device_id = v_target WHERE device_id = v_source;

  -- professor_follows (023): set union on (device_id, professor_id). Drop
  -- source dupes, move the rest — same conflict handling as favorites and
  -- the 021 resume tables on their UNIQUE constraints.
  DELETE FROM professor_follows b USING professor_follows a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.professor_id = b.professor_id;
  UPDATE professor_follows SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('professor_follows', n);

  -- professor_update_reads (023): read cursor per (device_id, professor_id).
  -- Keep the target's cursor on conflict (mirrors resume_renovations); at
  -- worst an already-seen update briefly shows unread again — never lost data.
  DELETE FROM professor_update_reads b USING professor_update_reads a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.professor_id = b.professor_id;
  UPDATE professor_update_reads SET device_id = v_target WHERE device_id = v_source;

  -- tracker-attachments: NOT moved in v1. Moving storage objects re-keys the
  -- backing bytes, which needs the Storage API (a service-role backend move),
  -- not raw SQL. We COUNT them so the client can honestly tell the user their
  -- files stayed on the other device (they're not lost, just not re-homed).
  SELECT count(*) INTO n FROM storage.objects
    WHERE bucket_id = 'tracker-attachments'
      AND (storage.foldername(name))[1] = v_source;
  v_summary := v_summary || jsonb_build_object('attachments_not_moved', n);

  -- Consume the grant and tombstone the source.
  UPDATE merge_grants SET consumed_at = now() WHERE token = p_token;
  INSERT INTO merged_devices (source_device_id, target_device_id, summary)
    VALUES (v_source, v_target, v_summary);

  RETURN jsonb_build_object('merged', true, 'summary', v_summary);
END;
$$;

-- Re-assert the grant surface (CREATE OR REPLACE preserves prior grants, but
-- state the invariant explicitly, matching 018's/021's footer).
REVOKE ALL ON FUNCTION public.redeem_merge_grant(uuid, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.redeem_merge_grant(uuid, text) TO authenticated;
