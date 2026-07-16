# Reputation Board (公开红黑榜) — future design

Status: **deferred**. v1 shipped only *internal* responsiveness signals: the
service-role aggregation endpoint (`/api/opportunities/responsiveness`), an
anonymous "students recently heard back" badge gated at N≥3 contacts, and a
ranker bonus (`OFE_RESPONSIVENESS_BONUS`, default 2.0 since 2026-07; the N≥3
gate keeps it inert until real volume arrives). Nothing public, nothing
individual-level, no named rankings.

## What the public board would be

A per-lab/program view of aggregate responsiveness — reply rate, median time
to reply, interview conversion — surfaced as tiers (responsive / unrated /
unresponsive) rather than raw scores. Value: students stop wasting cold emails
on labs that never answer; responsive PIs get more qualified interest.

## Why it waits

1. **Defamation / liability risk.** A public "黑榜" entry names a professor and
   implies a negative fact. Even truthful aggregates invite disputes, and today
   JoinALab has no legal entity to absorb that risk (LLC planned for fall;
   Stripe is blocked on the same milestone). No public negative signal before
   the entity + a review process exist.
2. **Cold start / tiny-n distortion.** Most opportunities have 0–5 tracked
   contacts. At that volume one student's mislabeled status flips a lab between
   red and black. The internal phase exists precisely to learn how much data
   accumulates and where honest thresholds sit (N≥3 is already generous).
3. **Moderation load.** A public board needs dispute handling, a PI right of
   response, correction SLAs, and abuse review (a rejected student spamming
   "no reply"). None of that machinery exists, and it is not a summer priority.
4. **Signal integrity.** Self-reported statuses are unverified. Public claims
   need stronger evidence (e.g., verified via forwarded reply headers or the
   in-app email flow) before they can name anyone.

## Preconditions to revisit

- Legal entity formed; ToS reviewed for user-generated-content protections.
- ≥30% of active opportunities with N≥5 tracked contacts.
- Moderation workflow: PI notification before listing, response window,
  dispute path, and time-decay so old silence doesn't brand a lab forever.
- Positive-only first release ("responsive" tier only, no 黑榜) as the trial.
