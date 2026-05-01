# Yaoxin's Bug Log

> Personal bug-fix log maintained by Yaoxin (Kenny).
> Each entry records: symptom → root cause → fix → files → verification.
> Future opencode sessions auto-append new entries when fixing bugs.

---

## 2026-05-01

### #1 — ColdEmailModal: "Open in Email | Gmail | Outlook" buttons misaligned

**Symptom**: In the cold-email modal footer, the right-side split-button container looked off — Gmail and Outlook were visibly shorter than "Open in Email" and a thin gray gap was visible between them.

**Root cause** (two separate bugs):
1. Container was `flex items-center` with mixed-height children:
   - "Open in Email" (`text-sm py-2.5`) → 40px tall
   - "Gmail" / "Outlook" (`text-[11px] py-2.5`) → 37px tall
   `items-center` vertically centered the shorter buttons, exposing 1.5px of footer background top + bottom.
2. The vertical divider `<div className="self-center w-px h-6 bg-blue-400" />` was 24px tall inside a 40px row, leaving 8px of unfilled space above and below — visible as a gray strip between the gradient and Gmail.

**Fix** (4 hunks in one file):
- Container: `flex items-center` → `flex items-stretch` so all buttons stretch to row height.
- Divider: removed `self-center` and `h-6` so it stretches full 40px.
- Gmail/Outlook buttons: added `inline-flex items-center justify-center` so their text stays vertically centered after the buttons grew taller.

**Files**: `frontend/src/components/ColdEmailModal.tsx` (lines 469-495)

**Verified**: Playwright `getBoundingClientRect` on all 3 buttons + divider showed all at `top=745, bottom=785, h=40`. Visual screenshot confirmed flush block.

---

### #2 — Compare page: grid layout collapsed to a single 1216px column

**Symptom**: Opening `/compare?ids=a,b,c` rendered an absurdly tall page (~5000px) with each opportunity's data stacked vertically instead of side-by-side. Should have been 4 columns (label + 3 opps), got 1.

**Root cause**: `CompareTable.tsx` built the grid columns class via runtime string interpolation:

```tsx
const cols = `grid-cols-[minmax(140px,180px)_repeat(${opps.length},minmax(0,1fr))]`;
```

Tailwind's JIT compiler scans source files at **build time** for class names. It never sees `grid-cols-[minmax(...)_repeat(3,...)]` as a literal, so it never generates the corresponding CSS. At runtime, the `class` attribute had the string but `display: grid` had no `grid-template-columns` rule applied — browser fell back to `grid-template-columns: none`, i.e. 1 column.

**Fix**: Switched from a Tailwind className to inline `style` prop:

```tsx
const gridStyle = { gridTemplateColumns: `180px repeat(${oppCount}, minmax(0, 1fr))` };
<div className="grid gap-2 ..." style={gridStyle}>
```

Inline styles bypass Tailwind JIT entirely.

**Files**: `frontend/src/app/compare/DifferencesSection.tsx` (and the new `CompareTable.tsx` orchestrator no longer constructs dynamic class strings).

**Verified**: `getComputedStyle(row).gridTemplateColumns` returned `"180px 345px 345px 345px"` post-fix instead of `"1216px"` pre-fix.

---

### #3 — Compare differences section: multiple coloring bugs

A bundle of issues spotted from a Kenny screenshot. All in `DifferencesSection.tsx` and `scores.ts`.

#### 3a. "公民身份要求" row had no color borders, but red/green text colors were inverted

**Symptom**: For an intl student looking at an opp where citizenship is required, the "是" (yes, required) cell rendered in **green text** and "否" (no, not required) cells rendered in **red text** — exactly opposite of the user's interest.

**Root cause**: Two layered bugs:
1. The citizenship FieldSpec had no `axis`, so the per-row color border logic never ran.
2. `CellContent` had a generic auto-color rule: `value === 'yes' → emerald text`, `value === 'no' → red text`. Fine for `international_friendly` (yes=good) but **inverted** for `citizenship_required` (yes=bad for intl).

**Fix**:
- Removed auto yes/no text coloring from `CellContent`. Color is now exclusively conveyed by the column's left border, which is field-aware.
- Added `citizenship` to a new `FIELD_SCORERS` map: returns `0` if `is_international && citizenship_required`, else `100`. Per-row coloring now correctly puts red border on the bad cell.

#### 3b. "未指定" / Unknown cells got no amber border

**Symptom**: Rows like 付费/国际友好 where data is missing for some opps showed those "未指定" cells with no visual indication, while a confirmed "yes" cell got emerald — making absent data look identical to neutral.

**Root cause**: Threshold logic was `score < 50` for amber. Unknown values returned exactly `50` from scorers (`compensationScore('unknown') = 50`, etc.), which **failed** the strict-less-than check.

**Fix**: Changed amber threshold to `score < 60` (catches the 50 boundary), and tightened red threshold to strict `< 50` (so unknown=50 doesn't accidentally get red when it's the worst score in a row).

#### 3c. Tie-break only colored the first cell

**Symptom**: When 2 of 3 cells had the same highest score, only the first one got emerald. E.g. "专业" row where Col 2 and Col 3 both matched user's ECE major — only Col 2 lit up green.

**Root cause**: Code used `i === bestIdx` (index match), which by construction is single-valued.

**Fix**: Changed to `score === bestVal` (value match), so all tied-for-best cells get emerald and all tied-for-worst get red.

#### 3d. Type/Organization/Duration rows had no border placeholder

**Symptom**: Rows for non-scored fields rendered with no `border-l-4`, while scored rows had it. Visual indent shifted by 4px between rows — the table looked uneven.

**Fix**: Default `border-l-4 border-transparent` on all cells, so all rows align. Color borders override the transparent default when the row is scored.

#### 3e. `majorMatchScore` couldn't handle abbreviations

**Symptom**: User profile said "Electrical & Computer Engineering". Opp's `eligibility.majors` said `["ECE", ...]`. The score returned `35` (no match) instead of treating ECE as a match. This caused "专业" to color wrong + downstream `eligibility` composite was off.

**Root cause**: The match function only tokenized both sides and checked for token overlap. `["electrical","computer","engineering"]` ∩ `["ece"]` = ∅.

**Fix**: Added an abbreviation check — if the opp's major is 1 short token (2-5 chars), check whether its letters spell the initials of the user's major's tokens. `"ece"` matches initials `"e"+"c"+"e"` of `"electrical computer engineering"` → return `90`.

```ts
if (mTok.length === 1 && mTok[0].length >= 2 && mTok[0].length <= 5) {
  const abbrev = mTok[0];
  if (abbrev === userInitials.slice(0, abbrev.length)) return 90;
}
```

**Files**: `frontend/src/app/compare/DifferencesSection.tsx`, `frontend/src/app/compare/scores.ts`

**Verified**: DOM-query of every cell's `className` after fix:
```
薪酬: amber:— | emerald:NSF stipend | amber:—
国际友好: amber:未指定 | red:否 | amber:未指定
公民身份要求: emerald:否 | red:是 | emerald:否     ← inversion fixed
专业: red:Communication | emerald:Biology...ECE... | emerald:ECE,CS,Engineering...  ← tie-break fixed
```

---

### #4 — PowerShell `Start-Process -RedirectStandardOutput` hangs the persistent shell

**Symptom**: Every time a daemon (uvicorn, npm dev) was launched from the opencode bash tool, the shell would appear to "hang" indefinitely — the spawn command returned the PID immediately, but every subsequent shell command (curl probes, taskkill, simple `ls`) would block. Compounding effect: the LLM agent (me) would interpret the "no curl response" as "spawn failed" and try to re-launch, making things worse.

**Root cause**: `Start-Process -RedirectStandardOutput X -RedirectStandardError Y` makes PowerShell create the file streams in the **parent** process and pass handles to the child. The opencode bash tool runs in a **persistent** PowerShell session — the parent keeps those redirect file streams alive after Start-Process returns, blocking the session's event loop on the unclosed handles. The PID return is honest; the daemon is fine.

**Fix**: Drop both redirect flags from the daemon launch:

```powershell
$proc = Start-Process -FilePath $PY -ArgumentList @(...) -PassThru -WindowStyle Hidden
$proc.Id | Out-File "$root\.backend.pid"
```

Tradeoff: no log file is captured for background daemons. For dev-time debugging, run uvicorn / `npm run dev` in a foreground real terminal instead, where stdout shows live.

To stop: `taskkill /T /F /PID <pid>` — `/T` kills the process tree (npm.cmd → cmd.exe → node, etc.).

**Files**: This is a workflow / tool-usage rule, not a code change. Documented in `repos/opencode/opportunity-filter-engine.md` so future sessions don't repeat the mistake.

**Verified**: New launch pattern was used to (re)start backend + frontend on 2026-05-01. PIDs returned cleanly, subsequent curl probes worked, no shell stalls.

---

<!-- New entries get appended here. Format per the entries above:
   ### #N — One-line title
   **Symptom**: ...
   **Root cause**: ...
   **Fix**: ...
   **Files**: ...
   **Verified**: ...
-->
