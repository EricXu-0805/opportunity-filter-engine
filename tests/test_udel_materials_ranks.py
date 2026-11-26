import json
from copy import deepcopy

import pytest
from bs4 import BeautifulSoup

from src.collectors import ucb_common, udel_materials_ranks
from src.collectors.schools import udel_faculty

URL = "https://mseg.udel.edu/people/doty/"
OID = "faculty-udel-mseg-22466e16"


def row():
    return {"id": OID, "pi_name": "Matthew Doty", "url": URL,
            "metadata": {"is_active": True, "faculty_title": "", "first_seen_at": "2026-11-19T12:00:00"}}


def page(title="Professor", name="Matthew Doty", *, final=URL, checked="2026-11-22T15:23:00+00:00",
         heading="h4"):
    html = f"""
        <main id="main-content"><div class="et_pb_column">
          <div class="et_pb_post_title"><div class="et_pb_title_container">
            <h1 class="entry-title">{name}</h1></div></div>
          <div class="et_pb_text"><div class="et_pb_text_inner">
            <{heading}>{title}</{heading}><h5>Director, Institute of Energy Conversion</h5></div></div>
          <div class="et_pb_text"><div class="et_pb_text_inner"><h4>Distinguished Professor Award</h4></div></div>
        </div></main>"""
    return ucb_common._mark_fetched_soup_observation(BeautifulSoup(html, "html.parser"),
                                                     requested_url=URL, final_url=final, observed_at=checked)


def read(monkeypatch, html, previous=None):
    fresh = row()
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *a, **kw: html)
    udel_materials_ranks.observe_materials_ranks([fresh], deep=True)
    if previous:
        udel_materials_ranks.preserve_unread_rank(previous, fresh)
    return fresh


@pytest.mark.parametrize("heading", ["h2", "h4"])
def test_quoted_rank_comes_from_named_module_and_actual_fetch_date(monkeypatch, heading):
    rank = "Karl W. and Renate Böer Chaired Professor of Materials Science and Engineering"
    md = read(monkeypatch, page(rank, heading=heading))["metadata"]
    assert md["faculty_title"] == rank
    assert md["faculty_title_observation"] == {
        "name": "Matthew Doty", "title": rank, "source": URL, "profile": URL, "checked_on": "2026-11-22",
    }


@pytest.mark.parametrize("rank", ["", "Quick Links", "Professor of the Year Award", "Professor Emeritus and Research Professor"])
def test_missing_role_or_award_on_readable_page_clears_old_rank(monkeypatch, rank):
    previous = read(monkeypatch, page())
    fresh = read(monkeypatch, page(rank), previous)["metadata"]
    assert fresh["is_active"] and not fresh["faculty_title"] and "faculty_title_observation" not in fresh


def test_failure_mismatch_retirement_and_recovery_preserve_the_original(monkeypatch):
    active = read(monkeypatch, page())
    held = read(monkeypatch, None, active)
    assert held["metadata"]["faculty_title_observation"] == active["metadata"]["faculty_title_observation"]
    redirect = read(monkeypatch, page(final="https://mseg.udel.edu/people/other/"), held)
    assert not redirect["metadata"]["faculty_title"] and "faculty_title_observation" not in redirect["metadata"]
    partial = page()
    partial.select_one(".et_pb_post_title + .et_pb_text").decompose()
    partial.select_one(".et_pb_column > .et_pb_text").decompose()
    assert read(monkeypatch, partial, held)["metadata"]["faculty_title_observation"] == active["metadata"]["faculty_title_observation"]
    other = read(monkeypatch, page(name="Alex Roe"), held)
    assert not other["metadata"]["is_active"] and other["metadata"]["deactivation_reason"] == "profile_identity_mismatch"
    assert not other["metadata"]["faculty_title"] and "faculty_title_observation" not in other["metadata"]
    assert not read(monkeypatch, None, other)["metadata"]["is_active"]
    retired = read(monkeypatch, page("Professor Emeritus", checked="2026-11-24T12:00:00Z"), other)
    assert not retired["metadata"]["is_active"] and retired["metadata"]["deactivated_at"] == "2026-11-24"
    again = read(monkeypatch, page("Professor Emeritus", checked="2026-11-25T12:00:00Z"), retired)
    assert again["metadata"]["deactivated_at"] == "2026-11-24"
    assert again["metadata"]["faculty_title_observation"]["checked_on"] == "2026-11-25"
    missing = read(monkeypatch, page(""), again)
    assert not missing["metadata"]["is_active"] and "faculty_title_observation" not in missing["metadata"]
    restored = read(monkeypatch, page("Research Professor", checked="2026-11-26T12:00:00Z"), missing)
    assert restored["id"] == OID and restored["metadata"]["is_active"]
    assert restored["metadata"]["faculty_title_observation"]["title"] == "Research Professor"


def test_other_profile_undated_response_and_sibling_units_do_not_receive_a_rank(monkeypatch):
    for bad in (page(final="https://mseg.udel.edu/people/other/"), page(checked="bad"),
                page(checked="2026-11-24T10:00:00"), page(checked="2999-01-01T00:00:00Z")):
        assert "faculty_title_observation" not in read(monkeypatch, bad)["metadata"]
    old = read(monkeypatch, page())
    for replacement in (dict(row(), pi_name="Another Person"), dict(row(), url=URL.replace("doty", "other"))):
        replacement["metadata"]["faculty_title_read_status"] = "unavailable"
        udel_materials_ranks.preserve_unread_rank(old, replacement)
        assert not replacement["metadata"]["faculty_title"]
    controls = [dict(row(), id="faculty-udel-cbe-d95f4672"), dict(row(), id="faculty-udel-me-4b7217c7"),
                dict(row(), url="https://other.edu/people/doty/")]
    expected = deepcopy(controls)
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *a, **kw: pytest.fail("unrelated URL or unit"))
    udel_materials_ranks.observe_materials_ranks(controls, deep=True)
    assert controls == expected


def test_normal_collector_wrapper_and_upsert_use_rank_observation(monkeypatch, tmp_path):
    work = tmp_path / "corpus.json"
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", work)
    monkeypatch.setattr(udel_faculty.faculty_graph, "fetch_and_normalize", lambda *a, **kw: [row()])
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *a, **kw: page())
    fresh = udel_faculty.fetch_and_normalize()
    assert fresh[0]["metadata"]["faculty_title"] == "Professor"
    work.write_text(json.dumps(fresh))
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *a, **kw: None)
    assert udel_faculty.merge_into_processed(udel_faculty.fetch_and_normalize()) == (0, 1)
    assert json.loads(work.read_text())[0]["metadata"]["faculty_title_observation"]["checked_on"] == "2026-11-22"


@pytest.mark.parametrize("with_seed", [False, True])
@pytest.mark.parametrize("initial_rank", ["Professor", "Professor Emeritus"])
def test_normal_shallow_cycle_and_unread_deep_cycle_keep_original_dated_rank(
        monkeypatch, tmp_path, with_seed, initial_rank):
    school = udel_faculty.SCHOOL
    unit = next(d for d in school["departments"] if d["short"] == "MSEG")
    if with_seed:
        # Scrape-only today. A retained/curated entry can also emit this same original ID on a shallow run.
        unit = dict(unit, faculty=[{"name": "Matthew Doty", "url": URL}])
    monkeypatch.setattr(udel_faculty, "SCHOOL", dict(school, departments=[unit]))
    monkeypatch.delenv("OFE_ENRICH_PROFILES", raising=False)
    directory = BeautifulSoup(
        '<div id="faculty"><div class="et_pb_text_inner"><h4>'
        '<a href="/people/doty/">Matthew Doty</a></h4></div></div>', "html.parser")
    profile = page(initial_rank)
    requests = []

    def fetch(url, **kwargs):
        requests.append(url)
        if url == unit["directory_url"]:
            return directory
        assert url == URL
        return profile

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    corpus = tmp_path / "corpus.json"
    corpus.write_text("[]")
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", corpus)

    def cycle(*, deep):
        requests.clear()
        incoming = udel_faculty.fetch_and_normalize(deep=deep)
        udel_faculty.merge_into_processed(incoming)
        [saved] = json.loads(corpus.read_text())
        assert saved["id"] == OID
        return incoming, saved["metadata"]

    _, original = cycle(deep=True)
    receipt = original["faculty_title_observation"]
    assert receipt["checked_on"] == "2026-11-22" and receipt["title"] == initial_rank
    active = original["is_active"]
    assert active == (initial_rank == "Professor")

    shallow, held = cycle(deep=False)
    assert requests == []
    assert [r["id"] for r in shallow] == ([OID] if with_seed else [])
    if with_seed:
        assert held["faculty_title_read_status"] == "not_attempted"
    assert held["faculty_title_observation"] == receipt and held["is_active"] == active

    profile = None
    _, held = cycle(deep=True)
    assert held["faculty_title"] == initial_rank and held["faculty_title_observation"] == receipt
    assert held["is_active"] == active and held["faculty_title_read_status"] == "unavailable"

    profile = page("Research Professor", checked="2026-11-25T21:30:00+00:00")
    _, restored = cycle(deep=True)
    assert restored["is_active"] and restored["faculty_title_read_status"] == "observed"
    assert restored["faculty_title"] == "Research Professor"
    assert restored["faculty_title_observation"] == dict(receipt, title="Research Professor", checked_on="2026-11-25")
