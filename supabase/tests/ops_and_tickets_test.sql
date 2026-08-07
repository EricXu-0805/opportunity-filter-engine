-- W15: feedback-ticket lifecycle + unified operational-incident queue.
--
-- Runs after every migration in the Flow B harness (ephemeral Postgres, GUC
-- stubs for auth.uid()/auth.jwt()). Asserts the invariants the product
-- boundary depends on:
--
--   * a resolved ticket/incident must carry a decision (no silent closes)
--   * submission idempotency (one ticket per client token)
--   * account isolation (a user reads only their own tickets)
--   * re-detection NEVER resolves or clears an open incident
--   * verified recovery is evidence; auto-resolve is opt-in per kind
--   * ambiguous review decisions stay ambiguous
--   * every handling step leaves an audit event

-- ---------------------------------------------------------------------------
-- Scenario 1: ticket lifecycle + audit + no-silent-close
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  u text := 'aaaa1111-1111-4111-8111-111111111111';
  tid uuid;
  c int;
  s text;
BEGIN
  PERFORM set_config('test.uid', u, false);
  INSERT INTO feedback (device_id, message, category, subject, client_token)
    VALUES (u, 'The tracker lost my note', 'bug', 'Lost note', 'tok-1')
    RETURNING id INTO tid;

  -- Arrival state is open/normal with no decision attached.
  SELECT status INTO s FROM feedback WHERE id = tid;
  IF s <> 'open' THEN RAISE EXCEPTION 'TEST FAIL t1: want open got %', s; END IF;
  PERFORM 1 FROM feedback WHERE id = tid AND priority = 'normal' AND resolution IS NULL;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL t1: unexpected arrival state'; END IF;

  -- A reply is NOT a resolution: recording one must leave the ticket unresolved.
  UPDATE feedback SET admin_reply = 'Thanks — reproducing now.', admin_reply_at = now(),
    admin_reply_by = 'ops:alice', admin_reply_delivery = 'stored', status = 'in_progress'
    WHERE id = tid;
  INSERT INTO feedback_events (ticket_id, actor, action, to_value)
    VALUES (tid, 'ops:alice', 'replied', 'stored');
  SELECT status INTO s FROM feedback WHERE id = tid;
  IF s <> 'in_progress' THEN RAISE EXCEPTION 'TEST FAIL t1: reply changed state to %', s; END IF;
  PERFORM 1 FROM feedback WHERE id = tid AND resolution IS NULL;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL t1: reply must not resolve'; END IF;

  -- Silent close is impossible: resolved without a decision violates the CHECK.
  BEGIN
    UPDATE feedback SET status = 'resolved' WHERE id = tid;
    RAISE EXCEPTION 'TEST FAIL t1: resolved without a resolution was allowed';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  UPDATE feedback SET status = 'resolved', resolution = 'fixed',
    resolved_by = 'ops:alice', resolved_at = now() WHERE id = tid;
  INSERT INTO feedback_events (ticket_id, actor, action, from_value, to_value)
    VALUES (tid, 'ops:alice', 'resolved', 'in_progress', 'resolved');

  SELECT count(*) INTO c FROM feedback_events WHERE ticket_id = tid;
  IF c <> 2 THEN RAISE EXCEPTION 'TEST FAIL t1: want 2 audit events got %', c; END IF;

  -- Invalid enum values are rejected rather than silently stored.
  BEGIN
    UPDATE feedback SET status = 'wishful' WHERE id = tid;
    RAISE EXCEPTION 'TEST FAIL t1: bogus status accepted';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  RAISE WARNING 'PASS scenario 1 (ticket lifecycle, reply != resolution, no silent close)';
END $$;

-- ---------------------------------------------------------------------------
-- Scenario 2: submission idempotency + account isolation
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  u1 text := 'bbbb2222-2222-4222-8222-222222222222';
  u2 text := 'cccc3333-3333-4333-8333-333333333333';
  c int;
BEGIN
  INSERT INTO feedback (device_id, message, client_token)
    VALUES (u1, 'first try', 'retry-tok');

  -- A retry of the SAME submission collides instead of creating ticket B.
  BEGIN
    INSERT INTO feedback (device_id, message, client_token)
      VALUES (u1, 'first try', 'retry-tok');
    RAISE EXCEPTION 'TEST FAIL t2: duplicate client_token created a second ticket';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
  SELECT count(*) INTO c FROM feedback WHERE device_id = u1 AND client_token = 'retry-tok';
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL t2: want 1 ticket got %', c; END IF;

  -- The same token from a DIFFERENT user is a different submission.
  INSERT INTO feedback (device_id, message, client_token)
    VALUES (u2, 'unrelated', 'retry-tok');

  -- Legacy/tokenless rows are unconstrained (partial index).
  INSERT INTO feedback (device_id, message) VALUES (u1, 'no token a');
  INSERT INTO feedback (device_id, message) VALUES (u1, 'no token b');

  -- RLS: each account sees only its own tickets.
  SET LOCAL ROLE authenticated;
  PERFORM set_config('test.uid', u1, true);
  SELECT count(*) INTO c FROM feedback;
  IF c <> 3 THEN RAISE EXCEPTION 'TEST FAIL t2: u1 should see 3 own tickets, saw %', c; END IF;
  SELECT count(*) INTO c FROM feedback WHERE device_id = u2;
  IF c <> 0 THEN RAISE EXCEPTION 'TEST FAIL t2: u1 could read u2 tickets (%)', c; END IF;

  PERFORM set_config('test.uid', u2, true);
  SELECT count(*) INTO c FROM feedback;
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL t2: u2 should see 1 own ticket, saw %', c; END IF;
  RESET ROLE;

  RAISE WARNING 'PASS scenario 2 (idempotent submission, per-account isolation)';
END $$;

-- ---------------------------------------------------------------------------
-- Scenario 3: users cannot forge handling state
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  u text := 'dddd4444-4444-4444-8444-444444444444';
  tid uuid;
  n int;
BEGIN
  INSERT INTO feedback (device_id, message) VALUES (u, 'please fix') RETURNING id INTO tid;

  SET LOCAL ROLE authenticated;
  PERFORM set_config('test.uid', u, true);
  -- No UPDATE policy exists: the statement matches zero rows rather than
  -- letting a client mark its own ticket handled.
  UPDATE feedback SET status = 'resolved', resolution = 'fixed' WHERE id = tid;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 0 THEN RAISE EXCEPTION 'TEST FAIL t3: client updated a ticket (% rows)', n; END IF;

  -- The operator audit log is invisible to clients.
  SELECT count(*) INTO n FROM feedback_events;
  IF n <> 0 THEN RAISE EXCEPTION 'TEST FAIL t3: client read % audit events', n; END IF;
  RESET ROLE;

  PERFORM 1 FROM feedback WHERE id = tid AND status = 'open';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL t3: ticket state changed'; END IF;

  RAISE WARNING 'PASS scenario 3 (handling state is operator-owned)';
END $$;

-- ---------------------------------------------------------------------------
-- Scenario 4: collector incident — re-detection never clears, recovery does
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  iid uuid;
  iid2 uuid;
  s text;
  fs text;
  occ int;
  c int;
BEGIN
  iid := record_ops_incident(
    'collector_failure', 'collector_failure:uiuc_faculty',
    'uiuc_faculty scrape failed', 'HTTP 403 on 12 departments',
    '{"error_category":"blocked","departments":12}'::jsonb,
    'uiuc_faculty', 'high', 'blocked');

  PERFORM 1 FROM ops_incidents WHERE id = iid AND status = 'open'
    AND failure_state = 'blocked' AND occurrence_count = 1;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL o4: bad initial incident'; END IF;

  -- Operator takes it.
  UPDATE ops_incidents SET assigned_to = 'ops:bob', status = 'investigating' WHERE id = iid;
  INSERT INTO ops_incident_events (incident_id, actor, action, to_value)
    VALUES (iid, 'ops:bob', 'assigned', 'ops:bob');

  -- The next run fails again: same incident, bumped counters, assignment and
  -- status untouched (a re-detect must not stomp operator state).
  iid2 := record_ops_incident(
    'collector_failure', 'collector_failure:uiuc_faculty',
    'uiuc_faculty scrape failed', 'HTTP 403 on 14 departments',
    '{"error_category":"blocked","departments":14}'::jsonb,
    'uiuc_faculty', 'high', 'blocked');
  IF iid2 <> iid THEN RAISE EXCEPTION 'TEST FAIL o4: dedup_key created a second incident'; END IF;

  SELECT status, occurrence_count INTO s, occ FROM ops_incidents WHERE id = iid;
  IF s <> 'investigating' THEN RAISE EXCEPTION 'TEST FAIL o4: re-detect changed status to %', s; END IF;
  IF occ <> 2 THEN RAISE EXCEPTION 'TEST FAIL o4: want occurrence 2 got %', occ; END IF;
  PERFORM 1 FROM ops_incidents WHERE id = iid AND assigned_to = 'ops:bob';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL o4: re-detect cleared assignment'; END IF;

  -- A verified successful run: evidence recorded, and for collectors the
  -- incident may auto-resolve — but only through the recovery path.
  PERFORM record_ops_recovery('collector_failure:uiuc_faculty', true, 'clean run, 63 depts');
  SELECT status, failure_state INTO s, fs FROM ops_incidents WHERE id = iid;
  IF s <> 'resolved' OR fs <> 'recovered' THEN
    RAISE EXCEPTION 'TEST FAIL o4: recovery did not resolve (% / %)', s, fs;
  END IF;
  PERFORM 1 FROM ops_incidents WHERE id = iid AND resolution = 'auto_recovered'
    AND resolved_at IS NOT NULL;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL o4: missing recovery decision'; END IF;

  -- Failing again later REOPENS with a cleared verdict rather than staying closed.
  PERFORM record_ops_incident(
    'collector_failure', 'collector_failure:uiuc_faculty',
    'uiuc_faculty scrape failed', 'HTTP 403 again',
    '{"error_category":"blocked"}'::jsonb, 'uiuc_faculty', 'high', 'blocked');
  SELECT status INTO s FROM ops_incidents WHERE id = iid;
  IF s <> 'open' THEN RAISE EXCEPTION 'TEST FAIL o4: recurrence did not reopen (%)', s; END IF;
  PERFORM 1 FROM ops_incidents WHERE id = iid AND resolution IS NULL;
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL o4: stale resolution survived reopen'; END IF;

  SELECT count(*) INTO c FROM ops_incident_events WHERE incident_id = iid;
  IF c < 5 THEN RAISE EXCEPTION 'TEST FAIL o4: want >=5 audit events got %', c; END IF;

  RAISE WARNING 'PASS scenario 4 (collector incident: dedup, no-stomp, verified recovery, reopen)';
END $$;

-- ---------------------------------------------------------------------------
-- Scenario 5: drift never auto-resolves on a later successful run
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  iid uuid;
  s text;
BEGIN
  iid := record_ops_incident(
    'data_drift', 'data_drift:purdue:faculty_count',
    'purdue faculty count dropped 38%',
    'previous 2187, current 1348, threshold -15%',
    '{"metric":"faculty_count","previous":2187,"current":1348,"threshold_pct":-15}'::jsonb,
    'purdue', 'urgent', NULL);

  -- The collector ran fine afterwards — job success is NOT data-quality
  -- success, so the recovery signal must leave the alert open for review.
  PERFORM record_ops_recovery('data_drift:purdue:faculty_count', false, 'collector run succeeded');
  SELECT status INTO s FROM ops_incidents WHERE id = iid;
  IF s <> 'open' THEN RAISE EXCEPTION 'TEST FAIL o5: drift auto-closed by a job success (%)', s; END IF;

  -- A reviewer accepting the change is what closes it, with the decision kept.
  UPDATE ops_incidents SET status = 'resolved', resolution = 'legitimate_change',
    resolution_note = 'Purdue split the directory; 839 moved to a new source',
    resolved_by = 'ops:carol', resolved_at = now() WHERE id = iid;
  INSERT INTO ops_incident_events (incident_id, actor, action, from_value, to_value, note)
    VALUES (iid, 'ops:carol', 'resolved', 'open', 'resolved', 'legitimate_change');

  PERFORM 1 FROM ops_incidents WHERE id = iid AND resolution = 'legitimate_change'
    AND resolved_by = 'ops:carol';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL o5: reviewer decision not recorded'; END IF;

  RAISE WARNING 'PASS scenario 5 (drift: job success never suppresses, reviewer decision recorded)';
END $$;

-- ---------------------------------------------------------------------------
-- Scenario 6: manual review keeps ambiguity ambiguous
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  iid uuid;
  c int;
BEGIN
  iid := record_ops_incident(
    'manual_review', 'manual_review:publication:faculty-mit-eecs-abc123',
    'Ambiguous publication attribution',
    'name_match only; two same-name authors at the institution',
    '{"candidates":2,"attribution":"name_match"}'::jsonb,
    'mit', 'normal', NULL, 'faculty', 'faculty-mit-eecs-abc123', 'recent_works');

  -- An honest reviewer must be able to say "still unclear" without being
  -- forced into verified/rejected.
  UPDATE ops_incidents SET status = 'resolved', resolution = 'needs_more_evidence',
    resolution_note = 'Both candidates publish in the same subfield; ORCID absent',
    resolved_by = 'ops:dana', resolved_at = now() WHERE id = iid;
  PERFORM 1 FROM ops_incidents WHERE id = iid AND resolution = 'needs_more_evidence';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL o6: ambiguous decision rejected'; END IF;

  -- 'unknown' and 'conflicting' are equally valid terminal decisions.
  UPDATE ops_incidents SET resolution = 'unknown' WHERE id = iid;
  UPDATE ops_incidents SET resolution = 'conflicting' WHERE id = iid;

  -- Made-up verdicts are not.
  BEGIN
    UPDATE ops_incidents SET resolution = 'probably_fine' WHERE id = iid;
    RAISE EXCEPTION 'TEST FAIL o6: bogus resolution accepted';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  -- Review items carry the entity they point at, so a decision can be routed
  -- back to the authoritative record.
  SELECT count(*) INTO c FROM ops_incidents
    WHERE entity_type = 'faculty' AND entity_id = 'faculty-mit-eecs-abc123'
      AND field = 'recent_works';
  IF c <> 1 THEN RAISE EXCEPTION 'TEST FAIL o6: entity linkage missing'; END IF;

  RAISE WARNING 'PASS scenario 6 (manual review: ambiguity preserved, entity-linked)';
END $$;

-- ---------------------------------------------------------------------------
-- Scenario 7: no silent closes anywhere in the operational queue
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  iid uuid;
BEGIN
  iid := record_ops_incident(
    'notification_failure', 'notification_failure:sub-9',
    'Web push rejected', 'provider returned 500 three times',
    '{"channel":"webpush","attempts":3,"error_category":"provider_5xx"}'::jsonb,
    'push', 'normal', 'failed');

  BEGIN
    UPDATE ops_incidents SET status = 'resolved' WHERE id = iid;
    RAISE EXCEPTION 'TEST FAIL o7: incident resolved with no decision';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  BEGIN
    UPDATE ops_incidents SET status = 'suppressed' WHERE id = iid;
    RAISE EXCEPTION 'TEST FAIL o7: incident suppressed with no reason';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  -- Unacknowledged notification failures stay actionable.
  PERFORM 1 FROM ops_incidents WHERE id = iid AND status = 'open' AND failure_state = 'failed';
  IF NOT FOUND THEN RAISE EXCEPTION 'TEST FAIL o7: notification incident not actionable'; END IF;

  RAISE WARNING 'PASS scenario 7 (no silent closes in the ops queue)';
END $$;

SELECT 'ALL W15 OPS + TICKET TESTS PASSED' AS result;
