# Roadmap

## Phase 1 — Product Definition ✅

**Duration:** Complete

**Deliverables:**
- [x] README.md
- [x] Product scope definition
- [x] Data sources inventory with access methods
- [x] Opportunity schema
- [x] User profile schema
- [x] Matching logic design
- [x] International student logic
- [x] Folder structure

---

## Phase 2 — Build Opportunity Dataset

**Duration:** 1-2 weeks

**Goal:** Collect and normalize 50-100 opportunities

**Tasks:**
1. Implement OUR Blog RSS collector (`src/collectors/uiuc_our_rss.py`)
2. Implement SRO Database scraper (`src/collectors/uiuc_sro.py`)
3. Build normalization pipeline (raw → schema)
4. Manually curate 20-30 high-quality opportunities
5. Build URL parser for ad-hoc link submission
6. Tag all records with international_friendly
7. Tag all records with application_effort
8. Store in SQLite (local dev) or PostgreSQL (deployed)

**Exit criteria:** 50+ normalized opportunities with ≥80% field completeness

---

## Phase 3 — Matching Engine

**Duration:** 1-2 weeks

**Goal:** Score and rank opportunities for a given profile

**Tasks:**
1. Implement eligibility scorer
2. Implement readiness scorer
3. Implement upside scorer
4. Implement combined ranker with bucket assignment
5. Build template-based explanation generator
6. Test with 3-5 real student profiles
7. Tune weights based on feedback

**Exit criteria:** Given a profile, system returns ranked results with explanations that feel correct to test users

---

## Phase 4 — MVP Interface

**Duration:** 1 week

**Goal:** Working Streamlit app

**Tasks:**
1. Profile input form (minimal V1 fields)
2. Results display with score, bucket, explanation
3. "Best Matches Now" / "Worth Stretching For" split view
4. Basic search/filter sidebar
5. Opportunity detail expansion

**Exit criteria:** A user can fill in profile in < 3 minutes and get useful ranked results

---

## Phase 5 — Application Assistance

**Duration:** 1-2 weeks

**Goal:** Move from discovery to action

**Tasks:**
1. Cold email template generator (per opportunity)
2. Resume direction suggestions (per opportunity)
3. Deadline tracking / urgency indicators
4. "What you're missing" checklist per opportunity
5. Optional: LLM-powered personalized cold email drafts

**Exit criteria:** Users report they can take at least one concrete action from recommendations

---

## Future Phases (Post-V1)

- Phase 6: NSF REU API + USAJobs API integration
- Phase 7: SerpApi for industry internships
- Phase 8: Multi-university expansion (config-driven scraper registry)
- Phase 9: User accounts + saved opportunities + email alerts
- Phase 10: Semantic matching with sentence-transformers + pgvector
- Phase 11: React + FastAPI frontend for production deployment
