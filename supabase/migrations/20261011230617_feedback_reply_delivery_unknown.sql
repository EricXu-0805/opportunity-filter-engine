-- 20261011230617_feedback_reply_delivery_unknown.sql
-- Let an admin reply email record an outcome nobody knows.
--
-- 030 allowed three reply-delivery values: 'stored' (no email attempted),
-- 'emailed' (Resend accepted it) and 'email_failed'. The reply route put every
-- send exception in 'email_failed', including a read timeout and a Resend 5xx,
-- where the request had reached the provider and the email may have gone out.
-- The ticket then told the operator the student had nothing, and a resend
-- could be the student's second copy.
--
-- 'unknown' is that ambiguous outcome. 'email_failed' stays for a definite
-- refusal: a Resend 4xx, the per-recipient cap, or no connection made. Rows
-- already marked 'email_failed' stay as they are, because which of them were
-- ambiguous was never recorded.
ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_reply_delivery_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_reply_delivery_check
  CHECK (admin_reply_delivery IS NULL OR admin_reply_delivery IN (
    'stored', 'emailed', 'email_failed', 'unknown'
  ));
