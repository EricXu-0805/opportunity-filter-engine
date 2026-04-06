# Matching Logic

## Overview

The matching engine evaluates every opportunity against a student profile using three independent scores, then combines them into a final ranking.

```
final_score = 0.45 × eligibility + 0.35 × readiness + 0.20 × upside
```

Each score ranges from 0 to 100. The final score determines the recommendation bucket.

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

| Bucket | Score range | Display label | Color |
|--------|------------|---------------|-------|
| High Priority | ≥ 75 | **Best Matches Now** | 🟢 Green |
| Good Match | 60-74 | **Good Match** | 🔵 Blue |
| Reach | 40-59 | **Worth Stretching For** | 🟡 Yellow |
| Low Fit | < 40 | Not shown by default | 🔴 (hidden) |

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
  ├─ Step 6: Bucket assignment
  │   High Priority / Good Match / Reach / Low Fit
  │
  ├─ Step 7: Sort within buckets
  │   By score descending, then by deadline ascending
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
