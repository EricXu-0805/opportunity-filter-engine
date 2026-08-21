"""Match / Results consistency contract tests (2026-07 close-out).

One canonical conclusion per (profile, opportunity, corpus generation,
matcher version, llm flag):

  * /matches and /matches/{id}/explain serve the SAME snapshot — identical
    score (including the LLM blend), bucket (including percentile banding),
    reasons, and unknowns.
  * Excluded opportunities are reported as excluded (in_results=false +
    reason code), never re-scored into a contradictory "normal" verdict.
  * Unknown inputs follow the documented neutral policy — null, missing key,
    empty string, and unknown enum can never produce different outcomes.
  * Pagination slices one snapshot: deterministic total order with a unique
    id tie-break, page-disjointness, and union == total.
  * The corpus is deduplicated by id at load, so counts can never be inflated
    by a shard-level duplicate.
"""

import json
import os
import sys
from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.routes.matches as m_module
from backend import data_loader
from backend.main import app
from src.matcher import ranker
from src.matcher.config import MATCHER_VERSION

client = TestClient(app)


def _profile(**overrides):
    base = {
        "name": "Test",
        "school": "UIUC",
        "home_school": "uiuc",
        "year": "sophomore",
        "major": "CS",
        "college": "Grainger College of Engineering",
        "secondary_interests": [],
        "international_student": False,
        "seeking_type": ["research"],
        "desired_fields": ["machine learning"],
        "hard_skills": [{"name": "Python", "level": "experienced"}],
        "coursework": ["CS 124"],
        "experience_level": "beginner",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": "machine learning",
        "search_weight": 50,
    }
    base.update(overrides)
    return base


def _opp(ident, **overrides):
    """A strong-fit uiuc research record; overrides shape the variants."""
    base = {
        "id": ident,
        "title": f"ML Research {ident}",
        "organization": "Test University",
        "on_campus": True,
        "opportunity_type": "research",
        # A reviewed source type, because every served record has one and an
        # unreviewed one is no longer actionable. Without it these fixtures
        # describe the 26-row exception rather than the corpus.
        "source_type": "campus_program",
        "paid": "yes",
        "is_rolling": True,
        "school": "uiuc",
        "audience": "campus",
        "url": f"https://example.edu/{ident}",
        "contact_email": f"{ident}@example.edu",
        "description_raw": "Machine learning research with mentorship and training. Python required.",
        "description_clean": "Machine learning research.",
        "keywords": ["machine learning"],
        "eligibility": {
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
            "majors": ["CS"],
            "skills_required": ["Python"],
            "international_friendly": "yes",
        },
        "application": {"application_url": f"https://example.edu/{ident}/apply"},
        "metadata": {"is_active": True},
    }
    base.update(overrides)
    return base


def _varied_corpus(n=14):
    """n records whose fit varies enough to spread scores across buckets."""
    corpus = []
    for i in range(n):
        overrides = {}
        if i % 4 == 1:
            overrides["paid"] = "unknown"
        if i % 4 == 2:
            # Intl-unknown but otherwise well-fitting, so it stays visible
            # (verify-don't-rule-out) for an F-1 profile; the off-topic
            # keywords still spread the scores.
            overrides["keywords"] = ["materials science"]
            overrides["eligibility"] = {
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "majors": ["CS"],
                "skills_required": ["Python"],
                "international_friendly": "unknown",
            }
        if i % 4 == 3:
            overrides["opportunity_type"] = "internship"
            overrides["paid"] = "no"
        corpus.append(_opp(f"opp-{i:02d}", **overrides))
    return corpus


@pytest.fixture
def snapshot_env(monkeypatch):
    """Synthetic corpus + snapshot reuse ON + deterministic fake LLM scorer.

    Returns a dict with the corpus and a call-counter for the fake scorer.
    """
    corpus = _varied_corpus()
    by_id = {o["id"]: o for o in corpus}
    ranker_state = (
        ranker._corpus_ref,
        ranker._corpus_rows,
        ranker._static_cache,
        ranker._sim_matrix,
        dict(ranker._kw_word_res),
    )
    monkeypatch.setattr(
        m_module,
        "load_opportunities_generation",
        lambda: (corpus, "snapshot-fixture"),
    )
    monkeypatch.setattr(m_module, "load_opportunities_by_id", lambda: by_id)
    ranker.register_corpus(corpus)

    calls = {"count": 0}

    def fake_scores(query, cand):
        calls["count"] += 1
        # Deterministic per-id scores; several exact collisions to exercise
        # the tie-break (ids differ, blended scores equal).
        return {
            opp_id: {"s": 60.0 + (int(opp_id.split("-")[1]) % 3) * 10.0, "r": f"why {opp_id}"}
            for opp_id, _area in cand
        }

    monkeypatch.setattr(m_module, "_resolve", lambda name: object())
    monkeypatch.setattr(m_module, "_llm_score_candidates", fake_scores)
    monkeypatch.setattr(m_module, "_llm_explanation", lambda *a, **k: None)
    monkeypatch.setattr(m_module, "_SNAPSHOT_TTL_SECONDS", 300)
    m_module._match_snapshots.clear()
    m_module._llm_rerank_cache.clear()
    m_module._explain_cache.clear()
    yield {"corpus": corpus, "by_id": by_id, "calls": calls}
    m_module._match_snapshots.clear()
    m_module._llm_rerank_cache.clear()
    m_module._explain_cache.clear()
    with ranker.corpus_generation_lock:
        (
            ranker._corpus_ref,
            ranker._corpus_rows,
            ranker._static_cache,
            ranker._sim_matrix,
            old_keyword_res,
        ) = ranker_state
        ranker._kw_word_res.clear()
        ranker._kw_word_res.update(old_keyword_res)


class TestExplainServesTheListConclusion:
    """Same profile + same opportunity ⇒ same eligibility, score, bucket,
    reasons, and unknowns on the list and the detail/compare endpoint —
    INCLUDING when the LLM blend changed the list's numbers (the old bug:
    explain returned the pure rule score + flat-floor bucket)."""

    def _assert_identical(self, listing, profile, llm_qs=""):
        assert listing["results"]
        for r in listing["results"]:
            resp = client.post(
                f"/api/matches/{r['opportunity_id']}/explain{llm_qs}", json=profile
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["final_score"] == r["final_score"]
            assert body["bucket"] == r["bucket"]
            assert body["reasons_fit"] == r["reasons_fit"]
            assert body["reasons_gap"] == r["reasons_gap"]
            assert body["eligibility_score"] == r["eligibility_score"]
            assert body["readiness_score"] == r["readiness_score"]
            assert body["upside_score"] == r["upside_score"]
            assert body["unknowns"] == r["unknowns"]
            assert body["in_results"] is True
            assert body["excluded_reason"] is None
            assert body["matcher_version"] == listing["matcher_version"]

    def test_llm_blended_scores_and_buckets_match(self, snapshot_env):
        profile = _profile()
        listing = client.post("/api/matches?llm=true", json=profile).json()
        # The fake scorer must actually have blended something, or this test
        # would silently degrade into the rule-only comparison.
        assert any(r["ai_reason"] for r in listing["results"])
        self._assert_identical(listing, profile, "?llm=true")

    def test_llm_false_path_matches(self, snapshot_env):
        profile = _profile()
        listing = client.post("/api/matches?llm=false", json=profile).json()
        assert all(not r["ai_reason"] for r in listing["results"])
        self._assert_identical(listing, profile, llm_qs="?llm=false")

    def test_percentile_bucket_served_not_flat_floor(self, snapshot_env):
        """With >=10 results the bucket comes from percentile banding. Any
        result whose score clears the 70.0 flat floor but is NOT labeled
        high_priority proves the list used banding — explain must agree
        (the flat-floor path would have said high_priority)."""
        profile = _profile()
        listing = client.post("/api/matches", json=profile).json()
        demoted = [
            r for r in listing["results"]
            if r["final_score"] >= 70.0 and r["bucket"] != "high_priority"
        ]
        for r in demoted:
            body = client.post(
                f"/api/matches/{r['opportunity_id']}/explain", json=_profile()
            ).json()
            assert body["bucket"] == r["bucket"]

    def test_excluded_opportunity_reports_exclusion(self, snapshot_env, monkeypatch):
        corpus = snapshot_env["corpus"] + [
            _opp("other-campus", school="ucb", audience="campus")
        ]
        by_id = {o["id"]: o for o in corpus}
        ranker.register_corpus(corpus)
        monkeypatch.setattr(
            m_module,
            "load_opportunities_generation",
            lambda: (corpus, "excluded-fixture"),
        )
        monkeypatch.setattr(m_module, "load_opportunities_by_id", lambda: by_id)
        m_module._match_snapshots.clear()

        profile = _profile()
        listing = client.post("/api/matches", json=profile).json()
        ids = {r["opportunity_id"] for r in listing["results"]}
        assert "other-campus" not in ids

        body = client.post("/api/matches/other-campus/explain", json=profile).json()
        assert body["in_results"] is False
        assert body["excluded_reason"] == "other_school_campus"
        # The canonical conclusion is stated, not contradicted by omission.
        assert "not in your results" in body["reasons_gap"][0].lower()

    @pytest.mark.parametrize(
        ("source_text", "reason", "gap_text"),
        [
            (
                "Not accepting undergraduate researchers at this time.",
                "faculty_not_accepting",
                "not currently accepting undergraduate students",
            ),
        ],
    )
    def test_source_negative_faculty_explain_preserves_precise_exclusion(
        self,
        snapshot_env,
        monkeypatch,
        source_text,
        reason,
        gap_text,
    ):
        faculty = _opp(
            "faculty-source-negative",
            source_type="faculty_research",
            description_raw=source_text,
            description_clean=source_text,
            metadata={"is_active": True, "research_areas_raw": source_text},
        )
        corpus = snapshot_env["corpus"] + [faculty]
        by_id = {o["id"]: o for o in corpus}
        ranker.register_corpus(corpus)
        monkeypatch.setattr(
            m_module,
            "load_opportunities_generation",
            lambda: (corpus, f"faculty-exclusion-{reason}"),
        )
        monkeypatch.setattr(m_module, "load_opportunities_by_id", lambda: by_id)
        m_module._match_snapshots.clear()

        response = client.post(
            "/api/matches/faculty-source-negative/explain",
            json=_profile(),
        )

        # CONTRACT CHANGE, deliberate: this used to answer 200 with
        # `in_results: false` and an explanation. The target-truth guard now
        # refuses the endpoint outright, the same way it already refused it for
        # a closed listing — explain accepts `?llm=true` and is a paid call, so
        # the refusal has to come before the work, and one endpoint answering
        # "here is why not" for one dead reason while refusing the other three
        # is the inconsistency this contract exists to remove.
        #
        # What must NOT change is the precision: the student is told the source
        # says this person is not accepting undergraduates, never a blurred
        # "closed" or "unavailable".
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "TARGET_NOT_ACTIONABLE"
        assert detail["reason"] == reason
        assert detail["retryable"] is False
        assert gap_text in detail["message"].lower()

    def test_matcher_version_served_and_stable(self, snapshot_env):
        listing = client.post("/api/matches", json=_profile()).json()
        assert listing["matcher_version"] == MATCHER_VERSION
        assert MATCHER_VERSION  # non-empty


class TestSnapshotPagination:
    def test_repeated_requests_identical_order(self, snapshot_env):
        profile = _profile()
        first = client.post("/api/matches?llm=true", json=profile).json()
        second = client.post("/api/matches?llm=true", json=profile).json()
        assert [r["opportunity_id"] for r in first["results"]] == [
            r["opportunity_id"] for r in second["results"]
        ]
        # Snapshot reuse: the paid scorer ran for the first request only.
        assert snapshot_env["calls"]["count"] == 1

    def test_pages_are_disjoint_and_union_is_complete(self, snapshot_env):
        profile = _profile()
        full = client.post("/api/matches", json=profile).json()
        expected = [r["opportunity_id"] for r in full["results"]]
        assert full["total"] == len(expected)

        seen: list = []
        offset = 0
        while True:
            page = client.post(
                f"/api/matches?limit=4&offset={offset}", json=profile
            ).json()
            ids = [r["opportunity_id"] for r in page["results"]]
            if not ids:
                break
            assert not set(ids) & set(seen), "pages must not overlap"
            seen.extend(ids)
            offset += 4
        assert seen == expected, "traversal must return every result exactly once, in order"

    def test_cursor_traversal_is_complete_and_generation_bound(self, snapshot_env):
        profile = _profile()
        expected = [
            result["opportunity_id"]
            for result in client.post("/api/matches", json=profile).json()["results"]
        ]
        seen: list[str] = []
        cursor = None
        result_set_id = None
        while True:
            suffix = "?limit=4" if cursor is None else f"?limit=4&cursor={cursor}"
            response = client.post(f"/api/matches{suffix}", json=profile)
            assert response.status_code == 200
            page = response.json()
            if result_set_id is None:
                result_set_id = page["result_set_id"]
            assert page["result_set_id"] == result_set_id
            assert page["returned_count"] == len(page["results"])
            seen.extend(result["opportunity_id"] for result in page["results"])
            if not page["has_more"]:
                assert page["next_cursor"] is None
                break
            assert page["next_cursor"]
            cursor = page["next_cursor"]
        assert seen == expected
        assert len(seen) == len(set(seen))

    def test_tampered_cursor_fails_closed(self, snapshot_env):
        first = client.post("/api/matches?limit=3", json=_profile()).json()
        cursor = first["next_cursor"]
        assert cursor
        replacement = "A" if cursor[-1] != "A" else "B"
        response = client.post(
            f"/api/matches?limit=3&cursor={cursor[:-1]}{replacement}",
            json=_profile(),
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "MATCH_CURSOR_INVALID"

    def test_cursor_rejects_new_corpus_generation(
        self, snapshot_env, monkeypatch
    ):
        versions = {"value": "generation-a"}
        monkeypatch.setattr(
            m_module,
            "load_opportunities_generation",
            lambda: (snapshot_env["corpus"], versions["value"]),
        )
        first = client.post("/api/matches?limit=3", json=_profile()).json()
        assert first["next_cursor"]
        versions["value"] = "generation-b"
        response = client.post(
            f"/api/matches?limit=3&cursor={first['next_cursor']}",
            json=_profile(),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "MATCH_CURSOR_EXPIRED"

    def test_cursor_rejects_evicted_snapshot_even_when_inputs_match(
        self,
        snapshot_env,
    ):
        first = client.post(
            "/api/matches?limit=3",
            json=_profile(),
        ).json()
        assert first["next_cursor"]

        # Simulate TTL eviction, process restart, or capacity eviction. The
        # profile/corpus/matcher key is unchanged, but a newly materialized
        # snapshot is a new generation and must not accept the old offset.
        m_module._match_snapshots.clear()
        response = client.post(
            f"/api/matches?limit=3&cursor={first['next_cursor']}",
            json=_profile(),
        )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "MATCH_CURSOR_EXPIRED"

    def test_total_equals_visible_bucket_sum(self, snapshot_env):
        body = client.post("/api/matches", json=_profile()).json()
        assert body["total"] == body["high_priority"] + body["good_match"] + body["reach"]
        assert body["total"] == len(body["results"])
        paged = client.post("/api/matches?limit=3", json=_profile()).json()
        assert paged["total"] == body["total"], "total is the universe, not the page"

    def test_equal_blended_scores_tie_break_deterministically(self, snapshot_env):
        body = client.post("/api/matches", json=_profile()).json()
        rows = body["results"]
        for a, b in zip(rows, rows[1:], strict=False):
            if a["final_score"] == b["final_score"]:
                assert a["opportunity_id"] < b["opportunity_id"], (
                    "equal scores must order by unique id"
                )

    def test_profile_change_is_a_different_snapshot(self, snapshot_env):
        # Every profile field the matcher consumes must key the snapshot —
        # coursework only differs here.
        client.post("/api/matches", json=_profile())
        client.post("/api/matches", json=_profile(coursework=["CS 225"]))
        assert len(m_module._match_snapshots) == 2
        from backend.schemas import ProfileRequest
        key_a = m_module._snapshot_key(
            m_module._normalized_profile(ProfileRequest(**_profile())), True
        )
        key_b = m_module._snapshot_key(
            m_module._normalized_profile(ProfileRequest(**_profile(coursework=["CS 225"]))), True
        )
        assert key_a != key_b

    def test_non_scoring_identity_fields_do_not_fragment_snapshot_key(
        self,
        snapshot_env,
    ):
        from backend.schemas import ProfileRequest

        first = m_module._normalized_profile(ProfileRequest(**{
            **_profile(),
            "name": "Alex",
            "linkedin_url": "https://example.com/alex",
        }))
        second = m_module._normalized_profile(ProfileRequest(**{
            **_profile(),
            "name": "Different display name",
            "linkedin_url": "https://example.com/different",
            "github_url": "https://github.com/different",
        }))

        assert m_module._snapshot_key(first, False) == m_module._snapshot_key(
            second,
            False,
        )

    def test_corpus_swap_invalidates_snapshot(self, snapshot_env, monkeypatch):
        import asyncio

        from backend.schemas import ProfileRequest
        profile_dict = m_module._normalized_profile(ProfileRequest(**_profile()))
        snap1 = asyncio.run(m_module._get_or_compute_snapshot(profile_dict, False))
        # Same corpus object + fresh TTL → the same snapshot is reused.
        assert asyncio.run(m_module._get_or_compute_snapshot(profile_dict, False)) is snap1
        # A NEW corpus list object (a reload) must recompute even when the
        # mtime-based corpus_version did not move (the identity belt).
        swapped = [dict(o) for o in snapshot_env["corpus"]]
        ranker.register_corpus(swapped)
        monkeypatch.setattr(
            m_module,
            "load_opportunities_generation",
            lambda: (swapped, "swapped-fixture"),
        )
        monkeypatch.setattr(
            m_module, "load_opportunities_by_id", lambda: {o["id"]: o for o in swapped}
        )
        snap2 = asyncio.run(m_module._get_or_compute_snapshot(profile_dict, False))
        assert snap2 is not snap1
        assert snap2.corpus_identity == id(swapped)
        assert snap1 not in m_module._match_snapshots.values()
        assert all(
            snap2.opportunities_by_id[opportunity_id] is not opportunity
            for opportunity_id, opportunity in {
                opportunity["id"]: opportunity for opportunity in swapped
            }.items()
            if opportunity_id in snap2.opportunities_by_id
        )

    def test_stale_loader_result_never_rebinds_ranker_backwards(
        self,
        snapshot_env,
        monkeypatch,
    ):
        import asyncio

        import src.matcher.ranker as rk
        from backend.schemas import ProfileRequest

        stale = snapshot_env["corpus"]
        current = [dict(opportunity) for opportunity in stale]
        rk.register_corpus(current)
        monkeypatch.setattr(
            m_module,
            "load_opportunities_generation",
            lambda: (stale, "stale-generation"),
        )
        profile_dict = m_module._normalized_profile(
            ProfileRequest(**_profile())
        )

        with pytest.raises(HTTPException) as error:
            asyncio.run(
                m_module._get_or_compute_snapshot(profile_dict, False)
            )

        assert error.value.status_code == 409
        assert error.value.detail["code"] == "MATCH_DATA_CHANGED"
        assert rk._corpus_ref is current

    def test_matcher_version_participates_in_snapshot_key(self, snapshot_env, monkeypatch):
        profile_dict = m_module._normalized_profile(
            __import__("backend.schemas", fromlist=["ProfileRequest"]).ProfileRequest(
                **_profile()
            )
        )
        key_now = m_module._snapshot_key(profile_dict, True)
        monkeypatch.setattr(m_module, "MATCHER_VERSION", "test-other-version")
        assert m_module._snapshot_key(profile_dict, True) != key_now

    def test_llm_flag_participates_in_snapshot_key(self, snapshot_env):
        profile_dict = m_module._normalized_profile(
            __import__("backend.schemas", fromlist=["ProfileRequest"]).ProfileRequest(
                **_profile()
            )
        )
        assert m_module._snapshot_key(profile_dict, True) != m_module._snapshot_key(
            profile_dict, False
        )

    def test_same_key_concurrent_miss_is_single_flight(self, snapshot_env, monkeypatch):
        import asyncio
        import time

        from backend.schemas import ProfileRequest
        from src.matcher.ranker import rank_visible_universe as real_rank

        calls = {"count": 0}

        def slow_rank(profile, opportunities, responsiveness=None):
            calls["count"] += 1
            time.sleep(0.05)
            return real_rank(profile, opportunities, responsiveness)

        monkeypatch.setattr(m_module, "rank_visible_universe", slow_rank)
        m_module._match_snapshots.clear()
        profile_dict = m_module._normalized_profile(ProfileRequest(**_profile()))

        async def run_concurrently():
            return await asyncio.gather(*[
                m_module._get_or_compute_snapshot(profile_dict, False)
                for _ in range(4)
            ])

        snapshots = asyncio.run(run_concurrently())
        assert calls["count"] == 1
        assert all(snapshot is snapshots[0] for snapshot in snapshots)

    def test_different_key_queue_is_hard_bounded(self, snapshot_env, monkeypatch):
        import asyncio
        import threading

        from backend.schemas import ProfileRequest
        from src.matcher.ranker import RankedMatchUniverse

        release = threading.Event()

        def blocked_rank(_profile, _opportunities, responsiveness=None):
            assert release.wait(timeout=2)
            return RankedMatchUniverse(
                visible=[],
                buckets={
                    "high_priority": 0,
                    "good_match": 0,
                    "reach": 0,
                    "low_fit": 0,
                },
                field_relevant_count=0,
            )

        monkeypatch.setattr(m_module, "rank_visible_universe", blocked_rank)
        m_module._match_snapshots.clear()
        # Derived from the constants, not pinned to a literal: the queue depth
        # is a tuning number (raised to 8 once an uncached snapshot was measured
        # at 6.4s against the live corpus), while "capacity is bounded and the
        # overflow is a retryable 503" is the contract worth keeping.
        capacity = m_module._MATCH_MAX_WORKERS + m_module._MATCH_MAX_PENDING
        profiles = [
            m_module._normalized_profile(
                ProfileRequest(**_profile(coursework=[f"CS {101 + n}"]))
            )
            for n in range(capacity + 1)
        ]

        async def exercise_capacity():
            pending = [
                asyncio.create_task(
                    m_module._get_or_compute_snapshot(profile, False)
                )
                for profile in profiles[:capacity]
            ]
            await asyncio.sleep(0.05)
            with pytest.raises(HTTPException) as error:
                await m_module._get_or_compute_snapshot(profiles[capacity], False)
            assert error.value.status_code == 503
            assert error.value.detail["code"] == "MATCH_BUSY"
            # The client is told this clears on its own — the browser now acts
            # on it (frontend/src/lib/api.ts honours Retry-After).
            assert error.value.detail["retryable"] is True
            assert error.value.headers["Retry-After"] == "5"
            release.set()
            await asyncio.gather(*pending)

        asyncio.run(exercise_capacity())

    def test_low_fit_explain_is_not_reported_as_listed(
        self, snapshot_env, monkeypatch
    ):
        corpus = snapshot_env["corpus"] + [
            _opp(
                "weak-low-fit",
                title="Unrelated archive",
                paid="no",
                on_campus=False,
                contact_email="",
                keywords=["medieval history"],
                description_raw="Archive cataloging.",
                description_clean="Archive cataloging.",
                eligibility={
                    "preferred_year": ["senior"],
                    "majors": ["History"],
                    "skills_required": ["Latin"],
                    "international_friendly": "unknown",
                },
                application={},
            )
        ]
        by_id = {o["id"]: o for o in corpus}
        ranker.register_corpus(corpus)
        monkeypatch.setattr(
            m_module,
            "load_opportunities_generation",
            lambda: (corpus, "low-fit-fixture"),
        )
        monkeypatch.setattr(m_module, "load_opportunities_by_id", lambda: by_id)
        m_module._match_snapshots.clear()
        profile = _profile(
            preferences={
                "min_match_threshold": 0,
                "show_reach_opportunities": True,
                "prioritize_paid": True,
                "exclude_citizenship_restricted": True,
            }
        )
        baseline = ranker.rank_all(profile, corpus)
        low_fit_ids = {
            result.opportunity_id for result in baseline if result.bucket == "low_fit"
        }
        assert low_fit_ids
        opportunity_id = sorted(low_fit_ids)[0]

        listing = client.post("/api/matches", json=profile).json()
        assert opportunity_id not in {
            result["opportunity_id"] for result in listing["results"]
        }
        explanation = client.post(
            f"/api/matches/{opportunity_id}/explain",
            json=profile,
        ).json()
        assert explanation["in_results"] is False
        assert explanation["excluded_reason"] == "below_threshold"


class TestServerMatchView:
    @staticmethod
    def _request(profile, **view_overrides):
        view = {
            "tab": "all",
            "search_query": "",
            "paid": "",
            "intl": "",
            "source": "",
            "on_campus": "",
            "deadline": "",
            "min_score": 0,
            "scope": "",
            "sort_by": "score",
            "show_dismissed": False,
            "favorite_ids": [],
            "dismissed_ids": [],
            "today": date.today().isoformat(),
        }
        view.update(view_overrides)
        return {"profile": profile, "view": view, "page_size": 4}

    def test_the_refine_flag_reaches_the_route_the_results_page_calls(
        self, snapshot_env, monkeypatch
    ):
        """?llm=true must actually run the refine pass here.

        This route passed a hardcoded False to the snapshot resolver, so the
        AI toggle changed the client's cache key and the header copy while the
        list stayed deterministic — an accepted, flag-open feature that no
        student could reach. Assert the pass runs, not merely that the
        parameter parses.
        """
        from backend.routes import matches as matches_mod

        seen: list[bool] = []
        original = matches_mod._get_or_compute_snapshot

        async def _record(profile_dict, llm):
            seen.append(llm)
            return await original(profile_dict, llm)

        monkeypatch.setattr(matches_mod, "_get_or_compute_snapshot", _record)

        request = self._request(_profile())
        assert client.post("/api/matches/view?llm=true", json=request).status_code == 200
        assert client.post("/api/matches/view?llm=false", json=request).status_code == 200
        assert client.post("/api/matches/view", json=request).status_code == 200
        assert seen == [True, False, False]

    def test_the_response_reports_the_mode_it_got_not_the_one_asked_for(
        self, snapshot_env, monkeypatch
    ):
        """?llm=true is a request; ai_refined is what happened.

        Every degrade — provider unconfigured, budget exhausted, an unusable
        batch — leaves a complete rule ranking behind, so the results cannot
        be told apart from a refined set by looking at them. Without an
        attestation the client badge has nothing to read but the request flag,
        and claims a paid pass that never ran.
        """
        from backend.routes import matches as matches_mod

        request = self._request(_profile())

        monkeypatch.setattr(matches_mod, "_resolve", lambda *a, **k: None)
        matches_mod._match_snapshots.clear()
        degraded = client.post("/api/matches/view?llm=true", json=request)
        assert degraded.status_code == 200
        assert degraded.json()["ai_refined"] is False

        def _applied(profile, results, lookup, **kwargs):
            for result in results[:1]:
                result.ai_reason = "Named their imaging work."
            return matches_mod.RerankOutcome(results, True)

        monkeypatch.setattr(matches_mod, "llm_rerank", _applied)
        matches_mod._match_snapshots.clear()
        refined = client.post("/api/matches/view?llm=true", json=request)
        assert refined.status_code == 200
        assert refined.json()["ai_refined"] is True

        matches_mod._match_snapshots.clear()
        rule_only = client.post("/api/matches/view?llm=false", json=request)
        assert rule_only.json()["ai_refined"] is False

    def test_unfiltered_cursor_walk_equals_canonical_visible_universe(
        self, snapshot_env
    ):
        profile = _profile()
        expected = [
            result.opportunity_id
            for result in ranker.rank_all(profile, snapshot_env["corpus"])
            if result.bucket != "low_fit"
        ]
        request = self._request(profile)
        seen: list[str] = []
        response_pages = []
        while True:
            response = client.post("/api/matches/view", json=request)
            assert response.status_code == 200
            page = response.json()
            response_pages.append(page)
            seen.extend(result["opportunity_id"] for result in page["results"])
            if not page["has_more"]:
                break
            request["cursor"] = page["next_cursor"]

        assert seen == expected
        assert len(seen) == len(set(seen))
        first = response_pages[0]
        assert first["filtered_total"] == len(expected)
        assert first["view_counts"]["all"] == len(expected)
        # Stage 1: the wire version is deliberately unchanged so a still-running
        # old frontend keeps working. The target-truth promise travels as its
        # own marker, present on every page including an empty one.
        assert first["contract_version"] == "match-view-v3-faculty-trust"
        assert all(page["target_truth_contract"] == "target-truth-v2" for page in response_pages)
        assert all(page["result_set_id"] == first["result_set_id"] for page in response_pages)
        assert all(page["view_id"] == first["view_id"] for page in response_pages)

    def test_favorites_dismissals_and_tab_counts_are_complete(self, snapshot_env):
        profile = _profile()
        canonical = [
            result.opportunity_id
            for result in ranker.rank_all(profile, snapshot_env["corpus"])
            if result.bucket != "low_fit"
        ]
        assert len(canonical) >= 4
        favorites = canonical[:4]
        request = self._request(
            profile,
            tab="starred",
            favorite_ids=favorites,
            dismissed_ids=[favorites[0]],
        )
        body = client.post("/api/matches/view", json=request).json()
        assert body["filtered_total"] == 3
        assert body["view_counts"]["starred"] == 3
        assert [result["opportunity_id"] for result in body["results"]] == favorites[1:]
        assert (
            body["view_counts"]["all"]
            == body["view_counts"]["high_priority"]
            + body["view_counts"]["good_match"]
            + body["view_counts"]["reach"]
        )

    def test_view_cursor_rejects_filter_change(self, snapshot_env):
        profile = _profile()
        request = self._request(profile)
        request["page_size"] = 1
        first = client.post("/api/matches/view", json=request).json()
        assert first["next_cursor"]

        changed = self._request(profile, paid="yes")
        changed["page_size"] = 1
        changed["cursor"] = first["next_cursor"]
        response = client.post("/api/matches/view", json=changed)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "MATCH_CURSOR_EXPIRED"

    def test_paid_filter_and_bucket_counts_match_full_snapshot(self, snapshot_env):
        profile = _profile()
        request = self._request(profile, paid="yes")
        body = client.post("/api/matches/view", json=request).json()
        baseline = [
            result
            for result in ranker.rank_all(profile, snapshot_env["corpus"])
            if result.bucket != "low_fit"
            and snapshot_env["by_id"][result.opportunity_id].get("paid")
            in {"yes", "stipend"}
        ]
        assert body["filtered_total"] == len(baseline)
        assert body["view_counts"]["all"] == len(baseline)
        assert body["view_counts"]["high_priority"] == sum(
            result.bucket == "high_priority" for result in baseline
        )

    def test_view_predicates_match_browser_rounding_alias_and_facets(self):
        from backend.schemas import MatchViewState
        from src.matcher.ranker import MatchResult

        results = [
            MatchResult(
                opportunity_id="ml-stipend",
                eligibility_score=80,
                readiness_score=80,
                upside_score=80,
                final_score=79.5,
                bucket="good_match",
                reasons_fit=["Machine learning fit"],
                reasons_gap=[],
                next_steps=[],
            ),
            MatchResult(
                opportunity_id="history",
                eligibility_score=80,
                readiness_score=80,
                upside_score=80,
                final_score=79.4,
                bucket="good_match",
                reasons_fit=["Archive fit"],
                reasons_gap=[],
                next_steps=[],
            ),
        ]
        opportunities = {
            "ml-stipend": _opp(
                "ml-stipend",
                title="Machine Learning Lab",
                paid="stipend",
                source="source-a",
                deadline="2026-08-01",
            ),
            "history": _opp(
                "history",
                title="Medieval Archive",
                paid="yes",
                source="source-b",
                deadline="2026-08-20",
            ),
        }
        view = MatchViewState(
            tab="all",
            search_query="ml",
            paid="yes",
            min_score=80,
            deadline="7",
            today="2026-07-31",
        )
        filtered, counts, facets, scope_available, _deadlines = (
            m_module._apply_match_view(
                results,
                opportunities,
                view,
                "uiuc",
            )
        )
        assert [result.opportunity_id for result in filtered] == ["ml-stipend"]
        assert counts["all"] == 1
        # Facets describe the complete canonical universe, not the filtered row.
        assert facets == [
            {"source": "source-a", "count": 1},
            {"source": "source-b", "count": 1},
        ]
        assert scope_available is True

    def test_rolling_deadline_excludes_unconfirmed_faculty_contacts(self):
        """A legacy faculty stamp cannot turn a directory profile into an opening."""
        from backend.schemas import MatchViewState
        from src.matcher.ranker import MatchResult

        results = [
            MatchResult(
                opportunity_id="rolling-program", eligibility_score=80,
                readiness_score=80, upside_score=80, final_score=79.5,
                bucket="good_match", reasons_fit=[], reasons_gap=[], next_steps=[],
            ),
            MatchResult(
                opportunity_id="faculty-contact", eligibility_score=80,
                readiness_score=80, upside_score=80, final_score=79.4,
                bucket="good_match", reasons_fit=[], reasons_gap=[], next_steps=[],
            ),
            MatchResult(
                opportunity_id="dated-program", eligibility_score=80,
                readiness_score=80, upside_score=80, final_score=79.3,
                bucket="good_match", reasons_fit=[], reasons_gap=[], next_steps=[],
            ),
        ]
        opportunities = {
            "rolling-program": {
                **_opp("rolling-program"), "is_rolling": True, "deadline": None,
            },
            # Old shards stamped every faculty profile rolling. Source type +
            # unreviewed metadata must fail closed even before loader cleanup.
            "faculty-contact": {
                **_opp("faculty-contact"),
                "source_type": "faculty_research",
                "is_rolling": True,
                "deadline": None,
                "metadata": {"manually_reviewed": False},
            },
            # A real closing date, and explicitly not rolling.
            "dated-program": {
                **_opp("dated-program"), "is_rolling": False, "deadline": "2026-08-01",
            },
        }
        view = MatchViewState(tab="all", deadline="rolling", today="2026-07-31")

        filtered, _counts, _facets, _scope, _deadlines = m_module._apply_match_view(
            results, opportunities, view, "uiuc",
        )
        assert [r.opportunity_id for r in filtered] == ["rolling-program"]

    def test_poisoned_faculty_never_satisfies_opening_facets_or_date_sort(self):
        from backend.schemas import MatchViewState
        from src.matcher.ranker import MatchResult

        faculty = MatchResult(
            opportunity_id="faculty-poison",
            eligibility_score=80,
            readiness_score=80,
            upside_score=80,
            final_score=90,
            bucket="high_priority",
            reasons_fit=[],
            reasons_gap=[],
            next_steps=[],
        )
        listing = MatchResult(
            opportunity_id="real-listing",
            eligibility_score=80,
            readiness_score=80,
            upside_score=80,
            final_score=80,
            bucket="good_match",
            reasons_fit=[],
            reasons_gap=[],
            next_steps=[],
        )
        opportunities = {
            "faculty-poison": {
                **_opp("faculty-poison"),
                "source_type": "faculty_research",
                "paid": "yes",
                "on_campus": True,
                "deadline": "2026-08-01",
                "posted_date": "2099-01-01",
                "is_rolling": True,
                "eligibility": {"international_friendly": "yes"},
            },
            "real-listing": {
                **_opp("real-listing"),
                "source_type": "campus_program",
                "deadline": "2026-08-05",
                "posted_date": "2026-07-01",
            },
        }

        for view in (
            MatchViewState(tab="all", paid="yes", today="2026-07-31"),
            MatchViewState(tab="all", intl="yes", today="2026-07-31"),
            MatchViewState(tab="all", on_campus="yes", today="2026-07-31"),
            MatchViewState(tab="all", on_campus="no", today="2026-07-31"),
            MatchViewState(tab="all", deadline="7", today="2026-07-31"),
            MatchViewState(tab="all", deadline="rolling", today="2026-07-31"),
        ):
            filtered, *_ = m_module._apply_match_view(
                [faculty], opportunities, view, "uiuc",
            )
            assert filtered == []

        unfiltered, *_rest, deadline_facets = m_module._apply_match_view(
            [faculty],
            opportunities,
            MatchViewState(tab="all", today="2026-07-31"),
            "uiuc",
        )
        assert [result.opportunity_id for result in unfiltered] == ["faculty-poison"]
        assert deadline_facets == {"7": 0, "14": 0, "30": 0, "passed": 0}

        deadline_sorted, *_ = m_module._apply_match_view(
            [faculty, listing],
            opportunities,
            MatchViewState(tab="all", sort_by="deadline", today="2026-07-31"),
            "uiuc",
        )
        newest_sorted, *_ = m_module._apply_match_view(
            [faculty, listing],
            opportunities,
            MatchViewState(tab="all", sort_by="newest", today="2026-07-31"),
            "uiuc",
        )
        assert [result.opportunity_id for result in deadline_sorted] == [
            "real-listing",
            "faculty-poison",
        ]
        assert [result.opportunity_id for result in newest_sorted] == [
            "real-listing",
            "faculty-poison",
        ]

    def test_unknown_campus_is_neither_yes_nor_no(self):
        from backend.schemas import MatchViewState
        from src.matcher.ranker import MatchResult

        results = [
            MatchResult(
                opportunity_id=ident,
                eligibility_score=80,
                readiness_score=80,
                upside_score=80,
                final_score=80 - index,
                bucket="good_match",
                reasons_fit=[],
                reasons_gap=[],
                next_steps=[],
            )
            for index, ident in enumerate(("campus-yes", "campus-no", "campus-unknown"))
        ]
        opportunities = {
            "campus-yes": {**_opp("campus-yes"), "on_campus": True},
            "campus-no": {**_opp("campus-no"), "on_campus": False},
            "campus-unknown": {**_opp("campus-unknown"), "on_campus": None},
        }

        def selected(value: str) -> list[str]:
            view = MatchViewState(tab="all", on_campus=value, today="2026-07-31")
            filtered, *_ = m_module._apply_match_view(results, opportunities, view, "uiuc")
            return [result.opportunity_id for result in filtered]

        assert selected("yes") == ["campus-yes"]
        assert selected("no") == ["campus-no"]

    def test_deadline_facets_count_what_each_chip_would_return(self):
        """The rail renders on these counts, so they must match the predicate.

        A chip that is shown because the count says 1 and then returns 0 is the
        same defect one layer along. Both sides are computed from
        `_calendar_days_until` against the caller's `today`.
        """
        from backend.schemas import MatchViewState
        from src.matcher.ranker import MatchResult

        def _result(opportunity_id: str, score: float) -> MatchResult:
            return MatchResult(
                opportunity_id=opportunity_id, eligibility_score=80,
                readiness_score=80, upside_score=80, final_score=score,
                bucket="good_match", reasons_fit=[], reasons_gap=[], next_steps=[],
            )

        results = [_result("closes-in-3", 80.0), _result("closes-in-20", 79.0),
                   _result("already-closed", 78.0), _result("no-date", 77.0)]
        opportunities = {
            "closes-in-3": {**_opp("closes-in-3"), "deadline": "2026-08-03"},
            "closes-in-20": {**_opp("closes-in-20"), "deadline": "2026-08-20"},
            "already-closed": {**_opp("already-closed"), "deadline": "2026-07-01"},
            "no-date": {**_opp("no-date"), "deadline": None},
        }
        view = MatchViewState(tab="all", today="2026-07-31")

        _f, _c, _s, _sc, deadlines = m_module._apply_match_view(
            results, opportunities, view, "uiuc",
        )
        assert deadlines == {"7": 1, "14": 1, "30": 2, "passed": 1}

        for window, expected in (("7", 1), ("14", 1), ("30", 2), ("passed", 1)):
            chosen = MatchViewState(tab="all", deadline=window, today="2026-07-31")
            rows, _c2, _f2, _s2, _d2 = m_module._apply_match_view(
                results, opportunities, chosen, "uiuc",
            )
            assert len(rows) == expected, window


class TestUnknownPolicy:
    """null / missing key / empty string / unknown enum must produce identical
    conclusions, and unknowns are traced, never silently converted."""

    def test_missing_year_forms_are_identical_and_neutral(self):
        opp = _opp("year-test")
        r_empty = ranker.rank_opportunity(_profile(year=""), opp)
        p_missing = _profile()
        del p_missing["year"]
        r_missing = ranker.rank_opportunity(p_missing, opp)
        r_unknown = ranker.rank_opportunity(_profile(year="unknown"), opp)
        assert r_empty.final_score == r_missing.final_score == r_unknown.final_score
        assert r_empty.eligibility_score == r_missing.eligibility_score
        for r in (r_empty, r_missing, r_unknown):
            assert "profile.year" in r.unknowns
            assert any("class year" in g.lower() for g in r.reasons_gap)
        # Neutral, not near-ineligible: a known-fit year scores higher but the
        # unknown-year profile is NOT floored to the old year_score=0 regime.
        r_known = ranker.rank_opportunity(_profile(), opp)
        assert r_known.final_score >= r_empty.final_score
        assert ranker._year_match_score("", ["freshman", "sophomore"]) == 40.0

    def test_paid_null_missing_unknown_enum_identical(self):
        base = _profile()
        scores = []
        for paid in (None, "unknown", "weird-enum"):
            o = _opp("paid-test", paid=paid)
            scores.append(ranker.rank_opportunity(base, o).final_score)
        o_missing = _opp("paid-test")
        del o_missing["paid"]
        scores.append(ranker.rank_opportunity(base, o_missing).final_score)
        assert len(set(scores)) == 1, f"paid unknown-forms diverged: {scores}"
        r = ranker.rank_opportunity(base, _opp("paid-test", paid=None))
        assert "opportunity.paid" in r.unknowns

    def test_unknown_intl_not_silently_omitted(self, snapshot_env):
        profile = _profile(international_student=True)
        listing = client.post("/api/matches", json=profile).json()
        unknown_intl_ids = {
            o["id"] for o in snapshot_env["corpus"]
            if o["eligibility"].get("international_friendly") == "unknown"
        }
        served = {r["opportunity_id"] for r in listing["results"]}
        assert unknown_intl_ids & served, (
            "verify-don't-rule-out: unknown-intl records must stay visible"
        )
        for r in listing["results"]:
            if r["opportunity_id"] in unknown_intl_ids:
                assert "opportunity.international_friendly" in r["unknowns"]

    def test_min_gpa_surfaces_as_unknown_and_never_scores(self):
        base = _profile()
        with_gpa = ranker.rank_opportunity(
            base, _opp("gpa-test", eligibility={
                "preferred_year": ["sophomore"], "majors": ["CS"],
                "skills_required": ["Python"], "international_friendly": "yes",
                "min_gpa": 3.7,
            })
        )
        without_gpa = ranker.rank_opportunity(
            base, _opp("gpa-test", eligibility={
                "preferred_year": ["sophomore"], "majors": ["CS"],
                "skills_required": ["Python"], "international_friendly": "yes",
            })
        )
        assert with_gpa.final_score == without_gpa.final_score
        assert "profile.gpa" in with_gpa.unknowns
        assert "profile.gpa" not in without_gpa.unknowns

    def test_open_majors_never_emits_empty_prefers_gap(self):
        r = ranker.rank_opportunity(
            _profile(major="History"),
            _opp("open-majors", eligibility={
                "preferred_year": ["sophomore"], "majors": [],
                "skills_required": [], "international_friendly": "yes",
            }),
        )
        assert not any(g.startswith("Prefers") for g in r.reasons_gap)
        assert "opportunity.majors" in r.unknowns

    def test_null_subobjects_survive_ranking(self):
        o = _opp("null-subs")
        o["eligibility"] = None
        o["application"] = None
        o["metadata"] = None
        r = ranker.rank_opportunity(_profile(), o)
        assert 0.0 <= r.final_score <= 100.0
        results = ranker.rank_all(_profile(), [o, _opp("normal")])
        assert {x.opportunity_id for x in results} >= {"null-subs", "normal"}

    def test_hard_exclusion_shared_codes(self):
        ctx = ranker._filter_context(_profile(international_student=True))
        assert ranker.hard_exclusion(
            _opp("x", metadata={"is_active": False}), ctx) == "inactive"
        assert ranker.hard_exclusion(
            _opp("x", school="ucb", audience="campus"), ctx) == "other_school_campus"
        restricted = _opp("x")
        restricted["eligibility"]["international_friendly"] = "no"
        assert ranker.hard_exclusion(restricted, ctx) == "citizenship_restricted"
        assert ranker.hard_exclusion(_opp("x"), ctx) is None


class TestCorpusDedup:
    @pytest.fixture
    def _reset_loader(self):
        from src.matcher import embeddings

        saved = (
            data_loader._opp_cache,
            data_loader._opp_cache_by_id,
            data_loader._opp_cache_mtime,
            data_loader._opp_cache_generation,
            data_loader._tfidf_fitted_mtime,
            embeddings._tfidf_vectorizer,
            embeddings._tfidf_fitted,
            ranker._corpus_ref,
            ranker._corpus_rows,
            ranker._static_cache,
            ranker._sim_matrix,
            dict(ranker._kw_word_res),
        )
        data_loader._opp_cache = []
        data_loader._opp_cache_by_id = {}
        data_loader._opp_cache_mtime = 0
        yield
        (
            data_loader._opp_cache,
            data_loader._opp_cache_by_id,
            data_loader._opp_cache_mtime,
            data_loader._opp_cache_generation,
            data_loader._tfidf_fitted_mtime,
            embeddings._tfidf_vectorizer,
            embeddings._tfidf_fitted,
            ranker._corpus_ref,
            ranker._corpus_rows,
            ranker._static_cache,
            ranker._sim_matrix,
            old_keyword_res,
        ) = saved
        ranker._kw_word_res.clear()
        ranker._kw_word_res.update(old_keyword_res)

    def test_duplicate_id_across_shards_loads_once(self, tmp_path, monkeypatch, _reset_loader):
        shards = tmp_path / "shards"
        shards.mkdir()
        a = [_opp("dup-1", title="From shard A"), _opp("uniq-a")]
        b = [_opp("dup-1", title="From shard B"), _opp("uniq-b")]
        (shards / "a.json").write_text(json.dumps(a))
        (shards / "b.json").write_text(json.dumps(b))
        monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)

        loaded = data_loader.load_opportunities()
        ids = [o["id"] for o in loaded]
        assert len(ids) == len(set(ids)) == 3
        assert ids == sorted(ids), "corpus must be id-sorted for deterministic paging"
        # First occurrence wins, and the by-id map points at the SAME record
        # the list serves — never a second interpretation of the identity.
        by_id = data_loader.load_opportunities_by_id()
        dup = next(o for o in loaded if o["id"] == "dup-1")
        assert by_id["dup-1"] is dup
        assert dup["title"] == "From shard A"

    def test_corpus_version_tracks_load(self, tmp_path, monkeypatch, _reset_loader):
        shards = tmp_path / "shards"
        shards.mkdir()
        (shards / "a.json").write_text(
            json.dumps([
                _opp("v-1", title="Machine learning laboratory"),
                _opp("v-2", title="Quantum materials laboratory"),
            ])
        )
        monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
        data_loader.load_opportunities()
        assert data_loader.corpus_version() != "0.000000"


class TestLlmRerankCanonicalOrder:
    def test_blend_ties_resolved_actionable_then_id(self, monkeypatch):
        monkeypatch.setattr(m_module, "_resolve", lambda name: object())
        monkeypatch.setattr(
            m_module, "_llm_score_candidates",
            lambda q, cand: {i: {"s": 50.0, "r": ""} for i, _ in cand},
        )
        m_module._llm_rerank_cache.clear()

        def result(ident, score, actionable):
            return ranker.MatchResult(
                opportunity_id=ident, eligibility_score=score, readiness_score=score,
                upside_score=score, final_score=score, bucket="reach",
                reasons_fit=[], reasons_gap=[], next_steps=[], actionable=actionable,
            )

        results = [
            result("c-dead", 60.0, False),
            result("b-live", 60.0, True),
            result("a-live", 60.0, True),
        ]
        lookup = {r.opportunity_id: _opp(r.opportunity_id) for r in results}
        out = m_module.llm_rerank(
            {"research_interests_text": "tie-break-query"}, results, lookup
        ).results
        assert [r.opportunity_id for r in out] == ["a-live", "b-live", "c-dead"]


class TestOpportunitiesSurfaceConsistency:
    @pytest.fixture
    def browse_corpus(self, monkeypatch):
        from datetime import date, timedelta

        import backend.routes.opportunities as o_module
        soon = (date.today() + timedelta(days=30)).isoformat()
        corpus = sorted(
            [
                _opp("z-active", opportunity_type="summer_program", deadline=soon),
                _opp("a-active", opportunity_type="summer_program", deadline=soon),
                _opp("m-retired", opportunity_type="summer_program",
                     deadline=soon, metadata={"is_active": False}),
            ],
            key=lambda o: o["id"],
        )
        monkeypatch.setattr(o_module, "load_opportunities", lambda: corpus)
        monkeypatch.setattr(
            o_module, "load_opportunities_by_id", lambda: {o["id"]: o for o in corpus}
        )
        return corpus

    def test_inactive_excluded_from_list_but_detail_resolves(self, browse_corpus):
        body = client.get("/api/opportunities?opportunity_type=summer_program").json()
        ids = [o["id"] for o in body["opportunities"]]
        assert "m-retired" not in ids
        assert body["total"] == len(ids) == 2
        # Saved links keep working: direct id fetch still resolves. Asked with
        # the current release scope because the rollout bridge serves a
        # historical record only to a client that has declared it can read a
        # target truth; what is under test here is that the record resolves at
        # all, not which clients may read it.
        detail = client.get(
            "/api/opportunities/m-retired",
            params={
                "_release_scope":
                    "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2",
            },
        )
        assert detail.status_code == 200

    def test_upcoming_excludes_inactive_and_tie_breaks_by_id(self, browse_corpus):
        body = client.get("/api/opportunities/upcoming?days=60").json()
        ids = [o["id"] for o in body["opportunities"]]
        assert "m-retired" not in ids
        assert ids == sorted(ids), "equal deadlines must order by id"
        assert body["total"] == len(ids)

    def test_similar_total_is_found_count_not_page_size(self, browse_corpus):
        body = client.get("/api/opportunities/a-active/similar?limit=1").json()
        assert len(body["opportunities"]) <= 1
        assert body["total"] >= len(body["opportunities"])


TRUTH_KEYS = {
    "listing_state", "reference_only", "actionable", "accepting_state",
    "reason_code", "verified_at", "expires_at",
}

# One record per way a target can be dead, alongside two live ones. Built
# here rather than sampled from the served corpus: a shard refresh changes
# which shapes happen to be present, and a test that quietly stops covering
# `reference_only` because the data moved is worse than no test.
_DEAD_SHAPES = {
    "m-closed": {"metadata": {"is_active": True, "urap_status": "closed"}},
    "m-reference": {"metadata": {"is_active": True, "reference_only": True}},
    "m-inactive": {"metadata": {"is_active": False}},
    "m-faculty-stop": {
        "source_type": "faculty_research",
        "description_raw": "I am not currently accepting undergraduate students.",
        "metadata": {"is_active": True},
    },
    # Nobody has reviewed what this is, and it looks exactly like a live paid
    # on-campus listing in every field a surface might read. The truth is the
    # only thing standing between it and the ranked universe.
    "m-unreviewed": {
        "source_type": None,
        "paid": "yes",
        "on_campus": True,
        "is_rolling": True,
        "deadline": "2099-12-31",
        "deadline_is_estimate": False,
        "posted_date": "2099-01-01",
        "eligibility": {
            "preferred_year": ["sophomore"],
            "majors": ["CS"],
            "skills_required": ["Python"],
            "international_friendly": "yes",
        },
        "application": {"application_url": "https://example.edu/unreviewed/apply"},
        "metadata": {"is_active": True},
    },
}
LIVE_IDS = ["opp-00", "opp-01"]


@pytest.fixture
def mixed_corpus(monkeypatch):
    """Two live records and one of every non-actionable shape."""
    corpus = [_opp(ident) for ident in LIVE_IDS]
    corpus += [_opp(ident, **overrides) for ident, overrides in _DEAD_SHAPES.items()]
    by_id = {o["id"]: o for o in corpus}
    ranker_state = (
        ranker._corpus_ref,
        ranker._corpus_rows,
        ranker._static_cache,
        ranker._sim_matrix,
        dict(ranker._kw_word_res),
    )
    monkeypatch.setattr(
        m_module, "load_opportunities_generation", lambda: (corpus, "mixed-fixture"),
    )
    monkeypatch.setattr(m_module, "load_opportunities_by_id", lambda: by_id)
    ranker.register_corpus(corpus)
    m_module._match_snapshots.clear()
    yield corpus
    m_module._match_snapshots.clear()
    with ranker.corpus_generation_lock:
        (
            ranker._corpus_ref,
            ranker._corpus_rows,
            ranker._static_cache,
            ranker._sim_matrix,
            old_keyword_res,
        ) = ranker_state
        ranker._kw_word_res.clear()
        ranker._kw_word_res.update(old_keyword_res)


def _view_body(**view):
    return {
        "profile": _profile(),
        "view": {"today": "2026-08-20", **view},
        "page_size": 50,
    }


class TestMatchResponsesAttestToTheirOwnContract:
    """What a client is entitled to assume, asserted at the endpoint.

    A response carrying the marker is a promise: every row has a complete
    target truth and every historical record has already been removed. The
    frontend's shared validator refuses any page that fails this, so a backend
    that stamped the marker onto a page it had not filtered would take the
    whole Results view down rather than degrade quietly.
    """

    def test_a_normal_page_states_both_versions(self, mixed_corpus):
        body = client.post("/api/matches", json=_profile()).json()

        assert body["contract_version"] == "match-page-v3-faculty-trust"
        assert body["target_truth_contract"] == "target-truth-v2"

    def test_the_view_endpoint_states_its_own_wire_version_and_the_same_marker(
        self, mixed_corpus,
    ):
        body = client.post("/api/matches/view", json=_view_body()).json()

        assert body["contract_version"] == "match-view-v3-faculty-trust"
        assert body["target_truth_contract"] == "target-truth-v2"

    @pytest.mark.parametrize("path", ["/api/matches", "/api/matches/view"])
    def test_every_row_carries_a_complete_actionable_truth(self, path, mixed_corpus):
        body = (
            client.post(path, json=_view_body()).json()
            if path.endswith("/view")
            else client.post(path, json=_profile()).json()
        )

        assert body["results"], "the fixture has live records to return"
        for row in body["results"]:
            opportunity = row["opportunity"]
            truth = opportunity.get("target_truth")
            assert truth is not None, row["opportunity_id"]
            # Exactly seven: a missing key breaks the client's parser, and an
            # extra one means an internal evidence pointer rode along.
            assert set(truth) == TRUTH_KEYS, row["opportunity_id"]
            assert truth["actionable"] is True, row["opportunity_id"]
            # The client keys favourites, compare and export off the outer id
            # while rendering from the nested record. A drift between them
            # exports one target's fields under another's identity.
            assert row["opportunity_id"] == opportunity["id"]

    @pytest.mark.parametrize("path", ["/api/matches", "/api/matches/view"])
    def test_no_dead_shape_survives_into_a_response(self, path, mixed_corpus):
        body = (
            client.post(path, json=_view_body()).json()
            if path.endswith("/view")
            else client.post(path, json=_profile()).json()
        )
        returned = {row["opportunity_id"] for row in body["results"]}

        assert returned == set(LIVE_IDS)
        for dead in _DEAD_SHAPES:
            assert dead not in returned, dead

    def test_the_counts_describe_the_same_universe_the_rows_came_from(
        self, mixed_corpus,
    ):
        """Totals padded with dead records are the subtler half of the bug.

        Filtering only the rows would leave "247 matches" above a list the
        student can never page to — and the bucket counts driving the tabs
        would be counting targets that are gone.
        """
        body = client.post("/api/matches", json=_profile()).json()
        buckets = ("high_priority", "good_match", "reach", "low_fit")

        assert body["total"] == len(LIVE_IDS)
        assert sum(body[b] for b in buckets) == len(LIVE_IDS)
        assert body["field_relevant_count"] <= len(LIVE_IDS)

    def test_the_view_counts_and_facets_exclude_them_too(self, mixed_corpus):
        body = client.post("/api/matches/view", json=_view_body()).json()

        assert body["filtered_total"] == len(LIVE_IDS)
        assert body["view_counts"]["all"] == len(LIVE_IDS)
        facet_total = sum(f["count"] for f in body["source_facets"])
        assert facet_total <= len(LIVE_IDS)
        assert sum(body["deadline_facets"].values()) <= len(LIVE_IDS)

    def test_an_empty_page_past_the_end_still_carries_the_marker(self, mixed_corpus):
        """The case a row-inspecting client cannot check for itself.

        With no rows there is nothing to examine, so an unmarked empty page is
        indistinguishable from an old backend's — and the client would have to
        either trust it or discard a legitimately empty result.
        """
        body = client.post("/api/matches?offset=9999", json=_profile()).json()

        assert body["results"] == []
        assert body["contract_version"] == "match-page-v3-faculty-trust"
        assert body["target_truth_contract"] == "target-truth-v2"

    def test_a_genuinely_empty_view_still_carries_the_marker(self, mixed_corpus):
        body = client.post(
            "/api/matches/view",
            json=_view_body(tab="starred", favorite_ids=["no-such-record"]),
        ).json()

        assert body["results"] == []
        assert body["filtered_total"] == 0
        assert body["contract_version"] == "match-view-v3-faculty-trust"
        assert body["target_truth_contract"] == "target-truth-v2"

    @pytest.mark.parametrize(
        ("label", "cursor", "status"),
        [
            # Structurally unreadable: not our encoding at all. A malformed
            # request is 400 — the server rejects it, nothing conflicts.
            ("invalid", "not-a-real-cursor", 400),
            # Well-formed and correctly signed, but naming a result set this
            # process no longer holds — the shape a client gets after a backend
            # restart or a snapshot TTL expiry. 409, because the request is
            # fine and the state it refers to is what moved.
            ("expired", None, 409),
        ],
    )
    @pytest.mark.parametrize("path", ["/api/matches", "/api/matches/view"])
    def test_a_dead_cursor_never_asks_the_client_to_retry_it(
        self, path, label, cursor, status, mixed_corpus,
    ):
        """Asserted on the real response, not on the constant in the source.

        `retryable: true` here would be a loop: the same cursor fails the same
        way forever, and the client's automatic retry turns one dead page into
        sustained traffic. Recovery is a fresh page-1 request, which the
        frontend does once — so the flag has to say "do not repeat this".
        """
        if cursor is None:
            # Mint a real signed cursor, then drop the snapshot it points at.
            # page_size 1 on both endpoints: the mixed fixture holds two live
            # records, so a default page would return everything and there
            # would be no next_cursor to expire.
            live = (
                client.post(path, json={**_view_body(), "page_size": 1}).json()
                if path.endswith("/view")
                else client.post("/api/matches?limit=1", json=_profile()).json()
            )
            cursor = live["next_cursor"]
            assert cursor, f"{path}: fixture must produce a second page"
            m_module._match_snapshots.clear()

        if path.endswith("/view"):
            body = {**_view_body(), "page_size": 1, "cursor": cursor}
            response = client.post(path, json=body)
        else:
            response = client.post(f"{path}?cursor={cursor}", json=_profile())

        assert response.status_code == status, f"{path}/{label}"
        detail = response.json()["detail"]
        assert detail["code"] == f"MATCH_CURSOR_{label.upper()}", f"{path}/{label}"
        assert detail["retryable"] is False, f"{path}/{label}"

    def test_the_marker_has_no_default_to_fall_back_to(self):
        """A forgotten field must fail loudly at the server, not silently.

        With `= ""` a new construction site that omitted it would serve a
        page claiming nothing, and every client would correctly refuse it —
        an outage discovered in production instead of at the type level.
        """
        import pydantic
        import pytest as _pytest

        from backend.schemas import MatchesResponse

        field = MatchesResponse.model_fields["target_truth_contract"]
        assert field.is_required(), "target_truth_contract must be required"
        with _pytest.raises(pydantic.ValidationError):
            MatchesResponse(
                total=0, high_priority=0, good_match=0, reach=0, low_fit=0,
                results=[], contract_version="match-page-v3-faculty-trust",
            )
