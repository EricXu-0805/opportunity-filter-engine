# LinkedIn / Handshake browser extension — design doc (fall track)

> Status: design only, 2026-07-05. Eric's MTP listed "LinkedIn/Handshake 插件". Decision: a browser extension is a separate product line (its own store review cycle, permissions model, and support burden) — scheduled for fall, not summer. Handshake the *data source* is already served by the parameterized collector (`HANDSHAKE_SCHOOLS`); this doc is only about the user-side extension.

## Concept

A MV3 extension that recognizes an opportunity/professor/job the user is viewing (LinkedIn job page, Handshake posting, faculty profile) and overlays JoinALab: match score vs their profile, one-click "add to tracker", and "draft outreach" via the existing grounded cold-email pipeline.

## Why it can wait

- The core funnel (match → email → track) works without it; the extension is an acquisition/retention layer.
- LinkedIn actively fights scraping/automation; anything that *acts* on LinkedIn (auto-connect, auto-message) risks user account restrictions and brand damage. Read-only overlay + copy-to-clipboard keeps us clean — but that boundary needs careful UX, worth designing once, right.
- Store review (Chrome Web Store) wants a privacy policy, minimal permissions, and a stable domain — all easier after the fall LLC.

## Architecture sketch

- MV3, content scripts scoped to `linkedin.com/jobs/*`, `*.joinhandshake.com/*`, and (phase 2) faculty-profile URL patterns per school.
- Page parsing client-side (title/org/description extraction); calls existing `/api` with the user's Supabase session (extension auth = same anon/OAuth device model, token in extension storage).
- Zero automation on the host site: no DOM writes into LinkedIn forms, no auto-send. Draft opens in JoinALab tab.
- Rate/abuse: reuse per-device limits; extension adds an `X-Client: extension` tag for observability.

## Scope ladder

1. v0: recognize + score + save-to-tracker (2–3 weeks incl. review cycle).
2. v1: draft outreach from page context.
3. v2 (maybe never): Handshake application status sync — only if Handshake ToS allows.

## Open questions for fall

Store listing account (LLC), privacy policy hosting, whether Firefox/Safari are worth the ports, and whether the same overlay should ship for school job boards (higher value, friendlier ToS).
