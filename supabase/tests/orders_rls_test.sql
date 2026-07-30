-- Orders RLS tests (migrations 019 + 024). Runs in the same ephemeral cluster as
-- flow_b_merge_test.sql (see run_flow_b_test.sh). Identity comes from the
-- auth.uid() stub reading test.uid; RLS is exercised for real by switching
-- to non-superuser roles. Before LLC formation, migration 024 removes the
-- client grants and policies entirely: browser roles cannot create, read,
-- update, or delete order rows.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

GRANT USAGE ON SCHEMA public TO authenticated;
GRANT USAGE ON SCHEMA public TO anon;

-- Seed one order per device as superuser — bypasses RLS by design.
INSERT INTO public.orders (device_id, package, amount_cents, channel)
VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'single_email', 990, 'manual');
INSERT INTO public.orders (device_id, package, amount_cents, channel)
VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'full_package', 4900, 'manual');

SET ROLE authenticated;
SELECT set_config('test.uid', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', false);

-- 1. An authenticated user CANNOT insert even their own pending order.
DO $$
BEGIN
  INSERT INTO public.orders (device_id, package, amount_cents, channel)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'single_email', 990, 'manual');
  RAISE EXCEPTION 'TEST FAIL orders-1: pre-LLC authenticated insert was allowed';
EXCEPTION WHEN insufficient_privilege THEN
  NULL;
END $$;

-- 2. An authenticated user CANNOT read historical order data.
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n FROM public.orders;
  RAISE EXCEPTION 'TEST FAIL orders-2: pre-LLC authenticated SELECT returned % row(s)', n;
EXCEPTION WHEN insufficient_privilege THEN
  NULL;
END $$;

-- 3. Authenticated UPDATE and DELETE are also rejected at the table boundary.
DO $$
BEGIN
  UPDATE public.orders SET status = 'paid'
  WHERE device_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  RAISE EXCEPTION 'TEST FAIL orders-3: pre-LLC authenticated UPDATE was allowed';
EXCEPTION WHEN insufficient_privilege THEN
  NULL;
END $$;

DO $$
BEGIN
  DELETE FROM public.orders
  WHERE device_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  RAISE EXCEPTION 'TEST FAIL orders-3: pre-LLC authenticated DELETE was allowed';
EXCEPTION WHEN insufficient_privilege THEN
  NULL;
END $$;

RESET ROLE;

-- 4. Anonymous INSERT and SELECT both fail closed.
SET ROLE anon;
DO $$
BEGIN
  INSERT INTO public.orders (device_id, package, amount_cents, channel)
  VALUES ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'single_email', 990, 'manual');
  RAISE EXCEPTION 'TEST FAIL orders-4: pre-LLC anonymous INSERT was allowed';
EXCEPTION WHEN insufficient_privilege THEN
  NULL;
END $$;

DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n FROM public.orders;
  RAISE EXCEPTION 'TEST FAIL orders-4: pre-LLC anonymous SELECT returned % row(s)', n;
EXCEPTION WHEN insufficient_privilege THEN
  NULL;
END $$;
RESET ROLE;

-- 5. Ground truth as service: only the two seeded rows exist and remain pending.
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n FROM public.orders;
  IF n <> 2 THEN
    RAISE EXCEPTION 'TEST FAIL orders-5: expected 2 rows total, got %', n;
  END IF;
  SELECT count(*) INTO n FROM public.orders WHERE status <> 'pending';
  IF n <> 0 THEN
    RAISE EXCEPTION 'TEST FAIL orders-5: % row(s) escaped pending', n;
  END IF;
END $$;
