-- Capture from the selected recovery point while Storage writes are frozen.
-- psql -XqAtw -v ON_ERROR_STOP=1 -v source_ref=... -v backup_id=... -f ...
BEGIN READ ONLY;
SET LOCAL row_security = off;
SELECT jsonb_build_object(
    'source_environment', :'source_ref',
    'source_backup_id', :'backup_id',
    'buckets', (
        SELECT jsonb_object_agg(b.id, jsonb_build_object(
            'public', b.public,
            'objects', COALESCE((
                SELECT jsonb_object_agg(o.name, (o.metadata->>'size')::bigint)
                FROM storage.objects o WHERE o.bucket_id = b.id
            ), '{}'::jsonb)
        ))
        FROM storage.buckets b
        WHERE b.id IN ('tracker-attachments', 'application-materials', 'tracker-attachment-versions')
    )
);
COMMIT;
