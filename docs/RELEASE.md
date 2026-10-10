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
| `ledger_currency` | `data/releases/CURRENT.json` vs the candidate | the gate itself |
| `corpus` | shard record floor | the gate itself |
| `freshness` | `professor_tracking.json` counts vs `FRESHNESS_MIN_PCT` | the gate itself |
| `tracking_release_ready` | `professor_tracking.json` strict contract | the gate itself |
| `truthfulness` | `data/audits/truthfulness_report.json` (GO + age ≤30d) | the gate itself |
| `flag_parity` | backend vs frontend release-scope tables, by name **and value** | the gate itself |
| `release_record` | the SHA `/api/health` reports, the `data-release-sha` on the frontend's HTML, and — derived from those two commits — each side's data version (last shard commit) and flag table | the gate itself with `--backend-url`/`--frontend-url`, or an operator |
| `restore_drill` | `data/releases/drills/<drill_id>.json` | an operator, via `scripts/restore_drill.py` |
| `ci:*` (4 required checks) | `scripts/verify_refresh_pr.py`-shaped snapshot | CI, bound to the head SHA |
| `open_incidents` | `GET /api/admin/ops/incidents?unresolved_only=true` → `rollup` (the gate counts `release_blocking_total`: every unresolved incident except a `manual_review:snapshot_refresh:*` reminder) | an operator with `ADMIN_TOKEN` |
| `provider_readiness` | `GET /api/ready` → `reported.providers` | an operator with `ADMIN_TOKEN` |
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

### The release record

One record ties together what is actually serving: the backend's commit, the
frontend's commit, the data each was built with, and the flags each enforces.
The gate fails when either deploy is on a commit other than the candidate, or
when the two deploys' data versions or flag tables differ. Without
`--release-sha` it does not compare the two deployed commits with each other;
the `release_sha` gate already fails such a run.

```
python scripts/release_gate.py --release-sha <40-hex> \
    --backend-url https://<render host> --frontend-url https://<site> ...
```

The gate reads `GET /api/health` → `release_sha` and the `data-release-sha`
attribute on `GET /`. Everything else is derived from those two commits,
because a deploy builds one commit's tree. Render's build only runs
`pip install`. `data_loader` reads `data/processed/shards` when no
`opportunities.json` exists, and that file is gitignored. The frontend's
coverage numbers (`school-stats.json`) are committed with the shards by the
refresh workflow. So the data version is the last commit that touched the
shards at that SHA. If either deploy reports no full SHA, the gate says
`UNVERIFIED`. An observation older than one day is stale. The release-gate
workflow passes the `BACKEND_URL`/`FRONTEND_URL` secrets the cron workflows
already use. Without `--backend-url`/`--frontend-url`, an operator can record
`{"deployment": {"observed_at", "backend_sha", "frontend_sha"}}` instead.

`UNVERIFIED` is deliberately distinct from `FAIL`: both block, but the first
means "we have no evidence either way" and the second means "we have evidence
of a problem". Collapsing them would hide which gates need infrastructure
access and which need fixing.

### Evidence expires

Every gate describing a live observation — the canaries, `api_ready`,
`promotion`, `scheduler`, `dead_man`, `rollback`, `backup`, `open_incidents`,
`provider_readiness` — must carry `observed_at`. Undated evidence is
`UNVERIFIED`, and evidence past that gate's maximum age is `FAIL`. The limits
live in `_EVIDENCE_MAX_AGE_DAYS`; `backup` is 7 days because that is the
retention window, so an older recovery point is not a worse option but no
option at all.

`ci:*` carries no age limit on purpose: it is keyed on the commit, so a result
for the candidate SHA cannot predate a change to the candidate.

The ledger checks itself the same way. `ledger_currency` fails when the
committed ledger describes another SHA or is more than 7 days old — the state
`data/releases/CURRENT.json` was in on 2026-09-03, when it was 127 commits
behind and still read as the project's release posture.

Two flags keep that check satisfiable rather than permanently red, because a
ledger is written *after* the candidate it describes and can never sit inside
that candidate's own tree:

- `--update-current` makes the run itself the refresh. The gate reports
  `ledger_currency` PASS on that basis and says so in the evidence — the
  statement is made true by the run. It excuses nothing else; a refreshing run
  that is missing evidence is still NO-GO, and `--update-current` cannot
  publish a GO the evidence does not support.
- `--ledger PATH` reads the ledger from somewhere other than the checkout. The
  release-gate workflow points it at the default branch's copy, for the same
  reason it reads operator evidence and drill records from there.

Refresh the ledger by regenerating it. Never edit it.

### `NOT_APPLICABLE` — the only verdict that does not block

A gate exists to protect a shipped path. When every path it protects sits
behind a source-controlled-off flag, `FAIL` is a lie of a different kind: an
unexplained permanent red that nobody can action and everybody learns to skip.
The gate reports `NOT_APPLICABLE` instead, always naming the flag, and keeps
the underlying verdict under `evidence.would_be` so the gap stays visible and
the check re-arms by itself when the flag flips.

Today that covers `freshness` and `tracking_release_ready`: every consumer of
`professor_tracking.json` is behind `professor_signals`, which is `False`.
Their real numbers are still reported in the ledger's `freshness_percent` and
`fully_stale_school_count` — "not applicable" is a statement about the release
surface, never a reason to stop measuring.

Three rules keep this from becoming an escape hatch:

- A gate stops applying only when **every** feature requiring it is off. One
  enabled consumer keeps it blocking — which is why a missing LLM key still
  blocks with `ask_ai` closed, because `resume_renovate` is accepted and shares
  it.
- An unknown flag state — unreadable table, unrecognised flag name — leaves
  every gate applying. Uncertainty never buys an exemption.
- An operator may declare an external gate `NOT_APPLICABLE` only **with** a
  `reason`. A bare `"status": "NOT_APPLICABLE"` is rejected as
  `exemption_unexplained`; that is how a real blocker gets retired without
  being fixed.

`restore_drill` is deliberately absent from the applicability map. Recovery is
not a feature, so no flag may retire it.

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

### The operator alert drill

Each scheduled workflow's failure alert ends in `|| true`, so no run shows
whether the mail arrived. `.github/workflows/alert-drill.yml` sends one alert
down the same path (the `RESEND_API_KEY` and `OPERATOR_EMAIL` secrets, the
`RESEND_FROM_EMAIL` sender, Resend's `/emails` API) with `[DRILL]` in the
subject and the text. It fails when either secret is missing or Resend answers
outside 2xx. It has no schedule: start it from the Actions tab (alert-drill,
Run workflow). Resend accepting the mail is not delivery, so the drill counts
only once the mail is in the `OPERATOR_EMAIL` inbox. While `render.yaml` says
`checksPass`, a failed drill on main holds that commit's backend deploy like
any other red check.

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

The structural fix is to stop letting an unrelated job decide. `ci.yml` has a
`Deploy backend (Render hook)` job for that: on a push to main, once Backend,
Frontend and E2E (the checks branch protection requires) have passed, it POSTs
the Render deploy hook with `ref` set to that commit, and fails on any answer
outside 2xx. Until the `RENDER_DEPLOY_HOOK_URL` secret exists it logs a notice,
deploys nothing and passes, so its own check cannot hold today's `checksPass`
deploy. Nothing changes until the owner switches over.

### Switching the backend deploy to the CI hook

Steps 2 and 3 belong together; do them in one sitting.

1. In the Render dashboard, open the `opportunity-filter-engine-api` service,
   then Settings, then Deploy Hook, and copy the URL. It contains a key, and
   anyone holding it can deploy the service, so it goes nowhere except the
   secret in step 2.
2. In GitHub, open the repository's Settings, then Secrets and variables, then
   Actions, and add a repository secret named `RENDER_DEPLOY_HOOK_URL` with
   the URL as its value.
3. Open one PR that changes `render.yaml` to `autoDeployTrigger: off`, and
   merge it. Render's deploy documentation says a deploy-hook call that names
   a commit turns the service's auto-deploys off by itself; the blueprint line
   keeps a later Blueprint sync from turning `checksPass` back on. If the
   service is not synced from the Blueprint, also set auto-deploy to Off in
   its Build & Deploy settings.
4. On the merge commit, check three things: the `Deploy backend (Render hook)`
   job log says "Render accepted the deploy of" that SHA, Render's Events list
   a deploy of that SHA, and `/api/health` reports it as `release_sha` once
   the deploy is live.

A push to main between steps 2 and 3 reaches Render by both paths and builds
twice; that costs one build.

After the switch, a check that branch protection does not require (a refresh
dispatched on main, the alert drill, the Migrations job) no longer holds a
backend deploy. A non-2xx answer from the hook fails the job with the status
code and is not retried; re-run the job from the Actions page once the cause
is fixed. A 404 usually means the hook was regenerated in Render and the
secret still holds the old URL.

To switch back, delete the secret and set `autoDeployTrigger: checksPass` in
`render.yaml` again, and turn auto-deploy back on in the dashboard if Render
left it off.

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
  Reconcile by name, not by version string. `scripts/check_migration_parity.py`
  does that reconciliation offline. `--print-sql` prints the read-only export
  query. Its output goes back in through `--applied` (JSON or `psql --csv`).
  The script reports files production never ran, rows the repo does not have,
  and rows recorded twice, and exits 1 on any of them. It compares md5 where a
  row holds one statement. Run the query against production only with the
  owner's OK (backlog Q4); it has not been run against production yet.
- **`/api/ready` is not wired to `render.yaml`'s `healthCheckPath`** on
  purpose. It gates on corpus freshness, and at the time of writing the corpus
  sat at 94h against a 96h stale bound — pointing the instance probe at it
  would turn a late scraper into a total outage. Wiring it is a deliberate
  owner decision with that consequence understood.

## 6. Environment variables

Each table lists every variable read by the Python code in `backend/` and
`src/`, by the frontend (`next.config.js`, `frontend/scripts/`, `frontend/src/`),
and as `secrets.*`/`vars.*` by the workflows. `tests/test_release_gate.py` scans
those and fails when a variable is read but missing here, or listed here but
read nowhere. The operator tools in the top-level `scripts/` directory are not
scanned or listed (for example `snapshot_reminder.py` reads `RESEND_FROM` and
`OPERATOR_EMAIL`, and `restore_drill.py` reads `DRILL_*`). In the Required
column, `required` means production loses a shipped capability without the
variable. Each backend `required` row has a test that removes it and expects
the failure named in its last column.

### Backend (Render web service)

`WEB_CONCURRENCY` is not read: `render.yaml` starts uvicorn with `--workers 1`,
which takes precedence over it. One worker holds about 1.3-1.5 GB of the
Standard plan's 2 GB, so a second worker would not fit.

| Variable | Required | When missing |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | required | Accounts, cloud save, reminders, saved searches and the incident queue stop. Signed-in requests are treated as signed out. Incident reads and the heartbeat answer 503 and name the variable. Each cron answers `{"status": "skipped", "missing": [...]}`, which fails the workflow's `check_cron_response.py` step. `/api/ready` reports `providers.supabase: missing` without gating. |
| `CRON_SECRET` | required | Every `/api/cron/*` route answers 503 and names the variable. |
| `ADMIN_TOKEN` | required | Every `/api/admin/*` route, and `/api/ready` with a token, answers 503 and names the variable. The release gate cannot collect `open_incidents` or `provider_readiness` without it. |
| `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` | required | The reminders cron sends nothing and lists the missing names, and its workflow step fails. `/api/push/vapid-public-key` answers 503 when no public key is set. |
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | required | The saved-search digest cron sends nothing and lists the missing names, and its workflow step fails. Reminders lose the email fallback and count the row as `no_channel`. |
| `RESTORE_LINK_SECRET` | required | Digests cannot sign unsubscribe links. The digest cron sends nothing, lists the variable, and its step fails. The unsubscribe link answers 503. |
| `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | optional | The first one set is the LLM provider. With none set, AI drafting falls back to templates and nothing reports the fallback (owner question Q44). The release gate's `provider_readiness` still requires an LLM provider. `OPENROUTER_API_KEY` also enables the per-task model table. |
| `OFE_CHAT_MODELS`, `OFE_STRONG_MODEL`, `OFE_MODEL_*`, `OFE_LLM_RERANK_MODEL` | optional | The model defaults in `backend/lib/llm.py` and `src/matcher/config.py` apply. |
| `OFE_GLOBAL_LLM_PER_MIN`, `OFE_GLOBAL_LLM_PER_DAY`, `OFE_GLOBAL_EMAIL_PER_HOUR`, `OFE_COLD_EMAIL_CRITIQUE`, `OFE_COLD_EMAIL_NDRAFT` | optional | Built-in budgets and draft settings apply. |
| `OFE_BLOCKING_AI_MAX_WORKERS`, `OFE_BLOCKING_AI_MAX_PENDING`, `OFE_SINGLE_LLM_TIMEOUT_SECONDS`, `OFE_MULTI_LLM_TIMEOUT_SECONDS`, `OFE_LOCAL_WORK_TIMEOUT_SECONDS`, `OFE_MATCH_TIMEOUT_SECONDS`, `OFE_MATCH_SNAPSHOT_MAX`, `OFE_MATCH_SNAPSHOT_TTL`, `OFE_MAX_REQUEST_BODY_BYTES` | optional | Bounded defaults in `backend/lib/blocking.py`, `backend/routes/matches.py` and `backend/main.py` apply. An unparseable value falls back to the default. |
| `OFE_TRUSTED_PROXY_HOPS` | optional | One proxy hop (Render's) is trusted for the client IP. |
| `OFE_DISABLE_RATE_LIMIT` | optional | Rate limits apply. Set it only in local test runs, never in production. |
| `OFE_MATERIAL_ARCHIVE_ENABLED` | optional | Defaults to on (`1`). The archive still needs the Supabase pair. |
| `OFE_METERING_ENABLED` | optional | Usage metering stays off. |
| `OFE_CORPUS_WARN_HOURS`, `OFE_CORPUS_STALE_HOURS` | optional | `/api/ready` and the admin health check use 72 h to warn and 96 h to call the corpus stale. |
| `OFE_SOURCE_WARN_DAYS`, `OFE_SOURCE_STALE_DAYS` | optional | The defaults in `src/collectors/source_health.py` apply. |
| `OFE_W_ELIG`, `OFE_W_READY`, `OFE_W_UPSIDE`, `OFE_BUCKET_HIGH`, `OFE_BUCKET_GOOD`, `OFE_BUCKET_REACH`, `OFE_HIGH_PRIORITY_TARGET`, `OFE_INTL_UNKNOWN`, `OFE_INTL_UNKNOWN_INTERNSHIP`, `OFE_COURSE_UNKNOWN`, `OFE_COURSE_PER`, `OFE_COURSE_MAX_COUNT`, `OFE_COURSE_RELEVANCE`, `OFE_COURSE_FOCUS_BONUS`, `OFE_INTEREST_BONUS_CAP`, `OFE_EMPTY_INTEREST_MAJOR_BONUS`, `OFE_INTEREST_BONUS_PER_HIT`, `OFE_DEADLINE_PENALTY`, `OFE_GRAD_LEVEL_PENALTY`, `OFE_TOPIC_UNKNOWN_PEN`, `OFE_TOPIC_MISMATCH_PEN`, `OFE_EXPLORE_MAJOR_FLOOR`, `OFE_EXPLORE_READINESS_DROP`, `OFE_STRETCH_K`, `OFE_STRETCH_MID`, `OFE_STRETCH_BLEND`, `OFE_SEMANTIC_TOPK`, `OFE_SEMANTIC_W`, `OFE_SEMANTIC_FALLBACK_CAP`, `OFE_SEASONAL_BOOST`, `OFE_SEASONAL_FACTOR`, `OFE_SEASONAL_MONTHS`, `OFE_SIM_SCALE_TFIDF`, `OFE_ELIG_MAJOR_W`, `OFE_IMPLICIT_MAJOR_PER_HIT`, `OFE_IMPLICIT_MAJOR_CEIL`, `OFE_COLLEGE_AFFINITY_MAX`, `OFE_HOME_SCHOOL_AFFINITY_MAX`, `OFE_RESPONSIVENESS_BONUS`, `OFE_THIN_INVENTORY_FLOOR`, `OFE_LLM_RERANK_TOPK`, `OFE_LLM_RERANK_W`, `OFE_LLM_RERANK_BATCH`, `OFE_LLM_RERANK_CACHE_MAX` | optional | Matcher tuning. The values in `src/matcher/config.py` apply. Most of them feed `_matcher_fingerprint()`, so an override shows up as a different `MATCHER_VERSION`. |
| `OFE_PAYMENTS_ENABLED` | optional | The payments kill switch stays off. `payments` is closed in `release_scope.py` anyway. |
| `FRONTEND_URL` | optional | Email links point at `https://joinalab.com`. |
| `PUBLIC_BACKEND_URL`, `RENDER_EXTERNAL_URL` | optional | Unsubscribe links point at the production Render URL. Render sets `RENDER_EXTERNAL_URL` itself. |
| `EMAIL_POSTAL_ADDRESS` | optional | Digests omit the postal-address footer line. |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | optional | Read only as a fallback for `VAPID_PUBLIC_KEY`. |
| `GITHUB_TOKEN` | optional | GitHub profile imports use the unauthenticated limit of 60 requests per hour, shared by every student behind Render's egress IP. |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`, `SENTRY_TRACES_SAMPLE_RATE` | optional | Errors are not reported to Sentry. |
| `RENDER_GIT_COMMIT`, `OFE_RELEASE_SHA`, `RENDER`, `OFE_ENVIRONMENT` | optional | `/api/health` reports `release_sha: null` and `environment: "unknown"`. The release record then cannot bind the backend (UNVERIFIED). Render sets `RENDER_GIT_COMMIT` and `RENDER` itself. |

### Data refresh (GitHub Actions `refresh-data.yml` and the collector CLIs)

| Variable | Required | When missing |
|---|---|---|
| `OFE_ENRICH_PROFILES` | optional | The per-profile enrichment pass is skipped. The workflow sets it in the first week of each month. |
| `OPENALEX_API_KEY` | optional | OpenAlex calls go out without a key. No workflow sets it. |
| `LLM_MODEL`, `OPENAI_BASE_URL` | optional | LLM tagging is used only when a provider key is set; otherwise the rule-based tagger runs. |

### Frontend (Vercel build; `NEXT_PUBLIC_*` values are inlined at build time)

| Variable | Required | When missing |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | required | The app runs local-only: no sign-in, no cloud save. It logs one console warning and the build does not fail. A production build that fails fast is not implemented yet. |
| `NEXT_PUBLIC_AUTH_PROVIDERS` | required | No OAuth buttons render, so Google sign-in disappears. |
| `NEXT_PUBLIC_SITE_URL` | required | Canonical, Open Graph and sitemap URLs name `opportunity-filter-engine.vercel.app`. On 10-08 production's canonical was `joinalab.com`. |
| `NEXT_PUBLIC_AUTH_EMAIL_MODE` | optional | `dev-echo`: the magic-link form shows the test-sender warning. Set it to `live` to hide the warning. |
| `NEXT_PUBLIC_API_URL`, `BACKEND_URL` | optional | Browser calls use `/api`, which the Next rewrite sends to the production Render URL (`127.0.0.1:8000` outside production). |
| `VERCEL_GIT_COMMIT_SHA`, `OFE_RELEASE_SHA`, `VERCEL_ENV`, `OFE_ENVIRONMENT`, `NEXT_PUBLIC_RELEASE_SHA`, `NEXT_PUBLIC_RELEASE_ENV`, `NODE_ENV` | optional | The page says `data-release-sha="unknown"`, so the release record cannot bind the frontend. Vercel sets the first and third itself. |

### GitHub Actions secrets and variables

| Variable | Required | When missing |
|---|---|---|
| `BACKEND_URL`, `CRON_SECRET` | required | The cron workflows fail their "Require the secrets" step. The release gate does not observe the backend. |
| `ADMIN_TOKEN`, `RESEND_API_KEY` | required | `daily-reminders.yml` fails its secrets step. Without `RESEND_API_KEY`, `alert-drill.yml` fails too. |
| `REFRESH_PAT` | required | `refresh-data.yml` cannot open its data PR and fails. |
| `FRONTEND_URL` | optional | Alert emails lose their dashboard link. The release gate does not observe the frontend. |
| `OPERATOR_EMAIL` | optional | No alert or digest email is sent. The `daily-reminders.yml` alert step prints the alerts to the job log; the other alert steps log that they cannot alert and pass. `snapshot-reminder.yml` fails when a snapshot refresh is due, and `alert-drill.yml` fails. |
| `RENDER_DEPLOY_HOOK_URL` | optional | The `Deploy backend (Render hook)` job in `ci.yml` logs a notice, deploys nothing and passes, and Render's own auto-deploy (`render.yaml` `autoDeployTrigger`) decides. Once the switch-over in §3 sets that to `off`, nothing deploys the backend without this secret. |
| `RESEND_FROM_EMAIL` | optional | A repository variable (`vars.`), not a secret. Workflow emails are sent from Resend's test sender, `JoinALab <onboarding@resend.dev>`. |
