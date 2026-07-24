-- Assertions that require a real Supabase CLI push (and therefore the
-- supabase_migrations history table), not the manual psql policy-test runner.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

DO $$
DECLARE
  v_version text;
BEGIN
  FOREACH v_version IN ARRAY ARRAY[
    '001','002','003','004','005','006','007','008','009','010','011',
    '012','013','014','015','016','017','018','0181','019','020','0201',
    '021'
  ] LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM supabase_migrations.schema_migrations
      WHERE version = v_version
    ) THEN
      RAISE EXCEPTION 'TEST FAIL migration history: missing version %', v_version;
    END IF;
  END LOOP;

  IF EXISTS (
    SELECT version
    FROM supabase_migrations.schema_migrations
    GROUP BY version
    HAVING count(*) <> 1
  ) THEN
    RAISE EXCEPTION 'TEST FAIL migration history: duplicate migration version';
  END IF;

  IF to_regclass('public.profiles') IS NULL
     OR to_regclass('public.favorites') IS NULL THEN
    RAISE EXCEPTION 'TEST FAIL migration history: core tables were not migrated';
  END IF;
END;
$$;

DO $$ BEGIN
  RAISE WARNING 'PASS real Supabase migration history contract';
END $$;
