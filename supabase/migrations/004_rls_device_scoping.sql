-- Harden row-level security so anon clients can only touch rows matching
-- the device_id they present in the `x-device-id` request header.
--
-- BEFORE: all tables had `USING (true) WITH CHECK (true)` — effectively no RLS.
--   Any anon-key holder could enumerate every user's profile/favorites/
--   interactions.
-- AFTER: each policy compares row.device_id against a device_id plucked from
--   the request's JWT claims (populated by the frontend via setAuth()).
--
-- The identity model is still "bearer token" (device_id in localStorage) —
-- this migration upgrades it from "no security" to "matching security"
-- and blocks enumeration. Full account-backed auth is a separate migration.

-- =====================================================================
-- Helper: extract device_id from request context
-- =====================================================================
--
-- We set it via supabase-js `setSession` injecting a JWT with a custom
-- `device_id` claim, or via PostgREST's `request.jwt.claims` GUC.
-- The function returns '' when no claim is set so RLS falls through to
-- DENY (no row matches '').

CREATE OR REPLACE FUNCTION public.current_device_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'device_id',
    ''
  );
$$;

-- =====================================================================
-- profiles: one row per device
-- =====================================================================
--
-- Assumes the table was created via dashboard with columns:
--   id text primary key, profile_data jsonb, updated_at timestamptz
-- where `id` is used as the device_id.

ALTER TABLE IF EXISTS profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "profiles_allow_all" ON profiles;
DROP POLICY IF EXISTS "profiles_select_own" ON profiles;
DROP POLICY IF EXISTS "profiles_insert_own" ON profiles;
DROP POLICY IF EXISTS "profiles_update_own" ON profiles;
DROP POLICY IF EXISTS "profiles_delete_own" ON profiles;

CREATE POLICY "profiles_select_own" ON profiles
  FOR SELECT
  USING (id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "profiles_insert_own" ON profiles
  FOR INSERT
  WITH CHECK (id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "profiles_update_own" ON profiles
  FOR UPDATE
  USING (id = public.current_device_id() AND public.current_device_id() <> '')
  WITH CHECK (id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "profiles_delete_own" ON profiles
  FOR DELETE
  USING (id = public.current_device_id() AND public.current_device_id() <> '');

-- =====================================================================
-- profile_versions: history log keyed by device_id
-- =====================================================================

DROP POLICY IF EXISTS "profile_versions_allow_all" ON profile_versions;
DROP POLICY IF EXISTS "profile_versions_select_own" ON profile_versions;
DROP POLICY IF EXISTS "profile_versions_insert_own" ON profile_versions;

CREATE POLICY "profile_versions_select_own" ON profile_versions
  FOR SELECT
  USING (device_id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "profile_versions_insert_own" ON profile_versions
  FOR INSERT
  WITH CHECK (device_id = public.current_device_id() AND public.current_device_id() <> '');

-- (no update/delete — versions are append-only history)

-- =====================================================================
-- favorites
-- =====================================================================

ALTER TABLE IF EXISTS favorites ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "favorites_allow_all" ON favorites;
DROP POLICY IF EXISTS "favorites_select_own" ON favorites;
DROP POLICY IF EXISTS "favorites_insert_own" ON favorites;
DROP POLICY IF EXISTS "favorites_delete_own" ON favorites;

CREATE POLICY "favorites_select_own" ON favorites
  FOR SELECT
  USING (device_id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "favorites_insert_own" ON favorites
  FOR INSERT
  WITH CHECK (device_id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "favorites_delete_own" ON favorites
  FOR DELETE
  USING (device_id = public.current_device_id() AND public.current_device_id() <> '');

-- =====================================================================
-- interactions
-- =====================================================================

DROP POLICY IF EXISTS "interactions_allow_all" ON interactions;
DROP POLICY IF EXISTS "interactions_select_own" ON interactions;
DROP POLICY IF EXISTS "interactions_insert_own" ON interactions;
DROP POLICY IF EXISTS "interactions_update_own" ON interactions;
DROP POLICY IF EXISTS "interactions_delete_own" ON interactions;

CREATE POLICY "interactions_select_own" ON interactions
  FOR SELECT
  USING (device_id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "interactions_insert_own" ON interactions
  FOR INSERT
  WITH CHECK (device_id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "interactions_update_own" ON interactions
  FOR UPDATE
  USING (device_id = public.current_device_id() AND public.current_device_id() <> '')
  WITH CHECK (device_id = public.current_device_id() AND public.current_device_id() <> '');

CREATE POLICY "interactions_delete_own" ON interactions
  FOR DELETE
  USING (device_id = public.current_device_id() AND public.current_device_id() <> '');

-- =====================================================================
-- interactions: allow 'dismissed' status (added in recent frontend work)
-- =====================================================================

ALTER TABLE interactions DROP CONSTRAINT IF EXISTS interactions_interaction_type_check;
ALTER TABLE interactions ADD CONSTRAINT interactions_interaction_type_check
  CHECK (interaction_type IN ('applied', 'replied', 'interviewing', 'rejected', 'dismissed'));
