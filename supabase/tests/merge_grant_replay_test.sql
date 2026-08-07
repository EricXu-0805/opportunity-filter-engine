-- Migration 026: idempotent redeem_merge_grant replay.
--
-- flow_b_merge_test.sql's scenario 1 already covers the email-bound replay
-- happy path (same account, same proof -> identical result, no re-merge).
-- This file covers the OAuth secret-bound path plus the fail-closed edges
-- 026's header calls out: cross-uid replay, same-uid-wrong-secret replay,
-- and a grant consumed before 026 shipped (redeemed_by IS NULL) — none of
-- these may ever return a stored result, only "already used".
--
-- Run against the same ephemeral cluster as flow_b_merge_test.sql (loaded:
-- _stubs.sql -> migrations through 026). UUIDs below are disjoint from every
-- actor used in flow_b_merge_test.sql / professor_tracking_merge_test.sql /
-- confirm_interaction_contact_test.sql / orders_rls_test.sql.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

-- =====================================================================
-- Scenario: OAuth secret-bound grant — same-account replay is idempotent;
-- cross-uid and wrong-secret replays of the SAME consumed token still fail.
-- =====================================================================
DO $$
DECLARE
  o text := '34343434-3434-4343-8434-343434343434';  -- OAuth anon source
  p text := '56565656-5656-4565-8565-565656565656';  -- OAuth sign-in target
  attacker text := '78787878-7878-4787-8787-787878787878';
  the_secret text := 'replay-test-secret';
  tok uuid;
  res jsonb;
  replay_res jsonb;
  c int;
BEGIN
  INSERT INTO favorites (device_id, opportunity_id) VALUES (o, 'opp-replay');
  INSERT INTO saved_searches (device_id, name) VALUES (o, 'O replay search');

  PERFORM set_config('test.uid', o, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant(NULL, encode(sha256(convert_to(the_secret, 'UTF8')), 'hex'));

  PERFORM set_config('test.uid', p, false);
  PERFORM set_config('test.jwt', '{"email":"whoever@ex.com"}', false);
  res := redeem_merge_grant(tok, the_secret);
  IF (res->>'merged')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST FAIL replay-oauth: expected merged=true, got %', res;
  END IF;
  PERFORM 1 FROM merge_grants WHERE token = tok AND redeemed_by = p AND redeemed_result = res;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'TEST FAIL replay-oauth: redeemed_by/redeemed_result not recorded atomically with consumed_at';
  END IF;

  -- ---- same account, correct secret: idempotent replay ----
  replay_res := redeem_merge_grant(tok, the_secret);
  IF replay_res <> res THEN
    RAISE EXCEPTION 'TEST FAIL replay-oauth same-account: expected identical replay, got % vs %', replay_res, res;
  END IF;
  SELECT count(*) INTO c FROM favorites WHERE device_id = p;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL replay-oauth same-account: merge re-ran (favorites want 1 got %)', c; END IF;
  SELECT count(*) INTO c FROM merged_devices WHERE source_device_id = o;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL replay-oauth same-account: duplicate tombstone (want 1 got %)', c; END IF;

  -- ---- same account, WRONG secret: still rejected, not idempotent ----
  BEGIN
    PERFORM redeem_merge_grant(tok, 'wrong-secret');
    RAISE EXCEPTION 'TEST FAIL replay-oauth wrong-secret: should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%already used%' THEN
      RAISE EXCEPTION 'TEST FAIL replay-oauth wrong-secret: wrong error %', sqlerrm;
    END IF;
  END;

  -- ---- same account, NO secret: still rejected ----
  BEGIN
    PERFORM redeem_merge_grant(tok);
    RAISE EXCEPTION 'TEST FAIL replay-oauth no-secret: should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%already used%' THEN
      RAISE EXCEPTION 'TEST FAIL replay-oauth no-secret: wrong error %', sqlerrm;
    END IF;
  END;

  -- ---- a DIFFERENT account (cross-uid), even presenting the correct
  -- secret, must never receive the stored result ----
  PERFORM set_config('test.uid', attacker, false);
  PERFORM set_config('test.jwt', '{"email":"attacker@ex.com"}', false);
  BEGIN
    PERFORM redeem_merge_grant(tok, the_secret);
    RAISE EXCEPTION 'TEST FAIL replay-oauth cross-uid: should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%already used%' THEN
      RAISE EXCEPTION 'TEST FAIL replay-oauth cross-uid: wrong error %', sqlerrm;
    END IF;
  END;

  RAISE WARNING 'PASS OAuth-path replay (same-account idempotent; wrong-secret/no-secret/cross-uid all rejected)';
END $$;

-- =====================================================================
-- Scenario: a grant consumed by pre-026 code (redeemed_by IS NULL, as every
-- row consumed before this migration shipped would be) must never become
-- replayable just because a later caller happens to match the original
-- target's uid and proof — the column being NULL means we were never told
-- who redeemed it, so the safe answer is always "already used".
-- =====================================================================
DO $$
DECLARE
  src text := '90909090-9090-4909-8909-909090909090';
  tgt text := '13131313-1313-4313-8313-131313131313';
  tok uuid;
BEGIN
  INSERT INTO favorites (device_id, opportunity_id) VALUES (src, 'opp-legacy');

  PERFORM set_config('test.uid', src, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('legacy-target@ex.com');

  -- Simulate a row consumed by pre-026 code: consumed_at set directly,
  -- redeemed_by/redeemed_result left NULL (the column did not exist yet).
  UPDATE merge_grants SET consumed_at = now() WHERE token = tok;

  PERFORM set_config('test.uid', tgt, false);
  PERFORM set_config('test.jwt', '{"email":"legacy-target@ex.com"}', false);
  BEGIN
    PERFORM redeem_merge_grant(tok);
    RAISE EXCEPTION 'TEST FAIL replay-legacy: pre-026 consumed grant must not become replayable';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%already used%' THEN
      RAISE EXCEPTION 'TEST FAIL replay-legacy: wrong error %', sqlerrm;
    END IF;
  END;

  -- Source data must be untouched — the rejected replay must not have run
  -- any merge DML.
  PERFORM 1 FROM favorites WHERE device_id = src AND opportunity_id = 'opp-legacy';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL replay-legacy: source row moved despite rejection'; END IF;

  RAISE WARNING 'PASS pre-026 consumed grant (redeemed_by IS NULL) never becomes replayable';
END $$;
