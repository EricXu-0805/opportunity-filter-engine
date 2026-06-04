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

COURSEWORK_PER_COURSE = _env_float("OFE_COURSE_PER", 12.0)
COURSEWORK_MAX_FROM_COUNT = _env_float("OFE_COURSE_MAX_COUNT", 70.0)
COURSEWORK_RELEVANCE_BONUS = _env_float("OFE_COURSE_RELEVANCE", 30.0)

INTEREST_BONUS_CAP = _env_float("OFE_INTEREST_BONUS_CAP", 8.0)
INTEREST_BONUS_PER_HIT = _env_float("OFE_INTEREST_BONUS_PER_HIT", 3.0)

DEADLINE_PASSED_PENALTY = _env_float("OFE_DEADLINE_PENALTY", 0.7)

GRAD_LEVEL_PENALTY = _env_float("OFE_GRAD_LEVEL_PENALTY", 0.5)

# Research-topic alignment: when a student names specific research interests,
# a research posting whose curated areas *contradict* them is demoted. "Unknown"
# (we have no specific area for the lab — true for ~73% of faculty rows that
# carry only a broad department field) defaults to a no-op 1.0: a missing
# enrichment is a data gap, not evidence of poor fit, so penalizing it would
# systematically steer research-seekers away from research. Only a *confirmed*
# mismatch (the lab has specific keywords, none align) is penalized.
TOPIC_UNKNOWN_PENALTY = _env_float("OFE_TOPIC_UNKNOWN_PEN", 1.0)
TOPIC_MISMATCH_PENALTY = _env_float("OFE_TOPIC_MISMATCH_PEN", 0.80)

STRETCH_SIGMOID_K = _env_float("OFE_STRETCH_K", 0.07)
STRETCH_MIDPOINT = _env_float("OFE_STRETCH_MID", 55.0)
STRETCH_BLEND = _env_float("OFE_STRETCH_BLEND", 0.45)

SEMANTIC_RERANK_TOPK = int(_env_float("OFE_SEMANTIC_TOPK", 200))
SEMANTIC_RERANK_WEIGHT = _env_float("OFE_SEMANTIC_W", 0.5)
SEMANTIC_RERANK_FALLBACK_CAP = _env_float("OFE_SEMANTIC_FALLBACK_CAP", 0.2)

# Upside keyword_score maps a raw similarity via 15 + sim * SCALE. The base
# upside layer is corpus-fitted TF-IDF, whose cosines top out ~0.16, so it needs
# a large multiplier to reach usable scores. (Embeddings power semantic_rerank,
# which blends cosine*100 directly and does not use this scale.)
SIMILARITY_SCALE_TFIDF = _env_float("OFE_SIM_SCALE_TFIDF", 400.0)
