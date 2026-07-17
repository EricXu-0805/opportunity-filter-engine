-- 020_usage_events.sql
-- Metering ledger for future usage-based billing (résumé renovation is "first
-- free, then per-optimization"; cold-email agent send is paid). Inert until the
-- paid tiers actually go live post-August pricing — the backend's metering
-- adapter is gated OFF by default (OFE_METERING_ENABLED unset). This table just
-- has to exist so enabling is a one-flag flip, not a migration.
--
-- Write model mirrors 019_orders' status transitions: a client must NOT be able
-- to forge its own usage ledger (that would let it under-report to dodge quota),
-- so there is deliberately NO client INSERT policy. Rows are written only by the
-- service-role backend (backend/lib/metering.py), which bypasses RLS. The
-- client may READ its own usage so the UI can show remaining free quota.

CREATE TABLE IF NOT EXISTS public.usage_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text NOT NULL,
  feature text NOT NULL,
  quantity int NOT NULL DEFAULT 1 CHECK (quantity > 0),
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.usage_events ENABLE ROW LEVEL SECURITY;

-- Read-own only. No INSERT/UPDATE/DELETE policy: clients can never write here
-- (service-role backend bypasses RLS to record usage). Same "no user write"
-- shape as orders' post-pending transitions.
DROP POLICY IF EXISTS "usage_events_select_own" ON public.usage_events;
CREATE POLICY "usage_events_select_own" ON public.usage_events
  FOR SELECT USING (device_id = (select auth.uid()::text));

CREATE INDEX IF NOT EXISTS idx_usage_events_device_created
  ON public.usage_events (device_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_feature
  ON public.usage_events (device_id, feature);
