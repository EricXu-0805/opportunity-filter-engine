# Release procedure and promotion gates

The release decision is evidence-based and the default is **NO-GO**.
`scripts/release_gate.py` is the arbiter: it exits 0 only when every required
gate presents current evidence bound to one frozen release SHA, and exits 1
otherwise. A NO-GO is the normal outcome until evidence has been gathered —
it is not a bug to be worked around.

```
python scripts/release_gate.py --release-sha <40-hex> \
    --evidence evidence/ci.json --evidence evidence/canaries.json \
    --out data/releases/<sha>.json
```

## 1. Freeze the SHA

One immutable 40-hex commit SHA identifies the whole release: backend build,
frontend build, migration set, E2E run, canaries, and artifacts. The gate
refuses short SHAs and tags (both ambiguous), refuses a SHA not present in
the repository, and refuses to gather local evidence from a dirty worktree or
a HEAD that differs from the release SHA.

Deployed services prove their own identity via `backend/lib/build_info.py`
(`RENDER_GIT_COMMIT`, falling back to `OFE_RELEASE_SHA`, else **null** — never
a fabricated placeholder, and never a locally computed `git rev-parse`, which
would say nothing about what is actually running). `/api/health` and
`/api/ready` both report it.

## 2. Gather evidence

| Gate | Source | Who can produce it |
|---|---|---|
| `release_sha`, `worktree` | this repo | the gate itself |
| `corpus` | shard record floor | the gate itself |
| `tracking_release_ready` | `professor_tracking.json` strict contract | the gate itself |
| `truthfulness` | `data/audits/truthfulness_report.json` (GO + age ≤30d) | the gate itself |
| `flag_parity` | backend vs frontend release-scope tables | the gate itself |
| `ci:*` (4 required checks) | `scripts/verify_refresh_pr.py`-shaped snapshot | CI, bound to the head SHA |
| `open_incidents` | `GET /api/admin/ops/incidents?unresolved_only=true` | an operator with `ADMIN_TOKEN` |
| `api_ready` | `GET /api/ready` on the deployed instance | an operator |
| `render_canary`, `vercel_canary`, `supabase_canary` | the deployed environments | an operator |
| `backup`, `restore` | see `docs/DISASTER_RECOVERY.md` | an operator |
| `scheduler` | cron run history | an operator |
| `dead_man` | `ops_heartbeats` + a recorded drill (migration 032) | an operator |

Evidence files are JSON keyed by gate name; every external gate must carry a
`release_sha` so it can be bound to the release. Evidence for a different SHA
is a FAIL, not a pass.

Operator-gathered evidence lives at `data/releases/evidence/<sha>.json` and the
release-gate workflow reads it **from the default branch**, not from the
checkout. That is not a shortcut: evidence about a deploy cannot exist inside
the commit being deployed, while `check_worktree_clean` requires HEAD to equal
the release SHA. Omit a gate's key rather than inventing one — an absent key
reads as UNVERIFIED and blocks, which is the answer that keeps the gate worth
consulting.

`UNVERIFIED` is deliberately distinct from `FAIL`: both block, but the first
means "we have no evidence either way" and the second means "we have evidence
of a problem". Collapsing them would hide which gates need infrastructure
access and which need fixing.

## 3. Promotion stages

| Stage | Entry criteria | Evidence | Stop / rollback condition |
|---|---|---|---|
| **Release candidate** | SHA frozen; all 4 required CI checks green on that exact SHA; no critical check skipped | `ci:*` PASS | any required check missing, skipped, or red |
| **Canary** | RC criteria met; deployed to Render + Vercel at the same SHA | `render_canary`, `vercel_canary`, `supabase_canary`, `api_ready` PASS | `/api/ready` non-200; deployed SHA ≠ release SHA; 5xx rate rises |
| **Internal validation** | canary green; representative flows exercised by an operator | `promotion` evidence naming the flows checked | any flow fails, or a new `ops_incident` opens |
| **Limited production** | internal validation recorded; backup point recorded and restore capability proven | `backup` + `restore` PASS | error-rate or latency regression; any unresolved incident |
| **Full production** | limited-production window observed clean; scheduler + dead-man verified | `scheduler`, `dead_man` PASS | any of the above |

Deployment succeeding is not promotion. Each stage requires its evidence
recorded in the ledger before the next begins.

### The dead man's switch (migration 032)

Every scheduled workflow POSTs `/api/cron/heartbeat` as its last step. A
pg_cron job (`ops-dead-man-sweep`, every 10 minutes) files a `collector_failure`
incident for any heartbeat past its deadline, and the daily `/api/cron/ops-scan`
reads the sweep's *own* heartbeat — so pg_cron dying is caught from GitHub and
GitHub dying is caught from Postgres. Both land in `ops_incidents`, which
`open_incidents` already blocks on.

To gather `dead_man` evidence, run a drill rather than asserting the design:

```sql
-- 1. an immediately-overdue heartbeat
insert into ops_heartbeats (name, description, expected_interval_seconds, grace_seconds, priority)
values ('release_drill', 'release-gate drill', 1, 0, 'low');
-- 2. the sweep must file it
select * from ops_dead_man_sweep();
select status, failure_state, detail->>'overdue_seconds' from ops_incidents
  where dedup_key = 'dead_man:release_drill';
-- 3. check in, sweep again: the incident must close itself
select record_ops_heartbeat('release_drill', '{"source":"drill"}'::jsonb);
select * from ops_dead_man_sweep();
-- 4. tear the row down; leave the incident as the record
delete from ops_heartbeats where name = 'release_drill';
```

Record the observed row values in the evidence file. A drill that was not run
is `UNVERIFIED`, not `PASS` — the design being correct is not evidence that
the switch is armed.

### A scheduled workflow can hold the backend deploy

`render.yaml` sets `autoDeployTrigger: checksPass`, and Render waits for
**every** check run on the commit — it has no notion of "required". That is
what froze the backend for four days in August when the non-required
`Security advisory` job went red (#733).

The same mechanism has a second, quieter form: a workflow that runs *on main*
hangs its check on main's head commit for as long as it runs. Observed
2026-08-14 — `c549ffb` merged with all four required checks green, and Render
never queued a deploy, because a manually dispatched `refresh` was still
`in_progress` against that commit. `Deploys` showed `0656768` Live and no
pending build.

The block is **per commit, and a later clean commit skips over it**. Measured
the same afternoon: `c549ffb` stayed undeployed with its `refresh` check still
running, and when `6c57d30` merged behind it with only the four CI checks,
Render deployed that instead — carrying `c549ffb`'s code with it. `c549ffb`
never got a deploy of its own and never needed one.

So the exposure is narrower than "merges during the refresh window are lost",
and it is worse where it lands: **the last merge before a quiet period.** If
nothing merges after it, nothing carries it, and it waits for the refresh to
finish — or forever, if the refresh fails. That is precisely the #733 shape:
the four-day freeze happened because nothing merged behind the stuck commit.

Vercel is unaffected; it deploys fails-open, which is how the front and back
ends drift apart in the meantime.

Check before concluding a deploy is stuck:

```bash
gh api repos/<owner>/<repo>/commits/<sha>/check-runs \
  --jq '.check_runs[] | "\(.name): \(.status) \(.conclusion)"'
```

The structural fix is to stop letting an unrelated job decide: set
`autoDeploy: false` and call a Render deploy hook from the CI workflow once —
and only once — the four required jobs are green. That needs a
`RENDER_DEPLOY_HOOK_URL` secret, so it is the operator's move, not a code
change that can land ahead of it.

## 4. Rollback

**Trigger:** `/api/ready` non-200 after deploy, deployed SHA ≠ release SHA,
a new `high`/`urgent` `ops_incident`, or any user-visible correctness report.

**Actor:** the operator running the release.

**Application rollback:** Render — redeploy the previous successful deploy
from the dashboard (the blueprint pins no version, so the previous image is
the rollback target). Vercel — promote the previous production deployment.
Both are SHA-identifiable via `/api/health`, so a rollback can be *verified*
rather than assumed: re-read `release_sha` after the rollback and confirm it
matches the intended previous SHA.

**Migration recovery — read this before releasing anything with a migration.**
Migrations in this repo are **forward-only**: 0 of 33 carry a down script,
and the pattern is supersession (006 supersedes 004; 026 revokes what 019
granted). Three migrations are also **not idempotent** (`002_interactions.sql`,
`003_profile_versions.sql`, `0181_oauth_merge_secret.sql` use bare
`CREATE POLICY` / `CREATE INDEX` / `ADD COLUMN`), so re-running them against a
live database errors. Consequences:

- There is no automated schema rollback. Recovery from a bad migration is a
  restore to the recorded pre-release point (see `DISASTER_RECOVERY.md`), or a
  hand-written forward fix reviewed as its own change.
- A release containing a migration therefore **cannot** reach limited
  production until `backup` and `restore` evidence exists. The gate enforces
  this by requiring both.

**Data recovery:** restore to the pre-release recovery point. Note that some
data changes are deliberately irreversible by design (e.g.
`024_contacted_status.sql` declines to rewrite existing rows rather than
guess), so a restore is the only route back for those.

**Post-rollback validation:** `/api/ready` returns 200; `/api/health`
`release_sha` equals the intended previous SHA; re-run the gate against that
SHA and confirm the previously-passing gates still pass.

## 5. Known gate weaknesses (recorded, not hidden)

- **Test scope ≠ shipped scope.** `tests/conftest.py` has an autouse fixture
  that forces `feature_enabled` → True for every module that does not opt out.
  Exactly one of ~126 test modules opts out, so the great majority of tests
  validate the flags-ON surface rather than what ships. `tests/test_release_scope.py`
  is the only module proving the real production surface. Narrowing that
  fixture is tracked separately; until then, "CI green" is weaker evidence
  about production behavior than it appears.
- **Migration application to production is manual** (dashboard SQL editor), so
  nothing forces the applied set to match the committed set. The ledger itself
  is no longer the problem: checked on 2026-08-14, production's
  `supabase_migrations.schema_migrations` holds **33 rows and covers all 33
  committed migrations**. It read as "3 of 33" because three of them (012, 013,
  014) were applied with `supabase db push` and are recorded under timestamp
  versions (`20260611111920` etc.) rather than their numeric prefixes — a
  naming difference that a count of matching prefixes reports as a gap.
  Reconcile by name, not by version string.
- **`/api/ready` is not wired to `render.yaml`'s `healthCheckPath`** on
  purpose. It gates on corpus freshness, and at the time of writing the corpus
  sat at 94h against a 96h stale bound — pointing the instance probe at it
  would turn a late scraper into a total outage. Wiring it is a deliberate
  owner decision with that consequence understood.
