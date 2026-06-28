"""Tests for the school-agnostic faculty_graph engine + the Michigan config.

Curated-seed path only for the data assertions (no network). The best-effort
scrape layer is exercised with injected sample HTML so the reusable parser is
covered without hitting a (Cloudflare-walled) live directory.

Locks in the invariants the data-quality gate depends on — every record is
``faculty_research`` with a person pi_name, clean keywords, a title whose
parenthetical is a subset of its keywords, and no two records in the school
sharing a non-null contact_email — so a config edit can't silently break them.
"""

from __future__ import annotations

import re

import pytest

from src.collectors import faculty_graph as fg
from src.collectors.schools.umich_faculty import SCHOOL
from src.collectors.ucb_common import _is_person_name
from src.collectors.uiuc_faculty import _is_junk_keyword
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES
from src.normalizers.school_audience import SOURCE_DEFAULTS

# --- Validator --------------------------------------------------------------

class TestValidator:
    def test_michigan_config_is_valid(self):
        assert fg.validate(SCHOOL) == []

    def test_missing_required_field_flagged(self):
        bad = {k: v for k, v in SCHOOL.items() if k != "source"}
        assert any("source" in e for e in fg.validate(bad))

    def test_department_without_faculty_or_scrape_flagged(self):
        bad = {**SCHOOL, "departments": [{"short": "X", "name": "X Dept"}]}
        assert any("no curated faculty" in e for e in fg.validate(bad))

    def test_fetch_rejects_invalid_config(self):
        with pytest.raises(ValueError):
            fg.fetch_and_normalize({"school_slug": "x", "departments": []})


# --- Registration contract --------------------------------------------------

class TestRegistration:
    def test_source_in_source_defaults(self):
        assert SOURCE_DEFAULTS[SCHOOL["source"]] == ("umich", "unknown")

    def test_source_in_faculty_sources(self):
        # Else stale professors are never retired by deactivate_stale_faculty.
        assert SCHOOL["source"] in FACULTY_SOURCES


# --- Seed normalization -----------------------------------------------------

@pytest.fixture(scope="module")
def recs():
    return fg.fetch_and_normalize(SCHOOL, deep=False)


class TestSeedNormalization:
    def test_produces_records(self, recs):
        assert len(recs) >= 40

    def test_all_faculty_research(self, recs):
        for o in recs:
            assert o["source_type"] == "faculty_research"
            assert o["source"] == "umich_faculty"
            assert o["school"] == "umich"
            assert o["audience"] == "unknown"

    def test_ids_unique_and_namespaced(self, recs):
        ids = [o["id"] for o in recs]
        assert len(ids) == len(set(ids))
        assert all(o["id"].startswith("faculty-umich-") for o in recs)

    def test_pi_names_are_people(self, recs):
        for o in recs:
            assert _is_person_name(o["pi_name"]), o["pi_name"]

    def test_required_schema_fields(self, recs):
        for o in recs:
            assert isinstance(o["eligibility"], dict)
            assert isinstance(o["metadata"], dict)
            assert isinstance(o["keywords"], list)
            assert len(o["description_clean"]) <= 1500
            assert o["deadline"] is None

    def test_title_parenthetical_is_subset_of_keywords(self, recs):
        for o in recs:
            m = re.search(r" — .+? \((.+)\)$", o["title"])
            if not m:
                continue
            shown = {a.strip().lower() for a in m.group(1).split(",")}
            kws = {(k or "").strip().lower() for k in o["keywords"]}
            assert not (shown - kws), f"{o['id']}: {shown - kws}"

    def test_keywords_have_no_junk(self, recs):
        for o in recs:
            for k in o["keywords"]:
                assert not _is_junk_keyword(k), f"{o['id']}: {k!r}"

    def test_no_shared_non_null_email(self, recs):
        """The school-scoped equivalent of the ucb joint-appointment gate: two
        umich_faculty records must not share a non-null contact_email."""
        from collections import defaultdict
        by_email = defaultdict(list)
        for o in recs:
            e = (o.get("contact_email") or "").strip().lower()
            if e:
                by_email[e].append(o["pi_name"])
        dups = {e: v for e, v in by_email.items() if len(v) > 1}
        assert not dups, f"shared emails: {dups}"

    def test_distinct_same_name_professors_both_kept(self, recs):
        """Michigan has two different professors named 'Wei Lu' (ECE memristors,
        ME batteries). A name-based de-dup would drop one; keep both."""
        wei_lu = [o for o in recs if o["pi_name"] == "Wei Lu"]
        assert len(wei_lu) == 2
        assert {o["contact_email"] for o in wei_lu} == {"wluee@umich.edu", "weilu@umich.edu"}

    def test_email_optional(self, recs):
        # Some have confirmed emails, some intentionally None (not guessed).
        assert any(o["contact_email"] for o in recs)
        assert any(o["contact_email"] is None for o in recs)


# --- Best-effort scrape layer (injected HTML, no network) -------------------

SAMPLE_HTML = """
<html><body>
  <div class="card"><h3><a href="/people/jane-doe/">Jane Q. Researcher</a></h3>
    <span class="rank">Assistant Professor</span></div>
  <div class="card"><h3><a href="/people/john-roe/">John Roe</a></h3>
    <span class="rank">Professor</span></div>
  <div class="card"><h3><a href="/about/">Department of Widgets</a></h3>
    <span class="rank">Office</span></div>
</body></html>
"""


class TestScrapeLayer:
    def test_scrape_disabled_without_config(self):
        assert fg._scrape_directory({"short": "X"}) == []

    def test_scrape_parses_cards_and_skips_nonpersons(self, monkeypatch):
        from bs4 import BeautifulSoup
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url: BeautifulSoup(SAMPLE_HTML, "html.parser"),
        )
        dept = {
            "short": "WID",
            "scrape": {
                "url": "https://example.edu/widgets/faculty",
                "selectors": {"card": "div.card", "name": "h3 a", "link": "h3 a", "title": "span.rank"},
            },
        }
        people = fg._scrape_directory(dept)
        names = {p["name"] for p in people}
        assert "Jane Q. Researcher" in names and "John Roe" in names
        # "Department of Widgets" is an institution label, not a person.
        assert "Department of Widgets" not in names

    def test_scrape_failure_degrades_to_empty(self, monkeypatch):
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup", lambda url: None)
        dept = {"short": "WID", "scrape": {"url": "https://example.edu/x", "selectors": {"card": "div"}}}
        assert fg._scrape_directory(dept) == []

    def test_scrape_captures_research_email_and_absolutizes_href(self, monkeypatch):
        """Rich cards (e.g. UW ECE) expose interests + a mailto inline, and link
        with a relative href — deep mode must land keyworded, emailed faculty
        with an absolute profile URL in one pass."""
        from bs4 import BeautifulSoup
        html = """
        <div class="entry">
          <span class="nm"><a href="/people/ada/">Ada Q. Lovelace</a></span>
          <span class="ti">Associate Professor</span>
          <span class="ri">Machine learning, computer vision, and Robotics</span>
          <span class="em"><a href="mailto:ada@uw.edu?subject=hi">ada@uw.edu</a></span>
        </div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "ECE", "scrape": {
            "url": "https://www.ece.uw.edu/faculty/",
            "selectors": {"card": "div.entry", "name": ".nm a", "link": ".nm a",
                          "title": ".ti", "research": ".ri", "email": ".em a"},
        }}
        people = fg._scrape_directory(dept)
        assert len(people) == 1
        p = people[0]
        assert p["url"] == "https://www.ece.uw.edu/people/ada/"  # relative -> absolute
        assert p["email"] == "ada@uw.edu"  # mailto: + ?subject stripped
        assert "Machine learning" in p["research_areas"]

    def test_clean_keywords_strips_oxford_comma_connective(self):
        """An Oxford-comma tail ("..., and Robotics") splits into a clause led by
        'and' — the connective must be stripped so the keyword clears the DQ junk
        filter (regression: UW ECE 'and Wireless power transfer')."""
        person = {"research_areas": "Machine learning, computer vision, and Robotics"}
        kws = fg._clean_keywords(person)
        assert "Robotics" in kws
        assert not any(k.lower().startswith("and ") for k in kws)
        for k in kws:
            assert not _is_junk_keyword(k), k


# --- University of Washington config (live-scraped, no network in tests) ----

class TestUWConfig:
    def test_uw_config_valid(self):
        from src.collectors.schools.uw_faculty import SCHOOL as UW
        assert fg.validate(UW) == []

    def test_uw_registered_in_source_defaults_and_faculty_sources(self):
        from src.collectors.schools.uw_faculty import SCHOOL as UW
        assert SOURCE_DEFAULTS[UW["source"]] == ("uw", "unknown")
        assert UW["source"] in FACULTY_SOURCES

    def test_uw_every_department_has_a_scrape_block(self):
        from src.collectors.schools.uw_faculty import SCHOOL as UW
        for dept in UW["departments"]:
            assert dept.get("scrape", {}).get("selectors", {}).get("card"), dept["short"]
