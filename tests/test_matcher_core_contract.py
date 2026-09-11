"""Regressions for the accepted, bounded Profile -> deterministic Match fixes.

Synthetic records only. Provider calls in reranking tests are replaced at their
boundary; the release gates and the production scoring weights are unchanged.
"""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, timedelta
from itertools import permutations

import pytest

from src.matcher import ranker

RELEASE_CONTRACT_TESTS = True


def _profile(**overrides):
    return {
        "year": "sophomore", "major": "CS", "home_school": "uiuc",
        "seeking_type": ["research", "summer_program"],
        "hard_skills": [{"name": "Python", "level": "experienced"}],
        "resume_ready": True, "experience_level": "some", "can_cold_email": True,
        "preferences": {"min_match_threshold": 0},
        **overrides,
    }


def _opp(ident="listing", **overrides):
    return {
        "id": ident, "source_type": "campus_program", "school": "uiuc",
        "title": "Computer vision research", "opportunity_type": "research",
        "keywords": ["computer vision"], "paid": "yes", "on_campus": True,
        "eligibility": {"preferred_year": ["sophomore"], "majors": ["CS"],
                        "skills_required": ["Python"], "international_friendly": "yes"},
        "application": {"contact_method": "portal", "application_effort": "medium",
                        "application_url": "https://example.edu/apply"},
        "metadata": {"is_active": True},
        **overrides,
    }


def _result(ident, score, evidence=1):
    return ranker.MatchResult(
        opportunity_id=ident, eligibility_score=score, readiness_score=score,
        upside_score=score, final_score=score, bucket="low_fit",
        reasons_fit=[], reasons_gap=[], next_steps=[], evidence_rank=evidence,
    )


class TestDeadlineEvidenceControlsEveryScoringClaim:
    @pytest.fixture(autouse=True)
    def _clock(self, monkeypatch):
        class FixedDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 3, 1)

        monkeypatch.setattr(ranker, "date", FixedDate)

    @pytest.mark.parametrize("marker", ["estimate_flag", "inferred_stamp", "both"])
    @pytest.mark.parametrize("days", [-30, 3, 30])
    def test_estimates_never_become_expiry_urgency_or_in_season_claims(self, marker, days):
        dateless = _opp(opportunity_type="summer_program")
        derived = deepcopy(dateless)
        derived["deadline"] = (ranker.date.today() + timedelta(days=days)).isoformat()
        if marker in {"estimate_flag", "both"}:
            derived["deadline_is_estimate"] = True
        if marker in {"inferred_stamp", "both"}:
            derived["metadata"]["inferred_fields"] = {"deadline": "estimate:award_start_date"}

        baseline = ranker.rank_opportunity(_profile(), dateless, today=ranker.date.today())
        result = ranker.rank_opportunity(_profile(), derived, today=ranker.date.today())
        assert result.final_score == baseline.final_score
        assert result.reasons_fit == baseline.reasons_fit
        assert result.reasons_gap == baseline.reasons_gap
        assert "opportunity.deadline" in result.unknowns
        assert "Verify the application deadline on the source page" in result.next_steps
        assert not any(step.startswith("Apply before deadline:") for step in result.next_steps)
        assert ranker._seasonal_multiplier(derived, today=ranker.date.today()) == 1.0

    def test_stated_past_deadline_still_penalizes_and_explains_without_hard_exclusion(self):
        dateless = _opp()
        expired = _opp(deadline="2026-02-01T12:00:00Z")
        base = ranker.rank_opportunity(_profile(), dateless)
        result = ranker.rank_opportunity(_profile(), expired)
        assert result.final_score == pytest.approx(base.final_score * 0.7, abs=0.1)
        assert any("Deadline has passed" in gap for gap in result.reasons_gap)
        assert "opportunity.deadline" not in result.unknowns
        assert ranker.hard_exclusion(expired, ranker._filter_context(_profile())) is None

    def test_stated_future_deadline_keeps_urgency_and_seasonal_lift(self):
        listing = _opp(opportunity_type="summer_program", deadline="2026-03-04T12:00:00Z")
        result = ranker.rank_opportunity(_profile(), listing, today=ranker.date.today())
        assert any("Deadline in 3 days" in reason for reason in result.reasons_fit)
        assert any("Summer research — in season" in reason for reason in result.reasons_fit)
        assert "opportunity.deadline" not in result.unknowns


class TestSeekingTypesAreAnUnorderedPreferenceSet:
    @pytest.mark.parametrize("opportunity_type, expected", [
        ("internship", 60.0), ("research", 100.0), ("summer_program", 100.0), ("volunteer", 30.0),
    ])
    def test_order_aliases_and_duplicates_do_not_change_affinity(self, opportunity_type, expected):
        for values in permutations(["Research", "Summer program", "research"]):
            assert ranker._type_preference_score(list(values), opportunity_type) == expected

    def test_empty_or_blank_preferences_keep_the_neutral_prior(self):
        assert ranker._type_preference_score([], "internship") == 60.0
        assert ranker._type_preference_score(["", "  "], "internship") == 60.0

    def test_the_complete_ranked_conclusion_survives_reordering(self):
        corpus = [_opp("research"), _opp("internship", opportunity_type="internship")]
        left = ranker.rank_all(_profile(seeking_type=["research", "summer_program"]), corpus)
        right = ranker.rank_all(_profile(seeking_type=["summer_program", "research", "research"]), corpus)
        assert [asdict(row) for row in left] == [asdict(row) for row in right]


class TestHighPriorityIsAStrictStableShortlist:
    @pytest.mark.parametrize("count", [0, 1, 9, 10, 19, 20, 21, 100])
    def test_equal_scores_cannot_overflow_the_twenty_places(self, count):
        rows = [_result(f"row-{i:03}", 75.0) for i in range(count)]
        ranker._assign_buckets(rows)
        assert [r.opportunity_id for r in rows if r.bucket == "high_priority"] == [
            f"row-{i:03}" for i in range(min(count, 20))
        ]
        assert all(row.bucket == "good_match" for row in rows[20:])

    def test_twentieth_boundary_uses_evidence_then_id_not_input_order(self, monkeypatch):
        rows = [_result(f"strong-{i:02}", 90.0) for i in range(19)] + [
            _result("a-legacy", 80.0, 1),
            _result("z-bound", 80.0, 2),
            _result("b-bound", 80.0, 2),
        ]
        selections = []
        for order in (rows, list(reversed(rows))):
            monkeypatch.setattr(ranker, "_iter_scored_results", lambda *args, order=order: iter(map(replace, order)))
            ranked = ranker.rank_all(_profile(), [])
            selections.append([r.opportunity_id for r in ranked if r.bucket == "high_priority"])
            assert [r.opportunity_id for r in ranked if r.bucket == "good_match"] == ["z-bound", "a-legacy"]
        assert selections[0] == selections[1]
        assert selections[0][-1] == "b-bound"
        assert len(selections[0]) == 20

    @pytest.mark.parametrize("scores", [
        list(range(100, 70, -1)), [75.0] * 100,
        [70.0] * 19 + [69.9] * 10, [65.0] * 12 + [50.0] * 9 + [10.0] * 30,
    ])
    def test_quality_floor_and_ordered_cutoffs_hold_even_in_small_universes(self, scores):
        rows = [_result(f"row-{i:03}", score) for i, score in enumerate(scores)]
        high, good, reach = ranker._bucket_thresholds(len(rows), lambda index: scores[index])
        assert high >= good >= reach
        assert high >= 70 and good >= 62 and reach >= 42
        ranker._assign_buckets(rows)
        assert len([row for row in rows if row.bucket == "high_priority"]) <= 20
        assert all(row.final_score >= 70 for row in rows if row.bucket == "high_priority")

    def test_compact_and_full_universes_choose_the_same_tied_members_and_counts(self, monkeypatch):
        rows = [_result(f"row-{i:03}", 75.0, i % 3) for i in range(100)]
        rows += [_result("low", 10.0), _result("reach", 45.0), _result("good", 65.0)]
        for order in (rows, list(reversed(rows))):
            monkeypatch.setattr(ranker, "_iter_scored_results", lambda *args, order=order: iter(map(replace, order)))
            full = ranker.rank_all(_profile(), [])
            compact = ranker.rank_visible_universe(_profile(), [])
            assert [asdict(r) for r in compact.visible] == [asdict(r) for r in full if r.bucket != "low_fit"]
            expected_counts = Counter(r.bucket for r in full)
            assert compact.buckets == {
                label: expected_counts[label]
                for label in ("high_priority", "good_match", "reach", "low_fit")
            }
            assert compact.buckets["high_priority"] == 20

    def test_semantic_rerank_reassigns_a_new_tied_boundary(self, monkeypatch):
        from src.matcher import embeddings

        rows = [_result(f"row-{i:03}", 100.0 - i, 2 if i == 29 else 1) for i in range(30)]
        ranker._assign_buckets(rows)
        monkeypatch.setattr(embeddings, "_has_embedding_provider", lambda: True)
        monkeypatch.setattr(embeddings, "semantic_similarity_batch", lambda q, texts: [0.75] * len(texts))
        result = ranker.semantic_rerank(
            _profile(research_interests_text="computer vision"), rows,
            {r.opportunity_id: _opp(r.opportunity_id) for r in rows}, top_k=30, semantic_weight=1.0,
        )
        assert result[0].opportunity_id == "row-029"
        assert [r.bucket for r in result] == ["high_priority"] * 20 + ["good_match"] * 10

    def test_llm_rerank_reassigns_the_cap_after_mapping_scores_into_a_tie(self, monkeypatch):
        from backend.routes import matches

        rows = [_result(f"row-{i:03}", 100.0 - i, 2 if i == 29 else 1) for i in range(30)]
        ranker._assign_buckets(rows)
        monkeypatch.setattr(matches, "_resolve", lambda name: object())
        monkeypatch.setattr(matches, "_llm_rerank_cache", {})
        monkeypatch.setattr(matches, "_llm_score_candidates", lambda q, candidates: {
            ident: {"s": 100.0 if int(ident[-3:]) >= 7 else 0.0, "r": ""}
            for ident, _ in candidates
        })
        outcome = matches.llm_rerank(
            _profile(research_interests_text="computer vision"), rows,
            {r.opportunity_id: _opp(r.opportunity_id) for r in rows}, top_k=30, weight=1.0,
        )
        assert outcome.applied is True
        assert outcome.results[0].opportunity_id == "row-029"
        high = [r for r in outcome.results if r.bucket == "high_priority"]
        assert len(high) == 20
        assert all(r.final_score == 100.0 for r in high)
        assert sum(r.final_score == 100.0 and r.bucket == "good_match" for r in outcome.results) == 3


class TestWhatTheAuditOfTheCandidateFound:
    """Three effects of the candidate's ranker changes, reproduced on the
    corpus or synthetically by an independent read-only audit."""

    def test_a_program_that_has_already_started_is_penalised_even_with_only_an_estimated_deadline(self):
        # 73 active NSF REU sites carried a past ESTIMATED deadline and a
        # start_date already behind us. _stated_deadline_date rightly refuses
        # to read urgency off the estimate — but that also lifted the 0.7
        # passed-penalty, and they took top-20 slots (#1 for a JHU biochem
        # profile). The start date is a stated field: a cycle that has begun is
        # over, whatever the estimate said.
        today = ranker.date.today()
        past_estimate = (today - timedelta(days=120)).isoformat()
        dateless = _opp(opportunity_type="summer_program")
        started = _opp(opportunity_type="summer_program", deadline=past_estimate,
                       deadline_is_estimate=True, start_date=(today - timedelta(days=60)).isoformat())
        upcoming = _opp(opportunity_type="summer_program", deadline=past_estimate,
                        deadline_is_estimate=True, start_date=(today + timedelta(days=200)).isoformat())

        base = ranker.rank_opportunity(_profile(), dateless, today=today)
        over = ranker.rank_opportunity(_profile(), started, today=today)
        ahead = ranker.rank_opportunity(_profile(), upcoming, today=today)

        assert over.final_score == pytest.approx(base.final_score * 0.7, abs=0.1)
        assert any("start date has passed" in gap for gap in over.reasons_gap)
        # The estimate itself still claims nothing: no urgency, no "apply before".
        assert ahead.final_score == base.final_score
        assert not any(step.startswith("Apply before deadline:") for step in ahead.next_steps)
        assert not any("Deadline has passed" in gap for gap in over.reasons_gap)

    def test_rank_twenty_one_is_not_hidden_in_a_small_universe(self):
        # In a universe of 21–33 results the 70th percentile sits above the
        # 20th score; clamping good_match onto high_priority left rank 21 with
        # no band and hid it as low_fit.
        scores = [90.0 - 0.5 * i for i in range(21)]  # 90.0 … 80.0
        rows = [_result(f"row-{i:03}", s) for i, s in enumerate(scores)]
        ranker._assign_buckets(rows)
        assert Counter(r.bucket for r in rows)["high_priority"] == 20
        assert rows[20].bucket != "low_fit"
        assert rows[20].bucket in {"good_match", "reach"}

    def test_selected_types_are_normalised_the_same_way_in_the_hard_filter(self):
        # The candidate normalised selected types for affinity ("Research" ->
        # 100) but the hard filter still compared raw strings, so the same
        # profile could be excluded from the very listings it scored highest.
        ctx = ranker._filter_context(_profile(seeking_type=["Research", "", "  "]))
        assert ctx.seeking == {"research"}
        assert ranker.hard_exclusion(_opp(opportunity_type="research"), ctx) is None
