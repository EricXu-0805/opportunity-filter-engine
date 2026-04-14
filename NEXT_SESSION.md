# Next Session TODO

## Completed (this session)
- [x] **UIUC Faculty Collector**: 10 departments, 924 new opportunities from CS/ECE/Physics/Chemistry/MechSE/BioE/MatSE/STAT/Math/iSchool faculty directories
- [x] **Embedding Semantic Matching**: Upgraded from token-count cosine to scikit-learn TF-IDF (with ngrams + sublinear TF). OpenAI/OpenRouter embedding support ready when API key added.
- [x] **OpenRouter LLM Support**: Email editor now supports OpenRouter (free tier) in addition to OpenAI for chat-based email refinement
- [x] **Profile Auto-Save**: Debounced 1.5s auto-save to Supabase + localStorage on every profile change. Save status indicator ("Saving..." / "Profile saved")
- [x] **Profile Version History**: New `profile_versions` Supabase table tracks every save (migration: 003_profile_versions.sql)
- [x] **OpenAI dependency**: Added `openai>=1.0` to requirements.txt for Vercel deployment
- [x] **Frontend filter**: Added "Faculty Research" as filterable source in results page

## Stats After This Session
- Total opportunities: **1730** (was 806)
- Data sources: **5** (was 4) — added `uiuc_faculty`
- Faculty departments scraped: 10
- Frontend build: passing

## Priority 1: Deploy & Verify
- Run migration `003_profile_versions.sql` in Supabase Dashboard (SQL Editor → paste & run)
- Set `OPENROUTER_API_KEY` on Vercel backend (Settings → Environment Variables)
- Push & deploy, verify email editor LLM works

## Priority 2: Faculty Enrichment
- Run `python -m src.collectors.uiuc_faculty --save` (WITH enrichment, ~15min) to get emails + research keywords for all 924 faculty
- Or wait for Monday GitHub Action deep scrape

## Priority 3: Handshake Data Source
- Needs login authentication (UIUC SSO)
- Complex scraper engineering
- Consider using browser automation (Playwright)

## Priority 4: More Upgrades
- Semantic matching with OpenAI embeddings (needs API key on Vercel)
- UIUC department-specific "open positions" pages (not just faculty directories)
- Profile sharing via URL
- Notification when new opportunities match your profile

## Current State
- Live: https://frontend-wine-pi-63.vercel.app
- Backend: https://opportunity-filter-engine.vercel.app/api
- Supabase: mjpirkyduibkakvlbdko
- GitHub: EricXu-0805/opportunity-filter-engine
