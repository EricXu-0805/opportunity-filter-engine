"""The host and each independently checked directory copy belong to one BU application."""

import copy
import json
from datetime import date

import pytest

from backend.lib.target_actionability import actionable_opportunities
from backend.routes import matches, opportunities
from backend.routes.matches import _match_card
from src import evidence
from src.collectors.base import RawOpportunity
from src.collectors.uiuc_sro import merge_into_processed, raw_to_normalized
from src.matcher import ranker
from src.program_windows import STARS_HOST, STARS_OLD_HOST, STARS_SRO_ALIAS, STARS_SRO_CURRENT
from src.reviewed_program_pairs import STARS, pairs_in_records, verified_pairs
from src.saved_searches.filter import matching_ids
from tests.test_match_consistency import _profile, snapshot_env  # noqa: F401
from tests.test_program_windows import _row
from tests.test_saved_search_digest import AUTH, _digest_row, _install_stubs, _set_digest_env, client


@pytest.fixture(autouse=True)
def _while_the_2027_application_is_open(monkeypatch):
    # BU STaRS closes on 2027-01-15; these tests describe the record while it is open.
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 25))


def _sources():
    def directory(url, deadline, destination):
        return raw_to_normalized(RawOpportunity(
            "uiuc_sro", "https://researchops.web.illinois.edu/?page=4",
            "Summer Training as Research Scholars", "", url, organization="Boston University",
            extra_fields={"deadline_raw": deadline, "program_url": destination},
        ))
    return [_row("bu", "stars"), directory(STARS_SRO_CURRENT, "2/1/27", STARS_HOST),
            directory(STARS_SRO_ALIAS, "Anticipated 2/1/27", STARS_OLD_HOST)]


def test_originals_retain_separate_source_views_favorites_and_next_cohort():
    rows = _sources()
    host, primary, alias = (r["id"] for r in rows)
    assert matching_ids(rows, {}) == [host]
    assert matching_ids(rows, {"source": "uiuc_sro"}) == [primary, alias]
    assert matching_ids(rows, {"source": STARS.host_source}) == [host]
    for expected in (host, primary, alias):
        assert matching_ids(rows, {}, preferred_ids=[expected]) == [expected]
    assert matching_ids(rows, {}, preferred_ids=[primary, alias]) == [primary]
    assert matching_ids(rows, {}, excluded_ids={host}) == [primary, alias]
    cards = {r["id"]: _match_card(r) for r in rows}
    assert verified_pairs(cards, projected=True) == pairs_in_records(rows)
    assert all(c["application_deadline_source_url"] == STARS_HOST for c in cards.values())
    other = copy.deepcopy(rows[2])
    other["deadline"] = "2028-01-20"
    assert matching_ids([*rows[:2], other], {}) == [host, alias]
    [current] = pairs_in_records([*rows[:2], other])
    assert alias not in current.historical_ids
    other["deadline"] = "2027-01-15"
    other["application"]["application_url"] = "https://example.edu/a-different-program"
    forged = _match_card({**other, "application_deadline_source_url": STARS_HOST})
    assert "application_deadline_source_url" not in forged
    [current] = verified_pairs({**cards, alias: forged}, projected=True)
    assert alias not in current.ids


def test_directory_collector_owns_retirement_and_can_restore_the_old_source_url(tmp_path):
    rows = _sources()
    host, primary, alias = (r["id"] for r in rows)
    store = tmp_path / "programs.json"
    store.write_text(json.dumps(rows))
    merge_into_processed(rows[1:], str(store))
    updated = {r["id"]: r for r in json.loads(store.read_text())}
    assert updated[alias]["metadata"]["duplicate_of"] == primary
    live = actionable_opportunities(list(updated.values()))
    assert matching_ids(live, {}) == [host]
    assert matching_ids(live, {"source": "uiuc_sro"}) == [primary]
    updated[primary]["metadata"].update(is_active=False, deactivation_reason="source_removed")
    store.write_text(json.dumps(list(updated.values())))
    merge_into_processed([rows[2]], str(store))
    live = actionable_opportunities(json.loads(store.read_text()))
    assert matching_ids(live, {}) == [host]
    assert matching_ids(live, {"source": "uiuc_sro"}) == [alias]
    assert primary in pairs_in_records(live)[0].historical_ids


def test_queued_digests_send_only_one_existing_link_per_application(monkeypatch):
    rows = _sources()
    host, primary, alias = (r["id"] for r in rows)
    _set_digest_env(monkeypatch)
    for source, queued, expected in (
        ("", [alias, primary, host], host), ("", [alias, primary], primary), ("", [alias], alias),
        ("uiuc_sro", [alias, primary, host], primary), ("uiuc_sro", [alias, host], alias),
        (STARS.host_source, [alias, host], host),
    ):
        sends = []
        row = _digest_row(new_match_ids=queued, filters_json={"source": source})
        _install_stubs(monkeypatch, opportunities=rows, rows=[row], sends=sends)
        answer = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert answer.status_code == 200 and answer.json()["sent"] == 1
        assert [oid for oid in (host, primary, alias) if "/opportunities/" + oid in sends[0]["text"]] == [expected]


def test_real_match_paging_and_saved_original_routes(snapshot_env, monkeypatch):  # noqa: F811
    rows = _sources()
    for row in rows:
        row["keywords"] = ["biomedical research"]
        row["description_clean"] = "Undergraduate summer training in biomedical research."
    host, primary, alias = (r["id"] for r in rows)
    other = {**rows[0], "id": "another-summer-program"}
    corpus = [*rows, other]
    ranker.register_corpus(corpus)
    monkeypatch.setattr(matches, "load_opportunities_generation", lambda: (corpus, "bu-2027-student-rules"))
    monkeypatch.setattr(opportunities, "load_opportunities_by_id", lambda: {r["id"]: r for r in corpus})
    profile = _profile(year="junior", home_school="bu", major="Biology", desired_fields=["biomedical research"],
                       seeking_type=["summer_program"])
    saved = [alias, host, primary]
    for options, expected in (
        ({}, [host, other["id"]]), ({"source": "uiuc_sro"}, [primary, alias]),
        ({"favorite_ids": [alias]}, [alias, other["id"]]), ({"tab": "starred", "favorite_ids": saved}, saved),
        ({"dismissed_ids": [host]}, [primary, alias, other["id"]]),
    ):
        payload = {"profile": profile, "view": {"tab": "all", "today": "2026-11-26", **options}, "page_size": 1}
        seen = []
        while True:
            response = client.post("/api/matches/view", json=payload)
            assert response.status_code == 200
            page = response.json()
            assert page["filtered_total"] == len(expected)
            seen.extend(r["opportunity_id"] for r in page["results"])
            if not page["has_more"]:
                break
            assert len(seen) < len(expected) and page["next_cursor"]
            payload["cursor"] = page["next_cursor"]
        assert len(set(seen)) == len(seen) and set(seen) == set(expected)
    for original in rows:
        response = client.get("/api/opportunities/" + original["id"])
        assert response.status_code == 200 and response.json()["url"] == original["url"]
        assert response.json()["application_deadline_source_url"] == STARS_HOST
    response = client.post("/api/opportunities/batch", json={"ids": saved})
    assert response.status_code == 200 and [r["id"] for r in response.json()["opportunities"]] == saved
