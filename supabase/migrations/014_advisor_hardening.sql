-- Hardening pass driven by the live project's Supabase advisors
-- (security + performance lints, verified 2026-06-12). Two classes of
-- finding, zero behavior change:
--
-- 1. public.log_interaction_status_change() (009_interaction_status_changes
--    .sql) is a SECURITY DEFINER trigger function with (a) a mutable
--    search_path [function_search_path_mutable] and (b) EXECUTE granted to
--    anon + authenticated via Postgres's default GRANT TO PUBLIC on new
--    functions, which exposed it at
--    /rest/v1/rpc/log_interaction_status_change. A trigger function should
--    never be directly callable by API roles.
--
-- 2. auth_rls_initplan: every RLS policy in this project compares a column
--    against a bare auth.uid()::text, which Postgres re-evaluates per row.
--    Wrapping as (select auth.uid()::text) makes the planner evaluate it
--    once per statement as an InitPlan — identical semantics, much cheaper
--    on multi-row scans.
--    https://supabase.com/docs/guides/database/postgres/row-level-security#call-functions-with-select
--
-- Deliberately NOT addressed here: auth_allow_anonymous_sign_ins warnings.
-- Anonymous-first auth IS this app's architecture (each device is an
-- anonymous user — see 006_anonymous_auth_rls.sql); every policy below pins
-- rows to that user's own auth.uid(), which is the mitigation the lint
-- asks you to confirm.

-- ---------------------------------------------------------------------------
-- 1a. Pin the trigger function's search_path. SECURITY DEFINER with a
-- mutable search_path is the classic escalation shape: anything that can
-- influence search_path at call time could shadow
-- `interaction_status_changes` with its own object and have the function
-- owner write into it instead. pg_temp goes last so temp objects can never
-- shadow public ones.
ALTER FUNCTION public.log_interaction_status_change()
  SET search_path = public, pg_temp;

-- 1b. Drop the direct-call surface. This does NOT break the trigger:
-- Postgres checks EXECUTE on a trigger function only at CREATE TRIGGER time
-- (against the migration role that ran 009), never against the end user
-- when the trigger fires — `interactions_log_status_change` keeps firing on
-- anon users' interactions writes, still as SECURITY DEFINER so the insert
-- bypasses interaction_status_changes' RLS as designed. Only the
-- PostgREST /rpc endpoint goes away.
REVOKE EXECUTE ON FUNCTION public.log_interaction_status_change()
  FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. Recreate every RLS policy with the InitPlan-friendly
-- (select auth.uid()::text) wrap. Names, commands, and row predicates are
-- byte-identical to the current definitions (006, 007, 008, 009, 010, 012)
-- apart from the wrap. DROP IF EXISTS + CREATE keeps this re-runnable.

-- profiles (006) — keyed on id, not device_id: the profile row ID is the
-- anonymous user's uid itself.
DROP POLICY IF EXISTS "profiles_select_own" ON profiles;
DROP POLICY IF EXISTS "profiles_insert_own" ON profiles;
DROP POLICY IF EXISTS "profiles_update_own" ON profiles;
DROP POLICY IF EXISTS "profiles_delete_own" ON profiles;

CREATE POLICY "profiles_select_own" ON profiles
  FOR SELECT USING (id = (select auth.uid()::text));

CREATE POLICY "profiles_insert_own" ON profiles
  FOR INSERT WITH CHECK (id = (select auth.uid()::text));

CREATE POLICY "profiles_update_own" ON profiles
  FOR UPDATE USING (id = (select auth.uid()::text))
  WITH CHECK (id = (select auth.uid()::text));

CREATE POLICY "profiles_delete_own" ON profiles
  FOR DELETE USING (id = (select auth.uid()::text));

-- profile_versions (006) — append-only history, so no update/delete.
DROP POLICY IF EXISTS "profile_versions_select_own" ON profile_versions;
DROP POLICY IF EXISTS "profile_versions_insert_own" ON profile_versions;

CREATE POLICY "profile_versions_select_own" ON profile_versions
  FOR SELECT USING (device_id = (select auth.uid()::text));

CREATE POLICY "profile_versions_insert_own" ON profile_versions
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

-- favorites (006) — toggle semantics: insert/delete only, no update.
DROP POLICY IF EXISTS "favorites_select_own" ON favorites;
DROP POLICY IF EXISTS "favorites_insert_own" ON favorites;
DROP POLICY IF EXISTS "favorites_delete_own" ON favorites;

CREATE POLICY "favorites_select_own" ON favorites
  FOR SELECT USING (device_id = (select auth.uid()::text));

CREATE POLICY "favorites_insert_own" ON favorites
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "favorites_delete_own" ON favorites
  FOR DELETE USING (device_id = (select auth.uid()::text));

-- interactions (006)
DROP POLICY IF EXISTS "interactions_select_own" ON interactions;
DROP POLICY IF EXISTS "interactions_insert_own" ON interactions;
DROP POLICY IF EXISTS "interactions_update_own" ON interactions;
DROP POLICY IF EXISTS "interactions_delete_own" ON interactions;

CREATE POLICY "interactions_select_own" ON interactions
  FOR SELECT USING (device_id = (select auth.uid()::text));

CREATE POLICY "interactions_insert_own" ON interactions
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "interactions_update_own" ON interactions
  FOR UPDATE USING (device_id = (select auth.uid()::text))
  WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "interactions_delete_own" ON interactions
  FOR DELETE USING (device_id = (select auth.uid()::text));

-- push_subscriptions (007)
DROP POLICY IF EXISTS "push_select_own" ON push_subscriptions;
DROP POLICY IF EXISTS "push_insert_own" ON push_subscriptions;
DROP POLICY IF EXISTS "push_update_own" ON push_subscriptions;
DROP POLICY IF EXISTS "push_delete_own" ON push_subscriptions;

CREATE POLICY "push_select_own" ON push_subscriptions
  FOR SELECT USING (device_id = (select auth.uid()::text));

CREATE POLICY "push_insert_own" ON push_subscriptions
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "push_update_own" ON push_subscriptions
  FOR UPDATE USING (device_id = (select auth.uid()::text))
  WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "push_delete_own" ON push_subscriptions
  FOR DELETE USING (device_id = (select auth.uid()::text));

-- interaction_status_changes (009) — select-only by design; writes happen
-- exclusively through the SECURITY DEFINER trigger hardened above.
DROP POLICY IF EXISTS "isc_select_own" ON interaction_status_changes;

CREATE POLICY "isc_select_own" ON interaction_status_changes
  FOR SELECT USING (device_id = (select auth.uid()::text));

-- saved_searches (010)
DROP POLICY IF EXISTS "saved_searches_select_own" ON saved_searches;
DROP POLICY IF EXISTS "saved_searches_insert_own" ON saved_searches;
DROP POLICY IF EXISTS "saved_searches_update_own" ON saved_searches;
DROP POLICY IF EXISTS "saved_searches_delete_own" ON saved_searches;

CREATE POLICY "saved_searches_select_own" ON saved_searches
  FOR SELECT USING (device_id = (select auth.uid()::text));

CREATE POLICY "saved_searches_insert_own" ON saved_searches
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "saved_searches_update_own" ON saved_searches
  FOR UPDATE USING (device_id = (select auth.uid()::text))
  WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "saved_searches_delete_own" ON saved_searches
  FOR DELETE USING (device_id = (select auth.uid()::text));

-- match_feedback (012)
DROP POLICY IF EXISTS "match_feedback_select_own" ON match_feedback;
DROP POLICY IF EXISTS "match_feedback_insert_own" ON match_feedback;
DROP POLICY IF EXISTS "match_feedback_update_own" ON match_feedback;
DROP POLICY IF EXISTS "match_feedback_delete_own" ON match_feedback;

CREATE POLICY "match_feedback_select_own" ON match_feedback
  FOR SELECT USING (device_id = (select auth.uid()::text));

CREATE POLICY "match_feedback_insert_own" ON match_feedback
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "match_feedback_update_own" ON match_feedback
  FOR UPDATE USING (device_id = (select auth.uid()::text))
  WITH CHECK (device_id = (select auth.uid()::text));

CREATE POLICY "match_feedback_delete_own" ON match_feedback
  FOR DELETE USING (device_id = (select auth.uid()::text));

-- storage.objects tracker-attachments policies (008) — same bare
-- auth.uid()::text pattern, same per-row re-evaluation cost, so they get
-- the same wrap. RLS keys off the first path segment:
--   tracker-attachments/{auth.uid()::text}/{opportunity_id}/{filename}
DROP POLICY IF EXISTS "tracker_attachments_select_own" ON storage.objects;
DROP POLICY IF EXISTS "tracker_attachments_insert_own" ON storage.objects;
DROP POLICY IF EXISTS "tracker_attachments_update_own" ON storage.objects;
DROP POLICY IF EXISTS "tracker_attachments_delete_own" ON storage.objects;

CREATE POLICY "tracker_attachments_select_own"
  ON storage.objects FOR SELECT
  USING (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = (select auth.uid()::text)
  );

CREATE POLICY "tracker_attachments_insert_own"
  ON storage.objects FOR INSERT
  WITH CHECK (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = (select auth.uid()::text)
  );

CREATE POLICY "tracker_attachments_update_own"
  ON storage.objects FOR UPDATE
  USING (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = (select auth.uid()::text)
  )
  WITH CHECK (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = (select auth.uid()::text)
  );

CREATE POLICY "tracker_attachments_delete_own"
  ON storage.objects FOR DELETE
  USING (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = (select auth.uid()::text)
  );
