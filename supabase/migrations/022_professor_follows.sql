-- 022_professor_follows.sql
-- Professor tracking (W8): follow a professor from an opportunity page and
-- read verified update events for the professors you follow.
--
-- Two tables, both device-scoped under the anonymous-auth RLS pattern (006):
--
--   professor_follows      — one row per (device, professor). professor_id is
--                            the record-scoped tracking id the backend derives
--                            from a faculty corpus record (prof:v1:<school>:<hash>);
--                            professor_name/school are display denormalizations
--                            captured at follow time so the dashboard can render
--                            a follow even when the corpus record has rotated.
--   professor_update_reads — per-professor read cursor (last seen event id) so
--                            the dashboard can show unread state across devices.
--
-- Events themselves are NOT stored here: they live in the pipeline-owned
-- data/processed/professor_tracking.json artifact and are served read-only by
-- the backend. Supabase only holds the user's relationship to them.

CREATE TABLE IF NOT EXISTS public.professor_follows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text NOT NULL,
  professor_id text NOT NULL
    CHECK (professor_id ~ '^prof:v1:[a-z0-9-]{1,48}:[0-9a-f]{20}$'),
  professor_name text
    CHECK (professor_name IS NULL OR char_length(professor_name) <= 200),
  school text
    CHECK (school IS NULL OR char_length(school) <= 64),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (device_id, professor_id)
);

ALTER TABLE public.professor_follows ENABLE ROW LEVEL SECURITY;

-- A follow is created or removed, never edited — no UPDATE policy.
DROP POLICY IF EXISTS "professor_follows_select_own" ON public.professor_follows;
CREATE POLICY "professor_follows_select_own" ON public.professor_follows
  FOR SELECT USING (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "professor_follows_insert_own" ON public.professor_follows;
CREATE POLICY "professor_follows_insert_own" ON public.professor_follows
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "professor_follows_delete_own" ON public.professor_follows;
CREATE POLICY "professor_follows_delete_own" ON public.professor_follows
  FOR DELETE USING (device_id = (select auth.uid()::text));

CREATE INDEX IF NOT EXISTS idx_professor_follows_device
  ON public.professor_follows (device_id);

CREATE TABLE IF NOT EXISTS public.professor_update_reads (
  device_id text NOT NULL,
  professor_id text NOT NULL
    CHECK (professor_id ~ '^prof:v1:[a-z0-9-]{1,48}:[0-9a-f]{20}$'),
  last_read_event_id text NOT NULL
    CHECK (last_read_event_id ~ '^prof-event:v1:[0-9a-f]{24}$'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (device_id, professor_id)
);

ALTER TABLE public.professor_update_reads ENABLE ROW LEVEL SECURITY;

-- Mutable cursor, mirrors the interactions policy set minus DELETE (clearing
-- a cursor has no product meaning; unfollow leaves it inert).
DROP POLICY IF EXISTS "professor_update_reads_select_own" ON public.professor_update_reads;
CREATE POLICY "professor_update_reads_select_own" ON public.professor_update_reads
  FOR SELECT USING (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "professor_update_reads_insert_own" ON public.professor_update_reads;
CREATE POLICY "professor_update_reads_insert_own" ON public.professor_update_reads
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "professor_update_reads_update_own" ON public.professor_update_reads;
CREATE POLICY "professor_update_reads_update_own" ON public.professor_update_reads
  FOR UPDATE USING (device_id = (select auth.uid()::text))
  WITH CHECK (device_id = (select auth.uid()::text));
