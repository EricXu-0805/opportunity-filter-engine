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

from src.normalizers.school_audience import (
    SOURCE_DEFAULTS,
    VALID_AUDIENCES,
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
