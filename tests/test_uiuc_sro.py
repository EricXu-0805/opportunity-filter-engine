"""Offline tests for src.collectors.uiuc_sro helpers.

Focus: _clean_compensation reduces the deep-scraped paid_info blob (±40-char
windows around paid keywords joined with ' | ', which leaks adjacent
Duration/Citizenship metadata) to a clean value. Mirrors the frontend
cleanCompensation so source data and display agree.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.uiuc_sro import _clean_compensation


def test_extracts_dollar_amount_from_leaked_blob():
    raw = "Science & Technology Duration 10 weeks Compensation $6,500 Citizenship Requirement No"
    assert _clean_compensation(raw) == "$6,500"


def test_extracts_qualitative_label():
    raw = "& Behavior Duration Varies Compensation Paid Program Citizenship Requirement No Citi"
    assert _clean_compensation(raw) == "Paid Program"


def test_bare_paid_mention_when_no_value():
    # Dirty blob (the ' | ' marks the leaked-window concatenation) with no
    # dollar amount and no "Compensation <label>" token → bare "paid" fallback.
    raw = "interns are paid | Behavioral Sciences Duration 12 weeks Compensation Varies by Position"
    assert _clean_compensation(raw) == "Paid"


def test_clean_value_passes_through_untouched():
    assert _clean_compensation("$5,000 stipend") == "$5,000 stipend"
    assert _clean_compensation("Paid") == "Paid"


def test_empty_and_unparseable():
    assert _clean_compensation("") == ""
    assert _clean_compensation(None) == ""
    # A long blob with no dollar/qualitative/keyword signal yields '' (caller
    # falls back to the paid badge) rather than dumping the leaked metadata.
    assert _clean_compensation("x" * 200) == ""
