"""School-specific contracts for the five liberal-arts profile passes."""

from __future__ import annotations

import re

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools import (
    bowdoin_faculty,
    carleton_faculty,
    coloradocollege_faculty,
    grinnell_faculty,
    middlebury_faculty,
)

PROFILE_CASES = [
    pytest.param(
        middlebury_faculty,
        "https://www.middlebury.edu/college/people/catherine-combelles",
        "https://www.middlebury.edu/college/people/",
        id="middlebury",
    ),
    pytest.param(
        carleton_faculty,
        "https://www.carleton.edu/directory/raka/",
        "https://www.carleton.edu/directory/",
        id="carleton",
    ),
    pytest.param(
        grinnell_faculty,
        "https://www.grinnell.edu/user/497",
        "https://www.grinnell.edu/user/497/not-a-profile",
        id="grinnell",
    ),
    pytest.param(
        bowdoin_faculty,
        "https://www.bowdoin.edu/profiles/faculty/jbateman/index.html",
        "https://www.bowdoin.edu/profiles/faculty/",
        id="bowdoin",
    ),
    pytest.param(
        coloradocollege_faculty,
        (
            "https://www.coloradocollege.edu/basics/contact/directory/"
            "people/bowman_amanda_catherine.html"
        ),
        "https://www.coloradocollege.edu/basics/contact/directory/",
        id="colorado-college",
    ),
]


@pytest.mark.parametrize(
    ("school_module", "profile_url", "blocked_directory"), PROFILE_CASES
)
def test_every_department_wires_enrich_and_only_profiles_are_fetched(
    monkeypatch, school_module, profile_url: str, blocked_directory: str
) -> None:
    enrich = school_module._ENRICH
    departments = school_module.SCHOOL["departments"]

    assert departments
    assert enrich["throttle"] == 0.15
    for department in departments:
        assert department["scrape"].get("profile_enrich") is enrich
        assert re.match(enrich["profile_url_re"], department["directory_url"]) is None

    fetched: list[str] = []

    def fake_fetch(url, **_kwargs):
        fetched.append(url)
        return BeautifulSoup(
            "<h1>Ada Lovelace</h1>"
            "<h2>Research Interests</h2><p>Computational ecology</p>",
            "html.parser",
        )

    monkeypatch.setattr("src.collectors.ucb_common.fetch_soup", fake_fetch)
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", True)

    faculty_graph._apply_profile_enrich(
        [
            {
                "name": "Ada Lovelace",
                "url": profile_url,
                "research_areas": "",
                "keywords": [],
            },
            {
                "name": "Ada Lovelace",
                "url": blocked_directory,
                "research_areas": "",
                "keywords": [],
            },
            {
                "name": "Ada Lovelace",
                "url": "https://evil.example/faculty/ada",
                "research_areas": "",
                "keywords": [],
            },
        ],
        {**enrich, "throttle": 0},
    )

    assert fetched == [profile_url]


@pytest.mark.parametrize(
    ("school_module", "profile_url", "label"),
    [
        pytest.param(
            middlebury_faculty,
            "https://www.middlebury.edu/college/people/catherine-combelles",
            "Areas of Interest",
            id="middlebury-label",
        ),
        pytest.param(
            coloradocollege_faculty,
            (
                "https://www.coloradocollege.edu/basics/contact/directory/"
                "people/bowman_amanda_catherine.html"
            ),
            "BIOGRAPHY AND RESEARCH INTERESTS",
            id="colorado-college-label",
        ),
    ],
)
def test_school_specific_label_reaches_record(
    monkeypatch, school_module, profile_url: str, label: str
) -> None:
    monkeypatch.setattr(
        "src.collectors.ucb_common.fetch_soup",
        lambda _url, **_kwargs: BeautifulSoup(
            f"<h1>Ada Lovelace</h1><h2>{label}</h2>"
            "<p>Computational ecology</p>",
            "html.parser",
        ),
    )
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", True)

    out = faculty_graph._apply_profile_enrich(
        [
            {
                "name": "Ada Lovelace",
                "url": profile_url,
                "research_areas": "",
                "keywords": [],
            }
        ],
        {**school_module._ENRICH, "throttle": 0},
    )

    assert out[0]["research_areas"] == "Computational ecology"
