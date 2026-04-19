# OpportunityEngine

A personalized research and internship matching engine for UIUC undergraduates. Automatically collects 1800+ opportunities from 6 sources (UIUC SRO, NSF REU, faculty directories, Handshake, OUR RSS, manual entries), then ranks and explains each match based on your profile.

Not a job board. A decision engine that answers three questions:
1. **Can I apply?** (Eligibility)
2. **Should I apply?** (Readiness)
3. **What should I do next?** (Actionable Guidance)

**[Live Demo](https://opportunity-filter-engine.vercel.app)** | **[API](https://opportunity-filter-engine-api.onrender.com/api/health)**

## Screenshots

### Profile Builder
Two-column form with college/major cascading dropdowns, international student filtering, resume upload with auto-skill extraction, and a research interest/experience balance slider.

![Profile Page](docs/screenshots/01-profile.png)

### Ranked Results
Every opportunity is scored (Eligibility 0.45 + Readiness 0.35 + Upside 0.20) and bucketed into High Priority, Good Match, or Reach. Each card explains *why it fits* and *what gaps you have*.

![Results Page](docs/screenshots/02-results.png)

### Cold Email Generator
One-click draft with pre-filled subject line and body, personalized to your profile and the specific opportunity. Copy to clipboard or open directly in your email client.

![Cold Email Modal](docs/screenshots/03-cold-email.png)

### Opportunity Dashboard
Live stats across all scraped sources: total opportunities, paid positions, international-friendly count, breakdowns by type and source.

![Dashboard](docs/screenshots/04-dashboard.png)

## Why This Exists

UIUC scatters opportunities across 7+ platforms with no unified view:

| Source | What it has | Problem | Our solution |
|--------|------------|---------|------|
| OUR Blog | Faculty-posted research positions | RSS feed exists but nobody parses it | ✅ Auto-parsed |
| SRO Database | 272+ external summer programs | 12 pages of unfiltered Drupal listings | ✅ 272 scraped |
| Handshake | Jobs + some research | Login-gated, mixes everything together | ✅ Cookie-auth collector |
| Department pages | Lab-specific openings | Scattered across 50+ faculty sites | ✅ 924 faculty from 10 depts |
| External REUs | 500+ NSF-funded programs | Requires knowing where to look | ✅ 476 from NSF API |
| Research Park | 800+ intern positions/year | Separate site, not linked to research | 🔜 Planned |

International freshmen have it worst: they can't tell what's realistic, what requires citizenship, or where to even start.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, React 18, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python 3.11, Pydantic v2 |
| Database | Supabase (profiles, favorites, interactions, version history) |
| Data Collection | BeautifulSoup, feedparser, requests, NSF Awards API |
| Matching | Three-layer scoring (eligibility × readiness × upside) + TF-IDF semantic similarity |
| LLM | OpenRouter / OpenAI for email refinement |
| Deploy | Vercel (frontend + backend), GitHub Actions (Mon/Thu auto-refresh) |

## Architecture

```
Data Sources (6 collectors: SRO, NSF REU, Faculty Dirs, Handshake, OUR RSS, Manual)
        │
        ▼
Normalization Pipeline (raw text → structured fields → skill/keyword inference)
        │
        ▼
Opportunity Database (1800+ normalized records, auto-refreshed Mon/Thu)
        │
        ▼
Matching Engine (eligibility × readiness × upside + TF-IDF semantic similarity)
        │
        ▼
Web Interface (Next.js + FastAPI + Supabase)
  ├── Profile form with resume parsing, GitHub import, auto-save
  ├── Ranked results with lab-specific explanations + filters
  ├── Cold email generator (3 variants + LLM refinement)
  └── Dashboard with live stats + user feedback tracking
```

## Run Locally

### Prerequisites
- Python 3.11+
- Node.js 18+

### Backend
```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The frontend proxies API requests to the backend automatically.

### Tests

```bash
# Backend: pytest — 98 unit + integration + API tests
pytest tests/ -v

# Frontend unit tests: vitest — 63 tests over lib/ modules
cd frontend
npm test

# Frontend E2E: playwright — 24 tests, real browser, runs both servers
cd frontend
npx playwright install chromium       # one-time browser download
npm run test:e2e                      # headless
npm run test:e2e:ui                   # watch/debug UI
```

All three suites run automatically in CI on every push/PR (see
`.github/workflows/ci.yml`).

## Project Structure

```
opportunity-filter-engine/
├── backend/                  # FastAPI REST API
│   ├── main.py               # App entry, CORS, routing
│   ├── schemas.py            # Pydantic request/response models
│   └── routes/
│       ├── matches.py        # POST /api/matches
│       ├── opportunities.py  # GET /api/opportunities
│       ├── cold_email.py     # POST /api/cold-email
│       └── resume.py         # POST /api/resume/upload
├── frontend/                 # Next.js 14 app
│   └── src/
│       ├── app/              # Pages (home, results, dashboard, about)
│       ├── components/       # MatchCard, ColdEmailModal, ResumeUpload, etc.
│       └── lib/              # API client, types, college data
├── src/                      # Core Python engine
│   ├── collectors/           # 6 source-specific scrapers
│   │   ├── uiuc_sro.py       # SRO database (272 opportunities)
│   │   ├── nsf_reu.py        # NSF REU Awards API (476)
│   │   ├── uiuc_faculty.py   # Faculty directories, 10 depts (924)
│   │   ├── handshake.py      # Handshake with cookie auth (75+)
│   │   └── uiuc_our_rss.py   # OUR RSS feed (25)
│   ├── matcher/              # Three-layer scoring + TF-IDF
│   │   ├── ranker.py         # Eligibility × readiness × upside
│   │   └── embeddings.py     # Semantic similarity (TF-IDF / OpenAI)
│   └── recommender/          # Cold email + resume gap advisor
├── data/
│   ├── processed/            # 1800+ normalized opportunities
│   └── manual_entries/       # Hand-curated entries
└── tests/                    # Integration tests
```

## Author

Guoyi Xu (Eric) - UIUC Electrical & Computer Engineering

## License

MIT
