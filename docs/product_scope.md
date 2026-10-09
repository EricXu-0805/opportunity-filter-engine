# Product Scope

Checked against the code on 2026-10-09. The release tables in
`backend/lib/release_scope.py` and `frontend/src/lib/release-scope.ts` decide
what ships; `tests/test_docs_current.py` fails when the flag table below
disagrees with either of them.

## What JoinALab is

JoinALab matches undergraduates to faculty labs, research programs and
internships. It ranks every opportunity against the student's profile,
explains the fit and the gaps, drafts the first email to the lab, and tracks
the application afterwards.

It covers 115 universities. Their faculty directories and campus programs are
re-scraped once a week, and the national sources (the SRO catalog, NSF REU
sites, SimplifyJobs internships) every Sunday; `RUNBOOK.md` section 2 has the
rotation. The 2026-10-08 refresh held 142,861 records, 7,161 of them inactive.
`src/school_scope.py` lists the schools the product has dropped and why (UC
Davis, since 2026-09-06).

## What a student can do on the public site

1. Build a profile on the home page: school, college, major, research
   interests, skills, a résumé upload and a GitHub import.
2. Get ranked results in three buckets (High Priority, Good Match, Reach),
   each with why it fits and what is missing, and filter them. Results can
   include other schools.
3. Open an opportunity: the source evidence, the contact, a cold-email draft,
   and a résumé tailored to that target.
4. Save opportunities and searches. Saved searches send email digests.
5. Track applications on `/tracker` and `/dashboard`, with deadlines and
   reminders by Web Push or email.
6. Import a posting by URL or pasted text as a private target.
7. Ask JoinALab to handle one professor for them (the concierge request on the
   opportunity page). A person does it by hand, and nothing is charged.

## Release flags

Every flag below is a source-controlled boolean, written once in each table.
Closed features keep their code and tests. Their pages call `notFound()`,
their API routes answer 404 from `ReleaseScopeMiddleware` in
`backend/main.py`, and fellowship records stay off every public surface.

| Backend flag | Frontend flag | State | What it controls | Why it is closed |
|---|---|---|---|---|
| `cross_school_matching` | `crossSchoolMatching` | on | The "include other schools" control on `/results` and cross-school ranking | |
| `resume_renovate` | `resumeRenovate` | on | Résumé renovation on the opportunity page and its routes: `/api/tailor/structure`, `/renovate`, `/bullet`, `/full-target/suggestions`, `/full-target/selection-plan` and `/api/resume/full-target/export`. Single-target tailoring (`/api/tailor`, `/api/tailor/extract-bullets`, `/api/tailor/status`) stays public either way | |
| `match_ai_refine` | `matchAiRefine` | off | The AI re-ranking pass on `/results` | When it was on, it changed the URL and badges but not the `/matches/view` ranking. It reopens only with server-side mode attestation and bounded paid concurrency. |
| `compare` | `compare` | off | `/compare`, compare selection in favorites, `/api/matches/{id}/explain` | Outside the accepted MVP surface |
| `fellowships` | `fellowships` | off | Fellowship records on every public surface, `/fellowships`, the Fellowship preference | Outside the accepted MVP surface |
| `roadmap` | `roadmap` | off | `/roadmap`, the dashboard roadmap card, `/api/roadmap`, `/api/matches/{id}/gaps` | Outside the accepted MVP surface |
| `ask_ai` | `askAi` | off | The Ask-AI chat on the opportunity page, `/api/opportunities/{id}/chat`, `/api/chat/models` | Outside the accepted MVP surface |
| `professor_signals` | `professorSignals` | off | Professor follows and updates, the responsiveness bonus in ranking | Outside the accepted MVP surface |
| `payments` | `payments` | off | Orders and the admin orders view, `/api/orders`, `/api/admin/orders` | Migration 026 dropped the orders RLS policies and revoked browser access, and the pricing module and payment QR images are not on `main` |
| `microsoft_school_auth` | `microsoftSchoolAuth` | off | Microsoft sign-in; the backend also refuses sessions minted through the Azure provider | Azure publisher verification needs a verified legal entity, which does not exist yet |
| `concierge_pay_qr` | `conciergePayQr` | off | The payment QR for the concierge channel | Needs a confirmed receiving account |

How a flag changes:

- A feature opens only in its own acceptance PR, which flips both tables,
  moves the feature from `UNACCEPTED_FEATURES` to `ACCEPTED_FEATURES` in
  `tests/test_release_scope.py`, and updates this table.
- No environment variable can open a closed feature. Only `payments` reads
  one, `OFE_PAYMENTS_ENABLED`: even after `payments` is accepted, the feature
  stays off until that variable is `1` or `true`.
- `tests/conftest.py` forces every flag on, except in the five test modules
  that set `RELEASE_CONTRACT_TESTS = True`, so a green suite says little about
  the shipped flag state. `tests/test_release_scope.py` is the module that
  tests the shipped table.

## What JoinALab does not do

| Excluded | Why |
|---|---|
| Sending email or applications automatically | The student sends every cold email from their own mail client. A concierge request is handled by a person, by hand |
| Collecting from behind a login | The scheduled refresh does not log in. A login-only list comes in as a hand export instead (CMU's research projects, `data/snapshots/cmu_uro_projects.json`) |
| Getting around bot walls | A school behind a Cloudflare challenge is dropped rather than worked around (UC Davis) |
| Serving fellowships, compare, roadmap or Ask AI | Built, but closed until each passes its own acceptance (table above) |

## Key differentiator

The explanation layer: telling students *why* an opportunity fits, *what*
they are missing, and *what to do next*, with every claim traced to a source
record.
