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

import pytest
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
    monkeypatch.setattr(m_module, "load_opportunities", lambda: corpus)
    monkeypatch.setattr(m_module, "load_opportunities_by_id", lambda: by_id)

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
        listing = client.post("/api/matches", json=profile).json()
        # The fake scorer must actually have blended something, or this test
        # would silently degrade into the rule-only comparison.
        assert any(r["ai_reason"] for r in listing["results"])
        self._assert_identical(listing, profile)

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
        monkeypatch.setattr(m_module, "load_opportunities", lambda: corpus)
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

    def test_matcher_version_served_and_stable(self, snapshot_env):
        listing = client.post("/api/matches", json=_profile()).json()
        assert listing["matcher_version"] == MATCHER_VERSION
        assert MATCHER_VERSION  # non-empty


class TestSnapshotPagination:
    def test_repeated_requests_identical_order(self, snapshot_env):
        profile = _profile()
        first = client.post("/api/matches", json=profile).json()
        second = client.post("/api/matches", json=profile).json()
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
        monkeypatch.setattr(m_module, "load_opportunities", lambda: swapped)
        monkeypatch.setattr(
            m_module, "load_opportunities_by_id", lambda: {o["id"]: o for o in swapped}
        )
        snap2 = asyncio.run(m_module._get_or_compute_snapshot(profile_dict, False))
        assert snap2 is not snap1
        assert snap2.corpus_ref is swapped

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
        saved = (
            data_loader._opp_cache,
            data_loader._opp_cache_by_id,
            data_loader._opp_cache_mtime,
        )
        data_loader._opp_cache = []
        data_loader._opp_cache_by_id = {}
        data_loader._opp_cache_mtime = 0
        yield
        (
            data_loader._opp_cache,
            data_loader._opp_cache_by_id,
            data_loader._opp_cache_mtime,
        ) = saved

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
        (shards / "a.json").write_text(json.dumps([_opp("v-1")]))
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
        )
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
        # Saved links keep working: direct id fetch still resolves.
        detail = client.get("/api/opportunities/m-retired")
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
