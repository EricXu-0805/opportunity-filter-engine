# Cold Email Trust / Freshness / Outbound Authorization — Final Report (W12)

Companion to `docs/cold_email_boundary_audit.md` (Phase-1 findings).
Implemented on `feat/cold-email-boundary`; audit baseline `origin/main` @ `ca44030`.

## The boundary, enforced

```text
verified facts               → allowed personalization
unverified facts             → excluded or explicitly unavailable
user preparation action      ≠ sent
explicit user confirmation   → one 'contacted' record
no outbound capability       → per-email approval is structural (the user sends)
```

## 1. Verified personalization sources (reused systems, no new verification logic)

| Fact | Gate | Where |
|---|---|---|
| Publications | `publication_attribution_status == "verified_author_id"` equality, fail closed (W9/#699) | 4 cold-email points: prompt offer, anchors, anti-fabrication corpus, template cite |
| Recipient email | W10b provenance bar (synthesized `email_source` never a target) + signed-in session; **W12 adds**: inactive-record bar and, for faculty records, the unit-mailbox bar (shared predicate with the collector nulling pass via `src/evidence.py`) | `backend/lib/contact_visibility.verified_send_target` |
| Position/rank | stated professor rank only earns "Professor <name>" greeting/framing (W11) | `src/evidence.is_professor_rank` in `_common_parts` |
| Research areas | dept names refused, broad fields dropped, mismatch drops the hook (template); **W12 adds** the empty-signal claim gate on the AI path: with zero research signal, any "your work/research on …" shape is rejected as fabrication (template fallback) | `_infer_research_area`, `_p1_research_hook`, `backend/routes/cold_email._ungrounded_research_claim` |
| Identity | corpus record + junk-name rejection; **residual** — no per-person identity verification exists anywhere in the product (record-scoped ids by design); a same-name confusion in the corpus would personalize. Mitigations: no AI identity resolution exists; conservative dedup; W12 freshness/inactive stamps surface stale records. Accepted residual, documented below | — |

Recipient-type distinction now enforced at serve time: `professor_email`
(personal, faculty record) vs `unit/department mailbox` (blocked for faculty
records) vs `program_contact_email` (allowed for program records) vs
synthesized (always blocked) vs unknown/absent (honest `unavailable` state).

## 2. Draft provenance and freshness

Design fact: **the server deliberately stores no drafts** — every modal open
regenerates from the live corpus, so there is no persistent draft store to
invalidate. The freshness model is therefore response-level + client-cache:

- Every `/cold-email`, `/cold-email/stream`, `/cold-email/variants` response
  now carries `generated_at`, `corpus_version`, `pipeline_version`
  (`COLD_EMAIL_PIPELINE_VERSION`), and `source_freshness`:
  `fresh` (verified within the shared 60-day tracking TTL) / `stale` /
  `inactive` / `unknown` (absent or unparseable `last_verified` — never
  optimistically fresh).
- The only client draft cache (`aiCacheRef`) now expires on a 30-minute TTL
  **and** whenever the backend's `corpus_version` moves
  (`aiCacheEntryIsStale`, exported + tested) — a long-lived tab can no longer
  re-serve a draft built from a superseded professor record. Pre-W12 cached
  responses (no version) fall back to the TTL rule alone.
- State mapping to the requested vocabulary: `draft_current` = regenerated
  this open / cache-fresh; `draft_stale` = TTL/corpus-moved cache entry
  (auto-regenerated, never silently re-served); `draft_invalid` = inactive
  source record (recipient withheld; `source_freshness: "inactive"`).

## 3. Preparation ≠ sending (verified end to end)

- copy / open-Gmail / open-Outlook / mailto set a UI flag only
  (`markContacted` — "No evidence = no tracking event"); zero API calls,
  zero analytics events. Compose deep-links are disabled without a revealed
  recipient. Test-locked (`ColdEmailModal.tracking.test.tsx`).
- The ONLY writer of an outreach record is the explicit "Did you send the
  email?" → "Yes" attestation, which now writes **`contacted`** (new
  first-class status, migration `024_contacted_status.sql`) instead of
  overloading `applied` — a cold-email contact no longer renders as
  "Applied" in the tracker/dashboard. Existing rows are not rewritten
  (a historical `applied` may genuinely be an application; never guessed).
- Idempotency: `UNIQUE(device_id, opportunity_id)` + upsert; the append-only
  status log is written only by the SECURITY-DEFINER trigger on genuine
  transitions; `recordContact` never downgrades an existing status;
  responsiveness aggregates distinct devices. Double-click / refresh / two
  tabs / retries converge to one row.

## 4. Outbound authorization

The system has **no capability to send mail to professors** — no Gmail API,
Outlook API, SMTP, or Graph usage exists; Resend is used only for the user's
own digests/reminders under cron-secret + rate limits. Per-email approval is
structural: the user reviews the exact draft in their own mail client and
presses send there. A tripwire test
(`tests/test_cold_email_boundary.py::TestNoOutboundSending`) fails the build
if the cold-email modules ever gain an outbound provider import or a
`/cold-email/send` route, forcing the W12 approval requirements
(exact-content binding, re-approval on edit, no bulk) to be implemented
before any such capability ships. The dormant `cold_email_send` metering
constant remains a billing placeholder with no route.

## 5. Tracking / analytics event model

```text
preparation (draft/copy/open)  → nothing persisted, nothing counted
send_approved / send_completed → N/A (no direct sending exists)
sent_confirmed                 → interactions.contacted (explicit attestation)
reply_received / outcome       → replied / interviewing / rejected statuses
```

Responsiveness (`CONTACT_STATUSES` now includes `contacted`) still requires
min-N ≥ 3 distinct devices and serves positive-only public aggregates;
`dismissed` excluded; no user-visible "emails sent" stat exists anywhere.

## 6. Tests (Phase 3)

New: `tests/test_cold_email_boundary.py` (24) — recipient bars (personal /
synthesized / unit-mailbox / dept-stem / program-contact / inactive / legacy),
freshness states incl. unknown-not-fresh, empty-signal claim gate, contacted
status semantics, migration content, outbound tripwire. Frontend: tracking
suite updated to the `contacted` contract + 3 new cache-freshness tests
(TTL, corpus-move, pre-W12 fallback). Requirement map for the 25 required
behaviors: 1-2 identity — residual documented (no identity-verification
system exists to gate on; covered by audit + tripwire on claims instead);
3-4 recipient bars (new tests); 5-6 publications (`test_publication_trust.py`,
`test_cold_email.py:514-628`); 7 research-area (`_ungrounded_research_claim`
tests + existing broad-field template tests); 8-12 draft freshness (response
stamps + `aiCacheEntryIsStale` tests; "stale draft cannot be sent" =
inactive→recipient withheld + cache auto-regeneration); 13-19 send semantics
(`ColdEmailModal.tracking.test.tsx` 7 tests + DB unique/trigger from
migrations 002/009/014); 20-23 direct sending (structural: tripwire tests —
capability absent); 24-25 tracking separation (`test_responsiveness.py`
suite + `CONTACT_STATUSES` tests).

Results at close-out: backend suite green, frontend vitest green, tsc +
eslint + ruff clean (see PR checks for the authoritative run).

## 7. Remaining risks (documented, tracked)

1. **Identity**: no per-person identity verification exists product-wide;
   cold email inherits corpus identity. Risk bounded by conservative dedup +
   no-AI-resolution + W12 freshness surfacing; a future professor-identity
   model (entity-resolved ids) is the real fix.
2. **Shared inboxes below every heuristic**: a 2-professor shared *personal-
   looking* address still passes (frequency pass needs ≥3, localpart looks
   personal). Serve-time bar closes the generic-localpart class only.
3. **`source_freshness: "stale"` is advisory** — the draft still generates
   (deliberate: the corpus refreshes weekly; blocking on 60d would dark large
   swaths). Inactive is the hard bar.
4. **Legacy `applied` rows** from pre-W12 confirm-sent remain labeled
   Applied; not rewritten on principle (cannot distinguish real applications).
5. The modal's edited drafts are still discarded on close without warning
   (UX debt, not a truth issue).
