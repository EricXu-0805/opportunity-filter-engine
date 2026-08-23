"""Offline tests for src.normalizers.deactivate_stale_faculty.

Locks in the conservative stale-faculty deactivation pass:

  * a record unseen for more than GRACE_DAYS is deactivated with the standard
    metadata stamps (is_active / deactivated_at / deactivation_reason);
  * fresh records (and records exactly at the cutoff) are kept;
  * the partial-scrape gate skips a source whose scrape yielded < 95% of its
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
         source_type="faculty_research", department="ECE"):
    return {
        "id": ident,
        "source": source,
        "source_type": source_type,
        "department": department,
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


def test_scrape_at_exactly_95_percent_passes_gate():
    opps = [_fac(f"p{i}", last_seen=STALE) for i in range(20)]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 19}, today=TODAY)
    assert counts["newly_deactivated"] == 20
    assert counts["skipped_partial_scrape"] == []


def test_aggregate_source_cannot_hide_a_missing_department_at_95_percent():
    opps = [
        _fac(f"present-{i}", last_seen=FRESH, department="Computer Science")
        for i in range(95)
    ]
    opps += [
        _fac(f"missing-{i}", last_seen=STALE, department="Statistics")
        for i in range(5)
    ]

    counts = deactivate_stale_faculty(
        opps,
        {"uiuc_faculty": 95},
        today=TODAY,
    )

    assert counts["newly_deactivated"] == 0
    assert counts["skipped_missing_unit_ledger"] == ["uiuc_faculty"]
    assert all(o["metadata"]["is_active"] is True for o in opps)


def test_unnamed_unit_is_preserved_without_unit_ledger():
    opps = [_fac("unknown", department="", last_seen=STALE)]

    counts = deactivate_stale_faculty(
        opps,
        {"uiuc_faculty": 1},
        today=TODAY,
    )

    assert counts["newly_deactivated"] == 0
    assert counts["skipped_missing_unit_ledger"] == ["uiuc_faculty"]
    assert opps[0]["metadata"]["is_active"] is True


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
    # refresh_all (the ucb deep-loop tuples + the uiuc_faculty / umich_faculty
    # summary keys). Match any quoted "<school>[_<dept>]_faculty" source — the
    # convention every school's faculty collector follows, so the Top-50 rollout
    # never has to touch this regex — excluding the lone non-source "*_faculty"
    # literal (the "deactivate_stale_faculty" summary key).
    _NON_SOURCE_FACULTY = {"deactivate_stale_faculty"}
    wired = set(re.findall(r'"(\w+_faculty)"', src)) - _NON_SOURCE_FACULTY
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


# ---------------------------------------------------------------------------
# Per-unit ledger: making the pass reach the 98.4% it currently cannot
#
# Of the 167 faculty sources wired into this pass, 52 represent exactly one
# named unit and can retire a departed professor. The other 115 — 126,877 of
# the 128,892 faculty records, 98.4% — span several departments, so the
# source-level count cannot prove any individual department was scraped, and
# the pass preserves everything. 9,692 records currently sit past the grace
# window with no mechanism able to adjudicate them, and the corpus holds
# professors their directory no longer lists.
#
# A per-department count closes that without weakening anything: the same
# MIN_SCRAPE_RATIO and GRACE_DAYS gates, applied per unit instead of per
# source. A department whose URL rotted scrapes 0 against N active records and
# is skipped; a whole collector component collapsing takes all of its
# departments to 0 and skips them all.
#
# Every gate below is the existing one. Nothing here lowers a bar.
# ---------------------------------------------------------------------------


def test_a_ledger_retires_only_within_a_department_that_scraped_completely():
    # The exact scenario test_aggregate_source_cannot_hide_a_missing_department
    # refuses to act on: 95 fresh CS, 5 stale Statistics. With a ledger the
    # answer is no longer "preserve everything" — it is "CS is provably
    # complete, Statistics provably is not".
    opps = [
        _fac(f"cs-{i}", last_seen=FRESH, department="Computer Science")
        for i in range(95)
    ] + [
        _fac(f"stat-{i}", last_seen=STALE, department="Statistics")
        for i in range(5)
    ]
    counts = deactivate_stale_faculty(
        opps,
        {"uiuc_faculty": {"Computer Science": 95, "Statistics": 0}},
        today=TODAY,
    )
    assert counts["newly_deactivated"] == 0
    assert counts["skipped_partial_scrape"] == ["uiuc_faculty/Statistics"]
    assert all(o["metadata"]["is_active"] is True for o in opps)


def test_a_department_that_scraped_completely_retires_its_stale_records():
    opps = [
        _fac(f"cs-{i}", last_seen=FRESH, department="Computer Science")
        for i in range(19)
    ] + [_fac("cs-gone", last_seen=STALE, department="Computer Science")]
    counts = deactivate_stale_faculty(
        opps, {"uiuc_faculty": {"Computer Science": 19}}, today=TODAY,
    )
    assert counts["newly_deactivated"] == 1
    assert opps[-1]["metadata"]["is_active"] is False
    assert opps[-1]["metadata"]["deactivation_reason"] == "absent_from_directory_rescrape"


def test_a_department_missing_from_the_ledger_is_never_retired():
    # A unit the ledger does not mention was not proven scraped at all. Absence
    # of evidence stays absence of authority.
    opps = [
        _fac("cs", last_seen=FRESH, department="Computer Science"),
        _fac("phys", last_seen=STALE, department="Physics"),
    ]
    counts = deactivate_stale_faculty(
        opps, {"uiuc_faculty": {"Computer Science": 1}}, today=TODAY,
    )
    assert counts["newly_deactivated"] == 0
    assert "uiuc_faculty/Physics" in counts["skipped_missing_unit_ledger"]
    assert opps[1]["metadata"]["is_active"] is True


def test_a_collapsed_component_takes_all_its_departments_down_with_it():
    # Chromium unavailable -> the JS producer returns nothing -> every
    # department it owns reports 0. None of them may retire anyone.
    opps = [
        _fac(f"js-{i}", last_seen=STALE, department=d)
        for d in ("Gies", "Social Work") for i in range(10)
    ]
    counts = deactivate_stale_faculty(
        opps, {"uiuc_faculty": {"Gies": 0, "Social Work": 0}}, today=TODAY,
    )
    assert counts["newly_deactivated"] == 0
    assert sorted(counts["skipped_partial_scrape"]) == [
        "uiuc_faculty/Gies", "uiuc_faculty/Social Work",
    ]


def test_a_held_source_reports_what_it_would_retire_and_retires_nothing():
    # UIUC carries a release-contract safety hold (refresh_contract blocks a
    # release that does not preserve it). Stage one produces the evidence for
    # lifting it without touching a single record.
    opps = [
        _fac(f"cs-{i}", last_seen=FRESH, department="Computer Science")
        for i in range(19)
    ] + [_fac("cs-gone", last_seen=STALE, department="Computer Science")]
    counts = deactivate_stale_faculty(
        opps,
        {"uiuc_faculty": {"Computer Science": 19}},
        today=TODAY,
        held_sources={"uiuc_faculty"},
    )
    assert counts["newly_deactivated"] == 0
    assert counts["would_deactivate"] == ["cs-gone"]
    assert all(o["metadata"]["is_active"] is True for o in opps)


def test_a_bare_count_still_means_exactly_what_it_meant_before():
    # No ledger -> the single-named-unit rule, unchanged. This is the same
    # assertion as test_aggregate_source_cannot_hide_a_missing_department,
    # restated here so a regression in the new branch cannot pass by only
    # keeping the ledger path honest.
    opps = [
        _fac(f"cs-{i}", last_seen=FRESH, department="Computer Science")
        for i in range(95)
    ] + [
        _fac(f"stat-{i}", last_seen=STALE, department="Statistics")
        for i in range(5)
    ]
    counts = deactivate_stale_faculty(opps, {"uiuc_faculty": 95}, today=TODAY)
    assert counts["newly_deactivated"] == 0
    assert counts["skipped_missing_unit_ledger"] == ["uiuc_faculty"]
