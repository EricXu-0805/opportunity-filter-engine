# RUNBOOK — operating JoinALab

Checked against the code on 2026-10-09. Every command in a code block was run
that day, except the ones marked **operator**: those need production secrets
or change production. Releases and rollback have their own document,
`docs/RELEASE.md`. Open work is not tracked here (section 8).

## 1. Check what is deployed

```bash
curl -sS https://opportunity-filter-engine-api.onrender.com/api/health
curl -sS https://opportunity-filter-engine-api.onrender.com/api/ready
curl -sS https://joinalab.com/ | grep -o 'data-release-sha="[^"]*"'
```

`/api/health` reports the backend's `release_sha`; the page attribute reports
the frontend's. Both should name the same `main` commit: on 2026-10-09 both
said `6e7530d0`. `/api/ready` answers 200 with `"ready": true`, or 503 with
the failing checks (corpus freshness among them) listed in `reasons`. Render
deploys a `main` commit only after its CI checks pass
(`autoDeployTrigger: checksPass` in `render.yaml`).

## 2. Data refresh

`.github/workflows/refresh-data.yml` runs every day at 06:07 UTC (every schedule
here starts a few minutes past the hour, because GitHub starts top-of-hour
schedules late). It takes the
shard for the UTC weekday (`date -u +%u`, 1 = Monday) from `WEEKLY_ROTATION`
in `scripts/refresh_rotation.py`, so each school is re-scraped once a week.
Monday's shard carries `uiuc`, and Sunday (7) is `national`: the SRO catalog,
NSF REU and SimplifyJobs internships. Print any day's shard:

```bash
python3 scripts/refresh_rotation.py --day 1
python3 scripts/refresh_rotation.py --day 7
```

`--day` refuses to answer when a supported school sits in no shard or in two.
That check exists because 25 registered schools were once in no shard and
went unrefreshed after onboarding. A school leaves the rotation only by
leaving the product (`src/school_scope.py`).

What one scheduled run does:

1. Scrapes its shard in deep mode, with a 240-minute source budget (210 on a
   day that also runs the Illinois Experts pass). The job itself times out at
   350 minutes.
2. In the first seven days of the month, follows each faculty profile link of
   the shard (`OFE_ENRICH_PROFILES=1`). On the first Monday it also runs the
   Illinois Experts pass for `uiuc`, capped at 30 minutes.
3. Runs the corpus-wide offline passes (`python -m src.normalizers.enrich_processed --save`,
   `python -m src.normalizers.deactivate_past --save`) and the data-quality
   tests.
4. Writes back only the shards it was allowed to refresh and whose sources
   succeeded, opens an `auto/refresh-data-*` PR, and squash-merges it once the
   required checks pass. That step needs the `REFRESH_PAT` secret.
5. Checks in to the dead man's switch (section 3).

GitHub can start a scheduled run late; the 2026-10-02 run started 5.5 hours
late. Scheduled and manual runs sit in separate concurrency groups, and the
first step keeps them apart: a manual run defers to a refresh in progress, and
a scheduled run cancels a manual one.

**Manual run (operator).** Actions → Refresh Opportunity Data → Run workflow.
`schools` takes comma-separated school slugs or `national`; empty means a
full refresh. `deep` and `enrich_profiles` are `true`/`false`. The
workflow validates `schools` with this command, which you can run first:

```bash
python3 scripts/refresh_rotation.py --schools ucla --allow-full
python3 scripts/refresh_rotation.py --schools ucla --allow-full --needs-browser
```

The second prints whether the run will install headless Chromium. To read a
refresh's options locally, run `python -m src.collectors.refresh_all --help`;
publish data through the workflow's PR, not a hand-committed shard.

## 3. Other scheduled jobs

| Workflow | When (UTC) | What it does |
|---|---|---|
| `ops-scan.yml` | daily 11:13 | `POST /api/cron/ops-scan`: files collector and drift incidents |
| `snapshot-reminder.yml` | Monday 13:23 | Emails the operator when a hand-exported snapshot (CMU) is due |
| `daily-reminders.yml` | daily 23:11 | `GET /api/cron/reminders` (Web Push, email fallback), then the data-quality check and the feedback and orders digests |
| `saved-searches-refresh.yml` | daily 23:41 | `GET /api/cron/saved-searches/refresh`, then `/digest` |
| `campus-seed-health.yml` | Sunday 12:19 | Probes configured seed and program URLs for dead pages |
| `release-gate.yml` | manual only | The release gate (`docs/RELEASE.md`) |

Every scheduled workflow checks in with `POST /api/cron/heartbeat` at the
end. A pg_cron job from migration 032 files an incident for any heartbeat that
misses its deadline, and `ops-scan` checks the pg_cron job's own heartbeat.
`docs/RELEASE.md` ("The dead man's switch") has the drill. `ops-scan`,
`daily-reminders` and `saved-searches-refresh` start with a "Require the
secrets this cron runs on" step that names the secrets each needs. Every
workflow above also has a manual Run workflow button (**operator**).

## 4. Database migrations

### Why the 49 names look different

`supabase/migrations/` held 49 files on 2026-10-09. A migration's version is
the part of its name before the first underscore. The Supabase CLI applies
files in filename order and records each version once.

| Names | Count | Where they came from |
|---|---|---|
| `001`–`034` | 34 | The original three-digit sequence. `001` was written on 2026-07-24 (#646) to recreate tables first made in the dashboard. The last two, `033` (2026-08-27) and `034` (2026-09-05), landed after the first timestamp file. |
| `0181_oauth_merge_secret`, `0201_usage_events` | 2 | Renamed from `018_` and `020_` in #646 because two files shared each version, which made `supabase db push` impossible. Content unchanged. In filename order `0181_` runs before `018_` and `0201_` before `020_`. |
| `20260819164641_…` onward | 13 | `YYYYMMDDHHMMSS` UTC timestamps, the format `supabase migration new` writes. Every migration since 2026-09-24 uses it. |

The replay in CI (`supabase/tests/run_supabase_cli_migration_test.sh`)
applies all 49 into an empty database in that order.

### Rule for a new migration

1. Create it with `supabase migration new <snake_case_name>`. It gets a UTC
   timestamp later than every existing file. Never use a three-digit name: a
   `035_` sorts before all the timestamp files, so a fresh replay would run it
   before 13 migrations it may depend on. `tests/test_docs_current.py` fails on
   any new name that is not a 14-digit timestamp later than `20260930220000`,
   the newest version when the check was written.
2. Never edit or rename a migration that production has run. Write a new one
   that supersedes it; the chain is forward-only (`docs/RELEASE.md`,
   "Migration recovery").
3. Add the version to the array in
   `supabase/tests/migration_history_contract_test.sql`. Add its SQL test
   under `supabase/tests/` and name that test in a runner CI executes.
   `tests/test_ci_gate_honesty.py` fails while the version is missing from
   the array or a SQL test is named by no CI runner.
4. Replay locally:

   ```bash
   bash supabase/tests/run_flow_b_test.sh
   bash supabase/tests/run_supabase_cli_migration_test.sh
   ```

5. **Operator:** the owner applies it to production by hand, through the
   dashboard SQL editor or the Supabase MCP `apply_migration`, sending the
   file unchanged. Never run `supabase db push` against
   production. Production's history records `012`, `013` and `014` under
   timestamp versions such as `20260611111920`, so match its ledger to the
   files by name, not by version string (`docs/RELEASE.md`, section 5, and
   `supabase/MIGRATION_REPAIR.md`). `scripts/check_migration_parity.py` does
   that match offline: `--print-sql` prints the read-only export query, and
   `--applied <export>` reads its result back and exits 1 on drift, such as
   a file production never ran or a row the repo does not have. Running the
   query against production waits on the owner's OK.

`supabase db push` with the pinned CLI 2.95.4 works only on an empty
database. On 2026-10-09 a scratch database that had taken the full chain
refused all five follow-up pushes tried: with and without `--include-all`,
with and without a new migration file. Each time the CLI reported remote
versions `018` and `020` as missing locally. `supabase migration list` shows
the mismatch: it lists the remote `018` before `0181` and the local `018`
after it.

## 5. Release flags

`docs/product_scope.md` lists every flag, its state and why each closed one
is closed. A flag flips only in that feature's acceptance PR, which edits both
`backend/lib/release_scope.py` and `frontend/src/lib/release-scope.ts`, moves
the feature from `UNACCEPTED_FEATURES` to `ACCEPTED_FEATURES` in
`tests/test_release_scope.py`, and updates the table in
`docs/product_scope.md`.

## 6. Setting up a new environment

1. **Supabase.** Enable Authentication → Sign In / Providers → Anonymous
   Sign-Ins. Without it, `signInAnonymously()` returns HTTP 422
   (`anonymous_provider_disabled`), and the app keeps favorites in the browser
   under a "Saved locally only" banner. Then apply the migrations. Into an
   empty database `supabase db push` takes the whole chain, which is what the
   CI replay does (section 4).
2. **Secrets.** `docs/RELEASE.md` section 6 lists every variable the
   backend, the frontend build and the workflows read, whether production
   needs it, and what breaks without it. The backend's go in the Render
   dashboard (`render.yaml` holds only non-secret settings), the frontend's
   build variables in Vercel, and the workflows' in GitHub repository
   secrets. Section 3 says where the cron workflows name theirs.
3. **Web Push.** Generate a VAPID keypair and set `VAPID_PRIVATE_KEY`,
   `VAPID_PUBLIC_KEY` and `VAPID_SUBJECT` on the backend. Keep the private key
   in a password manager.

   ```bash
   python scripts/generate_vapid_keys.py
   ```

   The script also prints a `NEXT_PUBLIC_VAPID_PUBLIC_KEY` line. Nothing on the
   frontend reads it: the browser asks `GET /api/push/vapid-public-key`, which
   answers 503 until the backend has a public key, and the backend accepts
   that name only as a fallback for `VAPID_PUBLIC_KEY`.
4. **Check** with section 1's commands against the new hosts.

## 7. Releases and rollback

`docs/RELEASE.md`: the gate, the evidence each check needs, rollback for
Render, Vercel and the database, and the known weak spots.

## 8. Open work

The single to-do list is the owner's MVP checklist (the private "OE todolist"
Google Doc, MVP tab, items M01–M70). Work that is not in it is not planned.
