# Favorites / Tracker / Dashboard / Auth Integrity — Hardening Report (W16)

Follow-on to `docs/data_integrity_boundary_report.md` (W14) and
`docs/admin_ops_boundary_report.md` (W15). Baseline `origin/main` @ `059c086`.

W14 closed this boundary and W15 made operational failures visible. This pass
re-audited the **same** boundary against a finer specification, verified the
prior guarantees still hold, and closed the residuals those reports had
explicitly left open — plus one defect W14 missed.

## What was already true (verified, not rebuilt)

Re-checked against current main and confirmed intact:
`getInteractionsFull` throws rather than returning a confident empty map (with
the documented unconfigured-Supabase carve-out); `toggleFavorite` treats a
duplicate key as success; `trackInteraction` throws; notes/reminders still
cannot create a status (UPDATE-only + exact-one-row check + owner-token
revalidation — now *stronger* than W14 documented); Flow B verdict-based token
clearing, 60-minute TTL, and the orders merge; cron concurrency groups and
response-body checking.

Two W14 claims are now stale prose because the code improved: account
isolation moved from one shared `useAuthUid` hook to per-surface
generation-namespaced owner tokens, and `updateInteractionDetails` throws
rather than returning a boolean. Both corrected in this pass.

**Spec §9 (notes/reminders must not count as progress) was already satisfied**
— the dashboard funnel aggregates `status` only; reminders are counted
separately and framed as pending. No change needed.

## 1. Cross-account write leak — the defect W14 missed

`ProfessorUpdatesSection` had an empty-dependency load effect and was rendered
unkeyed, so it never reacted to an account change. After a cross-tab switch it
kept rendering Account A's follow feed while the rest of the dashboard
cleared — and `markAllRead` then derived cursors from **A's on-screen events**
and wrote them under **B's JWT**, persisting A's event ids as B's read state.
Every other private write in the app captures an owner token; this one did not.

Fixed by adopting the established pattern: an identity generation that orphans
in-flight work and refetches on every real account transition, plus an
`OwnerToken` captured before the write and re-checked **after** the await so a
mid-write switch cannot paint A's state onto B. Mutation-tested — removing the
guard fails the test.

Adjacent fix: `markAllRead` had no `catch`, so a failed write produced an
unhandled rejection and left the unread badge unexplained. It now reports the
failure and never claims the events were read.

## 2. Notification ambiguity (spec §10-§12)

W14 established that a timeout is never success and `remind_at` clears only
after provider acceptance. The residual it recorded — a timeout *after* the
push service already accepted — was worse than described: the same run also
fired the email fallback, so an ambiguous push produced a push **and** an
email immediately, not merely a next-day repeat.

- **Ambiguous is now its own outcome**, distinct from failed. An ambiguous
  push suppresses the same-run email fallback and records an incident whose
  detail carries `outcome: ambiguous`, `may_have_been_delivered`,
  `email_fallback_suppressed`, `remind_at_retained`.
- **Protocol-level idempotency**: RFC 8030 `Topic` headers (SHA-256 → 32 chars
  of the URL-safe base64 alphabet, the spec ceiling) plus an explicit TTL are
  now threaded through `safe_webpush`. A same-topic message *replaces* a
  pending undelivered one at the push service — collapsing the duplicate at
  the protocol layer instead of relying on the service-worker `tag`, which
  only helps while the first notification is still on screen. This also fixed
  a latent bug: pywebpush defaults `ttl=0`, meaning "deliver now or drop", so
  reminders to sleeping devices were being silently discarded.
- **`remind_at` is retained on ambiguity (at-least-once), deliberately.**
  Clearing it would be at-most-once and would silently drop reminders that
  genuinely never arrived — the worst failure for a feature whose only job is
  to remind. The repeat carries the same Topic, so it replaces rather than
  stacks.
- **Resend `Idempotency-Key`** on both email paths, derived from the send's
  natural identity and hashed so device/search identifiers stay out of a third
  party's request logs.
- Provider acknowledgment is still never conflated with delivered/opened
  (nothing tracks opens); the internal `last_delivered_at` write site and the
  operator-facing notes are now worded as *accepted*, which is what they mean.
- Digest failures now record incidents too (W15 gave push durable records; the
  digest had none).

## 3. Dashboard truthfulness (spec §13-§15)

- **The only user-facing freshness signal was dark in production.** The public
  `/opportunities/stats/summary` computed `last_updated_at` from the gitignored
  work file that `render.yaml` never assembles — byte-for-byte the bug W15
  fixed in the admin route, left unfixed on the public one. Both now share
  `backend/lib/corpus_freshness.py` so they cannot diverge again.
- **State vocabulary**: stat tiles rendered loading, error, and unknown
  identically as an em-dash. Each is now distinct (`data-state`
  loading/error/ready/unknown), with a real `0` still rendering as `0` — the
  W14 guarantee that must not regress.
- **MISSING is reported, not swallowed**: saved/tracked ids the corpus could
  not resolve now surface an explicit "N couldn't be loaded" note, matching
  what the favorites and tracker pages already did. Previously they vanished —
  and when *every* item failed to resolve, the UI asserted "no deadlines among
  your saves", presenting a load failure as a verified fact about the user's
  data.
- **STALE is a user-facing state**, with an explicit boundary reusing the
  existing admin thresholds (warn ≥72h, stale ≥96h) and an explicit unknown
  when no timestamp exists. Nothing bumps a freshness timestamp merely because
  a page was loaded — verified against the spec's explicit prohibition.
- A retry affordance was added, because an error state with no way forward is
  a dead end.

## 4. Tests

New: `tests/test_notification_idempotency.py` (28), `tests/test_corpus_freshness.py`
(11), 3 account-isolation tests on `ProfessorUpdatesSection` (one
mutation-verified), 14 dashboard state/freshness/missing tests. Existing W14/W15
pins all still pass.

Requirement map: §1-2 anonymous migration and §3-4 isolation/cross-tab →
verified intact (W14 suites + the new isolation tests); §5-6 Flow B and retry →
verified intact; §7 favorites → verified (removal is pessimistic with a visible
error and retry); §8-9 tracker/notes → verified intact, funnel counts status
only; §10-12 notifications → new idempotency suite; §13-15 dashboard → new
state, missing, and freshness tests.

## 5. Remaining risks

1. **Digest ambiguity window**: an ambiguous digest failure retries the next
   night, outside Resend's ~24h idempotency-key window, so a duplicate is still
   possible. Stamping the throttle on ambiguity would instead silently skip a
   week's digest; for an opt-in weekly summary a visible, incident-recorded
   duplicate is the better failure. Documented in code, not hidden.
2. **Per-notification lifecycle state** is still implicit (`remind_at` +
   counters + incidents) rather than an explicit queued/sending/acknowledged
   column. The ambiguity is now handled correctly, but a true state machine
   would need a migration.
3. **Freshness thresholds are mirrored** between the admin banner and the
   dashboard rather than imported from one module (ownership boundary during
   this pass); pinned by test so divergence surfaces.
4. Multi-tab storage-clear races remain the documented accepted residual from
   W14, unchanged.
5. `getOpportunitiesByIds` now has no app callers; removal belongs to whoever
   owns `lib/api.ts`.
