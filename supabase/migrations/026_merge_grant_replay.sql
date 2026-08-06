-- 026: idempotent replay for redeem_merge_grant.
--
-- Problem: 017/018's redeem_merge_grant is single-use by design (consumed_at),
-- but the client cannot always tell "the merge genuinely failed" apart from
-- "the merge succeeded and the HTTP response was lost" (network drop,
-- callback page navigated away, tab closed mid-request) — a real scenario on
-- /auth/callback, which may retry redemption on the SAME token after a
-- transport failure. Pre-026, that retry always raised "grant already used",
-- which the client cannot distinguish from a genuine double-redeem attempt by
-- someone else, so it had to surface a hard failure even though the merge had
-- already landed.
--
-- Fix: record WHO redeemed a grant (redeemed_by) and WHAT it returned
-- (redeemed_result) atomically in the SAME UPDATE that consumes it. A later
-- call on an already-consumed token is idempotent — replays the stored
-- result without re-running any of the per-table merge DML — ONLY when the
-- caller re-presents the exact same proof-of-identity the original
-- redemption required (the bound email match, or the secret hash match) AND
-- is the same account that redeemed it. Everything else that reaches an
-- already-consumed row still fails closed exactly as before:
--   * a DIFFERENT uid replaying (cross-uid) — rejected, "already used"
--   * the SAME uid but wrong/missing secret — rejected, "already used"
--   * a grant consumed by pre-026 code, where redeemed_by is NULL because the
--     column did not exist yet — rejected, "already used" (we were never told
--     who redeemed it, so we cannot safely vouch for a replay)
-- The binding-proof check itself is unchanged in strength: it is computed
-- once and enforced on BOTH a fresh redemption and a replay of a consumed
-- one, so a replay can never be used to skip proof-of-identity.
--
-- This CREATE OR REPLACE reproduces 023's redeem_merge_grant(uuid,text) body
-- VERBATIM (every table move through professor_update_reads) and only adds
-- the replay-idempotency logic — same pattern 021/023 themselves used to
-- extend 018's/021's body. Losing any of those later table moves here would
-- silently regress the resume-renovation / usage-event / professor-tracking
-- merges, so nothing below is trimmed.

ALTER TABLE public.merge_grants ADD COLUMN IF NOT EXISTS redeemed_by text;
ALTER TABLE public.merge_grants ADD COLUMN IF NOT EXISTS redeemed_result jsonb;

CREATE OR REPLACE FUNCTION public.redeem_merge_grant(p_token uuid, p_secret text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_target          text := auth.uid()::text;
  v_target_email    text := nullif(lower(trim(auth.jwt() ->> 'email')), '');
  v_source          text;
  v_bound_email     text;
  v_secret_hash     text;
  v_expires         timestamptz;
  v_consumed        timestamptz;
  v_redeemed_by     text;
  v_redeemed_result jsonb;
  v_bound_ok        boolean;
  v_summary         jsonb := '{}'::jsonb;
  v_result          jsonb;
  n int;
BEGIN
  IF v_target IS NULL THEN
    RAISE EXCEPTION 'redeem_merge_grant: no authenticated session';
  END IF;

  -- Lock the grant so two concurrent redeems can't both consume it.
  SELECT source_device_id, target_email, secret_hash, expires_at, consumed_at,
         redeemed_by, redeemed_result
    INTO v_source, v_bound_email, v_secret_hash, v_expires, v_consumed,
         v_redeemed_by, v_redeemed_result
    FROM merge_grants WHERE token = p_token FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'redeem_merge_grant: invalid grant';
  END IF;

  -- Binding proof — possession of the secret (OAuth path) or the bound email
  -- (email path). Computed once so it is enforced identically whether this
  -- redemption is fresh or a replay of an already-consumed grant.
  v_bound_ok := (
    v_secret_hash IS NOT NULL
      AND p_secret IS NOT NULL
      AND encode(sha256(convert_to(p_secret, 'UTF8')), 'hex') = v_secret_hash
  ) OR (
    v_secret_hash IS NULL
      AND v_bound_email IS NOT NULL
      AND v_bound_email IS NOT DISTINCT FROM v_target_email
  );

  IF v_consumed IS NOT NULL THEN
    -- Idempotent replay: only for the exact account that redeemed it the
    -- first time, re-presenting the exact same proof. Everything else that
    -- reaches a consumed row fails closed, unchanged from pre-026 behavior.
    IF v_redeemed_by IS NOT DISTINCT FROM v_target AND v_bound_ok THEN
      RETURN v_redeemed_result;
    END IF;
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
  IF NOT v_bound_ok THEN
    IF v_secret_hash IS NOT NULL THEN
      RAISE EXCEPTION 'redeem_merge_grant: grant not bound to this session';
    ELSE
      RAISE EXCEPTION 'redeem_merge_grant: grant not bound to this account';
    END IF;
  END IF;

  -- No-op cases: consume the grant (atomically recording who + the exact
  -- replayable result) and report why (not an error — the client just skips
  -- the summary UI).
  IF v_source = v_target THEN
    v_result := jsonb_build_object('merged', false, 'reason', 'same_device');
    UPDATE merge_grants
      SET consumed_at = now(), redeemed_by = v_target, redeemed_result = v_result
      WHERE token = p_token;
    RETURN v_result;
  END IF;
  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_source) THEN
    v_result := jsonb_build_object('merged', false, 'reason', 'source_already_merged');
    UPDATE merge_grants
      SET consumed_at = now(), redeemed_by = v_target, redeemed_result = v_result
      WHERE token = p_token;
    RETURN v_result;
  END IF;

  -- ---- per-table merge (byte-identical to 023) ---------------------------
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

  v_result := jsonb_build_object('merged', true, 'summary', v_summary);

  -- Consume the grant (atomically recording who + the exact replayable
  -- result) and tombstone the source.
  UPDATE merge_grants
    SET consumed_at = now(), redeemed_by = v_target, redeemed_result = v_result
    WHERE token = p_token;
  INSERT INTO merged_devices (source_device_id, target_device_id, summary)
    VALUES (v_source, v_target, v_summary);

  RETURN v_result;
END;
$$;

-- CREATE OR REPLACE preserves the grants from 023, but re-assert explicitly
-- so this file states the complete invariant on its own.
REVOKE ALL ON FUNCTION public.redeem_merge_grant(uuid, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.redeem_merge_grant(uuid, text) TO authenticated;
