-- Test-only stubs so the production migrations + 017 can be loaded into a
-- vanilla Postgres cluster (no Supabase). NOT part of any deployed migration.
--
--   * auth.uid()/auth.jwt(): read the "current caller" from session GUCs the
--     test sets (test.uid / test.jwt), mirroring Supabase's JWT-claim funcs.
--   * storage.*: minimal shapes so 008's bucket insert + object policies +
--     the redeem function's attachment COUNT parse and run.
--   * roles anon/authenticated/service_role: referenced by GRANT/REVOKE in
--     014 + 017; absent from a plain cluster.
--   * profiles/favorites: dashboard-created in prod (no migration file), so
--     the test must create them before 006 alters them.

-- Supabase roles referenced by GRANT/REVOKE statements.
DO $$ BEGIN CREATE ROLE anon NOLOGIN;           EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN;  EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role NOLOGIN;   EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- auth schema + claim-reading functions.
CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('test.uid', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION auth.jwt()
RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT coalesce(nullif(current_setting('test.jwt', true), '')::jsonb, '{}'::jsonb)
$$;

-- storage schema + minimal object model.
CREATE SCHEMA IF NOT EXISTS storage;

CREATE TABLE IF NOT EXISTS storage.buckets (
  id                 text PRIMARY KEY,
  name               text,
  public             boolean,
  file_size_limit    bigint,
  allowed_mime_types text[]
);

CREATE TABLE IF NOT EXISTS storage.objects (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket_id  text,
  name       text,
  owner      uuid,
  created_at timestamptz DEFAULT now()
);

-- Real Supabase storage.foldername returns the path segments EXCLUDING the
-- filename; for our [1] lookup only the first segment matters, but mirror
-- the real shape.
CREATE OR REPLACE FUNCTION storage.foldername(name text)
RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
  SELECT (string_to_array(name, '/'))[1 : greatest(array_length(string_to_array(name, '/'), 1) - 1, 1)]
$$;

-- profiles + favorites: dashboard-created in prod (no migration), created here
-- to match the columns the frontend reads/writes (supabase.ts).
CREATE TABLE IF NOT EXISTS profiles (
  id           text PRIMARY KEY,
  profile_data jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at   timestamptz DEFAULT now(),
  updated_at   timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS favorites (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id      text NOT NULL,
  opportunity_id text NOT NULL,
  created_at     timestamptz DEFAULT now(),
  UNIQUE (device_id, opportunity_id)
);
