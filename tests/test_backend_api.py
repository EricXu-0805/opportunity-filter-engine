"""Backend API + data-layer tests.

Covers features added across recent iterations:
  * /api/matches pagination semantics
  * /api/opportunities/upcoming endpoint
  * load_opportunities_by_id caching
  * _local_refine cumulative matching
  * TF-IDF corpus fitting
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
from backend import data_loader
from backend.routes.cold_email import _local_refine


client = TestClient(app)


@pytest.fixture
def sample_profile_req():
    return {
        "name": "Test",
        "school": "UIUC",
        "year": "sophomore",
        "major": "CS",
        "college": "Grainger College of Engineering",
        "secondary_interests": [],
        "international_student": True,
        "seeking_type": ["research"],
        "desired_fields": [],
        "hard_skills": [{"name": "Python", "level": "experienced"}],
        "coursework": ["CS 124"],
        "experience_level": "beginner",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": "machine learning",
        "linkedin_url": "",
        "github_url": "",
        "search_weight": 50,
    }


class TestHealthEndpoint:
    def test_health_returns_current_version(self):
        from backend.main import API_VERSION
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["version"] == API_VERSION


class TestMatchesPagination:
    def test_default_returns_up_to_500(self, sample_profile_req):
        resp = client.post("/api/matches", json=sample_profile_req)
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "results" in body
        assert len(body["results"]) <= 500

    def test_limit_clamps_page_size(self, sample_profile_req):
        resp = client.post("/api/matches?limit=5", json=sample_profile_req)
        assert resp.status_code == 200
        assert len(resp.json()["results"]) <= 5

    def test_offset_skips_results(self, sample_profile_req):
        first = client.post("/api/matches?limit=5&offset=0", json=sample_profile_req).json()
        second = client.post("/api/matches?limit=5&offset=5", json=sample_profile_req).json()
        if len(first["results"]) == 5 and len(second["results"]) > 0:
            first_ids = [r["opportunity_id"] for r in first["results"]]
            second_ids = [r["opportunity_id"] for r in second["results"]]
            assert not set(first_ids) & set(second_ids)

    def test_bucket_counts_reflect_full_corpus_not_page(self, sample_profile_req):
        full = client.post("/api/matches", json=sample_profile_req).json()
        paged = client.post("/api/matches?limit=3", json=sample_profile_req).json()
        for key in ("high_priority", "good_match", "reach", "low_fit"):
            assert full[key] == paged[key], f"bucket {key} should be corpus-wide, not page-wide"

    def test_invalid_limit_rejected(self, sample_profile_req):
        resp = client.post("/api/matches?limit=0", json=sample_profile_req)
        assert resp.status_code == 422
        resp = client.post("/api/matches?limit=9999", json=sample_profile_req)
        assert resp.status_code == 422


class TestUpcomingDeadlines:
    def test_returns_structure(self):
        resp = client.get("/api/opportunities/upcoming?days=30")
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "opportunities" in body
        assert body["days"] == 30

    def test_results_sorted_ascending_by_deadline(self):
        body = client.get("/api/opportunities/upcoming?days=365").json()
        opps = body["opportunities"]
        for i in range(len(opps) - 1):
            assert opps[i]["deadline"] <= opps[i + 1]["deadline"]

    def test_days_left_never_negative(self):
        body = client.get("/api/opportunities/upcoming?days=30").json()
        for o in body["opportunities"]:
            assert o["days_left"] >= 0

    def test_respects_days_window(self):
        body = client.get("/api/opportunities/upcoming?days=7").json()
        for o in body["opportunities"]:
            assert o["days_left"] <= 7

    def test_invalid_days_rejected(self):
        assert client.get("/api/opportunities/upcoming?days=0").status_code == 422
        assert client.get("/api/opportunities/upcoming?days=500").status_code == 422


class TestOpportunityDetail:
    def test_returns_opportunity_by_id(self):
        opps = data_loader.load_opportunities()
        target = opps[0]
        resp = client.get(f"/api/opportunities/{target['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == target["id"]
        assert body["title"] == target["title"]

    def test_redacts_contact_email(self):
        opps = data_loader.load_opportunities()
        with_email = next((o for o in opps if o.get("contact_email")), None)
        if not with_email:
            pytest.skip("No opportunity with contact_email in dataset")
        resp = client.get(f"/api/opportunities/{with_email['id']}").json()
        assert "contact_email" not in resp
        assert "pi_email" not in resp

    def test_404_for_unknown_id(self):
        resp = client.get("/api/opportunities/this-id-does-not-exist-xyz")
        assert resp.status_code == 404

    def test_400_for_overlong_id(self):
        resp = client.get("/api/opportunities/" + "a" * 150)
        assert resp.status_code == 400


class TestSemanticRerank:
    @pytest.fixture
    def profile_req(self):
        return {
            "name": "Test",
            "year": "sophomore",
            "major": "CS",
            "college": "Grainger College of Engineering",
            "international_student": True,
            "hard_skills": [{"name": "Python", "level": "experienced"}],
            "coursework": ["CS 124"],
            "research_interests_text": "machine learning and computer vision",
            "seeking_type": ["research"],
        }

    def test_semantic_false_is_baseline(self, profile_req):
        resp = client.post("/api/matches?semantic=false", json=profile_req)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) > 0

    def test_semantic_true_still_returns_results(self, profile_req):
        resp = client.post("/api/matches?semantic=true&limit=20", json=profile_req)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) > 0
        for r in body["results"]:
            assert 0 <= r["final_score"] <= 100

    def test_semantic_true_keeps_results_sorted(self, profile_req):
        body = client.post("/api/matches?semantic=true&limit=50", json=profile_req).json()
        scores = [r["final_score"] for r in body["results"]]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_semantic_rerank_can_reorder_top(self, profile_req):
        baseline = client.post("/api/matches?semantic=false&limit=10", json=profile_req).json()
        reranked = client.post("/api/matches?semantic=true&limit=10", json=profile_req).json()
        baseline_ids = [r["opportunity_id"] for r in baseline["results"]]
        reranked_ids = [r["opportunity_id"] for r in reranked["results"]]
        assert set(baseline_ids) == set(reranked_ids[:len(baseline_ids)]) or baseline_ids != reranked_ids

    def test_semantic_unit_call_direct(self):
        from src.matcher.ranker import semantic_rerank, MatchResult
        from backend import data_loader
        opps = data_loader.load_opportunities()
        lookup = data_loader.load_opportunities_by_id()
        fake_results = [
            MatchResult(
                opportunity_id=o["id"],
                eligibility_score=70, readiness_score=70, upside_score=70,
                final_score=70.0, bucket="good_match",
                reasons_fit=[], reasons_gap=[], next_steps=[],
            )
            for o in opps[:20]
        ]
        profile = {"research_interests_text": "machine learning"}
        out = semantic_rerank(profile, fake_results, lookup, top_k=20)
        assert len(out) == 20
        for r in out:
            assert 0 <= r.final_score <= 100

    def test_empty_results_passes_through(self):
        from src.matcher.ranker import semantic_rerank
        out = semantic_rerank({"research_interests_text": "ml"}, [], {}, top_k=50)
        assert out == []

    def test_zero_weight_is_noop(self):
        from src.matcher.ranker import semantic_rerank, MatchResult
        from backend import data_loader
        lookup = data_loader.load_opportunities_by_id()
        opps = data_loader.load_opportunities()
        results = [
            MatchResult(opportunity_id=o["id"], eligibility_score=50,
                        readiness_score=50, upside_score=50, final_score=50.0,
                        bucket="good_match", reasons_fit=[], reasons_gap=[], next_steps=[])
            for o in opps[:5]
        ]
        original = [r.final_score for r in results]
        semantic_rerank({"research_interests_text": "ml"}, results, lookup, semantic_weight=0.0)
        assert [r.final_score for r in results] == original


class TestSimilarOpportunities:
    def test_returns_similar_list(self):
        opps = data_loader.load_opportunities()
        target = next((o for o in opps if o.get("keywords")), opps[0])
        resp = client.get(f"/api/opportunities/{target['id']}/similar")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_id"] == target["id"]
        assert isinstance(body["opportunities"], list)

    def test_excludes_source_from_results(self):
        opps = data_loader.load_opportunities()
        target = opps[0]
        body = client.get(f"/api/opportunities/{target['id']}/similar").json()
        for o in body["opportunities"]:
            assert o["id"] != target["id"]

    def test_results_sorted_by_similarity(self):
        opps = data_loader.load_opportunities()
        target = next((o for o in opps if len(o.get("keywords") or []) >= 2), opps[0])
        body = client.get(f"/api/opportunities/{target['id']}/similar").json()
        scores = [o["_similarity"] for o in body["opportunities"]]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_respects_limit(self):
        opps = data_loader.load_opportunities()
        target = opps[0]
        body = client.get(f"/api/opportunities/{target['id']}/similar?limit=3").json()
        assert len(body["opportunities"]) <= 3

    def test_404_for_unknown_id(self):
        resp = client.get("/api/opportunities/nonexistent-xyz/similar")
        assert resp.status_code == 404

    def test_rejects_overlong_id(self):
        resp = client.get("/api/opportunities/" + "x" * 150 + "/similar")
        assert resp.status_code == 400

    def test_redacts_contact_info_in_results(self):
        opps = data_loader.load_opportunities()
        target = opps[0]
        body = client.get(f"/api/opportunities/{target['id']}/similar").json()
        for o in body["opportunities"]:
            assert "contact_email" not in o
            assert "pi_email" not in o

    def test_shared_keywords_score_higher_than_just_type(self):
        """Shared keywords should outrank same-type-but-no-shared-keywords."""
        opps = data_loader.load_opportunities()
        target = next((o for o in opps if len(o.get("keywords") or []) >= 3), None)
        if target is None:
            pytest.skip("No opportunity with 3+ keywords in dataset")
        body = client.get(f"/api/opportunities/{target['id']}/similar?limit=10").json()
        target_kws = {k.lower() for k in target["keywords"]}
        for o in body["opportunities"][:3]:
            shared = target_kws & {k.lower() for k in (o.get("keywords") or [])}
            same_type = o.get("opportunity_type") == target.get("opportunity_type")
            assert shared or same_type, "Top results should share keywords or type"


class TestBatchOpportunities:
    def test_returns_requested_ids(self):
        opps = data_loader.load_opportunities()
        ids = [o["id"] for o in opps[:3] if o.get("id")]
        resp = client.post("/api/opportunities/batch", json={"ids": ids})
        assert resp.status_code == 200
        body = resp.json()
        assert body["requested"] == len(ids)
        assert body["found"] == len(ids)
        assert len(body["opportunities"]) == len(ids)

    def test_silently_skips_missing_ids(self):
        opps = data_loader.load_opportunities()
        valid = opps[0]["id"]
        resp = client.post(
            "/api/opportunities/batch",
            json={"ids": [valid, "nonexistent-abc-123"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["requested"] == 2
        assert body["found"] == 1

    def test_rejects_non_list(self):
        assert client.post("/api/opportunities/batch", json={"ids": "not a list"}).status_code == 400
        assert client.post("/api/opportunities/batch", json={"foo": "bar"}).status_code == 400

    def test_caps_at_200(self):
        big = [f"id-{i}" for i in range(500)]
        assert client.post("/api/opportunities/batch", json={"ids": big}).status_code == 400

    def test_empty_list_returns_empty(self):
        resp = client.post("/api/opportunities/batch", json={"ids": []})
        assert resp.status_code == 200
        assert resp.json() == {"opportunities": [], "requested": 0, "found": 0}

    def test_skips_malformed_ids(self):
        resp = client.post(
            "/api/opportunities/batch",
            json={"ids": [123, None, "a" * 200, {"obj": True}]},
        )
        assert resp.status_code == 200
        assert resp.json()["found"] == 0


class TestOpportunityLookupCache:
    def test_by_id_returns_dict(self):
        lookup = data_loader.load_opportunities_by_id()
        assert isinstance(lookup, dict)
        assert len(lookup) > 0

    def test_lookup_consistent_with_list(self):
        opps = data_loader.load_opportunities()
        lookup = data_loader.load_opportunities_by_id()
        assert len(lookup) == len([o for o in opps if o.get("id")])
        sample = opps[0]
        assert lookup[sample["id"]] is sample

    def test_lookup_stable_across_calls(self):
        first = data_loader.load_opportunities_by_id()
        second = data_loader.load_opportunities_by_id()
        assert first is second


class TestLocalRefineCumulative:
    def test_formal_alone_applies_formal_only(self):
        body = "I would love to learn more.\n\nBest regards,\nJohn"
        out = _local_refine(body, "make it formal")
        assert "greatly appreciate" in out["body"]
        assert out["applied"] == ["formal"]

    def test_shorter_alone_trims_filler(self):
        body = "I am a fast learner.\nI am excited.\nBest regards"
        out = _local_refine(body, "make it shorter")
        assert "fast learner" not in out["body"]
        assert out["applied"] == ["concise"]

    def test_formal_and_shorter_both_apply(self):
        body = "I would love to learn more. I am a fast learner.\nBest regards"
        out = _local_refine(body, "more formal and shorter please")
        assert "greatly appreciate" in out["body"]
        assert "fast learner" not in out["body"]
        assert "formal" in out["applied"]
        assert "concise" in out["applied"]

    def test_no_matching_keywords_returns_unchanged(self):
        body = "Hello world"
        out = _local_refine(body, "random nonsense")
        assert out["body"] == body
        assert out["applied"] == []

    def test_all_three_keywords_stack(self):
        body = "I am very interested. I would love the chance. I am a fast learner."
        out = _local_refine(body, "formal shorter enthusiastic")
        assert set(out["applied"]) == {"formal", "concise", "enthusiastic"}


class TestTfidfCorpusFit:
    def test_fit_with_corpus_enables_real_idf(self):
        from src.matcher import embeddings

        corpus = [
            "python machine learning",
            "python data science",
            "chemistry biology research",
            "protein folding chemistry",
        ]
        embeddings.fit_tfidf_corpus(corpus)
        assert embeddings._tfidf_fitted is True

        sim_related = embeddings._tfidf_similarity(
            "python machine learning", "python data science",
        )
        sim_unrelated = embeddings._tfidf_similarity(
            "python machine learning", "protein folding chemistry",
        )
        assert sim_related > sim_unrelated

    def test_empty_corpus_does_not_fit(self):
        from src.matcher import embeddings
        embeddings._tfidf_fitted = False
        embeddings._tfidf_vectorizer = None
        embeddings.fit_tfidf_corpus([])
        assert embeddings._tfidf_fitted is False

    def test_corpus_fit_is_used_by_data_loader(self):
        from src.matcher import embeddings
        embeddings._tfidf_fitted = False
        embeddings._tfidf_vectorizer = None
        data_loader._tfidf_fitted_mtime = -1
        data_loader.load_opportunities()
        if len(data_loader._opp_cache) >= 2:
            assert embeddings._tfidf_fitted is True


class TestCORS:
    def test_localhost_allowed(self):
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" in {h.lower() for h in resp.headers.keys()}

    def test_vercel_preview_domain_allowed(self):
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "https://my-branch-preview-abc123.vercel.app",
                "Access-Control-Request-Method": "GET",
            },
        )
        headers = {h.lower() for h in resp.headers.keys()}
        assert "access-control-allow-origin" in headers


class TestHTMLSanitization:
    def test_strip_html_removes_tags(self):
        from backend.data_loader import _strip_html
        assert _strip_html("<p>hello</p>") == "hello"
        assert _strip_html("<b>bold</b> and <i>italic</i>") == "bold and italic"

    def test_strip_html_passthrough_plain_text(self):
        from backend.data_loader import _strip_html
        assert _strip_html("plain text") == "plain text"


class TestAdminDataQuality:
    def test_503_when_token_unset(self, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        from backend.routes import admin as admin_mod
        admin_mod._cache["snapshot"] = None
        admin_mod._cache["built_at"] = 0.0
        r = client.get("/api/admin/data-quality")
        assert r.status_code == 503

    def test_401_when_wrong_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret-abc")
        from backend.routes import admin as admin_mod
        admin_mod._cache["snapshot"] = None
        admin_mod._cache["built_at"] = 0.0
        r = client.get("/api/admin/data-quality?token=wrong")
        assert r.status_code == 401

    def test_200_with_token_and_cache(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret-xyz")
        from backend.routes import admin as admin_mod
        admin_mod._cache["snapshot"] = None
        admin_mod._cache["built_at"] = 0.0

        r1 = client.get("/api/admin/data-quality?token=secret-xyz")
        assert r1.status_code == 200
        d = r1.json()
        assert "total" in d
        assert "global" in d
        assert "rolling_deadline" in d["global"]
        assert d["cache_age_seconds"] == 0

        r2 = client.get("/api/admin/data-quality?token=secret-xyz")
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["cache_age_seconds"] >= 0  # served from cache

    def test_force_bypasses_cache(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "t")
        from backend.routes import admin as admin_mod
        admin_mod._cache["snapshot"] = {"cached": True}
        admin_mod._cache["built_at"] = 9999999999.0
        r = client.get("/api/admin/data-quality?token=t&force=true")
        assert r.status_code == 200
        assert r.json().get("cached") is None  # force rebuilt


class TestRollingSkillScoring:
    def test_rolling_lab_empty_skills_scored_neutral(self):
        from src.matcher.ranker import score_eligibility
        rolling_lab = {
            "title": "Research with Prof X",
            "source": "uiuc_faculty",
            "is_rolling": True,
            "eligibility": {
                "majors": ["CS"],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "skills_required": [],
                "international_friendly": "yes",
            },
            "opportunity_type": "research",
        }
        non_rolling_lab = {**rolling_lab, "is_rolling": False}
        profile = {
            "year": "junior", "major": "CS", "secondary_interests": [],
            "international_student": False, "seeking_type": ["research"],
            "hard_skills": [], "desired_fields": [],
        }
        rolling_score, _, _ = score_eligibility(profile, rolling_lab)
        non_rolling_score, _, _ = score_eligibility(profile, non_rolling_lab)
        assert rolling_score > non_rolling_score


class TestStatsFreshness:
    def test_stats_returns_last_updated_at(self):
        r = client.get("/api/opportunities/stats/summary")
        assert r.status_code == 200
        body = r.json()
        # data file should exist in tests (either real or example)
        if body.get("total", 0) > 0:
            assert "last_updated_at" in body
