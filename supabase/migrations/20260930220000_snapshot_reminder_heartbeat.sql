-- 20260930220000_snapshot_reminder_heartbeat.sql
-- Register the weekly snapshot-reminder workflow with the dead man's switch.
--
-- .github/workflows/snapshot-reminder.yml checks whether a hand-exported
-- snapshot (today only CMU's login-only undergraduate research project list,
-- data/snapshots/cmu_uro_projects.json) is due for a new export, and emails
-- the operator when it is. Like every scheduled workflow it checks in to
-- ops_heartbeats (migration 032), and the check-in route answers 404 for a
-- name that is not registered, so this row has to exist before the
-- workflow's first scheduled run.
--
-- Weekly interval, one day of grace: the same terms as campus_seed_health.
INSERT INTO ops_heartbeats
  (name, description, expected_interval_seconds, grace_seconds, priority)
VALUES
  ('snapshot_reminder',
   'Weekly snapshot refresh check (Mon 13:00 UTC). If this stops, nobody is emailed when the hand-exported CMU research project list is due for a new export.',
   604800, 86400, 'normal')
ON CONFLICT (name) DO UPDATE SET
  description = EXCLUDED.description,
  expected_interval_seconds = EXCLUDED.expected_interval_seconds,
  grace_seconds = EXCLUDED.grace_seconds,
  priority = EXCLUDED.priority,
  updated_at = now();
