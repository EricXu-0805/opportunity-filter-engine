-- Opt-in weekly email digest for saved searches. Columns live inline on
-- saved_searches (same trade-off as 011's run state): the digest cron only
-- ever needs the latest opt-in/email/sent-at per search, and the favorites
-- UI reads everything in the single existing SELECT.
--
-- Opt-in model: digest_opt_in defaults false and is only ever set true by
-- an explicit user action that also supplies digest_email. The unsubscribe
-- endpoint (HMAC-token GET, no auth) flips digest_opt_in back to false and
-- stamps digest_unsubscribed_at; keeping the timestamp (instead of nulling
-- the email) preserves an audit trail of "user opted out" so a re-opt-in
-- is always another explicit action.
--
-- No RLS change needed: the 4 _own policies from 010 already cover these
-- columns for the owner, and the digest cron + unsubscribe endpoint write
-- through SERVICE_ROLE_KEY which bypasses RLS (same model as 011).

ALTER TABLE saved_searches
  ADD COLUMN IF NOT EXISTS digest_email text,
  ADD COLUMN IF NOT EXISTS digest_opt_in boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS digest_unsubscribed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_digest_sent_at timestamptz;

-- The weekly cron lists only opted-in rows; expected to be a small
-- minority of saved searches, so a partial index keeps it cheap.
CREATE INDEX IF NOT EXISTS idx_saved_searches_digest_opt_in
  ON saved_searches (last_digest_sent_at NULLS FIRST)
  WHERE digest_opt_in;
