-- =====================================================================
-- interactions: allow 'contacted' status (W12 cold-email boundary)
--
-- The cold-email Confirm-sent attestation historically wrote 'applied'
-- because no closer status existed, so a cold-email contact rendered as
-- "Applied" in the tracker — a mislabeled outreach type. 'contacted' is the
-- honest state for "I sent the outreach email"; 'applied' stays the state
-- for an actual application. Existing rows are NOT rewritten (a historical
-- 'applied' may genuinely be an application; we never guess).
--
-- The append-only status-change trigger (009/014) needs no change: it logs
-- whatever distinct transition occurs. Responsiveness aggregation counts
-- 'contacted' as a contact signal (backend/routes/responsiveness.py).
-- =====================================================================

ALTER TABLE interactions DROP CONSTRAINT IF EXISTS interactions_interaction_type_check;
ALTER TABLE interactions ADD CONSTRAINT interactions_interaction_type_check
  CHECK (interaction_type IN ('contacted', 'applied', 'replied', 'interviewing', 'rejected', 'dismissed'));
