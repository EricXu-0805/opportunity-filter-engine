-- 027: compare-and-set profile saves.
--
-- Problem this closes (C1-R2B-CAS): the profile row was written with a blind
-- `upsert({id, profile_data})` plus a separate `profile_versions` insert.
-- Two consequences, both observed as data loss rather than as errors:
--
--   1. LOST UPDATE / RESURRECTION. Device A loads the row, the user removes
--      their resume on device B, then A's autosave (or its unmount flush, or
--      a retry of a request whose response was lost) writes the WHOLE row it
--      loaded minutes earlier. The removed resume is back, the removal is
--      gone, and nothing anywhere reported a failure. Client-side write
--      serialization (the profile-row queue) only orders writes issued by
--      ONE browser; it cannot see the other device at all.
--   2. TORN HISTORY. The current row and its version entry were two separate
--      statements from the client. A failure between them left a current row
--      with no matching history entry (or, on retry, duplicate history for
--      one logical save).
--
-- Fix: one SECURITY DEFINER function that takes the revision the caller
-- believes it is editing PLUS ONLY THE FIELDS IT ACTUALLY EDITED, and either
-- applies the write (current row + history entry + revision bump, ONE
-- transaction) or reports precisely why it did not. Direct
-- INSERT/UPDATE/DELETE on both tables is revoked from the browser roles, so a
-- client that has not been updated fails closed at the API layer instead of
-- silently resuming the blind-upsert behavior this migration exists to
-- remove. SELECT stays: reads are unchanged and still RLS-scoped.
--
-- PATCH, not full row. The server computes `stored || patch` — a top-level
-- shallow merge — so a field the caller did not send CANNOT be cleared by it,
-- whatever the caller believes the row contains. This is the difference
-- between "the /results cross-school toggle is a one-field edit" and "the
-- /results page rewrites the whole profile from a localStorage snapshot that
-- predates the resume removal." Callers that legitimately hold a whole
-- profile (the home form) still send only the keys they marked dirty; the
-- ONE case where the patch is the complete document is the initial create
-- (expected_revision = 0), where there is nothing to merge onto. History
-- stores the resulting AFTER-IMAGE, not the patch, so a version entry is
-- still a readable profile.
--
-- Idempotency is derived, not stored: a retry of a lost response arrives with
-- expected_revision = R while the row already sits at R+1 with the patch
-- already merged in — so re-merging it changes nothing. That is not a
-- conflict, it is this same write already applied, and it returns `unchanged`
-- with no second history row. No mutation-id table, no uniqueness constraint
-- (deliberately: see the profile_versions index below, which must stay
-- non-unique because Flow B moves one account's history under another's id).

-- ---------------------------------------------------------------------------
-- 1. Schema
-- ---------------------------------------------------------------------------

-- Existing rows adopt revision 1: they are a real, current profile, and the
-- first CAS write from any device will present expected_revision = 1 after
-- reading it back. Starting at 0 would make every pre-027 row look like the
-- "create it" case.
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 1;

DO $$ BEGIN
  ALTER TABLE public.profiles
    ADD CONSTRAINT profiles_revision_positive CHECK (revision >= 1);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Nullable, and pre-027 history stays NULL: those rows were written by the
-- old two-statement client and genuinely cannot be attributed to a revision.
-- Flow B also NULLs the entries it re-homes under a different account, whose
-- revision sequence they were never part of.
ALTER TABLE public.profile_versions
  ADD COLUMN IF NOT EXISTS profile_revision bigint;

DO $$ BEGIN
  ALTER TABLE public.profile_versions
    ADD CONSTRAINT profile_versions_revision_positive
    CHECK (profile_revision IS NULL OR profile_revision >= 1);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Query index, NOT a uniqueness constraint. "one history row per (owner,
-- revision)" is false by construction after a Flow B merge: the target's own
-- history and the source's re-homed history share one device_id, and a unique
-- index would make the merge itself fail.
CREATE INDEX IF NOT EXISTS profile_versions_device_revision_idx
  ON public.profile_versions (device_id, profile_revision);

-- ---------------------------------------------------------------------------
-- 2. The CAS entry point
-- ---------------------------------------------------------------------------
--
-- Returns a structured envelope rather than raising for the expected
-- outcomes — a conflict is normal operation (another device saved first), not
-- an error, and the caller needs the current revision + row to rebase onto.
-- Only genuinely unusable input raises: no session, wrong session, missing or
-- malformed revision/payload. Nothing is caught internally, so a failure of
-- the history insert aborts the whole call and the current row is NOT left
-- advanced without its matching history entry.
--
--   applied   — the row now holds (stored || patch) at revision (previous +
--               1), and exactly one history entry was appended for it
--   unchanged — merging this patch into the stored row would change nothing,
--               at either the caller's expected revision (a redundant save)
--               or one past it (this very write, whose response the caller
--               lost). Nothing was written; no duplicate history.
--   conflict  — someone else's revision is current. ZERO writes. The current
--               revision + profile are returned so the caller can rebase.
--   missing   — there is no row to update (expected_revision >= 1 but the row
--               is absent), or this account was merged away by Flow B and no
--               longer owns any profile. Fail closed; the caller must reload
--               rather than recreate a row under a dead identity.
CREATE OR REPLACE FUNCTION public.commit_profile_patch_cas(
  p_expected_device_id text,
  p_expected_revision  bigint,
  p_patch              jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_uid         text := auth.uid()::text;
  v_revision    bigint;
  v_profile     jsonb;
  v_updated_at  timestamptz;
  v_next        bigint;
  v_merged      jsonb;
BEGIN
  -- Identity. p_expected_device_id is captured at the moment the user's edit
  -- intent began, before any await; if the session has moved on since, this
  -- write belongs to nobody currently signed in. NULL is rejected explicitly
  -- because IS DISTINCT FROM would let a null-vs-null pair through.
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'commit_profile_patch_cas: no authenticated session' USING ERRCODE = '42501';
  END IF;
  IF p_expected_device_id IS NULL OR v_uid IS DISTINCT FROM p_expected_device_id THEN
    RAISE EXCEPTION 'commit_profile_patch_cas: identity_changed' USING ERRCODE = '42501';
  END IF;
  -- A missing or negative revision is not "probably a create" — it is a
  -- caller that does not know what it is overwriting, which is the entire
  -- failure mode this function exists to make impossible.
  IF p_expected_revision IS NULL OR p_expected_revision < 0 THEN
    RAISE EXCEPTION 'commit_profile_patch_cas: invalid_revision' USING ERRCODE = '22023';
  END IF;
  -- An empty patch is rejected rather than treated as a no-op save: it is
  -- always a caller bug (a save intent with nothing in it), and accepting it
  -- would let the create branch below produce an empty profile row.
  IF p_patch IS NULL OR jsonb_typeof(p_patch) <> 'object' OR p_patch = '{}'::jsonb THEN
    RAISE EXCEPTION 'commit_profile_patch_cas: invalid_patch' USING ERRCODE = '22023';
  END IF;
  -- expected_revision = 0 is the ONE case where the patch becomes the whole
  -- stored document, so a partial patch there does not "merge onto nothing" —
  -- it creates a mutilated profile that every later load then treats as
  -- canonical. The realistic way in is a single-field writer (the /results
  -- cross-school toggle, the school-confirmation gate) firing on a device
  -- whose row has not been created yet. Requiring the identity-defining core
  -- makes that structurally impossible; a one-field patch can never satisfy
  -- it. This is a deliberate, narrow coupling to the application's profile
  -- shape — see the frontend contract test that pins DEFAULT_PROFILE against
  -- this same list so the two cannot drift apart silently.
  -- Presence is not enough: a row whose college, major or grade is blank (or
  -- whitespace, which looks filled in and is not) says nothing, and once it
  -- exists every later write patches onto it and the create path never runs
  -- again. search_weight has to be a number in range for the same reason.
  -- The client refuses the identical shape (isCompleteDocument); neither side
  -- may be talked into it alone.
  IF p_expected_revision = 0 AND NOT (
    p_patch ? 'home_school' AND p_patch ? 'college' AND p_patch ? 'major'
    AND p_patch ? 'grade' AND p_patch ? 'search_weight'
    AND jsonb_typeof(p_patch -> 'college') = 'string'
    AND jsonb_typeof(p_patch -> 'major') = 'string'
    AND jsonb_typeof(p_patch -> 'grade') = 'string'
    AND btrim(p_patch ->> 'college') <> ''
    AND btrim(p_patch ->> 'major') <> ''
    AND btrim(p_patch ->> 'grade') <> ''
    AND jsonb_typeof(p_patch -> 'search_weight') = 'number'
    AND (p_patch ->> 'search_weight')::numeric BETWEEN 0 AND 100
  ) THEN
    RAISE EXCEPTION 'commit_profile_patch_cas: incomplete_create' USING ERRCODE = '22023';
  END IF;

  -- One lock key per profile owner, shared with redeem_merge_grant (see 027's
  -- CREATE OR REPLACE below). Without it, a merge can read "target has no
  -- profile", decide to adopt the source's row, and be overtaken by a CAS
  -- insert creating that very row — leaving two rows racing for one id, or
  -- the adopted row silently replacing a profile the user just wrote.
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || v_uid));

  -- Taken AFTER the lock, so it cannot observe a half-finished merge. An
  -- account that was merged into another one owns no profile any more;
  -- re-creating its row here would resurrect a dead identity's data and hide
  -- it from the account that now holds it.
  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_uid) THEN
    RETURN jsonb_build_object(
      'status', 'missing',
      'reason', 'merged_away',
      'revision', 0,
      'profile', NULL,
      'updated_at', NULL
    );
  END IF;

  SELECT revision, profile_data, updated_at
    INTO v_revision, v_profile, v_updated_at
    FROM profiles WHERE id = v_uid FOR UPDATE;

  IF NOT FOUND THEN
    IF p_expected_revision <> 0 THEN
      -- The caller believes it is editing revision N of a row that does not
      -- exist. Recreating it would silently undo whatever deleted it.
      RETURN jsonb_build_object(
        'status', 'missing',
        'reason', 'absent',
        'revision', 0,
        'profile', NULL,
        'updated_at', NULL
      );
    END IF;
    -- The ONLY branch where the patch IS the whole document: there is
    -- nothing stored to merge onto. Sending a complete canonical profile
    -- here is the CALLER's contract (the home form builds it from its own
    -- hydrated state) — the database deliberately does not guess at the
    -- application's field list, it only refuses an empty object (above).
    INSERT INTO profiles (id, profile_data, revision, created_at, updated_at)
      VALUES (v_uid, p_patch, 1, now(), now())
      RETURNING revision, profile_data, updated_at
      INTO v_revision, v_profile, v_updated_at;
    INSERT INTO profile_versions (device_id, profile_data, created_at, profile_revision)
      VALUES (v_uid, v_profile, v_updated_at, v_revision);
    RETURN jsonb_build_object(
      'status', 'applied',
      'revision', v_revision,
      'profile', v_profile,
      'updated_at', v_updated_at
    );
  END IF;

  -- Top-level shallow merge. A key absent from the patch keeps its stored
  -- value — that is the whole point of the patch shape, and it is what makes
  -- a stale caller unable to blank out a field it never knew about.
  v_merged := v_profile || p_patch;

  -- Merging changes nothing. Two ways to get here and both mean "your write
  -- is the one that is stored": a redundant save at the same revision, and a
  -- retry whose original response was lost (current = expected + 1, the patch
  -- already merged in). Neither may bump the revision or append a second
  -- history row — a retry that did would make every dropped response
  -- permanently visible as a duplicate version, and would move the revision
  -- out from under every other device for no actual change.
  IF v_merged = v_profile
     AND (v_revision = p_expected_revision OR v_revision = p_expected_revision + 1) THEN
    RETURN jsonb_build_object(
      'status', 'unchanged',
      'revision', v_revision,
      'profile', v_profile,
      'updated_at', v_updated_at
    );
  END IF;

  IF v_revision <> p_expected_revision THEN
    -- ZERO writes. The caller gets what is actually stored so it can decide
    -- whether its edit still applies (see the client's three-way rebase).
    RETURN jsonb_build_object(
      'status', 'conflict',
      'revision', v_revision,
      'profile', v_profile,
      'updated_at', v_updated_at
    );
  END IF;

  v_next := v_revision + 1;
  UPDATE profiles
     SET profile_data = v_merged,
         revision = v_next,
         updated_at = now()
   WHERE id = v_uid
   RETURNING revision, profile_data, updated_at
    INTO v_revision, v_profile, v_updated_at;

  -- The full after-image, not the patch: a version entry has to be a
  -- readable profile on its own, or the history is useless for the one thing
  -- it exists for (seeing what the profile held at the time). Same
  -- transaction, deliberately not wrapped in an exception block: if the
  -- history row cannot be written, the current row must not advance either.
  INSERT INTO profile_versions (device_id, profile_data, created_at, profile_revision)
    VALUES (v_uid, v_profile, v_updated_at, v_revision);

  RETURN jsonb_build_object(
    'status', 'applied',
    'revision', v_revision,
    'profile', v_profile,
    'updated_at', v_updated_at
  );
END;
$$;

REVOKE ALL ON FUNCTION public.commit_profile_patch_cas(text, bigint, jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.commit_profile_patch_cas(text, bigint, jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.commit_profile_patch_cas(text, bigint, jsonb) TO service_role;

-- ---------------------------------------------------------------------------
-- 3. Close the direct-DML path
-- ---------------------------------------------------------------------------
-- Supabase grants the browser roles table privileges through its managed
-- default privileges, so the RLS policies above were the only thing shaping
-- writes. With the CAS function in place, an UNCONDITIONAL upsert from a
-- browser is exactly the bug this migration removes — revoke it so a stale
-- deployed bundle fails closed (permission denied) instead of quietly keeping
-- the lost-update behavior. SELECT is untouched: reads are unchanged, still
-- policy-scoped to the caller's own row.
--
-- profile_versions loses INSERT too: history is now written only as part of a
-- CAS transaction, so a client-issued insert could only ever produce an entry
-- with no corresponding revision.
-- PUBLIC is revoked alongside the two named roles: has_table_privilege('anon',
-- …) is true whenever PUBLIC holds the privilege, so revoking only the named
-- roles would leave the grant fully in force through PUBLIC.
REVOKE INSERT, UPDATE, DELETE ON public.profiles FROM PUBLIC, anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.profile_versions FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 4. Flow B: share the CAS lock key
-- ---------------------------------------------------------------------------
-- This CREATE OR REPLACE reproduces 026's redeem_merge_grant(uuid, text) body
-- — the current canonical one, including every per-table move through
-- professor_update_reads and 026's own replay-idempotency logic — and adds
-- exactly FOUR things. A future migration that copies this body forward must
-- carry all four; losing any of them is silent data loss, not a style change:
--   1. the shared per-owner advisory lock, taken on BOTH accounts in a fixed
--      (sorted) order so two merges involving the same pair cannot deadlock;
--   2. the TARGET tombstone guard — a merge into an account that was itself
--      merged away buries the data where nobody can reach it (reverse merge
--      A->B then B->A, or chaining A->B after B->C). Fails closed, before any
--      DML, without consuming the grant;
--   3. profile_revision handling for the two profile outcomes (adopt vs
--      archive);
--   4. nothing else. Trimming any table move here would silently regress the
--      resume-renovation / usage-event / professor-tracking merges.
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
  v_adopted         boolean := false;
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

  -- No-op case: same device. Nothing moves, so no profile lock is needed.
  IF v_source = v_target THEN
    v_result := jsonb_build_object('merged', false, 'reason', 'same_device');
    UPDATE merge_grants
      SET consumed_at = now(), redeemed_by = v_target, redeemed_result = v_result
      WHERE token = p_token;
    RETURN v_result;
  END IF;

  -- 027: the SAME key commit_profile_cas takes, on BOTH accounts, before the
  -- merged_devices scan and before anything reads `profiles`. This is what
  -- makes "target has no profile, adopt the source's" safe: a CAS on either
  -- account is either fully applied before this point or fully blocked until
  -- the merge commits and its own merged-away check can see the tombstone.
  -- Sorted so a merge of A->B and a merge of B->A cannot deadlock each other.
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || least(v_source, v_target)));
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || greatest(v_source, v_target)));

  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_source) THEN
    v_result := jsonb_build_object('merged', false, 'reason', 'source_already_merged');
    UPDATE merge_grants
      SET consumed_at = now(), redeemed_by = v_target, redeemed_result = v_result
      WHERE token = p_token;
    RETURN v_result;
  END IF;
  -- 027: the TARGET must be alive too. Pre-027 only the source was checked,
  -- which left two ways to move data into an account that no longer exists:
  --   * reverse merge — A->B tombstones A; a later B->A passes the source
  --     check (B is not tombstoned) and moves everything BACK into the dead
  --     A, then tombstones B as well, leaving both accounts dead and the data
  --     reachable from neither;
  --   * chain onto a dead target — B->C tombstones B; a later A->B moves A's
  --     data into B, which C's owner will never see.
  -- Both are silent data loss, so this fails closed with a stable message and
  -- WITHOUT consuming the grant: raising rolls the whole call back, and the
  -- situation is recoverable (sign in to the account that actually survived).
  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_target) THEN
    RAISE EXCEPTION 'redeem_merge_grant: target already merged';
  END IF;

  -- ---- per-table merge (byte-identical to 023/026 apart from profiles/
  -- profile_versions revision handling, below) -----------------------------
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

  -- profiles (id = uid): keep target's; if target has none, adopt source's
  -- (revision sequence moves with the row — it is the same document under a
  -- new owner); otherwise preserve source's as a profile_version so nothing
  -- is lost. That archived copy is explicitly revision-less: it belongs to a
  -- sequence the target account never had, and stamping the target's numbers
  -- on it would make the history lie about what revision N contained.
  IF NOT EXISTS (SELECT 1 FROM profiles WHERE id = v_target) THEN
    UPDATE profiles SET id = v_target WHERE id = v_source;
    GET DIAGNOSTICS n = ROW_COUNT;
    v_adopted := n > 0;
    v_summary := v_summary || jsonb_build_object('profile',
      CASE WHEN n > 0 THEN 'adopted' ELSE 'none' END);
  ELSE
    INSERT INTO profile_versions (device_id, profile_data, created_at, profile_revision)
      SELECT v_target, profile_data, now(), NULL FROM profiles WHERE id = v_source;
    DELETE FROM profiles WHERE id = v_source;
    IF FOUND THEN
      v_summary := v_summary || jsonb_build_object('profile', 'kept_target_saved_other_as_version');
    ELSE
      v_summary := v_summary || jsonb_build_object('profile', 'kept_target');
    END IF;
  END IF;

  -- profile_versions: append-only; move all. Revisions survive the move only
  -- when the current row moved with them (adoption); otherwise they describe
  -- a sequence that no longer exists under this owner.
  IF v_adopted THEN
    UPDATE profile_versions SET device_id = v_target WHERE device_id = v_source;
  ELSE
    UPDATE profile_versions SET device_id = v_target, profile_revision = NULL
      WHERE device_id = v_source;
  END IF;

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

REVOKE ALL ON FUNCTION public.redeem_merge_grant(uuid, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.redeem_merge_grant(uuid, text) TO authenticated;
