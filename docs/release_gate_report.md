# Production Release Gate — Final Report

**Decision: NO-GO.** This is the correct and expected outcome, not a failure of
the work. The gate exists to refuse a release that cannot prove itself, and
six of its gates depend on infrastructure evidence that cannot be produced
from inside this repository.

Baseline `origin/main` @ `1029f03`. Gate: `scripts/release_gate.py`
(exit 0 = GO, exit 1 = NO-GO). Ledger: `data/releases/CURRENT.json`.

## Phase 1 — Audit verdicts

| # | Area | Verdict |
|---|---|---|
| 1 | Release process | NOT IMPLEMENTED — 0 git tags across 1,073 commits; no CHANGELOG, VERSION file, or release workflow |
| 2 | SHA / version tracking | FAIL → **fixed** — `API_VERSION` was a fossil never bumped since its introducing commit, and its test was tautological (asserted the constant equals itself) |
| 3 | Backend CI | PARTIAL → **fixed** — `pip-audit` carried `continue-on-error`; 53 tests conditionally skip when the corpus work file is absent, and `assemble()` had no floor, so an empty corpus could pass green |
| 4 | Frontend CI | PARTIAL → **fixed** — `npm audit` non-blocking, `lint --if-present` silently passable, and CI installs with `npm ci` while Vercel used `npm install` (33 caret ranges → production could run untested versions) |
| 5 | Migration validation | PARTIAL — strong chain replay on a throwaway cluster, but never runs against prod or a prod-like clone; no idempotency test, and 3 of 33 migrations would fail a live re-run; history contract pins 29 of 33 |
| 6 | E2E | PARTIAL — ~149 tests against a production build, but Chromium-only (the defined mobile project never runs), a Supabase stub (no real auth/RLS), and the authenticated admin block skips in CI |
| 7 | Readiness endpoint | NOT IMPLEMENTED → **built** — `/api/health` returned a literal constant, and `_lifespan` swallows every warmup exception, so a failed corpus load booted green behind a 200 |
| 8 | Render | PARTIAL — `autoDeployTrigger: checksPass` is the one real deploy control; no `healthCheckPath`, no readiness gate, no branch pin |
| 9 | Vercel | FAIL → **partially fixed** — deployed on every push to main without waiting for CI, asymmetric with Render |
| 10 | Supabase migration process | FAIL — fully manual dashboard SQL; three mutually contradictory applied-migration ledgers (prod history 3 of 33, RUNBOOK 6, contract test 29); none authoritative |
| 11 | Backup | NOT IMPLEMENTED — zero automated backup anywhere; whether Supabase PITR is enabled cannot be determined from the repo |
| 12 | Restore | NOT IMPLEMENTED — no procedure, and no evidence a restore was ever tested |
| 13 | Scheduler architecture | PARTIAL → **improved** — well-hardened (concurrency groups, response-body checking), but all four crons went silently green when secrets were unset, and `ops-scan` had no alert at all |
| 14 | Dead-man monitoring | NOT IMPLEMENTED — every alert is a step *inside* a run, so if the workflow itself stops, nothing fires. This already happened: the refresh failed 7 runs in a row before anyone noticed, and three timeout-cancellations alerted nobody |
| 15 | Promotion | NOT IMPLEMENTED (environments) / PARTIAL (flags) — no staging, canary, or gradual rollout; release-scope flags are the de-facto mechanism, and the backend and frontend tables had drifted |
| 16 | Rollback | FAIL — 11 lines scoped to one April session; migrations are forward-only with 0 down scripts |

**The most consequential audit finding is a gate weakness, not a missing gate:**
`tests/conftest.py` has an autouse fixture forcing `feature_enabled` → True for
every module that does not opt out. Exactly one of ~126 test modules opts out.
So the great majority of the suite validates the flags-ON surface rather than
what ships. "CI green" is therefore weaker evidence about production behavior
than it looks. This is recorded in `docs/RELEASE.md` §5 and left as tracked
debt rather than changed under a release-gate PR — narrowing it will move many
tests and deserves its own reviewed change.

## Phase 2 — What was built

**SHA freeze and provenance.** `backend/lib/build_info.py` resolves build
identity from `RENDER_GIT_COMMIT` → `OFE_RELEASE_SHA` → **null**. Both sides
shape-validate (`^[0-9a-f]{7,40}$`), so `""`, `"unknown"`, `"main"`, and an
unexpanded `"$VERCEL_GIT_COMMIT_SHA"` resolve to unknown rather than being
published as provenance. No `git rev-parse` and no subprocess anywhere — a
locally computed SHA would say nothing about what is running, and tests assert
the source contains no such call. `/api/health` gained `release_sha`,
`environment`, `started_at` additively (its three existing consumers see a
byte-identical `status`/`version`). The frontend inlines the SHA at build time
onto `<html data-release-sha>`, so the deployed commit is readable with a
single `curl | grep`.

**Same-SHA enforcement.** The gate refuses short SHAs and tags as ambiguous,
refuses a SHA absent from the repo, refuses local evidence from a dirty
worktree or a mismatched HEAD, and marks any external or CI evidence carrying a
different `release_sha` as FAIL rather than PASS.

**Non-skipped green gate.** Required checks report `passed / failed / skipped /
not_run` separately; a `SKIPPED` or `NEUTRAL` required check is explicitly not
a pass, and an unregistered check is `NOT_RUN`. The decorative audit steps moved
out of the required jobs into a non-required `security-advisory` job that fails
honestly, so a required job no longer contains a step whose failure is ignored.
`assemble()` gained a 1,000-record floor (real corpus: 131,998) so an empty
corpus can no longer let the data-quality gate pass vacuously.
`truthfulness_audit.py report` now exits 1 on NO-GO — it previously returned 0
even when it had decided NO-GO, so its own verdict could not gate anything.

**Truthful `/api/ready`.** Five gating checks (corpus non-empty; a real
published generation, not the cold `"0.000000"` sentinel; TF-IDF fitted and
similarity matrix published; ranker bound to the *current* corpus generation
via the non-blocking probe; freshness known and not stale) returning 503 with
machine-readable reason codes. Unknown freshness is a failure, never a pass.
Providers, matcher identity, and the tracking release block are **reported and
never gating** — every provider degrades by design, and gating on one would pull
all reads out of rotation for a feature that already falls back cleanly. Two
tiers: anonymous gets a boolean plus coarse codes; `X-Admin-Token` unlocks
detail, so the probe cannot become a public inventory of configured providers.

**Freshness consolidated.** The boundary existed in three disagreeing places
(docs 72/96, frontend banner 72/96, backend 96/192). It now lives once in
`corpus_freshness_thresholds()` at the documented 72h/96h, env-overridable.
The old backend value meant the operator alert fired a full extra cron cycle
after the docs and the UI had already called the data stale.

**Scheduler honesty.** The three endpoint crons now fail on a missing required
secret instead of exiting 0 (a revoked secret was an invisible green no-op),
`ops-scan` gained the operator alert it never had, and all four alert on
`failure() || cancelled()` so a timeout-cancellation is not silence.
`check_cron_response.py` now exits 1 on empty, non-JSON, and non-object bodies.

**Promotion and rollback** are defined in `docs/RELEASE.md` with entry criteria,
required evidence, and stop conditions per stage; recovery is in
`docs/DISASTER_RECOVERY.md` with an explicit, empty drill table.

## Phase 3 — Tests

`tests/test_release_gate.py` (31), `tests/test_readiness.py` (48),
`tests/test_build_info.py` (52), `tests/test_ci_gate_honesty.py` (8),
plus updated shard-floor, truthfulness-exit, and cron-checker suites, and 20
frontend `build-info` tests. Two verification techniques worth noting: the CI
honesty tests were run as a **negative control** against `git show HEAD:` copies
of the pre-fix workflows (6 of 8 fail there, proving they detect the defect
rather than merely describing the fix), and `test_removing_any_single_evidence_returns_to_no_go`
drops each evidence key in turn and asserts the verdict returns to NO-GO — so no
single gate can be quietly dropped without the decision changing.

## Phase 4 — Ledger

`data/releases/CURRENT.json`, regenerated at the release SHA. Current summary:

```
passed=4  failed=2  unverified=15  skipped=0  not_run=0
DECISION: NO-GO
```

Two gates FAIL on evidence the repo *does* have — both are real findings the
gate caught mechanically:

1. **`flag_parity`** — `concierge_pay_qr` and `microsoft_school_auth` are
   frontend-only flags with **no server-side gate**. The backend test asserted
   flag *values* but not *shape*, so this drift was invisible.
2. **`tracking_release_ready`** — the committed artifact stores
   `release_ready: true` but carries only 5 of the 9 checks its producer now
   requires, so the strict contract refuses it. The gate reports the strict
   verdict, not the stored boolean.

Fifteen gates are `UNVERIFIED` — distinct from FAIL on purpose. Both block, but
`UNVERIFIED` means "no evidence either way", which tells an operator this needs
infrastructure access rather than a code fix.

## First real finding: the honest audit immediately surfaced 3 CVEs

Moving `pip-audit` out of the required job and letting it fail honestly paid
off on the very first run. It reports:

```
cryptography 48.0.1  PYSEC-2026-3552  fix: 50.0.0
cryptography 48.0.1  PYSEC-2026-3553  fix: 49.0.0
cryptography 48.0.1  PYSEC-2026-3554  fix: 49.0.0
```

These were present before this change and silently ignored by
`continue-on-error: true`. `cryptography` is not incidental here — it backs
VAPID signing for web push.

The advisory job is deliberately **non-required**, so this does not block the
merge of the gate itself; a new upstream CVE should not freeze unrelated
releases. But it **is** a blocker for an actual production release, and it is
recorded as one below. The remediation is a major-version dependency bump
(48 → 49/50) that deserves its own reviewed change with the full suite run
against it, not a drive-by edit inside a release-gate PR.

## Remaining blockers to a GO

**Requires infrastructure access (cannot be produced from this repo):**
`render_canary`, `vercel_canary`, `supabase_canary`, `api_ready` on a deployed
instance, `open_incidents` rollup, `backup`, `restore`, `scheduler` run history,
and `dead_man` — the last requires provisioning an external monitor and testing
its alert path, which is the only structural fix for the "workflow itself
stopped" failure mode that has already bitten this project twice.

**Requires a code or data change:** the two FAILs above; the three
`cryptography` CVEs (PYSEC-2026-3552/3553/3554, fix 49.0.0+); the
`conftest.py` feature-flag scope; migration idempotency for the three bare-DDL migrations;
the stale migration-history contract; and reconciling what is actually applied
to production.

**Partially solved, honestly:** Vercel production still builds on a fresh push
before CI concludes. The ignore-step gate skips a build whose required checks
are already red, but CI takes 20–35 minutes and Vercel evaluates the step once,
seconds after the push — so on the normal path it falls open with a loud
`UNGATED` log rather than failing closed and freezing all production deploys.
A complete fix needs Vercel-side promotion from CI with a token, which
`vercel.json` cannot express.

**Not wired on purpose:** `render.yaml` has no `healthCheckPath`. Pointing the
instance probe at a freshness-gating `/api/ready` would convert a late scraper
into a total outage — measured live at 94h against a 96h bound, two hours of
margin. That wiring is an owner decision with the consequence stated, not a
side effect of this change.
