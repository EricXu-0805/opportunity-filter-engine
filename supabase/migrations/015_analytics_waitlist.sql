-- 015: product-analytics funnel events + paid-intent waitlist.
--
-- analytics_events: one row per funnel step (landed, generated matches, opened
-- an opportunity, used an AI feature, clicked the "apply for me" intent) so we
-- can finally see WHERE users drop off. waitlist: a concierge "do it for me"
-- paid-intent capture (email + context) used to validate willingness-to-pay
-- before Stripe exists.
--
-- Same anonymous-auth model as favorites / interactions / match_feedback:
-- device_id is populated from auth.uid()::text and every policy compares against
-- it (see 006_anonymous_auth_rls.sql). Policies use the (select auth.uid()::text)
-- wrap for per-row performance (the 014 hardening pattern).
--
-- Privacy: a user may only INSERT their OWN rows. analytics_events has NO read
-- policy on purpose — the client cannot read events back; aggregation is
-- operator-only via the service-role key (which bypasses RLS). waitlist also
-- allows SELECT-own so a user can see their own pending request. Both paths are
-- disclosed in the privacy policy.

CREATE TABLE IF NOT EXISTS analytics_events (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  event text NOT NULL,
  props jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS analytics_events_event_created_idx
  ON analytics_events (event, created_at DESC);

ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;

-- Insert-own only. No SELECT/UPDATE/DELETE policy → with RLS enabled the anon /
-- authenticated client cannot read or mutate events; the operator aggregates
-- with the service-role key.
DROP POLICY IF EXISTS "analytics_events_insert_own" ON analytics_events;
CREATE POLICY "analytics_events_insert_own" ON analytics_events
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

CREATE TABLE IF NOT EXISTS waitlist (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  email text,
  intent text NOT NULL DEFAULT 'apply_for_me',
  props jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS waitlist_created_idx ON waitlist (created_at DESC);

ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "waitlist_insert_own" ON waitlist;
CREATE POLICY "waitlist_insert_own" ON waitlist
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "waitlist_select_own" ON waitlist;
CREATE POLICY "waitlist_select_own" ON waitlist
  FOR SELECT USING (device_id = (select auth.uid()::text));
