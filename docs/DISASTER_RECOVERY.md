# Disaster recovery: backup and restore

> **Current status: backups exist; recovery is still UNVERIFIED, and the
> recorded recovery point has aged out of retention. Both are release
> blockers.**
>
> ```
> backup exists  !=  recovery verified
> ```
>
> `scripts/release_gate.py` reports `restore_drill` as **`BLOCKED`** with reason
> `scratch_project_access_required`, which keeps the release at NO-GO on its
> own. `BLOCKED` rather than `UNVERIFIED` on purpose: this is not evidence
> nobody has got around to gathering, it is evidence nobody *can* gather until
> a scratch project exists. The two need different people on different days.
>
> ```
> status:              BLOCKED
> owner:               project owner
> reason:              scratch Supabase project / management access required
> recommended_action:  provision an isolated scratch project and authorize the
>                      restore drill in §3
> ```
>
> A drill was attempted on 2026-09-04 and could not be started. What blocked it
> is recorded in §5 — the blocker is access, not procedure.

## 1. What exists today

Checked in the Supabase dashboard on 2026-08-14. Earlier revisions of this
document said no backup existed anywhere; that was true of the repository and
false of the project, which is exactly the gap this section closed.

- **Daily physical backups, on the Pro plan.** Project
  `mjpirkyduibkakvlbdko`, seven retained, each `PHYSICAL` / `COMPLETED`, taken
  around 07:2x–07:3x UTC. Nothing in this repository creates them and nothing
  here would notice if they stopped.
- **Point-in-time recovery is NOT enabled.** It is a paid add-on and the
  dashboard offers it rather than showing a window. Consequences that follow
  from that, not from anything in this repo: recovery granularity is one day,
  so the worst-case RPO is ~24h, and a bad migration applied at 09:00 UTC
  costs everything written since ~07:30 UTC.
- **Storage objects are excluded** from database backups — the database holds
  only their metadata. The drill checks the private Tracker, versioned Tracker
  and application-material buckets against an independent storage backup inventory.
- **Restore has a first-class path**: the dashboard's *Restore to new project*
  (BETA) restores any retained point into a **separate** project, which is
  precisely the non-destructive drill §3 requires. It provisions a new billed
  project, so it is the owner's call to run rather than a routine action.
- **No restore has ever been performed.** See §4 — the table is still empty.
- Application-level recovery is separately incomplete: whole-document
  renovation snapshots are retained but have no restore UI.

Because migrations are forward-only and three are non-idempotent (see
`docs/RELEASE.md` §4), a restore is the *only* recovery path for a bad
migration. That makes this gate load-bearing rather than a formality.

### The retention window is part of the evidence

Backup evidence expires at the retention window, not at someone's convenience.
`scripts/release_gate.py` gives the `backup` gate a 7-day maximum evidence age
for exactly that reason: a recovery point older than the rolling window is not
a worse recovery option, it is **not a recovery option at all** — it no longer
exists.

The recovery point recorded for release `f089a580` (**2026-08-13T07:30:41Z**)
has aged out. Re-record the current point rather than citing that one.

## 2. Prerequisites

Before starting a drill, have all of these. Without them the drill fails at
step 3, after the billed project has already been provisioned.

| Prerequisite | Why | Who has it |
|---|---|---|
| Supabase dashboard access to `mjpirkyduibkakvlbdko` | listing and selecting the recovery point | project owner |
| Authority to provision a billed project | *Restore to new project* creates one | project owner |
| The scratch project's `service_role` key | schema + data validation | produced by the restore |
| The scratch project's `anon` key | the RLS leg — the one a service-role probe cannot make | produced by the restore |
| Python 3.11+ with `requirements.txt` installed | `scripts/restore_drill.py` | anyone |
| A backend pointed at the scratch project | proves the application leg | release operator |
| Backup-bound catalogue capture and private storage inventory, with their SHA-256 digests retained independently | identifies what a full restore must contain | backup owner |
| `psql`, TLS root certificate and read access to the scratch database catalogue | observes restored columns and applied migrations | release operator |

The drill takes scratch credentials. The backup owner supplies the separately captured source evidence.

## 3. Required before any release containing a migration

### Step 1 — Establish and record the backup

Record the recovery point in the release's evidence file
(`data/releases/evidence/<sha>.json`, key `backup`) from the Supabase
dashboard: identifier / recovery point, timestamp (UTC), environment
(production project ref), scope (which schemas/tables; whether storage objects
are included), retention window, and owner (who can perform a restore). Include
`observed_at` — undated evidence is refused.

At the recovery point, the backup owner captures the source schema while the
public and private application schemas and migration history are frozen across the backup and capture.
Run from the candidate checkout. Use a project-specific password file (mode
0600) and a trusted CA certificate for the endpoint. The default connection is
`db.<project-ref>.supabase.co:5432`, user `postgres`. On an IPv4-only network,
copy the **Session pooler** host from the project's Supabase **Connect** dialog
and pass `--session-pooler-host "$SOURCE_POOLER_HOST"` to the capture. The
pooler password-file entry uses that host, port 5432, database `postgres`, and
user `postgres.<project-ref>`. Use the scratch project's corresponding host
and password-file entry for step 3. See [Supabase connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres).

```bash
PGPASSFILE="$SOURCE_PGPASSFILE" PGSSLROOTCERT="$SOURCE_PGSSLROOTCERT" \
  python -m scripts.restore_schema_evidence --project-ref "$SOURCE_REF" \
    --source-backup-id "$RECOVERY_POINT" --out "$PRIVATE_DIR/source-schema.json"
```

Retain the SHA-256 of the capture file with the backup receipt. The capture
compares application columns, applied migrations, and definitions of views, indexes, table
constraints, user triggers, functions and procedures in the public and private
schemas. PostgreSQL computes the DDL digest on the server in the same read-only
statement. The capture stores counts, hashes, recovery point, project ref and
timestamp. RLS behavior has a separate test. Backups with a missing capture or
an earlier columns-only receipt remain `UNVERIFIED` for schema equivalence.

The separate storage backup must supply its full private inventory and a
SHA-256 retained with the backup receipt. Each bucket contains a list of
objects. Each object has a key, byte length and lowercase SHA-256 of the
backed-up bytes. For example, this inventory describes one 3-byte synthetic
object containing `abc`. Include every object in `tracker-attachment-versions`
when that bucket existed at the recovery point. An existing empty bucket has
an empty list. For a pre-rollout backup, use JSON `null` only when the independent
source bucket catalogue confirms the bucket was absent. The drill then checks
the complete scratch bucket catalogue. Two-bucket historical receipts remain
readable and need this additional evidence to clear the current gate.

```json
{"version":2,"source_backup_id":"example-point","source_environment":"source-ref","buckets":{
  "tracker-attachments":[{"key":"example.pdf","size":3,"sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}],
  "application-materials":[], "tracker-attachment-versions":null}}
```

Keep the inventory and both backup receipts private. Restore the storage
backup into the scratch project before running step 3.

### Step 2 — Restore into a scratch project

*Database → Backups → Restore to new project*, on the recorded point. It
restores into a **separate**, newly provisioned project — never over
production, which is what makes it safe to drill — and that new project is
billed, so run it deliberately and delete it when the drill is done.

Record the actual restore start as an ISO 8601 timestamp including its timezone (for example, `2026-11-25T18:00:00Z`). Set `RESTORE_STARTED_AT` to this timestamp.

### Step 3 — Prove recovery, do not assume it

Set `SCRATCH_REF` and `SCRATCH_BACKEND_URL` for the restored project. Run the
following block in Bash and enter the scratch keys at the hidden prompts:

```bash
export DRILL_SUPABASE_URL="https://${SCRATCH_REF}.supabase.co"
read -rs -p "Scratch service-role key: " DRILL_SERVICE_ROLE_KEY && echo
read -rs -p "Scratch anon key: " DRILL_ANON_KEY && echo
export DRILL_SERVICE_ROLE_KEY DRILL_ANON_KEY
export PGPASSFILE="$SCRATCH_PGPASSFILE" PGSSLROOTCERT="$SCRATCH_PGSSLROOTCERT"

python scripts/restore_drill.py \
    --source-backup-id "$RECOVERY_POINT" \
    --source-environment mjpirkyduibkakvlbdko \
    --scratch-environment "$SCRATCH_REF" \
    --restore-started-at "$RESTORE_STARTED_AT" \
    --source-schema-manifest "$PRIVATE_DIR/source-schema.json" \
    --source-schema-manifest-sha256 "$TRUSTED_SCHEMA_SHA256" \
    --attachment-manifest "$PRIVATE_DIR/storage-inventory.json" \
    --attachment-manifest-sha256 "$TRUSTED_STORAGE_SHA256" \
    --api-base "$SCRATCH_BACKEND_URL"
```

For an IPv4-only connection, append
`--session-pooler-host "$SCRATCH_POOLER_HOST"` to the drill command. Unset
`DRILL_SERVICE_ROLE_KEY` and `DRILL_ANON_KEY` after recording the result.

The command writes
`data/releases/drills/<drill_id>.json` — which `release_gate.py` reads clause
by clause. That file is the deliverable; the markdown row in §4 is a human
index of it, not the evidence itself.

1. **Schema**: every required table is reachable. The drill compares independently observed public/private columns, application DDL and applied migrations across the source and scratch projects, and checks the applied identities against the candidate filenames.
2. **Data**: representative user-owned tables came back populated. An empty
   restore satisfies every schema check and none of the point of one.
3. **RLS**: an anonymous caller sees no user-owned rows. This is the leg a
   service-role-only check cannot make — a restore that brings back the tables
   but not their policies reads perfectly well to an admin probe while exposing
   every student's rows to the internet.
4. **Application**: the restored data plane answers, and with `--api-base`,
   `/api/ready` returns 200 against it.
5. **Attachment bytes**: both scratch buckets must match the complete backup
   inventory. Every expected object must have the same length and SHA-256
   after download. The public drill record contains aggregate counts and a
   receipt digest. If either receipt is missing, the affected evidence is
   unverified and the drill cannot pass.

Without `--api-base` the application leg records `PARTIAL`, not `PASS`, and the
drill's `final_result` is `FAIL` — deliberately. A drill that did not boot the
application did not prove the application recovers.

Historical drill records remain readable. Their former pair of checkout fingerprints cannot establish either database observation. A fresh drill can supply the missing evidence.

### Step 4 — Record and tear down

Commit the drill record. Then delete the scratch project: it is billed, and a
forgotten one is both a standing cost and a second copy of production data.

### Failure handling

A drill that finds problems is the most valuable kind. Its record is written
either way, and must be committed either way.

| What failed | What it means | Next |
|---|---|---|
| `schema_validation` | the restore did not bring back the full schema | do not release; treat the backup as unproven and escalate to Supabase |
| `attachment_validation` | private objects differ or verification is incomplete | check the independent storage backup and rerun in scratch |
| `data_validation` | tables restored empty | wrong recovery point, or the backup is not capturing data — re-run against another point before drawing conclusions |
| `rls_validation` | policies did not survive the restore | **the most serious outcome**: recovery would expose user data. Release stays NO-GO until the procedure includes reapplying policies, verified by a re-run |
| `application_smoke` | app cannot run against the restored database | recovery is incomplete even though the data is intact; find the missing piece (env, extension, role) and document it here |

## 4. The drill log

| Date (UTC) | Recovery point | Scope | Restored to | Schema | Data | RLS | App | Operator | Result |
|---|---|---|---|---|---|---|---|---|---|
| _(none yet)_ | — | — | — | — | — | — | — | — | **NEVER TESTED** |

Add a row per drill, alongside its `data/releases/drills/<drill_id>.json`. The
gate treats a drill older than 180 days as expired, and re-checks the migration
set it restored against the candidate's — migrations are forward-only, so a
drill taken before new ones landed is not evidence about today's recovery
target.

## 5. Attempted 2026-09-04 — CANNOT VERIFY

Recorded because "never attempted" and "attempted and blocked" are different
facts, and only the second one names what to fix.

| Checked | Result |
|---|---|
| `https://api.supabase.com/v1/projects` | HTTP 401 — no management token available |
| `https://mjpirkyduibkakvlbdko.supabase.co/rest/v1/` | HTTP 401 |
| `https://mjpirkyduibkakvlbdko.supabase.co/auth/v1/health` | HTTP 401 |
| Supabase credentials in the environment | none present |
| `psql` / `pg_restore` / `pg_dump` | not installed |
| `docker` / `podman` / `colima` | not installed |
| Existing scratch or staging project | none — `docs/release_gate_report.md` records "no staging" |

**Conclusion: `BLOCKED`; the release stays `NO-GO`.** The blocker is access
and billing authority, both of which sit with the project owner. The procedure
above is executable and its tooling is committed and tested. Nothing here can
be worked around from inside the repository, and it must not be: a drill record
written without a restore would make the one gate that has never lied start
lying.

The fixture that proves the gate's PASS path is reachable is **not** release
evidence and is deliberately not committed — `data/releases/drills/` holds only
its README. A drill record counts only when a real restore produced it.

**To clear it:** the project owner runs §3 against a scratch project. Expected
cost is one restored project for the duration of the drill.

## 6. Evidence format

The gate consumes two separate things, and they are not interchangeable.

`data/releases/drills/<drill_id>.json` is written by
`scripts/restore_drill.py` and read by the `restore_drill` gate. It is the
proof of recovery capability, and it is not release-specific.

`data/releases/evidence/<sha>.json` is the operator's per-release evidence
file, and carries the `backup` recovery point plus the `restore` attestation
for this specific release:

```json
{
  "backup": {
    "status": "PASS",
    "release_sha": "<40-hex>",
    "observed_at": "<when the dashboard was read, ISO-8601 UTC>",
    "detail": "recovery point <id> <timestamp>, project <ref>, 7d retention, owner <name>"
  },
  "restore": {
    "status": "PASS",
    "release_sha": "<40-hex>",
    "observed_at": "<when the drill ran>",
    "detail": "drill <drill_id>: restored <backup id> into <scratch ref>; schema, data, RLS and /api/ready verified"
  }
}
```

Supplying `backup` without a drill does **not** unblock the release: the gate
requires the drill record too, because a backup nobody has restored is an
untested assumption. Both entries must carry `observed_at`, and both must carry
the release SHA so they bind to the release being decided.

## 7. Ownership and production recovery decision points

| Decision | Owner | Trigger |
|---|---|---|
| Run a drill | project owner | before any release containing a migration; whenever the last drill is >180d old |
| Declare a production incident recoverable only by restore | release operator + project owner | a bad migration, or data loss confirmed beyond a forward fix |
| Choose the recovery point | project owner | at incident time; granularity is one day, so the choice is which day's ~07:30 UTC snapshot |
| Accept the RPO | project owner | implicit in every release while PITR is off — worst case ~24h of writes |
| Restore over production | project owner **only** | never as part of a drill; only in a declared incident |
| Enable PITR | project owner | when ~24h of writes stops being an acceptable loss |

Production recovery is never automated and never delegated to CI. Every path
above ends at the project owner, because every one of them provisions billing,
destroys data, or both.
