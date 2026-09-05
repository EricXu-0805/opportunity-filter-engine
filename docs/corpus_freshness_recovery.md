# Corpus freshness: decomposition, recovery, and what is still blocked

Written 2026-09-05, after `corpus_freshness` became a blocking release gate.
Numbers here are reproducible: `python3 scripts/release_gate.py --release-sha
<sha>` for the record dimension, `python3 scripts/source_freshness_report.py
report` for the source dimension.

## 1. The number that was being reported was not the release requirement

The previous ledger reported **34.8% freshness, 39 fully-stale schools** and
called it "reported but not gating". Both halves were wrong.

That figure came from `professor_tracking.json`, which measures whether each
of 129,060 active professors has a **tracking baseline**. 85,002 never got
one. That is a coverage gap in a feature nobody ships — `professor_signals` is
`False`, so all four consumers of that artifact are 404'd or skipped. It says
nothing about the freshness of what students actually read.

The release requirement is the **corpus**: were the records we serve
re-observed recently? Measured on every active record's own `last_seen_at`
against `GRACE_DAYS` (14 — the bound `deactivate_stale_faculty` already uses
for "unseen for two missed weekly deep runs"), the answer was **91.17% with
four fully-stale schools**.

Both numbers are now computed, both are reported, and they have separate names
(`corpus_freshness`, `tracking_freshness`) so neither can stand in for the
other again.

## 2. Decomposition, before recovery

```
total records in shards        137,816
  active                       134,169
  inactive (deactivated)         3,647
  fresh active                 122,325
  stale active                  11,844
FRESHNESS                        91.17%   (floor 95.0%)

schools (shards)                   117
  fully fresh                        4
  partially stale                  109
  FULLY STALE                        4     ucb, colgate, swarthmore, ucd
  zero-active (suspicious)           0
```

Stale records by age — the shape matters, because a single broad band means
one systemic cause rather than ordinary weekly drift:

| age | stale records |
|---|---|
| 14–20d | 1,389 |
| 21–27d | 193 |
| 28–34d | 476 |
| 35–41d | 2,018 |
| **42–48d** | **5,774** |
| 49–69d | 1,409 |
| >100d | 18 |
| never seen | 26 |

Ranked by contribution to the deficit:

| stale | cum. | school | fresh/active | dominant stale source |
|---|---|---|---|---|
| 3,062 | 27.1% | ucb | 0/3,062 | `faculty_research` 2,125, `ucb_program` 861 |
| 1,004 | 36.0% | wisc | 783/1,787 | `faculty_research` 1,002 |
| 809 | 43.1% | nyu | 1,359/2,168 | `faculty_research` 809 |
| 718 | 49.5% | tamu | 2,542/3,260 | `faculty_research` 718 |
| 508 | 54.0% | jhu | 4,076/4,584 | `faculty_research` 508 |
| 281 | 56.5% | osu | 2,239/2,520 | `faculty_research` 281 |
| 251 | 58.7% | umd | 1,055/1,306 | `faculty_research` 251 |

After UCB the tail is uniform: individual **departments** decaying inside
otherwise-healthy schools, ~100–1,000 records each across 112 schools. No
single further repair moves the total much.

## 3. Root cause of the four fully-stale schools

All four were **in** the weekly rotation and being attempted. None was
"never scheduled".

The signature was identical in three of them, and it is the reason
`status: ok` is not evidence of anything:

```
swarthmore_faculty: fetched=0  status=ok    2026-08-15, 08-22, 08-29
colgate_faculty:    fetched=0  status=ok    2026-08-19, 08-26
ucb_ling_faculty:   fetched=0  status=ok    2026-08-18, 08-25
```

A collector that fetches nothing and reports success looks like a healthy run
in every summary, moves no `last_seen_at`, and freezes its school. This is the
`suspicious_zero` outcome the shard-isolation work introduced, and these are
the runs that motivated it.

| School | Records | Root cause | Outcome |
|---|---|---|---|
| **colgate** | 323 | `colgate_faculty` returned 0 for 5 weeks | **RECOVERED** |
| **swarthmore** | 238 | `swarthmore_faculty` returned 0 for 3 weeks | **RECOVERED** |
| **ucb** | 3,062 | `ucb_eecs_faculty` upstream host gone; publish withheld | **BLOCKED** |
| **ucd** | 7 | Cloudflare WAF, deliberate backend-only onboarding | **BLOCKED** |

### colgate and swarthmore — recovered

Both collectors were run directly and both work:

```
colgate_faculty:     308 fetched,  6 new, 302 updated   zero_class=success_nonzero
swarthmore_faculty:  224 fetched,  6 new, 218 updated   zero_class=success_nonzero
```

The collectors were never broken *here*. They return 0 from the CI runner and
full rosters from a residential IP — an IP-reputation block that produces a
200 with no cards, which is exactly why it reported `ok`. The refresh was
re-run, the release contract passed both schools (`publishable: [colgate,
swarthmore]`), and their shards were republished with real observations.

**This is the honest bar for "recovered": a real harvest moved real
`last_seen_at` stamps.** Nothing was re-timestamped.

## 4. Still blocked, with owners

### `ucb` — 3,062 records, 27% of the deficit

```
status:              BLOCKED
reason:              ucb_eecs_faculty source host is gone; publish gate
                     correctly withholds the whole school
owner:               data pipeline owner
affected_freshness:  +2.28pp (91.57% -> 93.85%) if published
```

The refresh was run. **55 of UCB's 56 sources harvested successfully today.**
One did not:

```
ucb_eecs_faculty: fetched=0  zero_class=suspicious_zero  baseline=144
```

`www2.eecs.berkeley.edu` — the directory this collector has always read — no
longer serves HTTP. TLS connects and the certificate verifies, then the
request dies (`SSL: UNEXPECTED_EOF_WHILE_READING`); three consecutive attempts
and the site root all return nothing. EECS has moved to
`https://eecs.berkeley.edu/people/faculty/`, which is a different platform and
serves **no faculty cards in its static HTML** (0 mailto links, one profile
link, and that one is the in-memoriam page) — the roster is rendered
client-side.

Repointing the collector is therefore not a URL change. It needs a fresh
recon, new selectors, and the headless render path, which is onboarding-grade
work and its own change.

The release contract then withholds the *entire* school:

```
required faculty sources were partial:
  ['ucb_datascience_faculty', 'ucb_econ_faculty', 'ucb_ling_faculty',
   'ucb_scandinavian_faculty', 'ucb_soc_faculty']
release.status: blocked   ready: False   publishable: []
```

Those five scraped 94–100% of their stored counts — ordinary roster churn —
but the gate holds the school until faculty retirement can be reasoned about
safely. **That gate was not touched.** Publishing UCB by relaxing it would be
exactly the "treat a partial scrape as a refresh" failure the gate exists to
prevent, so UCB's freshly harvested records were deliberately **not**
published, and the work file was reset from the committed shards.

Note the two dimensions disagree, and both are right:

- `no_fully_stale_school` (per source, from the run ledger): UCB is
  **partially degraded** — 55 of 56 sources fresh.
- `corpus_freshness` (per record, from the shards): UCB is **fully stale** —
  every published record is 45 days old.

UCB's collectors work. UCB's *data* is stuck behind the publish gate. Only the
second fact reaches a student, which is why the record dimension is the one
that gates the release.

**Recommended action:** re-onboard `ucb_eecs_faculty` against
`eecs.berkeley.edu/people/faculty/` using the render path, then re-run the UCB
shard. Until then UCB stays fully stale and the release stays NO-GO.

### `ucd` — 7 records

```
status:              BLOCKED
reason:              Cloudflare managed challenge; robots.txt disallows AI
                     crawlers; onboarded backend-only by decision
owner:               project owner (policy), data pipeline owner (execution)
affected_freshness:  +0.005pp — negligible in percent, but it is the last
                     school between fully_stale_school_count and 0
```

UC Davis was onboarded deliberately backend-only: the collector and its seven
URC programs exist, the school is not in the switcher, and faculty is zero
because a strict Cloudflare managed challenge blocks the render path from
datacenter and flagged IPs. **No stealth or evasion is permitted**, so there is
no in-repo route to recovering it.

**Recommended action:** obtain an official UC Davis API or crawl allowlist, or
formally retire the school from the corpus. Until one of those happens
`fully_stale_school_count` cannot reach 0, and the release cannot pass this
gate.

## 5. After recovery

```
                          before      after
freshness_percent          91.17%     91.57%     (floor 95.0%)
fully_stale_school_count        4          2      ucb, ucd
active records            134,169    134,142
fresh records             122,325    122,839
stale records              11,844     11,303
fully fresh schools             4          4
partially stale schools       109        111
```

Source dimension, once the ledger existed (`source_freshness_report
bootstrap`, seeded from the `last_seen_at` real harvests already stamped —
never invented, never overwriting a row a real run wrote):

```
school_count                     117
fully_fresh_school_count         115
partially_degraded_school_count    1     ucb (55/56 sources fresh)
fully_stale_school_count           1     ucd
stale_shard_count                  2
failed_shard_count                 0
degraded_shard_count               1
total_shard_count                288
```

## 6. Why the release stays NO-GO

Neither acceptance condition is met, and neither can be met by anything in
this repository:

```
freshness 91.57% < 95.0%          FAIL — needs ucb (+2.28pp) and a
                                         department-level sweep for the rest
fully_stale_school_count 2 > 0    FAIL — ucb and ucd, both blocked above
```

The remaining ~8,200 stale records after UCB are individual departments
decaying inside healthy schools. Reaching 95% needs a systematic
department-level freshness sweep, not another one-school repair — the tail is
flat, and no single school after UCB contributes more than 0.75pp.


---

# Round two — 2026-09-05

## 7. The UCB veto was in the contract, not the collectors

Round one reported UCB as "55 of 56 sources harvest, publish withheld" and left
it there. Traced properly, the veto is one branch in
`src/collectors/refresh_contract.py`, and it contradicts a decision the same
file makes two hundred lines above it.

`suspicious_zero` **degrades**, with the reasoning written out: merges are
upsert-only so an empty harvest cannot delete a record, and
`deactivate_stale_faculty` declines to retire from a source that is not
reporting `ok`, so what publishes is not wrong — there is just less of it.

`skipped_partial_scrape` **blocked**. Every word of that reasoning applies to
it, and one word more: `skipped_partial_scrape` *is*
`deactivate_stale_faculty`'s own record that it already declined to retire from
those sources. The veto re-spent a safety budget that had already been spent,
and because `unit_of()` resolves a source to its shard file — one file per
school — it charged the whole school for it.

Re-evaluating the recorded 2026-09-05 UCB summary with the branch changed to
degrade:

```
before   status blocked    ready False   publishable []
after    status degraded   ready True    publishable ['ucb']
         + 1 suspicious_zero and 5 partial_scrape degradations, one per source
```

Nothing about freshness is laundered by this. The merge writes `last_seen_at`
only on records it actually re-observed; the rest keep the stamps they had and
go stale on schedule. That is the partial-degradation outcome the policy asks
for, and it is now the tested one.

**Answering the audit directly:** #879 isolates publication *between* schools,
which is as far as a shard file goes — one file per school. It did not isolate
*within* a school, because it fixed the zero branch and not the partial branch.
With both fixed, one dead department no longer freezes its university.

## 8. The stale tail is one failure, repeated

Every school in the top thirty shows the same signature. Their faculty
collector scrapes well under its stored active count, which trips
`MIN_SCRAPE_RATIO`, so the unseen records are neither re-observed nor retired.
They accumulate as permanent stale weight.

| school | last run | fetched | active | ratio |
|---|---|---|---|---|
| wisc | 2026-08-26 | 846 | 1,765 | 48% |
| nyu | 2026-08-25 | 1,348 | 2,157 | 62% |
| tamu | 2026-08-25 | 2,542 | 3,252 | 78% |
| oregonstate | 2026-09-03 | 359 | 604 | 59% |
| sbu | 2026-08-29 | 663 | 909 | 73% |
| unl | 2026-08-28 | 1,000 | 1,211 | 83% |
| umd | 2026-08-26 | 1,111 | 1,299 | 86% |
| ucla | 2026-09-03 | 1,738 | 1,988 | 87% |
| ncsu | 2026-08-31 | 1,996 | 2,302 | 87% |
| jhu | 2026-08-28 | 4,058 | 4,554 | 89% |

Note oregonstate, ucla and vanderbilt: they ran on **2026-09-03**, two days
before this measurement, and are still stale. This is not a scheduling
backlog. The collectors run and under-deliver.

### Which is it — broken scraper, or faculty who left?

Decided by shape, not assumption. A department where *every* record is stale
did not lose all its professors; its page moved or its markup changed. A
department with some fresh and some stale is where real departures live.

```
departments fully fresh                  2,798
departments partly stale                 1,004
departments ENTIRELY stale                 239

stale records in entirely-stale depts    7,748   74.5%   <- URL rot / drift
stale records scattered in live depts    2,650   25.5%   <- possible departures
```

Spot-checked against wisc, whose 35 dead departments hold 923 of its 1,002
stale records:

| department | configured URL | result |
|---|---|---|
| Statistics | `stat.wisc.edu/people/` | **404** — moved |
| English | `english.wisc.edu/people/faculty/` | **404** — moved |
| Computer Sciences | `www.cs.wisc.edu/people/faculty-2/` | 200, parses 0 — **selector drift** |
| Economics | `econ.wisc.edu/faculty/` | 200, parses 0 — **selector drift** |

Both signatures, in one collector.

### What this rules out

**Mass retirement would be wrong.** The obvious way to "improve" freshness here
is to let `deactivate_stale_faculty` retire the 10,398 stale faculty, which
would remove them from the denominator and lift the percentage immediately.
The shape analysis says that would delete ~7,700 professors who never left —
their department's page moved. `MIN_SCRAPE_RATIO` is correctly refusing, and
per-unit ledgers (which only UIUC supplies today) would correctly refuse too: a
department scraping 0 against N active is skipped by design.

The freshness deficit is **4,756 records**. The 239 dead departments hold
**7,748**. Repairing them covers the deficit with room to spare, and it is the
only route that makes those records genuinely fresh rather than genuinely gone.

## 9. Recovery priority

Ranked by percentage points recoverable, not alphabetically. Every row is the
same recovery path — re-recon the department URL, repair the selector, re-run
the shard — which is why they are worth batching by collector rather than by
school.

| # | school | source | stale | of | last success | gain | cum |
|---|---|---|---|---|---|---|---|
| 1 | wisc | wisc_faculty | 1,002 | 1,787 | 2026-08-19 | 0.75pp | 0.75pp |
| 2 | ucb | ucb_urap_projects | 861 | 3,062 | 2026-07-21 | 0.64pp | 1.39pp |
| 3 | nyu | nyu_faculty | 809 | 2,168 | 2026-08-18 | 0.60pp | 1.99pp |
| 4 | tamu | tamu_faculty | 718 | 3,260 | 2026-08-18 | 0.54pp | 2.53pp |
| 5 | jhu | jhu_faculty | 508 | 4,584 | 2026-08-14 | 0.38pp | 2.91pp |
| 6 | osu | osu_faculty | 292 | 2,520 | 2026-08-22 | 0.22pp | 3.12pp |
| 7 | umd | umd_faculty | 251 | 1,306 | 2026-08-19 | 0.19pp | 3.31pp |
| 8 | sbu | sbu_faculty | 248 | 914 | 2026-08-22 | 0.18pp | 3.50pp |
| 9 | oregonstate | oregonstate_faculty | 246 | 608 | 2026-08-20 | 0.18pp | 3.68pp |
| 10 | unl | unl_faculty | 220 | 1,216 | 2026-08-14 | 0.16pp | 3.84pp |

The top thirty together are 5.83pp of the 8.55pp total deficit. No single
school after wisc is worth more than 0.64pp — the tail is flat, which is why
the unit of work is the shared failure signature, not the school.

## 10. UC Davis, investigated rather than assumed

Probed 2026-09-05. The conclusion is unchanged but it is now evidence rather
than recollection.

| Route | Result |
|---|---|
| `urc.ucdavis.edu/*` content pages | **403** Cloudflare |
| `urc.ucdavis.edu/jsonapi` (Drupal JSON:API) | **403** |
| `urc.ucdavis.edu/rss.xml`, `/feed` | **403** |
| Supported render path (real headless Chromium) | **403** — "Attention Required! \| Cloudflare" |
| `urc.ucdavis.edu/sitemap.xml` | **200**, 450 entries |
| `urc.ucdavis.edu/robots.txt` | **200** — standard Drupal; content is **not** disallowed |
| `www.ucdavis.edu`, `catalog.ucdavis.edu` | 200 |
| `engineering.` / `lettersandscience.` / `financialaid.ucdavis.edu` | 403 |

Two things worth separating. **robots.txt permits this content** — only
`/core/`, `/profiles/` and admin paths are disallowed. The barrier is an edge
bot-management decision, not a crawl policy. That is why the unblock is an
allowlist request to UC Davis, not a technical workaround, and why no
workaround was attempted: the supported browser path is refused the same way
`requests` is, and going further would be evasion.

**The source is still the correct source.** All seven records' URLs are still
listed in the official sitemap, so the corpus definition is not wrong and UCD
stays in the denominator. The sitemap also carries `lastmod` for 445 of its 450
entries — and it is deliberately **not** used to refresh these records. A
sitemap entry proves a URL exists and when the CMS last touched it; it does not
re-observe a record's title, description, or deadline. Treating it as a
re-observation would raise freshness on weaker evidence than the pipeline's own
semantics, which is the failure mode this whole effort exists to prevent.

```
status:              BLOCKED
owner:               project owner
reason:              Cloudflare managed challenge on urc.ucdavis.edu; refused to
                     requests, to structured endpoints, and to the supported
                     render path alike
recommended_action:  request a crawl allowlist from UC Davis for the URC host,
                     or formally retire the school from the active corpus
affected:            7 records; the last school between fully_stale_school_count
                     and 0
```
