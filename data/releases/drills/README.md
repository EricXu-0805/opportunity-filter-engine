# Restore-drill records

One JSON file per drill, written by `scripts/restore_drill.py` and read by the
`restore_drill` gate in `scripts/release_gate.py`. The procedure is
`docs/DISASTER_RECOVERY.md` §3.

These are **not** per-release. A drill proves that the backups restore and that
the restored database is usable; it stays valid until it expires (180 days) or
until the migration set moves past the one it restored. The per-release
`backup` / `restore` attestations live in `data/releases/evidence/<sha>.json`
instead.

Write them with the script, not by hand. The gate checks each clause
separately — `final_result: PASS` with a failing `rls_validation` is rejected as
`drill_internally_inconsistent`, precisely so a summary cannot outrun its own
steps.

```
drill_id                  traceable id for this run
performed_at              ISO-8601 UTC
source_backup_id          the recovery point, as the dashboard names it
source_environment        production project ref the backup came from
scratch_environment       project ref it was restored INTO (never production)
source_schema_version     migration-set identity at the source
restored_schema_version   migration-set identity observed after the restore
restore_started_at        when the dashboard restore began
restore_completed_at      when validation ran
schema_validation         PASS | FAIL
data_validation           PASS | FAIL
rls_validation            PASS | FAIL
application_smoke         PASS | PARTIAL | FAIL
issues_found              list; empty on a clean drill
final_result              PASS | FAIL
```

No credential of any kind belongs in these files. They name *which* project was
used, never how to reach it.

**This directory is empty because no restore drill has ever been completed.**
That is why the release gate reports `restore_drill: UNVERIFIED` and the
release is NO-GO. See `docs/DISASTER_RECOVERY.md` §5 for the 2026-09-04
attempt and what blocked it.
