"""Offline feedback-learning v1 (docs/FEEDBACK_LEARNING.md).

Pure read-only aggregation + replay over match_feedback votes. Migration 012
stores verdict/bucket/final_score per vote (018 adds context.position);
per-vote component scores are NOT stored, so weight replay degrades honestly
to score-vs-verdict agreement until they are. Never writes weights.
"""

from __future__ import annotations

from itertools import product

from src.matcher.config import WEIGHTS_DEFAULT, LayerWeights

MIN_SAMPLE = 50

_SCORE_BAND_LABELS = ("0-20", "20-40", "40-60", "60-80", "80-100", "unscored")
_POSITION_BAND_LABELS = ("1-3", "4-10", "11+")
_COMPONENT_KEYS = ("eligibility_score", "readiness_score", "upside_score")


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_band(score: float | None) -> str:
    if score is None:
        return "unscored"
    for upper, label in ((20, "0-20"), (40, "20-40"), (60, "40-60"), (80, "60-80")):
        if score < upper:
            return label
    return "80-100"


def _position_band(position: float) -> str:
    if position <= 3:
        return "1-3"
    if position <= 10:
        return "4-10"
    return "11+"


def _rate_rows(groups: dict[str, list[str]], order: tuple[str, ...] | None = None) -> list[dict]:
    rows = [
        {"key": key, "n": len(verdicts), "up_rate": round(sum(1 for v in verdicts if v == "up") / len(verdicts), 3)}
        for key, verdicts in groups.items()
    ]
    if order:
        rows.sort(key=lambda r: order.index(r["key"]))
    else:
        rows.sort(key=lambda r: r["n"], reverse=True)
    return rows


def analyze_votes(votes: list[dict], school_by_id: dict) -> dict:
    """Analysis block for the admin feedback endpoint.

    Breakdowns are limited to what is actually captured per vote: bucket,
    final_score, opportunity_id (joined to school here), and — for votes
    written after migration 018 — context.position. Keyword-overlap is not
    captured, which the block states instead of inventing it.
    """
    votes = [v for v in votes if v.get("verdict") in ("up", "down")]
    n = len(votes)
    if n < MIN_SAMPLE:
        return {"insufficient": True, "needed": MIN_SAMPLE, "sample_n": n}

    by_bucket: dict[str, list[str]] = {}
    by_school: dict[str, list[str]] = {}
    by_band: dict[str, list[str]] = {}
    by_position: dict[str, list[str]] = {}
    for v in votes:
        verdict = v["verdict"]
        by_bucket.setdefault(v.get("bucket") or "unknown", []).append(verdict)
        by_school.setdefault(school_by_id.get(v.get("opportunity_id")) or "unknown", []).append(verdict)
        by_band.setdefault(_score_band(_num(v.get("final_score"))), []).append(verdict)
        context = v.get("context") if isinstance(v.get("context"), dict) else {}
        position = _num(context.get("position"))
        if position is not None:
            by_position.setdefault(_position_band(position), []).append(verdict)

    return {
        "sample_n": n,
        "up_rate": round(sum(1 for v in votes if v["verdict"] == "up") / n, 3),
        "by_bucket": _rate_rows(by_bucket),
        "by_score_band": _rate_rows(by_band, order=_SCORE_BAND_LABELS),
        "by_school": _rate_rows(by_school),
        "by_position": _rate_rows(by_position, order=_POSITION_BAND_LABELS),
        "keyword_overlap": {
            "available": False,
            "reason": "not captured per vote — migration 012 stores verdict/bucket/final_score only",
        },
        "replay": replay_weights(votes),
    }


def _concordance(pairs: list[tuple[float, str]]) -> float | None:
    """Fraction of (up, down) vote pairs where the up-voted score is higher
    (ties count half) — threshold-free ranking agreement, i.e. AUC. None when
    votes are one-sided."""
    ups = [score for score, verdict in pairs if verdict == "up"]
    downs = [score for score, verdict in pairs if verdict == "down"]
    if not ups or not downs:
        return None
    wins = sum(1.0 if u > d else 0.5 if u == d else 0.0 for u in ups for d in downs)
    return round(wins / (len(ups) * len(downs)), 3)


def _normalized(w: tuple[float, float, float]) -> tuple[float, float, float]:
    total = sum(w)
    return (round(w[0] / total, 4), round(w[1] / total, 4), round(w[2] / total, 4))


def replay_weights(votes: list[dict], weights: LayerWeights = WEIGHTS_DEFAULT) -> dict:
    """Evaluate ±20% ELIG/READINESS/UPSIDE perturbations against thumb
    agreement. Requires per-vote component scores to re-rank; without them
    (all production votes today) degrades to agreement on the stored
    final_score and says so. Pure function — NEVER writes weights."""
    scored = [
        v for v in votes
        if v.get("verdict") in ("up", "down") and _num(v.get("final_score")) is not None
    ]
    replayable = [
        (tuple(_num(v[k]) for k in _COMPONENT_KEYS), v["verdict"])
        for v in scored
        if all(_num(v.get(k)) is not None for k in _COMPONENT_KEYS)
    ]

    if len(replayable) < MIN_SAMPLE:
        return {
            "mode": "score_band_agreement",
            "current_agreement": _concordance([(_num(v["final_score"]), v["verdict"]) for v in scored]),
            "best_candidate": None,
            "delta": None,
            "sample_n": len(scored),
            "note": (
                f"only {len(replayable)}/{len(scored)} votes carry component scores (need {MIN_SAMPLE}); "
                "migration 012 stores verdict/bucket/final_score only, so ±20% weight perturbations cannot "
                "be re-ranked — agreement shown is up-vs-down concordance on the stored final_score"
            ),
        }

    def agreement_for(w: tuple[float, float, float]) -> float | None:
        return _concordance([(w[0] * e + w[1] * r + w[2] * u, verdict) for (e, r, u), verdict in replayable])

    base = (weights.eligibility, weights.readiness, weights.upside)
    current = agreement_for(base)
    if current is None:
        return {
            "mode": "weight_replay",
            "current_agreement": None,
            "best_candidate": None,
            "delta": None,
            "sample_n": len(replayable),
            "note": "votes are one-sided (all up or all down) — pairwise agreement is undefined",
        }

    seen = {_normalized(base)}
    best_w: tuple[float, float, float] | None = None
    best_a = None
    for fe, fr, fu in product((0.8, 1.0, 1.2), repeat=3):
        candidate = _normalized((base[0] * fe, base[1] * fr, base[2] * fu))
        if candidate in seen:
            continue
        seen.add(candidate)
        agreement = agreement_for(candidate)
        if best_a is None or agreement > best_a:
            best_w, best_a = candidate, agreement
    return {
        "mode": "weight_replay",
        "current_agreement": current,
        "best_candidate": {"eligibility": best_w[0], "readiness": best_w[1], "upside": best_w[2]},
        "delta": round(best_a - current, 3),
        "sample_n": len(replayable),
        "note": "offline replay only — weights are never auto-applied",
    }
