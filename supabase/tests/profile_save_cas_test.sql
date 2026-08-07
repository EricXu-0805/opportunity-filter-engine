-- Migration 027: commit_profile_patch_cas + the Flow B interactions it shares
-- a lock key with.
--
-- Run against the same ephemeral cluster as flow_b_merge_test.sql (loaded:
-- _stubs.sql -> migrations through 027, with the Supabase managed table
-- grants mirrored in immediately before 027 so its REVOKE is proven to be the
-- thing that removes them — see run_flow_b_test.sh). UUIDs below are disjoint
-- from every actor used in the other test files.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

-- =====================================================================
-- 1. Create -> patch -> patch. The headline property: a key the caller did
--    NOT send keeps its stored value.
-- =====================================================================
DO $$
DECLARE
  u text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a01';
  res jsonb;
  c int;
  v_profile jsonb;
BEGIN
  PERFORM set_config('test.uid', u, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);

  -- ---- first save: expected_revision 0, patch IS the whole canonical row ----
  res := commit_profile_patch_cas(u, 0, jsonb_build_object(
    'home_school', 'uiuc', 'search_weight', 50,
    'college', 'Grainger', 'major', 'CS', 'grade', 'Junior',
    'resume_text', 'my resume', 'coursework', jsonb_build_array('ECE 220')
  ));
  IF res->>'status' IS DISTINCT FROM 'applied' THEN
    RAISE EXCEPTION 'TEST FAIL cas-create: want applied got %', res;
  END IF;
  IF (res->>'revision')::bigint IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'TEST FAIL cas-create: want revision 1 got %', res;
  END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = u;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-create: want 1 history row got %', c; END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = u AND profile_revision = 1;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-create: history row not stamped with revision 1'; END IF;

  -- ---- R1 -> R2 via a ONE-FIELD patch ----
  res := commit_profile_patch_cas(u, 1, '{"major":"ECE"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'applied' OR (res->>'revision')::bigint IS DISTINCT FROM 2 THEN
    RAISE EXCEPTION 'TEST FAIL cas-patch: want applied@2 got %', res;
  END IF;
  v_profile := res->'profile';
  IF v_profile->>'major' IS DISTINCT FROM 'ECE' THEN
    RAISE EXCEPTION 'TEST FAIL cas-patch: patch not applied, got %', v_profile;
  END IF;
  -- THE point of the patch shape: fields the caller never sent are untouched.
  IF v_profile->>'resume_text' IS DISTINCT FROM 'my resume'
     OR v_profile->>'college' IS DISTINCT FROM 'Grainger'
     OR v_profile->'coursework' IS DISTINCT FROM jsonb_build_array('ECE 220') THEN
    RAISE EXCEPTION 'TEST FAIL cas-patch: omitted fields were cleared, got %', v_profile;
  END IF;
  -- History stores the full AFTER-IMAGE, not the patch.
  SELECT profile_data INTO v_profile FROM profile_versions
    WHERE device_id = u AND profile_revision = 2;
  IF v_profile->>'resume_text' IS DISTINCT FROM 'my resume' OR v_profile->>'major' IS DISTINCT FROM 'ECE' THEN
    RAISE EXCEPTION 'TEST FAIL cas-patch: history stored the patch, not the after-image: %', v_profile;
  END IF;

  -- ---- redundant save at the SAME revision: unchanged, no history, no bump ----
  res := commit_profile_patch_cas(u, 2, '{"major":"ECE"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'unchanged' OR (res->>'revision')::bigint IS DISTINCT FROM 2 THEN
    RAISE EXCEPTION 'TEST FAIL cas-redundant: want unchanged@2 got %', res;
  END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = u;
  IF c IS DISTINCT FROM 2 THEN RAISE EXCEPTION 'TEST FAIL cas-redundant: history grew to %', c; END IF;

  -- ---- lost response: same expected revision + same patch, already applied ----
  res := commit_profile_patch_cas(u, 1, '{"major":"ECE"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'unchanged' OR (res->>'revision')::bigint IS DISTINCT FROM 2 THEN
    RAISE EXCEPTION 'TEST FAIL cas-lost-response: want unchanged@2 got %', res;
  END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = u;
  IF c IS DISTINCT FROM 2 THEN RAISE EXCEPTION 'TEST FAIL cas-lost-response: duplicate history (%)', c; END IF;
  SELECT revision INTO c FROM profiles WHERE id = u;
  IF c IS DISTINCT FROM 2 THEN RAISE EXCEPTION 'TEST FAIL cas-lost-response: revision moved to %', c; END IF;
END;
$$;

-- =====================================================================
-- 2. Two devices at the same revision: exactly one applies, the loser
--    writes NOTHING. Then the résumé-delete-vs-stale-unrelated-edit case
--    this whole migration exists for.
-- =====================================================================
DO $$
DECLARE
  u text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a02';
  res jsonb;
  c int;
  hist_before int;
  v_profile jsonb;
BEGIN
  PERFORM set_config('test.uid', u, false);

  PERFORM commit_profile_patch_cas(u, 0, jsonb_build_object(
    'home_school', 'uiuc', 'search_weight', 50,
    'college', 'Grainger', 'major', 'CS', 'grade', 'Junior',
    'resume_text', 'sensitive resume text', 'coursework', jsonb_build_array('ECE 220')
  ));

  -- Device A (still holding revision 1) removes the résumé.
  res := commit_profile_patch_cas(u, 1, '{"resume_text":"","coursework":[]}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'applied' OR (res->>'revision')::bigint IS DISTINCT FROM 2 THEN
    RAISE EXCEPTION 'TEST FAIL cas-remove: want applied@2 got %', res;
  END IF;

  SELECT count(*) INTO hist_before FROM profile_versions WHERE device_id = u;

  -- Device B is STILL on revision 1 — it never saw the removal. Its edit is
  -- about the college, nothing to do with the résumé. Pre-027 it shipped the
  -- whole row it loaded and the résumé came back.
  res := commit_profile_patch_cas(u, 1, '{"college":"LAS"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'conflict' THEN
    RAISE EXCEPTION 'TEST FAIL cas-stale: want conflict got %', res;
  END IF;
  IF (res->>'revision')::bigint IS DISTINCT FROM 2 THEN
    RAISE EXCEPTION 'TEST FAIL cas-stale: conflict must report the CURRENT revision, got %', res;
  END IF;
  IF res->'profile'->>'resume_text' IS DISTINCT FROM '' THEN
    RAISE EXCEPTION 'TEST FAIL cas-stale: conflict must return the current row for rebase, got %', res;
  END IF;
  -- ZERO writes on conflict.
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = u;
  IF c IS DISTINCT FROM hist_before THEN RAISE EXCEPTION 'TEST FAIL cas-stale: conflict wrote history (% -> %)', hist_before, c; END IF;
  SELECT profile_data INTO v_profile FROM profiles WHERE id = u;
  IF v_profile->>'college' IS DISTINCT FROM 'Grainger' THEN
    RAISE EXCEPTION 'TEST FAIL cas-stale: conflict mutated the row: %', v_profile;
  END IF;

  -- B rebases onto revision 2 and re-sends the SAME one-field patch. Its edit
  -- lands; the résumé stays removed.
  res := commit_profile_patch_cas(u, 2, '{"college":"LAS"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'applied' OR (res->>'revision')::bigint IS DISTINCT FROM 3 THEN
    RAISE EXCEPTION 'TEST FAIL cas-rebase: want applied@3 got %', res;
  END IF;
  v_profile := res->'profile';
  IF v_profile->>'college' IS DISTINCT FROM 'LAS' THEN
    RAISE EXCEPTION 'TEST FAIL cas-rebase: edit lost, got %', v_profile;
  END IF;
  IF v_profile->>'resume_text' IS DISTINCT FROM '' OR v_profile->'coursework' IS DISTINCT FROM '[]'::jsonb THEN
    RAISE EXCEPTION 'TEST FAIL cas-rebase: removed résumé was resurrected: %', v_profile;
  END IF;
END;
$$;

-- =====================================================================
-- 3. Fail-closed input + session handling. Nothing here may write.
-- =====================================================================
DO $$
DECLARE
  u text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a03';
  other text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a04';
  res jsonb;
  c int;
BEGIN
  PERFORM set_config('test.uid', u, false);
  PERFORM commit_profile_patch_cas(u, 0, '{"home_school":"uiuc","search_weight":50,"college":"Grainger","major":"CS","grade":"Junior"}'::jsonb);

  -- no session
  PERFORM set_config('test.uid', '', false);
  BEGIN
    PERFORM commit_profile_patch_cas(u, 1, '{"major":"X"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-no-session: should have raised';
  EXCEPTION WHEN sqlstate '42501' THEN NULL;
  END;

  -- wrong uid: the session is `other`, the intent was captured as `u`
  PERFORM set_config('test.uid', other, false);
  BEGIN
    PERFORM commit_profile_patch_cas(u, 1, '{"major":"X"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-wrong-uid: should have raised';
  EXCEPTION WHEN sqlstate '42501' THEN NULL;
  END;
  -- ... and the `other` session did not get a row created for itself either
  SELECT count(*) INTO c FROM profiles WHERE id = other;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL cas-wrong-uid: wrote under the live session'; END IF;

  PERFORM set_config('test.uid', u, false);
  -- null expected device id
  BEGIN
    PERFORM commit_profile_patch_cas(NULL, 1, '{"major":"X"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-null-device: should have raised';
  EXCEPTION WHEN sqlstate '42501' THEN NULL;
  END;
  -- null / negative revision
  BEGIN
    PERFORM commit_profile_patch_cas(u, NULL, '{"major":"X"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-null-revision: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  BEGIN
    PERFORM commit_profile_patch_cas(u, -1, '{"major":"X"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-negative-revision: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- null / non-object / empty patch
  BEGIN
    PERFORM commit_profile_patch_cas(u, 1, NULL);
    RAISE EXCEPTION 'TEST FAIL cas-null-patch: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  BEGIN
    PERFORM commit_profile_patch_cas(u, 1, '["not","an","object"]'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-array-patch: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  BEGIN
    PERFORM commit_profile_patch_cas(u, 1, '{}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-empty-patch: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- A create carrying only ONE field — the exact shape a single-field writer
  -- (cross-school toggle, school gate) would send on a device whose row does
  -- not exist yet. Accepting it would make a mutilated row canonical.
  BEGIN
    PERFORM commit_profile_patch_cas(u, 0, '{"include_cross_school":true}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-partial-create: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  BEGIN
    PERFORM commit_profile_patch_cas(u, 0, '{"home_school":"uiuc"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-partial-create-school: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- Missing exactly one required key is still incomplete.
  BEGIN
    PERFORM commit_profile_patch_cas(u, 0,
      '{"home_school":"uiuc","college":"C","major":"M","grade":"G"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-partial-create-weight: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;

  -- Present but MEANINGLESS is refused too: a row whose required fields are
  -- blank (or whitespace, which looks filled in) would become canonical and
  -- the create path would never run again.
  BEGIN
    PERFORM commit_profile_patch_cas(u, 0,
      '{"home_school":"uiuc","college":"   ","major":"M","grade":"G","search_weight":50}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-blank-create-college: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  BEGIN
    PERFORM commit_profile_patch_cas(u, 0,
      '{"home_school":"uiuc","college":"C","major":"","grade":"G","search_weight":50}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-blank-create-major: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  BEGIN
    PERFORM commit_profile_patch_cas(u, 0,
      '{"home_school":"uiuc","college":"C","major":"M","grade":"  ","search_weight":50}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-blank-create-grade: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- …as is a search_weight that is not a number in range.
  BEGIN
    PERFORM commit_profile_patch_cas(u, 0,
      '{"home_school":"uiuc","college":"C","major":"M","grade":"G","search_weight":"lots"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-create-weight-type: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  BEGIN
    PERFORM commit_profile_patch_cas(u, 0,
      '{"home_school":"uiuc","college":"C","major":"M","grade":"G","search_weight":900}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-create-weight-range: should have raised';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;

  -- Every rejection above wrote nothing.
  SELECT revision INTO c FROM profiles WHERE id = u;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-invalid-input: revision moved to %', c; END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = u;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-invalid-input: history grew to %', c; END IF;
END;
$$;

-- =====================================================================
-- 4. Absent row: expected_revision >= 1 must NOT recreate it.
--    expected_revision = 0 against an existing row is a conflict, unless
--    the create's own response was the thing that was lost.
-- =====================================================================
DO $$
DECLARE
  u text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a05';
  res jsonb;
  c int;
BEGIN
  PERFORM set_config('test.uid', u, false);

  res := commit_profile_patch_cas(u, 4, '{"major":"X"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'missing' OR res->>'reason' IS DISTINCT FROM 'absent' THEN
    RAISE EXCEPTION 'TEST FAIL cas-absent: want missing/absent got %', res;
  END IF;
  SELECT count(*) INTO c FROM profiles WHERE id = u;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL cas-absent: recreated the row'; END IF;

  PERFORM commit_profile_patch_cas(u, 0, '{"home_school":"uiuc","search_weight":50,"college":"Grainger","major":"CS","grade":"Junior"}'::jsonb);

  -- A second create attempt with DIFFERENT content is a conflict, not a
  -- silent overwrite of the row that already exists.
  res := commit_profile_patch_cas(u, 0, '{"home_school":"uiuc","search_weight":50,"college":"LAS","major":"Econ","grade":"Senior"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'conflict' OR (res->>'revision')::bigint IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'TEST FAIL cas-recreate: want conflict@1 got %', res;
  END IF;
  IF res->'profile'->>'college' IS DISTINCT FROM 'Grainger' THEN
    RAISE EXCEPTION 'TEST FAIL cas-recreate: row was overwritten: %', res;
  END IF;

  -- A retry of the ORIGINAL create (its response was lost) is idempotent.
  res := commit_profile_patch_cas(u, 0, '{"home_school":"uiuc","search_weight":50,"college":"Grainger","major":"CS","grade":"Junior"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'unchanged' OR (res->>'revision')::bigint IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'TEST FAIL cas-recreate-replay: want unchanged@1 got %', res;
  END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = u;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-recreate-replay: duplicate history (%)', c; END IF;
END;
$$;

-- =====================================================================
-- 5. A failing history insert rolls the WHOLE call back — the current row
--    must never advance without its matching version entry.
-- =====================================================================
CREATE OR REPLACE FUNCTION cas_test_block_history() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.device_id = '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a06' THEN
    RAISE EXCEPTION 'cas_test: history write blocked';
  END IF;
  RETURN NEW;
END;
$$;

DO $$
DECLARE
  u text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a06';
  c int;
  v_profile jsonb;
BEGIN
  PERFORM set_config('test.uid', u, false);
  PERFORM commit_profile_patch_cas(u, 0, '{"home_school":"uiuc","search_weight":50,"college":"Grainger","major":"CS","grade":"Junior"}'::jsonb);

  CREATE TRIGGER cas_test_block_history BEFORE INSERT ON profile_versions
    FOR EACH ROW EXECUTE FUNCTION cas_test_block_history();

  BEGIN
    PERFORM commit_profile_patch_cas(u, 1, '{"major":"ECE"}'::jsonb);
    RAISE EXCEPTION 'TEST FAIL cas-history-atomic: should have raised';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%history write blocked%' THEN
      RAISE EXCEPTION 'TEST FAIL cas-history-atomic: wrong error %', sqlerrm;
    END IF;
  END;

  DROP TRIGGER cas_test_block_history ON profile_versions;

  SELECT revision, profile_data INTO c, v_profile FROM profiles WHERE id = u;
  IF c IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'TEST FAIL cas-history-atomic: revision advanced to % without history', c;
  END IF;
  IF v_profile->>'major' IS DISTINCT FROM 'CS' THEN
    RAISE EXCEPTION 'TEST FAIL cas-history-atomic: current row kept the rolled-back patch: %', v_profile;
  END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = u;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-history-atomic: history count % ', c; END IF;
END;
$$;

-- =====================================================================
-- 6. ACL. The runner mirrors Supabase's managed table grants immediately
--    before 027 (see run_flow_b_test.sh), so "denied" here proves 027
--    actively revoked them rather than that a vanilla cluster never
--    granted them in the first place.
-- =====================================================================
DO $$
DECLARE
  r text;
  t text;
  p text;
BEGIN
  -- Direct DML on both tables is gone for the browser roles AND for PUBLIC —
  -- a privilege held by PUBLIC makes has_table_privilege true for every role,
  -- so revoking only the named ones would change nothing.
  FOREACH r IN ARRAY ARRAY['public','anon','authenticated'] LOOP
    FOREACH t IN ARRAY ARRAY['public.profiles','public.profile_versions'] LOOP
      FOREACH p IN ARRAY ARRAY['INSERT','UPDATE','DELETE'] LOOP
        IF has_table_privilege(r, t, p) THEN
          RAISE EXCEPTION 'TEST FAIL cas-acl: % still has % on %', r, p, t;
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;

  -- Reads are untouched: the app still SELECTs its own row (policy-scoped).
  FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
    FOREACH t IN ARRAY ARRAY['public.profiles','public.profile_versions'] LOOP
      IF NOT has_table_privilege(r, t, 'SELECT') THEN
        RAISE EXCEPTION 'TEST FAIL cas-acl: % lost SELECT on %', r, t;
      END IF;
    END LOOP;
  END LOOP;

  -- service_role (the backend) keeps full access — it is not a browser role.
  IF NOT has_table_privilege('service_role', 'public.profiles', 'UPDATE') THEN
    RAISE EXCEPTION 'TEST FAIL cas-acl: service_role lost UPDATE on profiles';
  END IF;

  -- Function ACL. CREATE FUNCTION grants EXECUTE to PUBLIC by default, so
  -- the 'public' pseudo-role below is a real check on 027's REVOKE, not a
  -- restatement of a vanilla cluster's defaults.
  IF has_function_privilege('public',
       'public.commit_profile_patch_cas(text,bigint,jsonb)', 'EXECUTE') THEN
    RAISE EXCEPTION 'TEST FAIL cas-acl: PUBLIC still has EXECUTE on commit_profile_patch_cas';
  END IF;
  IF has_function_privilege('anon',
       'public.commit_profile_patch_cas(text,bigint,jsonb)', 'EXECUTE') THEN
    RAISE EXCEPTION 'TEST FAIL cas-acl: anon still has EXECUTE on commit_profile_patch_cas';
  END IF;
  IF NOT has_function_privilege('authenticated',
       'public.commit_profile_patch_cas(text,bigint,jsonb)', 'EXECUTE') THEN
    RAISE EXCEPTION 'TEST FAIL cas-acl: authenticated cannot EXECUTE commit_profile_patch_cas';
  END IF;
  IF NOT has_function_privilege('service_role',
       'public.commit_profile_patch_cas(text,bigint,jsonb)', 'EXECUTE') THEN
    RAISE EXCEPTION 'TEST FAIL cas-acl: service_role cannot EXECUTE commit_profile_patch_cas';
  END IF;

  -- There is no full-row sibling to fall back to.
  IF EXISTS (
    SELECT 1 FROM pg_proc pr JOIN pg_namespace n ON n.oid = pr.pronamespace
    WHERE n.nspname = 'public' AND pr.proname LIKE 'commit_profile%'
      AND pr.proname IS DISTINCT FROM 'commit_profile_patch_cas'
  ) THEN
    RAISE EXCEPTION 'TEST FAIL cas-acl: a non-patch profile commit function exists';
  END IF;
END;
$$;

-- The privileges are enforced, not merely reported: run as `authenticated`
-- and confirm the DML is refused while the RPC is not.
SET ROLE authenticated;
DO $$
BEGIN
  BEGIN
    EXECUTE $q$INSERT INTO public.profiles (id, profile_data) VALUES ('acl-probe', '{}'::jsonb)$q$;
    RAISE EXCEPTION 'TEST FAIL cas-acl-live: authenticated could INSERT into profiles';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    EXECUTE $q$UPDATE public.profiles SET profile_data = '{}'::jsonb$q$;
    RAISE EXCEPTION 'TEST FAIL cas-acl-live: authenticated could UPDATE profiles';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    EXECUTE $q$INSERT INTO public.profile_versions (device_id, profile_data) VALUES ('acl-probe', '{}'::jsonb)$q$;
    RAISE EXCEPTION 'TEST FAIL cas-acl-live: authenticated could INSERT into profile_versions';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END;
$$;

-- The same role CAN call the RPC, and the SECURITY DEFINER write inside it
-- lands despite the revoked table privileges.
DO $$
DECLARE
  u text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a07';
  res jsonb;
BEGIN
  PERFORM set_config('test.uid', u, false);
  res := commit_profile_patch_cas(u, 0, '{"home_school":"uiuc","search_weight":50,"college":"Grainger","major":"CS","grade":"Junior"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'applied' THEN
    RAISE EXCEPTION 'TEST FAIL cas-acl-live: authenticated RPC did not apply: %', res;
  END IF;
END;
$$;
RESET ROLE;

-- =====================================================================
-- 7. The advisory lock key is real, and it is the SAME key Flow B takes.
--    Both assertions run inside the DO block's own transaction, where an
--    xact-scoped advisory lock is still held.
-- =====================================================================
DO $$
DECLARE
  u text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a08';
  v_key bigint := hashtext('ofe-profile:' || '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a08')::bigint;
BEGIN
  PERFORM set_config('test.uid', u, false);
  PERFORM commit_profile_patch_cas(u, 0, '{"home_school":"uiuc","search_weight":50,"college":"Grainger","major":"CS","grade":"Junior"}'::jsonb);
  IF NOT EXISTS (
    SELECT 1 FROM pg_locks
     WHERE locktype = 'advisory' AND objsubid = 1 AND pid = pg_backend_pid()
       AND classid::bigint = ((v_key >> 32) & 4294967295)
       AND objid::bigint = (v_key & 4294967295)
  ) THEN
    RAISE EXCEPTION 'TEST FAIL cas-lock: commit_profile_patch_cas did not take ofe-profile:<uid>';
  END IF;
END;
$$;

DO $$
DECLARE
  src text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a09';
  tgt text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a10';
  tok uuid;
  k bigint;
  held int;
BEGIN
  PERFORM set_config('test.uid', src, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('lockcheck@ex.com', NULL);

  PERFORM set_config('test.uid', tgt, false);
  PERFORM set_config('test.jwt', '{"email":"lockcheck@ex.com"}', false);
  PERFORM redeem_merge_grant(tok, NULL);

  held := 0;
  FOREACH k IN ARRAY ARRAY[
    hashtext('ofe-profile:' || src)::bigint,
    hashtext('ofe-profile:' || tgt)::bigint
  ] LOOP
    IF EXISTS (
      SELECT 1 FROM pg_locks
       WHERE locktype = 'advisory' AND objsubid = 1 AND pid = pg_backend_pid()
         AND classid::bigint = ((k >> 32) & 4294967295)
         AND objid::bigint = (k & 4294967295)
    ) THEN held := held + 1;
    END IF;
  END LOOP;
  IF held IS DISTINCT FROM 2 THEN
    RAISE EXCEPTION 'TEST FAIL cas-lock: redeem_merge_grant holds % of the 2 ofe-profile keys', held;
  END IF;
END;
$$;

-- =====================================================================
-- 8. Flow B x revisions.
--    (a) target has NO profile -> the source row is adopted, revision and
--        history revisions come with it.
--    (b) target HAS a profile -> target revision untouched, the source's
--        current row is archived revision-less, and the source's moved
--        history is stripped of revisions that belong to a dead sequence.
--    (c) a merged-away source can never re-create its profile via CAS.
-- =====================================================================
DO $$
DECLARE
  src text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a11';
  tgt text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a12';
  tok uuid;
  c int;
  res jsonb;
BEGIN
  -- Source builds up two revisions; target has nothing.
  PERFORM set_config('test.uid', src, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  PERFORM commit_profile_patch_cas(src, 0, '{"home_school":"uiuc","search_weight":50,"college":"Grainger","major":"CS","grade":"Junior"}'::jsonb);
  PERFORM commit_profile_patch_cas(src, 1, '{"major":"ECE"}'::jsonb);
  tok := mint_merge_grant('adopt@ex.com', NULL);

  PERFORM set_config('test.uid', tgt, false);
  PERFORM set_config('test.jwt', '{"email":"adopt@ex.com"}', false);
  PERFORM redeem_merge_grant(tok, NULL);

  SELECT revision INTO c FROM profiles WHERE id = tgt;
  IF c IS DISTINCT FROM 2 THEN RAISE EXCEPTION 'TEST FAIL merge-adopt: want revision 2 got %', c; END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = tgt AND profile_revision IS NULL;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL merge-adopt: adopted history lost its revisions (% null)', c; END IF;
  SELECT count(*) INTO c FROM profile_versions WHERE device_id = tgt;
  IF c IS DISTINCT FROM 2 THEN RAISE EXCEPTION 'TEST FAIL merge-adopt: want 2 moved history rows got %', c; END IF;

  -- The adopting account can keep saving from the revision it now holds.
  res := commit_profile_patch_cas(tgt, 2, '{"grade":"Senior"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'applied' OR (res->>'revision')::bigint IS DISTINCT FROM 3 THEN
    RAISE EXCEPTION 'TEST FAIL merge-adopt: post-merge save got %', res;
  END IF;

  -- (c) the merged-away source is dead: CAS refuses to recreate its row.
  PERFORM set_config('test.uid', src, false);
  res := commit_profile_patch_cas(src, 0, '{"home_school":"uiuc","search_weight":50,"college":"X","major":"Y","grade":"Z"}'::jsonb);
  IF res->>'status' IS DISTINCT FROM 'missing' OR res->>'reason' IS DISTINCT FROM 'merged_away' THEN
    RAISE EXCEPTION 'TEST FAIL merge-tombstone: want missing/merged_away got %', res;
  END IF;
  SELECT count(*) INTO c FROM profiles WHERE id = src;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL merge-tombstone: source profile was recreated'; END IF;
END;
$$;

DO $$
DECLARE
  src text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a13';
  tgt text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a14';
  tok uuid;
  c int;
  v_profile jsonb;
BEGIN
  PERFORM set_config('test.uid', src, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  PERFORM commit_profile_patch_cas(src, 0, '{"home_school":"uiuc","search_weight":50,"college":"SourceCollege","major":"CS","grade":"Junior"}'::jsonb);
  PERFORM commit_profile_patch_cas(src, 1, '{"major":"SourceMajor"}'::jsonb);
  tok := mint_merge_grant('archive@ex.com', NULL);

  PERFORM set_config('test.uid', tgt, false);
  PERFORM set_config('test.jwt', '{"email":"archive@ex.com"}', false);
  PERFORM commit_profile_patch_cas(tgt, 0, '{"home_school":"uiuc","search_weight":50,"college":"TargetCollege","major":"Econ","grade":"Senior"}'::jsonb);

  PERFORM redeem_merge_grant(tok, NULL);

  -- Target's own row and revision are untouched by the merge.
  SELECT revision, profile_data INTO c, v_profile FROM profiles WHERE id = tgt;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL merge-archive: target revision moved to %', c; END IF;
  IF v_profile->>'college' IS DISTINCT FROM 'TargetCollege' THEN
    RAISE EXCEPTION 'TEST FAIL merge-archive: target row replaced: %', v_profile;
  END IF;

  -- The source's current row survives as a revision-less archive entry, and
  -- so does its moved history — those numbers belong to a sequence the target
  -- never had, and keeping them would make the history lie.
  SELECT count(*) INTO c FROM profile_versions
    WHERE device_id = tgt AND profile_data->>'college' = 'SourceCollege';
  IF c < 1 THEN RAISE EXCEPTION 'TEST FAIL merge-archive: source profile was not preserved'; END IF;
  SELECT count(*) INTO c FROM profile_versions
    WHERE device_id = tgt AND profile_data->>'college' = 'SourceCollege'
      AND profile_revision IS NOT NULL;
  IF c IS DISTINCT FROM 0 THEN
    RAISE EXCEPTION 'TEST FAIL merge-archive: % re-homed rows kept a foreign revision', c;
  END IF;
  -- The target's OWN history keeps its revision.
  SELECT count(*) INTO c FROM profile_versions
    WHERE device_id = tgt AND profile_data->>'college' = 'TargetCollege'
      AND profile_revision = 1;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL merge-archive: target history lost its revision'; END IF;

  SELECT count(*) INTO c FROM profiles WHERE id = src;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL merge-archive: source row was left behind'; END IF;
END;
$$;

-- =====================================================================
-- 8b. A tombstoned account is never a valid merge TARGET.
--     (i)  reverse merge   A->B, then B->A
--     (ii) chain onto dead B->C, then A->B
--     Both must fail closed BEFORE any DML, leaving profiles, favorites and
--     the tombstone table exactly as they were.
-- =====================================================================
DO $$
DECLARE
  a text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a15';
  b text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a16';
  tok_ab uuid;
  tok_ba uuid;
  c int;
  v_profile jsonb;
BEGIN
  -- Both devices are still ANONYMOUS and each mints its own grant before
  -- either signs in — the realistic way two opposing grants come to exist
  -- (mint_merge_grant is anon-only by design, 017, so this is the ONLY way
  -- they can). Device A's is bound to the account the user will sign into on
  -- B; device B's is bound to the account they will sign into on A.
  PERFORM set_config('test.uid', a, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  PERFORM commit_profile_patch_cas(a, 0,
    '{"home_school":"uiuc","search_weight":50,"college":"AProfile","major":"CS","grade":"Junior"}'::jsonb);
  INSERT INTO favorites (device_id, opportunity_id) VALUES (a, 'opp-reverse-a');
  tok_ab := mint_merge_grant('reverse-b@ex.com', NULL);

  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok_ba := mint_merge_grant('reverse-a@ex.com', NULL);

  -- The user signs in on B first: A merges into B, tombstoning A.
  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"email":"reverse-b@ex.com"}', false);
  PERFORM redeem_merge_grant(tok_ab, NULL);

  -- Later they sign in on A and its still-stashed grant is redeemed: source
  -- B (alive, now holding everything), target A (tombstoned). Pre-fix this
  -- walked every row back into the dead account and tombstoned B as well,
  -- leaving the data reachable from neither.
  PERFORM set_config('test.uid', a, false);
  PERFORM set_config('test.jwt', '{"email":"reverse-a@ex.com"}', false);
  BEGIN
    PERFORM redeem_merge_grant(tok_ba, NULL);
    RAISE EXCEPTION 'TEST FAIL merge-reverse: redeeming into a tombstoned target succeeded';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%target already merged%' THEN
      RAISE EXCEPTION 'TEST FAIL merge-reverse: wrong error %', sqlerrm;
    END IF;
  END;

  -- Nothing moved, nothing new was tombstoned, and the grant was not consumed.
  SELECT count(*) INTO c FROM favorites WHERE device_id = b;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL merge-reverse: B lost favorites (%)', c; END IF;
  SELECT count(*) INTO c FROM favorites WHERE device_id = a;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL merge-reverse: rows moved into the dead account'; END IF;
  SELECT profile_data INTO v_profile FROM profiles WHERE id = b;
  IF v_profile->>'college' IS DISTINCT FROM 'AProfile' THEN
    RAISE EXCEPTION 'TEST FAIL merge-reverse: B profile changed: %', v_profile;
  END IF;
  SELECT count(*) INTO c FROM profiles WHERE id = a;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL merge-reverse: dead account got a profile back'; END IF;
  SELECT count(*) INTO c FROM merged_devices WHERE source_device_id = b;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL merge-reverse: B was tombstoned by a rejected merge'; END IF;
  SELECT count(*) INTO c FROM merge_grants WHERE token = tok_ba AND consumed_at IS NULL;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL merge-reverse: a rejected redemption consumed the grant'; END IF;
END;
$$;

DO $$
DECLARE
  a text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a17';
  b text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a18';
  cc text := '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a19';
  tok uuid;
  c int;
BEGIN
  -- B merges into C, so B is dead.
  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  INSERT INTO favorites (device_id, opportunity_id) VALUES (b, 'opp-chain-b');
  tok := mint_merge_grant('chain1@ex.com', NULL);
  PERFORM set_config('test.uid', cc, false);
  PERFORM set_config('test.jwt', '{"email":"chain1@ex.com"}', false);
  PERFORM redeem_merge_grant(tok, NULL);

  -- A now tries to merge into the dead B. C's owner would never see it.
  PERFORM set_config('test.uid', a, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  INSERT INTO favorites (device_id, opportunity_id) VALUES (a, 'opp-chain-a');
  tok := mint_merge_grant('chain2@ex.com', NULL);
  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"email":"chain2@ex.com"}', false);
  BEGIN
    PERFORM redeem_merge_grant(tok, NULL);
    RAISE EXCEPTION 'TEST FAIL merge-chain: redeeming into a tombstoned target succeeded';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%target already merged%' THEN
      RAISE EXCEPTION 'TEST FAIL merge-chain: wrong error %', sqlerrm;
    END IF;
  END;

  SELECT count(*) INTO c FROM favorites WHERE device_id = a;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL merge-chain: A lost its data (%)', c; END IF;
  SELECT count(*) INTO c FROM favorites WHERE device_id = b;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL merge-chain: rows landed on the dead account'; END IF;
  SELECT count(*) INTO c FROM favorites WHERE device_id = cc;
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL merge-chain: C changed (%)', c; END IF;
  SELECT count(*) INTO c FROM merged_devices WHERE source_device_id = a;
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL merge-chain: A was tombstoned by a rejected merge'; END IF;
END;
$$;

-- =====================================================================
-- 9. Schema contract: the revision columns exist with the intended shape,
--    and (owner, revision) is deliberately NOT unique — Flow B re-homes one
--    account's history under another's id, which a unique index would break.
-- =====================================================================
DO $$
DECLARE
  c int;
BEGIN
  SELECT count(*) INTO c FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'profiles'
      AND column_name = 'revision' AND is_nullable = 'NO';
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-schema: profiles.revision missing/nullable'; END IF;

  SELECT count(*) INTO c FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'profile_versions'
      AND column_name = 'profile_revision' AND is_nullable = 'YES';
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-schema: profile_versions.profile_revision missing/not-nullable'; END IF;

  SELECT count(*) INTO c FROM pg_indexes
    WHERE schemaname = 'public' AND tablename = 'profile_versions'
      AND indexname = 'profile_versions_device_revision_idx';
  IF c IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'TEST FAIL cas-schema: (device_id, profile_revision) index missing'; END IF;

  SELECT count(*) INTO c FROM pg_indexes
    WHERE schemaname = 'public' AND tablename = 'profile_versions'
      AND indexname = 'profile_versions_device_revision_idx'
      AND indexdef LIKE '%UNIQUE%';
  IF c IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'TEST FAIL cas-schema: the revision index must NOT be unique'; END IF;

  -- The CHECK constraints reject the values they exist to reject.
  BEGIN
    UPDATE profiles SET revision = 0 WHERE id = '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a01';
    RAISE EXCEPTION 'TEST FAIL cas-schema: revision 0 was accepted';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  BEGIN
    UPDATE profile_versions SET profile_revision = 0
      WHERE device_id = '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a01';
    RAISE EXCEPTION 'TEST FAIL cas-schema: profile_revision 0 was accepted';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END;
$$;

DO $$ BEGIN
  RAISE WARNING 'PASS 027 profile save CAS';
END $$;
