-- Dynamic contract for the data-plane half of the MTP capability close.
-- The runner grants all four roles before the closing migration, so these
-- assertions prove the migration actively removes browser access rather than
-- passing because a vanilla PostgreSQL cluster never granted it.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

DO $$
DECLARE
  r text;
  t text;
  p text;
  remaining_policies integer;
  preserved_rows integer;
BEGIN
  FOREACH r IN ARRAY ARRAY['public', 'anon', 'authenticated'] LOOP
    FOREACH t IN ARRAY ARRAY[
      'public.resume_renovations',
      'public.resume_renovation_versions',
      'public.professor_follows',
      'public.professor_update_reads'
    ] LOOP
      FOREACH p IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
        IF has_table_privilege(r, t, p) THEN
          RAISE EXCEPTION
            'TEST FAIL hidden-capability-acl: % still has % on %', r, p, t;
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;

  SELECT count(*) INTO remaining_policies
  FROM pg_policies
  WHERE schemaname = 'public'
    AND tablename = ANY (ARRAY[
      'resume_renovations',
      'resume_renovation_versions',
      'professor_follows',
      'professor_update_reads'
    ]);
  IF remaining_policies <> 0 THEN
    RAISE EXCEPTION
      'TEST FAIL hidden-capability-acl: % browser policies remain',
      remaining_policies;
  END IF;

  FOREACH t IN ARRAY ARRAY[
    'public.resume_renovations',
    'public.resume_renovation_versions',
    'public.professor_follows',
    'public.professor_update_reads'
  ] LOOP
    FOREACH p IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
      IF NOT has_table_privilege('service_role', t, p) THEN
        RAISE EXCEPTION
          'TEST FAIL hidden-capability-acl: service_role lost % on %', p, t;
      END IF;
    END LOOP;
  END LOOP;

  IF NOT has_function_privilege(
    'authenticated', 'public.redeem_merge_grant(uuid,text)', 'EXECUTE'
  ) THEN
    RAISE EXCEPTION
      'TEST FAIL hidden-capability-acl: authenticated merge RPC was revoked';
  END IF;

  SELECT
    (SELECT count(*) FROM public.resume_renovations
      WHERE device_id = 'acl-preserve-device')
    + (SELECT count(*) FROM public.resume_renovation_versions
      WHERE device_id = 'acl-preserve-device')
    + (SELECT count(*) FROM public.professor_follows
      WHERE device_id = 'acl-preserve-device')
    + (SELECT count(*) FROM public.professor_update_reads
      WHERE device_id = 'acl-preserve-device')
  INTO preserved_rows;
  IF preserved_rows <> 4 THEN
    RAISE EXCEPTION
      'TEST FAIL hidden-capability-acl: expected 4 preserved rows, got %',
      preserved_rows;
  END IF;
END;
$$;

-- Table ACLs are enforced, not merely reported.
SET ROLE authenticated;
DO $$
BEGIN
  BEGIN
    PERFORM count(*) FROM public.resume_renovations;
    RAISE EXCEPTION
      'TEST FAIL hidden-capability-acl-live: authenticated SELECT succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;

  BEGIN
    INSERT INTO public.professor_follows (device_id, professor_id)
    VALUES (
      'acl-browser-device',
      'prof:v1:uiuc:ffffffffffffffffffff'
    );
    RAISE EXCEPTION
      'TEST FAIL hidden-capability-acl-live: authenticated INSERT succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END;
$$;
RESET ROLE;

DO $$ BEGIN
  RAISE WARNING 'PASS hidden MTP data-plane ACL + preservation contract';
END $$;
