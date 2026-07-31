# Truthfulness Sample-Verification Plan (Phase 2)

Phase 1 ([truthfulness_audit.md](truthfulness_audit.md)) audited the *code*
paths that produce each data category. Phase 2 audits the *data*: a structured
manual verification pass in which representative samples per category are
compared against the live source by a human/AI reviewer, and an aggregate
report gates "truthfulness approval" **fail-closed**.

Tooling: `scripts/truthfulness_audit.py` (stdlib only).

```bash
python scripts/shard_corpus.py assemble          # if the work file is absent
python scripts/truthfulness_audit.py sample      # -> data/audits/samples/<category>.json
# ... review loop: fill verdicts in the sample files ...
python scripts/truthfulness_audit.py report      # -> data/audits/truthfulness_report.json + GO/NO-GO
```

## Sample size and rationale

10 samples per category (`--per-category 10`), 10 categories = 100 rows per
audit round. A category only counts as complete when it holds **>= 8 samples
and zero pending rows** — small enough to review in one sitting, large enough
that the risk quotas below are all represented alongside a random slice. Per
category the sampler aims for **~4 risk-quota picks + 6 random** picks from
active records (`metadata.is_active is not False`). If a risk pool is empty in
the current corpus, the gap is recorded in the category file's
`risk_pool_gaps` (it is itself a finding — e.g. zero `verified_author_id`
publications) rather than failing the draw.

| Category | Field audited | Risk quotas (drawn first) |
|---|---|---|
| school | `school` (+`organization`) | multi-campus orgs (same org string under 2+ school slugs; "Purdue"+`school=purdue`); similarly-named orgs sharing a distinctive word (Columbia/Miami/Washington…) |
| department | `department` | unit-type confusion (Institute/Center/Laboratory/School of); empty department |
| professor | `pi_name` (identity + affiliation) | same name under 2+ schools; Emeritus/Visiting titles |
| position | `metadata.faculty_title` | non-professor rank (Lecturer/Instructor/Director/Scientist/Fellow); exactly "Professor" (known default-fill suspect); empty |
| program | `title` + `metadata.status` | `status == "unknown"`; `discovered == true`; stale year (< current year) in title |
| deadline | `deadline` / `is_rolling` | `deadline_is_estimate`; explicit past deadline; rolling with a `deadline_note`; blanket rolling faculty default |
| international | `eligibility.international_friendly` (+`citizenship_required`) | nsf_reu policy-derived "no"; any "yes" (must be explicit in source); `citizenship_required == true`; "unknown" (should stay unknown) |
| email | `contact_email` | `email_source` constructed\*; wayback; null email; generic local part (info@/admin@/contact@/office@/dept@) |
| research_area | `keywords` | keywords with empty `research_areas_raw` (no captured evidence); empty keywords (correctly unknown); identical keyword sets across 3+ records in one department (blanket suspicion) |
| publication | `metadata.recent_works` | works present with **no** `publication_attribution_status` (legacy name-match — must be dark in product); `verified_author_id` (gap noted if none exist); initials-only first names |

## Selection method

Deterministic seeded sampling: records are sorted by `id`, each category uses
`random.Random(f"{seed}:{category}")`, and the seed is recorded in every
artifact — the same seed always reproduces the same sample, and a single
category can be re-drawn independently without disturbing the others. Risk
quotas are filled round-robin across that category's risk selectors first;
the remainder is drawn uniformly from the active pool.

Each row also records `verification_status` — **what the system itself claims
about the value** (`verified` / `unverified` / `inferred` / `unknown` /
`policy_default`), derived from the record's own provenance stamps per the
Phase-1 findings (see the docstring of `derive_verification_status`). The
reviewer's job is to test that claim against reality.

## Reviewer instructions

For each row: open `source_url`, then

1. **Verify entity identity first.** Is this page actually about this
   professor / department / program at this school? Wrong entity =
   `entity_mismatch`, severity `critical` — stop there.
2. **Compare the exact field value** (`system_value`) against what the page
   says. Fill `source_evidence` with a short verbatim excerpt (<= 300 chars),
   `manual_expected_value` with what the source supports, then set
   `review_result`, `error_type` (free text), `severity`, `reviewer`,
   `reviewed_at` (ISO), and `notes`.
3. **Never mark correct because plausible.** "Sounds right" is not evidence.
   If the page does not support the value, it is `unsupported_value` even if
   the value is probably true.
4. **Unknowns presented as certainty are errors.** A value the system knows
   is unknown/inferred but that the UI presents as certain fact is
   `incorrect_value` (or `unsupported_value`), not correct. Conversely, an
   honest `unknown` that matches an absent/ambiguous source is
   `correctly_unknown` — that is a *pass*.
5. **WAF-blocked or dead pages** = `blocked`. Do not evade blocks; note the
   block in `notes`. `stale` = the source changed since collection but the
   collected value was right at the time (pair with `severity: minor` when
   labeled honestly).

`review_result` vocabulary: `verified_correct`, `correctly_unknown`,
`incorrect_value`, `unsupported_value`, `source_mismatch`, `entity_mismatch`,
`conflicting`, `stale`, `blocked` (plus the initial `pending`).

## Pass/fail criteria

- **critical** (release-blocking): wrong entity; a fabricated fact presented
  as confirmed; an eligibility or deadline overclaim; an email attributed to
  the wrong owner; an unverified publication presented as verified. A
  critical blocks approval until the record is fixed **and** the pipeline
  that produced it is reviewed for the same failure class.
- **minor**: stale-but-honestly-labeled values, formatting drift.

The report computes, fail-closed:

- `category_complete` = >= 8 samples and 0 pending;
- `critical_open` = any `severity: critical` sample with a finding-type
  `review_result` (`incorrect_value`, `unsupported_value`, `source_mismatch`,
  `entity_mismatch`, `conflicting`) whose `notes` do not carry the
  `RESOLVED:` prefix;
- `truthfulness_approved` = all 10 categories complete **and** no open
  criticals. A missing category file or any pending row => **NO-GO**.

## Correction loop

1. Fix the producing pipeline (collector/normalizer/enricher), not just the
   sampled record.
2. Regenerate the affected data and re-run `sample --category <cat>` for the
   affected category (fresh draw, same seed policy).
3. Re-review, then mark the original critical `RESOLVED: <what was fixed>` in
   its `notes` (the original verdict stays as the record of the finding).
4. Re-run `report` and re-check the decision.

## Artifacts

| Path | What |
|---|---|
| `data/audits/samples/<category>.json` | per-category sample + reviewer verdicts (seed, gaps recorded) |
| `data/audits/truthfulness_report.json` | aggregate + `truthfulness_approved` + GO/NO-GO decision |
| `docs/truthfulness_audit.md` | Phase-1 code audit the status derivation mirrors |
