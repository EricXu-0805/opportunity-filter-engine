"""Georgetown's three card templates, as its pages wrote them on 2026-11-24.

Sixteen units read nothing for weeks after the site changed the markup under
their selectors. Each test feeds the unit's own configuration a page in that
markup, with invented people.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.collectors import faculty_graph as fg
from src.collectors.schools.georgetown_faculty import SCHOOL


def _read(monkeypatch, short: str, body: str) -> dict[str, dict]:
    monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                        lambda url, **_kw: BeautifulSoup(f"<html><body>{body}</body></html>", "html.parser"))
    dept = next(d for d in SCHOOL["departments"] if d["short"] == short)
    return {p["name"]: p for p in fg._scrape_directory(dept)}


def _compact(name: str, rank: str, slug: str) -> str:
    return ('<div class="gu-cards-card gu-block gu-block-people-profiles-card">'
            '<div class="gu-cards-card-text">'
            '<p class="gu-block gu-paragraph gu-block-people-profiles-title">'
            f'<a class="gu-link gu-block-people-profiles-link" href="https://x.example.edu/profiles/{slug}/">{name}</a></p> '
            f'<p class="gu-block gu-paragraph gu-block-people-profiles-text">{rank}</p></div></div>')


def test_the_compact_card_reads_people_and_not_the_page_s_other_cards(monkeypatch):
    seminar = ('<div class="gu-cards-card gu-block"><div class="gu-cards-card-text">'
               '<p><a href="https://x.example.edu/seminar/">Spring Seminar Series</a></p>'
               '<p>Assistant Professor Sam Vale speaks</p></div></div>')
    people = _read(monkeypatch, "CLSS",
                   _compact("Ada Quill", "Associate Professor", "ada-quill")
                   + _compact("Ben Stowe", "Professor Emeritus", "ben-stowe")
                   + seminar)

    # One row: the emeritus card is filtered, the seminar card is no card.
    assert list(people) == ["Ada Quill"]
    assert people["Ada Quill"]["title"] == "Associate Professor"
    assert people["Ada Quill"]["url"] == "https://x.example.edu/profiles/ada-quill/"


def test_the_mccourt_person_block_reads_name_rank_and_profile_link(monkeypatch):
    def person(name: str, rank: str, slug: str) -> str:
        return ('<div class="wp-block-gu-person" itemscope itemtype="http://schema.org/Person">'
                '<div class="wp-block-gu-surface"><div class="gu-profile-content">'
                f'<div itemprop="name"><a href="https://x.example.edu/profiles/{slug}/">{name}</a></div>'
                f'<div itemprop="jobTitle">{rank}</div></div></div></div>')

    people = _read(monkeypatch, "MCCT",
                   person("Cora Finch", "Assistant Professor", "cora-finch")
                   + person("Dov Marsh", "Associate Teaching Professor; Faculty Director, MPP", "dov-marsh")
                   + person("Ema Holt", "Professor Emerita", "ema-holt"))

    assert set(people) == {"Cora Finch", "Dov Marsh"}
    assert people["Cora Finch"]["title"] == "Assistant Professor"
    assert people["Dov Marsh"]["url"] == "https://x.example.edu/profiles/dov-marsh/"


def test_a_computer_science_card_gives_its_whole_position_line_and_no_link_text(monkeypatch):
    def card(name: str, position: str, local: str, interests: str, button: str, href: str) -> str:
        return ('<div class="gu-block gu-block-media-text gu-block-image-text-cta">'
                '<div class="gu-block gu-container gu-block-image-text-cta-text-content">'
                f'<h2 class="gu-block gu-heading gu-block-image-text-cta-text-content-heading">{name}</h2> '
                '<p class="gu-block gu-paragraph gu-block-image-text-cta-text-content-text">'
                f'<strong>Position</strong>: {position}<br/><strong>Email</strong>: '
                f'<a href="mailto:{local}@x.example.edu">{local}@x.example.edu</a><br/>'
                f'<em>Interests</em>: {interests}</p> '
                f'<a class="link link-incentive gu-block-image-text-cta-text-content-link" href="{href}">{button}</a>'
                '</div></div>')

    people = _read(monkeypatch, "CS",
                   card("Eli Roe", "Associate Professor", "eroe", "compilers, type systems",
                        "Dr. Roe’s website", "https://roe.example.edu/")
                   + card("Fay Burns", "Professor of Practice", "fburns", "GPU computing",
                          "Dr. Burns’ Profile", "https://x.example.edu/s/contact/1/fay-burns")
                   + card("Gil Van Der Meer", "Research Professor", "gvandermeer", "privacy, measurement",
                          "Dr. Van Der Meer’s Profile", "https://x.example.edu/s/contact/2/gil")
                   + card("Hal Pike", "Associate Professor Emeritus", "hpike", "databases",
                          "Dr. Pike’s Profile", "https://x.example.edu/s/contact/3/hal-pike")
                   # No "Email:" label: the position line still ends at the next label.
                   + ('<div class="gu-block gu-block-media-text gu-block-image-text-cta">'
                      '<div class="gu-block gu-container gu-block-image-text-cta-text-content">'
                      '<h2 class="gu-block gu-heading">Ira Voss</h2> <p class="gu-block gu-paragraph">'
                      '<strong>Position</strong>: Teaching Professor Emeritus<br/>'
                      '<em>Interests</em>: algorithms</p></div></div>'))

    # The emeritus card is dropped: the ladder filter reads the whole line.
    assert set(people) == {"Eli Roe", "Fay Burns", "Gil Van Der Meer"}
    assert people["Eli Roe"]["title"] == "Associate Professor"
    assert people["Fay Burns"]["title"] == "Professor of Practice"
    assert people["Eli Roe"]["research_areas"] == "compilers, type systems"
    assert people["Fay Burns"]["research_areas"] == "GPU computing"
    assert people["Gil Van Der Meer"]["research_areas"] == "privacy, measurement"
    assert people["Eli Roe"]["url"] == "https://roe.example.edu/"
    assert people["Eli Roe"]["email"] == "eroe@x.example.edu"


def test_a_respelled_name_maps_to_one_stored_spelling_and_back_to_none():
    for dept in SCHOOL["departments"]:
        names = dept.get("id_names") or {}
        assert len(set(names.values())) == len(names), dept["short"]
        assert not set(names) & set(names.values()), dept["short"]
        for today, stored in names.items():
            assert fg._id_tail(dept["short"], stored) != fg._id_tail(dept["short"], today)



def test_english_uses_the_bio_link_within_each_faculty_card(monkeypatch):
    html = """
    <div class="gu-block-media-text"><h2>Ada Quill</h2>
      <p><strong>Assistant Teaching Professor</strong></p>
      <a href="/seminars/">Seminars</a>
      <a class="gu-block-image-text-cta-text-content-link" href="/bio/quill/">View bio</a>
    </div>
    """
    people = _read(monkeypatch, "ENGL", html)
    assert people["Ada Quill"]["url"] == "https://english.georgetown.edu/bio/quill/"
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "ENGL")
    record = fg._normalize(SCHOOL, dept, people["Ada Quill"])
    assert record["url"] == people["Ada Quill"]["url"]
    assert record["source_url"] == dept["directory_url"]
