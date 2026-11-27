from html import escape

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.arizona_faculty import SCHOOL


def test_nursing_roster_uses_the_academic_appointment_on_the_same_card(monkeypatch):
    department = next(dept for dept in SCHOOL["departments"] if dept["short"] == "NURS")
    roles = {
        "director": ["PhD Program Director", "Associate Professor"],
        "member": ["Member of the Graduate Faculty", "Assistant Clinical Professor (Career Track)"],
        "admin": ["Program Director", "Communications Manager"],
        "graduate": ["Graduate Research Assistant", "Member of the Graduate Faculty"],
        "former": ["Division Chair", "Professor Emerita", "Professor"],
        "adjunct": ["Specialty Coordinator", "Adjunct Professor", "Professor"],
        "research": ["Research Professor, Nursing", "(retired) Professor Emerita"],
        "missing": [],
    }
    cards = []
    for slug, titles in roles.items():
        items = "".join(f'<div class="field__item">{escape(title)}</div>' for title in titles)
        cards.append(
            '<article class="node--type-az-person">'
            f'<h3><a href="/person/{slug}">Alex {slug.title()}</a></h3>'
            f'<div class="field--name-field-az-titles">{items}</div></article>'
        )
    soup = BeautifulSoup("".join(cards), "html.parser")
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *_args, **_kwargs: soup)
    rows = faculty_graph._scrape_directory(department)
    assert {row["name"]: row["title"] for row in rows} == {
        "Alex Director": "Associate Professor",
        "Alex Member": "Assistant Clinical Professor (Career Track)",
        "Alex Research": "Research Professor, Nursing",
    }


def test_reviewed_nursing_joint_appointment_keeps_published_id_during_ece_outage(monkeypatch):
    from src.collectors.schools import arizona_faculty

    units = {d["short"]: d for d in SCHOOL["departments"]}
    monkeypatch.setattr(arizona_faculty, "SCHOOL", {**SCHOOL, "departments": [units["NURS"], units["ECE"]]})
    monkeypatch.setenv("OFE_ENRICH_PROFILES", "0")
    source = units["NURS"]["directory_url"]
    published = "faculty-arizona-ece-9b761039"
    nursing = "faculty-arizona-nurs-77b21e8a"

    def card(path, name="Chen X. Chen"):
        return BeautifulSoup(
            '<article class="node--type-az-person">'
            f'<h3><a href="{path}">{name}</a></h3>'
            '<div class="field--name-field-az-titles"><div class="field__item">'
            'Professor</div></div></article>', "html.parser")

    def read(nursing_path, stored, engineering=None):
        monkeypatch.setattr(ucb_common, "fetch_soup",
                            lambda url, **kwargs: card(nursing_path) if url == source else engineering)
        ledger = {}
        with faculty_graph.run_start_ids(frozenset(stored)):
            rows = arizona_faculty.fetch_and_normalize(unit_ledger=ledger)
        return {row["id"] for row in rows}, ledger["nurs"]

    ids, ledger = read("/cxchen", [published])
    assert nursing not in ids
    assert ledger["observed_count"] == 0
    assert ledger["live_roster_count"] == 1
    assert ledger["observed_entity_ids"] == [nursing]
    assert read("/different-person", [published])[0] == {nursing}
    assert read("/cxchen", [])[0] == {nursing}
    # If nursing already owns a published record after a real transfer, keep reading it.
    assert read("/cxchen", [published, nursing])[0] == {nursing}
    # A readable engineering roster which now lists another person is distinct
    # from an outage. Let the normal reconciliation handle an actual move.
    ids, ledger = read("/cxchen", [published], card("/other", "Leila Smith"))
    assert nursing in ids
    assert ledger["observed_count"] == 1
