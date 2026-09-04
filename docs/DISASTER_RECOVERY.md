# Disaster recovery: backup and restore

> **Current status: backups exist; recovery is still UNVERIFIED, and the
> recorded recovery point has aged out of retention. Both are release
> blockers.**
>
> ```
> backup exists  !=  recovery verified
> ```
>
> `scripts/release_gate.py` reports `restore_drill` as `UNVERIFIED` with reason
> `drill_never_performed`, which keeps the release at NO-GO on its own. That is
> the correct state until the drill in §3 is performed and its record lands in
> `data/releases/drills/`.
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
  only their metadata. Today that is one 21.9 KB object in the private
  `tracker-attachments` bucket (migration 008), so the exposure is small, but
  it grows with every attachment a student uploads and nothing else covers it.
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
| Optionally, a backend pointed at the scratch project | turns the app leg from PARTIAL into PASS | release operator |

Nothing here needs production database credentials, and the drill never uses
them: `scripts/restore_drill.py` refuses to run when `DRILL_SUPABASE_URL`
names the source environment.

## 3. Required before any release containing a migration

### Step 1 — Establish and record the backup

Record the recovery point in the release's evidence file
(`data/releases/evidence/<sha>.json`, key `backup`) from the Supabase
dashboard: identifier / recovery point, timestamp (UTC), environment
(production project ref), scope (which schemas/tables; whether storage objects
are included), retention window, and owner (who can perform a restore). Include
`observed_at` — undated evidence is refused.

### Step 2 — Restore into a scratch project

*Database → Backups → Restore to new project*, on the recorded point. It
restores into a **separate**, newly provisioned project — never over
production, which is what makes it safe to drill — and that new project is
billed, so run it deliberately and delete it when the drill is done.

Note the restore start time; the drill record carries it.

### Step 3 — Prove recovery, do not assume it

Run the drill against the **scratch** project:

```bash
export DRILL_SUPABASE_URL=https://<scratch-ref>.supabase.co
export DRILL_SERVICE_ROLE_KEY=<scratch service role key>
export DRILL_ANON_KEY=<scratch anon key>

python scripts/restore_drill.py \
    --source-backup-id "<recovery point as the dashboard names it>" \
    --source-environment mjpirkyduibkakvlbdko \
    --scratch-environment <scratch-ref> \
    --restore-started-at "<when step 2 began>" \
    --api-base https://<backend pointed at the scratch project>
```

It performs the four validations this section has always required, and writes
`data/releases/drills/<drill_id>.json` — which `release_gate.py` reads clause
by clause. That file is the deliverable; the markdown row in §4 is a human
index of it, not the evidence itself.

1. **Schema**: every table the application requires is present and reachable.
2. **Data**: representative user-owned tables came back populated. An empty
   restore satisfies every schema check and none of the point of one.
3. **RLS**: an anonymous caller sees no user-owned rows. This is the leg a
   service-role-only check cannot make — a restore that brings back the tables
   but not their policies reads perfectly well to an admin probe while exposing
   every student's rows to the internet.
4. **Application**: the restored data plane answers, and with `--api-base`,
   `/api/ready` returns 200 against it.

Without `--api-base` the application leg records `PARTIAL`, not `PASS`, and the
drill's `final_result` is `FAIL` — deliberately. A drill that did not boot the
application did not prove the application recovers.

### Step 4 — Record and tear down

Commit the drill record. Then delete the scratch project: it is billed, and a
forgotten one is both a standing cost and a second copy of production data.

### Failure handling

A drill that finds problems is the most valuable kind. Its record is written
either way, and must be committed either way.

| What failed | What it means | Next |
|---|---|---|
| `schema_validation` | the restore did not bring back the full schema | do not release; treat the backup as unproven and escalate to Supabase |
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

**Conclusion: `CANNOT VERIFY`; the release stays `NO-GO`.** The blocker is
access and billing authority, both of which sit with the project owner. The
procedure above is executable and its tooling is committed and tested. Nothing
here can be worked around from inside the repository, and it must not be: a
drill record written without a restore would make the one gate that has never
lied start lying.

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
