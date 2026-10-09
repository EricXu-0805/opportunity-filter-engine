"""Regressions for the accepted, bounded Profile -> deterministic Match fixes.

Synthetic records only. Provider calls in reranking tests are replaced at their
boundary; the release gates and the production scoring weights are unchanged.
"""

import random
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, timedelta
from itertools import combinations, permutations

import pytest

from src import evidence as evidence_module
from src.matcher import ranker

RELEASE_CONTRACT_TESTS = True

SERVED_TYPES = ("research", "summer_program", "internship")
SELECTIONS = [list(combo) for size in (1, 2, 3) for combo in combinations(SERVED_TYPES, size)]
BUCKETS = ("high_priority", "good_match", "reach", "low_fit")


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


def expected_selection_labels(single, selection):
    """What a selection must serve, derived from its single-type views alone:
    every row they show, under the label they show it with — except that the
    selection keeps one twenty-place High Priority shortlist, the first twenty
    of those rows in canonical order. Single-type High Priority rows past it
    are Good Matches."""
    rows = [row for kind in selection for row in single[kind] if row.bucket != "low_fit"]
    shortlist = sorted(
        (row for row in rows if row.bucket == "high_priority"), key=ranker.canonical_sort_key
    )[:20]
    kept = {row.opportunity_id for row in shortlist}
    return {
        row.opportunity_id: (
            "good_match"
            if row.bucket == "high_priority" and row.opportunity_id not in kept
            else row.bucket
        )
        for row in rows
    }


def pin_scores(monkeypatch):
    """Choose each record's final score and evidence rank; the real scorer,
    type filter and banding still run around them."""
    table = {}
    score = ranker._rank_opportunity_unlocked

    def pinned(profile, opportunity, *args, **kwargs):
        result = score(profile, opportunity, *args, **kwargs)
        result.final_score, result.evidence_rank = table[result.opportunity_id]
        return result

    monkeypatch.setattr(ranker, "_rank_opportunity_unlocked", pinned)
    return table


@pytest.fixture
def pinned_scores(monkeypatch):
    return pin_scores(monkeypatch)


def _generated_corpus(seed, scores):
    """Three types with independent sizes and score distributions, ties on a
    half-point grid, and the type sometimes spelled the way a form sends it."""
    rng = random.Random(seed)
    corpus = []
    for kind in SERVED_TYPES:
        centre, spread = rng.uniform(30, 95), rng.uniform(2, 20)
        for index in range(rng.choice([0, 4, 9, 10, 14, 21, 35, 60])):
            ident = f"{kind}-{index:03}"
            spelling = rng.choice([kind, kind.replace("_", " ").title()])
            corpus.append(_opp(ident, opportunity_type=spelling))
            score = min(100.0, max(0.0, round(rng.gauss(centre, spread) * 2) / 2))
            scores[ident] = (score, rng.choice([0, 1, 2]))
    rng.shuffle(corpus)
    return corpus


class TestDeadlineEvidenceControlsEveryScoringClaim:
    @pytest.fixture(autouse=True)
    def _clock(self, monkeypatch):
        class FixedDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 3, 1)

        monkeypatch.setattr(ranker, "date", FixedDate)
        monkeypatch.setattr(evidence_module, "_today", lambda: FixedDate(2026, 3, 1))

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

    def test_stated_past_deadline_still_penalizes_and_explains(self):
        dateless = _opp()
        expired = _opp(deadline="2026-02-01T12:00:00Z")
        base = ranker.rank_opportunity(_profile(), dateless)
        result = ranker.rank_opportunity(_profile(), expired)
        assert result.final_score == pytest.approx(base.final_score * 0.7, abs=0.1)
        assert any("Deadline has passed" in gap for gap in result.reasons_gap)
        assert "opportunity.deadline" not in result.unknowns

    def test_a_stated_deadline_two_days_past_is_a_hard_exclusion(self):
        """M05, a deliberate contract change: this used to assert `None` — the
        record stayed in the universe with only the x0.7 haircut. A deadline
        the source stated now closes the listing in target truth, and
        hard_exclusion reads the truth first. The day after the deadline is
        still inside the time-zone grace and is only penalized; an estimate
        never excludes."""
        ctx = ranker._filter_context(_profile())
        assert ranker.hard_exclusion(_opp(deadline="2026-02-27"), ctx) == "listing_closed"
        assert ranker.hard_exclusion(_opp(deadline="2026-02-28"), ctx) is None
        assert ranker.hard_exclusion(_opp(deadline="2026-02-01", deadline_is_estimate=True), ctx) is None

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


class TestEachTypeIsBandedOnItsOwnScores:
    """F2 (2026-09-30): the Reach cut was the 40th percentile of every ticked
    type at once, so a record's visibility and label moved with the other
    types in the selection while its own score stood still. Each type is now
    cut on its own distribution. A selection serves exactly the union of its
    single-type views, and the one thing the types share is the twenty-place
    High Priority shortlist."""

    def test_ticking_another_type_neither_reveals_nor_hides_a_summer_program(self, pinned_scores):
        # The production finding in miniature: thirty summer programs scoring
        # 69..40 are cut at their own p40, 51. Research rows all below 42 used
        # to drag the shared p40 down to the 42 floor and reveal nine of them;
        # internships scoring 95..76 used to push it up to 59 and hide eight.
        corpus = []
        for kind, top, count in (
            ("summer_program", 69.0, 30), ("research", 39.0, 40), ("internship", 95.0, 20),
        ):
            for index in range(count):
                ident = f"{kind}-{index:02}"
                corpus.append(_opp(ident, opportunity_type=kind))
                pinned_scores[ident] = (top - index, 1)

        def summer_rows(selection):
            return {
                row.opportunity_id: row.bucket
                for row in ranker.rank_all(_profile(seeking_type=selection), corpus)
                if row.bucket != "low_fit" and row.opportunity_id.startswith("summer")
            }

        alone = summer_rows(["summer_program"])
        assert sorted(alone) == [f"summer_program-{index:02}" for index in range(19)]
        assert summer_rows(["summer_program", "research"]) == alone
        assert summer_rows(["summer_program", "internship"]) == alone

    @pytest.mark.parametrize("seed", range(40))
    def test_every_selection_is_the_union_of_its_single_type_views(self, seed, pinned_scores):
        corpus = _generated_corpus(seed, pinned_scores)
        exploring = bool(seed % 2)
        single = {
            kind: ranker.rank_all(_profile(seeking_type=[kind], exploring=exploring), corpus)
            for kind in SERVED_TYPES
        }
        for selection in SELECTIONS:
            profile = _profile(seeking_type=selection, exploring=exploring)
            full = ranker.rank_all(profile, corpus)
            compact = ranker.rank_visible_universe(profile, corpus)
            served = {row.opportunity_id: row.bucket for row in compact.visible}
            assert set(served) == {
                row.opportunity_id
                for kind in selection
                for row in single[kind]
                if row.bucket != "low_fit"
            }
            assert served == expected_selection_labels(single, selection)
            assert [asdict(row) for row in compact.visible] == [
                asdict(row) for row in full if row.bucket != "low_fit"
            ]
            assert compact.buckets == {
                label: sum(row.bucket == label for row in full) for label in BUCKETS
            }
            assert sum(compact.buckets.values()) == sum(len(single[kind]) for kind in selection)

    def test_the_shortlist_is_the_first_twenty_nominees_across_the_selection(self, pinned_scores):
        # Alone, each type shortlists every one of its rows. Together the 42
        # nominees compete for twenty places: the twelve research rows at 90,
        # then eight of the thirty tied 80s — strongest evidence first, then
        # id, whichever type they come from. The other 22 are Good Matches.
        corpus = []
        for kind, score, count in (
            ("research", 90.0, 12), ("summer_program", 80.0, 15), ("internship", 80.0, 15),
        ):
            for index in range(count):
                ident = f"{kind}-{index:02}"
                corpus.append(_opp(ident, opportunity_type=kind))
                pinned_scores[ident] = (score, index % 3)
        shortlist = [f"research-{i:02}" for i in (2, 5, 8, 11, 1, 4, 7, 10, 0, 3, 6, 9)]
        shortlist += [f"internship-{i:02}" for i in (2, 5, 8, 11, 14)]
        shortlist += [f"summer_program-{i:02}" for i in (2, 5, 8)]

        for order in (corpus, corpus[::-1]):
            for kind in SERVED_TYPES:
                alone = ranker.rank_all(_profile(seeking_type=[kind]), order)
                assert {row.bucket for row in alone} == {"high_priority"}
            profile = _profile(seeking_type=list(SERVED_TYPES))
            ranked = ranker.rank_all(profile, order)
            assert [r.opportunity_id for r in ranked if r.bucket == "high_priority"] == shortlist
            assert Counter(row.bucket for row in ranked) == {"high_priority": 20, "good_match": 22}
            compact = ranker.rank_visible_universe(profile, order)
            assert [r.opportunity_id for r in compact.visible if r.bucket == "high_priority"] == shortlist
            assert compact.buckets == {"high_priority": 20, "good_match": 22, "reach": 0, "low_fit": 0}


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


class TestAMixedSelectionListsItsLabelsInOrder:
    """F2 follow-up, the owner's choice (2026-09-30): labels are cut per type
    and the types score on different scales, so a score-ordered mixed list put
    an internship Reach above a research Good Match. A selection now lists
    High Priority, then Good Match, then Reach, each in canonical order. A
    single type's list is unchanged: its labels already follow its scores."""

    @pytest.mark.parametrize("seed", range(40))
    def test_labels_never_step_back_and_one_type_keeps_the_canonical_order(self, seed, pinned_scores):
        corpus = _generated_corpus(seed, pinned_scores)
        rank = {label: index for index, label in enumerate(BUCKETS)}
        for selection in SELECTIONS:
            profile = _profile(seeking_type=selection)
            for rows in (ranker.rank_all(profile, corpus), ranker.rank_visible_universe(profile, corpus).visible):
                assert [rank[row.bucket] for row in rows] == sorted(rank[row.bucket] for row in rows)
                for label in BUCKETS:
                    group = [row.opportunity_id for row in rows if row.bucket == label]
                    in_canonical = sorted((row for row in rows if row.bucket == label), key=ranker.canonical_sort_key)
                    assert group == [row.opportunity_id for row in in_canonical]
                if len(selection) == 1:
                    assert rows == sorted(rows, key=ranker.canonical_sort_key)

    def test_a_research_good_match_comes_before_a_higher_scoring_internship_reach(self, pinned_scores):
        # Internships score higher across the board: their Reach band (71-82.5)
        # sits above research's Good Match band (62-68).
        corpus = []
        for kind, top, step, count in (("research", 68.0, 1.0, 40), ("internship", 95.0, 0.5, 80)):
            for index in range(count):
                ident = f"{kind}-{index:02}"
                corpus.append(_opp(ident, opportunity_type=kind))
                pinned_scores[ident] = (top - index * step, 1)
        rows = ranker.rank_visible_universe(_profile(seeking_type=["research", "internship"]), corpus).visible
        position = {row.opportunity_id: index for index, row in enumerate(rows)}
        pairs = [
            (good, reach)
            for good in rows if good.opportunity_type == "research" and good.bucket == "good_match"
            for reach in rows if reach.opportunity_type == "internship" and reach.bucket == "reach"
            if reach.final_score > good.final_score
        ]
        assert pairs, "the fixture must contain an internship Reach that outscores a research Good Match"
        assert all(position[good.opportunity_id] < position[reach.opportunity_id] for good, reach in pairs)
