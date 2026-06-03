"""Deterministic guards for the uiuc_js_faculty collector (Playwright-rendered
ACES directories). No network and no Playwright: the live render is mocked, so
these exercise the link-extraction, email-derivation and section-label filtering
logic that turns rendered anchors into normalized opportunities.
"""

from __future__ import annotations

from src.collectors import uiuc_js_faculty as js
from src.collectors.uiuc_faculty import DEPARTMENTS
from src.collectors.uiuc_js_faculty import (
    JS_DEPARTMENTS,
    _scrape_js_faculty_list,
    fetch_department,
)

# A rendered listing mixes real person anchors (/directory/<netid>), category
# nav links (/directory/faculty), section-heading anchors that share the person
# URL shape, and unrelated site chrome. Only the three real people survive.
FAKE_ANCHORS = [
    {"h": "/directory/faculty-members", "t": "Faculty Members"},
    {"h": "/directory/emeritus-faculty-members", "t": "Emeritus Faculty"},
    {"h": "/directory/dshike", "t": "Dan Shike"},
    {"h": "/directory/callen", "t": "Crystal A. Allen"},
    {"h": "/directory/aantnsn2", "t": "Adrienne Antonson"},
    {"h": "/directory/dshike", "t": "Dan Shike"},  # duplicate -> deduped
    {"h": "/directory/staff", "t": "Research Staff"},
    {"h": "/about", "t": "About Us"},
    {"h": "/directory/office", "t": "Business Office"},  # netid-shaped section label
    {"h": "https://x.com/illinois", "t": "Follow Us On X"},
]


def test_scrape_extracts_only_real_people(monkeypatch):
    monkeypatch.setattr(js, "_render_person_links", lambda url, **k: FAKE_ANCHORS)
    people = _scrape_js_faculty_list(JS_DEPARTMENTS["ansc"])

    assert [p["name"] for p in people] == [
        "Dan Shike", "Crystal A. Allen", "Adrienne Antonson",
    ]


def test_email_derived_from_netid_slug(monkeypatch):
    monkeypatch.setattr(js, "_render_person_links", lambda url, **k: FAKE_ANCHORS)
    people = _scrape_js_faculty_list(JS_DEPARTMENTS["ansc"])
    by_name = {p["name"]: p for p in people}

    assert by_name["Dan Shike"]["email"] == "dshike@illinois.edu"
    assert by_name["Adrienne Antonson"]["email"] == "aantnsn2@illinois.edu"
    assert by_name["Dan Shike"]["url"] == "https://ansc.illinois.edu/directory/dshike"


def test_category_and_section_anchors_are_dropped(monkeypatch):
    monkeypatch.setattr(js, "_render_person_links", lambda url, **k: FAKE_ANCHORS)
    names = {p["name"] for p in _scrape_js_faculty_list(JS_DEPARTMENTS["ansc"])}

    # "Business Office" has a netid-shaped slug but is a section label, and the
    # /directory/faculty-members category nav link is not a person.
    assert "Business Office" not in names
    assert "Faculty Members" not in names
    assert "Emeritus Faculty" not in names


def test_fetch_department_normalizes_to_schema(monkeypatch):
    monkeypatch.setattr(js, "_render_person_links", lambda url, **k: FAKE_ANCHORS)
    opps = fetch_department("ansc")

    assert len(opps) == 3
    o = next(o for o in opps if o["pi_name"] == "Dan Shike")
    assert o["contact_email"] == "dshike@illinois.edu"
    assert o["source"] == "uiuc_faculty"
    assert o["department"] == JS_DEPARTMENTS["ansc"]["name"]
    assert o["opportunity_type"] == "research"
    assert o["id"].startswith("faculty-ansc-")


def test_missing_playwright_yields_no_people(monkeypatch):
    # When the render returns nothing (e.g. Playwright absent), the collector
    # degrades to an empty list rather than raising.
    monkeypatch.setattr(js, "_render_person_links", lambda url, **k: [])
    assert _scrape_js_faculty_list(JS_DEPARTMENTS["fshn"]) == []
    assert fetch_department("fshn") == []


def test_unknown_department_returns_empty():
    assert fetch_department("not-a-dept") == []


def test_js_departments_have_valid_config():
    for cfg in JS_DEPARTMENTS.values():
        assert {"name", "short", "url", "base", "majors", "keywords"} <= set(cfg)
        assert cfg["url"].startswith("https://") and ".illinois.edu" in cfg["url"]
        assert cfg["base"] in cfg["url"]
        assert cfg["majors"] and cfg["keywords"]


def test_js_shorts_do_not_collide_with_static_faculty():
    # normalize_faculty stamps source="uiuc_faculty" and ids as
    # faculty-<short>-<hash>; a short shared with a static department would risk
    # id collisions across the two collectors.
    static_shorts = {c["short"].lower() for c in DEPARTMENTS.values()}
    js_shorts = {c["short"].lower() for c in JS_DEPARTMENTS.values()}
    assert static_shorts.isdisjoint(js_shorts), "JS dept short collides with static"
    assert len(js_shorts) == len(JS_DEPARTMENTS), "duplicate JS short codes"
