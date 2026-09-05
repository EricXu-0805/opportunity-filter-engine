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
