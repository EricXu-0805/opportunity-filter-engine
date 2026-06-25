-- 016_feedback.sql
-- In-app feedback: free-text comments / bug reports / suggestions a user
-- sends through the feedback widget. One row per submission, scoped to the
-- submitter's anonymous identity (device_id = auth.uid()::text) — the same
-- per-user RLS pattern as 015_analytics_waitlist.sql. INSERT-ONLY: a client
-- may write its own feedback but cannot read any feedback back (the operator
-- reads it with the service-role key). `email` is optional, set only when the
-- user wants a reply. Disclosed in the privacy policy (§2.7).

CREATE TABLE IF NOT EXISTS feedback (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  message text NOT NULL,
  email text,
  props jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

-- Insert-own only. No SELECT/UPDATE/DELETE policy → clients can neither read
-- nor mutate feedback rows; aggregation happens server-side via service role.
DROP POLICY IF EXISTS "feedback_insert_own" ON feedback;
CREATE POLICY "feedback_insert_own" ON feedback
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));
