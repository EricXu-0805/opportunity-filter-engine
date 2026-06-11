-- Phase 9.6 feedback loop (minimal): per-user thumbs up/down on whether a
-- match recommendation was accurate. Same anonymous-auth model as favorites
-- / interactions / saved_searches: device_id is populated from
-- auth.uid()::text and every policy compares against it
-- (see 006_anonymous_auth_rls.sql).
--
-- bucket + final_score are denormalised at vote time so feedback stays
-- interpretable later — the matcher's weights will change, and "user said
-- 'down' on an 85% high_priority match" is the signal we want to keep even
-- after the same opportunity re-scores differently.
--
-- UNIQUE (device_id, opportunity_id) gives one verdict per user per
-- opportunity; the client upserts on re-vote and deletes to clear.

CREATE TABLE IF NOT EXISTS match_feedback (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  opportunity_id text NOT NULL,
  verdict text NOT NULL CHECK (verdict IN ('up', 'down')),
  bucket text,
  final_score numeric,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (device_id, opportunity_id)
);

ALTER TABLE match_feedback ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "match_feedback_select_own" ON match_feedback;
DROP POLICY IF EXISTS "match_feedback_insert_own" ON match_feedback;
DROP POLICY IF EXISTS "match_feedback_update_own" ON match_feedback;
DROP POLICY IF EXISTS "match_feedback_delete_own" ON match_feedback;

CREATE POLICY "match_feedback_select_own" ON match_feedback
  FOR SELECT USING (device_id = auth.uid()::text);

CREATE POLICY "match_feedback_insert_own" ON match_feedback
  FOR INSERT WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "match_feedback_update_own" ON match_feedback
  FOR UPDATE USING (device_id = auth.uid()::text)
  WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "match_feedback_delete_own" ON match_feedback
  FOR DELETE USING (device_id = auth.uid()::text);
