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
--   * mint_merge_grant(target_email) runs while still authenticated as the
--     ANONYMOUS uid-B, so auth.uid() == uid-B proves session control (and a
--     permanent account — never a legitimate merge source — is refused). It
--     records a random, single-use, 15-minute grant bound to source = uid-B
--     AND to the target email (MANDATORY — see below). Survives the auth
--     redirect in localStorage.
--   * redeem_merge_grant(token) runs after sign-in, authenticated as uid-A.
--     target = auth.uid() == uid-A ALWAYS — the merge only ever pulls the
--     grant's source INTO the caller's own account, never into a third party.
--     It refuses an unbound grant outright and otherwise requires the signed-in
--     account's email to equal the grant's bound email.
--
-- Why an attacker can't use this to steal data:
--   * To pull a victim's data they'd need a grant whose source is the
--     victim's uid — but mint sets source = auth.uid() = the caller, so
--     they can only ever mint a grant for their OWN uid. Minting the
--     victim's grant needs the victim's session.
--   * redeem always targets the caller (auth.uid()), so nobody can push
--     rows INTO a victim's account either.
--   * A LEAKED token is useless: email binding is mandatory, so redeeming it
--     requires also controlling the bound email account (i.e. already owning
--     it). Plus single-use (consumed_at + row lock) + 15-min TTL + unguessable
--     v4 token.
--   * Because the target email can't be known before OAuth provider consent,
--     the OAuth existing-account path does NOT mint (it would need an unbound,
--     theft-prone grant). OAuth-path cross-device merge is deferred until it
--     can bind the email post-consent; the email/magic-link path (bound) does
--     merge. Anonymous data that isn't merged is not lost — it stays under the
--     source uid, exactly as before this migration.

-- ---------------------------------------------------------------------------
-- Grant + tombstone tables. RLS enabled with NO policies: PostgREST clients
-- can neither read nor write these directly; only the SECURITY DEFINER
-- functions below (running as the table owner) touch them.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.merge_grants (
  token           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_device_id text NOT NULL,
  target_email    text,                       -- lowercased; mandatory (mint rejects null)
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
  v_email  text := nullif(lower(trim(p_target_email)), '');
  v_token  uuid;
BEGIN
  IF v_source IS NULL THEN
    RAISE EXCEPTION 'mint_merge_grant: no authenticated session';
  END IF;
  -- Only an ANONYMOUS session is ever a legitimate merge source — a permanent
  -- account is the destination, never the thing handed off. Gating here keeps
  -- a permanent account's data out of the grant/theft surface entirely.
  IF coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) IS NOT TRUE THEN
    RAISE EXCEPTION 'mint_merge_grant: only an anonymous session may mint a merge grant';
  END IF;
  -- Email binding is MANDATORY. An unbound grant is redeemable by ANY account
  -- that holds the token, so a leaked/stolen token would let a third party pull
  -- the source's data into their own account. Requiring the target email means
  -- a stolen token is useless unless the thief also controls that email account
  -- (in which case they own the account anyway). The OAuth existing-account
  -- path cannot know the email before provider consent, so it does NOT mint —
  -- OAuth-path cross-device merge is deferred until it can bind post-consent.
  IF v_email IS NULL THEN
    RAISE EXCEPTION 'mint_merge_grant: target email is required (email binding is mandatory)';
  END IF;
  -- Never hand off a device that's already been merged away.
  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_source) THEN
    RAISE EXCEPTION 'mint_merge_grant: device already merged';
  END IF;

  INSERT INTO merge_grants (source_device_id, target_email, expires_at)
    VALUES (v_source, v_email, now() + interval '15 minutes')
    RETURNING token INTO v_token;

  RETURN v_token;
END;
$$;

-- Supabase's default privileges grant EXECUTE on new public functions to
-- anon/authenticated/service_role, so REVOKE FROM PUBLIC alone leaves the anon
-- role able to call this. Revoke anon explicitly: only a signed-in
-- (authenticated) session should ever mint. (The body also null-guards
-- auth.uid(), so an anon call would fail anyway — this is defense in depth.)
REVOKE ALL ON FUNCTION public.mint_merge_grant(text) FROM PUBLIC, anon;
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
  -- Email binding is mandatory (mint enforces it). An unbound grant must never
  -- be redeemable — reject outright rather than fall through to an unchecked
  -- move (defense in depth against a grant row created any other way).
  IF v_bound_email IS NULL THEN
    RAISE EXCEPTION 'redeem_merge_grant: unbound grant is not redeemable';
  END IF;
  -- Only the account whose email the grant was bound to may redeem it —
  -- defeats a stolen/leaked token.
  IF v_bound_email IS DISTINCT FROM v_target_email THEN
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

-- Same as mint: revoke the default anon grant; only an authenticated (post
-- sign-in) session redeems. Body also null-guards auth.uid().
REVOKE ALL ON FUNCTION public.redeem_merge_grant(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.redeem_merge_grant(uuid) TO authenticated;
