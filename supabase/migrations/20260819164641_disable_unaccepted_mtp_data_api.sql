-- The release scope hides Full Resume Renovate and Professor Signals until
-- their product contracts are accepted.  Their four storage tables predate
-- that decision and are called directly by browser Supabase clients, so an
-- API/route flag alone cannot close the capability for a stale bundle or a
-- direct PostgREST request.
--
-- Preserve every row and keep database-owner/service-role access.  A future
-- acceptance migration may restore bounded browser grants and RLS policies,
-- but it must do both deliberately; restoring only one side must stay closed.

DROP POLICY IF EXISTS "resume_renovations_select_own"
  ON public.resume_renovations;
DROP POLICY IF EXISTS "resume_renovations_insert_own"
  ON public.resume_renovations;
DROP POLICY IF EXISTS "resume_renovations_update_own"
  ON public.resume_renovations;
DROP POLICY IF EXISTS "resume_renovations_delete_own"
  ON public.resume_renovations;

DROP POLICY IF EXISTS "resume_renovation_versions_select_own"
  ON public.resume_renovation_versions;
DROP POLICY IF EXISTS "resume_renovation_versions_insert_own"
  ON public.resume_renovation_versions;

DROP POLICY IF EXISTS "professor_follows_select_own"
  ON public.professor_follows;
DROP POLICY IF EXISTS "professor_follows_insert_own"
  ON public.professor_follows;
DROP POLICY IF EXISTS "professor_follows_delete_own"
  ON public.professor_follows;

DROP POLICY IF EXISTS "professor_update_reads_select_own"
  ON public.professor_update_reads;
DROP POLICY IF EXISTS "professor_update_reads_insert_own"
  ON public.professor_update_reads;
DROP POLICY IF EXISTS "professor_update_reads_update_own"
  ON public.professor_update_reads;

REVOKE SELECT, INSERT, UPDATE, DELETE
  ON TABLE public.resume_renovations,
           public.resume_renovation_versions,
           public.professor_follows,
           public.professor_update_reads
  FROM PUBLIC, anon, authenticated;

-- Supabase's service key maps to service_role.  Keep the server/ops path
-- explicit rather than relying on managed default privileges.  The database
-- owner retains its inherent ownership privileges as well.
GRANT SELECT, INSERT, UPDATE, DELETE
  ON TABLE public.resume_renovations,
           public.resume_renovation_versions,
           public.professor_follows,
           public.professor_update_reads
  TO service_role;
