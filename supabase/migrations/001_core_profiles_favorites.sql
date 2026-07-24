-- Canonical core identity-owned tables.
--
-- These two tables predated the migration directory and were originally
-- created in the Supabase Dashboard. Keeping that hidden dependency made a
-- fresh project, disaster-recovery restore, or preview branch fail as soon as
-- migration 004 attempted to create policies on them. Define the exact shape
-- here so a from-scratch replay works.
--
-- Deliberately NO GRANT/REVOKE ceremony here: later migrations (006 onward)
-- own the policy/ACL end-state. On the live project these tables already
-- exist with 471 users behind them, so this file must be a pure no-op there —
-- an ACL statement that ran and then aborted mid-chain would lock real users
-- out. Everything below is idempotent and matches the deployed shape.

CREATE TABLE IF NOT EXISTS public.profiles (
  id text PRIMARY KEY,
  profile_data jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.favorites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text NOT NULL,
  opportunity_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT favorites_device_opportunity_key UNIQUE (device_id, opportunity_id)
);

CREATE INDEX IF NOT EXISTS favorites_device_created_idx
  ON public.favorites (device_id, created_at DESC);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.favorites ENABLE ROW LEVEL SECURITY;
