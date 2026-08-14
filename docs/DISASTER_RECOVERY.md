# Disaster recovery: backup and restore

> **Current status: backups exist and are recorded; recovery is still
> UNVERIFIED — that half is the release blocker.**
>
> ```
> backup exists  !=  recovery verified
> ```
>
> `scripts/release_gate.py` now reports `backup` as PASS against the recovery
> point recorded below, and `restore` as `UNVERIFIED`, which keeps the release
> at NO-GO on its own. That is the correct state until the drill in §2 is
> performed and its result recorded in §3.

## What exists today

Checked in the Supabase dashboard on 2026-08-14. Earlier revisions of this
document said no backup existed anywhere; that was true of the repository and
false of the project, which is exactly the gap this section now closes.

- **Daily physical backups, on the Pro plan.** Project
  `mjpirkyduibkakvlbdko`, seven retained (2026-08-07 .. 2026-08-13), each
  `PHYSICAL` / `COMPLETED`, taken around 07:2x–07:3x UTC. Nothing in this
  repository creates them and nothing here would notice if they stopped.
- **Point-in-time recovery is NOT enabled.** It is a paid add-on and the
  dashboard offers it rather than showing a window. Consequences that follow
  from that, not from anything in this repo: recovery granularity is one day,
  so the worst-case RPO is ~24h, and a bad migration applied at 09:00 UTC
  costs everything written since ~07:30 UTC.
- **Storage objects are excluded** from database backups — the database holds
  only their metadata. Today that is one 21.9 KB object in the private
  `tracker-attachments` bucket (migration 008), so the exposure is small, but
  it grows with every attachment a student uploads and nothing else covers it.
- **Restore has a first-class path**: the dashboard's *Restore to new project*
  (BETA) restores any of the seven points into a **separate** project, which is
  precisely the non-destructive drill §2 requires. It provisions a new billed
  project, so it is the owner's call to run rather than a routine action.
- **No restore has ever been performed.** See §3 — the table is still empty.
- Application-level recovery is separately incomplete: whole-document
  renovation snapshots are retained but have no restore UI.

Because migrations are forward-only and three are non-idempotent (see
`docs/RELEASE.md` §4), a restore is the *only* recovery path for a bad
migration. That makes this gate load-bearing rather than a formality.

## Required before any release containing a migration

### 1. Establish and record the backup

Record the recovery point in the release's evidence file
(`data/releases/evidence/<sha>.json`, key `backup`), from the Supabase
dashboard: identifier / recovery point, timestamp (UTC), environment
(production project ref), scope (which schemas/tables; whether storage objects
are included), retention window, and owner (who can perform a restore).

Done for f089a580: recovery point **2026-08-13T07:30:41Z**, PHYSICAL,
COMPLETED, project `mjpirkyduibkakvlbdko`, 7-day rolling retention, database
only (no Storage objects), owner Guoyi (Eric) Xu.

### 2. Prove recovery, do not assume it

Use *Database → Backups → Restore to new project* on the recorded point. It
restores into a **separate**, newly provisioned project — never over
production, which is what makes it safe to drill — and that new project is
billed, so run it deliberately and delete it when the drill is done. Verify all
four:

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
