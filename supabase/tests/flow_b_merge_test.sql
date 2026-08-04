-- Flow B merge tests (migrations 017 + 018). Run against an ephemeral cluster
-- that has loaded _stubs.sql -> migrations 002..016 -> 017 -> 018. Each
-- scenario is a self-contained DO block that RAISEs on failure; with
-- ON_ERROR_STOP the runner exits nonzero on the first failing assertion.
--
-- Identity is switched with set_config('test.uid'/'test.jwt', ...) which the
-- auth.uid()/auth.jwt() stubs read — the same claims the SECURITY DEFINER
-- functions consult in production. Minting requires an ANONYMOUS session
-- (is_anonymous claim) and EXACTLY ONE binding — a target email (email path,
-- scenarios 1-5) or a device-secret hash (OAuth path, 018, scenario 6) — so
-- every mint sets a jwt with "is_anonymous": true.

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
--   G = guard scenarios                          9999...

-- =====================================================================
-- Scenario 1: happy path — dedup + both conflict directions + status-history
-- coherence + replay + double-merge
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
  INSERT INTO storage.objects (bucket_id, name) VALUES ('tracker-attachments', b || '/opp2/resume.pdf');

  -- ---- mint as anon B (bound to A's email), redeem as A ----
  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
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
  PERFORM 1 FROM interactions WHERE device_id=a AND opportunity_id='opp1' AND interaction_type='replied';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s1: opp1 should be replied (B newer won)'; END IF;
  PERFORM 1 FROM interactions WHERE device_id=a AND opportunity_id='opp3' AND interaction_type='interviewing';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s1: opp3 should stay interviewing (A newer won)'; END IF;

  -- status-history coherence: NO orphan status rows (an opportunity with
  -- history but no surviving interaction row) under the target.
  SELECT count(*) INTO c FROM interaction_status_changes isc
    WHERE isc.device_id = a
      AND NOT EXISTS (
        SELECT 1 FROM interactions i
        WHERE i.device_id = a AND i.opportunity_id = isc.opportunity_id);
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL s1: % orphan status-history rows after merge', c; END IF;

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

  IF (res#>>'{summary,attachments_not_moved}')::int <> 1 THEN
    RAISE EXCEPTION 'TEST FAIL s1: attachments_not_moved want 1 got %', res#>>'{summary,attachments_not_moved}';
  END IF;

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
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  BEGIN
    PERFORM mint_merge_grant('accountA@ex.com');
    RAISE EXCEPTION 'TEST FAIL s1 double: mint for merged device should fail';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%already merged%' THEN
      RAISE EXCEPTION 'TEST FAIL s1 double: wrong error %', sqlerrm;
    END IF;
  END;

  RAISE WARNING 'PASS scenario 1 (happy path + dedup + conflicts + coherence + replay + double-merge)';
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

  PERFORM set_config('test.uid', s, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
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
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('t@ex.com');
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
  -- same-device: mint (anon, bound) then redeem as the same uid whose email
  -- matches the binding -> merged=false / same_device
  PERFORM set_config('test.uid', d, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true, "email": "d@ex.com"}', false);
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
  PERFORM set_config('test.jwt', '{}', false);
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

-- =====================================================================
-- Scenario 5: mint/redeem guards — anon-only, mandatory email, no unbound
-- redemption (the hardenings from the adversarial review)
-- =====================================================================
DO $$
DECLARE
  g text := '99999999-9999-4999-8999-999999999999';  -- anon source
  t text := '88888888-8888-4888-8888-888888888888';  -- some target
  tok uuid;
BEGIN
  -- (a) non-anonymous session may NOT mint
  PERFORM set_config('test.uid', g, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": false, "email": "g@ex.com"}', false);
  BEGIN
    PERFORM mint_merge_grant('g@ex.com');
    RAISE EXCEPTION 'TEST FAIL s5a: non-anon mint should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%only an anonymous session%' THEN
      RAISE EXCEPTION 'TEST FAIL s5a: wrong error %', sqlerrm;
    END IF;
  END;

  -- (b) anonymous mint WITHOUT a target email is rejected (binding mandatory)
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  BEGIN
    PERFORM mint_merge_grant(NULL);
    RAISE EXCEPTION 'TEST FAIL s5b: unbound mint should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%target email is required%' THEN
      RAISE EXCEPTION 'TEST FAIL s5b: wrong error %', sqlerrm;
    END IF;
  END;
  BEGIN
    PERFORM mint_merge_grant('   ');   -- whitespace-only == empty
    RAISE EXCEPTION 'TEST FAIL s5b2: blank-email mint should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%target email is required%' THEN
      RAISE EXCEPTION 'TEST FAIL s5b2: wrong error %', sqlerrm;
    END IF;
  END;

  -- (c) an unbound grant that exists ANYWAY (crafted directly, bypassing mint)
  --     must not be redeemable — redeem rejects null binding outright.
  INSERT INTO merge_grants (token, source_device_id, target_email, expires_at)
    VALUES (gen_random_uuid(), g, NULL, now() + interval '15 minutes')
    RETURNING token INTO tok;
  PERFORM set_config('test.uid', t, false);
  PERFORM set_config('test.jwt', '{"email":"t@ex.com"}', false);
  BEGIN
    PERFORM redeem_merge_grant(tok);
    RAISE EXCEPTION 'TEST FAIL s5c: unbound-grant redeem should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%unbound grant is not redeemable%' THEN
      RAISE EXCEPTION 'TEST FAIL s5c: wrong error %', sqlerrm;
    END IF;
  END;

  RAISE WARNING 'PASS scenario 5 (anon-only mint, mandatory email, no unbound redemption)';
END $$;

-- =====================================================================
-- Scenario 6: OAuth device-secret binding (migration 018)
-- =====================================================================
DO $$
DECLARE
  o text := '11111111-1111-4111-8111-111111111111';  -- OAuth anon source
  p text := '22222222-2222-4222-8222-222222222222';  -- OAuth sign-in target
  q text := '33333333-3333-4333-8333-333333333333';  -- attacker target
  es text := '44444444-4444-4444-8444-444444444444'; -- email-path source (6e)
  et text := '66666666-6666-4666-8666-666666666666'; -- email-path target (6e)
  the_secret text := 'oauth-device-secret';
  tok uuid;
  res jsonb;
  c int;
BEGIN
  -- ---- seed SOURCE (O) + mint a secret-bound grant as anon O ----
  INSERT INTO favorites (device_id, opportunity_id) VALUES (o, 'opp-oauth');
  INSERT INTO saved_searches (device_id, name) VALUES (o, 'O search');

  PERFORM set_config('test.uid', o, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant(NULL, encode(sha256(convert_to(the_secret, 'UTF8')), 'hex'));

  -- (b) stolen token WITHOUT the secret is refused (1-arg delegate path)
  PERFORM set_config('test.uid', q, false);
  PERFORM set_config('test.jwt', '{"email":"attacker@ex.com"}', false);
  BEGIN
    PERFORM redeem_merge_grant(tok);
    RAISE EXCEPTION 'TEST FAIL s6b: secretless redeem should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%not bound to this session%' THEN
      RAISE EXCEPTION 'TEST FAIL s6b: wrong error %', sqlerrm;
    END IF;
  END;

  -- (c) wrong secret refused
  BEGIN
    PERFORM redeem_merge_grant(tok, 'wrong');
    RAISE EXCEPTION 'TEST FAIL s6c: wrong-secret redeem should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%not bound to this session%' THEN
      RAISE EXCEPTION 'TEST FAIL s6c: wrong error %', sqlerrm;
    END IF;
  END;

  SELECT count(*) INTO c FROM favorites WHERE device_id = o;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL s6: source data should be intact after refusals'; END IF;
  PERFORM 1 FROM merged_devices WHERE source_device_id = o;
  IF FOUND THEN RAISE EXCEPTION 'TEST FAIL s6: source should not be tombstoned after refusals'; END IF;

  -- (a) happy path: the browser holding the raw secret redeems (failed
  --     attempts above must not have consumed the grant); the signed-in
  --     email is irrelevant to a secret-bound grant.
  PERFORM set_config('test.uid', p, false);
  PERFORM set_config('test.jwt', '{"email":"whoever@ex.com"}', false);
  res := redeem_merge_grant(tok, the_secret);
  IF (res->>'merged')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST FAIL s6a: expected merged=true, got %', res;
  END IF;
  SELECT count(*) INTO c FROM favorites WHERE device_id = p;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL s6a favorites: want 1 got %', c; END IF;
  SELECT count(*) INTO c FROM saved_searches WHERE device_id = p;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL s6a saved_searches: want 1 got %', c; END IF;
  SELECT count(*) INTO c FROM favorites WHERE device_id = o;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL s6a: source not drained'; END IF;
  PERFORM 1 FROM merged_devices WHERE source_device_id = o AND target_device_id = p;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s6a: no tombstone'; END IF;
  PERFORM 1 FROM merge_grants WHERE token = tok AND consumed_at IS NOT NULL;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s6a: grant not consumed'; END IF;

  -- (d) mint binding rule: exactly one of email / secret hash
  PERFORM set_config('test.uid', q, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  BEGIN
    PERFORM mint_merge_grant('x@ex.com', encode(sha256(convert_to('s', 'UTF8')), 'hex'));
    RAISE EXCEPTION 'TEST FAIL s6d: double-bound mint should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%not both%' THEN
      RAISE EXCEPTION 'TEST FAIL s6d: wrong error %', sqlerrm;
    END IF;
  END;
  BEGIN
    PERFORM mint_merge_grant(NULL, NULL);
    RAISE EXCEPTION 'TEST FAIL s6d2: unbound mint should have failed';
  EXCEPTION WHEN others THEN
    IF sqlerrm NOT LIKE '%target email is required%' THEN
      RAISE EXCEPTION 'TEST FAIL s6d2: wrong error %', sqlerrm;
    END IF;
  END;

  -- (e) email-path regression: an email-bound grant (minted via the 1-arg
  --     delegate) still redeems, and a spurious p_secret is ignored.
  INSERT INTO favorites (device_id, opportunity_id) VALUES (es, 'opp-email');
  PERFORM set_config('test.uid', es, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('e6@ex.com');

  PERFORM set_config('test.uid', et, false);
  PERFORM set_config('test.jwt', '{"email":"e6@ex.com"}', false);
  res := redeem_merge_grant(tok, 'spurious-secret');
  IF (res->>'merged')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST FAIL s6e: expected merged=true, got %', res;
  END IF;
  SELECT count(*) INTO c FROM favorites WHERE device_id = et;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL s6e: email-bound merge did not move rows'; END IF;

  RAISE WARNING 'PASS scenario 6 (OAuth secret binding: possession redeems, stolen/wrong secret refused, exactly-one binding, email path intact)';
END $$;

-- =====================================================================
-- Scenario 7: résumé-renovation + usage-event merge (migration 021)
--   - resume_renovations: union on (device_id, opportunity_id), target kept on
--     conflict, source dupes dropped, non-conflicting moved.
--   - resume_renovation_versions + usage_events: append-only, move all.
--   - source fully drained across all three 021 tables.
-- =====================================================================
DO $$
DECLARE
  u text := '77777777-7777-4777-8777-777777777777';  -- anon source
  v text := '10101010-1010-4010-8010-101010101010';  -- permanent target
  tok uuid;
  res jsonb;
  c int;
BEGIN
  -- ---- seed TARGET (V) ----
  INSERT INTO resume_renovations (device_id, opportunity_id, doc)
    VALUES (v, 'oppR', '{"who":"V"}');                 -- conflict with U's oppR
  INSERT INTO resume_renovation_versions (device_id, opportunity_id, doc)
    VALUES (v, 'oppR', '{"snap":"V1"}');
  INSERT INTO usage_events (device_id, feature) VALUES (v, 'renovation');

  -- ---- seed SOURCE (U) ----
  INSERT INTO resume_renovations (device_id, opportunity_id, doc)
    VALUES (u, 'oppR', '{"who":"U"}'),                  -- dup -> target kept
           (u, 'oppS', '{"who":"U"}');                  -- new -> moves
  INSERT INTO resume_renovation_versions (device_id, opportunity_id, doc)
    VALUES (u, 'oppR', '{"snap":"U1"}');                -- append -> moves
  INSERT INTO usage_events (device_id, feature)
    VALUES (u, 'renovation'), (u, 'bullet_optimize');   -- append -> both move

  -- ---- mint as anon U (bound to V's email), redeem as V ----
  PERFORM set_config('test.uid', u, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('accountV@ex.com');

  PERFORM set_config('test.uid', v, false);
  PERFORM set_config('test.jwt', '{"email":"accountv@ex.com"}', false);
  res := redeem_merge_grant(tok);

  IF (res->>'merged')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST FAIL s7: expected merged=true, got %', res;
  END IF;

  -- resume_renovations: 2 under V (oppR kept target + oppS moved).
  SELECT count(*) INTO c FROM resume_renovations WHERE device_id = v;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL s7 renovations: want 2 got %', c; END IF;
  PERFORM 1 FROM resume_renovations
    WHERE device_id = v AND opportunity_id = 'oppR' AND doc->>'who' = 'V';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s7: oppR should keep target doc (V)'; END IF;
  PERFORM 1 FROM resume_renovations
    WHERE device_id = v AND opportunity_id = 'oppS' AND doc->>'who' = 'U';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s7: oppS should have moved from source'; END IF;
  IF (res#>>'{summary,resume_renovations}')::int <> 1 THEN
    RAISE EXCEPTION 'TEST FAIL s7: renovations summary want 1 got %',
      res#>>'{summary,resume_renovations}';
  END IF;

  -- resume_renovation_versions: append-only -> both survive under V.
  SELECT count(*) INTO c FROM resume_renovation_versions WHERE device_id = v;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL s7 renovation_versions: want 2 got %', c; END IF;

  -- usage_events: append-only -> all three under V.
  SELECT count(*) INTO c FROM usage_events WHERE device_id = v;
  IF c <> 3 THEN RAISE EXCEPTION 'TEST FAIL s7 usage_events: want 3 got %', c; END IF;

  -- source U fully drained across all three 021 tables.
  SELECT (SELECT count(*) FROM resume_renovations WHERE device_id = u)
       + (SELECT count(*) FROM resume_renovation_versions WHERE device_id = u)
       + (SELECT count(*) FROM usage_events WHERE device_id = u)
    INTO c;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL s7: source U not drained, % rows remain', c; END IF;

  RAISE WARNING 'PASS scenario 7 (renovation + usage merge: union/dedup/drain)';
END $$;


-- ---------------------------------------------------------------------------
-- Scenario 8 (W14): orders move on merge; paid history survives the account
-- switch. Also pins the widened grant TTL (a grant minted now is redeemable
-- 30 minutes later — regression guard for the 15-minute strand-forever bug).
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  -- UUIDs unique to this scenario: the professor-tracking merge test (runs
  -- later in this same database) mints for '8888…' — a tombstone here would
  -- break its mint with "device already merged".
  u text := '40404040-4040-4040-8040-404040404040';  -- anon source
  v text := '50505050-5050-4050-8050-505050505050';  -- permanent target
  tok uuid;
  res jsonb;
  c int;
BEGIN
  -- Source bought while anonymous (pending + paid); target has its own order.
  INSERT INTO orders (device_id, package, amount_cents, channel, status)
    VALUES (u, 'concierge_basic', 4900, 'manual', 'pending'),
           (u, 'concierge_basic', 4900, 'manual', 'paid');
  INSERT INTO orders (device_id, package, amount_cents, channel, status)
    VALUES (v, 'concierge_plus', 9900, 'manual', 'paid');

  PERFORM set_config('test.uid', u, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('accountw@ex.com');

  -- Widened TTL: backdate the mint by 30 minutes — must still redeem.
  UPDATE merge_grants
    SET expires_at = expires_at - interval '30 minutes'
    WHERE token = tok;

  PERFORM set_config('test.uid', v, false);
  PERFORM set_config('test.jwt', '{"email":"accountw@ex.com"}', false);
  res := redeem_merge_grant(tok);

  IF (res->>'merged')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST FAIL s8: expected merged=true, got %', res;
  END IF;

  SELECT count(*) INTO c FROM orders WHERE device_id = v;
  IF c <> 3 THEN RAISE EXCEPTION 'TEST FAIL s8 orders: want 3 under target got %', c; END IF;
  SELECT count(*) INTO c FROM orders WHERE device_id = u;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL s8: source orders not drained (%)', c; END IF;
  PERFORM 1 FROM orders WHERE device_id = v AND status = 'paid' AND package = 'concierge_basic';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL s8: paid anonymous order lost'; END IF;
  IF (res#>>'{summary,orders}')::int <> 2 THEN
    RAISE EXCEPTION 'TEST FAIL s8: orders summary want 2 got %', res#>>'{summary,orders}';
  END IF;

  -- Clean up: orders_rls_test.sql runs later in this same database and
  -- asserts whole-table row counts — scenario rows must not leak into it.
  DELETE FROM orders WHERE device_id IN (u, v);

  RAISE WARNING 'PASS scenario 8 (orders merge + widened TTL)';
END $$;

SELECT 'ALL FLOW B TESTS PASSED' AS result;
