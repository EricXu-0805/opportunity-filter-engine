CREATE TABLE IF NOT EXISTS profile_versions (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  profile_data jsonb NOT NULL,
  created_at timestamptz DEFAULT now()
);

ALTER TABLE profile_versions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profile_versions_allow_all" ON profile_versions
  FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX idx_profile_versions_device ON profile_versions(device_id);
CREATE INDEX idx_profile_versions_created ON profile_versions(created_at DESC);
