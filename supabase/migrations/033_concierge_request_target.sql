-- 033_concierge_request_target.sql
-- Give the "apply for me" request the one thing it was always missing: WHICH
-- opportunity.
--
-- The concierge funnel shipped in 015 as an untargeted signal — a student
-- clicked an intent button on /account, left an email, and the row said only
-- that somebody, somewhere, wanted help. Nobody could act on that, because the
-- work the student is asking for is per-professor: read this lab, tailor this
-- résumé, send this email. The buying moment happens in front of one card, and
-- until now the request lost the card on the way to the database.
--
-- This is deliberately NOT the orders table. 026 closed that path because the
-- commercial terms do not exist yet, and nothing here reopens it: no price, no
-- amount, no channel, no status a payment could advance. A row means "a
-- student asked us to do this for them", which is a thing we can honour by
-- hand today and meter later.
--
-- The column is nullable because the untargeted rows 015 already collected are
-- real: they said someone was interested before we could ask about what.
-- Backfilling them with a guess would turn an honest blank into a fabricated
-- target.

ALTER TABLE waitlist ADD COLUMN IF NOT EXISTS opportunity_id text;

-- One standing request per student per target. Double-clicking the button, or
-- coming back a week later to ask again, must not turn one job into three in
-- the operator's queue. Partial, so the 015-era untargeted rows — which have
-- no target to be duplicates of — are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS waitlist_one_request_per_target
  ON waitlist (device_id, opportunity_id)
  WHERE opportunity_id IS NOT NULL;

-- The operator's read is "what has been requested, newest first"; the student's
-- is "which of these have I already asked for", which the RLS SELECT policy
-- from 015 already scopes to their own device.
CREATE INDEX IF NOT EXISTS waitlist_target_created_idx
  ON waitlist (opportunity_id, created_at DESC)
  WHERE opportunity_id IS NOT NULL;
