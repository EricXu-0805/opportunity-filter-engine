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
| The production database password | step 3 opens one read-only connection to production as `postgres`; typed at a hidden prompt | project owner |
| Authority to provision a billed project | *Restore to new project* creates one | project owner |
| The scratch project's database password, `service_role` key and `anon` key | schema, data and RLS validation; typed at hidden prompts | produced by the restore |
| `psql` (PostgreSQL client) and the Supabase CA certificate | both catalogue reads use verified TLS | anyone |
| Python 3.11+ as `python3` with `requirements.txt` installed, in both terminals: the project's virtual environment (step 2 checks it) | the scripts in `scripts/` and the backend of step 6 | anyone |
| A backend started against the scratch project | the application leg | release operator |

## 3. The drill, step by step

This is the only place the procedure is written down. Run every block from
the root of the candidate checkout, in one terminal session (zsh or Bash), in
the order given: later blocks use the variables earlier ones set. The two
blocks that start the backend (steps 2 and 6) go into a second terminal, as
the text above them says. The blocks contain no placeholders except where the
text above a block says to replace a value.

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
exist yet. Do not leave the example time in place: rows stamped after
`RECOVERY_POINT_TIME` are not required of the restore, so a time earlier than
the backup's own lets a restore that lacks those rows pass. The capture
refuses a time more than 26 hours before it runs, because step 1 chooses the
newest daily backup and that one is never much more than a day old. Inside
those 26 hours it cannot tell a wrong time from the right one, so read the
time off the dashboard row you will restore. To drill an older backup on
purpose, add `--older-backup` to the command in step 3: a time up to 8 days
old is then accepted (no retained backup is older), and the capture prints a
`WARNING recovery point:` line with how many of the rows it counted will not
be required of the restore.

```bash
SOURCE_REF=mjpirkyduibkakvlbdko
RECOVERY_POINT='2026-11-27 07:31:02 UTC'
RECOVERY_POINT_TIME=2026-11-27T07:31:02Z
PRIVATE_DIR="$HOME/joinalab-restore-drill"
```

```bash
umask 077
mkdir "$PRIVATE_DIR"
export PGSSLROOTCERT="$PRIVATE_DIR/prod-ca-2021.crt"
```

Save one file into `$PRIVATE_DIR` by hand: `prod-ca-2021.crt`, the CA
certificate the dashboard offers on the *Database Settings* page, section
*SSL Configuration*
([Supabase SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement)).
The same certificate verifies the scratch project.

**Passwords and keys.** Never put one on a command line, in an `export`, or in
a file for this procedure: the shell history and the process list keep what
is typed there. Each command below asks for the credential it needs at a
prompt that does not echo, reads it from nowhere else (the old
`DRILL_SERVICE_ROLE_KEY` and `DRILL_ANON_KEY` variables are ignored), and
replaces it with `[redacted]` if a server's reply or a library's error message
ever carries it back into a record or onto the screen. Nothing shows at such a
prompt while you type or paste: paste once and press Enter, and do not try to
correct the line with an arrow or Ctrl key. If one was pressed, the command
says so, uses nothing of that input and asks again.
The commands work the same in zsh and Bash.
If no terminal can hide the input (a pipe, a scheduled job), they stop instead
of reading it. The one exception is the database password: when `PGPASSWORD`
or `PGPASSFILE` is already set in the shell, the commands use it without
asking and say so in one line (`... database password: not asked for,
PGPASSWORD is set in this shell`). `PGPASSWORD` holds one password, which is
then sent to production in step 3 and to the scratch project in step 7. If
either variable is left over from other work, `unset` it first.

The default connection is `db.<project-ref>.supabase.co:5432`, user
`postgres`. On an IPv4-only network that host cannot be reached: copy the
**Session pooler** host from the project's **Connect** dialog and append
`--session-pooler-host <that host>` to the command in step 3. The same
applies to the scratch project in step 7. See
[Supabase connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres).

**The interpreter, checked before anything is paid for.** `python3` must be
the interpreter that has `requirements.txt` installed, in this terminal and in
the second one that runs the backend: the project's virtual environment. A
login shell's own `python3` (Homebrew's, or the system's) can run the capture
and the drill and still lack a package the backend imports, and that would
show only in step 6, after the billed restore. Activate the environment in
both terminals, from the root of the checkout (if yours lives elsewhere, use
its path):

```bash
source .venv/bin/activate
```

Then, in the second terminal, start the backend exactly as step 6 will, here
with an address that belongs to no project:

```bash
SUPABASE_URL="https://not-restored-yet.invalid" SUPABASE_SERVICE_ROLE_KEY= \
  python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Wait for its log line `Application startup complete` (about a minute), then
ask it, from the first terminal, what the drill will ask in step 7:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/ready
```

It must print `200`. `/api/ready` reports the backend's own state and does not
query the database, so this needs no scratch project. If the backend stopped
with `ModuleNotFoundError`, this `python3` is not the virtual environment's.
If the check prints `503`, `curl -s http://127.0.0.1:8000/api/ready` shows the
`reasons`, which the `application_smoke` row under "Failure handling" explains.
Put it right now, then stop this backend with Ctrl-C; step 6 starts it again
against the scratch project.

### Step 3 — Capture the source project

One command, one read-only transaction against production (`BEGIN READ ONLY`,
20-second statement timeout). It can run any time after the backup and must
finish before the restore in step 5 is started. It asks for production's
database password at a hidden prompt.

```bash
python3 -m scripts.restore_schema_evidence --project-ref "$SOURCE_REF" \
  --source-backup-id "$RECOVERY_POINT" --recovery-point-time "$RECOVERY_POINT_TIME" \
  --out "$PRIVATE_DIR/source-schema.json" \
  --row-counts-out "$PRIVATE_DIR/source-rows.json" \
  --storage-catalogue-out "$PRIVATE_DIR/catalogue.json"
```

Read what it prints before going on; the restore in step 5 is the first thing
that costs money.

- A line starting `WARNING migrations:` means production's migration ledger
  and this checkout differ (on 2026-11-25 production did not have
  `20261125130000_guard_tracker_attachment_replacement.sql`). The drill can
  still pass: it shows that the restore reproduces production. It then lists
  this checkout's migrations under "not covered", and the release gate answers
  `schema_state_advanced` until the migration is applied and a new drill is run.
  Decide now whether to apply the migration first.
- `Schema observation unavailable: the recovery point time is ...` means
  `RECOVERY_POINT_TIME` is more than 26 hours before now (or more than 8 days,
  with `--older-backup`). Production was not contacted and nothing was
  written. Set the variable to the time of the backup you will restore and run
  the command again.
- `Schema observation unavailable: the private Storage catalogue cannot be
  captured: ...` names the bucket that is missing, public, or holds objects
  without a recorded size. Nothing was written. For a database-only drill run
  the command again without the `--storage-catalogue-out` line.

It writes three owner-only files and refuses to start if any of the paths is
already in use, so a second capture needs a new `PRIVATE_DIR`:

- `source-schema.json`, the receipt: digests and counts of application
  columns, applied migrations, and definitions of views, indexes, table
  constraints, user triggers, functions and procedures in the public and
  private schemas; relation RLS settings, policy definitions and roles; schema,
  relation, column and routine grants; triggers, policies and relation grants
  on `storage.objects` and `storage.buckets`; and the public flag of each
  tracked bucket. It holds digests only, because the drill copies it into the
  record that is committed.
- `source-rows.json`: for each of the 23 application tables, the row count and
  how many of those rows were written after the recovery point. The receipt
  pins it through `row_evidence_sha256`.
- `catalogue.json`: every object key and size in the private buckets. The
  receipt pins it through `storage_catalogue_sha256`.

Take the digest of the receipt now (the capture printed the same value as
`receipt_sha256`) and write it down somewhere other than `$PRIVATE_DIR`. The
drill refuses a receipt whose digest differs, which is what shows the file was
not changed between the capture and the drill.

```bash
TRUSTED_SCHEMA_SHA256=$(shasum -a 256 "$PRIVATE_DIR/source-schema.json" | cut -d' ' -f1)
echo "$TRUSTED_SCHEMA_SHA256"
```

### Step 4 — Attachments: leave them out, or copy them

A restored project has the database rows that describe each stored file and
none of the files
([what a restore carries over](https://supabase.com/docs/guides/platform/clone-project)).
Choose one of the two paths and keep to it in steps 5 and 7.

**Database only.** Run nothing here. In step 7 the drill is told
`--attachments-out-of-scope`; it then reads no storage object, records
`attachment_validation: NOT_COVERED`, and can end `PASS` for the database with
attachment bytes listed under "not covered". The release gate reports such a
drill as `attachments_not_covered`: recovery of the files stays unproven until
a drill takes the other path. Use this for a first drill.

**With attachments.** One command reads every object the catalogue lists from
production's Storage (one GET each, nothing else), writes them under
`$ARCHIVE/<bucket>/<exact object key>`, and builds the inventory. It asks for
production's `service_role` key at a hidden prompt.

```bash
ARCHIVE="$PRIVATE_DIR/archive"
PINNED_STORAGE_CATALOGUE_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["storage_catalogue_sha256"])' "$PRIVATE_DIR/source-schema.json")
```

```bash
python3 -m scripts.restore_storage_manifest --download --catalogue "$PRIVATE_DIR/catalogue.json" \
  --catalogue-sha256 "$PINNED_STORAGE_CATALOGUE_SHA256" --archive "$ARCHIVE" \
  --source-environment "$SOURCE_REF" --source-backup-id "$RECOVERY_POINT" \
  --out "$PRIVATE_DIR/storage-inventory.json"
```

```bash
TRUSTED_STORAGE_SHA256=$(shasum -a 256 "$PRIVATE_DIR/storage-inventory.json" | cut -d' ' -f1)
echo "$TRUSTED_STORAGE_SHA256"
```

Run it straight after step 3: the catalogue lists the files as they were at
the capture, and a file changed or removed since makes the command stop. If
you already hold an independent copy of the buckets, lay it out as
`$ARCHIVE/<bucket>/<exact object key>` yourself (an empty bucket is an empty
directory) and run the same command without `--download`.

The command compares exact keys and sizes in each bucket with the catalogue
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

Go on only when the check at the end of step 2 has printed `200`. Note the
time, then use *Database → Backups → Restore to new project* on the
recorded point. It restores into a **separate**, newly provisioned project —
never over production, which is what makes it safe to drill — and that new
project is billed, so run it deliberately and delete it when the drill is done.
The Backups page also offers to restore a backup onto the project it was taken
from. On production that replaces the live database with the backup, and it is
not part of this procedure: if what you are about to confirm does not say that
it creates a new project, cancel it.

```bash
RESTORE_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

When the new project is ready, replace the value below with its project ref
(the `<ref>` in `https://<ref>.supabase.co`). Have its database password and,
from *Project Settings → API*, its `service_role` and `anon` keys ready to
paste at the prompts in step 7; a restored project has keys of its own.

```bash
SCRATCH_REF=replace-with-the-new-project-ref
```

On the path with attachments, put the files into the scratch project now. The
command checks every archived file against the inventory, refuses a target
equal to `SOURCE_REF`, then asks for the **scratch** project's `service_role`
key at a hidden prompt and uploads each file over the metadata row the restore
brought back (`x-upsert`, the same call
[Supabase's own storage migration](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore#migrating-storage-objects)
uses). It is the only command in this procedure that writes to a project. It
uploads bytes only: content types are not restored.

```bash
python3 -m scripts.restore_storage_load --attachment-manifest "$PRIVATE_DIR/storage-inventory.json" \
  --attachment-manifest-sha256 "$TRUSTED_STORAGE_SHA256" --archive "$ARCHIVE" \
  --source-environment "$SOURCE_REF" --source-backup-id "$RECOVERY_POINT" \
  --scratch-environment "$SCRATCH_REF"
```

### Step 6 — Start a backend against the scratch project

In the second terminal (the one from step 2, virtual environment active), from
the same checkout, with the scratch ref in place of the value shown:

```bash
SUPABASE_URL="https://replace-with-the-new-project-ref.supabase.co" SUPABASE_SERVICE_ROLE_KEY= \
  python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Keep the empty `SUPABASE_SERVICE_ROLE_KEY=`. The backend fills every variable
the command line leaves unset from `backend/.env` and `.env`, which on a
development machine hold production's `service_role` key; with that key and
the scratch address, its attachment clean-up task would send production's key
to the scratch project once a minute. `/api/ready` does not need the key, and
with it empty the task does not start.

Wait for its log line `Application startup complete`, then, back in the first
terminal:

```bash
SCRATCH_BACKEND_URL=http://127.0.0.1:8000
curl -s -o /dev/null -w '%{http_code}\n' "$SCRATCH_BACKEND_URL/api/ready"
```

It must print `200` again before step 7.

### Step 7 — Run the drill

The drill asks for three things at hidden prompts, in this order: the scratch
database password, the scratch `service_role` key and the scratch `anon` key.
Run the one command for the path chosen in step 4.

Database only:

```bash
python3 scripts/restore_drill.py \
  --source-backup-id "$RECOVERY_POINT" \
  --source-environment "$SOURCE_REF" \
  --scratch-environment "$SCRATCH_REF" \
  --restore-started-at "$RESTORE_STARTED_AT" \
  --source-schema-manifest "$PRIVATE_DIR/source-schema.json" \
  --source-schema-manifest-sha256 "$TRUSTED_SCHEMA_SHA256" \
  --source-row-counts "$PRIVATE_DIR/source-rows.json" \
  --attachments-out-of-scope \
  --api-base "$SCRATCH_BACKEND_URL"
```

With attachments:

```bash
python3 scripts/restore_drill.py \
  --source-backup-id "$RECOVERY_POINT" \
  --source-environment "$SOURCE_REF" \
  --scratch-environment "$SCRATCH_REF" \
  --restore-started-at "$RESTORE_STARTED_AT" \
  --source-schema-manifest "$PRIVATE_DIR/source-schema.json" \
  --source-schema-manifest-sha256 "$TRUSTED_SCHEMA_SHA256" \
  --source-row-counts "$PRIVATE_DIR/source-rows.json" \
  --attachment-manifest "$PRIVATE_DIR/storage-inventory.json" \
  --attachment-manifest-sha256 "$TRUSTED_STORAGE_SHA256" \
  --api-base "$SCRATCH_BACKEND_URL"
```

For an IPv4-only connection, add
`--session-pooler-host <scratch session pooler host>` before `--api-base`.

Under `data:` the drill prints how many of the rows the capture counted are
stamped after the recovery point and were therefore not required of the
restore. That should be what a few hours of use write. A number close to the
total means `RECOVERY_POINT_TIME` was too early, and a `PASS` then shows
little. After a capture with `--older-backup` the line starts with
`WARNING, an older backup:`. Every row written since that backup is then among
the rows not required, and a restore that lost some of them still passes.

The last lines are the result. `RESULT: PASS` is followed by "not covered by
this drill:" when the drill left something out on purpose: attachment bytes
(the database-only path), or this checkout's migrations (production's ledger
differs from the checkout, see step 3). Those lines are also in the record
under `not_covered`.

The command writes two files.

- `data/releases/drills/<drill_id>.json`, which `release_gate.py` reads clause
  by clause. That file is the deliverable; the markdown row in §4 is a human
  index of it, not the evidence itself. This repository is public, so the
  record holds no row count: for the data step it has the result, the names of
  the tables that failed, and two SHA-256 digests (of `source-rows.json` and of
  the restored counts). It also leaves out the backend's `/api/ready` reply.
- `$PRIVATE_DIR/<drill_id>.private.json`, owner-only: the same record plus the
  source and restored row count of every table, the failure lines with their
  numbers, how many rows an anonymous caller could read if the RLS leg failed,
  and the `/api/ready` reply. The drill refuses to run if
  `--source-row-counts` points inside the repository. Because the committed
  record has no counts, the release gate cannot redo the comparison; it reads
  the recorded outcome and checks the digest against the pinned receipt.

What each leg checks:

1. **Schema**: every required table is reachable, and the independently
   observed public/private columns, application DDL and applied migrations are
   the same on the source and scratch projects. Whether those applied
   migrations are the ones in this checkout is a separate statement: when they
   are not, the drill lists it under "not covered" (step 3) and does not fail.
2. **Data**: each of the 23 required application tables must hold, on scratch,
   every row the source says existed at the recovery point. The capture reads
   the live project hours after the nightly backup, so its totals include rows
   the backup cannot contain. It therefore counts each table twice: all rows,
   and the rows stamped later than 15 minutes before `RECOVERY_POINT_TIME` (the
   dashboard shows one time for a backup that takes minutes to complete). The
   restored table must hold at least the first number minus the second.
   Four tables only grow: `analytics_events`, `usage_events`,
   `feedback_events` and `profile_versions`. The application inserts into them
   and has no way to delete from them, so a restore must also never hold more
   of their rows than the capture counted. Every other table may hold more on
   scratch. Most lose rows in normal use (a favourite removed, two devices
   merged). `ops_incidents` and `ops_incident_events` gain rows on the scratch
   project itself: a restore is a binary copy, so the `ops-dead-man-sweep`
   pg_cron job of migration 032 comes with it and
   [starts running as soon as the restore completes](https://supabase.com/docs/guides/platform/clone-project).
   Nothing has checked in with the scratch project since the backup, so the
   job's first run files an incident for its own overdue heartbeat and its
   second, ten minutes later, records the recovery (on a local PostgreSQL with
   the migrations applied: one more incident and three more incident events
   after two runs). A visitor's page view or a new favourite between the backup
   and the capture does not fail this step; an empty or short table does, and
   the drill prints the three numbers it saw.
   What totals cannot show: which rows are present, and a table that lost rows
   in the restore while at least as many were deleted on the live site since
   the backup. The stamps of `interactions`, `match_feedback` and
   `professor_update_reads` come from the student's browser clock. A receipt
   without source counts leaves data recovery unverified.
   Ten tables of the public schema are not among the 23 and have no row check:
   `application_events`, `application_material_records`, `contact_events`,
   `contact_material_records`, `interaction_merge_archive`,
   `material_artifacts`, `outcome_notes`, `private_import_targets`,
   `target_resume_versions` and `target_resumes`; nor has
   `private.material_cleanup_outbox`. The schema leg covers their definitions,
   but a restore that brought them back empty would pass this step.
3. **RLS**: an anonymous caller sees no user-owned rows. This is the leg a
   service-role-only check cannot make — a restore that brings back the tables
   but not their policies reads perfectly well to an admin probe while exposing
   every student's rows to the internet.
4. **Application**: PostgREST and GoTrue on the scratch project answer, and
   the backend from step 6 returns 200 from `/api/ready`. That endpoint reports
   the backend's own state (corpus loaded, matcher ready, refresh not stale)
   and does not query the database, so the reads that reach the restored data
   are the drill's own; this leg shows the application starts with its
   settings pointed at the scratch project, not that every route works on it.
5. **Attachment bytes** (not on the database-only path): every scratch bucket
   must match the complete inventory. Every expected object must have the same
   length and SHA-256 after download. The public drill record contains
   aggregate counts and a receipt digest. Without `--attachments-out-of-scope`
   a missing inventory leaves this step unverified and the drill cannot pass.
   The scratch listing comes from the restored database, so a file deleted on
   the live site between the backup and the capture is listed on scratch, is
   absent from the inventory, and fails this step as unexpected.

Without `--api-base` the application leg records `PARTIAL`, not `PASS`, and the
drill's `final_result` is `FAIL` — deliberately. A drill that did not boot the
application did not prove the application recovers.

### Step 8 — Record and tear down

Commit `data/releases/drills/<drill_id>.json` and add its row to §4. It names
the two projects, the recovery point and the operator (`--operator`, by
default the login name on this machine), and holds digests and results; it
holds no row count, object name, key or password. Stop the backend from step 6.
Delete the scratch project: it is billed, and a forgotten one is both a
standing cost and a second copy of production data. Keep `$PRIVATE_DIR`
(receipt, row counts, catalogue, inventory, private record) somewhere private:
it is the half of the evidence the digests in the committed record point to,
and it never goes into the repository.

### Failure handling

A drill that finds problems is the most valuable kind. Its record is written
either way, and must be committed either way.

| What failed | What it means | Next |
|---|---|---|
| `schema_validation` | the restore did not bring back the full schema | do not release; treat the backup as unproven and escalate to Supabase |
| `schema observations: source_restored_schema_mismatch` | columns, definitions, policies, grants or applied migrations differ between production at the capture and the restore; when a definition differs the line ends with the kind and schema, for example `in trigger/storage (2 on the source, 3 restored)` | if a migration was applied to production between the backup and the capture, capture again after the next backup; otherwise treat the backup as unproven |
| `schema observations: schema_observation_missing` | the receipt was not accepted (its digest is not `TRUSTED_SCHEMA_SHA256`) or the scratch catalogue could not be read (a `::warning::` line above says why) | fix the digest or the scratch database connection and run step 7 again; no new restore is needed |
| `schema observations: schema_observation_unbound` | the receipt names another project or recovery point than the drill command | run step 7 with the `SOURCE_REF` and `RECOVERY_POINT` the capture used |
| `schema observations: schema_observation_time_unbound` | the capture, the restore start and the drill are not in that order in time | `RESTORE_STARTED_AT` must be later than the capture and earlier than now; if the capture really was taken after the restore started, capture and restore again |
| `attachment_validation` | private objects differ or verification is incomplete | check the storage copy and rerun in scratch |
| `data_validation` | the lines starting `! data:` say which: a table holds fewer rows than existed at the recovery point (the line gives the restored count, the source count, how many of those may be later than the backup, and how many are missing), or a table that only grows holds more rows than the later capture counted, or scratch gave no count for a table | fewer rows: check that `RECOVERY_POINT_TIME` is the time of the backup that was actually restored; if it is, the backup lacks data that production had, so treat it as unproven and escalate to Supabase. More rows in a table that only grows: the restored backup is newer than the capture, or it is another project's (the two incident tables are not among these; the scratch project's own sweep job adds rows to them). No count: the scratch service-role key or the table is missing |
| `rls_validation` | policies did not survive the restore | **the most serious outcome**: recovery would expose user data. Release stays NO-GO until the procedure includes reapplying policies, verified by a re-run |
| `application_smoke` | PostgREST or GoTrue on scratch did not answer, or the backend from step 6 did not return 200 from `/api/ready` (`PARTIAL` means no `--api-base` was given) | the `/api/ready` reply is in the private record. Its `reasons` are about the backend process, not the restore: `corpus_stale`, `corpus_freshness_unknown` or `corpus_empty` mean this checkout's data is old or missing, so update the checkout, restart the backend and run step 7 again. If PostgREST or GoTrue did not answer, the scratch project is not fully up or the keys are another project's. The `! application:` line gives the HTTP status of each of the three. `GoTrue 401` usually means the `anon` key typed at the prompt is not this project's; the RLS leg of that run then says `PASS` only because every anonymous read was refused with the key, so it shows nothing about the policies. Run step 7 again with the right key |

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
