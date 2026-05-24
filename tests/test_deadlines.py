"""Tests for the deadline normalization pipeline.

Covers the four-stage pipeline plus the SRO `?Yes`/`?No` garbage-token case
that triggered the rewrite (see git history).
"""

from __future__ import annotations

from datetime import date

import pytest

from src.normalizers.deadlines import (
    DeadlineType,
    normalize_deadline,
    parse_to_date,
    reclassify_opportunity,
    to_legacy,
)

# Pin a stable reference year so "March 15" without a year stays deterministic
REF_YEAR = 2026


# ── Garbage / SRO leak ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "?Yes",      # 254 records in production from the SRO selector bug
    "?No",       # 8 records
    "?",
    "?Yes ",
    "  ?No",
    "",
    None,
    "   ",
    "-",
    "—",
    "n/a",
    "N/A",
])
def test_garbage_is_unparseable_or_unknown(raw):
    parsed = normalize_deadline(raw, reference_year=REF_YEAR)
    assert parsed.type in (DeadlineType.UNPARSEABLE, DeadlineType.UNKNOWN), (
        f"{raw!r} should not pretend to be a date, got {parsed.type}"
    )
    assert parsed.date_start is None


def test_yes_no_never_become_today():
    """The SRO bug: garbage must NEVER silently become date.today()."""
    for raw in ("?Yes", "?No", "yes", "no"):
        parsed = normalize_deadline(raw, reference_year=REF_YEAR)
        assert parsed.date_start is None, (
            f"{raw!r} resolved to a date — pipeline regressed: {parsed}"
        )


# ── Sentinels ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "Rolling",
    "rolling",
    "Rolling Admissions",
    "Rolling basis",
    "Rolling deadline",
    "Open until filled",
    "open until filled",
    "Continuous",
    "Continuously",
    "Ongoing",
    "No fixed deadline",
    "No deadline",
    "Applications accepted on a rolling basis",
])
def test_rolling_sentinels(raw):
    parsed = normalize_deadline(raw, reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.ROLLING
    assert parsed.date_start is None


@pytest.mark.parametrize("raw", [
    "TBD",
    "TBA",
    "T.B.D.",
    "T.B.A.",
    "Coming Soon",
    "To be announced",
    "To be determined",
    "To be posted",
    "Check back",
    "Check website",
    "Not yet available",
    "Pending",
])
def test_unknown_sentinels(raw):
    parsed = normalize_deadline(raw, reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.UNKNOWN


@pytest.mark.parametrize("raw", [
    "ASAP",
    "asap",
    "As soon as possible",
    "Immediately",
    "Urgent",
])
def test_asap_sentinels(raw):
    parsed = normalize_deadline(raw, reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.ASAP


# ── Seasonal ───────────────────────────────────────────────────────────────

def test_spring_season():
    parsed = normalize_deadline("Spring 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2026, 1, 31)
    assert parsed.date_end == date(2026, 5, 31)


def test_fall_season():
    parsed = normalize_deadline("Fall 2025", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2025, 8, 1)


def test_winter_wraps_year():
    parsed = normalize_deadline("Winter 2025", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2025, 12, 1)
    assert parsed.date_end == date(2026, 2, 28)


def test_summer_season():
    parsed = normalize_deadline("Summer 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2026, 5, 1)


def test_autumn_alias_for_fall():
    parsed = normalize_deadline("Autumn 2025", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2025, 8, 1)


# ── Academic-year range ────────────────────────────────────────────────────

def test_fall_to_spring_range():
    parsed = normalize_deadline("Fall 2025 - Spring 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.RANGE
    assert parsed.date_start == date(2025, 8, 1)
    assert parsed.date_end == date(2026, 5, 31)


def test_range_with_em_dash():
    parsed = normalize_deadline("Fall 2025 — Spring 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.RANGE


def test_range_with_to():
    parsed = normalize_deadline("Fall 2025 to Spring 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.RANGE


# ── Fuzzy month ────────────────────────────────────────────────────────────

def test_end_of_january():
    parsed = normalize_deadline("End of January 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2026, 1, 28)


def test_mid_february():
    parsed = normalize_deadline("Mid-February 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2026, 2, 15)


def test_early_march():
    parsed = normalize_deadline("Early March 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2026, 3, 7)


# ── Exact dates (the 16 legit MM/DD/YY records) ────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2/1/27",   date(2027, 2, 1)),    # the 7 records found in prod
    ("1/31/27",  date(2027, 1, 31)),   # the 3 records found in prod
    ("1/22/27",  date(2027, 1, 22)),
    ("2/3/27",   date(2027, 2, 3)),
    ("2/15/27",  date(2027, 2, 15)),
    ("2026-03-15", date(2026, 3, 15)),
    ("March 15, 2026", date(2026, 3, 15)),
    ("15 Mar 2026", date(2026, 3, 15)),
    ("3/15/2026", date(2026, 3, 15)),
    ("3/15/26",  date(2026, 3, 15)),
    ("Friday, March 15, 2026", date(2026, 3, 15)),
])
def test_exact_date_formats(raw, expected):
    parsed = normalize_deadline(raw, reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.EXACT
    assert parsed.date_start == expected


# ── Field-label stripping (legacy SRO output) ──────────────────────────────

def test_strips_deadline_label():
    parsed = normalize_deadline("Deadline: 3/15/2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.EXACT
    assert parsed.date_start == date(2026, 3, 15)


def test_strips_anticipated_prefix():
    parsed = normalize_deadline("Anticipated Deadline: Spring 2026", reference_year=REF_YEAR)
    assert parsed.type == DeadlineType.APPROXIMATE
    assert parsed.date_start == date(2026, 1, 31)


# ── to_legacy() round-trip ─────────────────────────────────────────────────

def test_legacy_exact_returns_iso():
    parsed = normalize_deadline("3/15/2026", reference_year=REF_YEAR)
    dl, rolling = to_legacy(parsed)
    assert dl == "2026-03-15"
    assert rolling is False


def test_legacy_rolling_returns_flag():
    parsed = normalize_deadline("Rolling", reference_year=REF_YEAR)
    dl, rolling = to_legacy(parsed)
    assert dl is None
    assert rolling is True


def test_legacy_unparseable_returns_none():
    parsed = normalize_deadline("?Yes", reference_year=REF_YEAR)
    dl, rolling = to_legacy(parsed)
    assert dl is None
    assert rolling is False


def test_legacy_range_uses_start():
    parsed = normalize_deadline("Fall 2025 - Spring 2026", reference_year=REF_YEAR)
    dl, rolling = to_legacy(parsed)
    assert dl == "2025-08-01"  # date_start
    assert rolling is False


# ── reclassify_opportunity() — backfill ────────────────────────────────────

def test_reclassify_yes_no_clears_deadline():
    """The SRO bug fix: garbage in `deadline` gets cleared, not preserved."""
    opp = {"id": "x", "deadline": "?Yes", "is_rolling": False}
    report = reclassify_opportunity(opp, reference_year=REF_YEAR)
    assert opp["deadline"] is None
    assert opp["is_rolling"] is False  # unchanged — it's not rolling, just garbage
    assert report["changed"] is True
    assert report["parsed_type"] == "unparseable"


def test_reclassify_rolling_string_sets_flag():
    """3 records had `deadline='Rolling'` instead of `is_rolling=True`."""
    opp = {"id": "x", "deadline": "Rolling", "is_rolling": False}
    report = reclassify_opportunity(opp, reference_year=REF_YEAR)
    assert opp["deadline"] is None
    assert opp["is_rolling"] is True
    assert report["changed"] is True
    assert report["parsed_type"] == "rolling"


def test_reclassify_mmddyy_to_iso():
    """16 records had MM/DD/YY format; backfill normalizes to ISO."""
    opp = {"id": "x", "deadline": "2/1/27", "is_rolling": False}
    report = reclassify_opportunity(opp, reference_year=REF_YEAR)
    assert opp["deadline"] == "2027-02-01"
    assert opp["is_rolling"] is False
    assert report["changed"] is True


def test_reclassify_already_iso_no_change():
    opp = {"id": "x", "deadline": "2026-03-15", "is_rolling": False}
    report = reclassify_opportunity(opp, reference_year=REF_YEAR)
    assert opp["deadline"] == "2026-03-15"
    assert report["changed"] is False


def test_reclassify_no_demote_rolling():
    """If an opp is already is_rolling=True with deadline=None, leave it alone."""
    opp = {"id": "x", "deadline": None, "is_rolling": True}
    report = reclassify_opportunity(opp, reference_year=REF_YEAR)
    assert opp["is_rolling"] is True
    assert opp["deadline"] is None
    assert report["changed"] is False


def test_reclassify_preserves_richer_iso_datetime():
    """Handshake-style ISO datetimes (with time + tz) parse to the same date
    as ``YYYY-MM-DD`` — keep the original richer string so backfills don't
    churn 71 already-correct records.
    """
    opp = {"id": "x", "deadline": "2026-04-17T23:59:59.999-05:00", "is_rolling": False}
    report = reclassify_opportunity(opp, reference_year=REF_YEAR)
    assert opp["deadline"] == "2026-04-17T23:59:59.999-05:00"
    assert report["changed"] is False


# ── parse_to_date() compatibility shim ─────────────────────────────────────

def test_parse_to_date_returns_date_for_exact():
    assert parse_to_date("3/15/2026") == date(2026, 3, 15)


def test_parse_to_date_returns_none_for_rolling():
    assert parse_to_date("Rolling") is None


def test_parse_to_date_returns_none_for_garbage():
    assert parse_to_date("?Yes") is None


def test_parse_to_date_returns_none_for_missing():
    assert parse_to_date(None) is None
    assert parse_to_date("") is None


# ── ParsedDeadline is hashable / equality works ────────────────────────────

def test_parsed_deadline_equality():
    a = normalize_deadline("Rolling")
    b = normalize_deadline("Rolling")
    assert a.type == b.type
