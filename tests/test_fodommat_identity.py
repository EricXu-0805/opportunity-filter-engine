"""One proved project and two durable source IDs, across pagination and alerts."""

import copy
from datetime import date

import pytest

from backend.routes import matches, opportunities
from src import evidence
from src.matcher import ranker
from src.normalizers import fodommat
from src.program_windows import NCSA_DIRECTORY, apply_program_window
from src.saved_searches.filter import matching_ids
from tests.test_match_consistency import _opp, _profile, client, snapshot_env  # noqa: F401
from tests.test_saved_search_digest import AUTH, _digest_row, _install_stubs, _set_digest_env


@pytest.fixture
def programs(monkeypatch):
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 26))
    host_url = "https://reu.ncsa.illinois.edu/"

    def row(oid, source, url, source_url):
        result = _opp(
            oid,
            title="FoDOMMaT",
            source=source,
            opportunity_type="summer_program",
            source_type="summer_program",
            url=url,
            source_url=source_url,
            deadline="2027-02-15",
            description_clean="FoDOMMaT sample program",
            application={"application_url": host_url},
        )
        apply_program_window(result)
        fodommat.apply_requirements(result)
        return result

    return [
        row(fodommat.DIRECTORY_ID, "uiuc_sro", NCSA_DIRECTORY, "https://researchops.web.illinois.edu/?page=11"),
        row(fodommat.HOST_ID, "manual", host_url, host_url),
    ]


def test_only_the_bound_pair_collapses_after_the_students_filters(programs):
    directory, host = programs
    another = {**directory, "id": "different-program-same-URL-title-date"}
    rows = [directory, another, host]
    assert matching_ids(rows, {}, "FoDOMMaT") == [another["id"], host["id"]]
    assert matching_ids(rows, {"source": "uiuc_sro"}) == [directory["id"], another["id"]]
    assert matching_ids(rows, {"source": "manual"}) == [host["id"]]
    assert matching_ids(rows, {}, excluded_ids={host["id"]}) == [directory["id"], another["id"]]
    assert matching_ids(rows, {}, preferred_id=directory["id"]) == [directory["id"], another["id"]]
    for change in ({"deadline": "2028-02-15"}, {"url": host["url"]}, {"source": "manual"}):
        candidate = {**directory, **change}
        assert matching_ids([candidate, host], {}) == [directory["id"], host["id"]]


def test_both_originals_remain_accessible_across_real_match_pages(snapshot_env, monkeypatch, programs):  # noqa: F811
    directory, host = programs
    unrelated = {**directory, "id": "different-project"}
    corpus = [host, unrelated, directory]
    ranker.register_corpus(corpus)
    monkeypatch.setattr(matches, "load_opportunities_generation", lambda: (corpus, "checked-2027-cohort"))
    profile = _profile(seeking_type=["summer_program"])
    profile["preferences"] = {"min_match_threshold": 0}
    view = {"tab": "all", "search_query": "FoDOMMaT", "today": "2027-02-09"}

    def pages(params):
        body = {"profile": profile, "view": {**view, **params}, "page_size": 1}
        ids = []
        while True:
            response = client.post("/api/matches/view", json=body)
            assert response.status_code == 200, response.text
            data = response.json()
            ids.extend(r["opportunity_id"] for r in data["results"])
            if not data["has_more"]:
                assert len(ids) == len(set(ids)) == data["filtered_total"]
                return ids, data
            assert data["next_cursor"] and len(ids) < 4
            body["cursor"] = data["next_cursor"]

    ids, data = pages({})
    assert set(ids) == {host["id"], unrelated["id"]}
    assert data["total"] == data["view_counts"]["all"] == 2
    assert sum(data[k] for k in ("high_priority", "good_match", "reach")) == data["total"]
    assert data["deadline_facets"]["7"] == 2
    assert set(pages({"source": "uiuc_sro"})[0]) == {directory["id"], unrelated["id"]}
    assert pages({"source": "manual"})[0] == [host["id"]]
    assert set(pages({"favorite_ids": [directory["id"]]})[0]) == {directory["id"], unrelated["id"]}
    both = list(fodommat.IDS)
    starred, star_data = pages({"favorite_ids": both, "tab": "starred"})
    assert set(starred) == set(both) and star_data["view_counts"]["starred"] == 2
    assert pages({"dismissed_ids": [host["id"]], "favorite_ids": [directory["id"]], "tab": "starred"})[0] == [
        directory["id"]
    ]
    plain = client.post("/api/matches?limit=1", json=profile).json()
    assert plain["total"] == 2 and plain["has_more"]
    after = client.post("/api/matches", params={"limit": 1, "cursor": plain["next_cursor"]}, json=profile).json()
    assert not after["has_more"]
    assert {item["opportunity_id"] for item in plain["results"] + after["results"]} == {host["id"], unrelated["id"]}


def test_refresh_preserves_legacy_queued_id_without_a_second_notification(monkeypatch, programs):
    _set_digest_env(monkeypatch)
    directory, host = programs
    previous = {
        "id": "same-cohort",
        "device_id": "isolated-test",
        "last_run_at": "2026-11-26T00:00:00Z",
        "last_result_ids": [directory["id"]],
        "new_match_ids": ["missing-from-load", directory["id"]],
        "filters_json": {},
        "query": "FoDOMMaT",
    }
    cases = [
        (previous, [directory["id"]], previous["new_match_ids"]),
        ({**previous, "filters_json": {"source": "manual"}}, [host["id"]], ["missing-from-load"]),
        ({**previous, "new_match_ids": list(fodommat.IDS)}, [host["id"]], [host["id"]]),
    ]
    for row, baseline, queued in cases:
        patches = []
        _install_stubs(monkeypatch, rows=[copy.deepcopy(row)], opportunities=programs, patches=patches)
        response = client.get("/api/cron/saved-searches/refresh", headers=AUTH)
        assert response.status_code == 200 and response.json()["new_matches"] == 0, response.text
        assert patches[0]["json"]["last_result_ids"] == baseline, row
        assert patches[0]["json"]["new_match_ids"] == queued


@pytest.mark.parametrize(
    "source,expected", [("", fodommat.HOST_ID), ("manual", fodommat.HOST_ID), ("uiuc_sro", fodommat.DIRECTORY_ID)]
)
def test_digest_uses_a_single_existing_link_even_before_the_next_refresh(monkeypatch, programs, source, expected):
    _set_digest_env(monkeypatch)
    row = _digest_row(new_match_ids=list(fodommat.IDS), filters_json={"source": source})
    sends, patches = [], []
    _install_stubs(monkeypatch, rows=[row], opportunities=programs, sends=sends, patches=patches)
    response = client.get("/api/cron/saved-searches/digest", headers=AUTH)
    assert response.status_code == 200 and response.json()["sent"] == 1, response.text
    assert len(sends) == 1
    other = next(oid for oid in fodommat.IDS if oid != expected)
    for body in (sends[0]["html"], sends[0]["text"]):
        assert "/opportunities/" + expected in body
        assert "/opportunities/" + other not in body
    assert patches[-1]["json"]["new_match_ids"] == []


def test_digest_does_not_deliver_either_source_after_switching_to_another(monkeypatch, programs):
    _set_digest_env(monkeypatch)
    row = _digest_row(new_match_ids=list(fodommat.IDS), filters_json={"source": "nsf_reu"})
    sends, patches = [], []
    _install_stubs(monkeypatch, rows=[row], opportunities=programs, sends=sends, patches=patches)
    response = client.get("/api/cron/saved-searches/digest", headers=AUTH)
    assert response.status_code == 200 and response.json()["sent"] == 0
    assert not sends and patches[-1]["json"]["new_match_ids"] == []


def test_original_shares_and_old_batched_collections_resolve_to_their_own_sources(monkeypatch, programs):
    by_id = {row["id"]: row for row in programs}
    monkeypatch.setattr(opportunities, "load_opportunities_by_id", lambda: by_id)
    for oid in fodommat.IDS:
        response = client.get("/api/opportunities/" + oid)
        assert response.status_code == 200, response.text
        detail = response.json()
        assert (detail["id"], detail["url"]) == (oid, by_id[oid]["url"])
        assert detail["application_opens"]["source_url"] == "https://reu.ncsa.illinois.edu/"
        assert "experience with Python is required" in str(detail["detail_fields"])
    response = client.post("/api/opportunities/batch", json={"ids": list(fodommat.IDS)})
    assert response.status_code == 200
    assert [o["id"] for o in response.json()["opportunities"]] == list(fodommat.IDS)
