"""Offline tests for src.normalizers.deactivate_stale_faculty.

Locks in the conservative stale-faculty deactivation pass:

  * a record unseen for more than GRACE_DAYS is deactivated with the standard
    metadata stamps (is_active / deactivated_at / deactivation_reason);
  * fresh records (and records exactly at the cutoff) are kept;
  * the partial-scrape gate skips a source whose scrape yielded < 70% of its
    currently-active records — a broken scrape must never mass-deactivate;
  * sources absent from ``fetched_counts`` (didn't run, or errored) are never
    touched, no matter how stale their records are;
  * a deactivated professor who reappears in a later scrape is reactivated by
    the existing merge behavior (round-trip through both real faculty merges).
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.normalizers.deactivate_stale_faculty import (
    FACULTY_SOURCES,
    deactivate_stale_faculty,
)

TODAY = date(2026, 6, 12)
STALE = "2026-05-01T00:00:00"      # 42 days before TODAY
FRESH = "2026-06-12T08:00:00"      # scraped this run
AT_CUTOFF = "2026-05-29T00:00:00"  # exactly GRACE_DAYS before TODAY


def _fac(ident, source="uiuc_faculty", last_seen=STALE, active=True,
         source_type="faculty_research"):
    return {
        "id": ident,
        "source": source,
        "source_type": source_type,
        "title": f"Research with Prof. {ident}",
        "deadline": None,
        "metadata": {
            "first_seen_at": "2026-01-01T00:00:00",
            "last_seen_at": last_seen,
            "is_active": active,
        },
    }


def test_stale_record_deactivated_with_standard_stamps():
    opps = [_fac("a", last_seen=STALE)]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 10}, today=TODAY)
    assert counts["newly_deactivated"] == 1
    meta = opps[0]["metadata"]
    assert meta["is_active"] is False
    assert meta["deactivated_at"] == "2026-06-12"
    assert meta["deactivation_reason"] == "absent_from_directory_rescrape"


def test_fresh_and_at_cutoff_records_kept():
    opps = [_fac("a", last_seen=FRESH), _fac("b", last_seen=AT_CUTOFF)]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 10}, today=TODAY)
    assert counts["newly_deactivated"] == 0
    assert counts["kept_fresh"] == 2
    assert all(o["metadata"]["is_active"] is True for o in opps)


def test_partial_scrape_gate_skips_source():
    opps = [_fac(f"p{i}", last_seen=STALE) for i in range(10)]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 6}, today=TODAY)
    assert counts["newly_deactivated"] == 0
    assert counts["skipped_partial_scrape"] == ["uiuc_faculty"]
    assert all(o["metadata"]["is_active"] is True for o in opps)


def test_scrape_at_exactly_70_percent_passes_gate():
    opps = [_fac(f"p{i}", last_seen=STALE) for i in range(10)]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 7}, today=TODAY)
    assert counts["newly_deactivated"] == 10
    assert counts["skipped_partial_scrape"] == []


def test_source_not_in_run_is_untouched():
    opps = [_fac("a", source="ucb_eecs_faculty", last_seen=STALE)]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 10}, today=TODAY)
    assert counts["newly_deactivated"] == 0
    assert opps[0]["metadata"]["is_active"] is True


def test_no_sources_ran_is_full_noop():
    opps = [_fac("a", last_seen=STALE),
            _fac("b", source="ucb_stat_faculty", last_seen=STALE)]
    counts = deactivate_stale_faculty(opps, {}, today=TODAY)
    assert counts["newly_deactivated"] == 0
    assert all(o["metadata"]["is_active"] is True for o in opps)


def test_non_faculty_source_type_is_out_of_scope():
    opps = [_fac("a", last_seen=STALE, source_type="research")]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 10}, today=TODAY)
    assert counts["newly_deactivated"] == 0
    assert opps[0]["metadata"]["is_active"] is True


def test_missing_last_seen_at_is_kept():
    opps = [_fac("a", last_seen=None)]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 10}, today=TODAY)
    assert counts["newly_deactivated"] == 0
    assert counts["kept_fresh"] == 1


def test_already_inactive_excluded_from_gate_denominator():
    # 10 records, 7 already inactive: gate compares fetched against the 3
    # still-active ones, so fetched=3 passes and the stale actives retire.
    opps = [_fac(f"d{i}", last_seen=STALE, active=False) for i in range(7)]
    opps += [_fac(f"a{i}", last_seen=STALE) for i in range(3)]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 3}, today=TODAY)
    assert counts["already_inactive"] == 7
    assert counts["newly_deactivated"] == 3
    # The previously-inactive records keep their original stamps untouched.
    assert "deactivated_at" not in opps[0]["metadata"]


def test_faculty_sources_match_refresh_all_registrations():
    """FACULTY_SOURCES must exactly equal the set of faculty sources refresh_all
    actually processes — derived from the wiring, not a hardcoded literal, so it
    can't go stale as departments are added. A source wired but unregistered
    would never have its stale professors retired; a registered source not wired
    would never be scraped. Both directions are bugs, so assert equality.
    """
    import pathlib
    import re

    import src.collectors.refresh_all as refresh_all  # import must not blow up

    src = pathlib.Path(refresh_all.__file__).read_text(encoding="utf-8")
    # Every faculty source name appears as a quoted source-name literal in
    # refresh_all (the ucb deep-loop tuples + the uiuc_faculty summary key).
    # Anchored to the source-naming convention so unrelated "*_faculty" strings
    # (e.g. the "deactivate_stale_faculty" summary key) aren't miscounted.
    wired = set(re.findall(r'"(ucb_\w+_faculty|uiuc_faculty)"', src))
    assert wired == set(FACULTY_SOURCES), (
        "FACULTY_SOURCES is out of sync with refresh_all's faculty wiring.\n"
        f"  wired but unregistered: {sorted(wired - set(FACULTY_SOURCES))}\n"
        f"  registered but not wired: {sorted(set(FACULTY_SOURCES) - wired)}"
    )


# --- Reactivation round-trip through the real merges -------------------------


def _deactivated_copy(opp):
    old = copy.deepcopy(opp)
    old["metadata"]["last_seen_at"] = STALE
    old["metadata"]["is_active"] = False
    old["metadata"]["deactivated_at"] = "2026-05-20"
    old["metadata"]["deactivation_reason"] = "absent_from_directory_rescrape"
    return old


def test_ucb_merge_reactivates_reappearing_faculty(tmp_path, monkeypatch):
    from src.collectors import ucb_common
    from src.collectors.ucb_stat_faculty import STAT_CONFIG

    fresh = ucb_common.normalize_faculty(
        {"name": "Ani Adhikari", "title": "Teaching Professor",
         "url": "https://statistics.berkeley.edu/people/ani-adhikari"},
        STAT_CONFIG,
    )
    old = _deactivated_copy(fresh)
    old["metadata"]["first_seen_at"] = "2026-01-01T00:00:00"
    processed = tmp_path / "opportunities.json"
    processed.write_text(json.dumps([old]), encoding="utf-8")
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", processed)

    added, updated = ucb_common.merge_into_processed([fresh])

    assert (added, updated) == (0, 1)
    saved = json.loads(processed.read_text(encoding="utf-8"))[0]
    assert saved["metadata"]["is_active"] is True
    assert saved["metadata"]["last_seen_at"] == fresh["metadata"]["last_seen_at"]
    assert saved["metadata"]["first_seen_at"] == "2026-01-01T00:00:00"


def test_uiuc_merge_reactivates_reappearing_faculty(tmp_path):
    from src.collectors.uiuc_faculty import (
        DEPARTMENTS,
        merge_into_processed,
        normalize_faculty,
    )

    fresh = normalize_faculty(
        {"name": "Jane Smith", "title": "Professor",
         "url": "https://ece.illinois.edu/about/directory/faculty/jsmith",
         "research_areas": "machine learning, computer vision"},
        DEPARTMENTS["ece"],
    )
    old = _deactivated_copy(fresh)
    old["metadata"]["first_seen_at"] = "2026-01-01T00:00:00"
    processed = tmp_path / "opportunities.json"
    processed.write_text(json.dumps([old]), encoding="utf-8")

    added, updated = merge_into_processed([fresh], filepath=str(processed))

    assert (added, updated) == (0, 1)
    saved = json.loads(processed.read_text(encoding="utf-8"))[0]
    assert saved["metadata"]["is_active"] is True
    assert saved["metadata"]["last_seen_at"] == fresh["metadata"]["last_seen_at"]
    assert saved["metadata"]["first_seen_at"] == "2026-01-01T00:00:00"
