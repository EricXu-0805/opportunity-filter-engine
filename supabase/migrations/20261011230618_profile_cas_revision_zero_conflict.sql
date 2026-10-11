-- 20261011230618_profile_cas_revision_zero_conflict.sql
-- A revision-0 patch onto a profile row that exists is a stale revision.
--
-- commit_profile_patch_cas (029) refused any revision-0 patch that was not a
-- complete create, and checked that BEFORE looking the row up. Tabs opened
-- before #1017 can still send a partial revision-0 patch for a row that
-- exists. They got incomplete_create (22023), which the client reports as a
-- transport error and resends, so the edit never saved and the form blamed
-- "another device".
--
-- The completeness check now runs only once the row is known to be absent,
-- which is the one case where the patch becomes the whole stored document.
-- Onto a row that exists, a revision-0 patch takes the same path as any
-- stale revision: 'conflict' with the current revision and row, zero writes
-- (or 'unchanged' when the row is at revision 1 and already holds every
-- value sent, the rule a complete revision-0 patch already followed). The
-- check now runs after the advisory lock and the merged-away check, so a
-- merged-away account sending a partial revision-0 patch gets 'missing'
-- rather than incomplete_create.
--
-- Everything else is 029's body unchanged; the block marked M79 below is
-- the only edit. CREATE OR REPLACE keeps the owner and grants; they are
-- restated as 029 had them.
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
    -- M79: moved here from before the advisory lock. 029 ran it before the
    -- row lookup, so a partial revision-0 patch onto a row that exists was
    -- refused instead of answered as the stale revision it is (below).
    --
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
