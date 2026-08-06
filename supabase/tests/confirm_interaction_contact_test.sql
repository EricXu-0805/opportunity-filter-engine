-- confirm_interaction_contact_test.sql (migration 025)
--
-- Runs the RPC as the `authenticated` role (not the postgres superuser,
-- which has BYPASSRLS and would silently skip the RLS path entirely) so
-- interactions_insert_own/interactions_update_own (device_id =
-- auth.uid()::text, 006_anonymous_auth_rls.sql) are genuinely exercised —
-- SECURITY INVOKER means those policies are the real, live enforcement
-- layer for this test, not a documentation claim. GRANT SELECT/INSERT/
-- UPDATE/DELETE ON interactions TO authenticated below mirrors Supabase's
-- own managed default privileges for a public-schema table (not something
-- that appears in any migration file — same pattern run_flow_b_test.sh
-- already uses for `orders` ahead of the 024 test).
--
-- Asserts the atomic confirm RPC's product-truth contract:
--   - owner guard, exercised through real RLS: a mismatched
--     p_expected_device_id is rejected (42501, 'identity_changed'), zero
--     mutation.
--   - unauthenticated (auth.uid() NULL) is rejected the same way, both
--     when the caller still supplies a device id and when it passes NULL.
--   - anon role has no EXECUTE at all (permission denied) — dynamic proof,
--     not just the static has_function_privilege check below.
--   - empty/blank opportunity id is rejected (22023, 'invalid_opportunity').
--   - an absent row becomes 'applied' with last_contacted_at + remind_at.
--   - an existing further-along status (replied/interviewing/rejected/
--     dismissed) and any notes survive byte-for-byte, AND the conflict
--     path does NOT fire the interactions_log_status_change trigger (009)
--     — no new interaction_status_changes row, because interaction_type
--     was never SET.
--   - an omitted remind_at preserves the existing reminder; a supplied one updates it.
--   - calling it twice in a row (retry) is idempotent — no error, and
--     EXACTLY ONE row exists for the (device_id, opportunity_id) pair
--     (not just "the returned value looks right").
--   - static contract: SECURITY INVOKER (not DEFINER), search_path fixed,
--     PUBLIC/anon revoked, authenticated granted.
-- Two-session concurrency (real overlapping backends, not just sequential
-- calls in one session) is covered separately by
-- run_confirm_interaction_concurrency_test.sh, chained after this file.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

-- Mirror Supabase's managed default privileges for a public-schema table —
-- required for the `authenticated` role to even attempt the INSERT/UPDATE
-- inside this SECURITY INVOKER function; RLS then further restricts rows.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.interactions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.interaction_status_changes TO authenticated;

DO $$
DECLARE
  u1 text := '99999999-9999-4999-8999-999999999901';
  u2 text := '99999999-9999-4999-8999-999999999902';
  opp_absent text := 'opp-confirm-absent';
  opp_advanced text := 'opp-confirm-advanced';
  opp_reminder text := 'opp-confirm-reminder';
  opp_idempotent text := 'opp-confirm-idempotent';
  rec record;
  caught boolean;
  sqlstate_seen text;
  status_change_count_before int;
  status_change_count_after int;
  row_count int;
BEGIN
  -- ---- seed setup runs as postgres (table owner) — not the path under test ----
  SET ROLE postgres;
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, notes, remind_at, last_contacted_at)
    VALUES (u1, opp_advanced, 'replied', 'called the lab, waiting to hear back', '2026-08-01', '2026-07-20T00:00:00Z');
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, remind_at)
    VALUES (u1, opp_reminder, 'interviewing', '2026-08-01');
  RESET ROLE;

  -- ==== everything below runs as `authenticated` — the real RLS path ====
  SET ROLE authenticated;

  -- ---- owner guard (RLS-adjacent, explicit check): mismatched caller ----
  PERFORM set_config('test.uid', u1, false);
  caught := false;
  BEGIN
    PERFORM confirm_interaction_contact(u2, opp_absent, NULL);
  EXCEPTION WHEN OTHERS THEN
    caught := true;
    sqlstate_seen := SQLSTATE;
    IF SQLERRM <> 'identity_changed' THEN
      RAISE EXCEPTION 'TEST FAIL confirm-owner-guard: expected message identity_changed, got %', SQLERRM;
    END IF;
    IF sqlstate_seen <> '42501' THEN
      RAISE EXCEPTION 'TEST FAIL confirm-owner-guard: expected SQLSTATE 42501, got %', sqlstate_seen;
    END IF;
  END;
  IF NOT caught THEN
    RAISE EXCEPTION 'TEST FAIL confirm-owner-guard: mismatched device id did not raise';
  END IF;
  PERFORM 1 FROM interactions WHERE opportunity_id = opp_absent;
  IF FOUND THEN
    RAISE EXCEPTION 'TEST FAIL confirm-owner-guard: a row was created despite the owner mismatch';
  END IF;

  -- ---- unauthenticated: auth.uid() NULL, a real device id supplied ----
  PERFORM set_config('test.uid', '', false); -- '' -> NULL via the auth.uid() stub's nullif
  caught := false;
  BEGIN
    PERFORM confirm_interaction_contact(u1, opp_absent, NULL);
  EXCEPTION WHEN OTHERS THEN
    caught := true;
    IF SQLERRM <> 'identity_changed' OR SQLSTATE <> '42501' THEN
      RAISE EXCEPTION 'TEST FAIL confirm-unauthenticated: expected identity_changed/42501, got % / %', SQLERRM, SQLSTATE;
    END IF;
  END;
  IF NOT caught THEN
    RAISE EXCEPTION 'TEST FAIL confirm-unauthenticated: an unauthenticated caller was not rejected';
  END IF;

  -- ---- unauthenticated AND null device id: the IS DISTINCT FROM loophole ----
  caught := false;
  BEGIN
    PERFORM confirm_interaction_contact(NULL, opp_absent, NULL);
  EXCEPTION WHEN OTHERS THEN
    caught := true;
    IF SQLERRM <> 'identity_changed' OR SQLSTATE <> '42501' THEN
      RAISE EXCEPTION 'TEST FAIL confirm-null-device-id: expected identity_changed/42501, got % / %', SQLERRM, SQLSTATE;
    END IF;
  END;
  IF NOT caught THEN
    RAISE EXCEPTION 'TEST FAIL confirm-null-device-id: a NULL p_expected_device_id was not rejected (the NULL=NULL loophole)';
  END IF;
  PERFORM 1 FROM interactions WHERE opportunity_id = opp_absent;
  IF FOUND THEN
    RAISE EXCEPTION 'TEST FAIL confirm-null-device-id: a row was created with a NULL device id';
  END IF;

  -- ---- invalid opportunity id: empty / blank ----
  PERFORM set_config('test.uid', u1, false);
  caught := false;
  BEGIN
    PERFORM confirm_interaction_contact(u1, '', NULL);
  EXCEPTION WHEN OTHERS THEN
    caught := true;
    IF SQLERRM <> 'invalid_opportunity' OR SQLSTATE <> '22023' THEN
      RAISE EXCEPTION 'TEST FAIL confirm-invalid-opp: expected invalid_opportunity/22023, got % / %', SQLERRM, SQLSTATE;
    END IF;
  END;
  IF NOT caught THEN
    RAISE EXCEPTION 'TEST FAIL confirm-invalid-opp: an empty opportunity id was not rejected';
  END IF;
  caught := false;
  BEGIN
    PERFORM confirm_interaction_contact(u1, '   ', NULL);
  EXCEPTION WHEN OTHERS THEN
    caught := true;
  END;
  IF NOT caught THEN
    RAISE EXCEPTION 'TEST FAIL confirm-invalid-opp: a blank (whitespace-only) opportunity id was not rejected';
  END IF;

  -- ---- absent row becomes 'applied' (as authenticated, RLS-scoped) ----
  SELECT * INTO rec FROM confirm_interaction_contact(u1, opp_absent, '2026-08-10');
  IF rec.interaction_type <> 'applied' THEN
    RAISE EXCEPTION 'TEST FAIL confirm-absent: expected applied, got %', rec.interaction_type;
  END IF;
  IF rec.device_id <> u1 THEN
    RAISE EXCEPTION 'TEST FAIL confirm-absent: row landed on device_id %, not the caller %', rec.device_id, u1;
  END IF;
  IF rec.last_contacted_at IS NULL THEN
    RAISE EXCEPTION 'TEST FAIL confirm-absent: last_contacted_at was not stamped';
  END IF;
  IF rec.remind_at <> '2026-08-10' THEN
    RAISE EXCEPTION 'TEST FAIL confirm-absent: remind_at want 2026-08-10 got %', rec.remind_at;
  END IF;

  -- ---- existing advanced status + notes survive byte-for-byte, AND the
  --      status-change trigger does NOT fire on this conflict path ----
  SELECT count(*) INTO status_change_count_before
    FROM interaction_status_changes WHERE device_id = u1 AND opportunity_id = opp_advanced;
  SELECT * INTO rec FROM confirm_interaction_contact(u1, opp_advanced, NULL);
  IF rec.interaction_type <> 'replied' THEN
    RAISE EXCEPTION 'TEST FAIL confirm-advanced: status was downgraded to %', rec.interaction_type;
  END IF;
  IF rec.notes <> 'called the lab, waiting to hear back' THEN
    RAISE EXCEPTION 'TEST FAIL confirm-advanced: notes were altered: %', rec.notes;
  END IF;
  IF rec.remind_at <> '2026-08-01' THEN
    RAISE EXCEPTION 'TEST FAIL confirm-advanced: an omitted remind_at cleared the existing reminder (got %)', rec.remind_at;
  END IF;
  IF rec.last_contacted_at <= '2026-07-20T00:00:00Z'::timestamptz THEN
    RAISE EXCEPTION 'TEST FAIL confirm-advanced: last_contacted_at was not refreshed';
  END IF;
  SELECT count(*) INTO status_change_count_after
    FROM interaction_status_changes WHERE device_id = u1 AND opportunity_id = opp_advanced;
  IF status_change_count_after <> status_change_count_before THEN
    RAISE EXCEPTION 'TEST FAIL confirm-advanced: a metadata-only confirm fired the status-change trigger (before % after %)',
      status_change_count_before, status_change_count_after;
  END IF;

  -- ---- a SUPPLIED remind_at on an existing row does update it ----
  SELECT * INTO rec FROM confirm_interaction_contact(u1, opp_reminder, '2026-09-01');
  IF rec.interaction_type <> 'interviewing' THEN
    RAISE EXCEPTION 'TEST FAIL confirm-reminder: status was altered: %', rec.interaction_type;
  END IF;
  IF rec.remind_at <> '2026-09-01' THEN
    RAISE EXCEPTION 'TEST FAIL confirm-reminder: supplied remind_at was not applied (got %)', rec.remind_at;
  END IF;

  -- ---- idempotent retry: calling it twice in a row succeeds both times,
  --      and leaves EXACTLY ONE row for the pair (not a duplicate) ----
  PERFORM confirm_interaction_contact(u1, opp_idempotent, NULL);
  SELECT * INTO rec FROM confirm_interaction_contact(u1, opp_idempotent, NULL);
  IF rec.interaction_type <> 'applied' THEN
    RAISE EXCEPTION 'TEST FAIL confirm-idempotent: expected applied on retry, got %', rec.interaction_type;
  END IF;
  SELECT count(*) INTO row_count FROM interactions WHERE device_id = u1 AND opportunity_id = opp_idempotent;
  IF row_count <> 1 THEN
    RAISE EXCEPTION 'TEST FAIL confirm-idempotent: expected exactly 1 row after two calls, got %', row_count;
  END IF;

  RESET ROLE;
  RAISE NOTICE 'confirm_interaction_contact behavioral tests (RLS path, as authenticated): OK';
END $$;

-- ---- anon role: EXECUTE is denied at the grant level (dynamic proof) ----
DO $$
DECLARE
  caught boolean := false;
BEGIN
  SET ROLE anon;
  BEGIN
    PERFORM confirm_interaction_contact('99999999-9999-4999-8999-999999999901', 'opp-anon-denied', NULL);
  EXCEPTION WHEN insufficient_privilege THEN
    caught := true;
  END;
  RESET ROLE;
  IF NOT caught THEN
    RAISE EXCEPTION 'TEST FAIL confirm-anon-denied: anon role was able to call the function (EXECUTE not actually revoked)';
  END IF;
  RAISE NOTICE 'confirm_interaction_contact anon EXECUTE denial: OK';
END $$;

-- ---- static contract: SECURITY INVOKER, fixed search_path ----
DO $$
DECLARE
  is_secdef boolean;
  cfg text[];
BEGIN
  SELECT p.prosecdef, p.proconfig
    INTO is_secdef, cfg
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname = 'confirm_interaction_contact';

  IF is_secdef IS DISTINCT FROM false THEN
    RAISE EXCEPTION 'TEST FAIL confirm-contract: expected SECURITY INVOKER (prosecdef=false), got prosecdef=%', is_secdef;
  END IF;
  IF cfg IS NULL OR NOT ('search_path=public, pg_temp' = ANY (cfg)) THEN
    RAISE EXCEPTION 'TEST FAIL confirm-contract: expected search_path=public, pg_temp in proconfig, got %', cfg;
  END IF;
  RAISE NOTICE 'confirm_interaction_contact static contract (invoker, search_path): OK';
END $$;

-- ---- static contract: PUBLIC/anon revoked, authenticated granted ----
DO $$
DECLARE
  has_public boolean;
  has_anon boolean;
  has_authenticated boolean;
BEGIN
  SELECT has_function_privilege('public', 'confirm_interaction_contact(text, text, date)', 'EXECUTE')
    INTO has_public;
  SELECT has_function_privilege('anon', 'confirm_interaction_contact(text, text, date)', 'EXECUTE')
    INTO has_anon;
  SELECT has_function_privilege('authenticated', 'confirm_interaction_contact(text, text, date)', 'EXECUTE')
    INTO has_authenticated;

  IF has_public THEN
    RAISE EXCEPTION 'TEST FAIL confirm-contract: PUBLIC still has EXECUTE';
  END IF;
  IF has_anon THEN
    RAISE EXCEPTION 'TEST FAIL confirm-contract: anon still has EXECUTE';
  END IF;
  IF NOT has_authenticated THEN
    RAISE EXCEPTION 'TEST FAIL confirm-contract: authenticated is missing EXECUTE';
  END IF;
  RAISE NOTICE 'confirm_interaction_contact static contract (grants): OK';
END $$;
