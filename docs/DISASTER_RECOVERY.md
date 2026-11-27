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

Before starting a drill, have all of these. Without them the drill stops
after the billed project has already been provisioned.

| Prerequisite | Why | Who has it |
|---|---|---|
| Supabase dashboard access to `mjpirkyduibkakvlbdko` | listing and selecting the recovery point | project owner |
| The production database password | step 3 opens one read-only connection to production as `postgres` | project owner |
| Authority to provision a billed project | *Restore to new project* creates one | project owner |
| The scratch project's database password, `service_role` key and `anon` key | schema, data and RLS validation | produced by the restore |
| `psql` (PostgreSQL client) and the Supabase CA certificate | both catalogue reads use verified TLS | anyone |
| Python 3.11+ as `python3`, with `requirements.txt` installed | the scripts in `scripts/` | anyone |
| A backend started against the scratch project | the application leg | release operator |

## 3. The drill, step by step

This is the only place the procedure is written down. Run every block from
the root of the candidate checkout, in one terminal session (zsh or Bash), in
the order given: later blocks use the variables earlier ones set. The blocks
contain no placeholders except where the text above a block says to replace a
value.

Required before any release containing a migration.

### Step 1 — Choose and record the recovery point

In the dashboard, *Database → Backups*, choose the newest completed backup.
Record it in the release's evidence file (`data/releases/evidence/<sha>.json`,
key `backup`): identifier / recovery point, timestamp (UTC), environment
(production project ref), scope (which schemas/tables; whether storage objects
are included), retention window, and owner (who can perform a restore).
Include `observed_at` — undated evidence is refused.

### Step 2 — Prepare the session and a private directory

Everything the capture writes stays in one directory outside the repository.
Replace the right-hand side of `RECOVERY_POINT` with the backup exactly as the
dashboard names it and of `RECOVERY_POINT_TIME` with the time the dashboard
shows for it, written in UTC as below, and choose a directory that does not
exist yet:

```bash
SOURCE_REF=mjpirkyduibkakvlbdko
RECOVERY_POINT='2026-11-27 07:31:02 UTC'
RECOVERY_POINT_TIME=2026-11-27T07:31:02Z
PRIVATE_DIR="$HOME/joinalab-restore-drill"
```

```bash
umask 077
mkdir "$PRIVATE_DIR"
SOURCE_PGPASSFILE="$PRIVATE_DIR/source.pgpass"
SCRATCH_PGPASSFILE="$PRIVATE_DIR/scratch.pgpass"
PGSSLROOTCERT_FILE="$PRIVATE_DIR/prod-ca-2021.crt"
```

Put two files into `$PRIVATE_DIR` by hand:

- `prod-ca-2021.crt`: the CA certificate the dashboard offers on the
  *Database Settings* page, section *SSL Configuration*
  ([Supabase SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement)).
  The same certificate verifies the scratch project.
- `source.pgpass`: one line, written in an editor (not with `echo`, which
  would leave the password in the shell history):
  `db.mjpirkyduibkakvlbdko.supabase.co:5432:postgres:postgres:<database password>`

The default connection is `db.<project-ref>.supabase.co:5432`, user
`postgres`. On an IPv4-only network that host cannot be reached: copy the
**Session pooler** host from the project's **Connect** dialog, append
`--session-pooler-host <that host>` to the command in step 3, and write the
password-file line as `<that host>:5432:postgres:postgres.<project-ref>:<password>`.
The same applies to the scratch project in step 7. See
[Supabase connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres).

### Step 3 — Capture the source project

One command, one read-only transaction against production (`BEGIN READ ONLY`,
20-second statement timeout). It can run any time after the backup and must
finish before the restore in step 5 is started.

```bash
PGPASSFILE="$SOURCE_PGPASSFILE" PGSSLROOTCERT="$PGSSLROOTCERT_FILE" \
  python3 -m scripts.restore_schema_evidence --project-ref "$SOURCE_REF" \
    --source-backup-id "$RECOVERY_POINT" --recovery-point-time "$RECOVERY_POINT_TIME" \
    --out "$PRIVATE_DIR/source-schema.json" \
    --storage-catalogue-out "$PRIVATE_DIR/catalogue.json"
```

It writes two owner-only files and refuses to start if either path is already
in use, so a second capture needs a new `PRIVATE_DIR`:

- `source-schema.json`, the receipt: digests and counts of application
  columns, applied migrations, and definitions of views, indexes, table
  constraints, user triggers, functions and procedures in the public and
  private schemas; relation RLS settings, policy definitions and roles; schema,
  relation, column and routine grants; triggers, policies and relation grants
  on `storage.objects` and `storage.buckets`; the public flag of each tracked
  bucket; and, for each of the 23 application tables, the row count and how
  many of those rows were written after the recovery point.
- `catalogue.json`: every object key and size in the private buckets. The
  receipt pins it through `storage_catalogue_sha256`.

Take the digest of the receipt now and write it down somewhere other than
`$PRIVATE_DIR`. The drill refuses a receipt whose digest differs, which is what
shows the file was not changed between the capture and the drill.

```bash
TRUSTED_SCHEMA_SHA256=$(shasum -a 256 "$PRIVATE_DIR/source-schema.json" | cut -d' ' -f1)
PINNED_STORAGE_CATALOGUE_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["storage_catalogue_sha256"])' "$PRIVATE_DIR/source-schema.json")
echo "$TRUSTED_SCHEMA_SHA256"
```

### Step 4 — Build the attachment inventory

Storage objects are not in the database backup, so their bytes come from a
separate copy laid out as `$ARCHIVE/<bucket>/<exact object key>`. An existing
empty bucket is an empty directory; `tracker-attachment-versions` has a
directory only if the catalogue lists that bucket.

```bash
ARCHIVE="$PRIVATE_DIR/archive"
```

```bash
python3 -m scripts.restore_storage_manifest --catalogue "$PRIVATE_DIR/catalogue.json" \
  --catalogue-sha256 "$PINNED_STORAGE_CATALOGUE_SHA256" --archive "$ARCHIVE" \
  --source-environment "$SOURCE_REF" --source-backup-id "$RECOVERY_POINT" \
  --out "$PRIVATE_DIR/storage-inventory.json"
TRUSTED_STORAGE_SHA256=$(shasum -a 256 "$PRIVATE_DIR/storage-inventory.json" | cut -d' ' -f1)
echo "$TRUSTED_STORAGE_SHA256"
```

The generator compares exact keys and sizes in each bucket with the catalogue
and streams every regular file through SHA-256. It rejects extra or missing
objects, symbolic links, missing sizes, public buckets and a version-bucket
presence mismatch, and walks the tree a second time to detect a change during
the scan. The inventory it writes looks like this one, which describes a single
3-byte object containing `abc`; `null` means the bucket did not exist at the
recovery point:

```json
{"version":2,"source_backup_id":"example-point","source_environment":"source-ref","buckets":{
  "tracker-attachments":[{"key":"example.pdf","size":3,"sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}],
  "application-materials":[], "tracker-attachment-versions":null}}
```

### Step 5 — Restore into a scratch project

Note the time, then use *Database → Backups → Restore to new project* on the
recorded point. It restores into a **separate**, newly provisioned project —
never over production, which is what makes it safe to drill — and that new
project is billed, so run it deliberately and delete it when the drill is done.

```bash
RESTORE_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

When the new project is ready, replace the value below with its project ref
(the `<ref>` in `https://<ref>.supabase.co`), and write `scratch.pgpass` in
`$PRIVATE_DIR` the same way as `source.pgpass`, with the scratch ref and the
scratch database password.

```bash
SCRATCH_REF=replace-with-the-new-project-ref
```

Then upload every file under `$ARCHIVE` into the scratch project's bucket of
the same name, under the same key, with the Storage page of the **scratch**
dashboard; check the project ref in the address bar before any upload. A
bucket the inventory records as `null` must not exist on scratch.

### Step 6 — Start a backend against the scratch project

In a second terminal, from the same checkout, with the scratch ref in place of
the value shown:

```bash
SUPABASE_URL="https://replace-with-the-new-project-ref.supabase.co" \
  python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Back in the first terminal:

```bash
SCRATCH_BACKEND_URL=http://127.0.0.1:8000
```

### Step 7 — Run the drill

Run this block in Bash and enter the scratch keys (*Project Settings → API* in
the scratch dashboard) at the hidden prompts:

```bash
export DRILL_SUPABASE_URL="https://${SCRATCH_REF}.supabase.co"
read -rs -p "Scratch service-role key: " DRILL_SERVICE_ROLE_KEY && echo
read -rs -p "Scratch anon key: " DRILL_ANON_KEY && echo
export DRILL_SERVICE_ROLE_KEY DRILL_ANON_KEY
PGPASSFILE="$SCRATCH_PGPASSFILE" PGSSLROOTCERT="$PGSSLROOTCERT_FILE" \
  python3 scripts/restore_drill.py \
    --source-backup-id "$RECOVERY_POINT" \
    --source-environment "$SOURCE_REF" \
    --scratch-environment "$SCRATCH_REF" \
    --restore-started-at "$RESTORE_STARTED_AT" \
    --source-schema-manifest "$PRIVATE_DIR/source-schema.json" \
    --source-schema-manifest-sha256 "$TRUSTED_SCHEMA_SHA256" \
    --attachment-manifest "$PRIVATE_DIR/storage-inventory.json" \
    --attachment-manifest-sha256 "$TRUSTED_STORAGE_SHA256" \
    --api-base "$SCRATCH_BACKEND_URL"
unset DRILL_SERVICE_ROLE_KEY DRILL_ANON_KEY
```

For an IPv4-only connection, add
`--session-pooler-host <scratch session pooler host>` before `--api-base`.

The command writes
`data/releases/drills/<drill_id>.json` — which `release_gate.py` reads clause
by clause. That file is the deliverable; the markdown row in §4 is a human
index of it, not the evidence itself.

1. **Schema**: every required table is reachable. The drill compares independently observed public/private columns, application DDL and applied migrations across the source and scratch projects, and checks the applied identities against the candidate filenames.
2. **Data**: each of the 23 required application tables must hold, on scratch,
   every row the source says existed at the recovery point. The capture reads
   the live project hours after the nightly backup, so its totals include rows
   the backup cannot contain. It therefore counts each table twice: all rows,
   and the rows stamped later than 15 minutes before `RECOVERY_POINT_TIME` (the
   dashboard shows one time for a backup that takes minutes to complete). The
   restored table must hold at least the first number minus the second.
   Five tables only grow: `analytics_events`, `usage_events`,
   `feedback_events`, `ops_incident_events` and `profile_versions`. The
   application inserts into them and has no way to delete from them, so a
   restore must also never hold more of their rows than the capture counted.
   Every other table loses rows in normal use as well (a favourite removed, two
   devices merged), so its restore may hold more. A visitor's page view or a
   new favourite between the backup and the capture does not fail this step;
   an empty or short table does, and the drill prints the three numbers it saw.
   What totals cannot show: which rows are present, and a table that lost rows
   in the restore while at least as many were deleted on the live site since
   the backup. The stamps of `interactions`, `match_feedback` and
   `professor_update_reads` come from the student's browser clock. A receipt
   without source counts leaves data recovery unverified.
3. **RLS**: an anonymous caller sees no user-owned rows. This is the leg a
   service-role-only check cannot make — a restore that brings back the tables
   but not their policies reads perfectly well to an admin probe while exposing
   every student's rows to the internet.
4. **Application**: the restored data plane answers, and with `--api-base`,
   `/api/ready` returns 200 against it.
5. **Attachment bytes**: every scratch bucket must match the complete
   inventory. Every expected object must have the same length and SHA-256
   after download. The public drill record contains aggregate counts and a
   receipt digest. If either receipt is missing, the affected evidence is
   unverified and the drill cannot pass.

Without `--api-base` the application leg records `PARTIAL`, not `PASS`, and the
drill's `final_result` is `FAIL` — deliberately. A drill that did not boot the
application did not prove the application recovers.

### Step 8 — Record and tear down

Commit the drill record and add its row to §4. Stop the backend from step 6.
Delete the scratch project: it is billed, and a forgotten one is both a
standing cost and a second copy of production data. Then delete
`source.pgpass` and `scratch.pgpass`; keep the rest of `$PRIVATE_DIR`, which
is the private half of the evidence.

### Failure handling

A drill that finds problems is the most valuable kind. Its record is written
either way, and must be committed either way.

| What failed | What it means | Next |
|---|---|---|
| `schema_validation` | the restore did not bring back the full schema | do not release; treat the backup as unproven and escalate to Supabase |
| `attachment_validation` | private objects differ or verification is incomplete | check the storage copy and rerun in scratch |
| `data_validation` | the lines starting `! data:` say which: a table holds fewer rows than existed at the recovery point (the line gives the restored count, the source count, how many of those may be later than the backup, and how many are missing), or a table that only grows holds more rows than the later capture counted, or scratch gave no count for a table | fewer rows: check that `RECOVERY_POINT_TIME` is the time of the backup that was actually restored; if it is, the backup lacks data that production had, so treat it as unproven and escalate to Supabase. More rows in a table that only grows: the restored backup is newer than the capture, or it is another project's. No count: the scratch service-role key or the table is missing |
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
