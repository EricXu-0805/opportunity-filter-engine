# Roadmap

## Phase 1 — Product Definition ✅

**Status:** Complete

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

## Phase 2 — Build Opportunity Dataset ✅

**Status:** Complete (greatly exceeded original 50-100 target — now at 1900+ opportunities across 10+ collectors)

**Done:**
- [x] OUR Blog RSS collector (`src/collectors/uiuc_our_rss.py`)
- [x] SRO Database scraper (`src/collectors/uiuc_sro.py`)
- [x] Normalization pipeline (raw → schema)
- [x] Manual entry collector (`src/collectors/manual_importer.py`) + `data/manual_entries/`
- [x] URL parser for ad-hoc link submission (now full `/import` page with paste-URL + paste-text + LLM extraction — see [Round 12 in CHANGELOG](#shipped-rounds))
- [x] `international_friendly` tagging in normalization
- [x] `application_effort` tagging in normalization
- [x] Storage on Supabase (Postgres)

---

## Phase 3 — Matching Engine ✅

**Status:** Complete with the original three-layer design plus an opt-in semantic re-ranker.

**Done:**
- [x] Eligibility scorer
- [x] Readiness scorer
- [x] Upside scorer
- [x] Combined ranker with bucket assignment (High Priority / Good Match / Reach / Low Fit)
- [x] Template-based explanation generator (`reasons_fit`, `reasons_gap`, `next_steps`)
- [x] AI semantic re-rank toggle (TF-IDF; sentence-transformers / OpenAI optional)

---

## Phase 4 — MVP Interface ✅

**Status:** Complete; surpassed Streamlit plan with Next.js 16 + React 19 frontend.

**Done:**
- [x] Profile input form (college / major / grade / international / format / skills / coursework / interests / resume / GitHub / LinkedIn / search-weight slider)
- [x] Results page with bucket tabs, filter rail, search box, AI rerank toggle, keyboard navigation, pagination
- [x] Min-score, paid, international, source, on-campus, deadline filters with URL state
- [x] Opportunity detail page with PI contact, eligibility, application metadata, similar opportunities

---

## Phase 5 — Application Assistance ✅

**Status:** Complete plus several follow-ons (interaction tracker, notes, attachments, comparison view, cold email LLM refinement).

**Done:**
- [x] Cold email template generator (3 variants — formal / curious / specific)
- [x] LLM-powered personalized cold email drafts + quick-action refinement
- [x] Resume gap advisor (missing skills, recommended coursework, preparation timeline, resume tips)
- [x] Deadline tracking + urgency indicators (red / amber / gray)
- [x] Interaction tracker (applied / replied / interviewing / rejected / dismissed) with status timeline
- [x] Markdown notes + reminder timestamps per interaction
- [x] File attachments per opportunity (offer letters, screenshots, etc.)
- [x] Side-by-side `/compare` view for 2-3 starred opportunities

---

## Shipped Rounds (Post-V1, in merge order)

The repo has shipped 14 PRs of feature work + hardening on top of the original five phases. Highlights:

- **Round 1** — Next.js 14 → 16, React 18 → 19 upgrade
- **Round 12** — `/import` paste-text endpoint (LinkedIn / paywalled / no-URL flows)
- **Round 13** — `useLocalStorageJSON` transformer + `handleStar` race guard
- **Round 14** — Research Park collector + `uiuc_other` test coverage
- **Round 15** — Saved searches infrastructure (migration 010 + Supabase wrapper)
- **Round 16** — Saved searches UI (`/results` Save button + `/favorites` list)
- **Round 17** — Saved searches cron + new-match diff tracking (migration 011 + backend route + `.github/workflows/saved-searches-refresh.yml`)
- **Round 18** — New-match badges + `humanize-time` helper on `/favorites`
- **Round 19** — Highlight ring on `/results` via `?highlight=` URL param
- **Round 20** — Acknowledge / mark-seen mechanism (optimistic + server ack)
- **Round 21** — `useEffect` mount-cancellation guards across saved-searches load sites
- **Round 22** — Playwright e2e coverage for the saved-searches stack
- **Round 23** — README accuracy refresh

---

## Open / Planned

- **Email digest** — periodic email summarising new matches per saved search. **Blocked on email-collection UX decision** (where to ask, opt-in policy, frequency, transport reuse vs new).
- **USAJobs API integration** — federal positions; not started.
- **SerpApi for industry internships** — not started.
- **Multi-university expansion** — config-driven scraper registry; not started.
- **Full vector embeddings** — sentence-transformers + pgvector replacement for TF-IDF; not started.
- **Admin dashboard widget for saved-search cron health** — operator-facing surface noted in the R20 handoff queue.
