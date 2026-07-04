"""Tunable knobs for the matching algorithm.

Centralized so they can be A/B tested or overridden via env without
touching `ranker.py`. Any value here that gets re-tuned should be
captured in a CHANGELOG entry along with offline-eval delta numbers
once we add the eval harness.

Convention: 0-100 scoring everywhere; 0.0-1.0 only for layer weights.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class LayerWeights:
    eligibility: float
    readiness: float
    upside: float


WEIGHTS_DEFAULT = LayerWeights(
    eligibility=_env_float("OFE_W_ELIG", 0.45),
    readiness=_env_float("OFE_W_READY", 0.35),
    upside=_env_float("OFE_W_UPSIDE", 0.20),
)

BUCKET_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (_env_float("OFE_BUCKET_HIGH", 70.0), "high_priority"),
    (_env_float("OFE_BUCKET_GOOD", 62.0), "good_match"),
    (_env_float("OFE_BUCKET_REACH", 42.0), "reach"),
    (0.0, "low_fit"),
)

# high_priority is a focused "apply to these now" shortlist: the top N results
# that ALSO clear OFE_BUCKET_HIGH. A flat absolute floor alone produced wildly
# uneven counts (5 for one profile, 80 for another) because score distributions
# differ per profile; capping at a target count normalizes it while the floor
# keeps the bucket from promoting weak matches on sparse queries (RANK-6).
HIGH_PRIORITY_TARGET_COUNT = int(_env_float("OFE_HIGH_PRIORITY_TARGET", 20))

PROFICIENCY_WEIGHTS: dict[str, float] = {
    "expert": 1.0,
    "experienced": 0.75,
    "beginner": 0.5,
}

INTL_UNKNOWN_SCORE = _env_float("OFE_INTL_UNKNOWN", 60.0)
# Internships whose sponsorship field is blank still mostly allow CPT/OPT, so a
# flat 60 over-deters F-1 students from their primary audience. Score "unknown"
# internships higher than research/other postings — verify-don't-rule-out.
INTL_UNKNOWN_INTERNSHIP_SCORE = _env_float("OFE_INTL_UNKNOWN_INTERNSHIP", 72.0)

COURSEWORK_PER_COURSE = _env_float("OFE_COURSE_PER", 12.0)
COURSEWORK_MAX_FROM_COUNT = _env_float("OFE_COURSE_MAX_COUNT", 70.0)
COURSEWORK_RELEVANCE_BONUS = _env_float("OFE_COURSE_RELEVANCE", 30.0)

INTEREST_BONUS_CAP = _env_float("OFE_INTEREST_BONUS_CAP", 8.0)
INTEREST_BONUS_PER_HIT = _env_float("OFE_INTEREST_BONUS_PER_HIT", 3.0)

DEADLINE_PASSED_PENALTY = _env_float("OFE_DEADLINE_PENALTY", 0.7)

GRAD_LEVEL_PENALTY = _env_float("OFE_GRAD_LEVEL_PENALTY", 0.65)

# Research-topic alignment: when a student names specific research interests,
# a research posting whose curated areas *contradict* them is demoted. "Unknown"
# (we have no specific area for the lab — true for ~73% of faculty rows that
# carry only a broad department field) defaults to a no-op 1.0: a missing
# enrichment is a data gap, not evidence of poor fit, so penalizing it would
# systematically steer research-seekers away from research. Only a *confirmed*
# mismatch (the lab has specific keywords, none align) is penalized.
TOPIC_UNKNOWN_PENALTY = _env_float("OFE_TOPIC_UNKNOWN_PEN", 1.0)
TOPIC_MISMATCH_PENALTY = _env_float("OFE_TOPIC_MISMATCH_PEN", 0.80)

# "I'm still exploring" mode (profile.exploring=True): a student who hasn't
# settled on a direction. The matcher then WIDENS rather than narrows —
#   * cross/same-domain major mismatches lift to a single floor (a "wrong" major
#     is breadth, not poor fit),
#   * the topic-alignment penalty is suppressed (don't steer an explorer away
#     from areas they haven't ruled out),
#   * readiness (resume/skills) is de-emphasized (early-stage students shouldn't
#     rank on application-readiness),
#   * the top buckets are diversity-sampled so the explorer sees breadth across
#     research areas / opportunity types instead of one lab cluster.
EXPLORE_MAJOR_MISMATCH_FLOOR = _env_float("OFE_EXPLORE_MAJOR_FLOOR", 25.0)
EXPLORE_READINESS_DROP = _env_float("OFE_EXPLORE_READINESS_DROP", 0.10)

STRETCH_SIGMOID_K = _env_float("OFE_STRETCH_K", 0.07)
STRETCH_MIDPOINT = _env_float("OFE_STRETCH_MID", 55.0)
STRETCH_BLEND = _env_float("OFE_STRETCH_BLEND", 0.45)

SEMANTIC_RERANK_TOPK = int(_env_float("OFE_SEMANTIC_TOPK", 200))
SEMANTIC_RERANK_WEIGHT = _env_float("OFE_SEMANTIC_W", 0.5)
SEMANTIC_RERANK_FALLBACK_CAP = _env_float("OFE_SEMANTIC_FALLBACK_CAP", 0.2)

# Seasonal boost: summer research / REU postings are most actionable in the
# spring-into-summer window when their cycles are open, so they get a small
# multiplicative lift during those months. Applied AFTER the stretch transform
# (like the deadline/grad multipliers) and gated to opportunity_type
# 'summer_program' so it never perturbs the score of a non-seasonal posting.
# Months are 1-12; default Feb-July covers the apply-now-for-summer window.
SEASONAL_BOOST_ENABLED = os.environ.get("OFE_SEASONAL_BOOST", "1") not in ("0", "false", "False")
SEASONAL_BOOST_FACTOR = _env_float("OFE_SEASONAL_FACTOR", 1.10)
SEASONAL_BOOST_MONTHS: frozenset[int] = frozenset(
    int(m) for m in os.environ.get("OFE_SEASONAL_MONTHS", "2,3,4,5,6,7").split(",") if m.strip()
)

# Upside keyword_score maps a raw similarity via 15 + sim * SCALE. The base
# upside layer is corpus-fitted TF-IDF, whose cosines top out ~0.16, so it needs
# a large multiplier to reach usable scores. (Embeddings power semantic_rerank,
# which blends cosine*100 directly and does not use this scale.)
SIMILARITY_SCALE_TFIDF = _env_float("OFE_SIM_SCALE_TFIDF", 400.0)

# Major→topic implicit keyword bridge. A student who hasn't written explicit
# research interests still steers ranking through field-typical keywords derived
# from their major. CAPPED well below an explicit-interest match (which reaches
# 75-100 in keyword_score) so the implicit signal only reorders the 25.0 baseline
# tier — it can never outrank a real stated interest. This is the numeric
# "explicit interests LEAD, major DRIVES" guarantee.
IMPLICIT_MAJOR_KEYWORD_CEILING = _env_float("OFE_IMPLICIT_MAJOR_CEIL", 55.0)
IMPLICIT_MAJOR_PER_HIT = _env_float("OFE_IMPLICIT_MAJOR_PER_HIT", 10.0)

# Major's share of the eligibility layer. Raised from the original 0.20 so the
# student's major actually steers ranking (it was too weak to reorder), but kept
# moderate so it MODULATES rather than OVERRIDES an explicit stated interest — a
# vet major who writes "computer vision" must still see CV work near the top.
# The remaining (1 - this) is split across year/intl/skill/type in the original
# 30:20:15:15 proportion, so the eligibility layer always sums to 1.0.
ELIG_MAJOR_WEIGHT = _env_float("OFE_ELIG_MAJOR_W", 0.24)

# College→department affinity: a small additive nudge (pre-stretch, like the
# interest bonus) when the opportunity's department matches the student's college.
# Strictly below INTEREST_BONUS_CAP (8.0) so college stays a tiebreaker, not a
# driver. Missing department → no bonus, never a penalty.
COLLEGE_AFFINITY_MAX = _env_float("OFE_COLLEGE_AFFINITY_MAX", 4.0)

# Home-school priority: when the cross-school toggle (include_cross_school) is
# on, the student's own school gets a small additive nudge (pre-stretch, like
# the college affinity) so 本校 wins ties against an equally-scored cross-school
# record — but stays far too small to outrank a clearly better topical match
# elsewhere (interests LEAD is the product law).
HOME_SCHOOL_AFFINITY_MAX = _env_float("OFE_HOME_SCHOOL_AFFINITY_MAX", 4.0)

# Thin-inventory honesty: when a profile has fewer than this many topically
# relevant visible results, the client shows "few matches in your field" instead
# of implying the padded generic total is all field-relevant.
THIN_INVENTORY_FLOOR = int(_env_float("OFE_THIN_INVENTORY_FLOOR", 8))
