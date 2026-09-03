# Collectors Publish / Zero-Output Department Isolation — Audit & Report

Audited tree: `origin/main` @ `4f8b0fb` → `fb008b7` (#863). Audit date: 2026-09-03.
Method: traced the runtime publish path end to end, then read what production
has **on disk** — the committed shards, `collector_status.json`, and its
history ledger. That is how the three broken collectors and the 44-day UC
Berkeley freeze were found; every count and timestamp below comes from those
artifacts, not from reasoning about the code.

## The failure

```
one department collector emits 0
  → the release contract attributes the zero to the source's SCHOOL
  → by_unit[school].ready = False
  → publishable drops the school
  → shard_corpus.py split --only-shards never writes <school>.json
  → the whole school goes stale, healthy departments included
```

UC Berkeley is collected by **54 separate `ucb_*_faculty` collectors**, one per
department, and `unit_of()` mapped every one of them onto the single `ucb`
publication unit. `ucb_ling_faculty` broke, so all of UC Berkeley stopped
publishing.

## Phase 1 — Audit verdicts

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Collector execution architecture | PASS | `refresh_all.py:1219-1259` — each source is independently try/except'd; one failure never stops siblings from collecting |
| 2 | Department/source boundaries | PARTIAL | Real per-department sources exist (54 for UCB), but `refresh_contract.unit_of()` collapsed all of them to one school unit |
| 3 | Shard generation | PARTIAL | `shard_corpus.split()` is upsert-only, never `--prune` on a scheduled run, and has a shrink guard — but the guard `raise`d **before writing any shard**, so one flaked school discarded every healthy school in the run |
| 4 | School aggregation | **FAIL** | `by_unit[unit].ready` is one boolean AND-ed over every source attributed to the school. No representation for "mostly healthy" |
| 5 | Publish gate | PARTIAL | Isolated per *school* since the 2026-08-08 UCSB incident (`publishable_shards.py`), never per department |
| 6 | Zero-output validation | **FAIL** | `emitted == 0` blocked the unit. Worse, a zero was indistinguishable from a failure: `fetch_soup()` returns `None` on a 403 bot wall, `_scrape_directory()` degrades to `[]`, and the summary records `{"fetched": 0, "status": "ok"}` either way |
| 7 | Last-known-good behavior | PASS | `deactivate_stale_faculty` authorizes retirement only for sources reporting `ok`, and `MIN_SCRAPE_RATIO` skips a partial scrape. No records were ever lost — only every other department's refresh |
| 8 | Currently broken collectors | **3 FOUND** | see below |
| 9 | UCB stale root cause | **CONFIRMED** | `ucb_ling_faculty`; the department moved to `lx.berkeley.edu` and the parser's `previous_sibling` assumption stopped holding |
| 10 | Freshness timestamp semantics | **FAIL** | Only per-record `last_seen_at` plus ONE corpus-wide timestamp (`corpus_freshness.corpus_last_updated_at`). No `last_attempt_at` / `last_success_at` / `last_publish_at` anywhere, per source or per school |
| 11 | Per-shard monitoring | NOT IMPLEMENTED | `/admin/collector-status` serves only the current run's snapshot, and each run rewrites it for its own shard alone — so a department dead for six weeks looked the same as one not scheduled today |
| 12 | Per-school monitoring | NOT IMPLEMENTED | No per-school freshness existed at all |
| 13 | Admin/alert integration | PARTIAL, and **actively masking** | `ops.py` opened incidents for `status == "error"` only. A `status == "ok"` source with `fetched: 0` hit the recovery branch and **auto-resolved its own incident** as a "verified successful run", every week |
| 14 | `fully_stale_school_count` | Existed only for professor tracking (`professor_profiles.py:548`), never for corpus shards |

### The exact veto condition

`src/collectors/refresh_contract.py`, before this change:

```python
elif fetched == 0:
    block(f"required source {key} emitted zero records", unit_of(key))
```

`unit_of()` returns the **shard file**, which is per school. So one department
at zero withheld every sibling department in the same file.

Two further vetoes, both fixed here:

* `shard_corpus.split()` raised on any shrunken target before writing
  anything — a whole-**run** veto, wider still than the school-level one.
* `ops.py:1140` auto-resolved a `collector_failure` incident for any `ok`
  source, zero included, so the alarm cleared itself.

### Broken collectors (real evidence)

| school | source | current | last good | last success | first zero | root cause |
|---|---|---|---|---|---|---|
| ucb | `ucb_ling_faculty` | 0 | 17 | 2026-07-21 | 2026-08-18 | **URL + template drift.** `linguistics.berkeley.edu/faculty` 301s to `lx.berkeley.edu/people/faculty`; each person is now a `div.panel-pane` whose `h2.pane-title` holds the name, so the heading is no longer the table's `previous_sibling` |
| colgate | `colgate_faculty` | 0 | 314 | 2026-07-29 | 2026-08-19 | **Selector drift.** The college-wide directory View was re-themed onto `table-results-view`; the name link moved from `.h3 a` to `h3.table-results-view__link a`, so every row was dropped for want of a name |
| swarthmore | `swarthmore_faculty` | 0 | 228 | 2026-07-29 | 2026-08-15 | **Not a code fault.** Returns 224 records from a residential IP; fails only from CI egress. Needed classification as a failure, not a parser change |
| ucb | `ucb_pmb_faculty` | 31 | 31 | 2026-08-25 | 2026-08-18 | Transient; recovered by itself — and blocked all of UC Berkeley for a week on the way past |

`ucb_ling_faculty` reproduced deterministically before the fix: `Found 0 LING
faculty` against the live site. Its unit test stayed green throughout, because
the fixture encoded the pre-move markup.

### Blast radius, measured

`data/processed/shards/ucb.json`: 3,106 records, **3,018 stamped
`last_seen_at 2026-07-21`** — 44 days, across runs on 08-18 and 08-25 that both
collected healthy data for 53 departments and discarded it.

Corpus-wide, 117 shards; 4 older than 7 days: `ucb` 44d, `ucd` 44d (a
documented Cloudflare block), `swarthmore` 36d, `colgate` 36d. The other 113
were inside the normal weekly rotation band (0–9 days).

## Phase 2 — What changed

**Zero-output vocabulary** (`src/collectors/source_health.py`). Four outcomes
replace the one `"ok"` that covered three different situations:

```
success_nonzero   records emitted
valid_zero        emitted nothing, and nothing is DECLARED expected for it
suspicious_zero   emitted nothing while the corpus holds active records
failed            errored, or could not say how much it produced
```

`valid_zero` is never inferred. It requires membership in
`CONFIRMED_EMPTY_SOURCES` (currently `ucb_urap_projects`, whose own docstring
records "0 off-season"). An undeclared source that has held records and now
emits none is `suspicious_zero`; so is a mandatory producer that has *never*
produced (`ucd_faculty`, walled off by Cloudflare). The baseline is counted
from the corpus at run time, so it cannot be manufactured by running the
pipeline.

**The gate**, per department instead of per school. A `suspicious_zero`
degrades its own source and its school still publishes. This is safe because
the layers below already prove it: merges are upsert-only, so an empty harvest
cannot delete a record, and `deactivate_stale_faculty` authorizes retirement
only for sources reporting `ok` — which a suspicious zero no longer does, so
its records are preserved rather than retired.

What is **not** waived: an errored source still blocks its school (accuracy,
not coverage); a source whose evidence cannot be trusted still blocks
(`ucsb_urca_projects` without complete sitemap evidence); structural failures
still block everything; and the verdict stays degraded every run until the
source emits records again.

**The freshness ledger** (`data/processed/source_health.json`, committed
alongside the shards it describes). Per source: `last_attempt_at`,
`last_success_at`, `current_count`, `last_good_count`, `status`,
`failure_reason`, `consecutive_failures`. Per shard: `last_publish_at`.
`last_success_at` advances **only** on a healthy outcome — this is the whole
mechanism by which a permanently broken department stops hiding behind fresh
siblings.

Publishing is per shard; succeeding is per source. `record_publish()` writes
only into the `shards` section and never touches a source row, so "UCB
published today" can never become "every UCB department succeeded today".

**Eligibility.** Staleness is judged only for sources a scheduled run is
required to produce (`refresh_contract.monitored_sources()` — the same
definition publication uses). The corpus also carries `manual` seeds and
`*_external_research` pages that a campus crawl only re-stamps when it
rediscovers them; judging those on a weekly clock reported the `national`
shard permanently degraded, and a monitor that is always amber is one nobody
reads. They are shown with `eligible: false`, never counted.

**Boundaries** are counted in missed weekly slots, not the corpus-wide 72/96
*hours*: each shard is scraped once a week, so an hours-scale bound would mark
every correctly-refreshed school stale six days out of seven. `warn > 10d`
(missed its slot once), `stale > 17d` (missed two, and past
`GRACE_DAYS = 14`, so its records are now being retired for absence — real
product impact, which is the honest place to draw the line).

## Remaining debt

* **`swarthmore_faculty` from CI egress.** The collector is healthy (224
  records locally); the runner's IP is refused. It will now be classified
  `failed`/`suspicious_zero` and alert instead of silently vetoing the school,
  but the underlying block is not fixed. Needs a UA/pre_delay probe from a
  runner, or the render path, before CI collects it.
* **`ucd_faculty`** remains a permanent `suspicious_zero` (0 records, strict
  Cloudflare challenge — see `docs`/memory: no evasion). It now degrades UC
  Davis rather than blocking it, and UC Davis publishes its 7 URC programs.
* **One-time id churn for link-less LING faculty.** Records whose URL was the
  synthetic `linguistics.berkeley.edu/faculty#<slug>` anchor get a new id under
  the new host. One person (Sherry Hicks) is affected; the old row retires
  through the normal grace window.
* **No fetch-outcome provenance inside the engine.** `classify()` separates a
  broken collector from a legitimately empty one using the corpus baseline,
  which is sufficient and unfakeable, but the summary still cannot say *why* a
  zero happened (403 vs markup drift). Recording attempted/loaded page counts
  per department — as `campus_graph` already does — would make the alert
  self-diagnosing.
* **`tests/test_professor_updates_api.py::test_limit_and_has_more`** fails on a
  wall-clock-rotted fixture (records dated 2026-07-02, `FRESHNESS_TTL_DAYS =
  60`). Pre-existing and unrelated — verified by stashing this branch's changes
  and re-running.
