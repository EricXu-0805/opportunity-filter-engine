SELECT CASE WHEN pg_catalog.row_security_active('storage.buckets'::regclass)
              OR pg_catalog.row_security_active('storage.objects'::regclass)
            THEN NULL
            ELSE (
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
       END AS buckets
