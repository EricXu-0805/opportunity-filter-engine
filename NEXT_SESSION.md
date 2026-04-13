# Next Session TODO

## Completed (this session)
- [x] Skill Proficiency Tags: beginner/experienced/expert toggle per skill, weighted matching
- [x] Email Editor: two-panel layout (left: editable email + variant tabs, right: chat refinement panel)
- [x] LinkedIn/GitHub Integration: URL fields in profile, GitHub repo language parsing + skill import
- [x] Why It Fits: specific skill overlap, proficiency-weighted matching, research interest alignment

## Priority 1: LLM Chat-Based Email Editing
- Wire up OpenAI API for the chat panel in ColdEmailModal
- Currently uses local text transformations (formal/shorter/enthusiastic/coursework)
- Add streaming responses for a real chat experience
- Requires OPENAI_API_KEY env var setup

## Priority 2: GitHub Deep Integration
- Parse repo READMEs for project descriptions
- Use GitHub contribution graph as experience signal
- Auto-infer proficiency level from commit frequency per language

## Priority 3: Richer Opportunity Data
- Enrich opportunities with PI research descriptions
- Scrape faculty pages for current research topics
- Match against student research_interests_text with semantic similarity

## Priority 4: Profile Persistence
- Sync profile changes to Supabase in real-time (debounced)
- Add profile versioning / history
- Share profile via URL

## Current State
- Live: https://frontend-wine-pi-63.vercel.app
- Backend: https://opportunity-filter-engine.vercel.app/api
- Supabase: mjpirkyduibkakvlbdko
- GitHub: EricXu-0805/opportunity-filter-engine
