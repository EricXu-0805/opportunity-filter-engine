-- One statement snapshot covers every logical attachment for this caller. The
-- ZIP client constructs the same marker from the versions it actually read.
-- Each leaf hashes UTF-8 (path, anchor ID, revision, size, MIME), delimited by
-- NUL (impossible within Postgres text). Sort the lowercase hex leaves in C
-- order and hash their concatenation. Only a count, digest and time leave SQL.
CREATE FUNCTION public.tracker_attachment_export_marker() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE u uuid := auth.uid(); marker jsonb;
BEGIN
  IF u IS NULL THEN RAISE EXCEPTION 'sign in required'; END IF;
  WITH resolved AS MATERIALIZED (
    SELECT private.tracker_attachment_view(u, a.name) AS item
    FROM storage.objects AS a
    WHERE a.bucket_id = 'tracker-attachments'
      -- In C order '/' is immediately followed by '0': a bounded UID prefix.
      AND a.name COLLATE "C" >= (u::text || '/') AND a.name COLLATE "C" < (u::text || '0')
      AND NOT (right(a.name, length('/.emptyFolderPlaceholder')) = '/.emptyFolderPlaceholder'
               AND (a.metadata->'size' = '0'::jsonb) IS TRUE)
  ), leaves AS (
    SELECT encode(sha256(convert_to(item->>'path', 'UTF8') || decode('00','hex') ||
                         convert_to(item->>'anchorId', 'UTF8') || decode('00','hex') ||
                         convert_to(item->>'revision', 'UTF8') || decode('00','hex') ||
                         convert_to(item->>'sizeBytes', 'UTF8') || decode('00','hex') ||
                         convert_to(item->>'mimeType', 'UTF8')), 'hex') AS leaf
    FROM resolved WHERE item IS NOT NULL
  )
  SELECT jsonb_build_object(
    'count', count(*),
    'digest', encode(sha256(convert_to(coalesce(string_agg(leaf, '' ORDER BY leaf COLLATE "C"), ''), 'UTF8')), 'hex'),
    'observedAt', statement_timestamp()
  ) INTO marker FROM leaves;
  RETURN marker;
END $$;
REVOKE ALL ON FUNCTION public.tracker_attachment_export_marker() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.tracker_attachment_export_marker() TO authenticated;
