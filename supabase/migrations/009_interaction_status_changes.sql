-- Append-only log of every interaction_type transition on the
-- `interactions` table, so the opportunity detail page can render a
-- real status timeline ("applied -> replied -> interviewing") instead
-- of just the latest status.
--
-- Written by an AFTER INSERT/UPDATE trigger on `interactions` so any
-- code path that flips interaction_type (frontend trackInteraction,
-- future backend automation, manual psql) is captured automatically.
-- The trigger runs SECURITY DEFINER so it bypasses the row owner's
-- RLS on insert — necessary because the logging happens inside the
-- same statement that mutates `interactions`.
--
-- Pre-existing interactions rows do NOT get backfilled. A row's
-- history starts the first time it's updated after this migration
-- lands; consumers should fall back to interactions.updated_at when
-- the log is empty.

CREATE TABLE IF NOT EXISTS interaction_status_changes (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  opportunity_id text NOT NULL,
  from_status text,
  to_status text NOT NULL,
  changed_at timestamptz DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_isc_lookup
  ON interaction_status_changes (device_id, opportunity_id, changed_at DESC);

ALTER TABLE interaction_status_changes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "isc_select_own" ON interaction_status_changes;

CREATE POLICY "isc_select_own" ON interaction_status_changes
  FOR SELECT USING (device_id = auth.uid()::text);


CREATE OR REPLACE FUNCTION log_interaction_status_change()
RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO interaction_status_changes
      (device_id, opportunity_id, from_status, to_status)
    VALUES
      (NEW.device_id, NEW.opportunity_id, NULL, NEW.interaction_type);
  ELSIF TG_OP = 'UPDATE'
        AND OLD.interaction_type IS DISTINCT FROM NEW.interaction_type THEN
    INSERT INTO interaction_status_changes
      (device_id, opportunity_id, from_status, to_status)
    VALUES
      (NEW.device_id, NEW.opportunity_id, OLD.interaction_type, NEW.interaction_type);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS interactions_log_status_change ON interactions;

CREATE TRIGGER interactions_log_status_change
  AFTER INSERT OR UPDATE OF interaction_type ON interactions
  FOR EACH ROW
  EXECUTE FUNCTION log_interaction_status_change();
