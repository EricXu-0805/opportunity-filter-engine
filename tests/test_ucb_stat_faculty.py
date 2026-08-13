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
from datetime import UTC, datetime

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.lib.contact_visibility import verified_send_target
from src.collectors import ucb_common
from src.collectors.ucb_common import (
    dedup_by_profile_url,
    drop_joint_appointment_duplicates,
    extract_email_from_profile,
    extract_research_interests,
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
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == STAT_CONFIG["work_auth_notes"]


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


# --- profile-page research-interest enrichment (offline) ---

# Real per-professor profile structure (statistics.berkeley.edu/people/<slug>):
# the page the email hop already fetches also carries a free-text
# field--name-field-research-interests block and a linked
# field--name-field-research-areas-ref taxonomy — both ignored before, leaving
# 46/47 STAT records with the bare ['statistics'] keyword.
PROFILE_WITH_INTERESTS_HTML = """
<article class="node node--type-faculty">
  <h3 class="page--title">Peng Ding</h3>
  <div class="field field--name-field-job-title field__item">Professor</div>
  <div class="field field--name-field-email field--type-email field--label-above">
    <div class="field__label">Email</div>
    <div class="field__item">pengdingpku@berkeley.edu</div>
  </div>
  <div class="field field--name-field-research-interests field--type-text-with-summary field--label-above">
    <div class="field__label">Research Expertise and Interests</div>
    <div class="field__item"><p>causal inference, econometrics, experimental design,
    missing data, applications in biomedical and social sciences</p></div>
  </div>
  <div class="field field--name-field-research-areas-ref field--type-entity-reference field--label-above">
    <div class="field__label">Research Areas</div>
    <div class="field__items">
      <div class="field__item"><a href="/research/causal-inference-graphical-models">Causal Inference</a></div>
      <div class="field__item"><a href="/research/nonparametric-inference">Nonparametric Inference</a></div>
    </div>
  </div>
</article>
"""

PENG_PROFILE_URL = "https://statistics.berkeley.edu/people/peng-ding"


def test_extract_research_interests_reads_both_profile_fields():
    soup = BeautifulSoup(PROFILE_WITH_INTERESTS_HTML, "html.parser")
    text = extract_research_interests(soup, STAT_CONFIG)
    assert "causal inference" in text           # free-text interests field
    assert "Nonparametric Inference" in text    # linked taxonomy field
    # Drupal field labels are page furniture, not research signal.
    assert "Research Expertise and Interests" not in text
    assert "Research Areas" not in text


def test_extract_research_interests_empty_when_profile_has_none():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_research_interests(soup, STAT_CONFIG) == ""


def test_enrichment_attaches_email_and_research_interests(monkeypatch):
    profile_soup = BeautifulSoup(PROFILE_WITH_INTERESTS_HTML, "html.parser")
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: profile_soup)
    person = {"name": "Peng Ding", "title": "Professor",
              "url": "https://statistics.berkeley.edu/people/peng-ding"}
    ucb_common.enrich_faculty_from_profiles([person], STAT_CONFIG)
    assert person["email"] == "pengdingpku@berkeley.edu"

    opp = normalize_faculty(person, STAT_CONFIG)
    # Real topical keywords from the profile, not the bare department fallback.
    assert "causal inference" in opp["keywords"]
    assert opp["keywords"] != ["statistics"]
    assert opp["contact_email"] == "pengdingpku@berkeley.edu"
    assert "_contact_claim" not in person
    # W7a reconciliation (W12 merge): with the binding claim cleared and no
    # binding fields present, the profile-observed address rides the
    # legacy rule — same strength as every pre-stamping profile_page row.
    assert verified_send_target(opp) == opp["contact_email"]
    assert opp["metadata"]["email_source"] == "profile_page"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert "causal inference" in opp["metadata"]["research_areas_raw"]


def test_reviewed_statistics_profile_mints_atomic_send_evidence(monkeypatch):
    observed_at = datetime.now(UTC).replace(microsecond=0)
    profile_soup = ucb_common._mark_fetched_soup_observation(
        BeautifulSoup(PROFILE_WITH_INTERESTS_HTML, "html.parser"),
        requested_url=PENG_PROFILE_URL,
        final_url=f"{PENG_PROFILE_URL}/",
        observed_at=observed_at,
    )
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: profile_soup)
    person = {
        "name": "Peng Ding",
        "title": "Professor",
        "url": PENG_PROFILE_URL,
    }

    ucb_common.enrich_faculty_from_profiles([person], STAT_CONFIG)
    opp = normalize_faculty(person, STAT_CONFIG)

    assert opp is not None
    assert verified_send_target(opp) == "pengdingpku@berkeley.edu"
    assert opp["metadata"]["email_source"] == "bound_profile_container"
    assert opp["metadata"]["contact_source_url"] == f"{PENG_PROFILE_URL}/"
    assert (
        opp["metadata"]["contact_verified_at"]
        == observed_at.isoformat()
    )
    assert opp["metadata"]["contact_verified_email"] == (
        "pengdingpku@berkeley.edu"
    )


def test_statistics_profile_rerun_clears_unrevalidated_old_proof(monkeypatch):
    observed_at = datetime.now(UTC).replace(microsecond=0)
    marked = ucb_common._mark_fetched_soup_observation(
        BeautifulSoup(PROFILE_WITH_INTERESTS_HTML, "html.parser"),
        requested_url=PENG_PROFILE_URL,
        final_url=PENG_PROFILE_URL,
        observed_at=observed_at,
    )
    person = {
        "name": "Peng Ding",
        "title": "Professor",
        "url": PENG_PROFILE_URL,
    }
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: marked)
    ucb_common.enrich_faculty_from_profiles([person], STAT_CONFIG)
    assert "_contact_claim" in person

    unmarked = BeautifulSoup(PROFILE_WITH_INTERESTS_HTML, "html.parser")
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: unmarked)
    ucb_common.enrich_faculty_from_profiles([person], STAT_CONFIG)
    opp = normalize_faculty(person, STAT_CONFIG)

    assert "_contact_claim" not in person
    assert opp is not None
    assert opp["contact_email"] == "pengdingpku@berkeley.edu"
    assert opp["metadata"]["email_source"] == "profile_page"
    # W7a reconciliation (W12 merge): with the binding claim cleared and no
    # binding fields present, the profile-observed address rides the
    # legacy rule — same strength as every pre-stamping profile_page row.
    assert verified_send_target(opp) == opp["contact_email"]


def test_statistics_profile_rerun_clears_old_proof_on_failed_observation(
    monkeypatch,
):
    observed_at = datetime.now(UTC).replace(microsecond=0)

    def marked(html):
        return ucb_common._mark_fetched_soup_observation(
            BeautifulSoup(html, "html.parser"),
            requested_url=PENG_PROFILE_URL,
            final_url=PENG_PROFILE_URL,
            observed_at=observed_at,
        )

    first = marked(PROFILE_WITH_INTERESTS_HTML)
    second_observations = [
        marked(
            """
            <article class="node node--type-faculty">
              <h3 class="page--title">Peng Ding</h3>
            </article>
            """
        ),
        marked(
            """
            <article class="node node--type-faculty">
              <h3 class="page--title">Grace Hopper</h3>
              <div class="field field--name-field-email">
                grace@berkeley.edu
              </div>
            </article>
            """
        ),
        marked(
            """
            <html><title>Access denied</title>
              <body>Verify you are human</body>
            </html>
            """
        ),
        None,
    ]

    for second in second_observations:
        person = {
            "name": "Peng Ding",
            "title": "Professor",
            "url": PENG_PROFILE_URL,
        }
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: first)
        ucb_common.enrich_faculty_from_profiles([person], STAT_CONFIG)
        assert "_contact_claim" in person

        monkeypatch.setattr(
            ucb_common,
            "fetch_soup",
            lambda url, observation=second: observation,
        )
        ucb_common.enrich_faculty_from_profiles([person], STAT_CONFIG)
        opp = normalize_faculty(person, STAT_CONFIG)

        assert "_contact_claim" not in person
        assert opp is not None
        # W7a reconciliation (W12 merge): with the binding claim cleared and no
        # binding fields present, the profile-observed address rides the
        # legacy rule — same strength as every pre-stamping profile_page row.
        assert verified_send_target(opp) == opp["contact_email"]


def test_enrichment_without_research_section_stays_lite(monkeypatch):
    profile_soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: profile_soup)
    person = {"name": "No Email Person", "title": "Professor",
              "url": "https://statistics.berkeley.edu/people/no-email-person"}
    ucb_common.enrich_faculty_from_profiles([person], STAT_CONFIG)
    assert "email" not in person
    assert "research_areas" not in person

    opp = normalize_faculty(person, STAT_CONFIG)
    assert opp["keywords"] == ["statistics"]
    assert opp["metadata"]["confidence_score"] == 0.5


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
