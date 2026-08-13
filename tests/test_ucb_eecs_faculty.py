"""Offline tests for src.collectors.ucb_eecs_faculty.

No network: the parser is exercised against a small HTML fixture that mirrors
the real EECS directory markup (div.cc-image-list__item__content > h3 a, a
<p> with the rank in the first <strong>, an inline Berkeley email, and
/Research/Areas/ topic links). Locks in the parser, the Berkeley-specific
normalized schema, and id stability — the EECS path now runs through
ucb_common (shared fetch/normalize/merge), so these tests also pin that the
consolidation changed no record-visible behavior.
"""

from __future__ import annotations

import os
import sys

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.lib.contact_visibility import verified_send_target
from src.collectors import ucb_common
from src.collectors.ucb_common import fetch_soup, normalize_faculty
from src.collectors.ucb_eecs_faculty import (
    EECS_AREA_KEYWORDS,
    EECS_CONFIG,
    _scrape_eecs_faculty_list,
)

# Four faculty cards (one fully populated, one missing email/areas, one with
# the directory's no_email@ placeholder, one emeritus) plus a non-faculty card
# with no Homepages link that must be ignored.
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
      <h3><a href="/Faculty/Homepages/attwood.html">David Attwood</a></h3>
      <p><strong>Professor</strong><br>no_email@eecs.berkeley.edu
      <br><strong>Research Interests:</strong>
      <a href="/Research/Areas/PHO">Optics</a></p>
    </div>
  </div>
  <div class="cc-image-list__item">
    <div class="cc-image-list__item__content">
      <h3><a href="/Faculty/Homepages/sequin.html">Carlo H. Séquin</a></h3>
      <p><strong>Professor Emeritus</strong><br>sequin@cs.berkeley.edu
      <br><strong>Research Interests:</strong>
      <a href="/Research/Areas/GR">Computer Graphics</a></p>
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
    ucb_common._mark_fetched_soup_observation(
        soup,
        requested_url=EECS_CONFIG["url"],
        final_url=EECS_CONFIG["url"],
    )
    return _scrape_eecs_faculty_list(soup, EECS_CONFIG["base"])


def test_parser_extracts_only_homepages_faculty():
    people = _scrape()
    # The contact-office card has no /Faculty/Homepages/ link, so it's skipped.
    assert len(people) == 4
    assert {p["name"] for p in people} == {
        "Pieter Abbeel", "Jane Researcher", "David Attwood", "Carlo H. Séquin",
    }


def test_parser_pulls_email_title_and_research_areas():
    abbeel = next(p for p in _scrape() if p["name"] == "Pieter Abbeel")
    assert abbeel["_contact_claim"]["contact_email"] == "pabbeel@cs.berkeley.edu"
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
    assert verified_send_target(opp) == "pabbeel@cs.berkeley.edu"
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


def test_known_record_ids_are_byte_stable():
    """Ids are the upsert key into processed/opportunities.json: if the
    derivation drifts (e.g. during the ucb_common consolidation), the next
    scrape duplicates all ~200 UCB records instead of updating them. Pin
    real corpus ids, including two recomputed by the mojibake fix."""
    for name, expected in [
        ("Pieter Abbeel", "faculty-ucb-eecs-8f9a715a"),
        ("Björn Hartmann", "faculty-ucb-eecs-ffde8ecc"),
        ("Boubacar Kanté", "faculty-ucb-eecs-830e5c93"),
    ]:
        person = {"name": name, "url": "https://example.test/p.html",
                  "title": "Professor"}
        assert normalize_faculty(person, EECS_CONFIG)["id"] == expected


def test_emeritus_and_retired_titles_are_skipped():
    sequin = next(p for p in _scrape() if p["name"] == "Carlo H. Séquin")
    assert sequin["title"] == "Professor Emeritus"
    assert normalize_faculty(sequin, EECS_CONFIG) is None
    for title in ("Professor Emerita", "Adjunct Professor, Retired",
                  "Professor Emeritus, Professor in the Graduate School",
                  "Professor in Residence Emeritus"):
        person = {"name": "Some Person", "url": "https://example.test/p.html",
                  "title": title, "email": "person@berkeley.edu"}
        assert normalize_faculty(person, EECS_CONFIG) is None
    active = {"name": "Some Person", "url": "https://example.test/p.html",
              "title": "Associate Professor", "email": "person@berkeley.edu"}
    assert normalize_faculty(active, EECS_CONFIG) is not None


def test_placeholder_directory_email_is_treated_as_no_email():
    attwood = next(p for p in _scrape() if p["name"] == "David Attwood")
    assert "email" not in attwood
    opp = normalize_faculty(attwood, EECS_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5


def test_external_campus_semantics():
    abbeel = next(p for p in _scrape() if p["name"] == "Pieter Abbeel")
    opp = normalize_faculty(abbeel, EECS_CONFIG)
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert "no work authorization required" not in opp["eligibility"]["work_auth_notes"]


def test_metadata_keys_are_canonical():
    abbeel = next(p for p in _scrape() if p["name"] == "Pieter Abbeel")
    opp = normalize_faculty(abbeel, EECS_CONFIG)
    assert set(opp["metadata"]) == {
        "confidence_score", "last_verified", "first_seen_at", "last_seen_at",
        "is_active", "manually_reviewed", "notes", "faculty_title",
        "research_areas_raw", "identity_bound", "email_source",
        "contact_verified_email", "contact_source_url", "contact_verified_at",
    }
    assert set(opp) == {
        "id", "source", "source_url", "source_type", "title", "organization",
        "department", "lab_or_program", "pi_name", "contact_email", "url",
        "location", "on_campus", "remote_option", "opportunity_type", "paid",
        "compensation_details", "deadline", "posted_date", "start_date",
        "duration", "eligibility", "application", "description_raw",
        "description_clean", "keywords", "metadata",
    }


# --- umbrella-tag keyword mapping ---

# The fixed umbrella research-area vocabulary observed across the live
# directory's 153 records (the /Research/Areas/ link texts). Every tag must
# yield real topical keywords: before the explicit mapping, substring-matching
# against KEYWORD_BANK recovered only 10 distinct keywords and ~30% of records
# fell back to the bare department keyword.
EECS_UMBRELLA_TAGS = [
    "Artificial Intelligence (AI)",
    "Biosystems & Computational Biology (BIO)",
    "Computer Architecture & Engineering (ARC)",
    "Control, Intelligent Systems, and Robotics (CIR)",
    "Cyber-Physical Systems and Design Automation (CPSDA)",
    "Database Management Systems (DBMS)",
    "Design, Modeling and Analysis (DMA)",
    "Education (EDUC)",
    "Graphics (GR)",
    "Human-Computer Interaction (HCI)",
    "Information, Data, Network, and Communication Sciences (IDNCS)",
    "Integrated Circuits (INC)",
    "Micro/Nano Electro Mechanical Systems (MEMS)",
    "Operating Systems & Networking (OSNT)",
    "Physical Electronics (PHY)",
    "Power and Energy (ENE)",
    "Programming Systems (PS)",
    "Scientific Computing (SCI)",
    "Security (SEC)",
    "Signal Processing (SP)",
    "Theory (THY)",
]


def _tagged_person(areas: str) -> dict:
    return {"name": "Test Person", "url": "https://example.test/p.html",
            "title": "Professor", "research_areas": areas}


def test_every_umbrella_tag_yields_real_keywords():
    fallback = EECS_CONFIG["keywords"][:1]
    for tag in EECS_UMBRELLA_TAGS:
        kws = normalize_faculty(_tagged_person(tag), EECS_CONFIG)["keywords"]
        assert kws and kws != fallback, f"{tag!r} fell back to {kws}"


def test_previously_unmapped_umbrella_tags_get_topical_keywords():
    # Theory + ARC produced zero bank hits before the mapping (fallback-only).
    opp = normalize_faculty(
        _tagged_person("Theory (THY); Computer Architecture & Engineering (ARC)"),
        EECS_CONFIG,
    )
    assert "algorithms" in opp["keywords"]
    assert "computer architecture" in opp["keywords"]
    assert EECS_CONFIG["keywords"][0] not in opp["keywords"]


def test_mapped_keywords_do_not_duplicate_bank_matches():
    # "Signal Processing (SP)" is both a mapping key and a verbatim bank hit.
    opp = normalize_faculty(_tagged_person("Signal Processing (SP)"), EECS_CONFIG)
    assert opp["keywords"].count("signal processing") == 1


def test_mapped_keywords_pass_dq_junk_gates():
    """Every mapped keyword lands in keywords[] (and the title parenthetical)
    of real records, so it must clear the corpus-wide junk/fragment gates in
    tests/test_opportunity_data_quality.py."""
    import re

    from src.collectors.uiuc_faculty import _is_junk_keyword

    lead = re.compile(
        r"^(?:such as|particularly|especially|including|namely|e\.g\.?)\b",
        re.IGNORECASE,
    )
    for tag, kws in EECS_AREA_KEYWORDS.items():
        assert kws, f"{tag!r} maps to no keywords"
        for k in kws:
            assert not _is_junk_keyword(k), f"{tag!r} -> junk keyword {k!r}"
            assert not lead.match(k), f"{tag!r} -> fragment lead-in {k!r}"


# The live server omits a charset header, so requests' resp.text falls back to
# ISO-8859-1 and mangles UTF-8 names ("Kanté" -> "KantÃ©"). fetch_soup must
# parse the response bytes instead.
UTF8_NO_CHARSET_HTML = """
<div class="cc-image-list__item__content">
  <h3><a href="/Faculty/Homepages/kante.html">Boubacar Kanté</a></h3>
  <p><strong>Professor</strong><br>kante@berkeley.edu
  <br><strong>Research Interests:</strong>
  <a href="/Research/Areas/PHO">Photonics</a></p>
</div>
""".encode()


def test_fetch_soup_is_mojibake_free_without_charset_header(monkeypatch):
    resp = requests.Response()
    resp.status_code = 200
    resp._content = UTF8_NO_CHARSET_HTML
    resp.headers["Content-Type"] = "text/html"
    resp.encoding = "ISO-8859-1"  # what requests infers when charset is absent
    monkeypatch.setattr(ucb_common.requests.Session, "get",
                        lambda self, *a, **k: resp)

    soup = fetch_soup("https://example.test/faculty.html")
    people = _scrape_eecs_faculty_list(soup, EECS_CONFIG["base"])
    assert people[0]["name"] == "Boubacar Kanté"
    opp = normalize_faculty(people[0], EECS_CONFIG)
    assert opp["pi_name"] == "Boubacar Kanté"
    assert "Ã" not in opp["title"]
