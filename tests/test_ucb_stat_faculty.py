"""Offline tests for src.collectors.ucb_stat_faculty.

No network: the parser runs against an HTML fixture mirroring the real
Open-Berkeley Drupal teaser markup (article.node--type-faculty > h3 a[/people/]
+ div.field--name-field-job-title). Locks in the selector-driven parser, the
lite-record behavior (no email, broad-field keyword), the Berkeley schema, and
id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors import ucb_common
from src.collectors.ucb_common import (
    dedup_by_profile_url,
    drop_joint_appointment_duplicates,
    extract_email_from_profile,
    normalize_faculty,
    scrape_open_berkeley_faculty,
)
from src.collectors.ucb_stat_faculty import STAT_CONFIG

# Two faculty teaser cards (one whose title mentions a banked keyword) plus a
# non-faculty article that must be ignored because it isn't node--type-faculty.
FIXTURE_HTML = """
<div class="view-content">
  <div class="views-row">
    <article class="node node--type-faculty node--view-mode-teaser">
      <div class="node__content">
        <h3 class="page--title"><a href="/people/ani-adhikari">Ani Adhikari</a></h3>
        <div class="field field--name-field-job-title field--label-hidden field__item">Teaching Professor</div>
      </div>
    </article>
  </div>
  <div class="views-row">
    <article class="node node--type-faculty node--promoted node--view-mode-teaser">
      <div class="node__content">
        <h3 class="page--title"><a href="/people/jennifer-chayes">Jennifer Chayes</a></h3>
        <div class="field field--name-field-job-title field--label-hidden field__item">Distinguished Professor and Dean, College of Computing, Data Science, and Society</div>
      </div>
    </article>
  </div>
  <div class="views-row">
    <article class="node node--type-news node--view-mode-teaser">
      <div class="node__content">
        <h3 class="page--title"><a href="/news/some-story">A news story, not a person</a></h3>
      </div>
    </article>
  </div>
</div>
"""


def _scrape():
    soup = BeautifulSoup(FIXTURE_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, STAT_CONFIG)


def test_parser_extracts_only_faculty_cards():
    people = _scrape()
    # The node--type-news article is ignored.
    assert len(people) == 2
    assert {p["name"] for p in people} == {"Ani Adhikari", "Jennifer Chayes"}


def test_parser_pulls_title_and_absolute_profile_url():
    ani = next(p for p in _scrape() if p["name"] == "Ani Adhikari")
    assert ani["title"] == "Teaching Professor"
    assert ani["url"] == "https://statistics.berkeley.edu/people/ani-adhikari"
    assert "email" not in ani  # lite: listing has no email


def test_normalize_produces_lite_berkeley_record():
    ani = next(p for p in _scrape() if p["name"] == "Ani Adhikari")
    opp = normalize_faculty(ani, STAT_CONFIG)
    assert opp["source"] == "ucb_stat_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["location"] == "Berkeley, CA"
    assert opp["id"].startswith("faculty-ucb-stat-")
    # lite: no email -> null contact + lower confidence + broad-field keyword.
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["statistics"]
    assert opp["eligibility"]["majors"] == STAT_CONFIG["majors"]
    # External campus: not on the product's UIUC campus, and work-auth /
    # international-friendliness can't be verified from the directory.
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ""


def test_keyword_picked_up_from_title_when_present():
    # Chayes' title contains "Data Science", a banked keyword.
    jc = next(p for p in _scrape() if p["name"] == "Jennifer Chayes")
    opp = normalize_faculty(jc, STAT_CONFIG)
    assert "data science" in opp["keywords"]


def test_id_is_deterministic():
    ani = next(p for p in _scrape() if p["name"] == "Ani Adhikari")
    a = normalize_faculty(ani, STAT_CONFIG)["id"]
    b = normalize_faculty(ani, STAT_CONFIG)["id"]
    assert a == b


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole
    STAT corpus on the next scrape. Pin a real corpus id."""
    ani = next(p for p in _scrape() if p["name"] == "Ani Adhikari")
    assert normalize_faculty(ani, STAT_CONFIG)["id"] == "faculty-ucb-stat-58582c90"


# --- profile-page email enrichment (offline) ---

PROFILE_HTML = """
<article class="node node--type-faculty">
  <h3 class="page--title">Ani Adhikari</h3>
  <div class="field field--name-field-email field--type-email field__item">
    Email adhikari@berkeley.edu
  </div>
</article>
"""

PROFILE_NO_EMAIL_HTML = """
<article class="node node--type-faculty">
  <h3 class="page--title">No Email Person</h3>
  <div class="field field--name-field-job-title">Professor</div>
</article>
"""


def test_extract_email_from_drupal_field():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, STAT_CONFIG) == "adhikari@berkeley.edu"


def test_extract_email_returns_none_when_absent():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, STAT_CONFIG) is None


def test_extract_email_prefers_mailto_and_skips_noise():
    html = """
    <div>
      <a href="mailto:webmaster@berkeley.edu">site</a>
      <a href="mailto:jane@stat.berkeley.edu">Jane</a>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    # webmaster@ is in the noise set, so the real address wins.
    assert extract_email_from_profile(soup, STAT_CONFIG) == "jane@stat.berkeley.edu"


def test_dedup_collapses_same_profile_url():
    people = [
        {"name": "Ani Adhikari", "url": "https://x/people/ani-adhikari"},
        {"name": "Ani Adhikari", "url": "https://x/people/ani-adhikari"},  # 2nd section
        {"name": "Peng Ding", "url": "https://x/people/peng-ding"},
    ]
    out = dedup_by_profile_url(people)
    assert len(out) == 2
    assert [p["name"] for p in out] == ["Ani Adhikari", "Peng Ding"]


# --- cross-UCB joint-appointment dedup (keep EECS, drop STAT) ---

def _eecs(name: str, email: str | None, suffix: str = "a") -> dict:
    return {
        "id": f"faculty-ucb-eecs-{suffix}",
        "source": "ucb_eecs_faculty",
        "pi_name": name,
        "contact_email": email,
    }


def _stat(name: str, email: str | None, suffix: str = "a") -> dict:
    return {
        "id": f"faculty-ucb-stat-{suffix}",
        "source": "ucb_stat_faculty",
        "pi_name": name,
        "contact_email": email,
    }


def test_joint_dedup_skips_stat_record_matching_eecs_by_email():
    existing = [_eecs("Michael I. Jordan", "jordan@cs.berkeley.edu")]
    # Different name spelling, same inbox: still the same professor.
    incoming = [_stat("Michael Jordan", "JORDAN@cs.berkeley.edu")]
    kept, dropped = drop_joint_appointment_duplicates(incoming, existing)
    assert kept == []
    assert dropped == 1


def test_joint_dedup_skips_stat_record_matching_eecs_by_name_only():
    existing = [_eecs("Bin Yu", "binyu@berkeley.edu")]
    # STAT scrape found no email (lite record) but the person matches by name.
    incoming = [_stat("bin yu ", None)]
    kept, dropped = drop_joint_appointment_duplicates(incoming, existing)
    assert kept == []
    assert dropped == 1


def test_joint_dedup_keeps_non_matching_stat_record():
    existing = [_eecs("Bin Yu", "binyu@berkeley.edu")]
    incoming = [_stat("Ani Adhikari", "adhikari@berkeley.edu")]
    kept, dropped = drop_joint_appointment_duplicates(incoming, existing)
    assert [o["pi_name"] for o in kept] == ["Ani Adhikari"]
    assert dropped == 0


def test_joint_dedup_ignores_same_source_records_on_rescrape():
    # A re-scrape of STAT must upsert its own previous records by id, never
    # skip them as "duplicates" of themselves.
    existing = [_stat("Ani Adhikari", "adhikari@berkeley.edu")]
    incoming = [_stat("Ani Adhikari", "adhikari@berkeley.edu")]
    kept, dropped = drop_joint_appointment_duplicates(incoming, existing)
    assert len(kept) == 1
    assert dropped == 0


def test_joint_dedup_null_email_does_not_match_null_email():
    existing = [_eecs("Someone Else", None)]
    incoming = [_stat("Ani Adhikari", None)]
    kept, dropped = drop_joint_appointment_duplicates(incoming, existing)
    assert len(kept) == 1
    assert dropped == 0


def test_merge_into_processed_applies_joint_dedup(tmp_path, monkeypatch):
    import json

    eecs = _eecs("Bin Yu", "binyu@berkeley.edu")
    processed = tmp_path / "opportunities.json"
    processed.write_text(json.dumps([eecs]), encoding="utf-8")
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", processed)

    dup = _stat("Bin Yu", "binyu@berkeley.edu", suffix="dup")
    fresh = _stat("Ani Adhikari", "adhikari@berkeley.edu", suffix="fresh")
    added, updated = ucb_common.merge_into_processed([dup, fresh])

    assert (added, updated) == (1, 0)
    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert {o["id"] for o in saved} == {eecs["id"], fresh["id"]}
