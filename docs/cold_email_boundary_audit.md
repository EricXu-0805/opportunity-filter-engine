# Cold Email Trust / Freshness / Outbound Authorization — Phase 1 Audit

Audited tree: `origin/main` @ `ca44030` (post-W11). Audit date: 2026-08-03.
Method: two full-lifecycle code audits (backend generation → events → analytics;
frontend actions → tracker → dashboards), cross-checked against the W5/W7a/W9/
W8b/W10b/W11 boundaries already on main.

Lifecycle audited: verified data → personalization context → AI draft →
storage → copy/Gmail/Outlook/mailto → external sending → tracking → analytics.

## Verdicts (18 audit items)

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Generation pipeline | PASS | Template (`src/recommender/cold_email.py:381`) + AI pipeline (`backend/routes/cold_email.py:744` briefs → drafts → critique → revise) with the anti-fabrication gate re-run at `:939-954`; every failure degrades to template |
| 2 | Personalization context builder | PASS | Deterministic fact-sheets only (`_render_professor_brief` :387-420, all `_sanitize_field`-ed); evidence corpus mirrors exactly what the prompt was offered (`_build_email_corpus` :821-857) |
| 3 | Professor identity verification usage | **NOT IMPLEMENTED** | No identity/affiliation/freshness gate before personalization; `verification_scope`, tracking baselines, `last_verified` never consulted by cold email. No AI-resolved identity exists anywhere (good) — the gap is the absent gate, not an unsafe resolver |
| 4 | Email verification usage | PARTIAL | W10b bar holds (synthesized `email_source` never a send target; anonymous sessions never see the address; `contact_visibility.py:35-58`). Residue: `page_scan`-grabbed and `<3-name` shared unit inboxes pass the serve-time bar (hygiene is collector-side only: `uiuc_faculty.py:1660-1699`); **no `is_active` bar** — a departed professor's stored email stays revealable via detail-by-id |
| 5 | Publication verification usage | PASS | `verified_recent_works` equality gate at all four cold-email points (prompt :332, anchors :548, corpus :854, template cite `recommender:372,686`) + serving redaction; no bypass found |
| 6 | Draft schema (server storage) | NOT IMPLEMENTED — **deliberate** | The server stores no drafts; drafts exist only in the HTTP response and modal state, regenerated from the live corpus on every open. "Draft freshness" therefore maps to response provenance + client-cache invalidation, not a persistence model |
| 7 | Draft provenance | PARTIAL | Response carries `method/style/fallback_reason/recipient_status` (`backend/schemas.py:233-260`) but no `generated_at` / corpus version / pipeline version |
| 8 | Draft invalidation | PARTIAL | Recipient + works re-resolved server-side on every generation call (good), but the modal's `aiCacheRef` (`ColdEmailModal.tsx:234-241`) survives close/reopen for the page lifetime with no TTL — a days-old AI draft can be re-served in a long-lived tab |
| 9 | Gmail/Outlook/mailto handling | PASS | Compose deep-links only (`ColdEmailModal.tsx:637-645`), built from the gated recipient, disabled without one (:1026,1036,1045); the user's own mail client sends |
| 10 | Copy/open event handling | PASS | `markContacted` is a UI flag only (:609-613 — "No evidence = no tracking event"); no API call, no analytics event for copy/gmail/outlook/mailto |
| 11 | Sent event creation | PASS | Only the client writes `interactions` under RLS; the append-only status log is written exclusively by the SECURITY DEFINER trigger (migrations 009/014); no backend automation creates sent-like events (reminder cron touches `remind_at` only) |
| 12 | Confirm-sent flow | PASS | Explicit "Did you send the email?" strip → `confirmSent` → `recordContact` (:598-620): creates a status only when no row exists, stamps `last_contacted_at`; never downgrades an existing status; test-locked (`ColdEmailModal.tracking.test.tsx:110-153`) |
| 13 | Duplicate event protection | PASS | `UNIQUE(device_id, opportunity_id)` + upsert `onConflict`; trigger logs only `IS DISTINCT FROM` transitions; responsiveness dedupes by device set (`responsiveness.py:71-88`); account-merge migrations dedupe |
| 14 | Direct sending capability | PASS (none exists) | No Gmail/Outlook/SMTP/Graph API. Resend is used only for self/ops mail (match digests to the caller's own address, cron-gated saved-search digests, reminder fallback to the account's own email). `cold_email_send` in `metering.py:34` is a dormant billing placeholder with no route |
| 15 | Approval flow | PASS by construction | The system cannot send to professors; the human sends each mail from their own client — per-email approval is structural. Guard needed only against future regression (tripwire test) |
| 16 | Analytics dependencies | PASS | Responsiveness reads only the trigger-owned status log; min-N=3, distinct-device, positive-only public; generation/copy/open feed no metric; dashboard counts come from `interactions` statuses only — no "emails sent" stat |
| 17 | Frontend status rendering | PARTIAL | No drafted/prepared state renders as outreach (nothing is written), but confirm-sent writes `'applied'`: the button says "mark as contacted" (en:3389/zh:7437) while the tracker then shows **"Applied"** — a cold-email contact is mislabeled as an application. `last_contacted_at` stored but rendered nowhere |
| 18 | Files requiring modification | — | listed in the Phase-2 plan below |

## Cross-checks against the boundary's forbidden behaviors

- unverified professor facts → **publications/email/rank gated; identity+freshness NOT gated (item 3)**
- stale personalized drafts → **regenerate-per-open, but unbounded in-tab AI cache + no inactive/stale flag (items 4/7/8)**
- preparation interpreted as sending → **PASS, test-locked**
- fake outreach records → **PASS (user-only writers, idempotent)**
- sending without explicit approval → **PASS (no send capability; user sends externally)**

## Phase-2 minimum plan

1. Recipient truth: promote the unit-mailbox predicate into `src/evidence.py`
   (single source with the collector pass) and add serve-time bars to
   `contact_visibility.verified_send_target`: inactive records and, for
   faculty records, unit-mailbox localparts → `unavailable`. Program records
   keep their program-contact recipients.
2. Draft provenance: stamp `generated_at`, `corpus_version`,
   `pipeline_version`, and `source_freshness`
   (`fresh` / `stale` (>60d `last_verified`, reusing the tracking TTL) /
   `inactive`) on every cold-email response; surface stale/inactive in the modal.
3. Empty-signal hardening: when the record carries no research signal, reject
   AI drafts claiming "your work/research on …" (deterministic post-gate) —
   the template path is already claim-free by construction.
4. `contacted` as a first-class interaction status (migration relaxing the 004
   CHECK, `responsiveness.CONTACT_STATUSES`, status menu/tracker column/i18n),
   so confirm-sent stops rendering as "Applied".
5. Frontend: TTL + corpus-version invalidation for `aiCacheRef`; drop the dead
   optimistic `last_contacted_at` stamp (`use-opportunity-detail.ts:72-76`).
6. Tripwire test: the cold-email module must never gain outbound-send imports.
