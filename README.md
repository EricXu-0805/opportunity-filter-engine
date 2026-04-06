# Opportunity Filter Engine

> 帮低年级本科生更快找到"自己现在有机会拿到"的 research / internship / summer program，而不是只帮他们搜到一堆职位。

## What This Is

An **Opportunity Decision Engine** for UIUC undergraduate students — especially international freshmen and sophomores in ECE, CS, STAT, and Data Science — that automatically collects, normalizes, and ranks opportunities based on three questions:

1. **Can I apply?** (Eligibility)
2. **Should I apply?** (Readiness)
3. **What should I do next?** (Actionable Guidance)

This is **not a job board**. It is a personalized filter that turns scattered, intimidating listings into an explained, prioritized, actionable list.

## Why This Matters

UIUC scatters opportunities across **7+ platforms** with no unified view:

| Source | What it has | Problem |
|--------|------------|---------|
| OUR Blog | Faculty-posted research positions | RSS feed exists but nobody parses it |
| SRO Database | 279+ external summer programs | 12 pages of unfiltered Drupal listings |
| Handshake | Jobs + some research | Login-gated, mixes everything together |
| CS Opportunities | CS/ECE research | NetID required, ~70 listings/year |
| Research Park | 800+ intern positions/year | Separate site, not linked to research |
| Department pages | Lab-specific openings | Scattered across 50+ faculty sites |
| External REUs | 500+ NSF-funded programs | Requires knowing where to look |

**The result:** students — especially international freshmen — can't tell what's realistic, what's worth their time, or where to even start.

## Core Architecture

```
┌─────────────────────────────────────────────────────┐
│                   DATA SOURCES                       │
│  OUR RSS · SRO Scraper · NSF API · USAJobs API      │
│  SerpApi · Manual Entries · URL Parser               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              NORMALIZATION PIPELINE                   │
│  Raw text → Structured fields → Tagging              │
│  (LLM extraction for ambiguous fields)               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              OPPORTUNITY DATABASE                     │
│  PostgreSQL + pgvector                               │
│  Standardized schema · Full-text search              │
│  Semantic embeddings · International tags            │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              MATCHING ENGINE                          │
│  Eligibility (0.45) + Readiness (0.35) + Upside (0.20)│
│  Rule-based first → Semantic matching later          │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              USER INTERFACE                           │
│  Profile input → Ranked results + Explanations       │
│  "Best Matches Now" / "Worth Stretching For"         │
│  Cold email guidance · Resume direction              │
└─────────────────────────────────────────────────────┘
```

## V1 Scope

### Included
- UIUC on-campus research opportunities (auto-collected)
- UIUC summer programs
- Selected external REUs and summer research programs
- Semi-automatic data pipeline (scrape + manual curation)
- Profile-based three-layer scoring
- Explained recommendations with next-step guidance
- International-student-aware filtering

### Excluded from V1
- Mass auto-apply
- Full LinkedIn automation
- Browser extension
- Nationwide scraping at scale
- Social/community features
- Automated resume rewriting

## Tech Stack

| Layer | V1 Choice | Why |
|-------|-----------|-----|
| Backend | FastAPI (Python) | Async-native, auto OpenAPI docs, Pydantic validation |
| Database | PostgreSQL + pgvector | Relational + FTS + vector search in one DB |
| Frontend | Streamlit (MVP) → Next.js (v2) | Fast iteration now, production-ready later |
| Scraping | requests + BeautifulSoup + feedparser | Covers RSS + static HTML |
| LLM | OpenAI API (gpt-4o-mini) | Structured field extraction + explanations |
| Deployment | Railway ($5/mo) | PostgreSQL + FastAPI in one place |

## Project Structure

```
opportunity-filter-engine/
├── README.md
├── docs/
│   ├── product_scope.md          # What we build and don't build
│   ├── data_sources.md           # Every source with access method
│   ├── user_profile_schema.md    # Profile fields and logic
│   ├── opportunity_schema.md     # Opportunity fields and tagging
│   ├── matching_logic.md         # Three-layer scoring system
│   ├── international_logic.md    # International student considerations
│   ├── roadmap.md                # Phase plan with milestones
│   └── future_features.md        # Post-V1 expansion
├── config/
│   └── sources.yaml              # Scraper registry configuration
├── data/
│   ├── raw/                      # Unprocessed scraped data
│   ├── processed/                # Normalized records
│   └── manual_entries/           # Hand-curated opportunities
├── src/
│   ├── collectors/               # Source-specific scrapers
│   │   ├── base.py               # Abstract scraper interface
│   │   ├── uiuc_our_rss.py       # OUR Blog RSS feed parser
│   │   ├── uiuc_sro.py           # Summer Research Ops scraper
│   │   ├── nsf_reu.py            # NSF Award Search API
│   │   ├── usajobs.py            # USAJobs API client
│   │   └── url_parser.py         # Parse any pasted URL into record
│   ├── parsers/                  # Text → structured field extraction
│   ├── normalizers/              # Raw → standardized schema
│   ├── matcher/                  # Scoring engine
│   │   ├── eligibility.py
│   │   ├── readiness.py
│   │   ├── upside.py
│   │   └── ranker.py
│   ├── recommender/              # Explanation + next-step generation
│   └── app/                      # Streamlit / FastAPI app
├── examples/
│   ├── sample_profile.json
│   └── sample_opportunities.json
└── tests/
```

## Phase Plan

| Phase | Goal | Duration | Key Deliverable |
|-------|------|----------|-----------------|
| 1 | Product definition | Done | README + schemas + matching logic |
| 2 | Build opportunity dataset | 1-2 weeks | 50-100 normalized opportunities |
| 3 | Matching engine | 1-2 weeks | Scoring functions + explanations |
| 4 | MVP interface | 1 week | Streamlit app with profile → results |
| 5 | Application assistance | 1-2 weeks | Cold email generator + resume tips |

## V1 Success Criteria

**Product:** 50+ standardized opportunities, 3-5 real student profiles tested, recommendations meaningfully faster than manual search

**UX:** Profile setup < 3 minutes, user immediately understands why a result is recommended, user can take at least one concrete action (apply / cold email / revise resume)

**Technical:** 2-3 stable auto-collection sources, incremental data updates, stable schemas

## License

TBD

## Author

Guoyi Xu — UIUC Computer Engineering
