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


def _data_as_of(data: list[dict]) -> date:
    """The date the snapshot was last refreshed = newest last_seen_at across
    records. The past-deadline invariant must be anchored here, not to
    date.today(): deactivate_past runs at refresh time against the refresh
    clock, so a committed record can only be a *pipeline leak* if its deadline
    had already passed when the data was generated. Anchoring to date.today()
    instead made the test go red at midnight boundaries whenever the committed
    file aged past a still-active deadline — that is staleness, not a bug."""
    seen = [
        _parse_iso((o.get("metadata") or {}).get("last_seen_at"))
        for o in data
    ]
    seen = [d for d in seen if d]
    return max(seen) if seen else date.today()


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
        """Records whose deadline had already passed *as of the snapshot's
        refresh date* must be is_active=False (handled by
        src.normalizers.deactivate_past, wired into refresh_all.py per R70-C
        so every refresh closes the loop). Zero tolerance — any leak means
        deactivate_past was bypassed at generation time.

        Anchored to the data's as-of date (newest last_seen_at), NOT
        date.today(): the deterministic logic of deactivate_past is covered
        separately by TestDeactivatePastLogic, and anchoring this snapshot
        assertion to the wall clock made it flake at midnight boundaries when
        the committed file aged past a deadline that was still live at refresh.
        """
        data = _load_data()
        as_of = _data_as_of(data)
        leaks = []
        for o in data:
            dt = _parse_iso(o.get("deadline"))
            if dt and dt < as_of:
                if o.get("metadata", {}).get("is_active") is not False:
                    leaks.append(o.get("id"))
        assert len(leaks) <= PAST_DEADLINE_LEAK_TOLERANCE, (
            f"{len(leaks)} records past-deadline as of {as_of} still "
            f"is_active=True (tolerance: {PAST_DEADLINE_LEAK_TOLERANCE}). "
            f"First 3: {leaks[:3]}"
        )

    def test_no_shared_department_keyword_pollution(self):
        """DQ-1: a department-wide 'Research Areas' nav block scraped into many
        profiles produced byte-identical multi-keyword sets across same-department
        faculty (74 CS profs all 'doing compilers'), giving false specific matches.
        After the demotion fix no uiuc_faculty multi-keyword set may be shared by
        more than the collector's threshold of same-department peers."""
        from collections import defaultdict

        from src.collectors.uiuc_faculty import _SHARED_KEYWORD_POLLUTION_THRESHOLD

        groups: dict[tuple[str, tuple[str, ...]], int] = defaultdict(int)
        for o in _load_data():
            if o.get("source") != "uiuc_faculty":
                continue
            kws = tuple(sorted((k or "").lower() for k in (o.get("keywords") or [])))
            if len(kws) >= 2:
                groups[(o.get("department", ""), kws)] += 1
        polluted = {k: n for k, n in groups.items() if n > _SHARED_KEYWORD_POLLUTION_THRESHOLD}
        assert not polluted, (
            f"{len(polluted)} department-block keyword sets still shared by "
            f">{_SHARED_KEYWORD_POLLUTION_THRESHOLD} peers. First: {list(polluted.items())[:2]}"
        )

    def test_no_shared_admin_contact_emails(self):
        """D3: a scraped department/advising inbox (amwhit@ on 123 profs, nslack@
        on 116) attached as many professors' contact_email misfires cold emails to
        the wrong person. After the null-pass no faculty contact_email may be
        shared by the collector's threshold of distinct professors."""
        from collections import defaultdict

        from src.collectors.uiuc_faculty import _SHARED_ADMIN_EMAIL_THRESHOLD

        names_by_email: dict[str, set[str]] = defaultdict(set)
        for o in _load_data():
            if o.get("source") != "uiuc_faculty":
                continue
            email = (o.get("contact_email") or "").strip().lower()
            if email:
                names_by_email[email].add((o.get("pi_name") or "").strip().lower())
        shared = {e: len(n) for e, n in names_by_email.items()
                  if len(n) >= _SHARED_ADMIN_EMAIL_THRESHOLD}
        assert not shared, (
            f"{len(shared)} contact email(s) still shared by "
            f">={_SHARED_ADMIN_EMAIL_THRESHOLD} distinct professors: {shared}"
        )

    def test_faculty_title_parenthetical_is_subset_of_keywords(self):
        """D1/D2: the parenthetical in a faculty title ("— CS (areas)") must name
        only the record's own keywords, never a scraped department nav-menu. Any
        area shown but absent from keywords is false-precise pollution."""
        import re

        offenders = []
        for o in _load_data():
            if o.get("source") != "uiuc_faculty":
                continue
            m = re.search(r" — .+? \((.+)\)$", o.get("title", ""))
            if not m:
                continue
            shown = {a.strip().lower() for a in m.group(1).split(",")}
            kws = {(k or "").strip().lower() for k in (o.get("keywords") or [])}
            extra = shown - kws
            if extra:
                offenders.append((o.get("id"), extra))
        assert not offenders, (
            f"{len(offenders)} faculty titles show areas absent from their "
            f"keywords (nav-menu pollution). First: {offenders[:3]}"
        )

    def test_faculty_description_has_no_navmenu_leak(self):
        """D2: scraped page furniture must not survive in faculty descriptions."""
        NAV = ["Once Research Secured", "Administration & Staff", "Colloquia Calendar",
               "Affiliated Faculty", "Labs & Facilities", "Research Institutes and Centers"]
        leaks = [
            o.get("id") for o in _load_data()
            if o.get("source") == "uiuc_faculty"
            and any(n in (o.get("description_clean") or "") for n in NAV)
        ]
        assert not leaks, f"{len(leaks)} faculty descriptions still leak nav-menu text: {leaks[:3]}"


class TestDeactivatePastLogic:
    """Deterministic guard for the deactivate_past normalizer itself, using an
    injected `today` so it never depends on the wall clock (unlike the snapshot
    invariant above). This is the real logic contract; the snapshot test only
    confirms the committed file honored it at generation time."""

    REF = date(2026, 1, 15)

    def _run(self, opps):
        from src.normalizers.deactivate_past import deactivate_past

        return deactivate_past(opps, today=self.REF)

    def test_past_deadline_marked_inactive_with_metadata(self):
        opp = {"id": "x", "deadline": "2026-01-01"}
        counts = self._run([opp])
        assert opp["metadata"]["is_active"] is False
        assert opp["metadata"]["deactivated_at"] == self.REF.isoformat()
        assert opp["metadata"]["deactivation_reason"] == "deadline_passed"
        assert counts["newly_deactivated"] == 1

    def test_future_deadline_kept_active(self):
        opp = {"id": "x", "deadline": "2026-12-31"}
        counts = self._run([opp])
        assert opp.get("metadata", {}).get("is_active") is not False
        assert counts["kept_active"] == 1

    def test_rolling_is_skipped(self):
        opp = {"id": "x", "deadline": "2026-01-01", "is_rolling": True}
        counts = self._run([opp])
        assert opp.get("metadata", {}).get("is_active") is not False
        assert counts["skipped_rolling"] == 1

    def test_no_deadline_is_skipped(self):
        opp = {"id": "x", "deadline": None}
        counts = self._run([opp])
        assert counts["skipped_no_deadline"] == 1

    def test_unparseable_deadline_is_skipped(self):
        opp = {"id": "x", "deadline": "sometime next spring"}
        counts = self._run([opp])
        assert opp.get("metadata", {}).get("is_active") is not False
        assert counts["skipped_invalid"] == 1

    def test_already_inactive_is_idempotent(self):
        """Re-running must not overwrite the original deactivated_at stamp."""
        opp = {
            "id": "x",
            "deadline": "2026-01-01",
            "metadata": {"is_active": False, "deactivated_at": "2025-12-01"},
        }
        counts = self._run([opp])
        assert counts["already_inactive"] == 1
        assert counts["newly_deactivated"] == 0
        assert opp["metadata"]["deactivated_at"] == "2025-12-01"
