# Favorites / Tracker / Dashboard / Auth Data-Integrity — Final Report (W14)

Companion to `docs/data_integrity_boundary_audit.md`. Implemented on
`feat/data-integrity-boundary`; audit baseline `origin/main` @ `81fa079`.

## The invariant, enforced

```text
No ownership proof          → no migration        (bound, single-use, atomic grants)
No explicit event           → no completion status (triple-guarded, unchanged)
No provider acknowledgment  → no cleared reminder  (verified + retried bookkeeping)
No fresh present data       → no zero dashboard    (errors throw; zeros mean zero)
```

## 1. Anonymous migration (Flow B)

The core was audited sound and is unchanged: in-place linking (same uid) is
the default path; existing-account sign-ins mint a mandatory email- or
secret-bound, single-use, tombstoned grant redeemed in one atomic
transaction, replayed end-to-end in CI. W14 closes the data-loss edges:

- **Orders now merge** (migration `025`): purchases made while anonymous
  follow the account instead of being orphaned on the tombstoned uid.
  Flow B suite scenario 8 pins it (union, drain, summary count).
- **Grant TTL 15 → 60 minutes** (same migration): real magic-link latency
  regularly exceeded 15 minutes, and an expired grant strands the anonymous
  data forever. Scenario 8 also pins that a 30-minute-old grant redeems.
- **Verdict-based token clearing**: the client kept a one-shot token that it
  deleted *before* the RPC — a transport failure orphaned the data. The token
  is now cleared only on a definitive server verdict (success, `invalid
  grant`, `already used`, `expired`, `unbound` — enumerated from the SQL),
  kept on transport errors with one bounded retry, so the next callback/load
  can still redeem.
- **Stale-grant expiry**: grants are stamped `minted_at`; an abandoned stash
  older than 60 minutes no longer defers user-scoped storage clears, and
  sign-out drops it. Legacy stash shapes stay compatible.
- **Honest attachments caveat**: the merge summary now says attachments
  "could not be transferred and are no longer accessible from this account"
  (en+zh) instead of implying recoverability.

Residuals (documented, not silent): attachments re-homing needs a
service-role Storage job (data retained, inaccessible); no post-sign-in
"unmigrated guest data" prompt exists; consumed/expired grant rows have no
purge job (RLS-unreachable either way).

## 2. Account isolation & cross-tab safety

RLS held everywhere (17 user-owned stores audited). The gap was client
surfaces that fetched once and never reacted to a uid change: stale Account-A
data kept rendering and new writes executed under Account B's JWT. Fix:
one shared `useAuthUid()` hook (epoch-based, StrictMode-safe, absorbs the
initial null→uid resolution) now drives clear-and-refetch on every uid switch
across dashboard, favorites, tracker, results, and opportunity detail.
localStorage choke-point clearing was already sound and is unchanged.

## 3. Retry & idempotency

- Flow B: already idempotent (single-use grant, atomic, tombstoned) — now
  also transport-safe client-side (above).
- `toggleFavorite`: duplicate-key insert (double-click/retry) is idempotent
  success, no longer a false "local-only" downgrade.
- `trackInteraction`: upsert keyed `(device_id, opportunity_id)` was already
  idempotent; it now throws on failure (including no-session) instead of
  faking success, and every optimistic surface reverts on throw.
- `updateInteractionDetails` returns success; TrackerPanel shows "Saved" only
  when true, with an explicit failed-save + retry state otherwise.
- Status-change log remains trigger-owned (unforgeable, transition-only).
- Residual: `saved_searches` has no unique key (duplicate names possible on
  deliberate re-submit; low-stakes, documented).

## 4. Tracker truthfulness

Audited PASS and unchanged: notes/reminders are UPDATE-only and cannot create
a status (triple-guarded, test-pinned); reminder suggestions set dates only;
`contacted` comes only from the explicit cold-email attestation (W12); the
history log records only genuine transitions.

## 5. Notification lifecycle

Scan-and-send (no queue) with correct acknowledgment ordering — `remind_at`
was already cleared only *after* a provider-accepted push or email. W14 makes
the bookkeeping as truthful as the send:

- **`contacted` reminders fire** — the cron's status filter predated W12 and
  silently excluded them (set-but-never-delivered, never cleared).
- **Verified, retried bookkeeping**: the `remind_at` clear is checked and
  retried once; persistent failure is a loud `bookkeeping_failed` counter
  (operator-alerted) instead of a silent daily duplicate.
- **Per-row isolation**: one row's transport error no longer aborts the
  batch (at-least-once for that row, never lost reminders for the rest).
- **Fallback hardening**: email-fallback catches transport exceptions, not
  just HTTP errors — a Resend timeout can no longer 500 the whole cron.
- **Digest duplicate window closed**: the post-send throttle stamp is
  retried and its failure recorded as a distinct "will duplicate next run"
  error instead of a buried generic row error.
- **Cron overlap**: both workflows now run under `concurrency` groups
  (queue, never cancel a half-done batch).
- Provider-accepted ≠ opened/acted: nothing tracks or claims opens
  (verified; unchanged).

## 6. Dashboard truthful states

- `getInteractionsFull` now throws on session/load failure (and flags
  storage status); an empty Map *means* zero rows. The dashboard's error
  branches are reachable through the real library for the first time —
  funnel/reminders/tracker render error states, never false zeros.
  One deliberate carve-out: an UNCONFIGURED Supabase is the documented
  local-only degraded mode (storage banner discloses it; the E2E environment
  runs this way) — there, zero synced rows is the truthful state and writes
  no-op by design. Only a configured environment failing is an error; both
  halves are unit-pinned (`supabase-localmode.test.ts` vs the configured
  suites).
- /favorites, /tracker, and the saved-searches section gained real error +
  retry states (previously `catch {}` → false empty / silent vanish).
- The favorites email export fails loudly instead of exporting blank
  status columns.
- Professor updates: `available: false` (artifact absent/unpublished) is now
  a distinct "temporarily unavailable" state instead of masquerading as
  "no updates yet" — the old conflation was test-pinned and the pin is
  replaced. Per-event `verified_at` display unchanged.
- /results was already the model (loading/error/empty separated) — untouched.
- Freshness: user-owned metrics are live queries (fresh by construction);
  corpus-freshness surfacing beyond the admin banner remains a product
  follow-up, now with the unavailable-state plumbing to hang it on.

## 7. Tests

Backend: `tests/test_data_integrity_boundary.py` (11 — contacted filter +
delivery, bookkeeping counted/retried/non-fatal, row isolation, fallback
timeout, digest stamp retry-and-loud, workflow/migration tripwires) + Flow B
scenario 8 (orders + TTL) in the CI-replayed SQL suite. Frontend: new
`supabase-interactions` (10), `supabase-favorites`, favorites/tracker page
error+retry suites, `use-favorites-data` uid-switch tests; updated pins that
certified untruthful behavior (ProfessorUpdates conflation, TrackerPanel
void-save "Saved", digest resend). Requirement map (27 behaviors):
1-5 migration → Flow B SQL suite s1-s8 + supabase-merge/identity-owner tests;
6-10 isolation → RLS suites (existing) + uid-switch tests + choke-point
tests (existing); 11-14 retry → 23505/upsert/revert tests + trigger
transition pins (existing); 15-18 tracker → existing triple-guard pins +
save-honesty tests; 19-22 notifications → boundary tests above (queued ≠
sent was already pinned: failure keeps `remind_at`); 23-27 dashboard →
error-vs-zero suites + unavailable-state tests (freshness: distinct
unavailable state; corpus staleness display documented residual).

Results at close-out: backend and frontend suites green, tsc/eslint/ruff
clean (authoritative run: PR checks).

## 8. Remaining risks

1. Attachments re-homing job and unmigrated-data prompt (product follow-ups).
2. `saved_searches` duplicate names on deliberate re-submit.
3. Push/email at-least-once residual: a wall-clock timeout after the push
   service actually accepted can double-notify once (inherent without a
   provider-side idempotency key).
4. Multi-tab localStorage clear races remain the documented accepted
   residual (idempotent clears, repaired at next choke point).
5. Corpus-freshness display for students (beyond admin) not yet built.
