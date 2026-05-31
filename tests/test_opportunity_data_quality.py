"""R70-A data quality invariants for data/processed/opportunities.json.

These tests lock in the contract established by the R70-A migration so the
data file (and any new collector output merged into it) cannot regress on
the issues we just fixed:

  * Every record exposes description_clean (no more schema-A program_overview
    records with only `description` that the frontend can't read).
  * No record has both `deadline=None` AND `is_rolling != True` for the
    aggregator sources (uiuc_sro / uiuc_our_rss / manual) — those listings
    should always be marked rolling so the UI shows "Rolling" instead of
    a blank timing block.
  * description_clean never exceeds the documented 1500-char cap.
  * IDs remain unique.
  * Past-deadline records are deactivated (with a small leak allowance for
    the historical 1 record we know about; tighter than that would require
    a separate cleanup pass).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "processed" / "opportunities.json"
DESCRIPTION_CAP = 1500
ROLLING_DEFAULT_SOURCES = {"uiuc_sro", "uiuc_our_rss", "manual"}
PAST_DEADLINE_LEAK_TOLERANCE = 0  # R70-C: zero tolerance now that deactivate_past runs in refresh_all

# R70-B: corruption patterns that pi_enricher used to emit when
# soup.get_text() concatenated adjacent HTML elements without a separator.
_PHONE_IN_LOCAL = re.compile(r"^[^@]*\d{3,4}-\d{3,4}")
_CAPS_MASHED_LOCAL = re.compile(r"^[A-Z][a-z]+[^A-Z_@]{12,}@")


def _load_data() -> list[dict]:
    if not DATA_FILE.exists():
        pytest.skip(f"{DATA_FILE} not present")
    with DATA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def _parse_iso(d):
    if not d or not isinstance(d, str):
        return None
    try:
        if "T" in d:
            return datetime.fromisoformat(d.replace("Z", "+00:00")).date()
        return datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


class TestR70ADataQuality:
    def test_every_record_has_description_clean(self):
        """R70-A backfilled 25 program_overview records that previously
        only had a `description` field. The frontend reads
        `description_clean || description_raw` so every record needs at
        least one of those, and ideally description_clean."""
        data = _load_data()
        missing = [
            o
            for o in data
            if "description_clean" not in o
        ]
        assert not missing, (
            f"{len(missing)} records missing description_clean key "
            f"(first 3 ids: {[o.get('id') for o in missing[:3]]})"
        )

    def test_aggregator_sources_have_deadline_or_rolling(self):
        """R70-A defaulted is_rolling=True for 308 records across
        uiuc_sro/uiuc_our_rss/manual that had no deadline. New records
        from those sources must keep that invariant."""
        data = _load_data()
        offenders = [
            o
            for o in data
            if o.get("source") in ROLLING_DEFAULT_SOURCES
            and not o.get("deadline")
            and o.get("is_rolling") is not True
        ]
        assert not offenders, (
            f"{len(offenders)} records from aggregator sources have "
            f"neither deadline nor is_rolling=True. First 3: "
            f"{[(o.get('source'), o.get('id')) for o in offenders[:3]]}"
        )

    def test_description_clean_within_cap(self):
        """R70-A raised the cap from 500 → 1500; nothing should exceed it."""
        data = _load_data()
        over_cap = [
            o
            for o in data
            if len(o.get("description_clean") or "") > DESCRIPTION_CAP
        ]
        assert not over_cap, (
            f"{len(over_cap)} records exceed the {DESCRIPTION_CAP}-char "
            f"description_clean cap (first 3 ids: "
            f"{[o.get('id') for o in over_cap[:3]]})"
        )

    def test_ids_unique(self):
        """Every record has a unique id."""
        data = _load_data()
        ids = [o.get("id") for o in data if o.get("id")]
        assert len(ids) == len(set(ids)), (
            f"Duplicate ids found: {len(ids) - len(set(ids))} duplicates"
        )

    def test_no_corrupted_contact_emails(self):
        """R70-B: pi_enricher used to extract phone-number-prefixed or
        capitalized-label-mashed addresses from HTML pages where adjacent
        elements lacked whitespace separators. After the fix + cleanup
        migration, no record should have a contact_email matching the
        known corruption patterns."""
        data = _load_data()
        corrupted = []
        for o in data:
            ce = o.get("contact_email")
            if not isinstance(ce, str) or "@" not in ce:
                continue
            if _PHONE_IN_LOCAL.match(ce) or _CAPS_MASHED_LOCAL.match(ce):
                corrupted.append((o.get("id"), ce))
        assert not corrupted, (
            f"{len(corrupted)} records have corruption-pattern contact_email "
            f"values. First 3: {corrupted[:3]}"
        )

    def test_past_deadline_deactivated(self):
        """Records with a parseable past deadline must be is_active=False
        (handled by src.normalizers.deactivate_past, now wired into
        refresh_all.py per R70-C so every local refresh closes the loop).
        Zero tolerance — any leak means deactivate_past was bypassed."""
        data = _load_data()
        today = date.today()
        leaks = []
        for o in data:
            dt = _parse_iso(o.get("deadline"))
            if dt and dt < today:
                if o.get("metadata", {}).get("is_active") is not False:
                    leaks.append(o.get("id"))
        assert len(leaks) <= PAST_DEADLINE_LEAK_TOLERANCE, (
            f"{len(leaks)} past-deadline records still is_active=True "
            f"(tolerance: {PAST_DEADLINE_LEAK_TOLERANCE}). First 3: {leaks[:3]}"
        )
