# Disaster recovery: backup and restore

> **Current status: NOT VERIFIED — this is a release blocker.**
>
> ```
> backup exists  !=  recovery verified
> ```
>
> No automated backup exists in this repository, and no restore has ever been
> tested. `scripts/release_gate.py` reports both `backup` and `restore` as
> `UNVERIFIED`, which keeps the release at NO-GO. That is the correct state
> until the drill below is performed and its result recorded here.

## What exists today

- **No automated backup.** No `pg_dump`, `pg_restore`, PITR configuration,
  snapshot job, or retention policy appears in any workflow, `Makefile`
  target, or script. (The `retention-days: 14` in `ci.yml` is the Playwright
  report artifact, not data.)
- **No restore procedure**, documented or automated.
- The only backup-adjacent text in the repo is inside a manual, approval-gated
  plan (`supabase/MIGRATION_REPAIR.md`) which says: *"Confirm backup/PITR
  status in the Supabase dashboard first; record the recovery point. Stop if
  recoverability is unknown."* That instruction is itself an admission that
  recoverability is not established in-repo.
- Whether Supabase daily backups or point-in-time recovery are enabled on the
  project **cannot be determined from this repository**, and the recorded plan
  tier in `RUNBOOK.md` is stale. This must be checked in the dashboard by an
  operator.
- Application-level recovery is separately incomplete: whole-document
  renovation snapshots are retained but have no restore UI.

Because migrations are forward-only and three are non-idempotent (see
`docs/RELEASE.md` §4), a restore is the *only* recovery path for a bad
migration. That makes this gate load-bearing rather than a formality.

## Required before any release containing a migration

### 1. Establish and record the backup

Record in the table below, from the Supabase dashboard:

- backup identifier / recovery point
- timestamp (UTC)
- environment (production project ref)
- scope (which schemas/tables; whether storage objects are included)
- retention window
- owner (who can perform a restore)

### 2. Prove recovery, do not assume it

Restore the recorded point into a **scratch** project or a local cluster —
never over production — and verify all four:

1. **Application starts** against the restored database.
2. **Schema works**: the migration set matches expectations; run
   `supabase/tests/run_supabase_cli_migration_test.sh` semantics against the
   restored schema, or at minimum confirm the tables and policies the app
   requires exist.
3. **Data is readable**: representative reads succeed for each user-owned
   table (favorites, interactions, saved_searches, orders, feedback,
   ops_incidents) under RLS as a normal account, not just as service role.
4. **Readiness succeeds**: `/api/ready` returns 200 with the restored database
   configured.

Only after all four pass may `restore` evidence be recorded as PASS.

### 3. Record the drill

| Date (UTC) | Recovery point | Scope | Restored to | App starts | Schema OK | Data readable | `/api/ready` | Operator | Result |
|---|---|---|---|---|---|---|---|---|---|
| _(none yet)_ | — | — | — | — | — | — | — | — | **NEVER TESTED** |

Add a row per drill. A drill older than the interval your risk tolerance
allows should be treated as expired; re-run it rather than citing a stale row.

## Evidence format

The gate consumes JSON keyed by gate name. Both entries must carry the release
SHA so they bind to the release being decided:

```json
{
  "backup": {
    "status": "PASS",
    "release_sha": "<40-hex>",
    "detail": "PITR point 2026-08-10T12:00Z, project <ref>, 7d retention, owner <name>"
  },
  "restore": {
    "status": "PASS",
    "release_sha": "<40-hex>",
    "detail": "restored to scratch project; app started; RLS reads verified; /api/ready 200"
  }
}
```

Supplying `backup` without `restore` does **not** unblock the release: the gate
requires both, because a backup nobody has restored is an untested assumption.
