CREATE TABLE IF NOT EXISTS push_subscriptions (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  endpoint text NOT NULL,
  p256dh text NOT NULL,
  auth text NOT NULL,
  created_at timestamptz DEFAULT now(),
  last_delivered_at timestamptz,
  last_error text,
  UNIQUE(device_id, endpoint)
);

CREATE INDEX IF NOT EXISTS idx_push_subscriptions_device
  ON push_subscriptions(device_id);

ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "push_select_own" ON push_subscriptions;
DROP POLICY IF EXISTS "push_insert_own" ON push_subscriptions;
DROP POLICY IF EXISTS "push_update_own" ON push_subscriptions;
DROP POLICY IF EXISTS "push_delete_own" ON push_subscriptions;

CREATE POLICY "push_select_own" ON push_subscriptions
  FOR SELECT USING (device_id = auth.uid()::text);

CREATE POLICY "push_insert_own" ON push_subscriptions
  FOR INSERT WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "push_update_own" ON push_subscriptions
  FOR UPDATE USING (device_id = auth.uid()::text)
  WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "push_delete_own" ON push_subscriptions
  FOR DELETE USING (device_id = auth.uid()::text);
