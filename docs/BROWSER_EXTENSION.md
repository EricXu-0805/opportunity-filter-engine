# LinkedIn / Handshake browser extension — design doc (fall track)

> Status: design only, 2026-07-05. Eric's MTP listed "LinkedIn/Handshake 插件". Decision: a browser extension is a separate product line (its own store review cycle, permissions model, and support burden) — scheduled for fall, not summer. U29 checks platform permissions before implementation. The Handshake collector is manual and school-parameterized.

## Concept

The July proposal described an MV3 extension that recognizes an opportunity/professor/job the user is viewing (LinkedIn job page, Handshake posting, faculty profile) and overlays JoinALab: match score vs their profile, one-click "add to tracker", and "draft outreach" via the existing grounded cold-email pipeline.

## Why it can wait

- The core funnel (match → email → track) works without it; the extension is an acquisition/retention layer.
- LinkedIn prohibits extensions that scrape, change the site’s appearance or automate actions. The proposed LinkedIn overlay and page parsing fall within those restrictions. A platform integration needs an approved interface covering the specific fields and uses. [LinkedIn Help](https://www.linkedin.com/help/recruiter/answer/a1340567) · [LinkedIn User Agreement, section 8.2](https://www.linkedin.com/legal/user-agreement)
- Handshake’s published terms prohibit third-party bulk collection of job descriptions and other marketplace information. Verify the terms of any separate partner agreement for the schools, fields, users, and purposes it covers. [Handshake terms](https://joinhandshake.com/legal/tos/)
- Store review (Chrome Web Store) wants a privacy policy, minimal permissions, and a stable domain — all easier after the fall LLC.

## Original architecture sketch

The following design is on hold pending a supported way to access each platform.

- MV3, content scripts scoped to `linkedin.com/jobs/*`, `*.joinhandshake.com/*`, and (phase 2) faculty-profile URL patterns per school.
- Page parsing client-side (title/org/description extraction); calls existing `/api` with the user's Supabase session (extension auth = same anon/OAuth device model, token in extension storage).
- Zero automation on the host site: no DOM writes into LinkedIn forms, no auto-send. Draft opens in JoinALab tab.
- Rate/abuse: reuse per-device limits; extension adds an `X-Client: extension` tag for observability.

## Proposed stages subject to platform approval

1. v0: recognize + score + save-to-tracker (2–3 weeks incl. review cycle).
2. v1: draft outreach from page context.
3. v2 (maybe never): Handshake application status sync — only if Handshake ToS allows.

## School configuration

The manual collector has three school profiles. The university references below identify the configured school portals. The periodic refresh does not invoke this collector. A school login establishes access for that user and does not establish third-party data rights.

| School | Configured host | University reference |
| --- | --- | --- |
| UIUC | illinois.joinhandshake.com | [Illinois Career Services](https://ler.illinois.edu/alumni/alumni-career-services/job-search-resources/) |
| UC Berkeley | berkeley.joinhandshake.com | [Berkeley career guide](https://career.berkeley.edu/wp-content/uploads/Career-Readiness-Checklist-PDF.pdf) |
| Michigan, Ann Arbor | umich.joinhandshake.com | [Michigan University Career Center](https://careercenter.umich.edu/making-appointment-university-career-center-students-disabilities) |

## Current workflow

A student can keep a private opportunity in JoinALab using the import tab in Resources. They can enter an employer's public posting or paste material they have permission to use, review the extracted fields, and save it. A student who wants to bookmark a job on Handshake can use Handshake's own Save control. That action can notify the employer when the student meets the qualifications. Saving privately in JoinALab and saving on Handshake are separate user choices. [Handshake saved jobs](https://support.joinhandshake.com/hc/en-us/articles/227072527-My-Saved-Jobs-in-Handshake)

## Open questions for fall

Store listing account (LLC), privacy policy hosting, whether Firefox/Safari are worth the ports, and whether the same overlay should ship for school job boards (higher value, friendlier ToS).
