-- Phase 2b of Tier 3 #6: cron-driven "new match" tracking for saved searches.
--
-- ALTER (vs CREATE TABLE) chosen on purpose: the cron only ever needs the
-- LATEST run state per saved search, not full history. Storing the result
-- snapshot inline on saved_searches keeps reads to a single SELECT in the
-- Round 18 UI ("show me my saved searches with new-match badges").
--
-- Trade-off accepted: no per-run audit trail (can't show "this search
-- gained 3 matches on Tue, lost 1 on Wed"). If that ever matters, add a
-- saved_search_runs table later; this column set is the minimum needed
-- for "X new since last run" UX.
--
-- last_result_ids holds the full match list at the most recent cron run.
-- new_match_ids = (current run) - (prior run's last_result_ids) — i.e.
-- opportunities that newly started matching the filter. The cron route
-- (backend/routes/saved_searches.py) reads the prior last_result_ids,
-- computes the diff, writes both columns back atomically per row.
--
-- No RLS change needed: the 4 policies from 010_saved_searches.sql
-- (select/insert/update/delete _own) already cover SELECT on the new
-- columns. The cron writes through SERVICE_ROLE_KEY which bypasses RLS.

ALTER TABLE saved_searches
  ADD COLUMN IF NOT EXISTS last_run_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_result_ids text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS new_match_ids text[] NOT NULL DEFAULT '{}';

-- Cron iterates "saved searches that haven't run in N hours" — index the
-- nullable last_run_at so the LEAST-recently-run rows can be picked up
-- first. NULLS FIRST ensures rows that have never been processed (just
-- inserted by /results) get prioritised in the next cron tick.
CREATE INDEX IF NOT EXISTS idx_saved_searches_last_run
  ON saved_searches (last_run_at NULLS FIRST);
