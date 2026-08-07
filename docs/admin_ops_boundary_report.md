# Feedback / Admin Workflow & Operational Visibility — Final Report (W15)

Companion to `docs/admin_ops_boundary_audit.md`. Implemented on
`feat/admin-ops-boundary`; audit baseline `origin/main` @ `402a808`.

## Invariants, enforced

```text
successful UI submission = durably persisted ticket + stable ticket UUID
Admin action             = authorized mutation + durable persistence + traceable state
system failure / review  = visible + actionable + persistent + resolvable
```

## 1. Ticket schema and UUID behavior

`feedback` was six columns with no lifecycle. Migration `026` adds category,
subject, status (`open|triaged|in_progress|waiting_on_user|resolved|closed`),
priority (`low|normal|high|urgent`), `assigned_to`, reply fields, resolution
(7-value taxonomy), `resolved_by/at`, `closed_at`, `updated_at`, and
`client_token`; plus indexes the ordered admin query never had.

The UUID PK always existed but was never returned. `submitFeedback` now does
`.insert(...).select('id').single()` and the widget shows a short reference
with a copy button (copying the full UUID). A new `feedback_select_own` RLS
policy lets a submitter read their own ticket — which is what makes the
returned id meaningful rather than decorative.

## 2. Submission semantics and draft preservation

Success was already shown only after a confirmed insert; that is unchanged.
What changed: the draft (message, email, category, subject, and the
idempotency token) now persists to `localStorage` under a registered
user-scoped key, restores on mount, survives every failure path, and clears
**only** on confirmed success. A 15s timeout escape means a hung insert lands
in the error state with the draft intact instead of wedging the button
disabled forever. Email format is validated inline; the textarea is capped
and counted; the widget is a real `<form>` so Enter submits.

## 3. Retry / idempotency

The widget mints a `crypto.randomUUID()` token per composed message and
reuses it across retries, regenerating only after success. A partial unique
index on `(device_id, client_token)` makes a duplicate physically
impossible. Critically, a `23505` collision is treated as **success**: the
ticket already exists from an attempt whose response was lost, so the client
re-reads it and shows the same reference rather than a false error or a
second ticket. Admin mutations are read-then-write and a no-op writes
nothing.

## 4. Admin assignment, priority, status, reply, resolution

All five are real persisted columns behind `PATCH /admin/feedback/{id}` and
`POST /admin/feedback/{id}/reply`, each writing an append-only
`feedback_events` row. Rules the API enforces (the DB CHECK is the backstop,
not the first line — unknown enums 400 before any network call):

- resolving or closing **requires** a resolution — no silent closes;
- a resolution may not sit on a non-terminal ticket;
- reopening clears the decision and carries the retracted verdict into the
  event note;
- `resolved → closed` keeps the original `resolved_at` (when it was decided
  is not when it was filed);
- **a reply never changes status or resolution** — they are different acts.

Reply delivery is honest per the W14 notification invariant: `emailed` only
on provider acceptance, otherwise `stored` or `email_failed`. The UI renders
exactly that state and the string "sent" appears nowhere — a
dictionary-level test asserts this in both locales.

## 5. Persistence and refresh

Every mutation re-reads from the server after confirmation; the console
renders server state, never optimistic state. A failed mutation shows an
inline error and leaves the prior state visible. Reply drafts survive failed
saves.

## 6. Account isolation and authorization

Feedback RLS: insert-own, select-own, **no user UPDATE/DELETE** — a client
cannot mark its own ticket handled. `feedback_events`, `ops_incidents`, and
`ops_incident_events` have RLS enabled with **no policies at all**:
operator-only, reachable exclusively via the service-role key. SQL scenarios
prove a client's UPDATE matches zero rows and the audit log reads as empty.

Admin authorization keeps the constant-time shared-token guard, now with
failed-attempt logging, a dedicated `/api/admin` rate bucket (30/60 rather
than the inherited 60/60), and a `require_admin` FastAPI dependency for new
routes. `X-Admin-Actor` attributes every audit row — **self-declared, not
proven**, since all operators share one token; the code, the docstrings, and
the UI hint all say so plainly, and an operator may not claim the reserved
`detector` label.

## 7. One operational model

Migration `027` creates `ops_incidents` with a `kind` discriminator
(`collector_failure | data_drift | notification_failure | manual_review`)
because the operator workflow is identical for all four. Detectors upsert
through `record_ops_incident` keyed on `dedup_key`; operators act through
`/admin/ops/incidents`.

The load-bearing invariant: **re-detection can only ever bump counters.** The
RPC cannot change status, assignment, or resolution, so a new collector run
merely starting never clears an unresolved failure, and a later successful
run never silently suppresses a drift alert. Recovery is separate evidence:
`record_ops_recovery` sets `failure_state='recovered'` and auto-resolves
**only when the caller opts in** — collector incidents do; drift never does,
because §17 requires data to return to expected state or a reviewer to
accept the change. A recurrence after closure reopens with the stale verdict
cleared.

Visibility now covers: collector failures with `failed|timed_out|blocked|partial|recovered`
classification and truncated evidence; `fatal_error` (previously rendered as
"no data yet"); `fetched`-count drift against the prior history entry; the
professor-tracking release gate; and per-notification failures recorded from
`push.py` with `provider_status` preserved (previously read and discarded)
and no endpoint or message content stored.

Manual review is entity-linked (`entity_type`/`entity_id`/`field`) and its
decisions deliberately include `unknown`, `conflicting`, and
`needs_more_evidence` — an ambiguous case must be allowed to stay ambiguous
rather than being forced into verified/rejected.

Retry records an operator-initiated attempt and returns
`delivery_claimed: false, resolved: false`; the UI says "retry recorded —
outcome unknown until a detector observes the next run".

## 8. Silent production defects fixed

1. **Collector history is now committed** — added to both the rebase stash
   and the `git add`, so failures survive the shard rotation instead of the
   ledger freezing (it had been stuck at 2026-07-25).
2. **The "cron died" alert can fire** — freshness now reads the committed
   snapshot's own run timestamp (with shard-mtime fallback) instead of a
   gitignored work file that never exists on Render.
3. **The poisoned baseline is refused** — a baseline older than 21 days is
   rejected and reported as `baseline_unavailable` rather than manufacturing
   permanent false regressions against a months-old snapshot.
4. **Cron bodies are checked** — `scripts/check_cron_response.py` fails the
   step on `bookkeeping_failed`, `row_errors`, `failed`, `incident_errors`,
   or `status: partial`, so W14's counters finally reach the operator alert.
   Both cron workflows gained the checkout they needed to run it.

## 9. Audit trail

`feedback_events` and `ops_incident_events` are append-only with actor,
action, from/to values, note, and timestamp. Events are written **after** the
mutation confirms — a trail asserting a change that then failed is worse than
a missing row — and a failed audit write surfaces as `audit_log_error` on an
otherwise-successful response rather than a misleading 5xx.

## 10. Tests

- **SQL** (`supabase/tests/ops_and_tickets_test.sql`, wired into the
  Migrations CI job): 7 scenarios — ticket lifecycle with reply≠resolution
  and no-silent-close, submission idempotency, per-account isolation,
  operator-owned handling state, collector dedup/no-stomp/verified-recovery/
  reopen, drift-never-auto-closed, ambiguity preserved.
- **Backend**: `tests/test_ops_incidents.py` (57), `tests/test_ops_plumbing.py`
  (16), +54 in `tests/test_backend_api.py`.
- **Frontend**: 22 widget + 8 `supabase-feedback` + 92 admin, including
  en/zh key parity and the no-"sent" assertion.

Requirement map (36 behaviors): 1-6 submission → widget + supabase-feedback +
SQL idempotency; 7-12 persistence → backend PATCH/reply suites + admin
refetch tests; 13-16 isolation → SQL RLS scenarios + the existing
identity-owner/merge suites; 17-19 authorization → 401/503 locks on every
route + RLS no-policy proofs; 20-23 collector → SQL scenario 4 + ops-scan
tests; 24-27 drift → SQL scenario 5 + drift detector tests; 28-31
notifications → push.py incident recording + retry-claims-nothing tests;
32-36 review → SQL scenario 6 + resolution-taxonomy tests.

## 11. Remaining risks

1. **Shared-token admin auth.** Actor attribution is self-declared; a real
   per-operator identity (Supabase role or per-operator tokens) is the honest
   next step. Everything else in the audit trail is durable and tamper-
   resistant, but attribution is only as strong as the shared secret.
2. **Detectors cover what artifacts expose.** Blocked *departments* still
   return `[]` inside an otherwise-successful source, so a partially-blocked
   collector can report `ok` with a smaller count; drift on `fetched` is the
   backstop. Making `faculty_graph` return per-dept failure records is the
   follow-up that would close it properly.
3. **Ops scan is cron-driven**, so incidents appear on the next scan rather
   than instantly.
4. **The truthfulness sample ledger** (21 unresolved findings) is not yet
   auto-ingested into the queue — the schema supports it; the importer is
   follow-up work.
5. **`admin_history.jsonl` still lives on ephemeral disk**; the baseline
   guard now refuses fossils rather than trusting them, but durable
   data-quality history (committing it from the cron) remains open.
