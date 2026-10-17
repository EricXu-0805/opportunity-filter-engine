"""Barnard's faculty rosters moved to the main site; a fixture replay of the new grid.

On 2026-10-10 barnard_faculty emitted 0 records against 212 in the corpus
(suspicious_zero): all 22 department pages were fetched without an error and
each parsed 0 rows. Every ``<dept>.barnard.edu`` roster now redirects to
``barnard.edu/<dept>``, whose "department faculty grid" carries none of the
old person-card classes, and most cards no longer show an email.

The fixtures are cards copied from barnard.edu/biology, /math, /history,
/anthropology and /neuroscience and one profile page, fetched 2026-10-17. No
test here touches the network.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.import_document import parse_import_html
from src.collectors.schools import barnard_faculty

FIXTURES = Path(__file__).parent / "fixtures" / "barnard"
# Keyed by the department word in the URL, so the old subdomain address (which
# now redirects to the same page) is served the page it would land on.
LISTINGS = {word: FIXTURES / f"{word}.html"
            for word in ("biology", "math", "history", "anthropology", "neuroscience")}
PROFILES = {"https://barnard.edu/profiles/elizabeth-bauer": FIXTURES / "profile_elizabeth-bauer.html"}
SHARD = Path(__file__).resolve().parents[1] / "data" / "processed" / "shards" / "barnard.json"


def _harvest(monkeypatch, shorts: set[str], profiles: dict = PROFILES) -> tuple[dict[str, dict], Counter]:
    """Records by name for the given departments, and how often each URL was fetched."""
    fetched: Counter = Counter()

    def fetch_soup(url, *args, bounded=False, **kwargs):
        fetched[url] += 1
        if "/profiles/" in url:
            path = profiles.get(url)
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
                              if d["short"] in shorts]}
    records = faculty_graph.fetch_and_normalize(school, deep=True)
    return {r["pi_name"]: r for r in records}, fetched


def _shard_rows() -> list[dict]:
    rows = json.loads(SHARD.read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("records") or rows.get("opportunities")
    return [r for r in rows if r.get("source") == "barnard_faculty"]


@pytest.fixture
def records(monkeypatch) -> dict[str, dict]:
    return _harvest(monkeypatch, {"BIOL", "MATH"})[0]


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
    corpus = {r["id"] for r in _shard_rows()}
    ids = {r["id"] for r in records.values()}
    assert ids and ids <= corpus


def test_every_department_is_read_from_the_main_site():
    for dept in barnard_faculty.SCHOOL["departments"]:
        assert dept["scrape"]["url"].startswith("https://barnard.edu/"), dept["short"]
        assert dept["scrape"]["profile_enrich"]["email_selector"]


def test_a_card_with_no_rank_is_dropped(monkeypatch):
    """History's emeriti, Italian's "1951-1990" and English's "Barnard's
    Tradition of Writers" cards carry no rank line at all (21 cards across the
    22 pages on 2026-10-17); a rank-less card is not a professor or lecturer."""
    records, _ = _harvest(monkeypatch, {"HIST"})
    assert "Joel Kaye, Professor Emeritus" not in records
    assert "Mark C. Carnes" in records


def test_the_visting_typo_still_reads_as_visiting(monkeypatch):
    records, _ = _harvest(monkeypatch, {"HIST"})
    assert "Michele Alacevich" not in records


def test_a_rank_run_into_the_name_still_reads_as_the_rank(monkeypatch):
    """The card's rank line reads "Nadia Abu El-HajProfessor of Anthropology
    & Chair of Anthropology", with no space after the name."""
    records, _ = _harvest(monkeypatch, {"ANTH"})
    chair = records["Nadia Abu El-Haj"]
    assert chair["metadata"]["faculty_title"] == "Professor of Anthropology & Chair of Anthropology"
    assert chair["title"].startswith("Prof. Nadia Abu El-Haj")
    assert records["Severin Fowles"]["metadata"]["faculty_title"].startswith("Professor of Anthropology")


def test_each_page_is_fetched_once_per_run(monkeypatch):
    """A card with no profile link points at its department page, which is not
    a profile; and Elizabeth Bauer, listed by Biology and by Neuroscience, has
    one profile page."""
    records, fetched = _harvest(monkeypatch, {"BIOL", "MATH", "NBB"})
    assert records["Daniela De Silva"]["url"] == "https://barnard.edu/math"
    assert records["Elizabeth Bauer"]["contact_email"] == "ebauer@barnard.edu"
    assert fetched["https://barnard.edu/profiles/elizabeth-bauer"] == 1
    assert {url: n for url, n in fetched.items() if n > 1} == {}


def test_a_profile_that_cannot_be_read_keeps_the_stored_email(monkeypatch, tmp_path):
    """barnard.edu answered GitHub's runners 403 on one page on 2026-10-10. A
    profile that cannot be read leaves the fresh record with no email, and the
    merge keeps the address the corpus already holds for that id."""
    records, _ = _harvest(monkeypatch, {"BIOL"}, profiles={})
    bauer = records["Elizabeth Bauer"]
    assert bauer["contact_email"] is None
    stored = next(r for r in _shard_rows() if r["id"] == bauer["id"])
    assert stored["contact_email"] == "ebauer@barnard.edu"
    processed = tmp_path / "opportunities.json"
    processed.write_text(json.dumps([stored]), encoding="utf-8")
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", processed)
    assert barnard_faculty.merge_into_processed([bauer]) == (0, 1)
    merged = json.loads(processed.read_text(encoding="utf-8"))
    assert merged[0]["contact_email"] == "ebauer@barnard.edu"
