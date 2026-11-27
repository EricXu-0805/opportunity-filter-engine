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
source_schema_version     catalogue, migration and project evidence captured with the backup
source_schema_manifest_sha256  SHA-256 retained with the source backup receipt
restored_schema_version   independently captured scratch catalogue and migration evidence
restore_started_at        when the dashboard restore began
restore_completed_at      when validation ran
schema_validation         PASS | FAIL
data_validation           PASS | FAIL | UNVERIFIED; evidence.data names the tables outside what the recovery point
                          explains and binds the private row counts by two SHA-256 digests
rls_validation            PASS | FAIL
application_smoke         PASS | PARTIAL | FAIL
attachment_manifest_sha256  SHA-256 retained with the storage backup receipt
attachment_validation     PASS | FAIL | UNVERIFIED | NOT_COVERED; aggregate byte proof in evidence.attachments
issues_found              list; empty on a clean drill
not_covered               list; what the drill left out on purpose (attachment bytes, or a checkout ahead of production)
final_result              PASS | FAIL | UNVERIFIED, for what the drill covered
```

No credential of any kind belongs in these files. They name *which* project was
used, never how to reach it.

No row count belongs in them either: this repository is public. The drill
writes the per-table counts, the failure lines that quote them, the number of
rows an anonymous caller could read when the RLS step fails and the backend's
`/api/ready` reply to `<drill_id>.private.json` beside the private source row
counts, outside the repository.

**This directory is empty because no restore drill has ever been completed.**
That is why the release gate reports `restore_drill: BLOCKED` and the
release is NO-GO. See `docs/DISASTER_RECOVERY.md` §5 for the 2026-09-04
attempt and what blocked it.
