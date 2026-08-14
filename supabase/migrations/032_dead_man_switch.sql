-- 032_dead_man_switch.sql
-- The one failure this repository has never been able to see: the automation
-- stopped running.
--
-- It has happened twice. `Refresh Opportunity Data` was dead for 8 days in
-- August and 18 days before that, and nothing anywhere raised a hand — every
-- detector we own runs *inside* the thing that stopped. A collector that
-- never starts produces no failing collector_status; a cron that GitHub
-- disabled emits no red run; a scan that is not scheduled reports nothing
-- rather than reporting that it reported nothing. Absence has no log line.
--
-- A dead man's switch inverts that: instead of the job telling us it broke,
-- the job must keep telling us it is alive, and a DIFFERENT system raises the
-- incident when it goes quiet. The two systems here watch each other:
--
--   * Postgres watches GitHub. Every scheduled workflow checks in through
--     `record_ops_heartbeat`; a pg_cron job runs `ops_dead_man_sweep()` every
--     ten minutes and files a `collector_failure` incident for anything
--     overdue. GitHub Actions being disabled, unscheduled, out of minutes, or
--     silently no-op does not stop this from firing.
--   * GitHub watches Postgres. The sweep records its own heartbeat, and the
--     daily `/api/cron/ops-scan` checks that one. pg_cron being uninstalled,
--     unscheduled, or erroring does not stop THAT from firing.
--
-- Neither can go quiet without the other noticing, and the incidents land in
-- `ops_incidents`, which `scripts/release_gate.py::check_open_incidents`
-- already reads — so a pipeline that dies unnoticed turns the release gate
-- red by itself.
--
-- WHY THE DEADLINE COUNTS FROM `registered_at` WHEN nothing has checked in:
-- "wired up but never actually called" is this repository's single most
-- common defect. A heartbeat that has never once been received is exactly as
-- broken as one that stopped, and is treated identically.

-- ---------------------------------------------------------------------------
-- The registry of things that must keep proving they are alive
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_heartbeats (
  -- Stable key used by the caller and by the incident dedup_key.
  name text PRIMARY KEY,

  -- What goes silent if this stops, in operator language. This is the text a
  -- future reader sees at 2am; it is not decoration.
  description text NOT NULL,

  -- How often the caller is expected to check in, and how late it may be
  -- before that is an incident. Grace absorbs GitHub's scheduled-run queue
  -- delay, which routinely runs tens of minutes behind the cron expression.
  expected_interval_seconds int NOT NULL CHECK (expected_interval_seconds > 0),
  grace_seconds int NOT NULL DEFAULT 0 CHECK (grace_seconds >= 0),

  priority text NOT NULL DEFAULT 'high'
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),

  -- Deliberate, recorded silence. A heartbeat that is not expected right now
  -- (a seasonal job, a drill row being torn down) is disabled with a reason
  -- rather than deleted, so "we stopped watching" is itself visible.
  enabled boolean NOT NULL DEFAULT true,
  disabled_reason text,

  -- NULL means never once received. See the header: that is a failure state,
  -- not a warm-up state.
  last_seen_at timestamptz,
  last_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  seen_count bigint NOT NULL DEFAULT 0,

  registered_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ops_heartbeats_disabled_has_reason
    CHECK (enabled OR disabled_reason IS NOT NULL)
);

ALTER TABLE ops_heartbeats ENABLE ROW LEVEL SECURITY;
-- No policies: operator-only, same posture as ops_incidents. Reached with the
-- service-role key by the backend, and by pg_cron inside the database.

CREATE INDEX IF NOT EXISTS ops_heartbeats_due_idx
  ON ops_heartbeats (enabled, last_seen_at);

-- The deadline every reader agrees on, defined once, so the sweep, the API
-- and any ad-hoc operator query cannot drift apart on what "overdue" means.
--
-- A generated column would have been the obvious home for it and is not
-- available: `timestamptz + interval` is STABLE rather than IMMUTABLE (adding
-- days or months depends on the session time zone), and a generated column
-- requires IMMUTABLE. A view is the honest substitute — same single
-- definition, computed at read time.
CREATE OR REPLACE VIEW ops_heartbeat_status
  WITH (security_invoker = true) AS
SELECT
  h.*,
  coalesce(h.last_seen_at, h.registered_at)
    + (h.expected_interval_seconds + h.grace_seconds) * interval '1 second'
    AS due_at,
  now() > coalesce(h.last_seen_at, h.registered_at)
    + (h.expected_interval_seconds + h.grace_seconds) * interval '1 second'
    AS overdue
FROM ops_heartbeats h;

REVOKE ALL ON ops_heartbeat_status FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Check-in
-- ---------------------------------------------------------------------------
-- Returns false for an unknown name instead of creating the row. A typo in a
-- workflow must surface as "that heartbeat does not exist" at the caller, not
-- as a brand-new row that silently satisfies nothing and leaves the real
-- heartbeat still overdue.
CREATE OR REPLACE FUNCTION public.record_ops_heartbeat(
  p_name text,
  p_detail jsonb DEFAULT '{}'::jsonb
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_found boolean;
BEGIN
  UPDATE ops_heartbeats SET
    last_seen_at = now(),
    last_detail = coalesce(p_detail, '{}'::jsonb),
    seen_count = seen_count + 1,
    updated_at = now()
  WHERE name = p_name
  RETURNING true INTO v_found;

  RETURN coalesce(v_found, false);
END;
$$;

-- ---------------------------------------------------------------------------
-- The sweep
-- ---------------------------------------------------------------------------
-- Files an incident for every enabled heartbeat past its deadline, and
-- records verified recovery for every one that has come back. Recovery
-- auto-resolves here — unlike drift detection, the evidence is complete and
-- unambiguous: the database itself timestamped the check-in. The event trail
-- on ops_incident_events keeps the outage on the record either way.
--
-- Returns one row per heartbeat it acted on, so an operator running it by
-- hand sees what it did rather than a bare count.
CREATE OR REPLACE FUNCTION public.ops_dead_man_sweep()
RETURNS TABLE (name text, action text, overdue_seconds bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  hb record;
  v_overdue bigint;
BEGIN
  FOR hb IN SELECT * FROM ops_heartbeat_status WHERE enabled ORDER BY name LOOP
    IF hb.overdue THEN
      v_overdue := floor(extract(epoch FROM now() - hb.due_at))::bigint;
      PERFORM record_ops_incident(
        p_kind => 'collector_failure',
        p_dedup_key => 'dead_man:' || hb.name,
        p_title => 'Heartbeat overdue: ' || hb.name,
        p_summary => hb.description || ' — last check-in '
          || coalesce(hb.last_seen_at::text, 'never')
          || ', overdue by ' || v_overdue || 's.',
        p_detail => jsonb_build_object(
          'heartbeat', hb.name,
          'last_seen_at', hb.last_seen_at,
          'registered_at', hb.registered_at,
          'due_at', hb.due_at,
          'overdue_seconds', v_overdue,
          'expected_interval_seconds', hb.expected_interval_seconds,
          'grace_seconds', hb.grace_seconds,
          'seen_count', hb.seen_count,
          'detected_by', 'ops_dead_man_sweep'
        ),
        p_scope => hb.name,
        p_priority => hb.priority,
        p_failure_state => CASE WHEN hb.last_seen_at IS NULL THEN 'blocked' ELSE 'failed' END
      );
      name := hb.name; action := 'overdue'; overdue_seconds := v_overdue;
      RETURN NEXT;
    ELSIF record_ops_recovery(
      p_dedup_key => 'dead_man:' || hb.name,
      p_auto_resolve => true,
      p_note => 'heartbeat received at ' || hb.last_seen_at::text
    ) THEN
      name := hb.name; action := 'recovered'; overdue_seconds := 0;
      RETURN NEXT;
    END IF;
  END LOOP;

  -- The sweep's own liveness, for the other half of the mutual watch: the
  -- daily ops-scan reads this one. Recorded last and unconditionally, so it
  -- proves the whole body ran rather than that the function was entered.
  PERFORM record_ops_heartbeat('ops_dead_man_sweep',
    jsonb_build_object('source', 'pg_cron'));
END;
$$;

REVOKE ALL ON FUNCTION public.record_ops_heartbeat(text, jsonb)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ops_dead_man_sweep() FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------
-- The registry itself
-- ---------------------------------------------------------------------------
-- One row per scheduled workflow in .github/workflows plus the sweep. Kept in
-- sync by TestTheRegistryMatchesTheSchedulers in tests/test_ops_incidents.py,
-- which parses this INSERT and the workflow files and fails CI in either
-- direction: a scheduled workflow with no heartbeat is an unwatched
-- scheduler, and a heartbeat no workflow writes goes overdue forever and
-- trains the operator to ignore the queue.
--
-- Intervals are the cron period; grace is generous because GitHub's shared
-- scheduled-run queue is routinely 10-40 minutes late and a false incident
-- every morning would train us to ignore the queue.
INSERT INTO ops_heartbeats
  (name, description, expected_interval_seconds, grace_seconds, priority)
VALUES
  ('refresh_data',
   'Daily corpus refresh (06:00 UTC). If this stops, every opportunity on the site quietly ages out.',
   86400, 21600, 'urgent'),
  ('ops_scan',
   'Daily operational detector (07:30 UTC). If this stops, collector failures and data drift stop being filed.',
   86400, 21600, 'high'),
  ('daily_reminders',
   'Daily follow-up reminder send (23:00 UTC). If this stops, users silently stop being nudged about outreach they scheduled.',
   86400, 21600, 'high'),
  ('saved_searches_refresh',
   'Daily saved-search refresh + digest (23:30 UTC). If this stops, saved searches silently stop matching new records.',
   86400, 21600, 'high'),
  ('campus_seed_health',
   'Weekly campus seed health check (Sun 12:00 UTC). If this stops, unreachable school seeds stop being reported.',
   604800, 86400, 'normal'),
  ('ops_dead_man_sweep',
   'The dead-man sweep itself, run by pg_cron every 10 minutes. If this stops, nothing is watching the schedulers.',
   600, 1800, 'urgent')
ON CONFLICT (name) DO UPDATE SET
  description = EXCLUDED.description,
  expected_interval_seconds = EXCLUDED.expected_interval_seconds,
  grace_seconds = EXCLUDED.grace_seconds,
  priority = EXCLUDED.priority,
  updated_at = now();

-- ---------------------------------------------------------------------------
-- Scheduling
-- ---------------------------------------------------------------------------
-- pg_cron exists on Supabase and not on the vanilla Postgres the migration
-- replay tests spin up, so this is conditional. That makes the schedule the
-- one part of this migration a green CI cannot prove — which is exactly why
-- `ops_dead_man_sweep` is in the registry above and the daily ops-scan reads
-- it: if this block silently did nothing in production, the sweep's own
-- heartbeat goes stale within 40 minutes and GitHub files the incident.
--
-- The two conditions are checked explicitly rather than by catching the
-- error: `CREATE EXTENSION pg_cron` fails outright unless the library is
-- preloaded, and a bare EXCEPTION WHEN OTHERS around scheduling is how you
-- end up believing you have a dead man's switch that was never armed.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron')
     AND coalesce(current_setting('shared_preload_libraries', true), '') LIKE '%pg_cron%'
  THEN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
    PERFORM cron.unschedule(jobid) FROM cron.job WHERE jobname = 'ops-dead-man-sweep';
    PERFORM cron.schedule('ops-dead-man-sweep', '*/10 * * * *',
                          'SELECT public.ops_dead_man_sweep()');
    RAISE NOTICE 'ops-dead-man-sweep scheduled every 10 minutes';
  ELSE
    RAISE NOTICE 'pg_cron not loadable here: ops_dead_man_sweep is installed but NOT scheduled';
  END IF;
END;
$$;
