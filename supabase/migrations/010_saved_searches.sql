-- Server-persisted searches for cross-device sync and (Phase 2+) cron-driven
-- "new match" digests. Per-device-scoped via the same auth.uid()::text
-- pattern as favorites / interactions / profile_versions
-- (see 006_anonymous_auth_rls.sql for the anonymous-auth model).
--
-- Separate from the client-side `ofe_filter_presets` localStorage path
-- (Round 13): presets are quick-recall filter combos on one device, saved
-- searches are opt-in surveillance subscriptions that will eventually
-- trigger email digests. Both can coexist; the UI to surface saved
-- searches is deferred to Round 16 once the cron-side data exists.
--
-- filters_json is jsonb so future filter dimensions can be added without
-- a schema migration. The `query`, `sort_by`, `tab` columns are
-- normalised separately because cron jobs (Phase 2) will need to query
-- against them directly for diff'ing prior result sets.

CREATE TABLE IF NOT EXISTS saved_searches (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  device_id text NOT NULL,
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  query text NOT NULL DEFAULT '',
  filters_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  sort_by text NOT NULL DEFAULT 'score',
  tab text NOT NULL DEFAULT 'all',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Listing query is always `WHERE device_id = ? ORDER BY updated_at DESC`,
-- so a composite index covers both the filter and the sort.
CREATE INDEX IF NOT EXISTS idx_saved_searches_lookup
  ON saved_searches (device_id, updated_at DESC);

ALTER TABLE saved_searches ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "saved_searches_select_own" ON saved_searches;
DROP POLICY IF EXISTS "saved_searches_insert_own" ON saved_searches;
DROP POLICY IF EXISTS "saved_searches_update_own" ON saved_searches;
DROP POLICY IF EXISTS "saved_searches_delete_own" ON saved_searches;

CREATE POLICY "saved_searches_select_own" ON saved_searches
  FOR SELECT USING (device_id = auth.uid()::text);

CREATE POLICY "saved_searches_insert_own" ON saved_searches
  FOR INSERT WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "saved_searches_update_own" ON saved_searches
  FOR UPDATE USING (device_id = auth.uid()::text)
  WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "saved_searches_delete_own" ON saved_searches
  FOR DELETE USING (device_id = auth.uid()::text);
