# Matching Logic

> **Contract note (2026-09-05):** the authoritative implementation is
> `src/matcher/ranker.py` + the canonical pipeline in
> `backend/routes/matches.py` (`_get_or_compute_snapshot`). This document records
> the default configuration; tunable values live in `src/matcher/config.py`.
> A match score is a review-priority signal, not an admission/reply probability
> or a certification that every eligibility requirement has been checked.

## Overview

The matching engine combines eligibility/field signals, preparation, and
opportunity attributes. These layers overlap in meaning; they are not three
independently verified qualifications.

```
raw   = 0.45 × eligibility + 0.35 × readiness + 0.20 × upside   (+ small additive bonuses)
final = stretch(raw)  × post-stretch multipliers (topic mismatch, passed deadline,
                        grad-level reach, seasonal boost)
```

Weights blend with the user's `search_weight` slider and `exploring` flag
(`_compute_weights`). The E/R/U weights at slider 0, 50, and 100 are respectively
(.40, .25, .35), (.45, .35, .20), and (.40, .45, .15): neither endpoint is pure
interest or pure experience. After additive bonuses, raw is capped at 100 and
stretched as `0.55*x + 45/(1+exp(-0.07*(x-55)))`. Multipliers follow; final scores
are rounded to one decimal, and buckets use that rounded score.

Public Match defaults to deterministic ranking. AI refine is release-gated off;
opening it requires acceptance, an explicit `llm=true` request, and budget.
Its dormant implementation maps the model's scores onto the evaluated rule-score
band before blending (default weight .70, top 20), then re-sorts and re-buckets.
It does not blend uncalibrated model scores directly into the rule score.

## Score 1: Eligibility (weight: 0.45)

**Question:** Can this student reasonably apply?

| Factor | Weight | Logic |
|--------|--------|-------|
| Year match | 28.5% | Known fit 100, adjacent undergraduate year 50, mismatch 0, unknown 40; inferred year lists are unknown |
| Major/field match | 24% | Exact 100, related 70, absent 30; faculty department labels only earn positive fit, not a mismatch penalty |
| International eligibility | 19% | Known friendly 100, restricted 0, unknown 60 (72 for internships); non-international profile defaults to 100 |
| Skill overlap | 14.25% | Required-skill weighted coverage: expert 1, experienced .75, beginner .5; no overlap 10, usually no requirements 35 |
| Opportunity type | 14.25% | Exact 100; research/summer 70, summer/internship 60, research/internship 50; unrelated 30, no preference 60 |

Selected opportunity types are an unordered set. Aliases and duplicates do not
change the score: when no exact type matches, use the strongest applicable
affinity, regardless of the order the student selected the types.

**Hard filters:** target truth excludes closed/reference/inactive/unreviewed
records and faculty explicitly not accepting undergraduates. School scope
excludes other-school campus-only listings and non-summer cross-school records
when cross-school matching is off. Explicit citizenship restrictions exclude an
international student when their exclusion preference is on. A nonpreferred
opportunity type is excluded only when its major list also has no direct
or related match. Year mismatch and a past date alone are soft penalties, not
hard exclusions. GPA is not evaluated; it is surfaced as unknown.

## Score 2: Readiness (weight: 0.35)

**Question:** Is this student ready to apply right now?

| Factor | Weight | Logic |
|--------|--------|-------|
| Resume available | 25% | Ready 100; absent and required 30, otherwise 60 |
| Relevant coursework | 20% | No courses 30; otherwise count score max(30,12×unique courses), capped at 70, plus up to 30 for relevant course signals |
| Prior experience | 20% | strong=100, some=70, beginner=40, none=20 |
| Cold email capability | 15% | 100 if yes, 40 if no (limits outreach options) |
| Application effort | 20% | Low 90, medium/unknown 60, high 30; faculty application requirements are neutralized |

Current browser inputs set resume readiness from the presence of resume text and
set cold-email capability to true. These are not a full-resume quality assessment
or evidence of a student's willingness to contact someone. Skill provenance and
confirmation reach the API but do not yet change numerical skill coverage.

**Key insight:** Readiness is NOT a disqualifier — a low readiness score means "this student would benefit from preparation tips alongside the recommendation."

## Score 3: Upside (weight: 0.20)

**Question:** Is this opportunity worth prioritizing?

| Record | Pay | First experience | Campus | Institution | Mentoring | Pathway | Interest keywords |
|---|---:|---:|---:|---:|---:|---:|---:|
| Faculty contact | 10% | 10% | 10% | 10% | 0% | 0% | 60% |
| Other, with required skills | 15% | 15% | 10% | 10% | 15% | 15% | 20% |
| Other, without required skills | 10% | 10% | 10% | 10% | 15% | 10% | 35% |

Pay yes/stipend/unknown/no scores 100/80/40/25. Explicit first-experience welcome
scores 100, otherwise 40. Campus is 80, at the student's own school 90, otherwise
50. Institution is normally 60, registered school 90, recognized organization
95. Mentoring/pathway use bounded source-text signals. Faculty safety projection
holds pay/first-experience/campus at 40/40/50; directory metadata is not an offer.

Interest keywords start at 25, rise to 75/100 for one/two matched desired fields,
and may be raised by corpus-fitted TF-IDF to `min(100,15+400*cosine)`. Implicit
major keywords provide a capped steer when no explicit interest is given.
Interest text does not establish research experience.

## Recommendation Buckets

Buckets are assigned by **one** algorithm — `_assign_buckets` in
`src/matcher/ranker.py`, applied to the full ranked result set:

- **≥ 10 results (the normal case):** percentile banding with a strict top-N cap.
  `high_priority` = at most the first `HIGH_PRIORITY_TARGET_COUNT` (20) results
  in canonical order that also clear the 70.0 floor. Boundary ties do not expand
  the shortlist: evidence strength, then opportunity id, decide which tied rows
  occupy the remaining places. Other tied rows fall through to `good_match`.
  With zero-based descending score array `s` and positive N, high cutoff is
  `max(70,s[min(N-1,n-1)])`; p70 is `s[floor(.3*n)]` and p40 is `s[floor(.6*n)]`.
  Good cutoff is `min(high,max(62,p70))`, reach is
  `min(good,max(42,p40))`; everything below is `low_fit`.
  This keeps cutoffs ordered even when a small universe puts its percentiles
  above the Nth score. Bands may have equal cutoffs or no members.
  A score of 75 can therefore legitimately land in `good_match` when the
  profile's distribution is strong — the flat table alone is NOT the contract.
- **< 10 results:** flat floors from `BUCKET_THRESHOLDS` — 70.0 / 62.0 / 42.0;
  the same count cap still applies if configured below the result count
  (env-overridable `OFE_BUCKET_HIGH/GOOD/REACH`; an override changes
  `MATCHER_VERSION`, see below).

`low_fit` results are counted but never returned by `/matches`.

For 100 equal scores of 75, exactly 20 are high and 80 are good. Reordering the
source corpus cannot change those 20 ids. Semantic and LLM reranking reapply
the same cap after updating scores; the histogram-based public path sorts its
retained rows canonically before choosing the tied boundary.

Lists and view pagination share a canonical snapshot. The internal explain and
compare implementations read its buckets too; their release gates still control
whether those user-facing features are available.

## Canonical result contract

One canonical conclusion per (profile, opportunity, corpus generation,
matcher version, llm flag). Enforced by the snapshot pipeline in
`backend/routes/matches.py`:

- `POST /matches` and `/matches/view` normally use `rank_visible_universe`, whose
  histogram represents all hard/minimum-filter survivors, including low-fit
  scores. Its retained rows use the same bucket policy as `rank_all`.
  An accepted, requested AI pass uses `rank_all` → bounded rerank → canonical
  re-sort → `_assign_buckets`. Pages and view counts describe that snapshot.
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
| research topic unknown | multiplier 1.0; heuristic absence of meaningful keyword overlap can apply .8 when sufficient explicit interests exist |
| `deadline` missing, invalid, estimated, or inference-stamped | no expiry/urgency conclusion, no deadline penalty, no seasonal boost; traced as `opportunity.deadline` unknown |
| `min_gpa` present on the record | NOT evaluated (the product doesn't collect student GPA) — surfaced as `profile.gpa` in `unknowns` |

`eligibility: null`, `metadata: null`, `application: null`, and null list
fields are treated as absent, never as crashes.

An estimated/inferred date can remain source context, but its next step says to
verify the deadline rather than to apply by that date. A valid, non-inferred past
listing deadline still receives the existing .7 penalty and verification gap;
an explicit closed status still excludes the record. Future stated dates retain
the existing near-deadline reason and seasonal lift. Metadata `expires_at` is not
currently an automatic expiry gate; this patch does not introduce a new TTL policy.

## Ordering & pagination

- Canonical order (every sorted surface): `(-final_score, -evidence_rank,
  opportunity_id)` — `canonical_sort_key` in the ranker. The unique id
  tie-break makes it a total order; both rerank paths re-sort with the same key.
  Evidence rank is 2 for bound email, 1 for a legacy email/nonempty application
  URL, and 0 for no actionable channel. This is not a live URL or mailbox check.
  Explore mode subsequently interleaves within buckets, preserving membership
  while deliberately relaxing global descending score order.
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
- At your university; verify the actual employment and funding requirements

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
