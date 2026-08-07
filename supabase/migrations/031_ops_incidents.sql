-- 027_ops_incidents.sql
-- W15: ONE durable operational queue for everything an operator must act on.
--
-- Before this, operational failures lived only where they happened: collector
-- errors in a rolling collector_status.json snapshot (a new run overwrote the
-- previous failure), data-quality regressions in an admin GET that computed
-- them on the fly and forgot them, notification failures in a cron response
-- counter, and manual-review requirements in JSON ledgers and record
-- metadata with no queue at all. None of it was assignable, none of it was
-- resolvable, and none of it survived the next run.
--
-- Rather than four parallel systems this is one table with a `kind`
-- discriminator, because the operator workflow is identical for all four:
-- see it, assign it, act on it, resolve it with a recorded decision.
--
-- WRITERS: detectors (backend, service role — fed by cron runs and the
-- existing quality artifacts) upsert on `dedup_key`; operators mutate through
-- the admin API. Supabase rather than a committed JSON artifact because the
-- backend cannot commit to git: an operator's assign/resolve has to land
-- somewhere the API can write.
--
-- CORE INVARIANT (spec §14/§17): re-detection NEVER resolves and NEVER
-- silently reopens-then-clears. A new collector run merely starting, or a
-- later successful run, does not by itself close an incident — only verified
-- recovery (detector-supplied evidence) or an operator decision does. The
-- upsert path below can therefore only ever bump the sighting counters.

CREATE TABLE IF NOT EXISTS ops_incidents (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,

  kind text NOT NULL CHECK (kind IN (
    'collector_failure', 'data_drift', 'notification_failure', 'manual_review'
  )),

  -- Stable identity of the underlying problem, e.g.
  -- 'collector_failure:uiuc_faculty', 'data_drift:purdue:faculty_count',
  -- 'notification_failure:<subscription>', 'manual_review:publication:<id>'.
  -- Detectors upsert on this so re-detecting the same problem updates one
  -- row instead of flooding the queue.
  dedup_key text NOT NULL UNIQUE,

  -- What it is about. scope = collector/source/school label; entity_* is set
  -- for manual-review items that point at a specific record.
  scope text,
  entity_type text,
  entity_id text,
  field text,

  title text NOT NULL,
  summary text,
  -- Evidence payload: metric/previous/current/threshold for drift, error
  -- category + attempt history for notifications, source excerpt + conflict
  -- pair for review items. Never secrets, tokens, or raw message bodies.
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,

  priority text NOT NULL DEFAULT 'normal'
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),

  status text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'acknowledged', 'investigating', 'resolved', 'suppressed')),

  -- Collector-specific lifecycle state (spec §14). 'recovered' is set ONLY by
  -- a detector that observed a verified successful run — it is evidence, not
  -- a resolution: the incident still needs closing so the recovery is
  -- reviewed rather than silently swallowed.
  failure_state text CHECK (failure_state IS NULL OR failure_state IN (
    'failed', 'timed_out', 'blocked', 'partial', 'recovered'
  )),

  assigned_to text,

  first_detected_at timestamptz NOT NULL DEFAULT now(),
  last_detected_at timestamptz NOT NULL DEFAULT now(),
  occurrence_count int NOT NULL DEFAULT 1,
  last_success_at timestamptz,

  -- Retry bookkeeping (notification failures, collector retries).
  attempt_count int NOT NULL DEFAULT 0,
  last_attempt_at timestamptz,
  next_retry_at timestamptz,

  -- Resolution taxonomy spans all four kinds, including the review decisions
  -- that are deliberately NOT verified/rejected: an ambiguous case must be
  -- allowed to stay ambiguous (spec §21).
  resolution text CHECK (resolution IS NULL OR resolution IN (
    -- operational
    'auto_recovered', 'fixed', 'legitimate_change', 'wont_fix',
    'duplicate', 'not_reproducible', 'suppressed',
    -- manual-review decisions
    'verified', 'rejected', 'unknown', 'conflicting', 'needs_more_evidence'
  )),
  resolution_note text,
  resolved_by text,
  resolved_at timestamptz,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- No silent closes: a resolved/suppressed incident must carry its decision.
ALTER TABLE ops_incidents DROP CONSTRAINT IF EXISTS ops_incidents_resolved_has_decision;
ALTER TABLE ops_incidents ADD CONSTRAINT ops_incidents_resolved_has_decision
  CHECK (status NOT IN ('resolved', 'suppressed') OR resolution IS NOT NULL);

CREATE INDEX IF NOT EXISTS ops_incidents_queue_idx
  ON ops_incidents (status, kind, priority, last_detected_at DESC);
CREATE INDEX IF NOT EXISTS ops_incidents_kind_idx
  ON ops_incidents (kind, last_detected_at DESC);
CREATE INDEX IF NOT EXISTS ops_incidents_entity_idx
  ON ops_incidents (entity_type, entity_id);

ALTER TABLE ops_incidents ENABLE ROW LEVEL SECURITY;
-- No policies: operator-only. Detectors and the admin API reach it with the
-- service-role key; no anon/authenticated client can read or write it.

-- ---------------------------------------------------------------------------
-- Append-only audit trail for operational handling
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_incident_events (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  incident_id uuid NOT NULL REFERENCES ops_incidents(id) ON DELETE CASCADE,
  -- Self-declared operator label (or 'detector' for automated sightings).
  actor text NOT NULL,
  action text NOT NULL CHECK (action IN (
    'detected', 'recurred', 'recovery_observed', 'assigned', 'unassigned',
    'priority_changed', 'status_changed', 'retried', 'resolved', 'reopened',
    'note_added'
  )),
  from_value text,
  to_value text,
  note text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ops_incident_events_incident_idx
  ON ops_incident_events (incident_id, created_at DESC);

ALTER TABLE ops_incident_events ENABLE ROW LEVEL SECURITY;
-- No policies: same operator-only containment as ops_incidents.

-- ---------------------------------------------------------------------------
-- Detector upsert: the ONLY automated write path
-- ---------------------------------------------------------------------------
-- Idempotent by dedup_key. On a repeat sighting it bumps last_detected_at /
-- occurrence_count and refreshes the evidence — it CANNOT change status,
-- resolution, or assignment. That is what stops a new collector run from
-- clearing an unresolved failure, and stops a later successful run from
-- silently suppressing a drift alert.
--
-- A previously-resolved incident that is detected AGAIN reopens (status
-- 'open', resolution cleared) and logs 'reopened' — a recurrence is new
-- information, not a continuation of the closed one.
CREATE OR REPLACE FUNCTION public.record_ops_incident(
  p_kind text,
  p_dedup_key text,
  p_title text,
  p_summary text DEFAULT NULL,
  p_detail jsonb DEFAULT '{}'::jsonb,
  p_scope text DEFAULT NULL,
  p_priority text DEFAULT 'normal',
  p_failure_state text DEFAULT NULL,
  p_entity_type text DEFAULT NULL,
  p_entity_id text DEFAULT NULL,
  p_field text DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_id uuid;
  v_status text;
BEGIN
  SELECT id, status INTO v_id, v_status
    FROM ops_incidents WHERE dedup_key = p_dedup_key;

  IF v_id IS NULL THEN
    INSERT INTO ops_incidents (
      kind, dedup_key, title, summary, detail, scope, priority,
      failure_state, entity_type, entity_id, field
    ) VALUES (
      p_kind, p_dedup_key, p_title, p_summary, coalesce(p_detail, '{}'::jsonb),
      p_scope, p_priority, p_failure_state, p_entity_type, p_entity_id, p_field
    ) RETURNING id INTO v_id;

    INSERT INTO ops_incident_events (incident_id, actor, action, to_value, note)
      VALUES (v_id, 'detector', 'detected', p_failure_state, p_summary);
    RETURN v_id;
  END IF;

  IF v_status IN ('resolved', 'suppressed') THEN
    -- Recurrence after closure: reopen with a clean slate so the old
    -- decision cannot be mistaken for a verdict on the new sighting.
    UPDATE ops_incidents SET
      status = 'open', resolution = NULL, resolution_note = NULL,
      resolved_by = NULL, resolved_at = NULL,
      detail = coalesce(p_detail, '{}'::jsonb),
      failure_state = coalesce(p_failure_state, failure_state),
      last_detected_at = now(), occurrence_count = occurrence_count + 1,
      updated_at = now()
    WHERE id = v_id;
    INSERT INTO ops_incident_events (incident_id, actor, action, from_value, to_value, note)
      VALUES (v_id, 'detector', 'reopened', v_status, 'open', p_summary);
  ELSE
    -- Still open: refresh evidence and counters ONLY.
    UPDATE ops_incidents SET
      detail = coalesce(p_detail, '{}'::jsonb),
      failure_state = coalesce(p_failure_state, failure_state),
      summary = coalesce(p_summary, summary),
      last_detected_at = now(), occurrence_count = occurrence_count + 1,
      updated_at = now()
    WHERE id = v_id;
    INSERT INTO ops_incident_events (incident_id, actor, action, to_value, note)
      VALUES (v_id, 'detector', 'recurred', p_failure_state, p_summary);
  END IF;

  RETURN v_id;
END;
$$;

-- ---------------------------------------------------------------------------
-- Verified recovery: evidence in, resolution NOT automatic
-- ---------------------------------------------------------------------------
-- A detector that observes a genuinely successful run for a scope calls this.
-- It records the success and flips failure_state to 'recovered', but leaves
-- the incident OPEN unless p_auto_resolve is explicitly true (collector
-- incidents opt in; drift alerts never do — §17 requires data to return to
-- expected state or a reviewer to accept the change).
CREATE OR REPLACE FUNCTION public.record_ops_recovery(
  p_dedup_key text,
  p_auto_resolve boolean DEFAULT false,
  p_note text DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_id uuid;
  v_status text;
BEGIN
  SELECT id, status INTO v_id, v_status
    FROM ops_incidents WHERE dedup_key = p_dedup_key;
  IF v_id IS NULL OR v_status IN ('resolved', 'suppressed') THEN
    RETURN false;
  END IF;

  UPDATE ops_incidents SET
    failure_state = 'recovered', last_success_at = now(), updated_at = now()
  WHERE id = v_id;
  INSERT INTO ops_incident_events (incident_id, actor, action, to_value, note)
    VALUES (v_id, 'detector', 'recovery_observed', 'recovered', p_note);

  IF p_auto_resolve THEN
    UPDATE ops_incidents SET
      status = 'resolved', resolution = 'auto_recovered',
      resolution_note = coalesce(p_note, 'verified successful run observed'),
      resolved_by = 'detector', resolved_at = now(), updated_at = now()
    WHERE id = v_id;
    INSERT INTO ops_incident_events (incident_id, actor, action, from_value, to_value, note)
      VALUES (v_id, 'detector', 'resolved', v_status, 'resolved', 'auto_recovered');
  END IF;

  RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.record_ops_incident(
  text, text, text, text, jsonb, text, text, text, text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_ops_recovery(text, boolean, text) FROM PUBLIC, anon, authenticated;
