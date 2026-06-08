"""Offline tests for src.collectors.ucb_eecs_faculty.

No network: the parser is exercised against a small HTML fixture that mirrors
the real EECS directory markup (div.cc-image-list__item__content > h3 a, a
<p> with the rank in the first <strong>, an inline Berkeley email, and
/Research/Areas/ topic links). Locks in the parser, the Berkeley-specific
normalized schema, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_eecs_faculty import (
    EECS_CONFIG,
    _scrape_eecs_faculty_list,
    normalize_faculty,
)

# Two faculty cards (one fully populated, one missing email/areas) plus a
# non-faculty card with no Homepages link that must be ignored.
FIXTURE_HTML = """
<div class="cc-image-list__items">
  <div class="cc-image-list__item">
    <div class="cc-image-list__item__content">
      <h3><span id="A"></span><a href="/Faculty/Homepages/abbeel.html">Pieter Abbeel</a></h3>
      <p>
        <strong>Professor</strong>
        <br>746 Sutardja Dai Hall, (510) 642-7034; pabbeel@cs.berkeley.edu
        <br><strong>Research Interests:</strong>
        <a href="/Research/Areas/AI">Artificial Intelligence (AI)</a>;
        <a href="/Research/Areas/CIR">Robotics</a>
        <br><strong>Education:</strong> 2008, Ph.D., Stanford University
      </p>
    </div>
  </div>
  <div class="cc-image-list__item">
    <div class="cc-image-list__item__content">
      <h3><a href="/Faculty/Homepages/noemail.html">Jane Researcher</a></h3>
      <p><strong>Associate Professor</strong><br>123 Cory Hall</p>
    </div>
  </div>
  <div class="cc-image-list__item">
    <div class="cc-image-list__item__content">
      <h3><a href="/about/contact.html">Department Office</a></h3>
      <p>Not a faculty profile link.</p>
    </div>
  </div>
</div>
"""


def _scrape():
    soup = BeautifulSoup(FIXTURE_HTML, "html.parser")
    return _scrape_eecs_faculty_list(soup, EECS_CONFIG["base"])


def test_parser_extracts_only_homepages_faculty():
    people = _scrape()
    # The contact-office card has no /Faculty/Homepages/ link, so it's skipped.
    assert len(people) == 2
    assert {p["name"] for p in people} == {"Pieter Abbeel", "Jane Researcher"}


def test_parser_pulls_email_title_and_research_areas():
    abbeel = next(p for p in _scrape() if p["name"] == "Pieter Abbeel")
    assert abbeel["email"] == "pabbeel@cs.berkeley.edu"
    assert abbeel["title"] == "Professor"
    assert "Robotics" in abbeel["research_areas"]
    assert abbeel["url"].startswith("https://www2.eecs.berkeley.edu/Faculty/Homepages/")


def test_parser_handles_missing_email_and_areas():
    jane = next(p for p in _scrape() if p["name"] == "Jane Researcher")
    assert "email" not in jane
    assert "research_areas" not in jane


def test_normalize_produces_berkeley_schema():
    abbeel = next(p for p in _scrape() if p["name"] == "Pieter Abbeel")
    opp = normalize_faculty(abbeel, EECS_CONFIG)
    assert opp["source"] == "ucb_eecs_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["location"] == "Berkeley, CA"
    assert opp["pi_name"] == "Pieter Abbeel"
    assert opp["contact_email"] == "pabbeel@cs.berkeley.edu"
    assert opp["id"].startswith("faculty-ucb-eecs-")
    # research areas drove real keywords, not just the broad fallback.
    assert "robotics" in opp["keywords"]
    assert opp["metadata"]["confidence_score"] == 0.7  # has email


def test_normalize_falls_back_to_broad_field_without_areas():
    jane = next(p for p in _scrape() if p["name"] == "Jane Researcher")
    opp = normalize_faculty(jane, EECS_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5  # no email
    assert opp["keywords"] == EECS_CONFIG["keywords"][:1]


def test_id_is_deterministic():
    abbeel = next(p for p in _scrape() if p["name"] == "Pieter Abbeel")
    a = normalize_faculty(abbeel, EECS_CONFIG)["id"]
    b = normalize_faculty(abbeel, EECS_CONFIG)["id"]
    assert a == b
