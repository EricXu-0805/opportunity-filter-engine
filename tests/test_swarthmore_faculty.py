"""Swarthmore's zero is the CI runner being turned away, not the parser.

swarthmore_faculty has emitted 0 records on every refresh run on GitHub's
runners (2026-08-15, 08-22, 08-29, 10-10) and a full roster from a machine
outside them (224 records on 2026-09-05, commit 614cc3a2): the site answers
the runner's address with a page that has no cards. The fixture is six cards
copied from swarthmore.edu/biology/faculty-staff as it was served on
2026-10-17, and the collector's selectors still read it. The block is not
worked around. No test here touches the network.
"""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import swarthmore_faculty

FIXTURE = Path(__file__).parent / "fixtures" / "swarthmore" / "biology.html"


def test_todays_biology_page_still_parses(monkeypatch):
    def fetch_soup(url, *args, **kwargs):
        return BeautifulSoup(FIXTURE.read_bytes(), "html.parser") if "/biology/" in url else None

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch_soup)
    school = {**swarthmore_faculty.SCHOOL,
              "departments": [d for d in swarthmore_faculty.SCHOOL["departments"]
                              if d["short"] == "BIOL"]}
    records = {r["pi_name"]: r for r in faculty_graph.fetch_and_normalize(school, deep=True)}
    # Visiting, laboratory-instructor and emerita cards are dropped; the
    # alumni class year comes off a name.
    assert set(records) == {"Vince Formica", "Bradley Davidson", "Stacey Miller"}
    assert records["Vince Formica"]["contact_email"] == "vformic1@swarthmore.edu"
    assert records["Stacey Miller"]["url"] == "https://www.swarthmore.edu/biology/faculty-staff"
