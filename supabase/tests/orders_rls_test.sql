-- Orders RLS tests (migration 019). Runs in the same ephemeral cluster as
-- flow_b_merge_test.sql (see run_flow_b_test.sh). Identity comes from the
-- auth.uid() stub reading test.uid; RLS is exercised for real by switching
-- to the non-superuser `authenticated` role — table privileges are granted
-- here to mirror Supabase's default grants, so the POLICIES are the gate.

\set ON_ERROR_STOP on
\timing off
SET client_min_messages = warning;

GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.orders TO authenticated;

-- Seed a VICTIM order (device B) as superuser — bypasses RLS by design.
INSERT INTO public.orders (device_id, package, amount_cents, channel)
VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'full_package', 4900, 'manual');

SET ROLE authenticated;
SELECT set_config('test.uid', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', false);

-- 1. A user CAN insert their own pending order.
DO $$
BEGIN
  INSERT INTO public.orders (device_id, package, amount_cents, channel)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'single_email', 990, 'manual');
END $$;

-- 2. A user CANNOT insert an order that is already 'paid'.
DO $$
BEGIN
  INSERT INTO public.orders (device_id, package, amount_cents, channel, status)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'full_package', 4900, 'manual', 'paid');
  RAISE EXCEPTION 'TEST FAIL orders-2: insert with status=paid was allowed';
EXCEPTION WHEN insufficient_privilege THEN
  NULL;  -- RLS WITH CHECK rejected it, as required
END $$;

-- 3. A user CANNOT insert an order for another device.
DO $$
BEGIN
  INSERT INTO public.orders (device_id, package, amount_cents, channel)
  VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'single_email', 990, 'manual');
  RAISE EXCEPTION 'TEST FAIL orders-3: insert for another device was allowed';
EXCEPTION WHEN insufficient_privilege THEN
  NULL;
END $$;

-- 4. A user CANNOT update status — no UPDATE policy, so zero rows qualify.
DO $$
DECLARE
  n int;
BEGIN
  UPDATE public.orders SET status = 'paid'
  WHERE device_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 0 THEN
    RAISE EXCEPTION 'TEST FAIL orders-4: user UPDATE touched % row(s)', n;
  END IF;
END $$;

-- 5. A user can read ONLY their own orders (device B's row is invisible).
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n FROM public.orders;
  IF n <> 1 THEN
    RAISE EXCEPTION 'TEST FAIL orders-5: expected 1 visible order, got %', n;
  END IF;
  SELECT count(*) INTO n FROM public.orders
  WHERE device_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  IF n <> 0 THEN
    RAISE EXCEPTION 'TEST FAIL orders-5: another device''s order is readable';
  END IF;
END $$;

RESET ROLE;

-- 6. Ground truth as service: both rows exist, statuses untouched by the user.
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n FROM public.orders;
  IF n <> 2 THEN
    RAISE EXCEPTION 'TEST FAIL orders-6: expected 2 rows total, got %', n;
  END IF;
  SELECT count(*) INTO n FROM public.orders WHERE status <> 'pending';
  IF n <> 0 THEN
    RAISE EXCEPTION 'TEST FAIL orders-6: % row(s) escaped pending', n;
  END IF;
END $$;
