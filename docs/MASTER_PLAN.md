# OFE MASTER PLAN — Top-50 Faculty Data Expansion + Landing the Product

> **Status:** durable plan, written 2026-06-15. Self-contained. A future session executes from this without re-deriving anything.
> **Owner roles:** Eric = founder/operator + the human who presses "send" + does Stripe/legal/manual fulfillment. This plan = lead engineer + strategist working brief.
> **One-line frame:** OFE is a 小事业 (small real business). The expansion in this doc is the **parallel scale track**. It must NEVER consume the attention owed to the 30-day concierge validation. Until the first non-friend paying/retained user exists, expansion is a *low-cost background bet*, not the main event.

---

## 0. TL;DR for a future session (read this first, then §8)

1. **Do not treat shipping schools as progress toward revenue.** The hard demand signal is one paying/retained stranger for "apply for me" within 30 days (§7a). That gate owns *prioritization*; this expansion runs in parallel but never pre-empts it.
2. **Wave 0 (collector generalization) ships before any new school.** It's the architectural unblocker. Spec in §3. Until it lands, the 5 Berkeley-dept clones are the only cheap faculty work.
3. **Filtering correctness is a HARD gate (§2).** Data expansion must not leak campus rows cross-school or silently show F-1 students citizenship-restricted opps as clean matches. Two known bugs + invariants + tests are in §2. Every new campus collector MUST land its `SOURCE_DEFAULTS` entry in the SAME PR.
4. **Schools are tiered by feasibility × effort × audience value ONLY (§4).** F-1-friendliness is NOT a ranking or defer reason — domestic/local sources are in scope as data; the *filter* handles the international/domestic split per-user.
5. **Defer only SPA/Cloudflare-hard schools (§4.4)** until a headless-fetch path exists — and say which + why. No silent drops.

---

## 1. North Star & the Validation-First Rule

### 1.1 The north star (Eric-confirmed: "就是我之前说的那个最终想法")
A fully-autonomous AI application-agent platform:

> Student fills in profile → engine matches opportunities → each opportunity gets a **per-target, graded-autonomy agent** that tailors the resume → drafts and sends cold emails → follows up by deadline → parses replies.

- **Scale path:** UIUC → US top-100 → global.
- **Business model = freemium.** Free tier (match + explanation) is the top-of-funnel that grows retention. Paid tier (agent auto-send / follow-up / reply-parsing) is the revenue engine. Same path, two stages: **validate free-tier retention first, then layer on paid agent.**
- **Moat = match quality + explanation + draft quality + honest, international-student-aware reachability judgment.** NOT degree of automation — 2026 generic agent frameworks already commoditize auto-delivery.
- **Autonomy is long-term pinned at L1/L2-confirm (a human presses send).** Emails carry Eric's real name to UIUC/peer-tier professors; a botched blast damages Eric's personal reputation. **声誉 > 速度.**

### 1.2 The validation gate (the hard trigger everything sequences behind)
**Mechanism (Wizard-of-Oz / concierge):** ship a "帮我投 + 付费/意向" button. Front-end pretends to be the agent; back-end = **Eric MANUALLY confirms and hand-sends every email.** Tests willingness-to-pay-for-an-outcome directly, carries zero reputation risk (Eric reviews every email), zero infra cost.

**Hard metric:** within 30 days, get the **FIRST paying-or-retained user who is NOT a friend/family member**, for "apply for me." Likely payer = an anxious parent (the study-abroad / research-application agency market has already proven WTP; OFE's wedge is 10×+ cheaper and more honest — states real reachability instead of selling dreams).

**If the gate is not met in 30 days:** OFE downgrades in the portfolio. **Until the gate passes, STOP operating OFE in "终态版" mode** — stop treating feature-stacking / engine-polishing as progress.

### 1.3 Why mass expansion was deferred — and how it's allowed to run anyway (Munger inversion)
The question is not "how many features from the end state are we," but **"what is the minimum evidence that earns the right to keep building."** Sequence: **③ validate → ① build the agent loop → ② only then scale.**

Mass multi-school expansion + full-autonomy auto-send are **FROZEN for *prioritization*** until the first real paying/retained user — because, until then, they are a **"高产出感陷阱"** (high-output-FEELING trap), the same failure mode as SMA's 9 unshipped design docs. "Wrote 200+ PRs" is the same trap as "wrote 9 docs" if the repo has 0 stars, ~5 active users, zero paid.

**BUT** this expansion is *cheap config-clone work* (Berkeley-dept clones ≈ ~50-line configs after Wave 0) and may proceed as a **low-cost background bet to keep exploration variance up** (it's 2026, only ~19 weeks in — too early to over-converge: "3 things heavily invested + a basket of cheap bets in play"). It builds the durable corpus and lights up empty UI surfaces (each new school populates the switcher). It does **NOT** substitute for proving someone pays, and it must **never become the thing that consumes the attention owed to concierge validation.**

**Rule of thumb for any future session:** if you are about to spend a block of attention on this expansion while the concierge button isn't live or the 30-day clock is running with no validation activity — **stop and do §7a instead.**

---

## 2. Filtering / Eligibility Correctness — HARD GATE

> **Invariant:** data expansion must not break the eligibility filter. As we add many schools with mixed `international_friendly` values and many campus collectors, two failure modes get more likely: (a) campus rows leaking cross-school, (b) F-1 students seeing citizenship-restricted opps as clean matches. Both are guarded below.

### 2.1 How the filter works today (two layers)

**Layer 1 — Scoring** (`src/matcher/ranker.py:591-611`, `score_eligibility`):
- `intl_score` starts 100; the **entire intl block is gated `if profile.get("international_student")`** (ranker.py:592). A domestic student never enters it → citizenship-restricted opps keep `intl_score=100`.
- `friendly = elig.get("international_friendly","unknown")`:
  - `"no"` → `intl_score=0.0` + gap "Requires US citizenship or permanent residency".
  - `"unknown"` → `INTL_UNKNOWN_SCORE` (config.py:60 = 60.0), an internship-aware "verify-don't-rule-out" gap.
  - `"yes"` → fit "Open to international students".
- intl is 0.20 of the eligibility layer (ranker.py:679).

**Layer 2 — Hard-filter** (`rank_all`, ranker.py:1421-1424): ONLY for `international_student`, drops `international_friendly=="no"` records when `preferences.exclude_citizenship_restricted` is True (default True). The pref is supplied by `backend/routes/matches.py:53-59`: when the client sends no preferences (the Next.js path always omits it — `frontend/src/lib/api.ts:54-78 toProfileRequest`), it sets `exclude_citizenship_restricted = international_student` (True for F-1, False for domestic). Schema default is True (`backend/schemas.py:17`).

**Scope model** (`src/normalizers/school_audience.py`): every record gets top-level `school` (host slug or `None`=national) + `audience` ('campus'/'open'/'unknown') from `SOURCE_DEFAULTS` by source; unmapped sources fall to `(None,'unknown')`. `rank_all` foreign-campus exclusion (ranker.py:1413-1419) drops an opp ONLY when `opp_school is not None AND != home_school AND audience=="campus"`. `None`(national)/open/unknown always pass. Frontend mirrors this (`discovery-scope.ts matchesScope`, `badge-utils.ts getIntlBadge` always paints `"no"` as a red "US only" badge).

### 2.2 Verdicts (from FILTER_AUDIT)

- **Domestic-sees-all: CORRECT.** Every citizenship/scope gate is behind `if international_student`; domestic `exclude_citizenship_restricted` is forced False (matches.py:58). No record is ever dropped for a domestic user on citizenship grounds. A UIUC home_school user keeps all uiuc campus rows + national + open + unknown. Domestic users are **not** over-filtered.
- **F-1 flagging: CORRECT for `international_friendly`.** `"no"` → `intl_score=0` + red "US only" badge + excludable. A kept restricted opp is never shown as a clean match.

### 2.3 Known bugs / gaps (carry forward — fix as part of the filter-correctness gate)

**BUG A — citizenship_required is ignored by the main matcher (silent clean-match for F-1).**
The matcher keys ONLY off `international_friendly`, never `eligibility.citizenship_required`. `normalizer.py:_check_citizenship` (168-176, set at :58) can mark `citizenship_required=True` from text ("must be a US citizen") while `international_friendly` stays `'unknown'`. The two are linked ONLY by the LLM tagger (`llm_tagger.py:481`), and only when it runs on a still-`'unknown'` field. Any record the tagger didn't fire on scores `INTL_UNKNOWN_SCORE=60` for an F-1, shows the orange "verify" badge, and is NOT excluded — a citizenship-restricted posting silently shown as a near-clean match. The compare view already does the right thing (`compare/scores.ts:179`: `citizenship_required && is_international → 0`), proving the **main matcher is the inconsistent one.** This gap gets WORSE as we add domestic/US-only sources.

**BUG B — foreign-campus on-campus work-auth bonus.**
`on_campus` is collector-stamped, not derived from school/audience (UCB rows = on_campus=False; UIUC = on_campus=True). If a new school's campus collector stamps `on_campus=True` for a foreign campus, it (a) feeds the F-1 "On-campus — no work authorization concerns" upside bonus (ranker.py:752-755) for a campus the student can't work on, and (b) wrongly matches the frontend `onCampus='yes'` facet.

**LEAK risk (highest-impact expansion bug) — unmapped campus collector.**
`SOURCE_DEFAULTS` is the ONLY place school/audience is assigned. A new school's CAMPUS collector NOT added to `SOURCE_DEFAULTS` falls to `(None,'unknown')` = national+open → its campus-only rows **LEAK to every other school's users** and bypass foreign-campus exclusion (which requires `school is not None`). `data_loader` does NOT call `apply_school_audience` — only `refresh_all.py:366` does; any record reaching served JSON without school/audience keys is treated national/visible-to-all.

### 2.4 Invariants that MUST hold as we add schools (enforce in code + tests)

1. **Every new campus collector lands its `SOURCE_DEFAULTS` entry in the SAME PR.** Omission = national+open leak. (After Wave 0, this is auto-built from the registry — see §3 — which structurally prevents the leak.)
2. **Every record out of `refresh_all` has non-null `audience` ∈ `VALID_AUDIENCES`**, and any record with `school != None && audience=='campus'` came from a source present in the registry/`SOURCE_DEFAULTS`. **Fail the build otherwise.**
3. **New campus collectors stamp `on_campus` relative to the HOST school.** Foreign-campus faculty rows = `on_campus=False` (matches existing UCB convention).
4. **`international_friendly` default stays `'unknown'`, never silently `'no'`.** Mixed-value expansion is safe as long as the default is conservative.
5. **The matcher must honor `citizenship_required` (fix BUG A) before we ingest many US-only domestic sources** — otherwise F-1 students get a rising tide of orange-60 false matches.

### 2.5 Required filter-correctness work (do these as a small PR block, gating the domestic-heavy waves)

- **Fix BUG A:** in `score_eligibility` (ranker.py:592-611) and the `rank_all` hard-filter (1421-1424), treat `citizenship_required==True` the same as `international_friendly=='no'` for F-1 (score 0 + gap + excludable). Aligns the main matcher with `compare/scores.ts:179`.
- **Fix BUG B:** in `score_upside` (ranker.py:752-755), only grant the on-campus work-auth bonus when `opp.school is None or == profile home_school`.
- **DQ/refresh assertion:** fail the build if any record has `school != None && audience=='campus'` from an unregistered source, or null/invalid audience (invariant 2).
- **Regression tests (add to the suite):**
  - F-1 profile + opp `{citizenship_required: True, international_friendly: 'unknown'}` → flagged (intl_score 0 / restricted reason) AND excludable; the SAME opp must NOT be penalized for a domestic profile.
  - New peer-school campus row (e.g. `school='uw', audience='campus'`) is hidden from a UIUC home_school F-1 AND domestic user; national/open/unknown rows always pass.
  - Foreign-campus row stamped `on_campus=True` does NOT earn the work-auth bonus for an F-1 whose `home_school != opp.school`.
- **Defend the preferences default:** either have the Next.js client always send `preferences` (mirroring `streamlit_app.py:451-456`) with `exclude_citizenship_restricted` derived from `is_international`, or change `ProfilePreferences` default (schemas.py:17) so a partial preferences object can't silently flip True for a domestic student.
- **Observability:** add a metric for records with `citizenship_required==True && international_friendly=='unknown'` (the un-reconciled set the matcher currently mishandles); confirm the LLM tagger runs on every refresh.

> **Do NOT re-raise the 38 refuted findings or OAuth items** (Google live/verified; Microsoft publisher-verification deferred until Eric buys his own domain/entity).

---

## 3. The Unblocker — Collector Generalization (Wave 0)

> **Ships before ANY new (non-Berkeley) school.** The 5 Berkeley-dept clones (EPS/ME/IEOR/BioE/MSE) need NO refactor and can proceed regardless. Any peer school (UW/UT/Stanford/GT/Wisc/Michigan/…) REQUIRES this first.

### 3.1 Why it's blocking
`src/collectors/ucb_common.py::normalize_faculty` hardcodes Berkeley in ≥4 places:
- L399 `organization = 'University of California, Berkeley'`
- L405 `location = 'Berkeley, CA'`
- L380 description string
- L372 id-prefix `faculty-ucb-{dept_short}-{name_hash}`

Plus: L75-80 `NOISE_EMAILS` (berkeley mailboxes); L242 email prefers `.endswith('berkeley.edu')`; L499 joint-appointment dedup keyed on `ucb_*` prefix; `school_audience.py:35-40` `SOURCE_DEFAULTS` hardcodes `ucb_*`; `deactivate_stale_faculty.py:29-35` `FACULTY_SOURCES` hardcodes 5 UCB sources; `refresh_all.py:255-277` hardcodes the Berkeley loop with EECS-before-STAT merge order; `url_parser.py:514` hardcodes `berkeley.edu → org`.

**Critical constraint:** all new config fields DEFAULT to the Berkeley value so the 4 existing UCB collectors stay **byte-identical** — id-stability tests pin exact ids (e.g. `faculty-ucb-chem-988f716c`). Keep `campus_slug` default `'ucb'`.

### 3.2 New modules + dataclasses

**`src/collectors/school_config.py` (NEW)** — `SchoolConfig` (NamedTuple):
- `school_slug: str` (e.g. `'ucb'`, `'umich'`, `'stanford'`)
- `organization_name: str` · `location: str`
- `id_prefix: str` (e.g. `'faculty-ucb'`)
- `primary_domain: str` (e.g. `'berkeley.edu'`) — replaces hardcoded `.endswith('berkeley.edu')`
- `noise_emails: frozenset[str]`
- `keyword_bank: list[str]` (default = `KEYWORD_BANK` from ucb_common)
- `departments: dict[str, DepartmentConfig]`

**`DepartmentConfig` (NamedTuple):**
- `source_id: str` (e.g. `'ucb_stat_faculty'`) · `name: str` · `short_code: str`
- `url: str` · `base: str` · `majors: list[str]`
- `collector_shape: str` ∈ `{'open_berkeley_card', 'bespoke_html', 'inline_parser', 'table_list'}`
- `selectors: dict | None` (for card shape)
- `parser_class: str | None` (names a callable in the module, for bespoke/inline)
- `area_keywords: dict[str, list[str]] | None` (EECS-style tag→keywords)
- `keywords: list[str]` (broad-only fallback) · `title_filter_regexes: list[str]` (emeritus, see §6) · `work_auth_notes: str`

Plus a `SCHOOL_REGISTRY` object exposing: `register(slug, cfg)`, `get(slug)`, `get_all_sources()`, `get_faculty_sources()`, `iter_faculty_collectors(order=[...])`, `get_domain_org_map()`.

**`src/collectors/faculty_base.py` (NEW)** — generic router:
```
fetch_and_normalize(school_config: SchoolConfig, dept_config: DepartmentConfig, enrich: bool = True) -> list[dict]
```
Routes by `collector_shape` to existing (now-parameterized) ucb_common functions or to the bespoke parser named in `dept_config.parser_class`. Preserves the profile-hop enrich path.

### 3.3 Refactors (each new field defaults to Berkeley value → byte-identical UCB output)

1. **`ucb_common.py`** — remove hardcodes; `normalize_faculty(person, school_config, dept_config)`, `merge_into_processed(new_opps, school_config)`. Joint-appointment dedup (`drop_joint_appointment_duplicates`) switches from `'ucb_*'` prefix to dynamic `school_slug`.
2. **`ucb_stat_faculty.py` / `ucb_chem_faculty.py`** — replace inline config + call with a factory call from `SCHOOL_REGISTRY`.
3. **`ucb_cee_faculty.py`** — `_scrape_cee_faculty_list()` becomes a registered `parser_class` (`bespoke_html`).
4. **`ucb_eecs_faculty.py`** — `_scrape_eecs_faculty_list()` registered `parser_class` (`inline_parser`); `EECS_AREA_KEYWORDS` → `DepartmentConfig.area_keywords`.
5. **`school_audience.py`** — `SOURCE_DEFAULTS` becomes `_build_source_defaults(SCHOOL_REGISTRY)` at import: each faculty collector auto-registers `(school_slug, 'campus')`; aggregators `(None, 'open')`. **This structurally kills the leak in §2.3.**
6. **`deactivate_stale_faculty.py`** — `FACULTY_SOURCES = frozenset(_build_faculty_sources(SCHOOL_REGISTRY))` at import.
7. **`refresh_all.py`** — replace the hardcoded Berkeley loop (254-277) with `for src, fetch_fn, merge_fn in SCHOOL_REGISTRY.iter_faculty_collectors(order=['ucb_eecs_faculty','ucb_stat_faculty',...])` to preserve EECS-before-STAT merge order.
8. **`url_parser.py:514`** — domain→org map extended from `SCHOOL_REGISTRY.get_domain_org_map()`.

### 3.4 pipeline_touchpoints checklist (the canonical "add a school" list)
For each NEW school, in one or few PRs:
1. `school_config.py` — add `SchoolConfig` entry + `SCHOOL_REGISTRY.register(slug, cfg)`.
2. `faculty_base.py` — no change (generic router).
3. `ucb_common.py` — no change (already parameterized).
4. `src/collectors/<school>_<dept>_faculty.py` — thin wrapper: pull config from `SCHOOL_REGISTRY`, call `faculty_base.fetch_and_normalize`. (For multi-dept single-module schools, one module + dept loop, à la `uiuc_faculty`.)
5. `school_audience.py` — auto-built at import (verify the new source appears via `get_all_sources()`).
6. `deactivate_stale_faculty.py` — auto-built at import.
7. `refresh_all.py` — add the source to the `iter_faculty_collectors` order list (deep-only, like UCB).
8. `url_parser.py` — auto-extended via `get_domain_org_map()`.
9. `tests/test_opportunity_data_quality.py` — `_is_faculty()` auto-picks up new sources (no change); DQ gate auto-validates new records.
10. `frontend/src/lib/schools.ts` — add `SCHOOLS[]` entry (existing pattern, separate task; only needed for catalog-ready / switcher-facing schools).
11. `frontend/src/lib/catalogs/index.ts` — add loader for the school's `COLLEGE_MAJORS` (existing pattern; needed only for switcher schools without a catalog yet).
12. Run `pytest tests/test_opportunity_data_quality.py` (the `TestR70ADataQuality` gate — see §6).

### 3.5 Effort + payoff
- **One-time Wave 0 refactor: ~40–60h** (ucb_common ~12h · school_config ~8h · faculty_base ~6h · audience/deactivate ~8h · refresh_all ~4h · migrate 4 UCB collectors ~12h · tests ~6h).
- **Payoff:** each NEW school drops to **~2–4h**; per-department within a shape drops to negligible.
- **Acceptance for Wave 0:** all UCB ids byte-identical (id-stability tests green); `TestR70ADataQuality` green; `school_audience`/`deactivate_stale_faculty` produce the same sets as before from the registry; refresh dry-run shows EECS-before-STAT order preserved.

---

## 4. Target Schools — Tiered into Build Waves

> **Tiering rule (operator-mandated):** feasibility × effort × audience value ONLY. Include BOTH international-friendly and domestic/local sources. **F-1-friendliness is NOT a tier or defer reason** — the §2 filter handles the split per-user. `has_catalog=true` is a tie-breaker (no frontend catalog work needed).

### 4.1 Master table (all 48)

| School | Catalog | Feasibility | Structure | Effort | Priority depts (lead) | Wave |
|---|---|---|---|---|---|---|
| Georgia Tech | ✅ | high | card | S | CC/CS, ECE, ME, Chem, ChBE, Physics | **1** |
| Univ. of Washington | ✅ | high | card | S | Allen/CSE, ECE, ME, Physics, Chem, Stat | **1** |
| UT Austin | ✅ | high | per-dept | M (CS/ECE = S) | CS, ECE *(email on listing)*, ME, BME, Phys, Chem | **1** |
| Univ. of Michigan | ✅ | medium | table-list | M | CSE, ECE, ME, BME, Stat, Physics | **1** |
| Stanford | ✅ | high | per-dept (unified `profiles.stanford.edu`) | M | CS, EE, ME, BioE, Stat, Physics | **1** |
| Georgia Tech / UW / UTexas above are the catalog-ready easy wins | | | | | | |
| Caltech | ❌ | high | card | S | EE, CMS/CS, MCE, APhMS, Physics, Chem | **1** |
| Princeton | ❌ | high | card | S | CS, ECE, Physics, Chem, MolBio, MAE | **1** |
| Univ. of Chicago | ❌ | high | card | S | CS, PME, Stat, Physics, Chem, Data Sci | **1** |
| Univ. of Pennsylvania | ❌ | high | card (SEAS unified) | S | CIS, ESE, BE, MEAM, MSE, (Phys A&S = M) | **1** |
| Duke | ❌ | high | card | S | CS, ECE, BME, MEMS, Physics, Stat | **1** |
| Purdue | ❌ | high | card | S | CS, ECE, ME, BME, Chem, MatE | **1** |
| USC | ❌ | high | card (Viterbi unified) | S | CS, ECE, AME, BME, CEMS, (Phys Dornsife later) | **1** |
| UC Santa Barbara | ❌ | high | card | S | CS, ECE, ME, Mat, Physics, PSTAT | **1** |
| Univ. of Minnesota | ❌ | high | card | S | CSE, ECE, ME, BME, Stat, Chem | **1** |
| Ohio State | ❌ | high | card | S | CSE, ECE, MAE, BME, Physics, Chem | **1** |
| Notre Dame | ❌ | high | card | S | CSE, AME, Chem, Physics, ChBE, EE | **1** |
| Univ. of Rochester | ❌ | high | card *(email+interests inline)* | S | CS, ECE, ME, BME, Physics, Chem | **1** |
| Univ. of Florida | ❌ | high | card (Wertheim unified) | S | CISE, ECE, MAE, BME, MSE, Chem | **1** |
| UMass Amherst | ❌ | high | card (2 unified Drupal dirs) | S | CICS/CS, ECE, MIE, BME, Chem, Physics | **1** |
| Virginia Tech | ❌ | high | card (AEM unified) | M (first), S clones | CS, ECE, ME, BME&M, MSE, AOE | **2** |
| Cornell | ❌ | high | per-dept | M (CS = S) | CS *(tags+email inline)*, ECE, MAE, Stat, Phys, Chem | **2** |
| MIT | ❌ | high | per-dept | M (EECS = S) | EECS, ME, Physics, Chem, BioE, Math/IDSS | **2** |
| Univ. of Wisconsin | ✅ | high | per-dept (eng dir + WP) | M | ECE, CS, ME, Chem, Physics, Stat | **2** |
| Northwestern | ❌ | high | per-dept (McCormick XML feed!) | M | CS, ECE, ME, BioE, MatSci, Physics | **2** |
| Texas A&M | ❌ | high | json feed (per-college) | M | CSCE, ECE, ME, BME, Physics, Chem | **2** |
| Rice | ❌ | high | table-list (unified `profiles.rice.edu`) | M | CS, ECE, BioE, MSNE, ME, Phys/Chem | **2** |
| Univ. of Maryland | ❌ | high | per-dept | M (CS/Phys = S) | CS, ECE, ME, Physics, Chem, BioE | **2** |
| Northeastern | ❌ | high | table-list (COE unified) | M (Khoury = M-L) | CS, ECE, BioE, MIE, Physics, Chem | **2** |
| Stony Brook | ❌ | high | card (commcms) | M | CS, ECE, AMS, Physics, Chem, BME | **2** |
| Boston University | ❌ | high | per-dept (fragmented) | M (CS = S) | CS, ECE, BME, Physics, Chem, Math/Stat | **2** |
| WashU St. Louis | ❌ | high | per-dept (2 platforms) | M | CSE, BME, MEMS, ESE, Physics, Chem | **2** |
| Rutgers New Brunswick | ❌ | high | per-dept (3 platforms) | M | ECE, MAE, CS, Physics, Stat, Chem | **2** |
| NC State | ❌ | high | per-dept | M (CS = S) | CS, ECE, MAE, MSE, Stat, Chem | **2** |
| Penn State | ❌ | high | per-dept (aspx + Drupal) | M | EECS, ME, BME + Eberly Phys/Chem/Stat *(rich)* | **2** |
| Univ. of Notre Dame above (Wave 1) | | | | | | |
| Columbia | ❌ | medium | per-dept (mixed CMS) | M | CS *(all inline)*, EE, Physics, Chem, BME, APAM | **3** |
| UC Irvine | ❌ | high | per-dept (CS = S) | M | CS *(email inline)*, EECS, MAE, BME, Phys, Stat | **3** |
| Harvard | ❌ | medium | per-dept (SEAS FacetWP + FAS Drupal/WAF) | L | SEAS CS/EE/BioE/AppMath, Phys, Chem, Stat | **3** |
| Yale | ❌ | medium | per-dept (A&S static; Eng SPA) | L (A&S = S/M) | Phys/Chem/Stat first; CS/EE eng SPA later | **3** |
| Carnegie Mellon | ❌ | medium | per-dept (fragmented) | L (MCS sci = S/M) | Physics/Chem first; CSD/ECE/ME/ChemE bespoke | **3** |
| Univ. of Colorado Boulder | ❌ | medium | via `experts.colorado.edu` (static) | M | CS, ECEE, ME, Physics, Chem, ChBE | **3** |
| **— DEFERRED (need headless/Cloudflare path) —** | | | | | | |
| UCLA | ✅ | medium | js-spa (Samueli AJAX) | L | CS, ECE, MAE, BioE, Chem, Stat | **Deferred** |
| UC San Diego | ❌ | medium | per-dept + Physics SPA + legacy TLS | L | CSE, ECE, MAE, BioE, Chem, Physics | **Deferred** |
| Vanderbilt | ❌ | low | js-spa | L | CS, ECE, BME, ME, ChBE, Physics | **Deferred** |
| UC Davis | ❌ | low | Cloudflare 403 (whole campus) | L | CS, ECE, MAE, BME, Physics, Chem | **Deferred** |
| Arizona State | ❌ | low | js-spa (iSearch) | L | SCAI/CS, ECEE, SEMTE, SBHSE, Mat, Physics | **Deferred** |

*(NYU sits between 3 and deferred — three separate ecosystems; Courant CS is a trivial inline win, Tandon is a card clone, A&S is a third parser. Treat as **Wave 3**, ship Courant CS first.)*

### 4.2 Wave grouping, counts, rough effort

**Wave 1 — catalog-ready + easiest card-style (highest ROI).** 20 schools.
- The 5 catalog-ready easy/medium: **GT, UW, UTexas, Michigan, Stanford** (+ Wisc & UCLA are catalog-ready but Wisc=Wave 2, UCLA=deferred).
- The card-style S-tier no-catalog: **Caltech, Princeton, UChicago, Penn, Duke, Purdue, USC, UCSB, Minnesota, Ohio State, Notre Dame, Rochester, Florida, UMass.**
- **Effort:** GT/UW/Stanford as the proving trio post-Wave-0 (UW is the named first peer-school target). Then S-card clones at ~2–4h each after the first of each shape. Catalog-ready schools skip frontend catalog work; no-catalog schools add a `schools.ts` + catalog entry (existing pattern). **Rough: 1 proving school (~1 day incl. shakeout) + ~18 × ~3h ≈ 8–10 focused days spread over the parallel track.**

**Wave 2 — unified-feed / single-bespoke-parser wins + per-dept M schools.** ~15 schools.
- Best-leverage single sources: **Northwestern** (one McCormick XML feed → ~150 eng PIs, email+research inline), **Texas A&M** (per-college JSON feed, 95% have email), **Rice** (`profiles.rice.edu` unified), **Northeastern COE**, **Wisconsin eng directory** (inline email+research), **MIT EECS** (`/role/faculty/`), **Cornell CS**.
- Plus per-dept M: **VT, Maryland, Stony Brook, BU, WashU, Rutgers, NC State, Penn State.**
- **Effort:** each unified-feed school ≈ M (one parser, no per-dept clones). **Rough: ~10–14 days over the parallel track.**

**Wave 3 — harder per-dept / partial-SPA, ship the easy half first.** ~5 schools.
- **Columbia, UC Irvine, NYU** (ship the clean inline-CS half, defer the SPA/odd half), **Harvard** (ship FAS A&S Drupal depts, reverse-engineer SEAS FacetWP later), **Yale** (ship A&S Physics/Chem/Stat card clones, defer Eng SPA), **CMU** (ship MCS sciences, bespoke the eng side), **CU Boulder** (one `experts.colorado.edu` collector unlocks all CU STEM).
- **Effort:** mixed M–L; partial coverage is acceptable (ship the cheap inline depts, defer the JS depts to the deferred-tooling bucket).

### 4.3 Within-school first-target picks (build the cheapest high-value dept first)
- **CS-with-everything-inline (zero/near-zero hop):** Cornell CS, Columbia CS, UCI CS (`cs.ics.uci.edu`), NYU Courant CS, Rochester eng, Northeastern COE, Wisc eng dir, Maryland Physics, Penn State Eberly sciences, GT College of Computing (research tags on listing), UTexas ECE (email on listing).
- **Single source covers a whole college:** Penn SEAS (`directory.seas.upenn.edu/<slug>`), USC Viterbi (`<dept>.usc.edu/directory/faculty`), Florida Wertheim (Connections plugin), Northwestern McCormick (XML), Texas A&M (per-college JSON), Stanford (`profiles.stanford.edu/browse/<school>/<dept>`), Rice (`profiles.rice.edu`), UMass (two unified Drupal dirs), Duke (one university-wide Drupal template).

### 4.4 Deferred — and WHY (no silent drops; NOT F-1 reasons)
All five are deferred purely on **build-cost / anti-bot grounds** because the existing static-HTTP collectors return empty shells or 403:
- **UCLA** — engineering is one Samueli AJAX SPA (no WP REST people endpoint; admin-ajax returns bare `0`); needs DevTools-captured action+params or headless render. *Catalog-ready, so it jumps to easy once a fetcher exists.*
- **UC San Diego** — Physics is a client-side SPA; legacy Chemistry/`previous.physics` fail TLS. (Jacobs eng depts alone would be S/M — could ship those without the SPA.)
- **Vanderbilt** — all eng depts are a JS SPA with zero faculty in static HTML; do a 30-min API-discovery spike before committing (a clean endpoint downgrades it to M).
- **UC Davis** — **campus-wide Cloudflare bot-management 403** on every dept; needs a JS-challenge-solving headless browser or residential proxy.
- **Arizona State** — Fulton directory is an iSearch-backed SPA; verify the `search.asu.edu webdir-profiles` API contract before building.

**Unblock condition for the whole deferred bucket:** stand up a headless-fetch path (the repo already has Playwright for E2E; gstack `/browse` daemon is available). Once that exists, UCLA (catalog-ready) + UCSD-Physics + Vanderbilt + UC Davis + ASU become M-effort. Pair them in one "browser-required sources" mini-wave.

---

## 5. Per-Collector-Shape Playbook

> Every shape reuses the same enrich + normalize pipeline (now school-agnostic after Wave 0). Pick the shape, write the thin config/parser, run the DQ gate.

### 5.1 `open_berkeley_card` — clone `ucb_chem_faculty` / `ucb_stat_faculty`
**Pattern:** card listing (name/title/profile-link) + per-profile enrich hop for email + research interests. Config = selectors dict + URL + majors + keywords.
**Maps to:** Caltech, Princeton, UChicago, Penn (SEAS), Duke, Purdue (eng), USC (Viterbi), UCSB, Minnesota, Ohio State, Notre Dame, Rochester, Florida (Wertheim), UMass (Drupal dirs), GT, UW, Stony Brook (commcms), Virginia Tech (AEM), Columbia CS, UC Irvine CS, NYU Tandon, Harvard FAS A&S, Yale A&S, CMU MCS sciences, BU CS.
**Effort:** S (first of a shape ~half a day; clones ~2–4h).

### 5.2 `bespoke_html` — clone `ucb_cee_faculty`
**Pattern:** custom `_scrape_<school>_<dept>_faculty_list(soup, base)` (~100–150 lines) for non-Drupal/grid markup with inline-ish research, then reuse dedup + enrich + normalize. Register as `parser_class`.
**Maps to:** Wisconsin eng directory (inline email+research), Rutgers science Joomla (paginated `?start=N` + profile hop), Penn State eng aspx (`?q=<psuid>`), WashU McKelvey `.html`, NC State CS, BU Physics grid, Brown CS list, Maryland Physics current.html.
**Effort:** M per new markup family; S clones within the same family.

### 5.3 `inline_parser` — clone `ucb_eecs_faculty`
**Pattern:** listing exposes email + research areas inline, no profile hop; optional `area_keywords` tag→keywords mapping when substring matching <70%.
**Maps to:** Cornell CS (tags+email inline), UTexas ECE (email inline), Rochester eng, Northeastern COE (`?alpha=` + inline research), UCI CS (`person__*` cards, 72/72 emails inline), Columbia CS (interests+email inline), NYU Courant CS, Stony Brook Physics list, Maryland CS (research tags inline; email on profile = light hop).
**Effort:** M first, then config-level.

### 5.4 `table_list` — clone `uiuc_faculty` multi-dept mega-module
**Pattern:** one module, many dept configs in a dict, shared table/list scraping, single pass.
**Maps to:** Michigan (AEM fragment endpoints, two URL families), Rice (`profiles.rice.edu`, dept-string filter), MIT Physics (server-rendered sortable table), Northeastern Khoury (paginated filter).
**Effort:** M-L for the module; ~0.5h per added dept.

### 5.5 `structured_feed` (NEW micro-shape — cheapest of all)
**Pattern:** a single JSON/XML feed powers a whole college; parse + filter by dept/role tag; optional per-profile hop only if `research_interests_text` is missing from the feed. (Not in the original 4 shapes but warranted — these are the highest-leverage sources in the cohort.)
**Maps to:** Northwestern McCormick (`faculty-search-list.xml`, research inline; de-obfuscate `name( at )domain`), Texas A&M (`engineering.tamu.edu/profile-data.json` 1591 recs / `artsci.tamu.edu/profile-data.json` 3007 recs — research not in feed → profile hop), Stanford `profiles.stanford.edu` (server-rendered card list, filter `affiliation=Faculty`, `?p=N`), CU Boulder `experts.colorado.edu/display/deptid_<id>` (deptid→major map).
**Effort:** M (one parser, no per-dept clones). Implement as a `parser_class` under `faculty_base` routing.

> **Anti-scraping carry-forwards baked into every shape:** send a real browser UA (umich/Stanford-dept/Penn-sciences/JHU-aggregator/Minnesota-Pure all 403 a default UA but pass a normal one); avoid FacetWP/admin-ajax filtered URLs — hit the static `/role/faculty/`-style route and filter client-side; decode Cloudflare `data-cfemail` hex (Minnesota); de-obfuscate `( at )` (Northwestern); don't follow malformed redirects (Princeton, Yale `cpsc`, Columbia legacy); target dept-owned hosts over WAF'd aggregators (JHU `cs.jhu.edu` not `engineering.jhu.edu`).

---

## 6. Data-Quality Carry-Forward (every new school must pass)

> **Gate:** `tests/test_opportunity_data_quality.py::TestR70ADataQuality`. It caught the faculty-DQ regression. **Do NOT loosen it.** Auto-refresh MUST run the full `--reenrich` cleaning path: drop-nonperson → null-emails → DQ-1 demote → DQ-2 derive → strip-junk/fragment/credentials → rebuild-titles. (The regression root cause was that `--reenrich` cleaning was never wired into `merge_into_processed` — keep it wired after Wave 0.)

For each new school, verify these six guards (and set the matching `DepartmentConfig` fields):

1. **Shared-admin / shared-inbox email nulling.** Directories mix `inquiries@`, `webmaster@`, `info@` into faculty listings. Set `DepartmentConfig.noise_emails` per dept. Email extraction order: mailto link → Drupal/field → page-wide regex, with `primary_domain` preference AFTER the noise filter (so no admin mailbox slips through). UIUC precedent: nulls `amwhit/nslack/aandreae`.
2. **Navigation-menu keyword pollution.** Sidebar/course-catalog links leak generic dept keywords into a PI's research signal. Point `research_interests` selectors at specific Drupal `field__item` divs (avoid menus); inline parsers read only the `<p>`/research block. New schools with nav-heavy templates need tight selectors, not page-wide text scans.
3. **Emeritus / retired filter.** `_RETIRED_TITLE_RE` (ucb_common.py:84, case-insensitive) filters at `normalize_faculty`. Schools vary ("Professor Emeritus" vs "Emeritus Professor" vs "Retired Faculty"). Set `DepartmentConfig.title_filter_regexes` per school. Many directories mix faculty/staff/postdoc/grad — filter to PI titles (OSU dirs list ~200 grad students; Stanford CS returns 2,242 before role filter; Physics tables include staff).
4. **Broad-only faculty (no research signal).** ~30% of records have no research section → fall back to `keywords[:1]`. Set school-level `keyword_bank` + dept-level `keywords` so the broad field uses the school's terminology (e.g. "Electrical Engineering" vs "EE"). Use `area_keywords` (EECS-style) where tags substring-match poorly.
5. **Joint-appointment dedup.** PIs in multiple dept listings. `refresh_all` controls merge order (EECS-before-STAT precedent) to keep "first in merge order." For 3-dept chains (A→B→C) the order is arbitrary-but-stable; document the order per school. Same-source same-refresh dedup via profile URL + normalized email/name.
6. **Partial-scrape staleness protection.** `deactivate_stale_faculty` skips deactivation when `fetched_counts[source] < MIN_SCRAPE_RATIO` (70%) of active records, and only after `GRACE_DAYS=14` (2 missed weekly runs). Watch high-churn directories (postdoc turnover) — a 50% semester churn school could perma-trip the 70% gate. Only sources reporting `status='ok'` in the current run are eligible.

**Plus the §2 filter invariants** are DQ-enforced: non-null `audience ∈ VALID_AUDIENCES`, registered campus sources, `on_campus` relative to host school.

---

## 7. Final Go-Live / Landing Plan (the backbone — never forget this)

> This is the spine the whole product hangs on. The expansion (§4) is a *rib*, not the spine. Sequencing: **(a) validate → (b) monetize → (c) scale data [parallel] → (d) agent autonomy ladder.**

### 7a. Concierge validation — DO THIS FIRST (gates everything)
**Goal:** first non-friend paying/retained user within 30 days.
- **Offer:** free **2 generations** (match + explanation + draft) → then a **$9.9 "do my outreach"** button ("帮我投").
- **Mechanism:** the button presents as the agent; **Eric MANUALLY confirms and hand-sends every email** (Wizard-of-Oz). Zero reputation risk (Eric reviews each), zero infra cost (replace the manual step with engineering only AFTER validation).
- **What ships:** legal pages (done) · **Stripe Payment Link (Eric — external/manual, needs Eric's account)** · the "帮我投 + 付费/意向" button on the results UI · a back-office view for Eric to see requests and hand-send.
- **Target payer:** anxious parent (study-abroad/research-agency market has proven WTP; OFE is 10×+ cheaper + honest about reachability).
- **Gate:** 30-day clock. Hit it → proceed to 7b. Miss it → OFE downgrades in the portfolio.
- **Approval/safety:** every email leaves the machine carrying Eric's real name → **external communication = Eric's explicit approval each send** (per CLAUDE.md). No automated sends in this phase, period.

### 7b. Freemium monetization layer — AFTER validation
Only build this once 7a proves someone pays.
- **`usage_counters` table** (free-tier quota: 2 generations) + **backend Supabase-JWT gate** enforcing the free/paid boundary server-side (not client-trusted).
- Wire the Stripe Payment Link → entitlement (manual reconciliation acceptable at first; webhook later).
- Free tier = match + explanation (top-of-funnel, retention). Paid = the outreach outcome.
- **Do NOT** build this before 7a — it's premature monetization infra without a demand signal.

### 7c. Data expansion waves — THE PARALLEL SCALE TRACK (this plan)
- Runs alongside 7a/7b as a **low-cost background bet.** Ship Wave 0 (§3) → Wave 1 (§4.2) as cheap config clones.
- **Each new school lights up a switcher surface** + grows the durable corpus. Faculty directories = durable → front-load now; program/REU portals = time-boxed → land just before fall/winter app season.
- **Hard rule:** this track must never consume the attention owed to 7a. If the 30-day clock is live and validation work is stalled, **pause expansion.**
- **Per-school checklist = §3.4. Per-school DQ = §6. Filter invariants = §2.4 (non-negotiable).**

### 7d. Agent autonomy ladder — toward the north star (last)
- **L0:** match + explanation (live).
- **L1:** agent drafts resume tailoring + cold email; human reviews + sends (concierge today is the manual version of this).
- **L2-confirm:** agent prepares the full send (recipient, draft, follow-up schedule); **a human presses send.** *Permanently pinned here* — emails carry Eric's real name; 声誉 > 速度.
- **L3+ (auto-send) is NOT pursued** until/unless reputation risk is structurally removed (e.g. sends from the *user's own* identity, not Eric's). Even then, 2026 auto-delivery is commoditized — it's not the moat.
- Reply-parsing + deadline-follow-up are the genuinely valuable L2 features to build after monetization proves out.

### 7e. Deferred on non-F-1 grounds (still valid, don't re-raise as new)
pgvector/Postgres (JSON+TF-IDF fine at ~5k records); E2E-as-required-check (wait for several consecutive green main runs after the deep refresh); the deferred SPA/Cloudflare schools (§4.4) pending a headless fetcher. **USAJobs/SerpApi and other F-1-gated sources (DOE SULI, NIH SIP, NASA OSTEM) are back IN scope as DATA** — the filter excludes them per-user at match time, not the collector at ingest time.

---

## 8. How to Resume (a future session reads this first)

1. **Check the validation clock before anything.** Is the concierge "帮我投" button live? Is the 30-day window running? Is there validation activity? If the clock is live and stalled → **do §7a, not expansion.** If no paying/retained stranger yet → expansion stays a background bet, never the headline.
2. **Wave 0 status: ✅ SHIPPED, under different names (2026-07 update).** The add-a-school architecture landed as the `faculty_graph` engine + per-school config modules in `src/collectors/schools/` (`<slug>.py` campus-graph config + `<slug>_faculty.py` faculty config; 19 schools as of 2026-07-10) — the planned `school_config.py`/`faculty_base.py` were never created because these subsume them. Adding a school = a config pair + registry entry, exactly the Wave-0 goal. Do NOT re-open Wave 0.
3. **Filter-correctness fixes (§2.5): ✅ FIXED in #208** (`fix(matcher): honor citizenship_required + gate F-1 on-campus bonus to home school`) — BUG A and BUG B both, with regression tests. Domestic-heavy waves are no longer gated on this.
4. **Pick the next school from §4.2 by wave + §4.3 first-target.** Catalog-ready (GT/UW/UTexas/Michigan/Stanford) skip frontend catalog work. Use the §5 shape playbook and the §3.4 touchpoint checklist. Land the `SOURCE_DEFAULTS`/registry entry in the SAME PR (§2.4 invariant 1).
5. **Run the §6 DQ guards** for the new school; `pytest tests/test_opportunity_data_quality.py` must stay green. Register the source deep-only in `refresh_all` (preserve merge order).
6. **Ship rules (from memory):** PR + CI gate (Backend + Frontend), commit identity, ruff 0.7.4 (`Optional[X]` OK), auto data-refresh ships via PR + auto-merge (needs `REFRESH_PAT`). **Merges to `main` need Eric's explicit consent (no `--admin`).** Don't make E2E a required check until de-flaked. **External sends require Eric's approval, every time.**
7. **Key files:** `src/collectors/ucb_common.py` · `src/collectors/refresh_all.py` · `src/normalizers/school_audience.py` · `src/normalizers/deactivate_stale_faculty.py` · `src/matcher/ranker.py` (filter) · `backend/routes/matches.py` (preferences default) · `tests/test_opportunity_data_quality.py` (DQ gate) · `frontend/src/lib/schools.ts` + `frontend/src/lib/catalogs/index.ts` (switcher). New: `src/collectors/school_config.py` · `src/collectors/faculty_base.py`.
8. **Don't re-derive / don't re-raise:** the 38 refuted findings, OAuth items (Google done; Microsoft deferred until Eric owns a domain/entity), pgvector. Don't drop or down-weight any source for F-1-unfriendliness — that's a filter concern, not an ingest concern.

---

**Plan paths verified present:** `src/collectors/ucb_common.py`, `src/collectors/refresh_all.py`, `src/normalizers/school_audience.py`, `src/normalizers/deactivate_stale_faculty.py`, `src/matcher/ranker.py`, `backend/routes/matches.py`, `tests/test_opportunity_data_quality.py`, `frontend/src/lib/schools.ts` (all confirmed). The planned `src/collectors/school_config.py` / `faculty_base.py` were superseded before creation by the shipped `src/collectors/schools/` per-school config pattern (see §8.2) — do not create them.

---

## 9. Disposal notes — 2026-07-05 (deferred WITH reasons; don't leave these hanging or re-raise as new)

- **Google Scholar integration → substituted, not deferred.** OpenAlex enrichment (topics + institution IDs, 14 schools in `openalex_enrich.py`) already delivers what Scholar would (scholarly topics, recent works for cold-email personalization). Scraping Scholar violates its ToS and gets IP-banned fast; there is no official API. Decision: never scrape Scholar; extend OpenAlex instead.
- **UCSD REAL portal (anti-bot) → defer.** UCSD already carries ~1,372 faculty from dept directories; REAL is an incremental listings source, not a coverage gap. Revisit only if a headless-fetch path ships for other blockers anyway.
- **LinkedIn/Handshake browser extension → design doc (`docs/BROWSER_EXTENSION.md`), fall track.** Separate product line (store review, permissions, support). Handshake as a *data source* is live and parameterized (`HANDSHAKE_SCHOOLS`) — the 2026-07 audit confirmed it is not hardcoded.
- **Org/institutional accounts → design doc (`docs/ORG_ACCOUNTS.md`).** Only `account_type: 'personal'` reserve ships now; build triggers defined in the doc.
- **Grad/PhD support → design + UIUC pilot plan (`docs/GRAD_SUPPORT.md`).** Faculty corpus already serves prospective-PhD outreach; pilot = profile options + eligibility caveats + grad email template.
