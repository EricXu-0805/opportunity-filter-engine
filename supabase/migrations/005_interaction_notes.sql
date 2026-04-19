ALTER TABLE interactions
  ADD COLUMN IF NOT EXISTS notes text,
  ADD COLUMN IF NOT EXISTS remind_at date,
  ADD COLUMN IF NOT EXISTS last_contacted_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_interactions_remind_at
  ON interactions (device_id, remind_at)
  WHERE remind_at IS NOT NULL;

ALTER TABLE interactions
  DROP CONSTRAINT IF EXISTS interactions_notes_length;
ALTER TABLE interactions
  ADD CONSTRAINT interactions_notes_length CHECK (notes IS NULL OR length(notes) <= 2000);
