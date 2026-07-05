"""Offline feedback-learning v1: analysis aggregation + weight replay."""

from src.matcher.config import LayerWeights
from src.matcher.feedback_learning import (
    MIN_SAMPLE,
    _concordance,
    analyze_votes,
    replay_weights,
)


def _vote(verdict, score=None, bucket=None, opp="opp-1", position=None, components=None):
    v = {"verdict": verdict, "opportunity_id": opp, "bucket": bucket, "final_score": score}
    if position is not None:
        v["context"] = {"position": position}
    if components is not None:
        v["eligibility_score"], v["readiness_score"], v["upside_score"] = components
    return v


class TestAnalyzeVotes:
    def test_under_min_sample_reports_insufficient(self):
        votes = [_vote("up", 80) for _ in range(10)]
        assert analyze_votes(votes, {}) == {"insufficient": True, "needed": 50, "sample_n": 10}

    def test_invalid_verdicts_do_not_count_toward_sample(self):
        votes = [_vote("up", 80) for _ in range(49)] + [_vote("meh", 80)]
        assert analyze_votes(votes, {})["insufficient"] is True

    def test_breakdowns_at_min_sample(self):
        votes = (
            [_vote("up", 85, "high_priority", opp="uiuc-1", position=2) for _ in range(30)]
            + [_vote("down", 45, "reach", opp="uw-1", position=15) for _ in range(20)]
        )
        schools = {"uiuc-1": "uiuc", "uw-1": "uw"}
        a = analyze_votes(votes, schools)

        assert a["sample_n"] == 50
        assert a["up_rate"] == 0.6
        assert {r["key"]: r["up_rate"] for r in a["by_bucket"]} == {"high_priority": 1.0, "reach": 0.0}
        assert {r["key"]: r["n"] for r in a["by_score_band"]} == {"40-60": 20, "80-100": 30}
        assert [r["key"] for r in a["by_score_band"]] == ["40-60", "80-100"]
        assert {r["key"]: r["up_rate"] for r in a["by_school"]} == {"uiuc": 1.0, "uw": 0.0}
        assert {r["key"]: r["n"] for r in a["by_position"]} == {"1-3": 30, "11+": 20}
        assert a["keyword_overlap"]["available"] is False
        assert a["replay"]["mode"] == "score_band_agreement"

    def test_missing_fields_fall_back_to_unknown_buckets(self):
        votes = [_vote("up", None, None, opp="ghost") for _ in range(50)]
        a = analyze_votes(votes, {})
        assert a["by_bucket"] == [{"key": "unknown", "n": 50, "up_rate": 1.0}]
        assert a["by_school"] == [{"key": "unknown", "n": 50, "up_rate": 1.0}]
        assert a["by_score_band"] == [{"key": "unscored", "n": 50, "up_rate": 1.0}]
        assert a["by_position"] == []


class TestConcordance:
    def test_perfect_separation(self):
        assert _concordance([(80, "up"), (90, "up"), (30, "down")]) == 1.0

    def test_ties_count_half(self):
        assert _concordance([(50, "up"), (50, "down")]) == 0.5

    def test_one_sided_is_undefined(self):
        assert _concordance([(80, "up"), (90, "up")]) is None


class TestReplayWeights:
    def test_degrades_without_component_scores(self):
        votes = [_vote("up", 80) for _ in range(40)] + [_vote("down", 40) for _ in range(20)]
        r = replay_weights(votes)
        assert r["mode"] == "score_band_agreement"
        assert r["current_agreement"] == 1.0
        assert r["best_candidate"] is None
        assert r["delta"] is None
        assert r["sample_n"] == 60
        assert "cannot" in r["note"]

    def test_degrades_when_too_few_votes_have_components(self):
        votes = (
            [_vote("up", 80, components=(90, 70, 60)) for _ in range(MIN_SAMPLE - 1)]
            + [_vote("down", 40) for _ in range(30)]
        )
        r = replay_weights(votes)
        assert r["mode"] == "score_band_agreement"
        assert f"only {MIN_SAMPLE - 1}" in r["note"]

    def test_replays_perturbations_and_finds_better_candidate(self):
        # Baseline mis-ranks by a hair (downs edge out ups on the weighted
        # sum), while ups clearly win on upside — a ±20% shift flips it.
        weights = LayerWeights(eligibility=0.45, readiness=0.35, upside=0.20)
        votes = (
            [_vote("up", 53, components=(48, 50, 70)) for _ in range(30)]
            + [_vote("down", 54, components=(55, 50, 55)) for _ in range(30)]
        )
        r = replay_weights(votes, weights=weights)
        assert r["mode"] == "weight_replay"
        assert r["sample_n"] == 60
        assert r["current_agreement"] == 0.0
        assert r["delta"] == 1.0
        assert abs(sum(r["best_candidate"].values()) - 1.0) < 0.001
        assert "never auto-applied" in r["note"]

    def test_replay_one_sided_votes_yield_undefined_agreement(self):
        votes = [_vote("up", 80, components=(80, 70, 60)) for _ in range(60)]
        r = replay_weights(votes)
        assert r["mode"] == "weight_replay"
        assert r["current_agreement"] is None
        assert r["best_candidate"] is None
