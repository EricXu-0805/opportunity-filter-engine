-- 026_feedback_tickets.sql
-- W15: turn feedback submissions into durable TICKETS with a real lifecycle.
--
-- 016 shipped feedback as a six-column insert-only inbox: a message, an
-- optional email, and nothing else. An operator could read it (service role)
-- but could not assign it, prioritise it, reply in-app, or record that it had
-- been handled — the only "reply" was a mailto: link that left the system and
-- wrote nothing back. This migration adds the lifecycle columns, an
-- append-only event log for admin actions, and a submission idempotency key.
--
-- Model mirrors 019_orders.sql: the client may INSERT its own row in the
-- initial state and READ its own rows, but EVERY transition afterwards is
-- service-role only (no user UPDATE policy). A client that could set its own
-- ticket to `resolved` would be fabricating a handling decision.
--
-- Audit: feedback_events is append-only and service-role-only, modelled on
-- 009_interaction_status_changes.sql but WITH an actor column (009 had no
-- notion of an operator). RLS forbids user updates, so the admin API is the
-- only sanctioned mutation path and therefore the only event writer; a direct
-- psql edit would bypass the log (documented residual, same as 009).

-- ---------------------------------------------------------------------------
-- Ticket lifecycle columns
-- ---------------------------------------------------------------------------

-- What the submitter told us (category/subject were never captured; the
-- widget copy invites bug/idea/other but stored none of it).
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS category text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS subject text;

-- Handling state. 'open' is the arrival state: a ticket nobody has triaged.
-- 'waiting_on_user' parks a ticket that needs a reply before it can move.
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'open';
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS priority text NOT NULL DEFAULT 'normal';
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS assigned_to text;

-- Reply and resolution are DIFFERENT things: a reply is a message to the
-- user, a resolution is the handling decision. Recording a reply must never
-- imply the ticket was resolved (and vice versa).
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS admin_reply text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS admin_reply_at timestamptz;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS admin_reply_by text;
-- Whether the reply was actually delivered to the user, or only stored.
-- 'stored' is the honest default: we do not claim an email went out unless a
-- provider accepted it (the W14 notification invariant).
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS admin_reply_delivery text;

ALTER TABLE feedback ADD COLUMN IF NOT EXISTS resolution text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS resolution_note text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS resolved_by text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS resolved_at timestamptz;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS closed_at timestamptz;

ALTER TABLE feedback ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

-- Submission idempotency: the widget mints a token per composed message, so a
-- retry after an ambiguous failure (server committed, response lost) reuses
-- the same token and collides instead of creating a second ticket.
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS client_token text;

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_status_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_status_check
  CHECK (status IN ('open', 'triaged', 'in_progress', 'waiting_on_user', 'resolved', 'closed'));

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_priority_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_priority_check
  CHECK (priority IN ('low', 'normal', 'high', 'urgent'));

-- Resolution taxonomy. NULL while unresolved — an unresolved ticket must not
-- carry a resolution, and a resolved one must carry a real decision rather
-- than a silent close.
ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_resolution_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_resolution_check
  CHECK (resolution IS NULL OR resolution IN (
    'fixed', 'expected_behavior', 'duplicate', 'data_corrected',
    'unable_to_reproduce', 'wont_fix', 'user_guidance_provided'
  ));

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_category_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_category_check
  CHECK (category IS NULL OR category IN ('bug', 'idea', 'data_issue', 'account', 'other'));

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_reply_delivery_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_reply_delivery_check
  CHECK (admin_reply_delivery IS NULL OR admin_reply_delivery IN (
    'stored', 'emailed', 'email_failed'
  ));

-- A resolved/closed ticket must actually carry its decision: no silent closes.
ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_resolved_has_decision;
ALTER TABLE feedback ADD CONSTRAINT feedback_resolved_has_decision
  CHECK (status NOT IN ('resolved', 'closed') OR resolution IS NOT NULL);

-- One ticket per (submitter, client token). Partial so legacy rows and any
-- client that omits the token are unaffected.
DROP INDEX IF EXISTS feedback_client_token_uniq;
CREATE UNIQUE INDEX feedback_client_token_uniq
  ON feedback (device_id, client_token)
  WHERE client_token IS NOT NULL;

-- The admin inbox sorts by recency and filters by state; 016 shipped no
-- indexes at all.
CREATE INDEX IF NOT EXISTS feedback_created_idx ON feedback (created_at DESC);
CREATE INDEX IF NOT EXISTS feedback_status_created_idx ON feedback (status, created_at DESC);

-- ---------------------------------------------------------------------------
-- Users may READ their own tickets (016 had no SELECT policy at all)
-- ---------------------------------------------------------------------------
-- Reading back your own ticket is what makes the returned UUID meaningful:
-- the submitter can confirm the ticket exists and watch its status, exactly
-- like orders_select_own. Still no UPDATE/DELETE policy — handling state is
-- operator-owned.
DROP POLICY IF EXISTS "feedback_select_own" ON feedback;
CREATE POLICY "feedback_select_own" ON feedback
  FOR SELECT USING (device_id = (select auth.uid()::text));

-- ---------------------------------------------------------------------------
-- Append-only admin audit trail
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feedback_events (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  ticket_id uuid NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
  -- Self-declared operator label from the admin API. Every operator shares
  -- one ADMIN_TOKEN today, so this attributes the action to a claimed
  -- identity, not a cryptographically proven one (documented residual).
  actor text NOT NULL,
  action text NOT NULL CHECK (action IN (
    'assigned', 'unassigned', 'priority_changed', 'status_changed',
    'replied', 'resolved', 'reopened', 'note_added'
  )),
  from_value text,
  to_value text,
  note text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS feedback_events_ticket_idx
  ON feedback_events (ticket_id, created_at DESC);

ALTER TABLE feedback_events ENABLE ROW LEVEL SECURITY;
-- No policies: operator-only data, reachable exclusively through the
-- service-role key (same containment as merge_grants in 017).
