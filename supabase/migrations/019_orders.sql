-- 019_orders.sql
-- Concierge manual-payment orders. The user creates their own PENDING order
-- (client insert under RLS), scans a static QR code, and claims payment via
-- the backend; every status transition after 'pending' is service-role only
-- (mark-paid-claimed + admin confirm endpoints). Deliberately NO user UPDATE
-- or DELETE policies — a client that could flip its own row to 'paid' would
-- be self-serve fraud.

CREATE TABLE IF NOT EXISTS public.orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text NOT NULL,
  package text NOT NULL,
  amount_cents int NOT NULL CHECK (amount_cents > 0),
  currency text NOT NULL DEFAULT 'usd',
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'awaiting_confirm', 'paid', 'cancelled', 'refunded')),
  channel text NOT NULL CHECK (channel IN ('wechat', 'alipay', 'manual', 'stripe')),
  note text,
  created_at timestamptz NOT NULL DEFAULT now(),
  paid_at timestamptz
);

ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "orders_insert_own_pending" ON public.orders;
CREATE POLICY "orders_insert_own_pending" ON public.orders
  FOR INSERT WITH CHECK (
    device_id = (select auth.uid()::text) AND status = 'pending'
  );

DROP POLICY IF EXISTS "orders_select_own" ON public.orders;
CREATE POLICY "orders_select_own" ON public.orders
  FOR SELECT USING (device_id = (select auth.uid()::text));
