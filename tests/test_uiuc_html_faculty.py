"""Tests for the HTML-directory faculty collector (Carle + Law + LER).

Network is monkeypatched; the value is in the card parsing, profile-URL dedup,
'Last, First' reversal, and email/research-interest extraction — including the
per-profile research-area enrichment that lifts Carle + Law off their bare
department broad field."""
from __future__ import annotations

from bs4 import BeautifulSoup

import src.collectors.uiuc_html_faculty as h


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


CARLE_LISTING = """
<div class="item person cat3 cicom-btsci" data-netid="kahmad">
  <div class="details"><div class="name">Kashif  Ahmad</div>
  <div class="title">Adjunct Teaching Professor</div>
  <div class="contact"><span class="email"><a href="mailto:kahmad@illinois.edu">email</a></span></div>
  </div></div>
<div class="item person cat3 cicom-btsci" data-netid="jamos">
  <div class="details"><div class="name">Jenny Amos</div>
  <div class="title">Teaching Associate Professor</div>
  <div class="contact"><span class="email"><a href="mailto:jamos@illinois.edu">email</a></span></div>
  </div></div>
"""

LAW_LISTING = """
<article class="faculty-member"><h2><a href="https://law.illinois.edu/faculty/faculty-profiles/jane-doe/">Jane Doe</a></h2></article>
<article class="faculty-member"><h2><a href="https://law.illinois.edu/faculty/faculty-profiles/jane-doe/">Jane Doe</a></h2></article>
<article class="faculty-member"><h2><a href="https://law.illinois.edu/faculty/faculty-profiles/john-roe/">John Roe</a></h2></article>
"""

LAW_PROFILE = """<html><body>
<a href="mailto:jdoe@illinois.edu">Email</a>
<a href="mailto:assistant@illinois.edu">Assistant</a>
<details><summary>Areas of Expertise</summary>
<div class="il-formatted"><p>Civil Procedure<br>Constitutional Law<br>Federal Courts</p></div>
</details>
</body></html>"""

# A Law profile with no expertise disclosure -> the collector keeps the broad field.
LAW_PROFILE_NO_AREAS = """<html><body>
<a href="mailto:jroe@illinois.edu">Email</a>
<h3>Education</h3><p>J.D., somewhere</p>
</body></html>"""

CARLE_PROFILE_RI = """<html><body>
<h2>Research Interests</h2>
<ul><li>Soft Matter Tribology</li><li>Wear of Materials</li></ul>
</body></html>"""

CARLE_PROFILE_NO_RI = """<html><body><h2>Education</h2><p>PhD</p></body></html>"""

LER_LISTING = """
<ul class="wp-block-list">
<li><a href="/directory/leo-alexander">Alexander, Leo</a></li>
<li><a href="/directory/robert-bruno/">Bruno, Robert</a></li>
</ul>
"""

LER_PROFILE = """<html><body>
<a href="mailto:leoa2@illinois.edu">Email</a>
<h3>Research Interests</h3>
<p>Employee recruitment and selection; Adverse impact; Psychometrics</p>
</body></html>"""


def test_first_illinois_email_takes_first_illinois_mailto():
    assert h._first_illinois_email(_soup(LAW_PROFILE)) == "jdoe@illinois.edu"


def test_first_illinois_email_empty_when_none():
    assert h._first_illinois_email(_soup("<a href='mailto:x@gmail.com'>x</a>")) == ""


def test_research_interests_atomizes_semicolon_block():
    out = h._research_interests(_soup(LER_PROFILE))
    assert out == ["Employee recruitment and selection", "Adverse impact", "Psychometrics"]


def test_labeled_phrases_reads_law_areas_of_expertise_summary():
    # Real Law DOM: matching the <summary>, find_next returns a wrapping <div>
    # whose text REPEATS the 'Areas of Expertise' label before the <br>-separated
    # areas — the label itself must not leak in as a keyword.
    html = ("<details><summary>Areas of Expertise</summary>"
            "<div>Areas of Expertise<p>Civil Procedure<br>Constitutional Law<br>Federal Courts</p></div>"
            "</details>")
    assert h._labeled_phrases(_soup(html)) == [
        "Civil Procedure", "Constitutional Law", "Federal Courts"]


def test_labeled_phrases_drops_prose_so_caller_falls_back():
    # A profile that describes its research in a sentence yields no phrases.
    html = "<h2>Research Interests</h2><div>My research objective is to understand how genes and hormones interact across the lifespan.</div>"
    assert h._labeled_phrases(_soup(html)) == []


def test_carle_parses_listing_and_enriches_from_profile(monkeypatch):
    def fake(url):
        if url == h.CARLE_URL:
            return _soup(CARLE_LISTING)
        return _soup(CARLE_PROFILE_RI) if "kahmad" in url else _soup(CARLE_PROFILE_NO_RI)
    monkeypatch.setattr(h, "_fetch_soup", fake)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = h.fetch_carle()
    assert len(recs) == 2
    assert recs[0]["pi_name"] == "Kashif Ahmad"
    assert recs[0]["contact_email"] == "kahmad@illinois.edu"
    assert recs[0]["source"] == "uiuc_faculty"
    assert recs[0]["department"] == "Carle Illinois College of Medicine"
    assert "Soft Matter Tribology" in recs[0]["keywords"]   # enriched from profile
    assert recs[1]["keywords"] == ["biomedical sciences"]   # no RI section -> broad


def test_law_dedups_by_profile_url_and_enriches_email_and_areas(monkeypatch):
    def fake(url):
        if url == h.LAW_URL:
            return _soup(LAW_LISTING)
        return _soup(LAW_PROFILE) if "jane-doe" in url else _soup(LAW_PROFILE_NO_AREAS)
    monkeypatch.setattr(h, "_fetch_soup", fake)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = h.fetch_law()
    assert [r["pi_name"] for r in recs] == ["Jane Doe", "John Roe"]  # 3 articles -> 2 unique
    assert recs[0]["contact_email"] == "jdoe@illinois.edu"
    assert "Constitutional Law" in recs[0]["keywords"]      # enriched from Areas of Expertise
    assert recs[1]["keywords"] == ["law"]                   # no expertise section -> broad


def test_ler_reverses_name_and_extracts_keywords(monkeypatch):
    def fake(url):
        return _soup(LER_LISTING) if url == h.LER_URL else _soup(LER_PROFILE)
    monkeypatch.setattr(h, "_fetch_soup", fake)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = h.fetch_ler()
    assert recs[0]["pi_name"] == "Leo Alexander"  # "Alexander, Leo" reversed
    assert recs[0]["contact_email"] == "leoa2@illinois.edu"
    assert "Employee recruitment and selection" in recs[0]["keywords"]


def test_ler_relative_links_made_absolute(monkeypatch):
    captured = []

    def fake(url):
        captured.append(url)
        return _soup(LER_LISTING) if url == h.LER_URL else _soup(LER_PROFILE)
    monkeypatch.setattr(h, "_fetch_soup", fake)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    h.fetch_ler()
    assert any(u.startswith("https://ler.illinois.edu/directory/") for u in captured)


FAA_PAGE = """
<article class="person-card"><div class="person-card__info">
  <h2 class="linked-title"><a class="linked-title__link"
    href="https://music.illinois.edu/people/profiles/andrew-anderson/">Andrew Anderson</a></h2>
  Andrew Anderson Assistant Professor of Double Bass</div>
  <a href="mailto:bassist@illinois.edu">email</a></article>
"""


def test_faa_card_parses_name_title_email_and_paginates(monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        # page 1 has a card; page 2 is empty -> pagination stops
        return _soup(FAA_PAGE) if url.rstrip("/").endswith("faculty") else _soup("<html></html>")
    monkeypatch.setattr(h, "_fetch_soup", fake)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = h.fetch_faa()
    music = [r for r in recs if r["department"] == "School of Music"]
    assert len(music) == 1
    assert music[0]["pi_name"] == "Andrew Anderson"
    assert music[0]["contact_email"] == "bassist@illinois.edu"
    assert "Double Bass" in music[0]["metadata"]["faculty_title"]
    assert any(u.endswith("page/2/") for u in calls)  # paginated past page 1


VETMED_LISTING = """
<div class="person-teaser">
  <a href="/profile?id=baratta3">Alyssa Baratta-Martin – DVM Instructor</a>
  <img data-src="baratta3@illinois.edu">
</div>"""


def test_vetmed_extracts_img_email_and_splits_name_title(monkeypatch):
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(VETMED_LISTING))
    recs = h.fetch_vetmed()
    assert recs[0]["pi_name"] == "Alyssa Baratta-Martin"
    assert recs[0]["contact_email"] == "baratta3@illinois.edu"
    assert recs[0]["metadata"]["faculty_title"] == "DVM Instructor"
    assert recs[0]["url"].startswith("https://vetmed.illinois.edu/profile?id=")


MEDIA_LISTING = """
<div class="pt-cv-content-item"><h4 class="pt-cv-title">
  <a href="https://media.illinois.edu/chambers-jason-p/">Jason P. Chambers</a></h4></div>"""
MEDIA_PROFILE = '<a href="mailto:jpchambe@illinois.edu">Email</a>'


def test_media_enriches_email_from_profile(monkeypatch):
    def fake(url):
        return _soup(MEDIA_LISTING) if "-faculty/" in url else _soup(MEDIA_PROFILE)
    monkeypatch.setattr(h, "_fetch_soup", fake)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = h.fetch_media()
    chambers = [r for r in recs if r["pi_name"] == "Jason P. Chambers"]
    assert chambers and chambers[0]["contact_email"] == "jpchambe@illinois.edu"
    assert chambers[0]["department"] == "Department of Advertising"
