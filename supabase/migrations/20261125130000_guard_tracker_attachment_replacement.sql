-- Storage's PUT endpoint uses an upsert. A replacement may only change the
-- selected object/version. Keep the ordinary upload path and its RLS unchanged.
CREATE FUNCTION public.guard_tracker_attachment_replacement() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE expected jsonb := NEW.user_metadata -> 'ofe_replace';
BEGIN
  -- AFTER INSERT distinguishes a real insert from ON CONFLICT DO UPDATE.
  -- A missing path must stay missing even if the Storage API probes it first.
  IF TG_OP = 'INSERT' THEN
    RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'tracker_attachment_changed';
  END IF;
  IF OLD.id::text IS DISTINCT FROM (expected ->> 'id')
     OR OLD.version IS NULL OR OLD.version IS DISTINCT FROM (expected ->> 'version')
     OR OLD.metadata ->> 'mimetype' IS DISTINCT FROM (expected ->> 'mime')
     OR (NEW.metadata ->> 'mimetype' IS NOT NULL AND
         NEW.metadata ->> 'mimetype' IS DISTINCT FROM (expected ->> 'mime'))
  THEN
    RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'tracker_attachment_changed';
  END IF;
  -- The guard is a request condition. Keep the old user metadata on the file.
  NEW.user_metadata := OLD.user_metadata;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_tracker_attachment_replacement() FROM PUBLIC, anon, authenticated;

CREATE TRIGGER tracker_attachment_reject_recreation
AFTER INSERT ON storage.objects FOR EACH ROW
WHEN (NEW.bucket_id = 'tracker-attachments' AND NEW.user_metadata ? 'ofe_replace')
EXECUTE FUNCTION public.guard_tracker_attachment_replacement();

CREATE TRIGGER tracker_attachment_check_revision
BEFORE UPDATE ON storage.objects FOR EACH ROW
WHEN (NEW.bucket_id = 'tracker-attachments' AND NEW.user_metadata ? 'ofe_replace')
EXECUTE FUNCTION public.guard_tracker_attachment_replacement();

-- Publish the client capability only after the database write guards exist.
CREATE FUNCTION public.tracker_attachment_replace_version(
  p_path text, p_id uuid, p_etag text, p_updated_at timestamptz, p_mime text
) RETURNS text LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT o.version
  FROM storage.objects AS o
  WHERE o.bucket_id = 'tracker-attachments' AND o.name = p_path AND o.id = p_id
    AND split_part(o.name, '/', 1) = auth.uid()::text
    AND coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) IS FALSE
    AND o.metadata ->> 'mimetype' = p_mime
    AND CASE WHEN p_etag IS NOT NULL THEN o.metadata ->> 'eTag' = p_etag
             ELSE date_trunc('milliseconds', o.updated_at) = date_trunc('milliseconds', p_updated_at) END;
$$;
REVOKE ALL ON FUNCTION public.tracker_attachment_replace_version(text, uuid, text, timestamptz, text)
  FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.tracker_attachment_replace_version(text, uuid, text, timestamptz, text)
  TO authenticated;
