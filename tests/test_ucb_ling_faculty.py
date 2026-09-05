"""Offline tests for src.collectors.ucb_ling_faculty.

No network: fixtures mirror Linguistics's real markup — each faculty member is a
small one-cell table (rank + "Email:" + office + "Research and teaching:") named
by an <h2> heading that often links to the professor's personal site. Locks in
the parser, the personal-site / synthetic-anchor URL, inline email + research,
the linguistics keyword mapping, dedup, output shape, and id stability.

TWO templates are pinned, because pinning only one is how this collector broke
in production undetected. The department moved to lx.berkeley.edu and wrapped
each person in a ``div.panel-pane`` whose ``h2.pane-title`` holds the name; the
heading stopped being the table's previous sibling, the parser matched nothing,
and the collector returned 0 with status "ok" for four weeks — withholding the
entire UC Berkeley shard. This fixture set had encoded the OLD shape only, so it
stayed green throughout. ``PANE_LISTING_HTML`` is the current markup and
``LISTING_HTML`` the legacy one; both must parse.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.lib.contact_visibility import verified_send_target
from src.collectors.ucb_common import (
    _mark_fetched_soup_observation,
    dedup_by_profile_url,
    normalize_faculty,
)
from src.collectors.ucb_ling_faculty import LING_CONFIG, _scrape_ling_faculty_list


def _person(name: str, body: str, site: str | None) -> str:
    heading = (f'<h2><a href="{site}">{name}</a></h2>' if site else f"<h2>{name}</h2>")
    return f'{heading}<table><tr><td>{body}</td></tr></table>'


# One faculty with a personal-site link, one without (synthetic anchor URL).
LISTING_HTML = f"""
<div class="region-content">
  {_person("Gašper Beguš",
           "Associate Professor of Linguistics Email: begus@berkeley.edu Office: 1213 Dwinelle "
           "Research and teaching: Phonology, phonetics, computational linguistics",
           "https://www.gasperbegus.com/")}
  {_person("Amy Rose Deal",
           "Professor Email: ardeal@berkeley.edu Office: 1226 Dwinelle "
           "Research and teaching: Syntax, semantics, fieldwork",
           None)}
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=LING_CONFIG["url"],
        final_url=LING_CONFIG["url"],
    )
    return _scrape_ling_faculty_list(soup, LING_CONFIG["base"], LING_CONFIG["url"])


def test_parses_name_title_email_research():
    people = _scrape()
    begus = next(p for p in people if p["name"] == "Gašper Beguš")
    assert begus["title"] == "Associate Professor of Linguistics"
    assert begus["_contact_claim"]["contact_email"] == "begus@berkeley.edu"
    assert "phonology" in begus["research_areas"].lower()
    assert "Email:" not in begus["research_areas"]


def test_personal_site_link_used_as_url():
    begus = next(p for p in _scrape() if p["name"] == "Gašper Beguš")
    assert begus["url"] == "https://www.gasperbegus.com/"


def test_no_link_gets_synthetic_anchor_url():
    deal = next(p for p in _scrape() if p["name"] == "Amy Rose Deal")
    assert deal["url"] == f"{LING_CONFIG['url']}#amy-rose-deal"


def test_research_yields_linguistics_keywords():
    person = {"name": "Amy Rose Deal", "url": "x", "title": "Professor",
              "research_areas": "Syntax, semantics, phonology, fieldwork"}
    opp = normalize_faculty(person, LING_CONFIG)
    for kw in ("syntax", "semantics", "phonology"):
        assert kw in opp["keywords"], kw


def test_dedup_keeps_distinct_synthetic_and_real_urls():
    out = dedup_by_profile_url(_scrape())
    assert len(out) == 2  # distinct URLs -> both kept


def test_output_shape_with_email():
    begus = next(p for p in _scrape() if p["name"] == "Gašper Beguš")
    opp = normalize_faculty(begus, LING_CONFIG)
    assert opp["source"] == "ucb_ling_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-ling-")
    assert opp["contact_email"] == "begus@berkeley.edu"
    assert verified_send_target(opp) == "begus@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == []
    assert opp["on_campus"] is None
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ""
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    person = {"name": "Gašper Beguš", "url": "x", "title": "Professor"}  # no email/research
    opp = normalize_faculty(person, LING_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["linguistics"]


def test_unrelated_later_table_cannot_reuse_previous_professor_heading():
    html = (
        _person(
            "Ada Lovelace",
            "Professor Email: ada@berkeley.edu Research and teaching: Computing",
            None,
        )
        + "<div>Unrelated content</div><table><tr><td>"
        "Email: helper.person@berkeley.edu"
        "</td></tr></table>"
    )
    soup = BeautifulSoup(html, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=LING_CONFIG["url"],
        final_url=LING_CONFIG["url"],
    )
    people = _scrape_ling_faculty_list(
        soup,
        LING_CONFIG["base"],
        LING_CONFIG["url"],
    )
    assert [person["name"] for person in people] == ["Ada Lovelace"]
    opp = normalize_faculty(people[0], LING_CONFIG)
    assert verified_send_target(opp) == "ada@berkeley.edu"


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole LING
    corpus on the next scrape. Pin a real corpus id."""
    begus = next(p for p in _scrape() if p["name"] == "Gašper Beguš")
    assert normalize_faculty(begus, LING_CONFIG)["id"] == "faculty-ucb-ling-ac3cb928"


# --- current template (lx.berkeley.edu OpenBerkeley panes) -----------------
def _pane(name: str, body: str, site: str | None) -> str:
    """One person as the live page renders them: a pane titled by the name."""
    heading = (
        f'<h2 class="pane-title"><a href="{site}">{name}</a></h2>'
        if site else f'<h2 class="pane-title">{name}</h2>'
    )
    return (
        f'<div class="panel-pane pane-bundle-text clearfix">{heading}'
        f'<div class="pane-content"><div class="fieldable-panels-pane">'
        f'<div class="field-items"><div class="field-item even">'
        f'<table><tr><td>{body}</td></tr></table>'
        f"</div></div></div></div></div>"
    )


PANE_LISTING_HTML = f"""
<div class="region-content">
  <div class="panel-pane"><h2 class="pane-title">People</h2></div>
  {_pane("Gašper Beguš",
         "Associate Professor of Linguistics Email: begus@berkeley.edu "
         "Office: 1213 Dwinelle Hall "
         "Research and teaching: Phonology, phonetics, computational linguistics",
         "https://www.gasperbegus.com/")}
  {_pane("Sherry Hicks",
         "Lecturer in Linguistics Email: sherry.hicks@berkeley.edu "
         "Office: 1303 Dwinelle Hall "
         "Research and teaching: American Sign Language",
         None)}
  {_pane("Mosiah Bluecloud",
         "Assistant Researcher Email: mosiahbluecloud@berkeley.edu "
         "Office: 1215 Dwinelle Hall "
         "Research and teaching: Language documentation",
         "/")}
</div>
"""


def _scrape_panes():
    soup = BeautifulSoup(PANE_LISTING_HTML, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=LING_CONFIG["url"],
        final_url=LING_CONFIG["url"],
    )
    return _scrape_ling_faculty_list(soup, LING_CONFIG["base"], LING_CONFIG["url"])


def test_current_pane_template_parses_every_person():
    """The regression: this shape used to yield ZERO people."""
    people = _scrape_panes()
    assert [p["name"] for p in people] == [
        "Gašper Beguš", "Sherry Hicks", "Mosiah Bluecloud",
    ]


def test_pane_template_recovers_title_email_research():
    begus = next(p for p in _scrape_panes() if p["name"] == "Gašper Beguš")
    assert begus["title"] == "Associate Professor of Linguistics"
    assert begus["_contact_claim"]["contact_email"] == "begus@berkeley.edu"
    assert "phonology" in begus["research_areas"].lower()


def test_pane_template_keeps_personal_site_and_synthesizes_the_rest():
    people = {p["name"]: p["url"] for p in _scrape_panes()}
    assert people["Gašper Beguš"] == "https://www.gasperbegus.com/"
    assert people["Sherry Hicks"] == f"{LING_CONFIG['url']}#sherry-hicks"


def test_uninformative_href_does_not_become_the_record_url():
    """The live page carries href="/" for one appointment. Taken literally it
    would collide with every other such person and dedup would keep one."""
    people = {p["name"]: p["url"] for p in _scrape_panes()}
    assert people["Mosiah Bluecloud"] == f"{LING_CONFIG['url']}#mosiah-bluecloud"
    assert len(dedup_by_profile_url(_scrape_panes())) == 3


def test_pane_title_is_not_bound_to_a_multi_person_pane():
    """A pane holding two tables cannot prove which name owns which row, so it
    is skipped rather than binding one professor's name to another's email."""
    html = (
        '<div class="panel-pane"><h2 class="pane-title">Ada Lovelace</h2>'
        '<div class="pane-content">'
        "<table><tr><td>Professor Email: ada@berkeley.edu</td></tr></table>"
        "<table><tr><td>Email: helper@berkeley.edu</td></tr></table>"
        "</div></div>"
    )
    soup = BeautifulSoup(html, "html.parser")
    _mark_fetched_soup_observation(
        soup, requested_url=LING_CONFIG["url"], final_url=LING_CONFIG["url"],
    )
    assert _scrape_ling_faculty_list(
        soup, LING_CONFIG["base"], LING_CONFIG["url"],
    ) == []


def test_directory_url_is_the_live_host():
    """The old host only 301s today; a collector pinned to a redirect is one
    server-config change away from silently collecting nothing."""
    assert LING_CONFIG["url"] == "https://lx.berkeley.edu/people/faculty"
