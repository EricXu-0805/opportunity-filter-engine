-- 024_disable_pre_llc_orders.sql
-- LLC / commercial terms are not accepted yet. The public app may collect a
-- concierge intent through waitlist, but no browser session may create an
-- order or read historical package / amount / status data directly in
-- Supabase. Backend route gates cannot protect this direct database path, so
-- remove both client-facing RLS policies and all browser-role table access.
--
-- A future reviewed payments acceptance migration must deliberately restore
-- the required grants and bounded policies together.

DROP POLICY IF EXISTS "orders_insert_own_pending" ON public.orders;
DROP POLICY IF EXISTS "orders_select_own" ON public.orders;
REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE public.orders FROM anon, authenticated;
