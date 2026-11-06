"""Unit tests for src.normalizers.school_audience.apply_school_audience.

The data-quality gate (TestSchoolAudience in test_opportunity_data_quality.py)
only fires if a malformed record has already landed in the corpus — it's a
backstop, not the first line of defense. This file exercises the boundary
coercion directly: mapped sources re-stamp idempotently from SOURCE_DEFAULTS,
and unmapped/manual sources have their free-form school/audience normalized so
a hand-imported record can never carry a value the gate would reject. 33 manual
records exist and manual_importer accepts free-form kwargs, so this coercion is
the sole guard before the gate.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from backend import data_loader
from src.collectors import campus_graph as cg
from src.collectors.schools import SCHOOL_CONFIGS
from src.matcher.ranker import _filter_context, hard_exclusion
from src.normalizers.school_audience import (
    REVIEWED_PROGRAM_AUDIENCES,
    SOURCE_DEFAULTS,
    VALID_AUDIENCES,
    apply_program_audience,
    apply_school_audience,
)


def test_mapped_source_is_restamped_from_defaults_ignoring_record_values():
    # A mapped source's per-record school/audience are overwritten by
    # SOURCE_DEFAULTS — the pass is idempotent and self-healing even if a
    # record arrives with garbage.
    expected_school, expected_audience = SOURCE_DEFAULTS["ucb_eecs_faculty"]
    opp = {"source": "ucb_eecs_faculty", "school": "WRONG", "audience": "everyone"}
    apply_school_audience([opp])
    assert opp["school"] == expected_school
    assert opp["audience"] == expected_audience


def test_faculty_sources_are_uniformly_unknown_audience():
    # Symmetry pin: every faculty directory (uiuc_faculty included — it was
    # 'campus' pre-toggle, hiding 3k+ UIUC professors from every other
    # school's students) is a cold-email target with professor-specific
    # openness. Visibility is the cross-school toggle's job, not a per-school
    # audience tag.
    offenders = {
        source: pair for source, pair in SOURCE_DEFAULTS.items()
        if source.endswith("_faculty") and pair[1] != "unknown"
    }
    assert not offenders


def test_unmapped_invalid_audience_coerced_to_unknown():
    opp = {"source": "manual", "school": "uiuc", "audience": "everyone"}
    apply_school_audience([opp])
    assert opp["audience"] == "unknown"
    assert opp["audience"] in VALID_AUDIENCES


def test_unmapped_valid_audience_is_preserved():
    opp = {"source": "manual", "school": "uiuc", "audience": "open"}
    apply_school_audience([opp])
    assert opp["audience"] == "open"


def test_unmapped_blank_or_whitespace_school_becomes_none():
    for raw in ("", "   "):
        opp = {"source": "manual", "school": raw, "audience": "open"}
        apply_school_audience([opp])
        assert opp["school"] is None


def test_unmapped_school_is_trimmed_and_lowercased():
    opp = {"source": "manual", "school": "  Stanford  ", "audience": "open"}
    apply_school_audience([opp])
    assert opp["school"] == "stanford"


def test_unmapped_missing_school_is_none_and_missing_audience_is_unknown():
    opp = {"source": "manual"}
    apply_school_audience([opp])
    assert opp["school"] is None
    assert opp["audience"] == "unknown"


def test_missing_source_defaults_to_unknown_bucket_and_coerces():
    # No source key at all → treated as the 'unknown' source (not in
    # SOURCE_DEFAULTS), so it takes the coercion branch.
    opp = {"audience": "bogus", "school": "  UCLA "}
    counts = apply_school_audience([opp])
    assert opp["school"] == "ucla"
    assert opp["audience"] == "unknown"
    assert counts.get("unknown") == 1


def test_returns_per_source_counts():
    opps = [
        {"source": "ucb_eecs_faculty"},
        {"source": "ucb_eecs_faculty"},
        {"source": "manual", "audience": "open", "school": "uiuc"},
    ]
    counts = apply_school_audience(opps)
    assert counts["ucb_eecs_faculty"] == 2
    assert counts["manual"] == 1


class TestExplicitCampusOnlyDetection:
    """A UCSB-only summer internship (audience='unknown') ranked #1 for a
    Northwestern student — the 'summer programs recruit nationally' rule
    assumed openness. Only an EXPLICIT own-campus restriction flips the tag."""

    def _opp(self, school, source, desc):
        return {"source": source, "school": school, "audience": "unknown",
                "description_raw": desc, "eligibility": {}}

    def test_rise_phrasing_becomes_campus(self):
        from src.normalizers.school_audience import apply_school_audience
        opp = self._opp("ucsb", "not-in-defaults",
                        "RISE research internships for UCSB undergraduates. Science "
                        "and engineering students from UCSB acquire research experience.")
        apply_school_audience([opp])
        assert opp["audience"] == "campus"

    def test_must_be_enrolled_becomes_campus(self):
        from src.normalizers.school_audience import apply_school_audience
        opp = self._opp("purdue", "not-in-defaults",
                        "Applicants must be enrolled at Purdue at time of application.")
        apply_school_audience([opp])
        assert opp["audience"] == "campus"

    def test_other_school_mention_stays_unknown(self):
        from src.normalizers.school_audience import apply_school_audience
        # a UIUC record mentioning another school's students never self-restricts
        opp = self._opp("northwestern", "not-in-defaults",
                        "This program welcomes participants; for UCSB undergraduates "
                        "a parallel session exists.")
        apply_school_audience([opp])
        assert opp["audience"] == "unknown"

    def test_plain_description_stays_unknown(self):
        from src.normalizers.school_audience import apply_school_audience
        opp = self._opp("ucsb", "not-in-defaults",
                        "Summer materials research internship with faculty mentorship.")
        apply_school_audience([opp])
        assert opp["audience"] == "unknown"

    def test_source_default_campus_not_downgraded(self):
        from src.normalizers.school_audience import apply_school_audience
        opp = self._opp("uiuc", "uiuc_our_rss", "Open position in a lab.")
        apply_school_audience([opp])
        assert opp["audience"] == "campus"


# --- Programs whose own page says who may apply ------------------------------

def _configured_row(school_slug: str, key: str) -> dict:
    school = next(s for s in SCHOOL_CONFIGS if s["school_slug"] == school_slug)
    for source in school["sources"]:
        for spec in source.get("programs", []):
            if spec["key"] == key:
                return cg._normalize_program(school, source, spec)
    raise LookupError((school_slug, key))


_UIUC_STUDENT = {"home_school": "uiuc"}


@pytest.mark.parametrize(("school", "key"), sorted(REVIEWED_PROGRAM_AUDIENCES))
def test_every_reviewed_audience_is_for_the_page_its_program_is_configured_at(school, key):
    row = _configured_row(school, key)
    reviewed = REVIEWED_PROGRAM_AUDIENCES[(school, key)]

    assert (row["source"], row["url"]) == (reviewed.source, reviewed.url)


@pytest.mark.parametrize(("school", "key"), [("northwestern", "nu_tgs_srop"), ("unl", "unl_summer_research_program")])
def test_a_visiting_student_program_reaches_students_of_other_schools(school, key):
    row = _configured_row(school, key)
    assert row["audience"] == "campus"

    apply_school_audience([row])

    assert (row["school"], row["audience"]) == (school, "open")
    assert hard_exclusion(row, _filter_context(_UIUC_STUDENT)) is None
    assert hard_exclusion(row, _filter_context({"home_school": school})) is None


def test_a_stored_row_gets_its_reviewed_audience_when_the_corpus_loads():
    stored = _configured_row("northwestern", "nu_tgs_srop")
    assert hard_exclusion(stored, _filter_context(_UIUC_STUDENT)) == "other_school_campus"

    loaded = data_loader._sanitize_opportunity(stored)

    assert loaded["audience"] == "open"
    assert hard_exclusion(loaded, _filter_context(_UIUC_STUDENT)) is None


def test_the_rest_of_the_schools_campus_bucket_stays_campus():
    row = _configured_row("unl", "unl_ucare")

    apply_school_audience([row])

    assert row["audience"] == "campus"


@pytest.mark.parametrize("change", ["moved", "display_link_moved", "discovered", "other_source"])
def test_only_the_reviewed_program_at_its_reviewed_page_gets_the_audience(change):
    row = _configured_row("unl", "unl_summer_research_program")
    if change == "moved":
        row["url"] = row["source_url"] = "https://summerprogram.unl.edu/2027/"
    elif change == "display_link_moved":
        row["url"] = "https://summerprogram.unl.edu/2027/"
    elif change == "discovered":
        row["metadata"]["discovered"] = True
    else:
        row["source"] = "unl_external_research"

    data_loader._sanitize_opportunity(row)

    assert row["audience"] == "campus"


def test_stanford_bio_x_summer_research_is_for_stanford_students_only():
    row = _configured_row("stanford", "biox_usrp")
    assert (row["audience"], row["opportunity_type"]) == ("unknown", "summer_program")
    assert hard_exclusion(row, _filter_context(_UIUC_STUDENT)) is None

    loaded = data_loader._sanitize_opportunity(row)

    assert loaded["audience"] == "campus"
    assert hard_exclusion(loaded, _filter_context(_UIUC_STUDENT)) == "other_school_campus"
    assert hard_exclusion(loaded, _filter_context({"home_school": "stanford"})) is None


def test_no_other_configured_program_changes_audience():
    changed = []
    for school in SCHOOL_CONFIGS:
        for source in school["sources"]:
            for spec in source.get("programs", []):
                if (school["school_slug"], spec["key"]) in REVIEWED_PROGRAM_AUDIENCES:
                    continue
                row = cg._normalize_program(school, source, spec)
                before = row["audience"]
                apply_program_audience(row)
                if row["audience"] != before:
                    changed.append(row["id"])

    assert changed == []
