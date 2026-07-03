-- 017: Cross-device anonymous-data merge (the code's "Flow B").
--
-- Context (see frontend/src/lib/supabase.ts:181-203 + R67 existing-account
-- recovery): the app is anonymous-first. Every per-user row is keyed
-- device_id = auth.uid()::text and isolated by RLS. Sign-in upgrades the
-- current anonymous user to a permanent one IN PLACE (updateUser /
-- linkIdentity), so the common cross-device story already works: build data
-- on device A, sign in on device B with the same email, and B authenticates
-- AS the same uid -> A's data is right there.
--
-- The one gap this migration closes: when device B built its OWN data while
-- still anonymous (uid-B) and THEN signs into an existing account (uid-A),
-- uid-B's rows are stranded — a different uid, invisible under RLS. Merging
-- them requires reading/writing across two uids, which RLS forbids for any
-- client. So the merge runs in SECURITY DEFINER functions (the single,
-- audited data-loss surface the code comment flagged for its own review).
--
-- Authorization model (prevents account takeover):
--   * mint_merge_grant() runs while still authenticated as uid-B, so
--     auth.uid() == uid-B proves session control. It records a random,
--     single-use, 15-minute grant token bound to source = uid-B (and,
--     optionally, to the email the user is about to sign into). The token
--     survives the auth redirect in localStorage.
--   * redeem_merge_grant(token) runs after sign-in, authenticated as uid-A.
--     target = auth.uid() == uid-A ALWAYS — the merge only ever pulls the
--     grant's source INTO the caller's own account, never into a third
--     party. Optional target_email binding means a leaked token is useless
--     unless the redeemer also controls that email account.
--
-- Why an attacker can't use this to steal data:
--   * To pull a victim's data they'd need a grant whose source is the
--     victim's uid — but mint sets source = auth.uid() = the caller, so
--     they can only ever mint a grant for their OWN uid. Minting the
--     victim's grant needs the victim's session.
--   * redeem always targets the caller (auth.uid()), so nobody can push
--     rows INTO a victim's account either.
--   * Single-use (consumed_at + row lock) + 15-min TTL + unguessable v4
--     token + optional email binding.

-- ---------------------------------------------------------------------------
-- Grant + tombstone tables. RLS enabled with NO policies: PostgREST clients
-- can neither read nor write these directly; only the SECURITY DEFINER
-- functions below (running as the table owner) touch them.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.merge_grants (
  token           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_device_id text NOT NULL,
  target_email    text,                       -- lowercased; NULL for OAuth mint
  created_at      timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz NOT NULL,
  consumed_at     timestamptz
);
ALTER TABLE public.merge_grants ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_merge_grants_source
  ON public.merge_grants (source_device_id);

CREATE TABLE IF NOT EXISTS public.merged_devices (
  source_device_id text PRIMARY KEY,          -- a device can only merge away once
  target_device_id text NOT NULL,
  merged_at        timestamptz NOT NULL DEFAULT now(),
  summary          jsonb NOT NULL DEFAULT '{}'::jsonb
);
ALTER TABLE public.merged_devices ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- mint_merge_grant: called while still on the anonymous (source) session,
-- immediately before the sign-in redirect. Returns the token to stash.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.mint_merge_grant(p_target_email text DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_source text := auth.uid()::text;
  v_token  uuid;
BEGIN
  IF v_source IS NULL THEN
    RAISE EXCEPTION 'mint_merge_grant: no authenticated session';
  END IF;
  -- Never hand off a device that's already been merged away.
  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_source) THEN
    RAISE EXCEPTION 'mint_merge_grant: device already merged';
  END IF;

  INSERT INTO merge_grants (source_device_id, target_email, expires_at)
    VALUES (
      v_source,
      nullif(lower(trim(p_target_email)), ''),
      now() + interval '15 minutes'
    )
    RETURNING token INTO v_token;

  RETURN v_token;
END;
$$;

REVOKE ALL ON FUNCTION public.mint_merge_grant(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.mint_merge_grant(text) TO authenticated;

-- ---------------------------------------------------------------------------
-- redeem_merge_grant: called after sign-in, authenticated as the permanent
-- (target) account. Moves the grant's source rows into the caller's account,
-- with per-table dedup, tombstones the source, and returns a summary.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.redeem_merge_grant(p_token uuid)
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
  v_expires      timestamptz;
  v_consumed     timestamptz;
  v_summary      jsonb := '{}'::jsonb;
  n int;
BEGIN
  IF v_target IS NULL THEN
    RAISE EXCEPTION 'redeem_merge_grant: no authenticated session';
  END IF;

  -- Lock the grant so two concurrent redeems can't both consume it.
  SELECT source_device_id, target_email, expires_at, consumed_at
    INTO v_source, v_bound_email, v_expires, v_consumed
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
  -- Email binding: if the grant was minted for a specific email, only that
  -- account may redeem it. Defends against a stolen/leaked token.
  IF v_bound_email IS NOT NULL AND v_bound_email IS DISTINCT FROM v_target_email THEN
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

  -- ---- per-table merge --------------------------------------------------
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
  DELETE FROM interactions a USING interactions b
    WHERE a.device_id = v_target AND b.device_id = v_source
      AND a.opportunity_id = b.opportunity_id
      AND b.updated_at > a.updated_at;              -- source newer -> drop target's stale row
  DELETE FROM interactions b USING interactions a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND b.opportunity_id = a.opportunity_id;      -- remaining collisions -> target wins
  UPDATE interactions SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('interactions', n);

  -- interaction_status_changes: append-only history; move all.
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

REVOKE ALL ON FUNCTION public.redeem_merge_grant(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.redeem_merge_grant(uuid) TO authenticated;
