"""Selected types bound the Match universe, independently of major fit.

Synthetic, deterministic records only; no provider or production data calls.
The shared ProfileRequest stays usable by material-generation endpoints.
"""
from itertools import combinations

import pytest
from fastapi.testclient import TestClient

from backend import main as main_module
from backend.main import app
from backend.routes import matches
from backend.schemas import ProfileRequest
from src.matcher import ranker

RELEASE_CONTRACT_TESTS = True
TYPES = ("research", "summer_program", "internship")
SELECTIONS = [list(items) for size in range(1, 4) for items in combinations(TYPES, size)]
client = TestClient(app)


def _profile(**overrides):
    return {
        "year": "sophomore", "major": "CS", "home_school": "uiuc",
        "seeking_type": ["research"], "international_student": False,
        "hard_skills": [{"name": "Python", "level": "experienced"}],
        "resume_ready": True, "experience_level": "some", "can_cold_email": True,
        "preferences": {"min_match_threshold": 0},
        **overrides,
    }


def _opp(kind, ident=None, majors=None):
    return {
        "id": ident or kind, "title": "Computer science research and training",
        "source_type": "campus_program", "school": "uiuc", "audience": "campus",
        "opportunity_type": kind, "organization": "Test University",
        "keywords": ["computer science"], "paid": "yes", "on_campus": True,
        "is_rolling": True, "url": "https://example.edu/apply",
        "description_raw": "Python research with mentorship and training.",
        "eligibility": {
            "preferred_year": ["sophomore"], "majors": ["CS"] if majors is None else majors,
            "skills_required": ["Python"], "international_friendly": "yes",
        },
        "application": {"contact_method": "portal", "application_effort": "medium",
                        "application_url": "https://example.edu/apply"},
        "metadata": {"is_active": True},
    }


@pytest.mark.parametrize("selection", SELECTIONS)
@pytest.mark.parametrize("majors", [["CS"], ["ECE"], []], ids=["same-major", "related-major", "open-major"])
def test_all_seven_type_selections_are_strict_regardless_of_major(selection, majors):
    ctx = ranker._filter_context(_profile(seeking_type=selection))
    for kind in [*TYPES, "unknown", "", None]:
        expected = None if kind in selection else "seeking_type_mismatch"
        assert ranker.hard_exclusion(_opp(kind, ident="candidate", majors=majors), ctx) == expected


def test_aliases_duplicates_and_order_preserve_the_selected_universe():
    ctx = ranker._filter_context(_profile(seeking_type=["Summer program", " RESEARCH ", "research"]))
    assert ranker.hard_exclusion(_opp("Research"), ctx) is None
    assert ranker.hard_exclusion(_opp("summer-program"), ctx) is None
    assert ranker.hard_exclusion(_opp("internship"), ctx) == "seeking_type_mismatch"


@pytest.fixture
def match_corpus(monkeypatch):
    corpus = [_opp(kind) for kind in TYPES] + [_opp("unknown"), _opp("", ident="untyped")]
    # Explain belongs to the dormant Compare surface. Exercise its shared
    # implementation without changing the production gate or AI acceptance.
    enabled = main_module.feature_enabled
    monkeypatch.setattr(main_module, "feature_enabled", lambda feature: feature == "compare" or enabled(feature))
    state = (ranker._corpus_ref, ranker._corpus_rows, ranker._static_cache,
             ranker._sim_matrix, dict(ranker._kw_word_res))
    ranker.register_corpus(corpus)
    monkeypatch.setattr(matches, "load_opportunities_generation", lambda: (corpus, "type-selection-fixture"))
    monkeypatch.setattr(matches, "load_opportunities_by_id", lambda: {o["id"]: o for o in corpus})
    monkeypatch.setattr(matches, "corpus_version", lambda: "type-selection-fixture")
    monkeypatch.setattr(matches, "_SNAPSHOT_TTL_SECONDS", 300)
    monkeypatch.setattr(matches, "_active_corpus_identity", None)

    def no_provider(*_args, **_kwargs):
        raise AssertionError("type selection must not call a provider")

    monkeypatch.setattr(matches, "chat_completion", no_provider)
    monkeypatch.setattr(matches, "_llm_score_candidates", no_provider)
    matches._match_snapshots.clear()
    yield corpus
    matches._match_snapshots.clear()
    with ranker.corpus_generation_lock:
        (ranker._corpus_ref, ranker._corpus_rows, ranker._static_cache,
         ranker._sim_matrix, old_keyword_res) = state
        ranker._kw_word_res.clear()
        ranker._kw_word_res.update(old_keyword_res)


def _pages(profile, *, view=False):
    cursor = None
    rows = []
    bodies = []
    for _ in range(10):
        if view:
            body = {"profile": profile, "view": {"today": "2026-09-24"}, "page_size": 1}
            if cursor:
                body["cursor"] = cursor
            response = client.post("/api/matches/view", json=body)
        else:
            params = {"limit": 1}
            if cursor:
                params["cursor"] = cursor
            response = client.post("/api/matches", params=params, json=profile)
        assert response.status_code == 200, response.text
        body = response.json()
        bodies.append(body)
        rows.extend(body["results"])
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
        assert cursor
    else:
        pytest.fail("bounded fixture pagination did not end")
    return rows, bodies


@pytest.mark.parametrize("selection", SELECTIONS)
def test_match_view_pages_counts_and_explain_share_the_selected_universe(match_corpus, selection):
    profile = _profile(seeking_type=selection)
    rows, pages = _pages(profile)
    view_rows, view_pages = _pages(profile, view=True)
    expected_ids = set(selection)
    assert {row["opportunity_id"] for row in rows} == expected_ids
    assert len(rows) == len(expected_ids)
    assert [row["opportunity_id"] for row in view_rows] == [row["opportunity_id"] for row in rows]
    for body in pages + view_pages:
        assert body["total"] == len(expected_ids)
        assert body["high_priority"] + body["good_match"] + body["reach"] == len(expected_ids)
        assert body["low_fit"] == 0
        assert body["result_set_id"] == pages[0]["result_set_id"]
        assert body["returned_count"] == len(body["results"])
    for body in view_pages:
        assert body["filtered_total"] == len(expected_ids)
        assert body["view_counts"]["all"] == len(expected_ids)

    selected = {row["opportunity_id"]: row for row in rows}
    for opportunity in match_corpus:
        ident = opportunity["id"]
        response = client.post(f"/api/matches/{ident}/explain", json=profile)
        assert response.status_code == 200, response.text
        explanation = response.json()
        assert explanation["in_results"] is (ident in expected_ids)
        if ident in expected_ids:
            assert explanation["excluded_reason"] is None
            assert explanation["final_score"] == selected[ident]["final_score"]
            assert explanation["bucket"] == selected[ident]["bucket"]
        else:
            assert explanation["excluded_reason"] == "seeking_type_mismatch"
            assert "selected opportunity types" in explanation["reasons_gap"][0]


@pytest.mark.parametrize("empty", [[], ["", "  "]])
@pytest.mark.parametrize("endpoint", ["/api/matches", "/api/matches/view", "/api/matches/research/explain"])
def test_explicit_empty_selection_is_rejected_before_ranking(match_corpus, monkeypatch, empty, endpoint):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("empty selections must not compute snapshots or pay providers")

    monkeypatch.setattr(matches, "_get_or_compute_snapshot", forbidden)
    profile = _profile(seeking_type=empty)
    body = {"profile": profile, "view": {"today": "2026-09-24"}} if endpoint.endswith("/view") else profile
    response = client.post(endpoint, json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "MATCH_TYPE_REQUIRED", "message": "Select at least one opportunity type.", "retryable": False,
    }
    # The same shared profile remains valid for Tailor/ColdEmail etc.
    assert ProfileRequest(**profile).seeking_type == empty


def test_omitted_selection_preserves_legacy_defaults_on_all_match_surfaces(match_corpus):
    legacy = _profile()
    legacy.pop("seeking_type")
    defaulted = {**legacy, "seeking_type": ["research", "summer_program"]}
    legacy_rows, legacy_pages = _pages(legacy)
    explicit_rows, explicit_pages = _pages(defaulted, view=True)
    assert {row["opportunity_id"] for row in legacy_rows} == {"research", "summer_program"}
    assert legacy_rows == explicit_rows
    assert legacy_pages[0]["result_set_id"] == explicit_pages[0]["result_set_id"]
    for kind in TYPES:
        response = client.post(f"/api/matches/{kind}/explain", json=legacy)
        assert response.status_code == 200
        assert response.json()["in_results"] is (kind != "internship")


@pytest.mark.parametrize("selection", [["fellowship", " Fellowship "], ["fellowship", "  "]])
def test_hidden_fellowship_only_legacy_fallback_is_retained(selection):
    # Deliberately retain the dormant feature-gate compatibility contract;
    # it is different from actively cancelling all three visible controls.
    profile = ProfileRequest(seeking_type=selection)
    assert matches._normalized_profile(profile)["seeking_type"] == ["research", "summer_program"]


def test_switching_selected_types_invalidates_existing_match_cursors(match_corpus):
    profile = _profile(seeking_type=list(TYPES))
    first = client.post("/api/matches?limit=1", json=profile).json()
    assert first["next_cursor"]
    response = client.post("/api/matches", params={"limit": 1, "cursor": first["next_cursor"]},
                           json=_profile(seeking_type=["research"]))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MATCH_CURSOR_EXPIRED"
