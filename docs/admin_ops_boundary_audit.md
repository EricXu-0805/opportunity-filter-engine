# Feedback / Admin Workflow & Operational Visibility — Phase 1 Audit (W15)

Audited tree: `origin/main` @ `402a808` (post-W14). Audit date: 2026-08-07.
Method: two full-lifecycle audits (feedback → ticket → admin handling;
operational visibility across collectors, drift, notifications, review).

The audit checked what production *actually has on disk*, not only what the
code says — which is how the three silent production defects in §D were found.

## A. Feedback / ticket verdicts

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Feedback form | PARTIAL | 2 fields only (message + optional email); no category/subject despite the copy inviting bug/idea/other; no length cap; `type="email"` never validates (button is `type="button"`, no `<form>`); no timeout escape — a hung insert wedges the button disabled forever |
| 2 | Feedback persistence | PASS | `supabase.ts:1064-1083` — awaited, error-checked, success shown only after a confirmed insert. No optimistic success anywhere |
| 3 | Ticket ID generation | PARTIAL | `feedback.id` is a real UUID PK (`016:11`) but the insert has no `.select()`, so it is never returned, never shown to the user, and used in admin only as a React key |
| 4 | Ticket schema | **FAIL** | Six columns. `status`, `priority`, `assigned_to`, `admin_reply`, `resolution`, `resolved_at`, `closed_at`, `updated_at`, `category`, `subject` — all absent. No indexes despite an ordered admin query |
| 5 | Admin list / detail | PARTIAL / **NOT IMPLEMENTED** | Read-only flat list of the latest 50 (`admin.py:620-710`, `FeedbackSection.tsx:126-152`); no detail view, filter, search, or pagination |
| 6 | Assignment | NOT IMPLEMENTED | No column, endpoint, or control |
| 7 | Priority | NOT IMPLEMENTED | Same |
| 8 | Status workflow | NOT IMPLEMENTED | No status column — every ticket is permanently "new" |
| 9 | Reply handling | **FAIL** | A `mailto:` link (`FeedbackSection.tsx:142`) is the entire reply mechanism: it leaves the product and writes nothing back |
| 10 | Resolution handling | NOT IMPLEMENTED | No resolution/resolved_at/closed_at, no close action |
| 11 | Persistence after refresh | PASS (rows) / **FAIL** (drafts) | Submitted rows are durable; a typed draft lives only in component state and dies on reload |
| 12 | Failed-submission behavior | PASS | Message and email are preserved, `role="alert"` shown, user can retry immediately |
| 13 | Retry / idempotency | **FAIL** | Same-tick double-click is blocked in memory, but there is no idempotency key and no constraint — a retry after an ambiguous failure creates a second ticket |
| 14 | Account isolation | PASS | Insert-own `WITH CHECK auth.uid()`, no SELECT policy at all; merge remaps feedback (017/021/023/025, SQL-tested) |
| 15 | Cross-tab / account switch | PARTIAL | Nothing to leak for drafts (nothing stored); the admin token is per-tab but is **not cleared on user sign-out or account switch**, and Lock does not propagate across tabs |
| 16 | Admin authorization | PARTIAL | One shared static `ADMIN_TOKEN`, constant-time compare, server-side, header-only, fails closed, all 10 routes guarded — but no operator identity, expiry, rotation, revocation, admin-specific rate limit, or failed-attempt logging |
| 17 | Audit logging | NOT IMPLEMENTED | Zero actor+action+timestamp records for any admin operation; `admin_history.jsonl` is data-quality telemetry, not an audit trail |

## B. Operational visibility verdicts

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 18 | Collector failure reporting | PARTIAL → **FAIL in production** | Only `ok`/`error` exist; blocked/timed-out/partial are indistinguishable (a WAF-blocked department returns `[]` and the source still reports **ok** with a smaller count — the UNC case); no incident entity anywhere (`grep incident\|assigned_to\|resolved_at` → 0 hits); the snapshot is rewritten per run **and scoped to that day's shard**, so Monday's failure is simply gone on Tuesday |
| 19 | Data-drift detection | PARTIAL | Real mechanisms exist (4 of 10 counters compared vs ~7 days, shard-shrink guard, `MIN_SCRAPE_RATIO`, tracking freshness gate) but they are one-sided (no spike detection), several are computed and never surfaced (`skipped_partial_scrape`, `fully_stale_schools`, `release_ready`), and the two production-facing ones are broken (§D) |
| 20 | Data-drift review workflow | NOT IMPLEMENTED | `AlertList` is a `<ul>` of strings recomputed per request — nothing can be acknowledged, assigned, or resolved, and no record survives that an alert fired |
| 21 | Notification failure queue | NOT IMPLEMENTED | Failure is five batch integers plus a log line; no per-notification record, no `provider_status` retained (read at `push.py:246` then discarded), no retry/resolve surface |
| 22 | Manual-review workflows | PARTIAL | Exactly one real queue exists (orders). The best-designed one — the W11 truthfulness ledger, with a full row schema and a fail-closed aggregator — has **no automation and no UI** (21 unresolved findings, no owner). `record_conflict` has **zero production callers**; `publication_attribution_status` is absent from all 117 shards; and ~32k records sit below the documented `confidence < 0.6` review threshold that was never implemented |
| 23 | Admin operational actionability | **FAIL** | 12 read-only panes; the only two write actions (confirm-order, trigger-refresh) are unrelated to operational items. Nothing can be marked handled |

## C. What was verified sound (no action needed)

Feedback persistence honesty (no optimistic success), account isolation and
merge coverage, the constant-time admin guard, `orders` as a working
review-queue template, atomic artifact writes, and the W14 notification
ordering (`remind_at` cleared only after provider acceptance).

## D. Silent production defects (found by inspecting live state)

1. **The collector history ledger is never committed.** `collector_status_history.jsonl`
   is absent from both the `/tmp` stash list and the `git add` in
   `refresh-data.yml`, so the runner's copy is destroyed by the rebase.
   The committed file is frozen at **2026-07-25** while refreshes run daily —
   the admin freshness chart has been plotting a fossil.
2. **The "cron died" alert can never fire.** `_opportunities_mtime()` stats
   `opportunities.json`, which is gitignored and never assembled by
   `render.yaml`; in production the path does not exist, so the function
   always returns `None`, the stale-data alert is unreachable, and
   `FreshnessBanner` never renders.
3. **The 7-day baseline is poisoned.** `admin_history.jsonl` lives on Render's
   ephemeral disk and resets to the committed file on every deploy — a
   12-row file whose newest entry is **2026-05-31** describing a corpus of
   1,916 records. Against today's ~132k corpus the daily operator email
   reports permanent, guaranteed-false regressions (e.g. `empty_keywords`
   +340,000%). That is worse than no alerting.
4. **Cron response bodies are discarded.** `curl -sf` sees only the status
   line, so W14's `bookkeeping_failed` / `row_errors` counters and the
   digest's `status: "partial"` never fail the job — the W14 code comment
   promising "the operator alert fires on the response counter" describes an
   alert that does not exist.

## E. Storage decision

Human-mutable state (ticket handling, incident acknowledgement, assignment,
resolution) must live in **Supabase**: the backend on Render cannot commit to
git, and `admin_history.jsonl` already demonstrates what happens to
runtime-written files on an ephemeral disk. Detection stays where the data
is — the backend reads the committed artifacts (`collector_status.json`,
its history ledger, `professor_tracking.json`) on a cron ping and upserts
incidents, so the scraper never needs database credentials.

Rather than four parallel systems, one `ops_incidents` table with a `kind`
discriminator: the operator workflow (see it, assign it, act, resolve with a
recorded decision) is identical for collector failures, drift alerts,
notification failures, and manual-review items.
