# Product Scope — V1

## One-sentence definition

A semi-automated opportunity filter for UIUC international undergrads that collects research and summer program listings, normalizes them, and ranks them by realistic fit — not just keyword match.

## What V1 does

1. **Collects** opportunities from 3-5 stable public sources automatically, plus manual/URL entries
2. **Normalizes** every opportunity into a consistent schema with international-student-aware tags
3. **Matches** opportunities to a student profile using three-layer scoring (Eligibility × Readiness × Upside)
4. **Explains** why each opportunity is recommended, what gaps exist, and what to do next
5. **Presents** results in two buckets: "Best Matches Now" and "Worth Stretching For"

## What V1 does NOT do

| Excluded feature | Why |
|-----------------|-----|
| Mass auto-apply | Ethical + legal risk, not validated yet |
| LinkedIn scraping at scale | Anti-bot, ToS risk, high engineering cost |
| Browser extension | Adds platform complexity before core is validated |
| Nationwide university scraping | Scope creep — validate UIUC first |
| Social/community features | Not core to the filter engine value |
| Automated resume rewriting | Separate product problem |
| Cold outreach to PIs without public posting | Mode A only — we only match visible opportunities |

## Mode A: public opportunity matching only

V1 operates in **Mode A**: the system only recommends opportunities that have a visible posting, application form, webpage, or explicit public description. We do not recommend "go email this professor who has no posting" in V1.

Rationale: this keeps data quality high and avoids the liability of directing students to contact faculty who haven't signaled they're looking for help.

## Target users (V1)

**Primary:** UIUC freshmen/sophomores, international students, ECE/CS/STAT/Data Science

**Initial deployment:** founder + 5-10 friends for testing and iteration

**Growth path:** campus-wide tool → multi-university platform

## V1 build philosophy

- **80% data foundation / 20% demo polish**
- Semi-automatic data pipeline (auto-scrape what we can, manually curate the rest)
- Rule-based matching first, semantic/LLM matching in v2
- SQLite acceptable for local dev, PostgreSQL for any deployment
- Ship something usable in 4-6 weeks, not a perfect product in 6 months

## Key differentiator

Not collection. Not scraping. Not search.

The differentiator is the **explanation layer**: telling students *why* an opportunity fits, *what* they're missing, and *what to do next*. This is what no existing tool provides for underclassmen.
