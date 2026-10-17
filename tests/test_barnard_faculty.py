"""Barnard's faculty rosters moved to the main site; a fixture replay of the new grid.

On 2026-10-10 barnard_faculty emitted 0 records against 212 in the corpus
(suspicious_zero): all 22 department pages were fetched without an error and
each parsed 0 rows. Every ``<dept>.barnard.edu`` roster now redirects to
``barnard.edu/<dept>``, whose "department faculty grid" carries none of the
old person-card classes, and most cards no longer show an email.

The fixtures are cards copied from barnard.edu/biology and barnard.edu/math
and one profile page, fetched 2026-10-17. No test here touches the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.import_document import parse_import_html
from src.collectors.schools import barnard_faculty

FIXTURES = Path(__file__).parent / "fixtures" / "barnard"
# Keyed by the department word in the URL, so the old subdomain address (which
# now redirects to the same page) is served the page it would land on.
LISTINGS = {"biology": FIXTURES / "biology.html", "math": FIXTURES / "math.html"}
PROFILES = {"https://barnard.edu/profiles/elizabeth-bauer": FIXTURES / "profile_elizabeth-bauer.html"}
SHARD = Path(__file__).resolve().parents[1] / "data" / "processed" / "shards" / "barnard.json"


@pytest.fixture
def records(monkeypatch) -> dict[str, dict]:
    def fetch_soup(url, *args, bounded=False, **kwargs):
        if "/profiles/" in url:
            path = PROFILES.get(url)
        else:
            path = next((p for word, p in LISTINGS.items() if word in url), None)
        if path is None:
            return None
        raw = path.read_bytes()
        return parse_import_html(raw) if bounded else BeautifulSoup(raw, "html.parser")

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch_soup)
    monkeypatch.setattr(faculty_graph.time, "sleep", lambda _s: None)
    school = {**barnard_faculty.SCHOOL,
              "departments": [d for d in barnard_faculty.SCHOOL["departments"]
                              if d["short"] in {"BIOL", "MATH"}]}
    return {r["pi_name"]: r for r in faculty_graph.fetch_and_normalize(school, deep=True)}


def test_the_grid_yields_the_professors_and_lecturers_only(records):
    """Emeriti (Ammirato, Bayer) and staff (Anastasio, Cook) are dropped."""
    assert set(records) == {"Jordan Balaban", "Elizabeth Bauer", "Daniela De Silva", "Dusa McDuff"}


def test_a_profile_supplies_the_email_and_research_the_grid_omits(records):
    bauer = records["Elizabeth Bauer"]
    assert bauer["url"] == "https://barnard.edu/profiles/elizabeth-bauer"
    assert bauer["contact_email"] == "ebauer@barnard.edu"
    assert bauer["keywords"] == ["Molecular and cellular neuroscience", "Emotional memory"]
    assert bauer["department"] == "Department of Biology"


def test_an_email_on_the_card_is_kept(records):
    assert records["Dusa McDuff"]["contact_email"] == "dmcduff@barnard.edu"
    assert records["Dusa McDuff"]["url"] == "https://barnard.edu/profiles/dusa-mcduff"


def test_a_card_without_a_profile_link_falls_back_to_the_department_page(records):
    assert records["Daniela De Silva"]["url"] == "https://barnard.edu/math"


def test_the_moved_rows_keep_their_corpus_ids(records):
    """Ids hash the department code and the name, not the URL, so the move
    updates the published rows instead of minting new ones."""
    rows = json.loads(SHARD.read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("records") or rows.get("opportunities")
    corpus = {r["id"] for r in rows if r.get("source") == "barnard_faculty"}
    ids = {r["id"] for r in records.values()}
    assert ids and ids <= corpus


def test_every_department_is_read_from_the_main_site():
    for dept in barnard_faculty.SCHOOL["departments"]:
        assert dept["scrape"]["url"].startswith("https://barnard.edu/"), dept["short"]
        assert dept["scrape"]["profile_enrich"]["email_selector"]
