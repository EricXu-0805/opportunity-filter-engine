# Publication trust: the historical remediation

> **The invariant.** A paper may be presented as a professor's only when the
> attribution is stamped `verified_author_id` **by the gate currently in
> force**. Everything else — name-matched, unstamped, withdrawn, ambiguous,
> or verified by a gate we have since retired — is not a trusted professor
> paper, anywhere.

## Why a remediation was needed at all

`src/publication_trust.py` has always answered "may this be cited today". It
could not answer "was this ever judged by a rule we still believe in", and for
6,255 professors the answer was no.

Gate 1 decided whether a paper could be a professor's by asking whether its
OpenAlex field sat anywhere in the nine-field family their **department** could
plausibly touch. Electrical & Computer Engineering spans nine fields including
Computer Science and Environmental Science, so for UIUC's Zhi-Pei Liang — an
MRI researcher — that family admitted a search-agent paper, a geochemical
anomaly-detection paper and a multi-agent figure-generation paper, and excluded
his own imaging work, which is filed under Medicine. All three were stamped
`verified_author_id`. A cold email generated on 2026-08-30 offered them to a
student as "your recent paper".

#846 replaced the rule with the author's own published fields. It could only
ever bind *future* harvests: `_works_targets` skipped anything already stamped
verified, so the records that most needed re-judging were precisely the ones
excluded from the pass that would have done it. #849 versioned the gate so they
become targets again. Neither changed the data.

This is the machinery that changed the data.

## The shape of it

```
   remediation_population()          every record a superseded gate approved
            │
            ▼
   invalidate_population()           trust withdrawn corpus-wide, in one pass,
            │                        BEFORE a single request is made
            ▼
   harvest_works_by_roster()         the supported harvest, metered, resumable
            │
            ▼
   apply_works() + apply_disposition()   re-attribute, retract, invalidate the
            │                            derivations that shared the provenance
            ▼
   Ledger.settle()                   exactly-once, durable, auditable
```

### Why the withdrawal comes first

The re-harvest needs a third party, a budget and hours. If trust were withdrawn
professor-by-professor as each one's turn arrived, every professor whose turn
had not come would keep serving citations no living rule approves, for the whole
window. So the withdrawal is one cheap local pass over the corpus that takes all
of it at once. **The failure mode of a slow or abandoned remediation is missing
personalization, never false attribution.**

`pending_remediation` is a real status rather than a deleted stamp because "we
took this back on purpose and it is queued" and "nobody ever looked at this" are
different facts, and the ledger, the operator queue and the next harvest all
need to tell them apart.

### Why the papers stay on the record

A withdrawn record keeps `metadata.recent_works`. They are the candidate list
the re-harvest is judged against, and a record that has forgotten what it used
to claim cannot be audited afterwards — "we removed three citations from this
professor" is a sentence the ledger can only write if the three were still there
to count. What leaves is the trust, and the resolved-author id, which is the
assertion "this OpenAlex person is this professor" that the retired rule made.

## Running it

```bash
# 1. What is affected? Mutates nothing.
python3 scripts/remediate_publications.py audit --out data/audits/remediation.json

# 2. Make the window safe. No network, no API key, idempotent.
python3 scripts/remediate_publications.py invalidate --save

# 3. Buy the answers. Metered; stops cleanly on an exhausted budget.
python3 scripts/remediate_publications.py harvest --schools uiuc \
    --roster-dir ~/oe-work/rosters --out /tmp/w.json --manifest /tmp/m.json

# 4. Land them.
python3 scripts/remediate_publications.py apply /tmp/w.json \
    --manifest /tmp/m.json --save

# 5. Prove it. Exits non-zero while either invariant is unmet.
python3 scripts/remediate_publications.py report
```

Steps 3 and 4 are per school and safe to repeat. Step 2 is safe to repeat at
any time and is *also* run by every data refresh (below), so it is not something
anyone has to remember.

### Cost

The roster path is what makes this affordable. Resolving an author through
OpenAlex's search API costs 10 credits a professor; paging an institution's
whole author roster costs 1 credit per 100 authors and answers for everyone at
that school at once. Papers are then bought 25 professors to a request. The free
tier (~1,000 credits/day, no key) covers several schools a day; a prepaid
`OPENALEX_API_KEY` raises the ceiling. Rosters cache under `--roster-dir`
(gitignored), so a resumed run re-pays for nothing.

## Exactly-once, and what that means here

The corpus write and the ledger append are two files and cannot be made one
atomic act. Rather than pretend otherwise, `apply` **writes the corpus first**
and settles the ledger after, and the mutation is self-describing:
`metadata.works_gate` at the target version is proof the remediation ran,
whoever failed to write it down.

So a crash between the two leaves a record the next run *reconciles* — records
the completion — instead of re-applying:

```
attempt 1 → corpus committed → process dies before settle()
attempt 2 → Ledger.reconcile() sees works_gate == 2 with no terminal entry
          → appends verified_complete{reconciled: true}
          → mutates nothing
```

Retries are allowed and counted (`attempt_count`). Duplicate *logical*
remediation is not, and `Ledger.duplicate_count()` computes it from the raw
event stream rather than the deduplicating index, so it is able to be non-zero
if the invariant ever breaks.

The unit of remediation is one professor record at one target gate:

```
idempotency_key = f"{professor_id}@gate{to_gate}"
```

Bumping `CURRENT_WORKS_GATE` therefore makes every settled record a *new*
logical unit automatically. No migration, no hand-maintained list of affected
ids, and no risk of a future gate change being mistaken for a duplicate.

### The lifecycle is not the disposition

`status` is how far the unit got; `result` is what the gate decided. They are
recorded separately because a job that started, harvested, or even decided an
attribution has changed nothing a reader can see.

| status | means |
|---|---|
| `queued` | entered the population; pre-state recorded |
| `started` | claimed by a worker (increments `attempt_count`) |
| `harvest_succeeded` | an answer exists for this unit |
| `mutation_committed` | the professor record was written |
| `verified_complete` | the written state was checked against the verdict — **terminal** |
| `needs_review` | routed to a human — **terminal for automation** |
| `failed` | **not terminal**; the unit stays in the population |

| result | effect on the relationship |
|---|---|
| `verified` | restored — and only this one restores it |
| `removed` | the gate rejected every paper; citations retracted |
| `unknown` | never resolved to an author; candidates dropped |
| `ambiguous` | two candidates the rule cannot separate; stays untrusted |
| `needs_review` | a human decides; stays untrusted meanwhile |

**Rediscovery is not verification.** A paper the old gate chose that the new
harvest happens to return again is trusted because of the *new* stamp it earns,
never because it was already there.

## Derived signals

Removing a bad relationship is not enough if something built on it survives.

`metadata.keywords` stamped `derived:openalex_topics` is not derived from the
papers — it comes from the author's topic profile — but it comes from the **same
author resolution**. So the rule is evidence-shaped rather than blanket:

* the relationship is **re-verified** → the resolution is confirmed → keywords stand;
* the relationship is **destroyed** → the resolution is discredited → the keywords that rest on it go with it, and the `inferred_fields` stamp with them;
* the keywords were **scraped from the professor's own page** (no OpenAlex stamp) → untouched, because nothing the re-harvest found impeaches them.

Otherwise a professor keeps being described by a stranger's research areas after
the stranger's papers have been taken away.

Client-side, `frontend/src/lib/match-cache.ts` caches `recent_works` and
`publication_attribution_status` copied off the match card for seven days.
`CACHE_VERSION` carries `-pubtrust-v3` so those payloads are discarded — a stale
local cache would otherwise keep rendering revoked citations, and keep feeding
them to a cold-email draft, after the server stopped serving them.

Server-side caches need no action: the match snapshot key embeds
`corpus_version`, which moves when the shards do.

## It enforces itself

`src/collectors/refresh_all.py` runs `invalidate_population` on **every**
refresh and reports the result as a `publication_remediation` source. This is
the part that means production does not depend on anyone remembering a CLI:

* bumping `CURRENT_WORKS_GATE` retires thousands of records in one commit, and the next refresh withdraws their trust without being asked;
* a re-scrape that walks an old gate-1 stamp back into the corpus — through a merge, a shard restore, or `_carry_forward_enrichment` — is caught the same day.

It is a dict lookup per faculty record, no network, and idempotent: a clean
corpus reports zero and writes nothing.

`POST /api/cron/ops-scan` closes the loop for a human. While any professor
remains withdrawn it files a `data_drift` incident (a remediation nobody
finishes is indistinguishable, from outside, from one nobody started), and any
unsettled attribution becomes one rolled-up `manual_review` incident carrying
the evidence. Only an approved verified review outcome may restore trust — the
review queue never writes to the corpus.

## Verifying

```bash
python3 scripts/remediate_publications.py report
```

exits 0 only when both hold:

```
old_gate_professors            == 0     no superseded-gate trust anywhere
duplicate_logical_remediations == 0     nothing was applied twice
```

`pending_professors > 0` is **not** a failure. It is the honest state of a
remediation still in progress, and those professors are serving no paper
personalization while it lasts.
