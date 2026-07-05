-- Feedback-learning v1: per-vote context for offline analysis
-- (docs/FEEDBACK_LEARNING.md). The client writes {"position": <1-based rank
-- of the card in the results list>} so position bias can be measured and
-- corrected offline. jsonb (not a position column) because future context —
-- e.g. per-layer component scores to unlock true weight replay — lands
-- without another migration. Nullable: old rows and pre-018 clients keep
-- working (the client retries without context when this column is missing).

ALTER TABLE match_feedback ADD COLUMN IF NOT EXISTS context jsonb;
