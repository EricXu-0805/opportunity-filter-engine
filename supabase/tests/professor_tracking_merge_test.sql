-- Professor tracking merge test (migrations 022 + 023). Runs after
-- flow_b_merge_test.sql in the same ephemeral cluster, so it uses fresh
-- actor uids (7/8) that no prior scenario has minted, merged, or tombstoned.
--
-- Asserts that redeem_merge_grant (as replaced by 023) claims BOTH new
-- tables: professor_follows as a set union with target-wins on the
-- (device_id, professor_id) UNIQUE conflict, professor_update_reads with the
-- target's cursor kept on PK conflict — mirroring 021's resume handling.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

DO $$
DECLARE
  t text := '77777777-7777-4777-8777-777777777777';  -- target account
  s text := '88888888-8888-4888-8888-888888888888';  -- anon source device
  prof_shared text := 'prof:v1:uiuc:aaaaaaaaaaaaaaaaaaaa';
  prof_target text := 'prof:v1:uiuc:bbbbbbbbbbbbbbbbbbbb';
  prof_source text := 'prof:v1:stanford:cccccccccccccccccccc';
  ev_old text := 'prof-event:v1:000000000000000000000001';
  ev_new text := 'prof-event:v1:000000000000000000000002';
  tok uuid;
  res jsonb;
  c int;
BEGIN
  -- ---- seed TARGET (T) ----
  INSERT INTO professor_follows (device_id, professor_id, professor_name, school)
    VALUES (t, prof_shared, 'Jane Doe', 'uiuc'),
           (t, prof_target, 'John Roe', 'uiuc');
  INSERT INTO professor_update_reads (device_id, professor_id, last_read_event_id)
    VALUES (t, prof_shared, ev_new);

  -- ---- seed SOURCE (S) ----
  INSERT INTO professor_follows (device_id, professor_id, professor_name, school)
    VALUES (s, prof_shared, 'Jane Doe', 'uiuc'),          -- dup -> dropped
           (s, prof_source, 'Ada Lovelace', 'stanford');  -- new -> moved
  INSERT INTO professor_update_reads (device_id, professor_id, last_read_event_id)
    VALUES (s, prof_shared, ev_old),                      -- conflict -> target's kept
           (s, prof_source, ev_old);                      -- new -> moved

  -- ---- mint as anon S (bound to T's email), redeem as T ----
  PERFORM set_config('test.uid', s, false);
  PERFORM set_config('test.jwt', '{"is_anonymous": true}', false);
  tok := mint_merge_grant('prof-tracking@ex.com');

  PERFORM set_config('test.uid', t, false);
  PERFORM set_config('test.jwt', '{"email":"prof-tracking@ex.com"}', false);
  res := redeem_merge_grant(tok);

  IF (res->>'merged')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST FAIL prof-merge: expected merged=true, got %', res;
  END IF;

  -- follows: union of {shared, target, source} under the target, none left
  -- under the source.
  SELECT count(*) INTO c FROM professor_follows WHERE device_id = t;
  IF c <> 3 THEN RAISE EXCEPTION 'TEST FAIL prof-merge follows: want 3 got %', c; END IF;
  PERFORM 1 FROM professor_follows WHERE device_id = t AND professor_id = prof_source
    AND professor_name = 'Ada Lovelace' AND school = 'stanford';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL prof-merge: source follow not moved'; END IF;
  SELECT count(*) INTO c FROM professor_follows WHERE device_id = s;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL prof-merge: % follows stranded on source', c; END IF;
  IF (res#>>'{summary,professor_follows}')::int <> 1 THEN
    RAISE EXCEPTION 'TEST FAIL prof-merge summary: professor_follows was %',
      res#>>'{summary,professor_follows}';
  END IF;

  -- read cursors: target's cursor wins the conflict, source-only cursor moves.
  SELECT count(*) INTO c FROM professor_update_reads WHERE device_id = t;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL prof-merge reads: want 2 got %', c; END IF;
  PERFORM 1 FROM professor_update_reads
    WHERE device_id = t AND professor_id = prof_shared AND last_read_event_id = ev_new;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL prof-merge: target cursor should win conflict'; END IF;
  PERFORM 1 FROM professor_update_reads
    WHERE device_id = t AND professor_id = prof_source AND last_read_event_id = ev_old;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL prof-merge: source-only cursor not moved'; END IF;
  SELECT count(*) INTO c FROM professor_update_reads WHERE device_id = s;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL prof-merge: % cursors stranded on source', c; END IF;

  RAISE WARNING 'PASS professor tracking merge (022/023: follows union + cursor target-wins + drain)';
END $$;

-- Malformed ids must be rejected at the table boundary (CHECK constraints).
DO $$
BEGIN
  BEGIN
    INSERT INTO professor_follows (device_id, professor_id)
      VALUES ('77777777-7777-4777-8777-777777777777', 'faculty-uiuc-not-a-tracking-id');
    RAISE EXCEPTION 'TEST FAIL prof-merge: malformed professor_id was accepted';
  EXCEPTION WHEN check_violation THEN
    NULL;  -- expected
  END;
  BEGIN
    INSERT INTO professor_update_reads (device_id, professor_id, last_read_event_id)
      VALUES ('77777777-7777-4777-8777-777777777777',
              'prof:v1:uiuc:dddddddddddddddddddd', 'not-an-event-id');
    RAISE EXCEPTION 'TEST FAIL prof-merge: malformed last_read_event_id was accepted';
  EXCEPTION WHEN check_violation THEN
    NULL;  -- expected
  END;
END $$;
