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
    (_env_float("OFE_BUCKET_HIGH", 78.0), "high_priority"),
    (_env_float("OFE_BUCKET_GOOD", 62.0), "good_match"),
    (_env_float("OFE_BUCKET_REACH", 42.0), "reach"),
    (0.0, "low_fit"),
)

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

MAJOR_PENALTY_HARD = _env_float("OFE_MAJOR_PEN_HARD", 0.75)
MAJOR_PENALTY_SOFT = _env_float("OFE_MAJOR_PEN_SOFT", 0.88)
MAJOR_PENALTY_HARD_AT = _env_float("OFE_MAJOR_PEN_HARD_AT", 10.0)
MAJOR_PENALTY_SOFT_AT = _env_float("OFE_MAJOR_PEN_SOFT_AT", 20.0)

STRETCH_SIGMOID_K = _env_float("OFE_STRETCH_K", 0.07)
STRETCH_MIDPOINT = _env_float("OFE_STRETCH_MID", 55.0)
STRETCH_BLEND = _env_float("OFE_STRETCH_BLEND", 0.45)

SEMANTIC_RERANK_TOPK = int(_env_float("OFE_SEMANTIC_TOPK", 200))
SEMANTIC_RERANK_WEIGHT = _env_float("OFE_SEMANTIC_W", 0.5)
SEMANTIC_RERANK_FALLBACK_CAP = _env_float("OFE_SEMANTIC_FALLBACK_CAP", 0.2)
