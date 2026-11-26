from copy import deepcopy

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.pitt_faculty import SCHOOL
from src.normalizers.pitt_cs_appointments import reviewed_cs_appointment

CS = next(d for d in SCHOOL["departments"] if d["short"] == "CS")
SCI = next(d for d in SCHOOL["departments"] if d["short"] == "SCI")
COLLEGE = CS["scrape"]["supplemental_roster"]["url"]


def test_college_roster_updates_the_original_id_and_cannot_retire_unlisted_faculty(monkeypatch):
    roster = """<main><div class="view-content"><div class="views-row">
        <div class="views-field-title"><a href="/people/thumrongsak-kosiyatrkul">Thumrongsak Kosiyatrakul »</a></div>
        <div class="views-field-field-title"><div class="field-content">Teaching Associate Professor</div></div>
        </div><div class="views-row"><div class="views-field-title">
        <a href="https://another.example/people/someone">Another Person</a></div></div></div></main>"""
    read = []
    def fetch(url):
        read.append(url)
        return BeautifulSoup(roster, "html.parser") if url == COLLEGE else None

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    observation = {}
    result = faculty_graph.fetch_and_normalize({**SCHOOL, "departments": [CS]}, deep=True, unit_ledger=observation)

    assert read == [CS["directory_url"], COLLEGE]
    assert [r["id"] for r in result] == ["faculty-pitt-cs-a2c06c2d"]
    assert result[0]["pi_name"] == "Thumrongsak Kosiyatrakul"
    assert result[0]["url"] == "https://www.sci.pitt.edu/people/thumrongsak-kosiyatrkul"
    assert observation["cs"]["live_roster_count"] == 1
    assert observation["cs"]["coverage"]["partial_render_rows"] == 1
    assert observation["cs"]["coverage"]["supplemental_roster_url"] == COLLEGE
    assert observation["cs"]["retirement_authorized"] is False

    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: None)
    assert faculty_graph.fetch_and_normalize({**SCHOOL, "departments": [CS]}, deep=True, unit_ledger=observation) == []
    assert observation["cs"]["live_roster_count"] == 0


def test_healthy_department_uses_its_own_listing(monkeypatch):
    department = """<div class="views-row"><div class="views-field-field-person-img">
        <a href="/people/full-time-faculty/michael-miller-yoder-0">View Profile</a></div>
        <div class="views-field-title"><span class="field-content">Michael Miller Yoder</span></div>
        <div class="views-field-field-title"><div class="field-content">Teaching Assistant Professor</div></div></div>"""
    def local_read(url):
        assert url == CS["directory_url"]
        return BeautifulSoup(department, "html.parser")

    monkeypatch.setattr(ucb_common, "fetch_soup", local_read)
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", False)
    ledger = {}
    rows = faculty_graph.fetch_and_normalize({**SCHOOL, "departments": [CS]}, deep=True, unit_ledger=ledger)
    assert [r["id"] for r in rows] == ["faculty-pitt-cs-1c364170"]
    assert ledger["cs"]["coverage"]["partial_render_rows"] == 0


def test_both_saved_details_keep_one_current_identity_in_either_order():
    cs = faculty_graph._normalize(SCHOOL, CS, {
        "name": "Bruce Childers", "title": "Professor and Dean",
        "url": "https://www.cs.pitt.edu/people/full-time-faculty/bruce-childers",
    })
    sci = faculty_graph._normalize(SCHOOL, SCI, {
        "name": "Bruce R. Childers", "title": "Dean, Professor, Department of Computer Science",
        "url": "https://www.sci.pitt.edu/people/bruce-r-childers",
    })
    assert [cs["id"], sci["id"]] == ["faculty-pitt-cs-e47a8796", "faculty-pitt-sci-69cd00cb"]
    for ordered in ([cs, sci], [sci, cs]):
        records = deepcopy(ordered)
        report = faculty_graph.collapse_same_person_faculty(records, published_ids=frozenset(r["id"] for r in records))
        assert {r["id"] for r in report["kept"]} == {cs["id"], sci["id"]}
        by_id = {r["id"]: r for r in report["kept"]}
        assert by_id[cs["id"]]["metadata"]["is_active"]
        assert by_id[sci["id"]]["metadata"]["duplicate_of"] == cs["id"]
        assert by_id[sci["id"]]["metadata"]["is_active"] is False

    for key, other in (("pi_name", "Another Person"), ("school", "other"),
                       ("department", "Department of Mathematics"), ("url", "https://www.sci.pitt.edu/people/faculty")):
        assert reviewed_cs_appointment({**sci, key: other}) is None


def test_the_dean_and_student_records_inboxes_never_become_a_professors_contact():
    from backend.lib.contact_visibility import verified_send_target
    from src.collectors.uiuc_faculty import _carry_forward_enrichment

    cs = faculty_graph._normalize(SCHOOL, CS, {
        "name": "Bruce Childers", "title": "Professor", "url": "https://www.cs.pitt.edu/people/full-time-faculty/bruce-childers",
    })
    for unit in ("SCIDean@pitt.edu", "SCIRecords@pitt.edu"):
        old = deepcopy(cs)
        old["contact_email"] = unit
        old["metadata"]["email_source"] = "profile_page"
        assert faculty_graph._clean_email(unit) is None
        assert not verified_send_target(old)
        newer = deepcopy(cs)
        _carry_forward_enrichment(old, newer)
        assert not newer["contact_email"]
        faculty_graph._merge_faculty_fields(newer, old)
        assert not newer["contact_email"]
    assert faculty_graph._clean_email("scidean@other.edu") == "scidean@other.edu"
