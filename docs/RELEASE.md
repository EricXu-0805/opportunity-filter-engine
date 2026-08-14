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
| `scheduler`, `dead_man` | cron run history + external monitor | an operator |

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
