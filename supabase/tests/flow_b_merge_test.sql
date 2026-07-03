-- Flow B merge tests (migration 017). Run against an ephemeral cluster that
-- has loaded _stubs.sql -> migrations 002..016 -> 017. Each scenario is a
-- self-contained DO block that RAISEs on failure; with ON_ERROR_STOP the
-- runner exits nonzero on the first failing assertion.
--
-- Identity is switched with set_config('test.uid'/'test.jwt', ...) which the
-- auth.uid()/auth.jwt() stubs read — the same claims the SECURITY DEFINER
-- functions consult in production.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

-- Fixed actors (valid v4 UUIDs).
--   A = permanent account / merge target        aaaa...
--   B = second device / merge source            bbbb...
--   S = victim source (email-binding test)       5555...
--   K = attacker target                          cccc...
--   X = expiry source / T = expiry target        eeee.../ffff...
--   D = same-device no-op                        dddd...

-- =====================================================================
-- Scenario 1: happy path — dedup + both conflict directions + replay
-- =====================================================================
DO $$
DECLARE
  a text := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  b text := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  tok uuid;
  res jsonb;
  c int;
BEGIN
  -- ---- seed TARGET (A) ----
  INSERT INTO favorites (device_id, opportunity_id) VALUES (a, 'opp1');
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, updated_at)
    VALUES (a, 'opp1', 'applied', '2026-01-01'),          -- older -> B wins
           (a, 'opp3', 'interviewing', '2026-03-01');     -- newer -> A wins
  INSERT INTO profiles (id, profile_data) VALUES (a, '{"who":"A"}');
  INSERT INTO profile_versions (device_id, profile_data) VALUES (a, '{"v":"A1"}');
  INSERT INTO saved_searches (device_id, name) VALUES (a, 'A search');
  INSERT INTO match_feedback (device_id, opportunity_id, verdict) VALUES (a, 'opp1', 'up');
  INSERT INTO push_subscriptions (device_id, endpoint, p256dh, auth) VALUES (a, 'E1', 'p', 'k');
  INSERT INTO analytics_events (device_id, event) VALUES (a, 'landing_view');
  INSERT INTO waitlist (device_id, email, intent) VALUES (a, 'x@ex.com', 'apply_for_me');
  INSERT INTO feedback (device_id, message) VALUES (a, 'A note');

  -- ---- seed SOURCE (B) ----
  INSERT INTO favorites (device_id, opportunity_id) VALUES (b, 'opp1'), (b, 'opp2');  -- opp1 dup, opp2 new
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, updated_at)
    VALUES (b, 'opp1', 'replied', '2026-02-01'),          -- newer than A's opp1 -> wins
           (b, 'opp2', 'applied', '2026-02-01'),          -- new
           (b, 'opp3', 'applied', '2026-02-15');          -- older than A's opp3 -> loses
  INSERT INTO profiles (id, profile_data) VALUES (b, '{"who":"B"}');
  INSERT INTO profile_versions (device_id, profile_data) VALUES (b, '{"v":"B1"}');
  INSERT INTO saved_searches (device_id, name) VALUES (b, 'B search 1'), (b, 'B search 2');
  INSERT INTO match_feedback (device_id, opportunity_id, verdict)
    VALUES (b, 'opp1', 'down'), (b, 'opp2', 'up');        -- opp1 conflict (A kept), opp2 new
  INSERT INTO push_subscriptions (device_id, endpoint, p256dh, auth)
    VALUES (b, 'E1', 'p', 'k'), (b, 'E2', 'p', 'k');      -- E1 dup, E2 new
  INSERT INTO analytics_events (device_id, event) VALUES (b, 'matches_generated'), (b, 'opp_opened');
  INSERT INTO waitlist (device_id, email, intent)
    VALUES (b, 'x@ex.com', 'apply_for_me'), (b, 'y@ex.com', 'apply_for_me');  -- x dup, y new
  INSERT INTO feedback (device_id, message) VALUES (b, 'B note');
  -- B attachment (should be counted, not moved)
  INSERT INTO storage.objects (bucket_id, name) VALUES ('tracker-attachments', b || '/opp2/resume.pdf');

  -- ---- mint as B (bound to A's email), redeem as A ----
  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{}', false);
  tok := mint_merge_grant('accountA@ex.com');

  PERFORM set_config('test.uid', a, false);
  PERFORM set_config('test.jwt', '{"email":"AccountA@ex.com"}', false);  -- case-insensitive bind
  res := redeem_merge_grant(tok);

  IF (res->>'merged')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST FAIL s1: expected merged=true, got %', res;
  END IF;

  -- ---- assert TARGET (A) row counts ----
  SELECT count(*) INTO c FROM favorites WHERE device_id = a;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL s1 favorites: want 2 got %', c; END IF;

  SELECT count(*) INTO c FROM interactions WHERE device_id = a;
  IF c <> 3 THEN RAISE EXCEPTION 'TEST FAIL s1 interactions count: want 3 got %', c; END IF;
  -- conflict directions
  PERFORM 1 FROM interactions WHERE device_id=a AND opportunity_id='opp1' AND interaction_type='replied';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s1: opp1 should be replied (B newer won)'; END IF;
  PERFORM 1 FROM interactions WHERE device_id=a AND opportunity_id='opp3' AND interaction_type='interviewing';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s1: opp3 should stay interviewing (A newer won)'; END IF;

  SELECT count(*) INTO c FROM saved_searches WHERE device_id = a;
  IF c <> 3 THEN RAISE EXCEPTION 'TEST FAIL s1 saved_searches: want 3 got %', c; END IF;

  SELECT count(*) INTO c FROM match_feedback WHERE device_id = a;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL s1 match_feedback: want 2 got %', c; END IF;
  PERFORM 1 FROM match_feedback WHERE device_id=a AND opportunity_id='opp1' AND verdict='up';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s1: opp1 verdict should stay up (target kept)'; END IF;

  SELECT count(*) INTO c FROM push_subscriptions WHERE device_id = a;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL s1 push: want 2 got %', c; END IF;

  SELECT count(*) INTO c FROM analytics_events WHERE device_id = a;
  IF c <> 3 THEN RAISE EXCEPTION 'TEST FAIL s1 analytics: want 3 got %', c; END IF;

  SELECT count(*) INTO c FROM waitlist WHERE device_id = a;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL s1 waitlist: want 2 got %', c; END IF;

  SELECT count(*) INTO c FROM feedback WHERE device_id = a;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL s1 feedback: want 2 got %', c; END IF;

  -- profile: A kept, B stashed as a version
  SELECT count(*) INTO c FROM profiles WHERE id = a;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL s1: A profile should remain'; END IF;
  PERFORM 1 FROM profiles WHERE id=a AND profile_data->>'who'='A';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s1: A profile_data should be preserved'; END IF;
  IF (res#>>'{summary,profile}') <> 'kept_target_saved_other_as_version' THEN
    RAISE EXCEPTION 'TEST FAIL s1: profile summary was %', res#>>'{summary,profile}';
  END IF;

  -- ---- assert SOURCE (B) fully drained across every table ----
  SELECT (SELECT count(*) FROM favorites WHERE device_id=b)
       + (SELECT count(*) FROM interactions WHERE device_id=b)
       + (SELECT count(*) FROM interaction_status_changes WHERE device_id=b)
       + (SELECT count(*) FROM profiles WHERE id=b)
       + (SELECT count(*) FROM profile_versions WHERE device_id=b)
       + (SELECT count(*) FROM saved_searches WHERE device_id=b)
       + (SELECT count(*) FROM match_feedback WHERE device_id=b)
       + (SELECT count(*) FROM push_subscriptions WHERE device_id=b)
       + (SELECT count(*) FROM analytics_events WHERE device_id=b)
       + (SELECT count(*) FROM waitlist WHERE device_id=b)
       + (SELECT count(*) FROM feedback WHERE device_id=b)
    INTO c;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL s1: source B not fully drained, % rows remain', c; END IF;

  -- attachments counted, not moved
  IF (res#>>'{summary,attachments_not_moved}')::int <> 1 THEN
    RAISE EXCEPTION 'TEST FAIL s1: attachments_not_moved want 1 got %', res#>>'{summary,attachments_not_moved}';
  END IF;

  -- tombstone + grant consumed
  PERFORM 1 FROM merged_devices WHERE source_device_id=b AND target_device_id=a;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s1: no tombstone'; END IF;
  PERFORM 1 FROM merge_grants WHERE token=tok AND consumed_at IS NOT NULL;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s1: grant not consumed'; END IF;

  -- ---- replay: same token again must be rejected ----
  BEGIN
    PERFORM redeem_merge_grant(tok);
    RAISE EXCEPTION 'TEST FAIL s1 replay: second redeem should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%already used%' THEN
      RAISE EXCEPTION 'TEST FAIL s1 replay: wrong error %', sqlerrm;
    END IF;
  END;

  -- ---- double-merge: minting for an already-merged source must fail ----
  PERFORM set_config('test.uid', b, false);
  BEGIN
    PERFORM mint_merge_grant('accountA@ex.com');
    RAISE EXCEPTION 'TEST FAIL s1 double: mint for merged device should fail';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%already merged%' THEN
      RAISE EXCEPTION 'TEST FAIL s1 double: wrong error %', sqlerrm;
    END IF;
  END;

  RAISE WARNING 'PASS scenario 1 (happy path + dedup + conflicts + replay + double-merge)';
END $$;

-- =====================================================================
-- Scenario 2: email-binding blocks a stolen token (takeover refusal)
-- =====================================================================
DO $$
DECLARE
  s text := '55555555-5555-4555-8555-555555555555';  -- victim source
  k text := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';  -- attacker target
  tok uuid;
  c int;
BEGIN
  INSERT INTO favorites (device_id, opportunity_id) VALUES (s, 'secret-opp');

  -- victim mints, bound to victim's email
  PERFORM set_config('test.uid', s, false);
  tok := mint_merge_grant('victim@ex.com');

  -- attacker steals the token, signs in as themselves, tries to redeem
  PERFORM set_config('test.uid', k, false);
  PERFORM set_config('test.jwt', '{"email":"attacker@ex.com"}', false);
  BEGIN
    PERFORM redeem_merge_grant(tok);
    RAISE EXCEPTION 'TEST FAIL s2: stolen token redeem should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%not bound to this account%' THEN
      RAISE EXCEPTION 'TEST FAIL s2: wrong error %', sqlerrm;
    END IF;
  END;

  -- attacker got nothing; victim's data is intact and un-merged
  SELECT count(*) INTO c FROM favorites WHERE device_id = k;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL s2: attacker should have 0 rows, got %', c; END IF;
  SELECT count(*) INTO c FROM favorites WHERE device_id = s;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL s2: victim data should be intact'; END IF;
  PERFORM 1 FROM merged_devices WHERE source_device_id = s;
  IF FOUND THEN RAISE EXCEPTION 'TEST FAIL s2: victim source should not be tombstoned'; END IF;

  RAISE WARNING 'PASS scenario 2 (email-binding takeover refusal)';
END $$;

-- =====================================================================
-- Scenario 3: expired grant rejected
-- =====================================================================
DO $$
DECLARE
  x text := 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';  -- source
  t text := 'ffffffff-ffff-4fff-8fff-ffffffffffff';  -- target
  tok uuid;
BEGIN
  PERFORM set_config('test.uid', x, false);
  tok := mint_merge_grant(NULL);                       -- unbound (OAuth-style)
  UPDATE merge_grants SET expires_at = now() - interval '1 minute' WHERE token = tok;

  PERFORM set_config('test.uid', t, false);
  PERFORM set_config('test.jwt', '{"email":"t@ex.com"}', false);
  BEGIN
    PERFORM redeem_merge_grant(tok);
    RAISE EXCEPTION 'TEST FAIL s3: expired redeem should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%expired%' THEN
      RAISE EXCEPTION 'TEST FAIL s3: wrong error %', sqlerrm;
    END IF;
  END;
  RAISE WARNING 'PASS scenario 3 (expiry)';
END $$;

-- =====================================================================
-- Scenario 4: same-device no-op, invalid token, unauthenticated
-- =====================================================================
DO $$
DECLARE
  d text := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  tok uuid;
  res jsonb;
BEGIN
  -- same-device: mint and redeem as the same uid -> merged=false/same_device
  PERFORM set_config('test.uid', d, false);
  PERFORM set_config('test.jwt', '{"email":"d@ex.com"}', false);
  tok := mint_merge_grant('d@ex.com');
  res := redeem_merge_grant(tok);
  IF (res->>'merged')::boolean IS NOT FALSE OR (res->>'reason') <> 'same_device' THEN
    RAISE EXCEPTION 'TEST FAIL s4 same-device: got %', res;
  END IF;

  -- invalid token
  BEGIN
    PERFORM redeem_merge_grant(gen_random_uuid());
    RAISE EXCEPTION 'TEST FAIL s4 invalid: should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%invalid grant%' THEN
      RAISE EXCEPTION 'TEST FAIL s4 invalid: wrong error %', sqlerrm;
    END IF;
  END;

  -- unauthenticated mint + redeem
  PERFORM set_config('test.uid', '', false);
  BEGIN
    PERFORM mint_merge_grant('z@ex.com');
    RAISE EXCEPTION 'TEST FAIL s4 unauth mint: should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%no authenticated session%' THEN
      RAISE EXCEPTION 'TEST FAIL s4 unauth mint: wrong error %', sqlerrm;
    END IF;
  END;
  BEGIN
    PERFORM redeem_merge_grant(gen_random_uuid());
    RAISE EXCEPTION 'TEST FAIL s4 unauth redeem: should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%no authenticated session%' THEN
      RAISE EXCEPTION 'TEST FAIL s4 unauth redeem: wrong error %', sqlerrm;
    END IF;
  END;

  RAISE WARNING 'PASS scenario 4 (same-device no-op, invalid token, unauthenticated)';
END $$;

SELECT 'ALL FLOW B TESTS PASSED' AS result;
