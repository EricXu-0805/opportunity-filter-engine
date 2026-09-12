"""Retirement authority must come from per-unit proof, never from inference.

The defect these cover cost a release cycle: every school-wide faculty
collector reported one integer, `deactivate_stale_faculty` could not prove
absence inside any single department from it, and so preserved everything.
7,522 stale records accumulated that no refresh could re-observe and no pass
could retire. The fix is a per-unit collection ledger — and the whole value of
it is that it distinguishes "this professor is gone" from "this collector did
not see this professor". Each test below pins one half of that distinction.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest
import yaml

from src.normalizers.deactivate_stale_faculty import (
    GRACE_DAYS,
    deactivate_stale_faculty,
    finalize_unit_ledger,
    unit_retirement_authority,
)

TODAY = date(2026, 9, 11)
LONG_AGO = (TODAY - timedelta(days=GRACE_DAYS + 10)).isoformat()
RECENT = (TODAY - timedelta(days=1)).isoformat()


def rec(rid, *, seen=LONG_AGO, dept="Department of Biology",
        source="testu_faculty", active=True, school="testu"):
    return {
        "id": rid,
        "source": source,
        "source_type": "faculty_research",
        "school": school,
        "department": dept,
        "metadata": {"is_active": active, "last_seen_at": seen},
    }


def observation(unit_id="bio", *, observed_ids=(), baseline=None,
                fetch="ok", parse="ok", validation="ok",
                completeness=None, authorized=None, name="Department of Biology"):
    obs = {
        "school": "testu",
        "source": "testu_faculty",
        "unit_id": unit_id,
        "unit_name": name,
        "collector": "faculty_graph",
        "collector_version": "faculty_graph.1.deadbeef",
        "ledger_version": 1,
        "observed_count": len(observed_ids),
        "observed_entity_ids": list(observed_ids),
        "started_at": "2026-09-11T00:00:00+00:00",
        "completed_at": "2026-09-11T00:05:00+00:00",
        "fetch_status": fetch,
        "parse_status": parse,
        "validation_status": validation,
        "baseline_active_count": baseline,
        "completeness_status": completeness,
        "retirement_authorized": authorized,
        "failure_reason": None,
    }
    if completeness is None and authorized is None:
        # Default to a finalized, complete observation.
        obs["baseline_active_count"] = (baseline if baseline is not None
                                        else len(observed_ids))
        obs["completeness_status"] = "complete"
        obs["retirement_authorized"] = True
    return obs


# 1. complete department scrape may authorize retirement
def test_complete_unit_scrape_authorizes_retirement():
    opps = [rec("faculty-tu-bio-aaaaaaa1", seen=LONG_AGO),
            rec("faculty-tu-bio-aaaaaaa2", seen=RECENT)]
    ledger = {"bio": observation(observed_ids=["faculty-tu-bio-aaaaaaa2"],
                                 baseline=2)}
    # 1 observed of 2 active is below the ratio, so widen the unit: 20 active,
    # 19 seen, one genuinely gone.
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=RECENT) for i in range(19)]
    opps.append(rec("faculty-tu-bio-ffffffff", seen=LONG_AGO))
    ledger = {"bio": observation(
        observed_ids=[o["id"] for o in opps[:19]], baseline=20)}
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert out["newly_deactivated"] == 1
    assert out["records_retirement_authorized"] == 1
    assert opps[-1]["metadata"]["is_active"] is False
    assert out["units_authorized"][0]["reason"] == "complete_unit_observation"


# 2. partial department scrape cannot authorize retirement
def test_partial_unit_scrape_cannot_authorize():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=LONG_AGO) for i in range(20)]
    ledger = {"bio": observation(observed_ids=[o["id"] for o in opps[:10]],
                                 baseline=20, completeness="partial",
                                 authorized=False)}
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert out["newly_deactivated"] == 0
    assert out["records_preserved_partial"] == 20
    assert all(o["metadata"]["is_active"] for o in opps)


# 3. suspicious-zero department cannot authorize retirement
def test_suspicious_zero_cannot_authorize():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=LONG_AGO) for i in range(5)]
    ledger = {"bio": observation(observed_ids=[], baseline=5,
                                 parse="suspicious_zero",
                                 completeness="unknown", authorized=False)}
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert out["newly_deactivated"] == 0
    assert out["records_preserved_suspicious_zero"] == 5


# 4. a 404 source cannot authorize retirement
def test_http_404_cannot_authorize():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=LONG_AGO) for i in range(5)]
    ledger = {"bio": observation(observed_ids=[], baseline=5,
                                 fetch="http_404", completeness="unknown",
                                 authorized=False)}
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert out["newly_deactivated"] == 0
    assert out["records_preserved_failed_source"] == 5
    assert any("fetch_http_404" in w["reason"] for w in out["units_withheld"])


# 5. a 403 source cannot authorize retirement
def test_http_403_cannot_authorize():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=LONG_AGO) for i in range(5)]
    ledger = {"bio": observation(observed_ids=[], baseline=5,
                                 fetch="http_403", completeness="unknown",
                                 authorized=False)}
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert out["newly_deactivated"] == 0
    assert out["records_preserved_failed_source"] == 5


# 6. missing unit lineage cannot authorize retirement
def test_missing_unit_lineage_cannot_authorize():
    # An id that carries no parseable unit is never attached to one.
    opps = [rec("legacy-row-without-unit", seen=LONG_AGO)]
    ledger = {"bio": observation(observed_ids=["faculty-tu-bio-1"], baseline=1)}
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert out["newly_deactivated"] == 0
    assert out["records_preserved_missing_lineage"] == 1
    assert opps[0]["metadata"]["is_active"] is True


# 7. a source-level school count alone cannot authorize department retirement
def test_school_wide_count_cannot_authorize_department_retirement():
    opps = [rec("faculty-tu-bio-aaaaaaa1", seen=LONG_AGO,
                dept="Department of Biology"),
            rec("faculty-tu-phy-aaaaaaa2", seen=LONG_AGO,
                dept="Department of Physics")]
    # The whole school scraped 2 of 2 — a perfect ratio that still proves
    # nothing about either department.
    out = deactivate_stale_faculty(opps, {"testu_faculty": 2}, today=TODAY)
    assert out["newly_deactivated"] == 0
    assert "testu_faculty" in out["skipped_missing_unit_ledger"]
    assert all(o["metadata"]["is_active"] for o in opps)


# 8. a departed professor absent from a complete unit scrape may be retired
def test_departed_professor_absent_from_complete_scrape_is_retired():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=RECENT) for i in range(19)]
    departed = rec("faculty-tu-bio-deadbee1", seen=LONG_AGO)
    opps.append(departed)
    ledger = {"bio": observation(observed_ids=[o["id"] for o in opps[:19]],
                                 baseline=20)}
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert departed["metadata"]["is_active"] is False
    assert departed["metadata"]["deactivation_reason"] == (
        "absent_from_directory_rescrape")
    assert out["proposals"][0]["entity_id"] == "faculty-tu-bio-deadbee1"
    assert out["proposals"][0]["observed_entity_ids_recorded"] is True


# 9. a professor absent because the collector failed is preserved
def test_professor_absent_because_collector_failed_is_preserved():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=LONG_AGO) for i in range(20)]
    # Same population as test 8, but the unit's fetch failed. Identical
    # absence, opposite verdict — which is the whole point of the ledger.
    ledger = {"bio": observation(observed_ids=[], baseline=20,
                                 fetch="timeout", completeness="unknown",
                                 authorized=False)}
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert out["newly_deactivated"] == 0
    assert all(o["metadata"]["is_active"] for o in opps)


# 10. a department move does not leave the professor inactive product-wide
def test_department_move_keeps_the_professor_active_somewhere():
    # The person left Biology and appears in Physics under a new unit id.
    # Retiring the Biology row is correct — they really are not in Biology —
    # but the professor must remain represented in the corpus.
    bio_rows = [rec(f"faculty-tu-bio-{i:08x}", seen=RECENT) for i in range(19)]
    moved_old = rec("faculty-tu-bio-99999999", seen=LONG_AGO)
    moved_new = rec("faculty-tu-phy-99999999", seen=RECENT,
                    dept="Department of Physics")
    opps = [*bio_rows, moved_old, moved_new]
    ledger = {
        "bio": observation(observed_ids=[r["id"] for r in bio_rows],
                           baseline=20),
        "phy": observation(unit_id="phy", name="Department of Physics",
                           observed_ids=[moved_new["id"]], baseline=1),
    }
    deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert moved_old["metadata"]["is_active"] is False
    assert moved_new["metadata"]["is_active"] is True


# 11. repeated reconciliation is idempotent
def test_repeated_reconciliation_is_idempotent():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=RECENT) for i in range(19)]
    opps.append(rec("faculty-tu-bio-cafebabe", seen=LONG_AGO))
    ledger = {"bio": observation(observed_ids=[o["id"] for o in opps[:19]],
                                 baseline=20)}
    first = deactivate_stale_faculty(opps, {"testu_faculty": ledger},
                                     today=TODAY)
    snapshot = copy.deepcopy(opps)
    second = deactivate_stale_faculty(opps, {"testu_faculty": ledger},
                                      today=TODAY)
    assert first["newly_deactivated"] == 1
    assert second["newly_deactivated"] == 0
    assert opps == snapshot


# 12. a dry run performs no mutations
def test_dry_run_mutates_nothing():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=RECENT) for i in range(19)]
    opps.append(rec("faculty-tu-bio-0badf00d", seen=LONG_AGO))
    ledger = {"bio": observation(observed_ids=[o["id"] for o in opps[:19]],
                                 baseline=20)}
    before = copy.deepcopy(opps)
    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger},
                                   today=TODAY, dry_run=True)
    assert out["dry_run"] is True
    assert out["newly_deactivated"] == 0
    assert out["records_retirement_authorized"] == 1
    assert out["would_deactivate"] == ["faculty-tu-bio-0badf00d"]
    assert opps == before


# 13. retirement does not rewrite historical last_seen_at
def test_retirement_preserves_last_seen_at():
    opps = [rec(f"faculty-tu-bio-{i:08x}", seen=RECENT) for i in range(19)]
    gone = rec("faculty-tu-bio-5ee40009", seen=LONG_AGO)
    opps.append(gone)
    ledger = {"bio": observation(observed_ids=[o["id"] for o in opps[:19]],
                                 baseline=20)}
    deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert gone["metadata"]["last_seen_at"] == LONG_AGO
    assert gone["metadata"]["deactivated_at"] == TODAY.isoformat()


# 14. manual recovery cannot cancel a scheduled refresh via shared concurrency
def test_manual_dispatch_cannot_displace_scheduled_refresh():
    wf = yaml.safe_load(open(".github/workflows/refresh-data.yml"))
    group = wf["concurrency"]["group"]
    # GitHub keeps only ONE pending run per group, so a shared literal group
    # lets a manual dispatch cancel the queued daily refresh. The group must
    # vary by event.
    assert "github.event_name" in group, (
        "scheduled and manual runs must not share a pending concurrency slot")
    assert wf["concurrency"]["cancel-in-progress"] is False
    steps = wf["jobs"]["refresh"]["steps"]
    guard = next((s for s in steps if "Defer manual runs" in (s.get("name") or "")),
                 None)
    assert guard is not None, "manual runs need a mutual-exclusion guard"
    assert guard["if"] == "github.event_name == 'workflow_dispatch'"
    # The guard must run before anything mutates or costs a checkout.
    assert steps.index(guard) == 0


# --- the authority invariant itself ---------------------------------------

@pytest.mark.parametrize("kwargs,expected_reason", [
    ({"fetch": "http_404"}, "fetch_http_404"),
    ({"fetch": "http_403"}, "fetch_http_403"),
    ({"fetch": "timeout"}, "fetch_timeout"),
    ({"parse": "zero_rows"}, "parse_zero_rows"),
    ({"parse": "suspicious_zero"}, "parse_suspicious_zero"),
    ({"validation": "failed"}, "validation_failed"),
])
def test_every_failure_mode_fails_closed(kwargs, expected_reason):
    entry = observation(observed_ids=["a"], baseline=1, completeness="complete",
                        authorized=True, **kwargs)
    ok, reason = unit_retirement_authority(entry, 1)
    assert ok is False
    assert reason == expected_reason


def test_unknown_status_is_not_authority():
    entry = observation(observed_ids=["a"], baseline=1, completeness="complete",
                        authorized=True, fetch="something_new_and_unhandled")
    ok, _ = unit_retirement_authority(entry, 1)
    assert ok is False


def test_producer_cannot_authorise_itself_without_completeness():
    entry = observation(observed_ids=["a"], baseline=100,
                        completeness="complete", authorized=True)
    # observed 1 of a declared baseline of 100 — the ratio gate still refuses.
    ok, reason = unit_retirement_authority(entry, 100)
    assert ok is False
    assert reason == "partial_scrape"


def test_finalize_marks_complete_and_partial_units():
    opps = [rec(f"faculty-tu-bio-{i:08x}") for i in range(10)]
    opps += [rec(f"faculty-tu-phy-{i:08x}", dept="Department of Physics")
             for i in range(10)]
    ledger = {
        "bio": observation(observed_ids=[o["id"] for o in opps[:10]]),
        "phy": observation(unit_id="phy", observed_ids=[opps[10]["id"]]),
    }
    for e in ledger.values():
        e["completeness_status"] = None
        e["retirement_authorized"] = None
        e["baseline_active_count"] = None
    finalize_unit_ledger(ledger, opps, "testu_faculty")
    assert ledger["bio"]["completeness_status"] == "complete"
    assert ledger["bio"]["retirement_authorized"] is True
    assert ledger["phy"]["completeness_status"] == "partial"
    assert ledger["phy"]["retirement_authorized"] is False


def test_finalize_never_authorises_a_unit_with_no_baseline():
    ledger = {"bio": observation(observed_ids=["faculty-tu-bio-1"])}
    ledger["bio"]["completeness_status"] = None
    ledger["bio"]["retirement_authorized"] = None
    finalize_unit_ledger(ledger, [], "testu_faculty")
    assert ledger["bio"]["retirement_authorized"] is False


def test_substitution_does_not_mask_a_departure():
    """A new arrival must not buy authority to retire someone unparsed.

    Regression for a false positive the manual sample caught on 2026-09-11:
    Bowdoin EOS scraped 6 people against 6 active records and scored a perfect
    count ratio, so the pass proposed retiring a professor who was still
    listed on the page it had just scraped — the scrape had simply failed to
    parse her card and had picked up a new colleague instead. Counting only
    how MANY rows came back cannot see that; intersecting with the baseline
    can.
    """
    kept = [rec(f"faculty-tu-bio-{i:08x}", seen=RECENT) for i in range(5)]
    unparsed = rec("faculty-tu-bio-0000beef", seen=LONG_AGO)
    opps = [*kept, unparsed]
    # Six observed against six active — but one of them is a brand-new person,
    # and the sixth incumbent was never seen.
    ledger = {"bio": observation(
        observed_ids=[*[r["id"] for r in kept], "faculty-tu-bio-newc0mer"])}
    ledger["bio"]["completeness_status"] = None
    ledger["bio"]["retirement_authorized"] = None
    ledger["bio"]["baseline_active_count"] = None
    finalize_unit_ledger(ledger, opps, "testu_faculty")

    assert ledger["bio"]["observed_count"] == 6
    assert ledger["bio"]["matched_baseline_count"] == 5
    assert ledger["bio"]["new_entity_count"] == 1
    assert ledger["bio"]["completeness_status"] == "partial"
    assert ledger["bio"]["retirement_authorized"] is False

    out = deactivate_stale_faculty(opps, {"testu_faculty": ledger}, today=TODAY)
    assert out["newly_deactivated"] == 0
    assert unparsed["metadata"]["is_active"] is True
