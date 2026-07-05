# Graduate / PhD support — design + pilot plan

> Status: design, 2026-07-05 (Eric's MTP: 不光本科). Verified current state: backend `year` is a free string (schemas.py), but the profile UI's `grades` options and the fellowships filter enum (`frontend/src/app/fellowships/types.ts`) are undergrad-only (Freshman–Senior). Nothing in the ranker hard-blocks grad users — eligibility scoring just has no grad awareness.

## What actually changes for a grad user

| Layer | Undergrad today | Grad gap |
|---|---|---|
| Profile | 4 class-year options | Needs `Masters` / `PhD` (+ program year later); free-string backend already accepts them |
| Inventory | Faculty (year-agnostic — the core asset works for grads as-is), REU/summer programs (mostly undergrad-restricted), fellowships (undergrad-framed) | Faculty: fine. Programs: need grad-specific sources (PhD openings, funded MS/PhD fellowships, RA/TA postings) |
| Matching | `_year_match` style eligibility vs undergrad terms | Must not penalize grads for "undergraduates only" records — should hard-note, not soft-score |
| Copy/emails | "undergraduate research" phrasing in templates | Cold-email templates need grad variants (prospective-PhD outreach ≠ course-project ask) |

Key insight: **the faculty corpus (the moat) is already the right inventory for prospective-PhD outreach** — the biggest grad use case (cold-emailing potential advisors) needs zero new scraping, only profile + copy + eligibility awareness.

## Grad-specific data sources (evaluated)

1. **Faculty "openings" signals** — many labs state "recruiting PhD students" on their pages; an enrichment flag (`recruiting_phd`) harvested during per-profile passes. Cheap, high value, reuses existing scrapers.
2. Department "PhD openings" / funded-position lists — sparse in the US (common in EU); low yield, defer.
3. Fellowship databases (NSF GRFP, Hertz, DoD NDSEG…) — small, curated, static; one curated catalog file covers 90% of value.
4. RA/TA boards — school-internal, auth-walled; defer.

## Pilot (1 school, before generalizing)

UIUC. Steps: (a) add Masters/PhD to profile options + i18n; (b) eligibility: records whose text matches undergrad-only patterns get a hard caveat chip for grad users instead of a silent mid-score; (c) cold-email grad template (prospective-advisor framing, cites papers via the OpenAlex works enrichment); (d) curated grad-fellowship catalog (~20 records, national). Measure: does a real grad dogfooder (Eric knows several at UIUC) get a usable top-15 + one sendable email? Only then extend patterns corpus-wide.

## Non-goals

No separate grad product/tier; no grad-specific ranker rewrite; no admissions-consulting features (different market, different liability).
