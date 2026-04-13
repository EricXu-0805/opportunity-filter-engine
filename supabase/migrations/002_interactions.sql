CREATE TABLE IF NOT EXISTS interactions (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  opportunity_id text NOT NULL,
  interaction_type text NOT NULL CHECK (interaction_type IN ('applied', 'replied', 'interviewing', 'rejected')),
  updated_at timestamptz DEFAULT now(),
  UNIQUE(device_id, opportunity_id)
);

ALTER TABLE interactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "interactions_allow_all" ON interactions
  FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX idx_interactions_device ON interactions(device_id);
