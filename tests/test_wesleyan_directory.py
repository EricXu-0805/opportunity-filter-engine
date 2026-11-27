from __future__ import annotations

import json

import pytest
import requests

from src.collectors import ucb_common
from src.collectors.schools import wesleyan_faculty as wesleyan


def _person(profile_id, name, title="Professor of Astronomy"):
    return {"id": profile_id, "name": name, "positions": [title], "department_classes": "astr"}


def _response(monkeypatch, payload, status=200):
    calls = []

    class Response:
        status_code = status

        def json(self):
            if isinstance(payload, Exception):
                raise payload
            return payload

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(wesleyan.requests, "get", get)
    return calls


def test_central_sighting_preserves_ids_fields_and_department_evidence(monkeypatch, tmp_path):
    calls = _response(monkeypatch, {"items": {"H": [
        _person("amhughes", "Meredith Hughes"), _person("emoran", "Another Person"),
        _person("sredfield", "Seth Redfield", "Professor Emeritus of Astronomy"),
        _person("unlisted", "An Additional Professor"), _person("iharjito", "I. Harjito"),
        _person("sumarsam", "Sumarsam"),
    ]}})
    offline_ledger, online_ledger = {}, {}
    offline = wesleyan.fetch_and_normalize(deep=False, unit_ledger=offline_ledger)
    assert calls == []
    online = wesleyan.fetch_and_normalize(unit_ledger=online_ledger)
    assert len(calls) == 1
    assert calls[0][0] == wesleyan._DIRECTORY_URL
    assert calls[0][1]["allow_redirects"] is False
    assert {r["id"] for r in online} == {r["id"] for r in offline}
    witnessed = [r for r in online if r["metadata"].get("listing_seen_on_source")]
    assert {r["pi_name"] for r in witnessed} == {"Meredith Hughes", "I. Harjito", "Sumarsam"}
    seen = witnessed[0]["metadata"]["last_seen_at"]
    assert seen and all(r["metadata"]["last_verified"] is None for r in online)
    assert all(r["metadata"]["verification_scope"] == "curated" for r in online)
    assert all(r["metadata"]["last_seen_at"] is None for r in online if r not in witnessed)
    for unit, evidence in offline_ledger.items():
        # The central read gives no further evidence for any department.
        for key in ("observed_count", "observed_entity_ids", "coverage", "retirement_authorized"):
            assert online_ledger[unit][key] == evidence[key]

    corpus = tmp_path / "opportunities.json"
    corpus.write_text(json.dumps(online))
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", corpus)
    _response(monkeypatch, {}, status=429)
    wesleyan.merge_into_processed(wesleyan.fetch_and_normalize())
    retained = [r for r in json.loads(corpus.read_text()) if r["metadata"].get("listing_seen_on_source")]
    assert {r["id"]: r["metadata"]["last_seen_at"] for r in retained} == {r["id"]: seen for r in witnessed}

    # Reassignment of a personal URL cannot preserve a mononym's sighting.
    prior = next(r for r in witnessed if r["pi_name"] == "Sumarsam")
    corpus.write_text(json.dumps([prior]))
    changed = next(r for r in offline if r["id"] == prior["id"])
    changed["url"] = "https://www.wesleyan.edu/about/directory/profile.html?id=another"
    wesleyan.merge_into_processed([changed])
    assert json.loads(corpus.read_text())[0]["metadata"]["last_seen_at"] is None


@pytest.mark.parametrize("bad_title", ["Visiting Professor", "Adjunct Professor", "Professor Emerita",
                                       "Professor of Physical Education", "Administrative Assistant", "",
                                       "In Memoriam: Professor", "Artist-in-Residence"])
def test_directory_matches_require_a_current_eligible_role(bad_title):
    p = _person("p", "Pat Jones", bad_title)
    assert wesleyan._directory_names({"items": {"P": [p]}}) == {}


def test_conflicting_identity_records_and_incomplete_data_do_not_count():
    p = _person("p", "Pat Jones")
    assert wesleyan._directory_names({"items": {"P": [p], "J": [{**p, "name": "Other Person"}]}}) == {}
    assert wesleyan._directory_names({"items": {"P": [p], "X": "bad group"}}) == {}
    assert wesleyan._directory_names({"items": {"P": [dict(p, positions=None)]}}) == {}


@pytest.mark.parametrize("status,payload", [(403, {}), (200, ValueError("HTML")), (200, {"items": []})])
def test_unreadable_roster_retains_all_ids_without_a_new_sighting(monkeypatch, status, payload):
    calls = _response(monkeypatch, payload, status)
    records = wesleyan.fetch_and_normalize()
    assert records and len(calls) == 1
    assert all(r["metadata"]["last_seen_at"] is None for r in records)


def test_timeout_retains_the_corpus(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout

    monkeypatch.setattr(wesleyan.requests, "get", timeout)
    assert all(r["metadata"]["last_seen_at"] is None for r in wesleyan.fetch_and_normalize())


def test_a_rank_held_in_a_later_position_counts():
    chair = {**_person("aexample", "Alex Example"),
             "positions": ["Astronomy, Chair, Astronomy", "Astronomy, Professor of Astronomy",
                           "College of Integrative Science, Professor, Integrative Sciences"]}
    staff = {**_person("bexample", "Blake Example"),
             "positions": ["Astronomy, Chair, Astronomy", "Academic Affairs, Director of Observing"]}
    former = {**_person("cexample", "Casey Example"),
              "positions": ["Astronomy, Visiting Professor of Astronomy", "Astronomy, Professor of Astronomy, Emerita"]}
    listed = wesleyan._directory_names({"items": {"E": [chair, staff, former]}})
    assert set(listed) == {"aexample"}


def _seeded(monkeypatch, people):
    profile = "https://www.wesleyan.edu/about/directory/profile.html?id="
    monkeypatch.setattr(wesleyan, "SCHOOL", {**wesleyan.SCHOOL, "departments": [wesleyan._dept(
        "ASTR", "Department of Astronomy", ["Astronomy"], "https://www.wesleyan.edu/astro/people.html",
        [wesleyan.faculty(name, title="Professor of Astronomy", url=profile + pid if pid else page)
         for name, pid, page in people])]})


def _sighted(monkeypatch, listed):
    _response(monkeypatch, {"items": {"A": listed}})
    return {r["pi_name"] for r in wesleyan.fetch_and_normalize()
            if r["metadata"].get("listing_seen_on_source")}


def test_a_stored_row_is_sighted_by_its_profile_id_when_the_directory_respells_the_name(monkeypatch):
    _seeded(monkeypatch, [("Alex Example", "aexample", None), ("José Sample Rivera", "jsample", None),
                          ("Cameron Placeholder", "cplaceholder", None), ("Mona Nym", "mnym", None),
                          ("Pat Jones", "pjones", None), ("Robin Absent", "rabsent", None)])
    two_roles = ["Astronomy, Chair, Astronomy", "Astronomy, Professor of Astronomy"]
    assert _sighted(monkeypatch, [
        {**_person("aexample", "Alex Example"), "positions": two_roles},
        _person("jsample", "Jose Sample"), _person("cplaceholder", "Camryn Placeholder"),
        _person("mnym", "Prof. Mona Nym"),
        # The id now names someone else; the same name under another id is another profile.
        _person("pjones", "Morgan Other"), _person("rabsent2", "Robin Absent"),
    ]) == {"Alex Example", "José Sample Rivera", "Cameron Placeholder", "Mona Nym"}


def test_a_stored_row_without_a_profile_id_is_sighted_by_its_folded_name_only_when_unique(monkeypatch):
    page = "https://www.wesleyan.edu/astro/people.html"
    _seeded(monkeypatch, [("Zoë Nomura", None, page + "#nomura"), ("Sam Lee", None, page + "#lee"),
                          ("Robin Absent", None, page + "#absent")])
    assert _sighted(monkeypatch, [
        {**_person("znomura", "Dr. Zoe Nomura"),
         "positions": ["Astronomy, Director, Observatory", "Astronomy, Associate Professor of Astronomy"]},
        _person("slee", "Sam Lee"), _person("slee01", "Sam Lee"), _person("rother", "Robin Other"),
    ]) == {"Zoë Nomura"}
