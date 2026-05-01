# Yaoxin's Session Log

> Personal log of everything Yaoxin (Kenny) does on this project, with or
> without help from opencode agents. Each session entry captures setup,
> features, bug fixes, workflow lessons, decisions, and commits. Future
> opencode sessions auto-append (see protocol in
> `repos/opencode/opportunity-filter-engine.md`).
>
> **Scope**: every meaningful operation — not just bugs. New features,
> refactors, configuration changes, decisions made and rejected, workflow
> insights all live here. Tiny edits (typo fixes, single-line renames) can
> be skipped.

---

## 2026-05-01 — Onboarding + compare redesign + AI chatbot + workflow lessons

**Setting**: First hands-on day on this project. xgy (Eric) did the main
build-out; Kenny joined as co-debugger and shipped four substantive
features in one session.

### 🛠 Setup

- Cloned `EricXu-0805/opportunity-filter-engine` to
  `C:\Users\kenny\source\repos\opportunity-filter-engine`. Last commit on
  main coming in: `c950e7d` (auto-refresh data).
- `pip install -r requirements.txt` → 26 packages.
- `npm install` (frontend) → 531 packages.
- `frontend/.env.local`: filled `NEXT_PUBLIC_SUPABASE_URL` +
  `NEXT_PUBLIC_SUPABASE_ANON_KEY` (prod values, anon is public-bundle-safe).
- `backend/.env`: documentation template only (backend has no python-dotenv).
  For dev: `$env:OFE_DISABLE_RATE_LIMIT='1'` in shell before launching.
- Verified end-to-end:
  - `GET /api/health` → 200
  - `GET /api/opportunities/stats/summary` → 1825 records / 1816 active
  - `/admin`, `/results`, `/dashboard`, `/favorites` all render
  - Next.js `/api/*` → backend rewrite works in dev

#### Setup gotchas

- ⚠️ `python` on PATH resolves to `C:\msys64\ucrt64\bin\python.exe` which
  is broken (missing stdlib `types` module). Real Python at
  `C:\Users\kenny\AppData\Local\Programs\Python\Python312\python.exe` —
  that's where pip and all deps installed. Always invoke uvicorn with the
  full path.
- npm via `npm.cmd` (PowerShell signing-policy issue with bare `npm`).

### ✨ Features shipped (4)

#### Feature 1 — Backend `/explain` endpoint extended (`feat(matches)`)

The `POST /api/matches/{id}/explain` endpoint previously returned only
a free-form `explanation` paragraph + `final_score` + `bucket`. The
compare page's bucket cards needed structured strengths/concerns lists,
which `rank_opportunity` already computes internally. Added five fields
to both the LLM and local-fallback response shapes:

```json
{
  "reasons_fit": [...],         // ✅ strengths bullets
  "reasons_gap": [...],         // ⚠️ concerns bullets
  "eligibility_score": 0-100,
  "readiness_score": 0-100,
  "upside_score": 0-100
}
```

Backwards-compatible additive change. Frontend `MatchExplanationResponse`
type updated to match.

**Commit**: `bc916b8`

#### Feature 2 — Compare page redesign (`feat(compare)`)

Old: single-column table that stacked 16+ rows of fields per opportunity
side-by-side. Information dense but no opinion — student couldn't tell
which one to apply to.

New: three stacked sections:

1. **Bucket cards** (top) — Top Match / Strong Backup / Reach.
   Each card shows match%, score-bar visual, strengths bullets (from
   `/explain.reasons_fit`), concerns bullets (`reasons_gap`), and an
   Apply button. Bucket label is position-based (after sorting by
   client-computed overall score), not raw match-score-based.
2. **Differences** (middle) — only fields that differ across opps. Color
   borders signal best/worst per row using a new `FIELD_SCORERS` map
   (per-field, NOT the 6 composite axes used by radar). Identical fields
   collapsed at top with "Show" toggle.
3. **Radar** (bottom) — SVG hex with 6 axes (skill / eligibility /
   effort / compensation / deadline-runway / intl-friendly). One colored
   polygon per opp + legend.

5 new files in `frontend/src/app/compare/`:
- `scores.ts` — `rankAndBucket()`, `FIELD_SCORERS`, `RADAR_AXES`,
  per-axis scoring functions
- `BucketCards.tsx` — top section, calls `getMatchExplanation` per opp
- `DifferencesSection.tsx` — middle section
- `RadarChart.tsx` — bottom section
- `CompareTable.tsx` — rewritten as orchestrator (was 256-line monolith,
  now 35 lines)

**Decision**: Kenny chose hybrid C+D over the four mockups I prepared.
Reasoning: cards answer "which one for me?", differences answer "where do
they differ specifically?", radar answers "how do they compare across
dimensions?". Each section pulls weight; A (per-row badges) felt
incremental, pure D (radar+cards no table) lost tabular precision.

**Commit**: `2a8825b`

#### Feature 3 — Favorites selection UX rework (`feat(favorites)`)

Old: every card had a checkbox in the top-right; floating "Compare N
selected" button auto-appeared at ≥2. Cluttered, ambiguous (looked like
"select to delete"-style UX).

New: deliberate flow.
- Top of `/favorites` has a single "Compare" button (visible if ≥2 favs)
- Click → enter selection mode: cards become click-selectable, blue ring
  on selected ones, white check icon overlay top-right
- Bottom sticky bar shows "已选 X / 3" + truncated titles + Cancel + Confirm
- Confirm → navigate to `/compare?ids=...`
- Cards mute their secondary actions (Draft Email, View Details, Star)
  during selection mode to prevent stray clicks

iOS-Photos-style flow. `MAX_COMPARE` dropped from 4 to 3 (and `tooMany`
i18n copy updated to match).

**Commit**: `c8c5357`

#### Feature 4 — Per-opportunity AI chatbot sidebar (`feat(opportunities)`)

Each opportunity detail page (`/opportunities/[id]`) now has an AI chat
panel anchored on the right (lg+) or behind a floating action button on
mobile (88vh slide-up drawer).

The chat is grounded in the specific opportunity's structured data via
a system prompt and optionally personalized with the user's profile
(toggleable on/off in the chat header, default on).

- Backend: new `POST /api/opportunities/{id}/chat`. Body:
  `{ message, history?, profile? }`. Mirrors the `/explain` LLM client
  pattern (OpenAI primary, OpenRouter fallback,
  `google/gemini-2.0-flash-lite-001` default model). Falls back to a
  structured snapshot of the opp when no LLM key is set, with a note to
  configure one.
- Frontend: `OpportunityChatbot.tsx` (new). Welcome message, 4 suggested
  questions, message bubbles (user blue, bot gray), input textarea with
  Enter-to-send, profile toggle, clear-conversation, error state, loading
  indicator. Last 10 messages of history sent with each request.
- Layout: `OpportunityDetail.tsx` outer wrapper changed `max-w-4xl` →
  `max-w-7xl`. Content wrapped in `flex flex-col lg:flex-row` with main
  content (max 2/3 width) + 360px-400px sticky aside on lg+ holding the
  chatbot. Mobile gets an indigo Sparkles FAB at bottom-right that opens
  a 88vh drawer with backdrop blur.

**Decision points** Kenny made:
- Mobile UX: FAB + drawer (vs always-shown stacked-below or fully hidden).
- Profile: default on, but with a per-conversation toggle.
- Differences middle section: collapse identical rows by default
  (vs always-show, vs tab-switch).

**Commit**: `3631d07`

### 🐛 Bugs fixed (4)

#### #1 — ColdEmailModal: "Open in Email | Gmail | Outlook" buttons misaligned

**Symptom**: Right-side split-button container in the cold-email modal
footer — Gmail and Outlook were visibly shorter than "Open in Email" and
a thin gray gap was visible between the gradient button and Gmail.

**Root cause** (two layered issues):
1. Container was `flex items-center` with mixed-height children: "Open in
   Email" (`text-sm py-2.5`) is 40px tall, Gmail/Outlook (`text-[11px]
   py-2.5`) are 37px tall. `items-center` vertically centered the
   shorter buttons, exposing 1.5px of footer background top + bottom.
2. The vertical divider `<div className="self-center w-px h-6 bg-blue-400" />`
   was 24px tall inside a 40px row, leaving 8px of unfilled space above
   and below — visible as a gray strip.

**Fix** (4 hunks in one file):
- Container: `flex items-center` → `flex items-stretch`
- Divider: removed `self-center` and `h-6` so it stretches full 40px
- Gmail/Outlook: added `inline-flex items-center justify-center` so their
  text stays vertically centered after the buttons grew taller

**Files**: `frontend/src/components/ColdEmailModal.tsx` (lines 469-495)

**Verified**: Playwright `getBoundingClientRect` on all 3 buttons +
divider showed all at `top=745, bottom=785, h=40`. Visual screenshot
confirmed flush.

**Commit**: `c87509a`

#### #2 — Compare page: grid layout collapsed to a single 1216px column

**Symptom**: Opening `/compare?ids=a,b,c` rendered an absurdly tall page
(~5000px) with each opportunity's data stacked vertically instead of
side-by-side. Should have been 4 columns (label + 3 opps), got 1.

**Root cause**: `CompareTable.tsx` built the grid columns class via
runtime string interpolation:

```tsx
const cols = `grid-cols-[minmax(140px,180px)_repeat(${opps.length},minmax(0,1fr))]`;
```

Tailwind's JIT compiler scans source files at **build time** for class
names. It never sees `grid-cols-[minmax(...)_repeat(3,...)]` as a
literal, so it never generates the corresponding CSS. At runtime, the
`class` attribute had the string but `display: grid` had no
`grid-template-columns` rule applied — browser fell back to
`grid-template-columns: none`, i.e. 1 column.

**Fix**: Switched from a Tailwind className to inline `style` prop:

```tsx
const gridStyle = { gridTemplateColumns: `180px repeat(${oppCount}, minmax(0, 1fr))` };
<div className="grid gap-2 ..." style={gridStyle}>
```

Inline styles bypass Tailwind JIT entirely.

**Files**: `frontend/src/app/compare/DifferencesSection.tsx` (and the new
orchestrator `CompareTable.tsx` no longer constructs dynamic class
strings).

**Verified**: `getComputedStyle(row).gridTemplateColumns` returned
`"180px 345px 345px 345px"` post-fix instead of `"1216px"` pre-fix.

**Commit**: rolled into `2a8825b`

#### #3 — Compare differences section: multiple coloring bugs

A bundle of issues spotted from a Kenny screenshot. All in
`DifferencesSection.tsx` and `scores.ts`. Five sub-bugs, fixed together.

##### 3a. "公民身份要求" row had no color borders, and red/green text was inverted

For an intl student looking at an opp where citizenship is required, the
"是" (yes, required) cell rendered in **green text** and "否" (no, not
required) cells rendered in **red text** — exactly opposite of the
user's interest.

Two layered bugs:
1. The citizenship FieldSpec had no `axis`, so the per-row color border
   logic never ran.
2. `CellContent` had a generic auto-color rule:
   `value === 'yes' → emerald text`, `value === 'no' → red text`. Fine
   for `international_friendly` (yes=good) but **inverted** for
   `citizenship_required` (yes=bad for intl).

Fix:
- Removed auto yes/no text coloring from `CellContent`. Color is now
  exclusively conveyed by the column's left border, which is field-aware.
- Added `citizenship` to a new `FIELD_SCORERS` map: returns `0` if
  `is_international && citizenship_required`, else `100`. Per-row
  coloring now correctly puts red border on the bad cell.

##### 3b. "未指定" / Unknown cells got no amber border

Rows like 付费 / 国际友好 where data is missing for some opps showed
those "未指定" cells with no visual indication, while a confirmed "yes"
cell got emerald — making absent data look identical to neutral.

Threshold logic was `score < 50` for amber. Unknown values returned
exactly `50` from scorers (`compensationScore('unknown') = 50`, etc.),
which **failed** the strict-less-than check.

Fix: amber threshold to `score < 60` (catches the 50 boundary), and
tightened red threshold to strict `< 50` (so unknown=50 doesn't
accidentally get red when it's the worst score in a row).

##### 3c. Tie-break only colored the first cell

When 2 of 3 cells had the same highest score, only the first one got
emerald. E.g. "专业" row where Col 2 and Col 3 both matched user's ECE
major — only Col 2 lit up green.

Code used `i === bestIdx` (index match), single-valued by construction.
Changed to `score === bestVal` (value match), so all tied-for-best cells
get emerald and all tied-for-worst get red.

##### 3d. Type/Organization/Duration rows had no border placeholder

Rows for non-scored fields rendered with no `border-l-4`, while scored
rows had it. Visual indent shifted by 4px between rows — the table
looked uneven.

Default `border-l-4 border-transparent` on all cells, so all rows align.
Color borders override the transparent default when the row is scored.

##### 3e. `majorMatchScore` couldn't handle abbreviations

User profile said "Electrical & Computer Engineering". Opp's
`eligibility.majors` said `["ECE", ...]`. The score returned `35` (no
match) instead of treating ECE as a match. This caused "专业" to color
wrong + downstream `eligibility` composite was off.

The match function only tokenized both sides and checked for token
overlap. `["electrical","computer","engineering"]` ∩ `["ece"]` = ∅.

Fix: added an abbreviation check — if the opp's major is 1 short token
(2-5 chars), check whether its letters spell the initials of the user's
major's tokens. `"ece"` matches initials `"e"+"c"+"e"` of
`"electrical computer engineering"` → return `90`.

```ts
if (mTok.length === 1 && mTok[0].length >= 2 && mTok[0].length <= 5) {
  const abbrev = mTok[0];
  if (abbrev === userInitials.slice(0, abbrev.length)) return 90;
}
```

**Files**: `frontend/src/app/compare/DifferencesSection.tsx`,
`frontend/src/app/compare/scores.ts`

**Verified**: DOM-query of every cell's `className` after fix:

```
薪酬: amber:— | emerald:NSF stipend | amber:—
国际友好: amber:未指定 | red:否 | amber:未指定
公民身份要求: emerald:否 | red:是 | emerald:否     ← inversion fixed
专业: red:Communication | emerald:Biology...ECE... | emerald:ECE,CS,Engineering...  ← tie-break fixed
```

**Commit**: rolled into `2a8825b`

#### #4 — PowerShell `Start-Process -RedirectStandardOutput` hangs persistent shell

**Symptom**: Every time a daemon (uvicorn, npm dev) was launched from
the opencode bash tool, the shell would appear to "hang" indefinitely —
the spawn command returned the PID immediately, but every subsequent
shell command (curl probes, taskkill, simple `ls`) would block.
Compounding effect: the LLM agent (me) would interpret the "no curl
response" as "spawn failed" and try to re-launch, making things worse.

**Root cause**: `Start-Process -RedirectStandardOutput X
-RedirectStandardError Y` makes PowerShell create the file streams in
the **parent** process and pass handles to the child. The opencode bash
tool runs in a **persistent** PowerShell session — the parent keeps
those redirect file streams alive after Start-Process returns, blocking
the session's event loop on the unclosed handles. The PID return is
honest; the daemon is fine.

**Fix**: Drop both redirect flags from the daemon launch:

```powershell
$proc = Start-Process -FilePath $PY -ArgumentList @(...) -PassThru -WindowStyle Hidden
$proc.Id | Out-File "$root\.backend.pid"
```

Tradeoff: no log file is captured for background daemons. For dev-time
debugging, run uvicorn / `npm run dev` in a foreground real terminal
instead, where stdout shows live.

To stop: `taskkill /T /F /PID <pid>` — `/T` kills the process tree
(npm.cmd → cmd.exe → node, etc.).

**Files**: This is a workflow / tool-usage rule, not a code change.
Documented in `repos/opencode/opportunity-filter-engine.md` so future
sessions don't repeat the mistake.

**Verified**: New launch pattern was used to (re)start backend +
frontend on 2026-05-01. PIDs returned cleanly, subsequent curl probes
worked, no shell stalls.

### 🔧 Workflow / tooling notes

- **Backend env loading**: backend has no `python-dotenv`. `backend/.env`
  is documentation only — values must be set in the shell before
  launching uvicorn (`$env:VAR='...'`).
- **Frontend HMR**: works automatically on file save during `npm run dev`.
  Most styling/UI iteration just needs save+refresh. Doesn't catch all
  syntax errors as silently as you'd expect though — check the dev
  console and the terminal log.
- **Playwright for visual verification**: incredibly useful — used
  `browser_evaluate` with `getBoundingClientRect` to confirm the modal
  button height bug had real measurements (40 vs 37 px) backing the
  visual diagnosis. Same pattern for the differences-section coloring
  fix: queried every cell's `className` to enumerate which got which
  color.
- **Tailwind JIT pitfall**: never construct class names via runtime
  template strings. Tailwind only sees source-time literals. Use inline
  `style={{ gridTemplateColumns: ... }}` for dynamic values.
- **Daemon spawning on Windows + persistent PowerShell**: drop
  `-RedirectStandardOutput` from `Start-Process`. See bug #4.

### 📦 Commits this session

```
c87509a fix(modal): align Open in Email split-button group
bc916b8 feat(matches): expose reasons_fit/reasons_gap and sub-scores in /explain
2a8825b feat(compare): redesign with bucket cards, differences, radar
c8c5357 feat(favorites): rework compare selection UX
3631d07 feat(opportunities): add per-opportunity AI chatbot sidebar
24aee63 docs: add yaoxin_bug_log.md and ignore *.pid
[next]  docs: rename log → yaoxin_log.md, expand to full session scope
```

### 💡 Decisions / followups

- **LLM polish currently in fallback mode** — backend `/chat` and
  `/explain` both return structured fallbacks because no
  `OPENROUTER_API_KEY` / `OPENAI_API_KEY` is set on the local backend.
  To enable: `$env:OPENROUTER_API_KEY = 'sk-or-...'` then taskkill the
  backend and re-spawn. Default model
  `google/gemini-2.0-flash-lite-001` is free on OpenRouter.
- **Compare's `tooMany` copy** is hardcoded to "3". If `MAX_COMPARE`
  ever changes, update both `favorites/page.tsx` and `dictionaries.ts`.
- **Mobile chatbot drawer** fixed at 88vh — could be made resizable
  later if users complain.
- **Compare's per-field scorers** vs **radar's 6 composite axes** are
  intentionally separate. The radar's `eligibility` axis is a weighted
  sum of major + year + intl, but the differences section uses
  `FIELD_SCORERS.majors` (just major-match) for the "专业" row. Same
  data, different aggregation level. Don't conflate them.
- **Push** to `EricXu-0805/opportunity-filter-engine` was approved by
  Kenny on 2026-05-01 after the 6-commit batch landed locally.

---

<!-- New session entries get appended below this line, newest first.
     Skeleton:

## YYYY-MM-DD — short title

**Setting**: ...

### 🛠 Setup (skip if no setup happened)
### ✨ Features shipped (N)
### 🐛 Bugs fixed (N)
### 🔧 Workflow / tooling notes
### 📦 Commits this session
### 💡 Decisions / followups
-->
