# Matching Logic

> **Contract note (2026-07):** the authoritative implementation is
> `src/matcher/ranker.py` + the canonical pipeline in
> `backend/routes/matches.py` (`_get_or_compute_snapshot`). The factor tables
> below are the original design sketch and describe intent, not the exact
> shipped weights — those live in `src/matcher/config.py`. The sections
> **Recommendation Buckets**, **Canonical result contract**, **Unknown
> semantics**, and **Ordering & pagination** below ARE the shipped contract.

## Overview

The matching engine evaluates every opportunity against a student profile using three independent scores, then combines them into a final ranking.

```
raw   = 0.45 × eligibility + 0.35 × readiness + 0.20 × upside   (+ small additive bonuses)
final = stretch(raw)  × post-stretch multipliers (topic mismatch, passed deadline,
                        grad-level reach, seasonal boost)
```

Weights blend with the user's `search_weight` slider and `exploring` flag
(`_compute_weights`), pass through a sigmoid "stretch" that widens the
distribution, and — on the list path — blend with the LLM rerank at weight
`LLM_RERANK_WEIGHT` (default 0.35) for the top `LLM_RERANK_TOPK` results.
Each score ranges from 0 to 100.

## Score 1: Eligibility (weight: 0.45)

**Question:** Can this student reasonably apply?

| Factor | Weight | Logic |
|--------|--------|-------|
| Year match | 30% | 100 if meets requirement, 50 if one year off, 0 if two+ |
| Major/field match | 25% | Exact match = 100, related = 70, unrelated = 20 |
| International eligibility | 25% | 100 if friendly, 0 if requires citizenship, 50 if unknown |
| Skill overlap | 20% | (matched_skills / required_skills) × 100 |

**Hard filters (instant disqualify):**
- `international_friendly = "no"` AND `student.international = true` → skip
- `preferred_year` doesn't include student's year AND is explicit → skip
- Deadline has passed → skip

## Score 2: Readiness (weight: 0.35)

**Question:** Is this student ready to apply right now?

| Factor | Weight | Logic |
|--------|--------|-------|
| Resume available | 25% | 100 if ready, 30 if not (can still cold email) |
| Relevant coursework | 20% | Count matching courses / expected courses |
| Prior experience | 20% | strong=100, some=70, beginner=40, none=20 |
| Cold email capability | 15% | 100 if yes, 40 if no (limits outreach options) |
| Application effort vs. readiness | 20% | Low effort + low readiness = still feasible |

**Key insight:** Readiness is NOT a disqualifier — a low readiness score means "this student would benefit from preparation tips alongside the recommendation."

## Score 3: Upside (weight: 0.20)

**Question:** Is this opportunity worth prioritizing?

| Factor | Weight | Logic |
|--------|--------|-------|
| Paid compensation | 20% | paid=100, stipend=70, unpaid=30 |
| First-experience friendly | 25% | Explicitly accepts beginners = 100 |
| Mentorship signal | 15% | Mentions mentoring, training, learning = higher |
| Brand/prestige value | 15% | Top-tier lab, known program, federal agency = higher |
| Future pathway potential | 15% | Return offers, publication potential, reference letters |
| On-campus convenience | 10% | On-campus = 80 for freshmen, remote = 60 |

## Recommendation Buckets

Buckets are assigned by **one** algorithm — `_assign_buckets` in
`src/matcher/ranker.py`, applied to the full ranked result set:

- **≥ 10 results (the normal case):** percentile banding with a top-N cap.
  `high_priority` = the top `HIGH_PRIORITY_TARGET_COUNT` (20) results that also
  clear the 70.0 floor; `good_match` down to max(62.0, p70 score);
  `reach` down to max(42.0, p40 score); everything else `low_fit`.
  A score of 75 can therefore legitimately land in `good_match` when the
  profile's distribution is strong — the flat table alone is NOT the contract.
- **< 10 results:** flat floors from `BUCKET_THRESHOLDS` — 70.0 / 62.0 / 42.0
  (env-overridable `OFE_BUCKET_HIGH/GOOD/REACH`; an override changes
  `MATCHER_VERSION`, see below).

`low_fit` results are counted but never returned by `/matches`.

Every surface (results list, pagination pages, the per-card explain modal, the
compare page) reads the bucket from the same canonical snapshot — no surface
recomputes it with the flat floors independently.

## Canonical result contract

One canonical conclusion per (profile, opportunity, corpus generation,
matcher version, llm flag). Enforced by the snapshot pipeline in
`backend/routes/matches.py`:

- `POST /matches` computes a snapshot: `rank_all` → LLM rerank blend →
  canonical re-sort → `_assign_buckets` → bucket counts. Pages are slices of
  that snapshot.
- `POST /matches/{id}/explain` reads the SAME snapshot entry — identical
  `final_score`, `bucket`, `reasons_*`, `unknowns`. An opportunity the list
  excluded returns `in_results: false` + a reason-coded `excluded_reason`
  (from the shared `hard_exclusion` filter) and an informational standalone
  score, with the exclusion stated as the first gap reason.
- Result fields: `opportunity_id, eligibility/readiness/upside/final_score,
  bucket, reasons_fit, reasons_gap, next_steps, ai_reason, unknowns`; the
  response carries `matcher_version` and the count invariant
  `total == high_priority + good_match + reach` (the pageable universe).

**Matcher versioning:** `src/matcher/config.py::MATCHER_VERSION` =
hand-bumped base + a fingerprint hash over every tunable (weights, bucket
thresholds, penalties, LLM rerank model/weight …), so env-knob drift changes
the served version automatically. It participates in the server snapshot key,
the explain-prose cache key, and the frontend's localStorage/sessionStorage
match caches — two matcher generations can never render together.

## Unknown semantics (canonical policy)

Missing/unknown data is scored with a documented NEUTRAL value — never
silently converted to eligible or ineligible — and traced in `unknowns`:

| Input unknown/missing | Policy |
|---|---|
| student `year` | neutral 40 (year layer) + "add your class year" gap |
| opportunity `preferred_year` empty/`unknown` | neutral 40, no fabricated targeting gap |
| opportunity `majors` empty (open posting) | 30, and NO "Prefers …" gap |
| `international_friendly` unknown (F-1 student) | verify-don't-rule-out: 60 (72 for internships) + verify reason; never a hard exclusion unless `citizenship_required` is explicit |
| `paid` null / missing / unrecognized | all collapse to `unknown` → 40; UI renders "Not disclosed", never "Unpaid" |
| research topic unknown | multiplier 1.0 (a data gap is not evidence of poor fit); only a confirmed mismatch is penalized |
| `deadline` missing | no penalty, no seasonal boost |
| `min_gpa` present on the record | NOT evaluated (the product doesn't collect student GPA) — surfaced as `profile.gpa` in `unknowns` |

`eligibility: null`, `metadata: null`, `application: null`, and null list
fields are treated as absent, never as crashes.

## Ordering & pagination

- Canonical order (every sorted surface): `(-final_score, not actionable,
  opportunity_id)` — `canonical_sort_key` in the ranker. The unique id
  tie-break makes it a total order; the LLM rerank re-sorts with the same key.
- `/matches` pages slice one snapshot → repeated/overlapping page requests
  within the snapshot TTL are duplicate-free and omission-free by
  construction.
- The corpus itself is deduplicated by id (first occurrence wins) and
  id-sorted at load (`backend/data_loader._canonicalize_corpus`), so
  `/opportunities` offset paging is deterministic across refreshes;
  `/opportunities/upcoming` sorts `(deadline, id)`; `/similar` sorts
  `(-similarity, id)`.
- Inactive records are excluded from every discovery surface (`/matches`,
  `/opportunities`, `/upcoming`, `/similar`, `/coverage`); direct id fetch and
  `/batch` still resolve them so saved links keep working.

## Explanation Generation

Every recommendation must include:

```markdown
## Undergraduate Research Assistant – Data Systems Lab
**Match Score: 83/100** 🟢 Best Match

### Why it fits
- Accepts undergraduate students including freshmen
- Python and data analysis align with your skills
- On-campus position — no work authorization concerns

### Potential gaps
- No prior research experience on your profile
- Resume may need a research-focused version

### Recommended next steps
1. Apply within 3 days (deadline: April 15)
2. Prepare a one-page research resume highlighting projects
3. Send a brief cold email to Prof. Smith expressing interest

### Application effort: Medium
```

**V1 implementation:** Template-based string generation using rule outputs.

**V2 upgrade:** LLM-generated explanations using profile + opportunity as context.

## Matching Pipeline

```
Input: (student_profile, list[opportunity])
  │
  ├─ Step 1: Pre-filter
  │   Remove expired, citizenship-blocked, wrong type
  │
  ├─ Step 2: Eligibility scoring
  │   For each remaining opportunity
  │
  ├─ Step 3: Readiness scoring
  │   For each remaining opportunity
  │
  ├─ Step 4: Upside scoring
  │   For each remaining opportunity
  │
  ├─ Step 5: Combine scores
  │   final = 0.45*elig + 0.35*ready + 0.20*upside
  │
  ├─ Step 6: Canonical sort
  │   (-final_score, not actionable, opportunity_id) — total order
  │
  ├─ Step 7: Bucket assignment (_assign_buckets, percentile + top-N cap)
  │   High Priority / Good Match / Reach / Low Fit
  │
  └─ Step 8: Generate explanations
      Template-based (V1) or LLM-based (V2)

Output: ranked list with scores, buckets, and explanations
```

## Weight Tuning

V1 weights are starting values. After testing with 3-5 real profiles, adjust based on:

- Do "High Priority" results feel obviously right?
- Are "Reach" results aspirational but not delusional?
- Are international eligibility issues correctly surfaced?

Log all profile → result mappings to build a feedback dataset for future tuning.
