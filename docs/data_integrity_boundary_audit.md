# Favorites / Tracker / Dashboard / Auth Data-Integrity Boundary — Phase 1 Audit (W14)

Audited tree: `origin/main` @ `81fa079` (post-W13). Audit date: 2026-08-04.
Method: three full-lifecycle audits (auth migration + Flow B; user-state
isolation + tracker; notifications + dashboard).

Principle audited: user state belongs to the correct user; displayed status
reflects real events; zero states appear only for present, fresh data.

## Verdicts (18 audit items)

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Anonymous identity model | PASS | Supabase anonymous sessions; anon `auth.uid()` doubles as `device_id`; 17 user-owned stores all RLS own-rows (`006_anonymous_auth_rls.sql`, 014 hardening) |
| 2 | Login migration flow | PASS | Default path is in-place linking (same uid — `updateUser`/`linkIdentity`, zero migration needed); existing-account sign-ins route through Flow B with a grant minted BEFORE the redirect |
| 3 | User state ownership | PASS | localStorage registry + 3 choke points (`identity-owner.ts:22-50`); documented multi-tab residuals; caches version+hash guarded |
| 4 | Favorite storage | PASS | UNIQUE(device,opp), own-row RLS, local mirror + backfill, merge-covered |
| 5 | Tracker storage | PASS | UNIQUE(device,opp), status CHECK, trigger-owned append-only log (client cannot forge), merge conflict-resolved |
| 6 | Notes/reminders storage | PARTIAL | UPDATE-only writes (can never create a status); **BUG: reminder cron filters `interaction_type in (applied,replied,interviewing)` — `contacted` (W12) rows never fire and never clear** (`push.py:146`) |
| 7 | Cache strategy | PASS | match cache `_v4` + profile-hash + matcher_version; AI cache TTL + corpus_version (W12); explain cache TTL + version; service worker caches nothing |
| 8 | Cross-tab behavior | PARTIAL | localStorage surfaces self-heal via choke points; home refetches on uid change; **favorites/tracker/dashboard/detail/results fetch once and never react to uid change — stale Account-A data renders and new writes execute under Account B's JWT** |
| 9 | Flow B implementation | PASS (documented) | Client-side RPC + SECURITY DEFINER (`017`/`0181`/`021`/`023` live body): mandatory email- or secret-hash binding, source = minter, target = redeemer, single-use + 15-min TTL + per-device tombstone, one atomic transaction, CI-replayed (initdb + real CLI) |
| 10 | Retry behavior | PARTIAL | Cron retry = free re-scan (works); `toggleFavorite` treats 23505 as failure → false "local-only" signal; `trackInteraction` upsert result unchecked |
| 11 | Idempotency support | PARTIAL | Unique keys everywhere user-visible EXCEPT `saved_searches` (duplicable on re-submit); status log trigger-owned |
| 12 | Tracker state transitions | PASS | Triple guard (UI gate + hook guard + UPDATE-only query); reminder suggestions set dates only; cold-email confirm-sent is the only `contacted` writer — all test-pinned |
| 13 | Notification queue lifecycle | NOT IMPLEMENTED (by design) | Scan-and-send, no queue/outbox; state = `remind_at` / `new_match_ids` columns. Acceptable at scale; lifecycle semantics audited via ordering below |
| 14 | Provider acknowledgment | PARTIAL | Ordering CORRECT (remind_at cleared only after accepted send/fallback; pywebpush raises >202; timeout never success; failures retry next cron — all pinned). Gaps: bookkeeping PATCHes unchecked (silent failure = daily duplicate), no per-row error isolation (one httpx error aborts the batch), email-fallback catches only HTTPException, digest send-before-stamp (PATCH failure = nightly duplicate), no cron concurrency groups |
| 15 | Dashboard data loading | **FAIL** | `getInteractionsFull` swallows every error into an empty Map (`supabase.ts:1128-1138`) → funnel/reminders/tracker render confident zeros on outage; the page's error branch is unreachable; the passing test mocks a rejection the real lib cannot produce |
| 16 | Dashboard freshness | **FAIL** (user-facing) | No student-facing staleness surface; `release_ready` served but never read; `available:false` conflated with "no updates yet" (conflation test-pinned); admin FreshnessBanner fine |
| 17 | Zero-state logic | mixed | /results PASS (model: skeleton/error-retry/empty separation); dashboard PARTIAL (correct tri-state UI betrayed by the data layer); **/favorites FAIL** (`catch {}` → false empty, no error state), **/tracker FAIL** (documented false-empty catch), **saved-searches section FAIL** (silently vanishes) |
| 18 | Files requiring changes | — | union list in `docs/data_integrity_boundary_report.md` |

## Flow B failure-mode findings (beyond the sound core)

1. **`orders` never merged** — absent from every redeem body (017/0181/021/023): a
   purchase made while anonymous silently vanishes from the merged account.
2. **15-min grant TTL vs magic-link latency** — click at minute 16 → redeem
   returns expired → sign-in still succeeds and the anonymous uid's rows are
   stranded forever (anon session overwritten; mint requires an anon session;
   no prompt, no tooling).
3. **Client clears the merge token BEFORE the RPC** (`supabase.ts:550-552`) — a
   transport failure permanently orphans the anon data (acknowledged in-code).
4. **Stale grant defers local clears indefinitely** (`identity-owner.ts:81-90`);
   `signOutOfAccount` never drops an abandoned `MERGE_GRANT`.
5. Attachments are not re-homed and the caveat copy overstates recoverability
   ("stayed on the other device" — the source uid is unreachable after sign-in).
6. No purge of expired/consumed `merge_grants`; no unmigrated-data prompt.

## Optimistic-state findings

- Truthful: renovation "Saved" (W13), follows (throw + retry), saved-search
  alert, digest opt-in state.
- False-state risks: status/notes/reminder writes are fire-and-forget
  (`.catch(() => {})`) with no revert — TrackerPanel can flash "Saved" on a
  failed write; `updateInteractionDetails` returns void.

## What was verified sound (no action needed)

Ownership proof, single-use, atomicity, and tombstones of Flow B (7-scenario
SQL suite + CI replay); RLS on all 17 stores; trigger-owned status history;
notes/reminders can never create statuses; no false open/clicked claims
anywhere in notifications; /results zero-state discipline; match/AI/explain
cache keying.
