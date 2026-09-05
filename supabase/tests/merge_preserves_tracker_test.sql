-- 034: a merge that keeps what it moves.
--
-- Run against the same ephemeral cluster as flow_b_merge_test.sql, after every
-- migration has loaded. Each scenario is a self-contained DO block that RAISEs
-- on failure; ON_ERROR_STOP makes the runner exit nonzero on the first one.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

-- =====================================================================
-- Scenario 1: the same professor asked for on both devices, under two
-- different emails. Before 034 this raised 23505 against 033's
-- waitlist_one_request_per_target, which rolled back the WHOLE merge and
-- left the grant unconsumed — so /auth/callback's Retry hit it forever.
-- =====================================================================
DO $$
DECLARE
  a text := '11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  b text := '11111111-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  tok uuid; res jsonb; c int; kept_email text; kept_at timestamptz;
BEGIN
  INSERT INTO waitlist (device_id, email, intent, opportunity_id, created_at)
    VALUES (a, 'account@ex.com', 'apply_for_me', 'prof-P', now() - interval '1 day');
  INSERT INTO waitlist (device_id, email, intent, opportunity_id, created_at)
    VALUES (b, 'typed@ex.com', 'apply_for_me', 'prof-P', now() - interval '9 days'),
           (b, NULL,           'apply_for_me', 'prof-Q', now() - interval '2 days');

  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('account@ex.com');
  PERFORM set_config('test.uid', a, false);
  PERFORM set_config('test.jwt', '{"email":"account@ex.com"}', false);
  res := redeem_merge_grant(tok);

  IF (res->>'merged')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST FAIL 034-1: the merge did not complete: %', res;
  END IF;

  -- prof-P collapses to one standing request; prof-Q is a different target and
  -- survives. Before 034 the (email,intent) rule would not have deleted prof-Q
  -- here, but the prof-P collision aborted everything anyway.
  SELECT count(*) INTO c FROM waitlist WHERE device_id = a AND opportunity_id = 'prof-P';
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL 034-1: expected 1 prof-P row, got %', c; END IF;

  SELECT count(*) INTO c FROM waitlist WHERE device_id = a AND opportunity_id = 'prof-Q';
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL 034-1: prof-Q went missing'; END IF;

  SELECT count(*) INTO c FROM waitlist WHERE device_id = b;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL 034-1: % rows left on the source', c; END IF;

  -- The surviving request has been standing since the earlier of the two.
  SELECT created_at INTO kept_at FROM waitlist
    WHERE device_id = a AND opportunity_id = 'prof-P';
  IF kept_at > now() - interval '8 days' THEN
    RAISE EXCEPTION 'TEST FAIL 034-1: kept the later created_at (%)', kept_at;
  END IF;

  -- An address is how the operator reaches them; the account's is not dropped.
  SELECT email INTO kept_email FROM waitlist
    WHERE device_id = a AND opportunity_id = 'prof-P';
  IF kept_email IS NULL THEN
    RAISE EXCEPTION 'TEST FAIL 034-1: the surviving request has no address';
  END IF;

  RAISE WARNING 'PASS 034-1 (same target on both devices merges; other targets survive)';
END $$;

-- =====================================================================
-- Scenario 2: a concierge request for professor P is not deleted because the
-- account already holds one for professor Q. Both writers hardcode
-- intent='apply_for_me', so the old (email,intent) key was really (email).
-- =====================================================================
DO $$
DECLARE
  a text := '22222222-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  b text := '22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  tok uuid; c int;
BEGIN
  INSERT INTO waitlist (device_id, email, intent, opportunity_id)
    VALUES (a, 'same@ex.com', 'apply_for_me', 'prof-Q');
  INSERT INTO waitlist (device_id, email, intent, opportunity_id)
    VALUES (b, 'same@ex.com', 'apply_for_me', 'prof-P');

  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('same@ex.com');
  PERFORM set_config('test.uid', a, false);
  PERFORM set_config('test.jwt', '{"email":"same@ex.com"}', false);
  PERFORM redeem_merge_grant(tok);

  SELECT count(*) INTO c FROM waitlist WHERE device_id = a AND opportunity_id = 'prof-P';
  IF c <> 1 THEN
    RAISE EXCEPTION 'TEST FAIL 034-2: the request for prof-P was deleted (found %)', c;
  END IF;
  RAISE WARNING 'PASS 034-2 (a request for one professor does not delete another)';
END $$;

-- =====================================================================
-- Scenario 3: the losing interaction is preserved, not deleted. Its notes are
-- salvaged onto the winner and the whole row is archived.
-- =====================================================================
DO $$
DECLARE
  a text := '33333333-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  b text := '33333333-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  tok uuid; merged_notes text; c int;
BEGIN
  -- Target wins on updated_at, so the SOURCE row is the loser.
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, notes,
                            last_contacted_at, updated_at)
    VALUES (a, 'opp1', 'applied', 'account note',
            now() - interval '3 days', now());
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, notes,
                            last_contacted_at, updated_at)
    VALUES (b, 'opp1', 'contacted', 'guest note nobody should lose',
            now() - interval '1 day', now() - interval '5 days');

  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('t3@ex.com');
  PERFORM set_config('test.uid', a, false);
  PERFORM set_config('test.jwt', '{"email":"t3@ex.com"}', false);
  PERFORM redeem_merge_grant(tok);

  SELECT notes INTO merged_notes FROM interactions
    WHERE device_id = a AND opportunity_id = 'opp1';
  IF merged_notes NOT LIKE '%account note%' THEN
    RAISE EXCEPTION 'TEST FAIL 034-3: the winner lost its own notes: %', merged_notes;
  END IF;
  IF merged_notes NOT LIKE '%guest note nobody should lose%' THEN
    RAISE EXCEPTION 'TEST FAIL 034-3: the loser''s notes were dropped: %', merged_notes;
  END IF;

  -- last_contacted_at is monotone: the later of the two survives.
  SELECT count(*) INTO c FROM interactions
    WHERE device_id = a AND opportunity_id = 'opp1'
      AND last_contacted_at > now() - interval '2 days';
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL 034-3: last_contacted_at went backwards'; END IF;

  -- And the discarded row is kept whole.
  SELECT count(*) INTO c FROM interaction_merge_archive
    WHERE device_id = a AND opportunity_id = 'opp1'
      AND interaction->>'notes' = 'guest note nobody should lose';
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL 034-3: nothing was archived (%)', c; END IF;

  RAISE WARNING 'PASS 034-3 (the losing entry is salvaged onto the winner and archived)';
END $$;

-- =====================================================================
-- Scenario 4: a live reminder is never replaced by a dead one.
--
-- Every merge source is an anonymous session, anonymous devices have no
-- delivery channel, so their remind_at accumulates past dates that never fire
-- and never clear. least() would pick exactly those over the account's live
-- future date, and the next cron run would fire a reminder for something
-- dealt with months ago and then clear it.
-- =====================================================================
DO $$
DECLARE
  a text := '44444444-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  b text := '44444444-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  tok uuid; kept date; c int;
BEGIN
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, remind_at, updated_at)
    VALUES (a, 'opp1', 'applied', (now() + interval '30 days')::date, now());
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, remind_at, updated_at)
    VALUES (b, 'opp1', 'contacted', (now() - interval '200 days')::date,
            now() - interval '5 days');
  -- And one the account never set, where the guest's is still ahead of us.
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, remind_at, updated_at)
    VALUES (a, 'opp2', 'applied', NULL, now());
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, remind_at, updated_at)
    VALUES (b, 'opp2', 'contacted', (now() + interval '10 days')::date,
            now() - interval '5 days');

  PERFORM set_config('test.uid', b, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('t4@ex.com');
  PERFORM set_config('test.uid', a, false);
  PERFORM set_config('test.jwt', '{"email":"t4@ex.com"}', false);
  PERFORM redeem_merge_grant(tok);

  SELECT remind_at INTO kept FROM interactions
    WHERE device_id = a AND opportunity_id = 'opp1';
  IF kept < now()::date THEN
    RAISE EXCEPTION 'TEST FAIL 034-4: a dead reminder (%) replaced the live one', kept;
  END IF;

  SELECT remind_at INTO kept FROM interactions
    WHERE device_id = a AND opportunity_id = 'opp2';
  IF kept IS NULL OR kept < now()::date THEN
    RAISE EXCEPTION 'TEST FAIL 034-4: a still-future reminder was not adopted (%)', kept;
  END IF;

  RAISE WARNING 'PASS 034-4 (a live reminder survives; only a future one is adopted)';
END $$;

SELECT 'ALL 034 MERGE-PRESERVATION TESTS PASSED' AS result;
