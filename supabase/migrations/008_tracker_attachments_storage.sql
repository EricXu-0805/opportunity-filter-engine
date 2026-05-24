-- Storage bucket for files attached to a tracked opportunity (offer
-- letters, screenshots of email threads, scanned interview prompts).
--
-- Path convention written by frontend:
--   tracker-attachments/{auth.uid()::text}/{opportunity_id}/{filename}
-- RLS keys off the first path segment so a row can only see / write
-- objects under its own auth.uid() prefix — same scoping model the
-- interactions table uses (006_anonymous_auth_rls.sql).

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  VALUES (
    'tracker-attachments',
    'tracker-attachments',
    false,
    5242880,
    ARRAY[
      'application/pdf',
      'image/png',
      'image/jpeg',
      'image/webp',
      'image/gif',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/plain',
      'text/markdown'
    ]::text[]
  )
  ON CONFLICT (id) DO UPDATE
    SET file_size_limit = EXCLUDED.file_size_limit,
        allowed_mime_types = EXCLUDED.allowed_mime_types,
        public = EXCLUDED.public;

DROP POLICY IF EXISTS "tracker_attachments_select_own" ON storage.objects;
DROP POLICY IF EXISTS "tracker_attachments_insert_own" ON storage.objects;
DROP POLICY IF EXISTS "tracker_attachments_update_own" ON storage.objects;
DROP POLICY IF EXISTS "tracker_attachments_delete_own" ON storage.objects;

CREATE POLICY "tracker_attachments_select_own"
  ON storage.objects FOR SELECT
  USING (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );

CREATE POLICY "tracker_attachments_insert_own"
  ON storage.objects FOR INSERT
  WITH CHECK (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );

CREATE POLICY "tracker_attachments_update_own"
  ON storage.objects FOR UPDATE
  USING (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = auth.uid()::text
  )
  WITH CHECK (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );

CREATE POLICY "tracker_attachments_delete_own"
  ON storage.objects FOR DELETE
  USING (
    bucket_id = 'tracker-attachments'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );
