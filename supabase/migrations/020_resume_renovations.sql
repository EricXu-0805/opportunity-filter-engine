-- 020_resume_renovations.sql
-- Per-opportunity résumé renovation: the student takes their standard résumé
-- (structured into sections+bullets) and macro-renovates it toward one
-- professor/opportunity, then optionally re-works individual bullets. Because
-- every opportunity record already carries pi_name/org/dept/keywords, tailoring
-- by opportunity_id IS "per-professor" — no separate professor entity needed.
--
-- Two tables, mirroring the profiles (mutable) + profile_versions (append-only)
-- split so the same anonymous-auth RLS and cross-device merge patterns apply:
--
--   resume_renovations          — one mutable working doc per (device,opp).
--   resume_renovation_versions  — append-only doc snapshots for whole-doc undo.
--
-- The per-bullet ROLLBACK history lives INSIDE doc (a variant chain per bullet:
-- base_text floor + macro/ai/user variants + a `current` index, -1 == base).
-- Rollback is a pure pointer move client-side — no LLM, so it can never
-- fabricate. AI re-optimization appends an anti-fabrication-validated variant;
-- self-edit appends a user variant. The append-only versions table is the
-- coarse safety net if a destructive per-bullet edit needs whole-doc recovery.

CREATE TABLE IF NOT EXISTS public.resume_renovations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text NOT NULL,
  opportunity_id text NOT NULL,
  doc jsonb NOT NULL DEFAULT '{}'::jsonb,
  base_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  method text,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (device_id, opportunity_id)
);

ALTER TABLE public.resume_renovations ENABLE ROW LEVEL SECURITY;

-- Mutable, mirrors the profiles policy set (own select/insert/update/delete).
DROP POLICY IF EXISTS "resume_renovations_select_own" ON public.resume_renovations;
CREATE POLICY "resume_renovations_select_own" ON public.resume_renovations
  FOR SELECT USING (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "resume_renovations_insert_own" ON public.resume_renovations;
CREATE POLICY "resume_renovations_insert_own" ON public.resume_renovations
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "resume_renovations_update_own" ON public.resume_renovations;
CREATE POLICY "resume_renovations_update_own" ON public.resume_renovations
  FOR UPDATE USING (device_id = (select auth.uid()::text))
  WITH CHECK (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "resume_renovations_delete_own" ON public.resume_renovations;
CREATE POLICY "resume_renovations_delete_own" ON public.resume_renovations
  FOR DELETE USING (device_id = (select auth.uid()::text));

CREATE INDEX IF NOT EXISTS idx_resume_renovations_device
  ON public.resume_renovations (device_id);

CREATE TABLE IF NOT EXISTS public.resume_renovation_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text NOT NULL,
  opportunity_id text NOT NULL,
  doc jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.resume_renovation_versions ENABLE ROW LEVEL SECURITY;

-- Append-only, mirrors profile_versions (own select + insert only).
DROP POLICY IF EXISTS "resume_renovation_versions_select_own" ON public.resume_renovation_versions;
CREATE POLICY "resume_renovation_versions_select_own" ON public.resume_renovation_versions
  FOR SELECT USING (device_id = (select auth.uid()::text));

DROP POLICY IF EXISTS "resume_renovation_versions_insert_own" ON public.resume_renovation_versions;
CREATE POLICY "resume_renovation_versions_insert_own" ON public.resume_renovation_versions
  FOR INSERT WITH CHECK (device_id = (select auth.uid()::text));

CREATE INDEX IF NOT EXISTS idx_resume_renovation_versions_device
  ON public.resume_renovation_versions (device_id);
CREATE INDEX IF NOT EXISTS idx_resume_renovation_versions_created
  ON public.resume_renovation_versions (created_at DESC);
