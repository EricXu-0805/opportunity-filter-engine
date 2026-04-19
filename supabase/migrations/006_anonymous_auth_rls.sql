-- Supersedes 004_rls_device_scoping.sql.
--
-- Switches RLS from a custom `request.jwt.claims -> device_id` scheme (where
-- the client signed its own JWT with NEXT_PUBLIC_SUPABASE_JWT_SECRET) to
-- Supabase's built-in anonymous auth — each device becomes an anonymous user
-- with a real auth.uid() UUID. We keep the existing text `device_id` column
-- and now populate it from auth.uid()::text for backward compatibility and
-- zero data migration: policies compare device_id to auth.uid()::text.
--
-- Existing device-id-only rows (created before this migration) become
-- unreadable by any auth.uid() and are effectively orphaned until a user
-- re-onboards under their new anonymous user. Acceptable because this app
-- has no production users yet.

DROP FUNCTION IF EXISTS public.current_device_id();

ALTER TABLE IF EXISTS profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS profile_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS interactions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "profiles_open" ON profiles;
DROP POLICY IF EXISTS "profiles_allow_all" ON profiles;
DROP POLICY IF EXISTS "profiles_select_own" ON profiles;
DROP POLICY IF EXISTS "profiles_insert_own" ON profiles;
DROP POLICY IF EXISTS "profiles_update_own" ON profiles;
DROP POLICY IF EXISTS "profiles_delete_own" ON profiles;

CREATE POLICY "profiles_select_own" ON profiles
  FOR SELECT USING (id = auth.uid()::text);

CREATE POLICY "profiles_insert_own" ON profiles
  FOR INSERT WITH CHECK (id = auth.uid()::text);

CREATE POLICY "profiles_update_own" ON profiles
  FOR UPDATE USING (id = auth.uid()::text)
  WITH CHECK (id = auth.uid()::text);

CREATE POLICY "profiles_delete_own" ON profiles
  FOR DELETE USING (id = auth.uid()::text);

DROP POLICY IF EXISTS "profile_versions_allow_all" ON profile_versions;
DROP POLICY IF EXISTS "profile_versions_select_own" ON profile_versions;
DROP POLICY IF EXISTS "profile_versions_insert_own" ON profile_versions;

CREATE POLICY "profile_versions_select_own" ON profile_versions
  FOR SELECT USING (device_id = auth.uid()::text);

CREATE POLICY "profile_versions_insert_own" ON profile_versions
  FOR INSERT WITH CHECK (device_id = auth.uid()::text);

ALTER TABLE IF EXISTS favorites ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "favorites_open" ON favorites;
DROP POLICY IF EXISTS "favorites_allow_all" ON favorites;
DROP POLICY IF EXISTS "favorites_select_own" ON favorites;
DROP POLICY IF EXISTS "favorites_insert_own" ON favorites;
DROP POLICY IF EXISTS "favorites_delete_own" ON favorites;

CREATE POLICY "favorites_select_own" ON favorites
  FOR SELECT USING (device_id = auth.uid()::text);

CREATE POLICY "favorites_insert_own" ON favorites
  FOR INSERT WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "favorites_delete_own" ON favorites
  FOR DELETE USING (device_id = auth.uid()::text);

DROP POLICY IF EXISTS "interactions_allow_all" ON interactions;
DROP POLICY IF EXISTS "interactions_select_own" ON interactions;
DROP POLICY IF EXISTS "interactions_insert_own" ON interactions;
DROP POLICY IF EXISTS "interactions_update_own" ON interactions;
DROP POLICY IF EXISTS "interactions_delete_own" ON interactions;

CREATE POLICY "interactions_select_own" ON interactions
  FOR SELECT USING (device_id = auth.uid()::text);

CREATE POLICY "interactions_insert_own" ON interactions
  FOR INSERT WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "interactions_update_own" ON interactions
  FOR UPDATE USING (device_id = auth.uid()::text)
  WITH CHECK (device_id = auth.uid()::text);

CREATE POLICY "interactions_delete_own" ON interactions
  FOR DELETE USING (device_id = auth.uid()::text);
