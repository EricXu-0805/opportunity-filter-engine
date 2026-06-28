# Adding a School — Standard Operating Procedure

How to add a new university to the opportunity engine end-to-end, which collector
engine to reach for, every place you must register a source, how to verify it,
and how the data actually reaches production.

This exists because we now have **four overlapping faculty approaches** and two
people building schools in parallel. Follow this so collectors stay consistent
and nothing silently ships broken data.

---

## 0. Mental model

A school contributes two things:

1. A **frontend registry entry** (`frontend/src/lib/schools.ts`) so users can
   select it, with a **catalog** (colleges → majors) behind `loadCatalog()`.
2. One or more **collector sources** that emit normalized opportunity records.

Every record carries two discovery fields set at the normalize boundary
(`src/normalizers/school_audience.py`):

- `school` — host-school slug (e.g. `"ucb"`), or `None` for national/open.
- `audience` — `"campus"` (host students only), `"open"` (any school), or
  `"unknown"` (per-professor; the default for faculty cold-email targets).

`(school, audience)` is assigned **per source** in `SOURCE_DEFAULTS`. The ranker's
multi-school scope filter and the data-quality (DQ) gate both depend on it.

---

## 1. Decision tree — which engine per source type

Pick per **source type**, not per school. A school usually needs a couple.

### Research programs / hubs / institutes / career centers → `campus_graph`
- **Engine:** `src/collectors/campus_graph.py`, config under
  `src/collectors/schools/<slug>.py` (see `princeton.py`, `umich.py`).
- **What it is:** curated seed records (hand-verified program pages) that are
  **offline-safe and stdlib-only**, plus an optional best-effort deep crawl.
- **Use when:** the school's value is a finite set of named programs/offices.
- **Emit buckets:** `campus` / `open` / `lab` → `(source, school, audience)`.

### Faculty → use the most robust source available, in this order:

| Approach | Engine | Use when |
|---|---|---|
| **JSON directory API** | `uiuc_json_faculty.py` pattern | The campus exposes a faculty JSON/REST endpoint (most robust — no HTML drift). UIUC AHS/Social Work/Gies/Education. **Always prefer this if it exists.** |
| **HTML directory** | `uiuc_html_faculty.py` pattern | A listable HTML faculty directory with stable markup. UIUC Carle/Law/LER/FAA/Media/VetMed. |
| **Open-Berkeley person grid** | `ucb_common.py` + a thin config | Site uses the standard `div.node-openberkeley-person` theme. Reuse `ucb_common.OPENBERKELEY_PERSON_SELECTORS`; the collector is just a config dict (see `ucb_music_faculty.py`). |
| **Bespoke parser** | `ucb_common.py` + custom `_scrape_*` | A one-off DOM (newer Bootstrap themes). See `ucb_classics_faculty.py` (`div.views-row`, name from URL slug) and `ucb_publicpolicy_faculty.py` (`div.directory__list-person`). |
| **Curated `faculty_graph`** | `faculty_graph.py`, `schools/<slug>_faculty.py` | **Scraping is blocked** (Cloudflare 403, login wall). Hand-curated, verified faculty (name + research + public email *only if confirmed — never guess*). See `umich_faculty.py`. |

**Rule of thumb:** scrape if you can verify a real yield; curate only when the
directory is unreachable. Always confirm reachability first (see §3).

---

## 2. Step-by-step

1. **Frontend registry** (`frontend/src/lib/schools.ts`): add a `School` entry —
   `slug`, `domain`, `name`, `shortName`, `nameZh`, brand `color`, `location`,
   `coverage`, `catalog`.
   - `catalog` must be **non-null** (`schools.test.ts` requires it) and its
     `{colleges, majors}` counts must **exactly match** the data behind
     `loadCatalog(slug)` (`catalogs/catalogs.test.ts` iterates every school).
   - So also add `catalogs/<slug>.ts` (a `COLLEGE_MAJORS` map) + a loader entry
     in `catalogs/index.ts`. (UIUC/UCB/the 8 in `NEW_CATALOG_SLUGS` already have
     these.)
   - `coverage.campusOpportunities` is a **hand-maintained estimate** (the
     frontend bundle does not load the corpus). Set it to a conservative
     round-down of the real active count; bump it when data lands.

2. **Build the collector(s)** per the §1 decision tree.

3. **Register the source(s)** — see §4 checklist.

4. **Verify** — see §3 and §5.

5. **Land the data** — see §6.

---

## 3. Verify reachability & markup BEFORE writing a parser

The expensive mistake is shipping a scraper with wrong selectors that yields 0.

- `curl -A "<browser UA>" <faculty-url>` — confirm `200` (not 403/404/redirect).
  Berkeley dept sites are reachable; **Michigan + many `lsa`/`ischool`/`gspp`
  pages are Cloudflare-walled (403)** — those must be curated, not scraped.
- Identify the card pattern (`node-openberkeley-person`? `views-row`?
  `directory__list-person`? a JSON endpoint?). Run the actual selectors and
  count clean person names before committing — don't trust a class-name grep.

---

## 4. Registration checklist (kept in lockstep by tests)

For **every** new source name:

- [ ] `src/normalizers/school_audience.py` → `SOURCE_DEFAULTS[source] = (school, audience)`.
- [ ] `src/collectors/refresh_all.py` → import its `fetch_and_normalize` and add a
      `(source_name, fetch_fn, merge_fn)` tuple. Faculty go in the **deep-only**
      loop; `campus_graph` schools are iterated from `schools.SCHOOL_CONFIGS`.
- [ ] **Faculty only:** `src/normalizers/deactivate_stale_faculty.py` →
      `FACULTY_SOURCES`. `tests/test_deactivate_stale_faculty.py` asserts this set
      **exactly equals** the faculty sources wired in `refresh_all` (regex over
      any `"<...>_faculty"` literal) — wired-but-unregistered or vice-versa fails.
- [ ] Frontend labels: `frontend/src/app/results/types.ts` `SOURCE_LABEL_KEY` +
      **both** `en` and `zh` blocks in `frontend/src/i18n/dictionaries.ts`
      (`translate.test.ts` enforces en/zh key parity).
- [ ] `campus_graph` schools: add `SCHOOL` to `schools/__init__.py` `SCHOOL_CONFIGS`.

---

## 5. Verification gates (the DQ contract)

Run `pytest tests/test_opportunity_data_quality.py` against the corpus with the
new records. Faculty records (`source_type="faculty_research"`) must satisfy:

- **No shared contact_email or pi_name** across same-institution faculty
  (joint-appointment gate). Two causes to watch:
  - A **department mailbox** scraped as a personal email (e.g. `tdps@berkeley.edu`
    on profiles with no personal address). Fix: add it to
    `ucb_common.NOISE_EMAILS`.
  - A genuinely cross-listed professor in two departments → the merge's
    `drop_joint_appointment_duplicates` keeps the existing record and drops the
    incoming one. Merge sources **sequentially** so later sources dedup against
    earlier ones.
  - Two *different* people with the same name (e.g. Michigan's two "Wei Lu") —
    dedup on **email/URL, not bare name**.
- **pi_name must be a person** (`_is_person_name`) — never an institution/place
  label scraped from a nav element.
- **No nav-furniture** in `description_clean`; **no junk/fragment keywords**
  (`uiuc_faculty._is_junk_keyword`); a **title parenthetical** must be a subset
  of the record's keywords; `description_clean ≤ 1500` chars.
- **Keyword pollution:** a department-wide "research areas" nav block scraped
  into every profile makes many same-dept peers share an identical keyword set
  (`test_no_shared_department_keyword_pollution`). Demote shared sets (see
  `uiuc_faculty._demote_shared_keyword_pollution`).

`campus_graph` seed records must keep `pi_name=None`, `contact_email=None`,
`is_rolling=True`, `deadline=None`, and `(school,audience)` matching
`SOURCE_DEFAULTS`.

---

## 6. Landing the data (read this — it's the part that bites)

Collectors merged to `main` **do not put data in the corpus by themselves.**
`data/processed/opportunities.json` only changes when the **deep refresh** runs.

- **Workflow:** `.github/workflows/refresh-data.yml` (Mon deep / Thu quick, or
  manual `workflow_dispatch` with `deep=true`). It scrapes **everything**, runs
  the DQ gate, then opens + squash-merges a data PR to `main`.
- ⚠️ **`REFRESH_PAT` is currently set but empty**, so the auto-publish step fails
  (`"REFRESH_PAT secret is not set"`). Until someone **Updates** that secret with
  a real PAT (repo `Contents`+`Pull requests` write), the data must be
  **hand-harvested**:
  1. The scrape still runs; on a *publish-only* failure it leaves the data on
     `auto/refresh-data-<run-id>`.
  2. Harvest surgically — take only the new/changed source records and swap them
     into current `main`, preserving everyone else's work (see PR #329). Do **not**
     wholesale-merge the auto-branch: a 2.5h scrape goes stale against `main`.
- ⚠️ **The DQ gate is all-or-nothing across the whole corpus.** A re-scrape can
  surface a *pre-existing* issue in an unrelated school and block the entire run.
  If you only need to land one school's new sources, prefer **generating just
  those collectors locally** and merging that delta (avoids the 2.5h cycle and
  unrelated blockers) — same pattern as the curated `campus_graph`/`faculty_graph`
  records.

---

## 7. Per-task workflow conventions

- Branch off the **latest `main`** for each task; open the PR yourself.
- Keep PRs scoped to one school/concern; stacked PRs **merge into their base, not
  `main`** — retarget to `main` (or re-open against `main`) before merging, or the
  commits never reach `main`.
- Verify live yields and run the DQ gate locally before opening the PR.

---

## Quick reference — engines & examples

| Need | File(s) |
|---|---|
| Programs/hubs/labs | `campus_graph.py` + `schools/princeton.py`, `schools/umich.py` |
| Curated faculty (scraping blocked) | `faculty_graph.py` + `schools/umich_faculty.py` |
| Faculty via JSON API | `uiuc_json_faculty.py` |
| Faculty via HTML directory | `uiuc_html_faculty.py` |
| Faculty, Open-Berkeley theme | `ucb_common.py` + `ucb_music_faculty.py` (config-only) |
| Faculty, bespoke DOM | `ucb_classics_faculty.py`, `ucb_publicpolicy_faculty.py` |
| Scope/audience tagging | `normalizers/school_audience.py` |
| Stale-faculty retirement | `normalizers/deactivate_stale_faculty.py` |
| Refresh orchestration | `collectors/refresh_all.py` |
| Frontend registry + catalog | `frontend/src/lib/schools.ts`, `frontend/src/lib/catalogs/` |
