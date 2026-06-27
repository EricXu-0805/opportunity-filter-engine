"""Tests for the HTML-directory faculty collector (Carle + Law + LER).

Network is monkeypatched; the value is in the card parsing, profile-URL dedup,
'Last, First' reversal, and email/research-interest extraction."""
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
</body></html>"""

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


def test_carle_parses_listing_cards_with_email(monkeypatch):
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(CARLE_LISTING))
    recs = h.fetch_carle()
    assert len(recs) == 2
    assert recs[0]["pi_name"] == "Kashif Ahmad"
    assert recs[0]["contact_email"] == "kahmad@illinois.edu"
    assert recs[0]["source"] == "uiuc_faculty"
    assert recs[0]["department"] == "Carle Illinois College of Medicine"


def test_law_dedups_by_profile_url_and_enriches_email(monkeypatch):
    def fake(url):
        return _soup(LAW_LISTING) if url == h.LAW_URL else _soup(LAW_PROFILE)
    monkeypatch.setattr(h, "_fetch_soup", fake)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = h.fetch_law()
    assert [r["pi_name"] for r in recs] == ["Jane Doe", "John Roe"]  # 3 articles -> 2 unique
    assert recs[0]["contact_email"] == "jdoe@illinois.edu"


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
