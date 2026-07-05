# Org Accounts — design doc (build-when-first-customer)

> Status: design only, 2026-07-05, per Eric's decision (机构客户 = 留学中介/顾问 + 大学 career/research 办公室; 骨架 + 文档, no implementation until a real org customer exists). The only shipped reserve is `account_type: 'personal'` on the profile type.

## Who buys

| Segment | Job to be done | Willingness signal |
|---|---|---|
| 留学中介 / independent counselors | Run 10–100 students' research-application funnels without hand-curating professor lists per student | Already pay for CRM-ish tools (Cialfo, 表格人肉); agency market proves WTP for outcomes |
| University career / undergrad-research offices | Give their whole student body a self-serve match tool; see aggregate engagement | Buy site licenses, procurement-driven, slow but sticky |

Counselors are the wedge: smaller deals, faster close, and they *fulfill* the concierge service themselves (our paid per-use flow becomes their tool, not our labor).

## Auth model (sketch)

- `orgs` table: `id, name, kind ('agency'|'university'), created_by, created_at`.
- `org_members`: `org_id, user_id (auth.uid), role ('owner'|'counselor'|'viewer'), invited_email, accepted_at`. Invite-only (owner mints invite links bound to email hash, same idiom as merge grants — single-use + TTL). No self-serve org signup; orgs are created by us during onboarding (B2B sales-assist).
- Student linkage: `org_students`: `org_id, student_device_id, consent_at, revoked_at`. **Student consents explicitly** (a share-code the student redeems — never counselor-initiated scraping of a student account). Consent is revocable; RLS: counselors read a student's profile/matches ONLY through an active consent row.
- `account_type` on profile stays a plain string; org membership is derived from `org_members`, not stored on the profile.

## Product surface (v1 scope when built)

1. Counselor dashboard: student roster (consented), each with match snapshot (top-10 + score buckets), staleness indicator, and per-student notes.
2. Batch actions: re-run matches for roster; export per-student shortlist (PDF/CSV); flag "concierge this one" → creates an order attributed to the org.
3. University variant defers everything above except aggregate anonymous stats (usage, coverage by college) — offices care about reach, not individual funnels.

## Pricing thinking (anchor, not final)

- Agency: per-seat ($29/mo counselor) + per-student-active ($3/mo) OR bundle of concierge credits at volume discount (aligns with our per-use anchor; agency margin stays theirs).
- University: flat site license by enrollment band; pilot free-for-a-quarter to seed case studies.
- Rule: org pricing must never undercut the direct per-use consumer price for the same fulfillment.

## Build triggers

Do NOT build until: (a) one agency asks to pay after a manual pilot (we run their students through the personal product by hand), or (b) a university office issues a real procurement signal. Manual pilot needs zero code — that is the point.
