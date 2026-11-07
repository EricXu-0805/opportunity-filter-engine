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


def test_labeled_phrases_split_commas_and_drops_sublabels():
    # Gies lists areas comma-joined under "Methods:" / "Applications:" sub-labels;
    # split_commas atomizes them and the colon sub-labels are dropped.
    html = ("<h3>Research Interests</h3><p>Methods:\nMachine learning, optimization\n"
            "Applications:\nSupply chain management, operations management</p>")
    assert h._labeled_phrases(_soup(html), split_commas=True) == [
        "Machine learning", "optimization",
        "Supply chain management", "operations management"]


def test_labeled_phrases_split_commas_drops_prose_fragments():
    # A prose description comma-shatters into clauses; connective-prefixed and
    # over-long fragments are dropped, real noun-phrase areas survive.
    html = ("<h3>Research Interests</h3><p>This research spans organizations, and communities, "
            "Collective Intelligence, to examine emergent behavior in teams, Archival Analysis, "
            "Journal of Finance</p>")  # journal = publication venue, not a topic
    out = h._labeled_phrases(_soup(html), split_commas=True)
    assert out == ["Collective Intelligence", "Archival Analysis"]


def test_labeled_phrases_default_keeps_commas_intact():
    # Without split_commas, a single comma-bearing area stays whole (Law/Carle/LER).
    html = "<h3>Research Interests</h3><p>Probability, Statistics and Stochastic Processes</p>"
    assert h._labeled_phrases(_soup(html)) == ["Probability, Statistics and Stochastic Processes"]


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
    # The broad field stands in for keywords only; the page stated no areas.
    assert [r["metadata"]["research_areas_raw"] for r in recs] == ["Soft Matter Tribology; Wear of Materials", ""]


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
    assert "Constitutional Law" in recs[0]["metadata"]["research_areas_raw"]
    assert recs[1]["metadata"]["research_areas_raw"] == ""


def test_ler_reverses_name_and_extracts_keywords(monkeypatch):
    def fake(url):
        return _soup(LER_LISTING) if url == h.LER_URL else _soup(LER_PROFILE)
    monkeypatch.setattr(h, "_fetch_soup", fake)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = h.fetch_ler()
    assert recs[0]["pi_name"] == "Leo Alexander"  # "Alexander, Leo" reversed
    assert recs[0]["contact_email"] == "leoa2@illinois.edu"
    assert "Employee recruitment and selection" in recs[0]["keywords"]
    assert recs[0]["metadata"]["research_areas_raw"].startswith("Employee recruitment and selection")


def test_ler_profile_without_interests_states_no_research_areas(monkeypatch):
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(LER_LISTING) if url == h.LER_URL else _soup("<p>Bio</p>"))
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = h.fetch_ler()
    assert {tuple(r["keywords"]) for r in recs} == {tuple(h.LER_CFG["keywords"])}
    assert {r["metadata"]["research_areas_raw"] for r in recs} == {""}


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
    # No profile is read: the unit's field is a keyword, never stated research.
    assert (music[0]["keywords"], music[0]["metadata"]["research_areas_raw"]) == (["music"], "")
    assert any(u.endswith("page/2/") for u in calls)  # paginated past page 1


# The listing's template: degrees after the dash in the heading, one
# p.position-title per role.
VETMED_LISTING = """
<div class="person-teaser">
  <div class="profile-picture"><img alt="" data-src="person1@illinois.edu" src="/directory/photos/person1.jpg"/></div>
  <div class="basic-info"><a href="/profile?id=person1"><h3 class="teaser-title">Avery Example <span> – DVM, PhD</span></h3></a>
  <p class="position-title">Example Director, Example Clinic</p><p class="position-title">Clinical Assistant Professor</p></div>
</div>
<div class="person-teaser">
  <div class="profile-picture"><img alt="" data-src="person2@illinois.edu" src="/directory/photos/person2.jpg"/></div>
  <div class="basic-info"><a href="/profile?id=person2"><h3 class="teaser-title">Blair Sample </h3></a>
  <p class="position-title">Research Assistant Professor</p></div>
</div>
<div class="person-teaser">
  <div class="profile-picture"><img alt="" data-src="person3@illinois.edu" src="/directory/photos/person3.jpg"/></div>
  <div class="basic-info"><a href="/profile?id=person3"><h3 class="teaser-title">Casey Placeholder <span> – DVM</span></h3></a></div>
</div>"""


def test_vetmed_extracts_img_email_and_reads_each_position_title_not_the_degrees(monkeypatch):
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(VETMED_LISTING))
    recs = h.fetch_vetmed()[:3]
    # A card that lists no degrees has no dash; its titles stay out of the name.
    assert [r["pi_name"] for r in recs] == ["Avery Example", "Blair Sample", "Casey Placeholder"]
    assert recs[0]["contact_email"] == "person1@illinois.edu"
    assert recs[0]["url"].startswith("https://vetmed.illinois.edu/profile?id=")
    titles = [r["metadata"]["faculty_title"] for r in recs]
    assert {r["metadata"]["research_areas_raw"] for r in recs} == {""}
    # No dash: the card's title was never read and fell to "Professor".
    assert titles == ["Example Director, Example Clinic; Clinical Assistant Professor",
                      "Research Assistant Professor", ""]


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
    assert chambers[0]["metadata"]["research_areas_raw"] == ""


# --- M149b: each collector reads the title its card or the profile it already
# fetches states, and writes none when neither states one. Synthetic people. ---

LAW_TITLED_LISTING = """
<article class="faculty-member"><div class="entry-details">
  <h2><a href="https://law.illinois.edu/faculty-research/faculty-profiles/avery-example/">Avery Example</a></h2>
  <p>Clinical Professor of Law<br/> Example Clinic Director</p></div></article>
<article class="faculty-member"><div class="entry-details">
  <h2><a href="https://law.illinois.edu/faculty-research/faculty-profiles/blair-sample/">Blair Sample</a></h2>
  <p>Example Chair in Law Emeritus</p></div></article>
<article class="faculty-member"><div class="entry-details">
  <h2><a href="https://law.illinois.edu/faculty-research/faculty-profiles/casey-placeholder/">Casey Placeholder</a></h2>
  </div></article>
"""


def test_law_reads_the_listing_title_one_role_per_line_and_an_emeritus_title_retires_the_row(monkeypatch):
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(LAW_TITLED_LISTING if url == h.LAW_URL else LAW_PROFILE))
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    recs = {r["pi_name"]: r["metadata"] for r in h.fetch_law()}
    assert recs["Avery Example"]["faculty_title"] == "Clinical Professor of Law; Example Clinic Director"
    assert recs["Avery Example"]["is_active"] is True
    # Read as "Professor" before, so the emeritus chair stayed listed.
    assert recs["Blair Sample"]["faculty_title"] == "Example Chair in Law Emeritus"
    assert (recs["Blair Sample"]["is_active"], recs["Blair Sample"]["deactivation_reason"]) == (
        False, "listed_as_emeritus")
    assert recs["Casey Placeholder"]["faculty_title"] == ""


LER_SYNTHETIC_LISTING = """<ul class="wp-block-list">
<li><a href="/directory/avery-example">Example, Avery</a></li></ul>"""
LER_TITLED_PROFILE = """<html><body><div class="profile-header__info">
<h2 class="profile-header__name">Avery Example</h2><p class="profile-header__ranking">ASSISTANT PROFESSOR</p>
<p class="profile-header__school">School of Labor &amp; Employment Relations</p></div>
<a href="mailto:person1@illinois.edu">person1@illinois.edu</a></body></html>"""


def test_ler_reads_the_title_its_profile_states_and_writes_none_without_it(monkeypatch):
    untitled = LER_TITLED_PROFILE.replace('<p class="profile-header__ranking">ASSISTANT PROFESSOR</p>', "")
    for profile, title in ((LER_TITLED_PROFILE, "ASSISTANT PROFESSOR"), (untitled, "")):
        monkeypatch.setattr(h, "_fetch_soup",
                            lambda url, p=profile: _soup(LER_SYNTHETIC_LISTING if url == h.LER_URL else p))
        monkeypatch.setattr(h.time, "sleep", lambda *a: None)
        assert {r["metadata"]["faculty_title"] for r in h.fetch_ler()} == {title}


MEDIA_SYNTHETIC_LISTING = """<div class="pt-cv-content-item"><h4 class="pt-cv-title">
  <a href="https://www.media.illinois.edu/example-avery/">Avery Example</a></h4></div>"""
MEDIA_TITLED_PROFILE = """<html><body><article><h1 class="entry-title">Avery Example</h1><div class="entry-content">
<div class="wp-block-column"><p class="has-medium-font-size wp-block-paragraph"><em><strong>Professor</strong></em><br/>
<em><strong>Associate Dean for Example Engagement</strong></em></p><h2>Affiliations</h2>
<p class="has-medium-font-size">Example Studies</p></div></div>
<a href="mailto:person1@illinois.edu">Email</a></article></body></html>"""


def test_media_reads_the_title_its_profile_states_and_writes_none_without_it(monkeypatch):
    untitled = '<a href="mailto:person1@illinois.edu">Email</a>'
    # A first paragraph that names no rank or appointment is no title.
    no_rank = MEDIA_TITLED_PROFILE.replace("<em><strong>Professor</strong></em><br/>", "").replace(
        "<em><strong>Associate Dean for Example Engagement</strong></em>", "Example Studies and Media")
    for profile, title in ((MEDIA_TITLED_PROFILE, "Professor; Associate Dean for Example Engagement"),
                           (untitled, ""), (no_rank, "")):
        monkeypatch.setattr(h, "_fetch_soup",
                            lambda url, p=profile: _soup(MEDIA_SYNTHETIC_LISTING if "-faculty/" in url else p))
        monkeypatch.setattr(h.time, "sleep", lambda *a: None)
        assert {r["metadata"]["faculty_title"] for r in h.fetch_media()} == {title}


def test_carle_and_faa_cards_without_a_title_get_none(monkeypatch):
    listing = """<div class="item person" data-netid="person1"><div class="details"><div class="name">Avery Example</div>
      </div></div>
    <div class="item person" data-netid="person2"><div class="details"><div class="name">Blair Sample</div>
      <div class="title">Teaching Associate Professor</div></div></div>"""
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(listing) if url == h.CARLE_URL else None)
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    assert [r["metadata"]["faculty_title"] for r in h.fetch_carle()] == ["", "Teaching Associate Professor"]
    for info in ("", '<div class="person-card__info">Avery Example <a href="mailto:p1@illinois.edu">p1@illinois.edu</a></div>'):
        card = _soup(f'<article class="person-card"><h2 class="linked-title">Avery Example</h2>{info}</article>')
        assert h._faa_card(card.select_one("article"), h.FAA_UNITS[0])["metadata"]["faculty_title"] == "", info


def test_ler_and_media_rows_whose_profile_cannot_be_read_get_no_title(monkeypatch):
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(LER_SYNTHETIC_LISTING) if url == h.LER_URL else None)
    assert {r["metadata"]["faculty_title"] for r in h.fetch_ler()} == {""}
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(MEDIA_SYNTHETIC_LISTING) if "-faculty/" in url else None)
    assert {r["metadata"]["faculty_title"] for r in h.fetch_media()} == {""}


def test_vetmed_cards_read_by_name_keep_the_ids_stored_under_their_old_names(monkeypatch):
    """The rows stored before 2026-10 under names that ran a degree-less card's
    titles in keep their ids (id_names), so they update in place."""
    listing = "".join(
        f'<div class="person-teaser"><div class="basic-info"><a href="/profile?id=p{i}">'
        f'<h3 class="teaser-title">{name}</h3></a><p class="position-title">Lecturer</p></div></div>'
        for i, name in enumerate(n for unit in h.VETMED_UNITS for n in unit.get("id_names", {})))
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(listing))
    recs = [r for r in h.fetch_vetmed() if r["department"] != "Department of Veterinary Clinical Medicine"]
    stored = {"faculty-vetmed-9f938cee": "Department of Pathobiology",
              "faculty-vetmed-f3ffd4f2": "Department of Pathobiology",
              "faculty-vetmed-64ace40c": "Department of Pathobiology",
              "faculty-vetmed-8164f832": "Department of Comparative Biosciences",
              "faculty-vetmed-d3591cd7": "Department of Comparative Biosciences"}
    by_unit = {u["name"]: set(u.get("id_names", {})) for u in h.VETMED_UNITS}
    assert {r["id"]: r["department"] for r in recs if r["pi_name"] in by_unit[r["department"]]} == stored
    assert all(" Lecturer" not in r["pi_name"] for r in recs)
    # Each stored name is the person's own, with the titles the old read ran in.
    assert all(old.startswith(f"{name} ") for u in h.VETMED_UNITS for name, old in u.get("id_names", {}).items())


def test_a_vetmed_name_with_a_hyphen_is_split_only_at_the_spaced_dash(monkeypatch):
    listing = """<div class="person-teaser">
  <div class="profile-picture"><img alt="" data-src="person1@illinois.edu"/></div>
  <div class="basic-info"><a href="/profile?id=person1"><h3 class="teaser-title">Avery Example-Sample <span> – DVM</span></h3></a>
  <p class="position-title">Clinical Assistant Professor</p></div></div>"""
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(listing))
    rec = h.fetch_vetmed()[0]
    assert (rec["pi_name"], rec["metadata"]["faculty_title"]) == ("Avery Example-Sample", "Clinical Assistant Professor")


# --- M165: an LER profile can list its research interests in one paragraph,
# between commas. Synthetic person and areas; only the structure is the page's. ---

def _ler_interests(paragraph: str, block: str = "p", after: str = "", heading: str = "h3") -> str:
    return f"""<html><body><div class="profile-bio"><h3>Education</h3><p>PhD, Mock Studies, 2001</p>
<{heading}>Research Interests</{heading}>
<{block}>{paragraph}</{block}>{after}
<h3>Courses</h3><p>LER 500 Mock Course</p></div>
<a href="mailto:person1@illinois.edu">person1@illinois.edu</a></body></html>"""


def _fetch_ler_profile(monkeypatch, profile: str) -> dict:
    monkeypatch.setattr(h, "_fetch_soup", lambda url: _soup(LER_SYNTHETIC_LISTING if url == h.LER_URL else profile))
    monkeypatch.setattr(h.time, "sleep", lambda *a: None)
    (rec,) = h.fetch_ler()
    return rec


def _reads_nothing(rec: dict) -> bool:
    return (rec["keywords"], rec["metadata"]["research_areas_raw"]) == (list(h.LER_CFG["keywords"]), "")


def test_ler_reads_each_area_of_a_research_interests_paragraph_that_lists_them_between_commas(monkeypatch):
    # A balanced parenthesis is part of its area; the last entry is six words,
    # the longest an entry may run.
    rec = _fetch_ler_profile(monkeypatch, _ler_interests(
        "Example Studies, Sample Markets, Placeholder Systems, Mock Dynamics (Sample), Dummy Rules Of Mock Example Firms"))
    areas = ["Example Studies", "Sample Markets", "Placeholder Systems", "Mock Dynamics (Sample)",
             "Dummy Rules Of Mock Example Firms"]
    assert rec["keywords"] == areas
    assert rec["metadata"]["research_areas_raw"] == "; ".join(areas)


def test_ler_keeps_a_repeated_area_once_and_the_first_eight_areas_of_a_comma_paragraph(monkeypatch):
    rec = _fetch_ler_profile(monkeypatch, _ler_interests(
        "Example Studies, Sample Markets, Example Studies, Placeholder Systems, Sample markets"))
    assert rec["keywords"] == ["Example Studies", "Sample Markets", "Placeholder Systems"]
    nine = [f"{w} Studies" for w in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota")]
    rec = _fetch_ler_profile(monkeypatch, _ler_interests(", ".join(nine)))
    assert rec["keywords"] == nine[:8]
    # Eight distinct areas: a repeat takes no room.
    rec = _fetch_ler_profile(monkeypatch, _ler_interests(", ".join(nine[:2] + nine[:1] + nine[2:])))
    assert rec["keywords"] == nine[:8]


def test_ler_reads_nothing_from_a_research_interests_paragraph_whose_commas_separate_anything_but_areas(monkeypatch):
    for paragraph in (
        # A sentence: its clauses after the first open in lower case.
        "Our group studies Example Markets, their mock dynamics, and sample outcomes",
        # Every entry capitalised, but one runs to seven words.
        "Example Studies, Sample Markets, How Small Groups Of Mock Example Firms",
        # Every entry a short capitalised phrase, but the paragraph ends a sentence.
        "Example Studies, Sample Markets, Placeholder Systems, Mock Dynamics, Dummy Rules.",
        # ... or holds a full stop in its middle.
        "Example Studies, Sample Markets. Placeholder Systems, Mock Dynamics, Dummy Rules",
        # No commas: one prose line.
        "Example Studies and Sample Markets across Placeholder Systems and Mock Dynamics",
        # A lead-in that names the section.
        "Research Interests Include Example Markets, Sample Bargaining, Placeholder Disputes",
        # A sub-label before a colon.
        "Areas: Example Markets, Sample Bargaining, Placeholder Disputes, Mock Dynamics",
        # A parenthesis whose own commas split it in two.
        "Example Economics (Mock Wages, Sample Unions), Placeholder Policy, Mock Relations",
    ):
        assert _reads_nothing(_fetch_ler_profile(monkeypatch, _ler_interests(paragraph))), paragraph


def test_ler_reads_a_comma_list_only_from_the_paragraph_under_the_first_research_heading(monkeypatch):
    areas = "Example Studies, Sample Markets, Placeholder Systems, Mock Dynamics, Dummy Rules"
    later = f"<h3>Research Areas</h3><p>{areas}</p>"
    # A <div> block is not read as a comma list, and the next labelled heading is not searched.
    assert _reads_nothing(_fetch_ler_profile(monkeypatch, _ler_interests(areas, block="div")))
    assert _reads_nothing(_fetch_ler_profile(monkeypatch, _ler_interests(areas, block="div", after=later)))
    # Once the first labelled paragraph is rejected, a later labelled heading is not searched either.
    prose = "Our group studies Example Markets, their mock dynamics, and sample outcomes"
    assert _reads_nothing(_fetch_ler_profile(monkeypatch, _ler_interests(prose, after=later)))


def test_ler_reads_no_comma_list_after_an_empty_research_interests_section(monkeypatch):
    # The heading's next element is the next section's heading; the paragraph
    # under that one states no research area.
    profile = """<html><body><div class="profile-bio"><h3>Research Interests</h3>
<h3>Courses</h3><p>LER 500 Mock Course, LER 501 Sample Course, LER 502 Placeholder Course</p></div>
<a href="mailto:person1@illinois.edu">person1@illinois.edu</a></body></html>"""
    assert _reads_nothing(_fetch_ler_profile(monkeypatch, profile))


def test_ler_reads_nothing_from_a_comma_paragraph_that_holds_a_line_break(monkeypatch):
    # Each line runs past _labeled_phrases' length guard. Read as one text, the
    # last area of a line and the first of the next would make one entry.
    lines = ("Alpha Studies, Beta Markets, Gamma Systems, Delta Dynamics, Epsilon Rules<br>"
             "Zeta Studies, Eta Markets, Theta Systems, Iota Dynamics, Kappa Rules")
    assert _reads_nothing(_fetch_ler_profile(monkeypatch, _ler_interests(lines)))
    # A line break inside inline markup is in the paragraph too.
    assert _reads_nothing(_fetch_ler_profile(monkeypatch, _ler_interests(f"<span>{lines}</span>")))


def test_ler_reads_a_comma_paragraph_under_an_h2_h4_or_summary_research_heading_too(monkeypatch):
    areas = "Example Studies, Sample Markets, Placeholder Systems, Mock Dynamics, Dummy Rules"
    for heading in ("h2", "h4", "summary"):
        rec = _fetch_ler_profile(monkeypatch, _ler_interests(areas, heading=heading))
        assert rec["keywords"] == areas.split(", "), heading


def test_ler_reads_nothing_from_a_comma_paragraph_with_one_unbalanced_parenthesis(monkeypatch):
    for paragraph in (
        # An opening parenthesis left unclosed ...
        "Example Studies, Sample Markets (Mock Firms, Placeholder Systems, Dummy Rules",
        # ... or a closing one never opened.
        "Example Studies, Sample Markets), Placeholder Systems, Mock Dynamics, Dummy Rules",
    ):
        assert _reads_nothing(_fetch_ler_profile(monkeypatch, _ler_interests(paragraph))), paragraph


def test_ler_keeps_a_semicolon_inside_the_comma_entry_that_holds_it(monkeypatch):
    # Entries lie between commas. Each half around the semicolon runs past
    # _labeled_phrases' length guard, so the comma read sees the whole paragraph.
    rec = _fetch_ler_profile(monkeypatch, _ler_interests(
        "Alpha Studies, Beta Markets, Gamma Systems, Delta Dynamics, Epsilon Rules; "
        "Zeta Studies, Eta Markets, Theta Systems, Iota Dynamics, Kappa Rules"))
    assert rec["keywords"] == ["Alpha Studies", "Beta Markets", "Gamma Systems", "Delta Dynamics",
                               "Epsilon Rules; Zeta Studies", "Eta Markets", "Theta Systems", "Iota Dynamics"]


def test_ler_comma_read_keeps_the_words_of_an_entry_with_inline_markup_apart():
    soup = _soup(_ler_interests("Example <em>Labor</em> Studies, Sample Markets, Placeholder Systems"))
    assert h._comma_listed_areas(soup) == ["Example Labor Studies", "Sample Markets", "Placeholder Systems"]


def test_ler_stores_an_entry_whose_source_text_wraps_with_single_spaces(monkeypatch):
    # The source wraps inside an entry, which a browser shows as one space.
    # Each line runs past _labeled_phrases' length guard.
    rec = _fetch_ler_profile(monkeypatch, _ler_interests(
        "Alpha Studies, Beta Markets, Gamma Systems, Delta Dynamics, Epsilon\n    Rules, "
        "Zeta Studies, Eta Markets, Theta Systems, Iota Dynamics"))
    areas = ["Alpha Studies", "Beta Markets", "Gamma Systems", "Delta Dynamics", "Epsilon Rules",
             "Zeta Studies", "Eta Markets", "Theta Systems"]
    assert rec["keywords"] == areas
    assert rec["metadata"]["research_areas_raw"] == "; ".join(areas)


def test_ler_reads_a_comma_with_no_space_after_it_as_a_separator_too(monkeypatch):
    rec = _fetch_ler_profile(monkeypatch, _ler_interests(
        "Alpha Studies,Beta Markets,Gamma Systems,Delta Dynamics,Epsilon Rules"))
    assert rec["keywords"] == ["Alpha Studies", "Beta Markets", "Gamma Systems", "Delta Dynamics", "Epsilon Rules"]


def test_ler_reads_a_paragraph_without_commas_of_six_capitalised_words_as_one_area(monkeypatch):
    # One entry, past _labeled_phrases' 60-character guard.
    phrase = "Placeholder Comparative Example Institutional Sample Arrangements"
    assert _fetch_ler_profile(monkeypatch, _ler_interests(phrase))["keywords"] == [phrase]


def test_ler_reads_a_research_interests_list_as_before_and_never_splits_its_items_on_commas(monkeypatch):
    rec = _fetch_ler_profile(monkeypatch, _ler_interests("Example Studies; Mock Rules, Test Forms and Sample Cases"))
    assert rec["keywords"] == ["Example Studies", "Mock Rules, Test Forms and Sample Cases"]
    listed = _ler_interests("<li>Example Studies, Sample Markets</li>", block="ul")
    assert _fetch_ler_profile(monkeypatch, listed)["keywords"] == ["Example Studies, Sample Markets"]


def test_ler_never_splits_a_research_interests_list_item_on_commas(monkeypatch):
    # A list item is one stated area however long; only a paragraph is read as a comma list.
    listed = _ler_interests(
        "<li>Example Studies, Sample Markets, Placeholder Systems, Mock Dynamics, Dummy Rules</li>", block="ul")
    assert _reads_nothing(_fetch_ler_profile(monkeypatch, listed))
