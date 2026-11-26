from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.gatech_faculty import SCHOOL

UNITS = {unit["short"]: unit for unit in SCHOOL["departments"]}


def _card(name, slug, title):
    return (
        '<div class="node--type-dir-person"><div class="directory-person">'
        f'<div class="field--name-field-person-name">{name}</div>'
        f'<div class="field--name-field-person-job-title-s-">{title}</div>'
        f'<a class="directory-person-wrapper-link" href="/directory/person/{slug}">Learn more about {name}</a>'
        '</div></div>'
    )


def _rows(unit, group):
    dept = UNITS[unit]
    cfg = dept["scrape"]
    specs = faculty_graph._parse_cards(
        BeautifulSoup(group, "html.parser"), cfg["selectors"], cfg["url"], cfg["ladder_filter"]
    )
    return [faculty_graph._normalize(SCHOOL, dept, person) for person in specs]


def test_each_person_in_each_grid_row_keeps_their_independent_name_rank_and_link():
    group = (
        '<div class="views-row">'
        + _card("Example First", "first", "Associate Professor")
        + _card("Example Second", "second", "Assistant Professor")
        + _card("Example Third", "third", "Professor Emeritus")
        + '</div>'
    )
    for unit in ("AE", "CHBE"):
        first, second = _rows(unit, group)
        assert [first["pi_name"], second["pi_name"]] == ["Example First", "Example Second"]
        assert [first["metadata"]["faculty_title"], second["metadata"]["faculty_title"]] == [
            "Associate Professor", "Assistant Professor",
        ]
        assert first["url"].endswith("/directory/person/first")
        assert second["url"].endswith("/directory/person/second")


def test_aerospace_nickname_keeps_the_original_id_only_on_the_reviewed_new_profile():
    original, other = _rows(
        "AE",
        _card("Masatoshi Hirabayashi", "masatoshi-hirabayashi", "Associate Professor")
        + _card("Masatoshi Hirabayashi", "different-person", "Assistant Professor"),
    )
    assert original["id"] == "faculty-gatech-ae-7be62004"
    assert other["id"] != original["id"]


def test_profile_enrichment_reads_one_typed_campus_field_for_the_roster_person(monkeypatch):
    unit = UNITS["CHBE"]
    cfg = unit["scrape"]
    url = "https://chbe.gatech.edu/directory/person/example-first"
    body = '<h1>Example First</h1><div class="field--name-field-person-email">%s</div><footer>office@gatech.edu</footer>'

    def field(address):
        return f'<div class="field__item"><a href="mailto:{address}">{address}</a></div>'

    def parsed(fields, name="Example First"):
        doc = BeautifulSoup(body % fields, "html.parser")
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda *_a, **_kw: doc)
        people = [{"name": name, "url": url, "title": "Associate Professor"}]
        [result] = faculty_graph._apply_profile_enrich(people, cfg["profile_enrich"])
        return result.get("email")

    assert parsed(field("example.first@chbe.gatech.edu")) == "example.first@chbe.gatech.edu"
    assert not parsed(field("example.first@chbe.gatech.edu"), "Another Person")
    assert not parsed(field("example.first@another.edu"))
    assert not parsed(field("example.first@gatech.edu") + field("different@gatech.edu"))


def test_legacy_engineering_cards_still_bind_only_their_own_profile():
    for unit, card in (("AE", "node--type-dir-person"), ("CHBE", "views-row")):
        legacy = (
            f'<div class="{card}"><a class="dir_link" href="/people/old">Legacy Faculty</a>'
            '<div class="field--name-field-person-job-title-s-">Professor</div></div>'
        )
        [old] = _rows(unit, legacy)
        assert old["pi_name"] == "Legacy Faculty"
        assert old["url"].endswith("/people/old")


def test_mechanical_roster_preserves_legacy_profiles_and_adds_only_confirmed_ranks_on_other_paths():
    def card(name, url, role):
        return (
            '<div class="faculty__user-wrapper">'
            f'<div class="faculty-name"><a href="{url}">{name}</a></div>'
            f'<div class="faculty-title">{role}</div></div>'
        )

    unit = UNITS["ME"]
    cfg = unit["scrape"]
    markup = (
        card("Old Chair", "/faculty/old", "Center Director")
        + card("Example Person", "/user/1086", "Assistant Professor")
        + card("Second Faculty", "/second", "Associate Professor")
        + card("Another Person", "/user/1198", "Financial Coordinator")
        + card("Former Faculty", "/user/1199", "Professor Emeritus")
        + card("Former Visitor", "/user/1200", "Adjunct Assistant Professor")
        + card("Blank Title", "/user/1201", "")
    )
    specs = faculty_graph._parse_cards(
        BeautifulSoup(markup, "html.parser"), cfg["selectors"], cfg["url"],
        cfg["ladder_filter"], field_filter=cfg["field_filter"],
    )
    assert [s["name"] for s in specs] == ["Old Chair", "Example Person", "Second Faculty"]


def test_mechanical_profile_requires_one_contact_field_with_one_consistent_address(monkeypatch):
    cfg = UNITS["ME"]["scrape"]["profile_enrich"]
    url = "https://me.gatech.edu/user/1086"
    own = '<p><strong>Email:</strong> lin.ortiz@gatech.edu</p>'
    other = '<p><strong>Email:</strong> assistant@gatech.edu</p>'

    def read(fields):
        html = '<div class="banner-text-wrapper"><h2>Lin Ortiz</h2>' + fields + '</div>'
        doc = BeautifulSoup(html, "html.parser")
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda *_a, **_kw: doc)
        [p] = faculty_graph._apply_profile_enrich([{"name": "Lin Ortiz", "url": url}], cfg)
        return p.get("email")

    assert read(own) == "lin.ortiz@gatech.edu"
    assert not read(own + other)
    assert not read('<p><strong>Email:</strong> person@gatech.edu or colleague@gatech.edu</p>')
    assert not read('<p><strong>Email:</strong> <a href="mailto:other@gatech.edu">person@gatech.edu</a></p>')
    assert not read('<p><strong>Email:</strong> office@gatech.edu</p>')
