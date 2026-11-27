import json

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import vt_aoe, vt_faculty


def test_aoe_tracks_named_emeritus_appointments_and_restores_a_current_original(monkeypatch, tmp_path):
    dept = next(d for d in vt_faculty.SCHOOL["departments"] if d["short"] == "AOE")
    monkeypatch.setattr(vt_faculty, "SCHOOL", {**vt_faculty.SCHOOL, "departments": [dept]})
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", False)
    database = tmp_path / "opportunities.json"
    database.write_text("[]")
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", database)
    directory = [None]
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: directory[0])
    person = "Wayne Neu"
    original = "faculty-vt-aoe-e1a38f09"
    bio = "/people/emeritus/neu.html"

    def group(name, members):
        cards = "".join(f'<div class="vt-list-item-wrapper"><h4 class="vt-list-item-heading" data-itemtype="bio">'
                        f'<a class="vt-list-item-title-link" href="{url}">{who}<span>, bio</span></a>'
                        f'</h4></div>' for who, url in members)
        return f"<section><h3>{name}</h3>{cards}</section>"

    def collect(*groups):
        doc = "".join(group(name, members) for name, members in groups)
        directory[0] = BeautifulSoup(f"<main>{doc}</main>", "html.parser") if groups else None
        ledger = {}
        incoming = vt_faculty.fetch_and_normalize(unit_ledger=ledger)
        vt_faculty.merge_into_processed(incoming)
        return {row["id"]: row for row in json.loads(database.read_text())}, ledger

    current = ("Faculty", [(person, bio), ("Alex Jones", "/people/faculty/alex.html")])
    retired = ("Emeritus faculty", [(person, bio)])
    rows, _ = collect(current)
    assert rows[original]["metadata"]["is_active"] and not rows[original]["metadata"]["faculty_title"]
    first_seen = rows[original]["metadata"]["first_seen_at"]
    rows, _ = collect(retired, ("Faculty", current[1][1:]))
    archived = rows[original]
    assert archived["metadata"]["faculty_title"] == "Emeritus faculty" and not archived["metadata"]["is_active"]
    assert archived["metadata"]["faculty_title_observation"]["source"] == vt_aoe.DIRECTORY
    assert archived["metadata"]["first_seen_at"] == first_seen
    archive_date = archived["metadata"]["deactivated_at"]
    rows, _ = collect(retired)
    assert rows[original]["metadata"]["deactivated_at"] == archive_date
    archived = rows[original]
    for sections in [(), (("Unknown grouping", [(person, bio)]),), (("Emeritus faculty", [(person, "/people/faculty/other.html")]),)]:
        rows, _ = collect(*sections)
        assert rows[original] == archived
    for order in [(current, retired), (retired, current)]:
        rows, _ = collect(*order)
        restored = rows[original]
        assert restored["metadata"]["is_active"] and not restored["metadata"]["faculty_title"]
        assert "deactivation_reason" not in restored["metadata"] and "faculty_title_observation" not in restored["metadata"]
        assert restored["metadata"]["first_seen_at"] == first_seen
        assert restored["url"].endswith(bio)
    rows, _ = collect(("Emeritus faculty", [(person, bio), (person, "/people/emeritus/someone-else.html")]))
    assert rows[original] == restored


def test_aoe_archived_record_cannot_displace_a_current_appointment_from_another_unit(monkeypatch):
    aoe = next(d for d in vt_faculty.SCHOOL["departments"] if d["short"] == "AOE")
    current = {**aoe, "short": "ME", "name": "Department of Mechanical Engineering",
               "scrape": {**aoe["scrape"], "url": "https://me.vt.edu/people/faculty.html"}}
    bio = "https://www.aoe.vt.edu/people/emeritus/neu.html"
    def read(url):
        heading = "Faculty" if url == current["scrape"]["url"] else "Emeritus faculty"
        current_control = '' if heading == "Faculty" else (
            '<h3>Faculty</h3><div class="vt-list-item-wrapper"><h4 class="vt-list-item-heading" data-itemtype="bio">'
            '<a class="vt-list-item-title-link" href="/people/faculty/jones.html">Alex Jones<span>, bio</span></a>'
            '</h4></div>')
        return BeautifulSoup(f'<main>{current_control}<h3>{heading}</h3><div class="vt-list-item-wrapper">'
                             f'<h4 class="vt-list-item-heading" data-itemtype="bio">'
                             f'<a class="vt-list-item-title-link" href="{bio}">Wayne Neu<span>, bio</span></a>'
                             f'</h4></div></main>', "html.parser")
    monkeypatch.setattr(ucb_common, "fetch_soup", read)
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", False)
    for depts in ([aoe, current], [current, aoe]):
        monkeypatch.setattr(vt_faculty, "SCHOOL", {**vt_faculty.SCHOOL, "departments": depts})
        rows = vt_faculty.fetch_and_normalize()
        person = [r for r in rows if r["pi_name"] == "Wayne Neu"]
        assert len(person) == 2 and len({r["id"] for r in person}) == 2
        assert {r["department"]: r["metadata"]["is_active"] for r in person} == {aoe["name"]: False, current["name"]: True}
