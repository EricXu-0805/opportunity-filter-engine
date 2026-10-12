-- Tracker attachments need a signed-in account. A guest session's files stay
-- under the guest uid when it later signs in to an account that already exists
-- (the merge moves rows, not Storage objects), so a guest may no longer add
-- one. Reading, opening and deleting files already uploaded stay as they were.
--
-- The upload goes browser -> Storage directly; there is no backend route to
-- guard, so this policy is the server-side gate. Supabase puts is_anonymous in
-- the JWT of an anonymous session (the same claim 017 reads).

DROP POLICY IF EXISTS "tracker_attachments_insert_own" ON storage.objects;

CREATE POLICY "tracker_attachments_insert_own"
  ON storage.objects FOR INSERT
  WITH CHECK (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = (select auth.uid()::text)
    AND (select coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false)) IS NOT TRUE
  );
