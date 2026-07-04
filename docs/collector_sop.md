# Collector SOP — the standard path for every new source

Status: canonical as of Jul 2026. This documents the path that **exists and is
test-guarded today** (the `campus_graph` / `faculty_graph` engines + manual
registry entries). MASTER_PLAN §3.4's `school_config.py`/`faculty_base.py`
auto-registry is a *future* design — do not follow that checklist until those
modules exist. Where this SOP and older docs disagree, this SOP wins.

The engine lineage, for orientation (do not build new collectors on the first two):

| generation | example | style | status |
|---|---|---|---|
| 1st — UIUC | `uiuc_faculty.py` + variants | hardcoded scraper functions | frozen; maintain only |
| 2nd — UCB | `ucb_common.py` + ~50 `ucb_*_faculty.py` | shared engine + config module per department | frozen; new UCB depts still follow it |
| 3rd — schools/ | `campus_graph.py` / `faculty_graph.py` + `schools/*.py` | fully declarative config | **canonical for every new school** |

---

## A. New-school file structure

A new school = **2 config modules + 4 registry entries + 2 test suites**. No new engine code.

```
src/collectors/schools/<slug>.py            # campus SCHOOL dict (programs, seeds, crawl)
src/collectors/schools/<slug>_faculty.py    # faculty SCHOOL dict + 2 thin wrappers
```

- Campus module: exposes one module-level `SCHOOL: dict`. **No functions.**
  Reference shape: `schools/princeton.py`; engine contract documented in the
  `campus_graph.py` docstring.
- Faculty module: exposes `SCHOOL: dict` plus exactly these wrappers
  (`deep: bool = True` — refresh_all only calls it inside the deep block):

  ```python
  def fetch_and_normalize(deep: bool = True) -> list[dict]:
      """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
      return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)

  def merge_into_processed(opps: list[dict]):
      return faculty_graph.merge_into_processed(opps)
  ```

- Naming: source strings are `"<slug>_faculty"` and the campus emit triple
  `"<slug>_research_programs"` / `"<slug>_external_research"` / `"<slug>_labs"`.
  Campus per-source names use the templated set
  `<slug>_announcement/_program/_program_open/_department/_career/_lab`
  (the princeton/umich/uw/ucsd hand-written names are legacy — don't copy them).
- New UCB department (not a new school): copy a Tier-A config module
  (`ucb_math_faculty.py` is the reference), keep the file/source name
  `ucb_<dept>_faculty`, and follow the same registry entries below.

## B. Fetch rules

- **Never call `requests` directly in a config module.** Configs declare
  *what* to fetch; engines own *how*.
- Engine fetch paths (already built — pick by declaring the block in config):
  `scrape` (CSS cards, optional `render: True` for JS/Cloudflare pages),
  `api` (WordPress REST), `ajax`, `algolia`, `cola` (Drupal JSON:API),
  `faculty180`, `json_dir` (generic JSON roster; field names accept dotted
  paths). Curated `faculty(...)` lists are the offline fallback for
  bot-walled sites.
- Every engine fetch: explicit timeout (20–30s), browser-like `HEADERS`,
  degrade-to-empty on failure (never raise out of a fetch helper),
  politeness delay on per-profile loops (0.75–1.5s).
- TLS: verification stays ON. If a host's chain is broken, do what
  `uiuc_our_rss._fetch_feed_bytes` and `uiuc_faculty._scrape_individual_page_keywords`
  do — verified attempt first, unverified retry **with a logged warning**.
  Never a bare `verify=False`.
- Pagination is declarative: `paginate: {param, start, max}` (query or path
  mode). Loops must stop on "no new records", not only on the max cap.
- Profile-page second fetch goes in `profile_enrich` and is gated by
  `OFE_ENRICH_PROFILES=1` (off in weekly CI; on for one-shot enrichment runs).

## C. Parse rules

- Prefer structured feeds over HTML whenever the site offers one
  (`json_dir`/`api`/`algolia`/`cola`), HTML cards over regex, regex last.
- All person parsing must survive: missing email, missing profile link,
  "Last, First" names (`name_flip`), pronouns/credentials in names, emeritus
  titles (`ladder_filter` with `require`/`drop`), section headings mixing
  staff into faculty (`section_filter`).
- Text cleaning goes through the engine/shared helpers
  (`_strip_nav_furniture`, keyword junk gates) — never re-implement.

## D. Normalize rules

- Collectors emit the **full normalized schema directly** (see
  `docs/opportunity_schema.md`); there is no post-hoc normalizer for
  engine-based collectors. The engines' `_normalize*` functions are the only
  place records are built.
- Required on every record: `id`, `source`, `source_type`, `title`, `url`,
  `source_url`, `organization`, `description_clean` (≤1500 chars),
  `eligibility{}`, `application{}`, `metadata{confidence_score, first_seen_at,
  last_seen_at, is_active}`.
- Faculty records: `source_type="faculty_research"`, `pi_name`,
  `contact_email` (None if unknown — never a shared dept inbox),
  `department`, keywords capped at 8. Confidence: 0.7 with email, 0.5 without.
- Campus records: emit-bucket decides `source`/`school`/`audience` inline;
  curated seeds 0.7, crawl-discovered 0.4 + `metadata.discovered=True`.
- `school`/`audience` are re-stamped every run from
  `school_audience.SOURCE_DEFAULTS` — a collector-set value on a mapped
  source is overwritten, so get the mapping right rather than the record.

## E. Stable IDs & dedupe

There is **no `external_id` field** — the stable identity is `id`:

| family | scheme |
|---|---|
| faculty (all schools) | `faculty-<id_prefix>-<dept_short>-<md5(short + name)[:8]>` |
| campus curated | `<slug>-<md5(source :: program_key)[:12]>` |
| campus discovered | same, key = `disc-<md5(url)[:10]>` |
| feeds (nsf/simplify/handshake) | `<source>-<stable upstream id>` |

- IDs must be **deterministic** (same person/program ⇒ same id every run) and
  **namespaced by school** (`id_prefix`). Never `uuid4()` in a batch collector
  — random ids duplicate the corpus on every refresh.
- Renaming a curated `key`, a dept `short`, or cleaning a name differently
  **mints new ids** — the DQ byte-stability tests exist to make you notice.
- Dedupe layers (all already built): per-fetch URL/email dedup in the engines;
  UCB joint-appointment drop (`drop_joint_appointment_duplicates`, email/name
  keyed, existing-corpus-wins — merge order in refresh_all is semantic);
  campus URL/title near-dup via `ucb_dedup.dedupe_against_existing`.
- Merge (`merge_into_processed`) is an upsert by `id` that preserves
  `metadata.first_seen_at` and carries committed enrichment forward. Reuse the
  engine's merge; never write a new one.

## F. Error handling

- Config modules contain **zero** try/except — isolation lives in
  refresh_all (one try/except per source; a failing school records
  `{"status": "error"}` and never sinks the run).
- Engines degrade to `[]`/`None` per fetch, log a warning, keep going.
- Empty-scrape protection is layered — keep all three intact:
  1. merge refuses/no-ops an empty batch where emptiness is seasonal
     (`ucb_urap_projects`) or CLI-driven (`run_cli --save`);
  2. `deactivate_stale_faculty` gates on `status=="ok"` **and** a
     ≥70%-of-active fetched count (`MIN_SCRAPE_RATIO`) so a partial scrape
     can't mass-retire a department;
  3. zero-record sub-scrapes are ERROR-logged in refresh_all so the run
     summary flags URL rot (`missing_departments` pattern).

## G. Logging

- `logger = logging.getLogger(__name__)` — never `print()` outside CLI
  `__main__` blocks.
- Log at INFO per source (counts), WARNING for degraded fetches, ERROR for
  zero-record scrapes of a directory that should never be empty. Silent
  failure is the #1 operational bug class in this codebase — when in doubt,
  ERROR-log it so `collector_status.json` reviews catch it.

## H. refresh_all wiring

- **Campus**: add the module's `SCHOOL` to `SCHOOL_CONFIGS` in
  `schools/__init__.py`. That's all — the loop, isolation, and status keys
  (`campus_graph:<slug>`) are generic.
- **Faculty**: three manual edits in `refresh_all.py` —
  1. import the pair: `from .schools.<slug>_faculty import fetch_and_normalize as fetch_<slug>_faculty` (+ merge alias);
  2. append `("<slug>_faculty", fetch_<slug>_faculty, merge_<slug>_faculty)`
     to the deep-only faculty list **at the end** (UCB order is semantic:
     EECS before STAT; neuro/datascience last — never insert above them);
  3. keep the source deep-only (faculty scrapes are the expensive class).
- Budget: the Monday deep run is ~3.7h against a 300-min CI cap — check
  `collector_status.json.duration_seconds` after adding a school.

## I. Stale / deactivate wiring

- Add `"<slug>_faculty"` to `deactivate_stale_faculty.FACULTY_SOURCES` **in
  the same PR** as the refresh_all wiring (set-equality test enforces it).
- Add the school/audience rows to `school_audience.SOURCE_DEFAULTS` in the
  same PR: `<slug>_faculty → (slug, "unknown")`, campus triple →
  `(slug,"campus") / (None,"open") / (slug,"unknown")`.
- Faculty freshness then needs nothing else: absent-from-rescrape professors
  retire after `GRACE_DAYS=14`, reactivation is automatic on reappearance.
- Deadline-bearing sources are covered by `deactivate_past`; a feed source
  with its own liveness signal implements a source-specific stale pass like
  `simplify_internships.deactivate_stale`.

## J. Tests

Fixtures are inline HTML/JSON constants in the test file (no fixtures/ dir);
HTTP is monkeypatched (`fetch_soup` / `requests.get` fakes); no network.

Minimum per new school:
1. **Config-contract test class** (pattern: `TestUwConfig` etc. in
   `test_faculty_graph.py`, `TestPrinceton` etc. in `test_campus_graph.py`):
   `validate(SCHOOL) == []`, registry membership, source in
   `FACULTY_SOURCES` + `SOURCE_DEFAULTS`, seed-path record shape, id prefix.
2. **Parser test per novel markup family** with a realistic HTML/JSON
   fixture: extracts names/titles/emails, skips non-persons and emeritus,
   pagination stops on no-new-records, missing-field degradation.
3. **ID stability**: deterministic ids; for scraped directories pin 2–3 real
   ids byte-exact (drift = mass duplication on next refresh).
4. The wiring is auto-guarded by `tests/test_collector_wiring.py` (disk →
   refresh_all → FACULTY_SOURCES/SOURCE_DEFAULTS) — it fails if you forget a
   registry, so run it first when adding a school.
5. DQ gate `tests/test_opportunity_data_quality.py` must stay green after the
   first real refresh lands data.

## K. PR checklist (new school)

- [ ] `schools/<slug>.py` + `schools/<slug>_faculty.py` configs; URLs verified HTTP-200, note the date in the docstring
- [ ] `SCHOOL_CONFIGS` entry (campus)
- [ ] refresh_all: faculty import pair + deep-loop tuple (at the end)
- [ ] `FACULTY_SOURCES` + `SOURCE_DEFAULTS` entries (same PR — tests enforce)
- [ ] config-contract tests + parser fixtures + id-stability pins
- [ ] `pytest tests/test_collector_wiring.py tests/test_refresh_all.py tests/test_deactivate_stale_faculty.py tests/test_faculty_graph.py tests/test_campus_graph.py` green
- [ ] ruff clean; no `print`, no bare `verify=False`, no `uuid4` ids
- [ ] frontend catalog/switcher entries if the school is user-facing (separate task is fine)
- [ ] PR body: department count, mechanism mix (scrape/api/render/...), expected record volume, deep-run cost estimate
- [ ] merge to main needs Eric's explicit consent; data lands via the CI refresh PR, not hand-committed

---

## Known debt (do NOT copy these patterns)

- `base.py` (`BaseCollector`/`RawOpportunity`) is vestigial — only the UIUC
  program collectors use it; new code ignores it.
- `config/sources.yaml` is documentation-only; nothing reads it.
- Three copies of name-cleaning/email-nulling/keyword-junk logic exist
  (uiuc_faculty / ucb_common / faculty_graph); converge opportunistically —
  engine helpers are the canonical copies.
- ~20 per-collector `merge_into_processed` variants predate the engines;
  new collectors must reuse the engine merges.
- UIUC program collectors emit a slim legacy schema (no `source_type` /
  `department` / confidence); scheduled for schema alignment, not a template.
- Duplicated seed records exist across uiuc_drp/uiuc_siebel/uiuc_other
  (CS DRP, ISUR) — pending owner decision.
