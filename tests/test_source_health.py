"""Department-level publish isolation and per-source freshness.

The failure this covers, end to end: one department collector emitted 0, the
release contract attributed the zero to its SCHOOL, the whole shard went
unpublished, and the school stayed frozen — UC Berkeley for 44 days with 53
healthy departments being re-scraped and discarded twice.

The invariants asserted here:

    department failure  -> degrade that department only
    department failure  != whole-school publish veto
    unexpected zero     -> preserve last-known-good, alert, never publish empty
    last_success_at      only ever advances on a real success
    school publish       never marks a department successful
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors import source_health as sh
from src.collectors.refresh_contract import (
    CONFIRMED_EMPTY_SOURCES,
    evaluate_refresh_summary,
    expected_sources,
    monitored_sources,
    record_source_aliases,
    shard_of_source,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------- classify --
class TestZeroClassification:
    """valid_zero / suspicious_zero / failed / success_nonzero."""

    def test_records_emitted_is_success(self):
        assert sh.classify(emitted=42, baseline=40) == sh.SUCCESS_NONZERO

    def test_declared_empty_source_zero_is_valid(self):
        """A seasonal listing outside its window legitimately has nothing."""
        assert sh.classify(
            emitted=0, baseline=479, allow_confirmed_empty=True,
        ) == sh.VALID_ZERO

    def test_historically_populated_source_at_zero_is_suspicious(self):
        """The ucb_ling_faculty case: 17 stored records, this run found none."""
        assert sh.classify(emitted=0, baseline=17) == sh.SUSPICIOUS_ZERO

    def test_never_populated_undeclared_source_is_not_called_valid(self):
        """valid_zero is never inferred — a mandatory producer that has never
        produced (ucd_faculty behind Cloudflare) is degraded, not healthy."""
        assert sh.classify(emitted=0, baseline=0) == sh.SUSPICIOUS_ZERO

    def test_error_is_failed(self):
        assert sh.classify(emitted=0, baseline=5, errored=True) == sh.FAILED

    @pytest.mark.parametrize("bad", [None, True, False, -1, "12", 1.5])
    def test_unusable_count_is_failed_not_success(self, bad):
        assert sh.classify(emitted=bad, baseline=5) == sh.FAILED

    def test_ucb_urap_projects_is_the_declared_seasonal_source(self):
        assert "ucb_urap_projects" in CONFIRMED_EMPTY_SOURCES


# ------------------------------------------------------------ the timestamps --
class TestTimestampSemantics:
    def _healthy(self, ledger, source="ucb_eecs_faculty", when=NOW, n=145):
        return sh.record_attempt(
            ledger, source=source, school="ucb",
            outcome=sh.SUCCESS_NONZERO, emitted=n, baseline=144, now=when,
        )

    def test_success_advances_attempt_and_success(self):
        ledger = sh.empty_ledger()
        row = self._healthy(ledger)
        assert row["last_attempt_at"] == row["last_success_at"] == NOW.isoformat()
        assert row["last_good_count"] == 145
        assert row["consecutive_failures"] == 0

    def test_suspicious_zero_advances_attempt_but_not_success(self):
        """The whole point: a source attempted weekly forever must not look
        fresh forever."""
        ledger = sh.empty_ledger()
        self._healthy(ledger, source="ucb_ling_faculty", when=NOW, n=17)
        later = NOW + timedelta(days=28)
        row = sh.record_attempt(
            ledger, source="ucb_ling_faculty", school="ucb",
            outcome=sh.SUSPICIOUS_ZERO, emitted=0, baseline=17, now=later,
            failure_reason="emitted 0 against a baseline of 17",
        )
        assert row["last_attempt_at"] == later.isoformat()
        assert row["last_success_at"] == NOW.isoformat()   # unmoved
        assert row["last_good_count"] == 17                 # preserved
        assert row["current_count"] == 0
        assert row["failure_reason"]

    def test_repeated_failure_accumulates(self):
        ledger = sh.empty_ledger()
        for day in (1, 8, 15):
            sh.record_attempt(
                ledger, source="colgate_faculty", school="colgate",
                outcome=sh.SUSPICIOUS_ZERO, emitted=0, baseline=314,
                now=NOW + timedelta(days=day),
            )
        assert ledger["sources"]["colgate_faculty"]["consecutive_failures"] == 3

    def test_recovery_resets_the_streak_and_stamps_success(self):
        ledger = sh.empty_ledger()
        sh.record_attempt(
            ledger, source="colgate_faculty", school="colgate",
            outcome=sh.SUSPICIOUS_ZERO, emitted=0, baseline=314, now=NOW,
        )
        recovered = NOW + timedelta(days=7)
        row = sh.record_attempt(
            ledger, source="colgate_faculty", school="colgate",
            outcome=sh.SUCCESS_NONZERO, emitted=308, baseline=314, now=recovered,
        )
        assert row["last_success_at"] == recovered.isoformat()
        assert row["consecutive_failures"] == 0
        assert row["failure_reason"] is None
        assert row["last_good_count"] == 308

    def test_first_failure_seeds_last_known_good_from_the_corpus(self):
        """So a regression is reportable even with no prior ledger row."""
        ledger = sh.empty_ledger()
        row = sh.record_attempt(
            ledger, source="swarthmore_faculty", school="swarthmore",
            outcome=sh.FAILED, emitted=0, baseline=228, now=NOW,
        )
        assert row["last_good_count"] == 228
        assert row.get("last_success_at") is None

    def test_publishing_a_school_does_not_make_its_sources_successful(self):
        """Stale-source masking, forbidden: "UCB published today" must never
        become "every UCB department succeeded today"."""
        ledger = sh.empty_ledger()
        sh.record_attempt(
            ledger, source="ucb_ling_faculty", school="ucb",
            outcome=sh.SUSPICIOUS_ZERO, emitted=0, baseline=17, now=NOW,
        )
        before = json.dumps(ledger["sources"], sort_keys=True)
        sh.record_publish(
            ledger, shards={"ucb": 3106}, now=NOW + timedelta(days=30),
        )
        assert json.dumps(ledger["sources"], sort_keys=True) == before
        assert ledger["shards"]["ucb"]["last_publish_at"]

    def test_unknown_success_is_never_reported_fresh(self):
        assert sh.freshness_of({}, NOW) == "unknown"
        assert sh.freshness_of({"last_success_at": "not-a-date"}, NOW) == "unknown"

    def test_last_nonzero_survives_an_empty_but_successful_run(self):
        """A declared-empty run is a success, so it moves last_success_at;
        when the source last produced records (M63) is a separate answer."""
        ledger = sh.empty_ledger()
        self._healthy(ledger, source="ucb_urap_projects", when=NOW, n=12)
        empty_at = NOW + timedelta(days=7)
        row = sh.record_attempt(
            ledger, source="ucb_urap_projects", school="ucb",
            outcome=sh.VALID_ZERO, emitted=0, baseline=12, now=empty_at,
        )
        assert row["last_success_at"] == empty_at.isoformat()
        assert row["last_nonzero_at"] == NOW.isoformat()
        row = sh.record_attempt(
            ledger, source="ucb_urap_projects", school="ucb",
            outcome=sh.FAILED, emitted=None, baseline=12, now=empty_at + timedelta(days=7),
        )
        assert row["last_nonzero_at"] == NOW.isoformat()
        recovered = empty_at + timedelta(days=14)
        row = self._healthy(ledger, source="ucb_urap_projects", when=recovered, n=9)
        assert row["last_nonzero_at"] == recovered.isoformat()
        [shown] = sh.source_rows(ledger, recovered, eligible=frozenset())
        assert shown["last_nonzero_at"] == recovered.isoformat()

    def test_a_success_that_emitted_nothing_is_not_a_nonzero_run(self):
        ledger = sh.empty_ledger()
        row = sh.record_attempt(
            ledger, source="colgate_faculty", school="colgate",
            outcome=sh.SUCCESS_NONZERO, emitted=0, baseline=0, now=NOW,
        )
        assert row["last_nonzero_at"] is None

    def test_a_row_recorded_before_the_field_answers_from_its_status(self):
        """A healthy outcome stamps status and last_success_at together, so a
        row whose latest outcome was a nonzero success already says when the
        source last produced records. Any other older row does not know."""
        earlier = (NOW - timedelta(days=30)).isoformat()
        ledger = {"schema_version": sh.SCHEMA_VERSION, "shards": {}, "sources": {
            "caltech_external_research": {"school": None, "status": sh.SUCCESS_NONZERO,
                                          "last_attempt_at": earlier, "last_success_at": earlier},
            "ucb_ling_faculty": {"school": "ucb", "status": sh.FAILED, "last_attempt_at": earlier,
                                 "last_success_at": earlier},
        }}
        shown = {row["source"]: row for row in sh.source_rows(ledger, NOW, eligible=frozenset())}
        assert shown["caltech_external_research"]["last_nonzero_at"] == earlier
        assert shown["ucb_ling_faculty"]["last_nonzero_at"] is None
        row = sh.record_attempt(
            ledger, source="caltech_external_research", school=None,
            outcome=sh.SUSPICIOUS_ZERO, emitted=0, baseline=14, now=NOW,
        )
        assert row["last_nonzero_at"] == earlier
        row = sh.record_attempt(
            ledger, source="ucb_ling_faculty", school="ucb",
            outcome=sh.VALID_ZERO, emitted=0, baseline=0, now=NOW,
        )
        assert row["last_nonzero_at"] is None


# -------------------------------------------------------- school aggregation --
def _ledger_with(rows: dict[str, tuple[str, int, str]]) -> dict:
    """rows: {source: (school, days_since_success, status)}."""
    ledger = sh.empty_ledger()
    for source, (school, age_days, status) in rows.items():
        sh.record_attempt(
            ledger, source=source, school=school,
            outcome=(
                sh.SUCCESS_NONZERO if status == sh.SUCCESS_NONZERO else status
            ),
            emitted=10 if status == sh.SUCCESS_NONZERO else 0,
            baseline=10, now=NOW - timedelta(days=age_days),
        )
        if status not in sh.HEALTHY_OUTCOMES:
            # A degraded row still has to carry a last_success_at from before,
            # or it would be "unknown" rather than "stale".
            ledger["sources"][source]["last_success_at"] = (
                NOW - timedelta(days=age_days)
            ).isoformat()
    return ledger


ALL = None  # explicit "count every row", bypassing the monitored-source gate


class TestSchoolAggregation:
    def test_one_stale_department_does_not_make_the_school_fully_stale(self):
        ledger = _ledger_with({
            "ucb_eecs_faculty": ("ucb", 2, sh.SUCCESS_NONZERO),
            "ucb_math_faculty": ("ucb", 2, sh.SUCCESS_NONZERO),
            "ucb_ling_faculty": ("ucb", 44, sh.SUSPICIOUS_ZERO),
        })
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["fully_stale"] is False
        assert school["state"] == "partially_degraded"
        assert school["fresh_shard_count"] == 2
        assert school["stale_shard_count"] == 1
        assert school["degraded_shard_count"] == 1
        assert school["total_shard_count"] == 3
        assert school["oldest_stale_age_days"] == pytest.approx(44, abs=0.1)

    def test_every_source_stale_makes_the_school_fully_stale(self):
        ledger = _ledger_with({
            "colgate_faculty": ("colgate", 36, sh.SUSPICIOUS_ZERO),
            "campus_graph:colgate": ("colgate", 42, sh.SUSPICIOUS_ZERO),
        })
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["fully_stale"] is True
        assert school["state"] == "fully_stale"
        assert school["fresh_shard_count"] == 0

    def test_all_fresh_is_fully_fresh(self):
        ledger = _ledger_with({
            "yale_faculty": ("yale", 3, sh.SUCCESS_NONZERO),
            "campus_graph:yale": ("yale", 3, sh.SUCCESS_NONZERO),
        })
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["state"] == "fully_fresh"
        assert school["fully_stale"] is False

    def test_a_fresh_publish_cannot_clear_a_fully_stale_school(self):
        """Republishing a shard rebuilt from retained records is not a
        refresh, and must not read as one."""
        ledger = _ledger_with({
            "colgate_faculty": ("colgate", 36, sh.SUSPICIOUS_ZERO),
        })
        sh.record_publish(ledger, shards={"colgate": 323}, now=NOW)
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["last_publish_at"] == NOW.isoformat()
        assert school["fully_stale"] is True

    def test_school_reports_its_oldest_success_and_coverage_change(self):
        """The newest success alone is one healthy department hiding a dead
        one, so the row also carries the oldest success and what the
        degraded sources no longer confirm."""
        ledger = _ledger_with({
            "ucb_eecs_faculty": ("ucb", 2, sh.SUCCESS_NONZERO),
            "ucb_ling_faculty": ("ucb", 44, sh.SUSPICIOUS_ZERO),
        })
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["last_successful_school_activity"] == (
            NOW - timedelta(days=2)).isoformat()
        assert school["oldest_success_at"] == (
            NOW - timedelta(days=44)).isoformat()
        assert school["never_succeeded_shard_count"] == 0
        # eecs emitted its 10 again; ling emitted 0 of the 10 seeded as its
        # last good count from the corpus baseline.
        assert school["coverage_current_count"] == 10
        assert school["coverage_last_good_count"] == 20
        assert school["coverage_delta"] == -10

    def test_a_never_successful_source_leaves_no_oldest_success(self):
        ledger = _ledger_with({
            "ucb_eecs_faculty": ("ucb", 2, sh.SUCCESS_NONZERO),
        })
        # Failed with no usable count, no last good count and no success:
        # it is measured against its baseline and counted as never succeeded.
        ledger["sources"]["ucb_ling_faculty"] = {
            "school": "ucb", "status": sh.FAILED, "current_count": None,
            "baseline_count": 5, "last_good_count": None,
            "last_success_at": None,
        }
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["oldest_success_at"] is None
        assert school["never_succeeded_shard_count"] == 1
        assert school["last_successful_school_activity"] == (
            NOW - timedelta(days=2)).isoformat()
        assert school["coverage_current_count"] == 10
        assert school["coverage_last_good_count"] == 15
        assert school["coverage_delta"] == -5

    def test_a_healthy_latest_attempt_adds_nothing_to_the_coverage_change(self):
        """Neither a corpus baseline nor an older last good count may turn a
        healthy attempt into lost coverage."""
        ledger = _ledger_with({
            "ucb_eecs_faculty": ("ucb", 2, sh.SUCCESS_NONZERO),
        })
        # Healthy with no last good count on record, measured before against
        # the 12 records the corpus held.
        ledger["sources"]["ucb_math_faculty"] = {
            "school": "ucb", "status": sh.SUCCESS_NONZERO, "current_count": 4,
            "baseline_count": 12, "last_good_count": None,
            "last_success_at": (NOW - timedelta(days=1)).isoformat(),
        }
        # Healthy with no usable count, measured before against its last 30.
        ledger["sources"]["ucb_ling_faculty"] = {
            "school": "ucb", "status": sh.VALID_ZERO, "current_count": None,
            "baseline_count": 30, "last_good_count": 30,
            "last_success_at": (NOW - timedelta(days=1)).isoformat(),
        }
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["coverage_current_count"] == 14
        assert school["coverage_last_good_count"] == 14
        assert school["coverage_delta"] == 0

    def test_corpus_report_counts_states_and_names_stale_schools(self):
        ledger = _ledger_with({
            "ucb_eecs_faculty": ("ucb", 2, sh.SUCCESS_NONZERO),
            "ucb_ling_faculty": ("ucb", 44, sh.SUSPICIOUS_ZERO),
            "colgate_faculty": ("colgate", 36, sh.SUSPICIOUS_ZERO),
            "yale_faculty": ("yale", 1, sh.SUCCESS_NONZERO),
        })
        report = sh.corpus_report(ledger, NOW, ALL)
        assert report["school_count"] == 3
        assert report["fully_fresh_school_count"] == 1
        assert report["partially_degraded_school_count"] == 1
        assert report["fully_stale_school_count"] == 1
        assert report["fully_stale_schools"] == ["colgate"]
        assert report["stale_shard_count"] == 2

    def test_fresh_campus_programs_do_not_stand_in_for_a_dead_faculty_roster(self):
        """Barnard once its campus check succeeds again. On the 2026-10-17
        ledger barnard_faculty had parsed zero rows since 08-29 and
        campus_graph:barnard had not succeeded since 08-29 either, so
        fully_stale already named the school; one fresh campus check would
        have cleared that while the roster stayed at zero."""
        ledger = _ledger_with({
            "barnard_faculty": ("barnard", 50, sh.SUSPICIOUS_ZERO),
            "campus_graph:barnard": ("barnard", 1, sh.SUCCESS_NONZERO),
        })
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["fully_stale"] is False
        assert school["no_fresh_faculty"] is True
        assert school["faculty_shard_count"] == 1
        assert school["fresh_faculty_shard_count"] == 0
        report = sh.corpus_report(ledger, NOW, ALL)
        assert report["fully_stale_schools"] == []
        assert report["no_fresh_faculty_schools"] == ["barnard"]
        assert report["no_fresh_faculty_school_count"] == 1

    def test_a_zero_row_faculty_run_is_no_fresh_faculty_inside_the_window(self):
        """A zero keeps the last success, so the source still reads fresh."""
        ledger = _ledger_with({
            "swarthmore_faculty": ("swarthmore", 3, sh.SUSPICIOUS_ZERO),
            "campus_graph:swarthmore": ("swarthmore", 1, sh.SUCCESS_NONZERO),
        })
        rows = {r["source"]: r for r in sh.source_rows(ledger, NOW, ALL)}
        assert rows["swarthmore_faculty"]["freshness"] == "fresh"
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["no_fresh_faculty"] is True

    def test_one_faculty_source_with_fresh_rows_is_enough(self):
        ledger = _ledger_with({
            "ucb_ling_faculty": ("ucb", 44, sh.SUSPICIOUS_ZERO),
            "ucb_eecs_faculty": ("ucb", 2, sh.SUCCESS_NONZERO),
            "nsf_reu": ("national", 4, sh.SUCCESS_NONZERO),
        })
        schools = {s["school"]: s for s in sh.school_rows(ledger, NOW, ALL)}
        assert schools["ucb"]["no_fresh_faculty"] is False
        assert schools["ucb"]["fresh_faculty_shard_count"] == 1
        # A shard with no faculty source has nothing to judge.
        assert schools["national"]["faculty_shard_count"] == 0
        assert schools["national"]["no_fresh_faculty"] is False

    def test_a_faculty_run_deferred_by_the_run_clock_is_judged_by_its_last_success(self):
        """refresh_all records a source deferred at the run time budget as
        failed with no count. Yale's only faculty source found 1,500
        professors 8 days ago and was deferred yesterday: those records are
        still fresh, and a missing count is not zero rows."""
        ledger = sh.empty_ledger()
        sh.record_attempt(
            ledger, source="yale_faculty", school="yale",
            outcome=sh.SUCCESS_NONZERO, emitted=1500, baseline=1500,
            now=NOW - timedelta(days=8))
        sh.record_attempt(
            ledger, source="yale_faculty", school="yale", outcome=sh.FAILED,
            emitted=None, baseline=1500, now=NOW - timedelta(days=1),
            failure_reason="stopped at the run time budget (deferred_deadline)")
        sh.record_attempt(
            ledger, source="campus_graph:yale", school="yale",
            outcome=sh.SUCCESS_NONZERO, emitted=12, baseline=12,
            now=NOW - timedelta(days=1))
        rows = {r["source"]: r for r in sh.source_rows(ledger, NOW, ALL)}
        assert rows["yale_faculty"]["current_record_count"] is None
        assert rows["yale_faculty"]["freshness"] == "fresh"
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["no_fresh_faculty"] is False
        assert school["fresh_faculty_shard_count"] == 1

    def test_a_faculty_run_that_raised_before_counting_is_judged_by_its_last_success(self):
        """A collector that raises leaves ``{"status": "error"}`` with no
        ``fetched``, so the ledger holds no count. Inside the stale bound the
        school keeps its faculty; past it, the missing count keeps nothing
        alive."""
        ledger = sh.empty_ledger()
        for school, age in (("nyu", 5), ("utah", 20)):
            sh.record_attempt(
                ledger, source=f"{school}_faculty", school=school,
                outcome=sh.SUCCESS_NONZERO, emitted=900, baseline=900,
                now=NOW - timedelta(days=age))
            sh.record_attempt(
                ledger, source=f"{school}_faculty", school=school,
                outcome=sh.FAILED, emitted=None, baseline=900,
                now=NOW - timedelta(days=1),
                failure_reason="ReadTimeout: the listing page timed out")
        schools = {s["school"]: s for s in sh.school_rows(ledger, NOW, ALL)}
        assert schools["nyu"]["no_fresh_faculty"] is False
        assert schools["utah"]["no_fresh_faculty"] is True

    def test_rows_from_a_stale_faculty_source_do_not_count(self):
        """A run that fails with rows (refresh_all records the ``fetched`` of
        an error or partial run) keeps the source's old last success. Past
        the stale bound those rows prove nothing, however fresh the campus
        check beside them."""
        ledger = sh.empty_ledger()
        sh.record_attempt(
            ledger, source="barnard_faculty", school="barnard",
            outcome=sh.SUCCESS_NONZERO, emitted=212, baseline=212,
            now=NOW - timedelta(days=30))
        sh.record_attempt(
            ledger, source="barnard_faculty", school="barnard",
            outcome=sh.FAILED, emitted=40, baseline=212,
            now=NOW - timedelta(days=1),
            failure_reason="Source check incomplete: list_pages_failed")
        sh.record_attempt(
            ledger, source="campus_graph:barnard", school="barnard",
            outcome=sh.SUCCESS_NONZERO, emitted=9, baseline=9,
            now=NOW - timedelta(days=1))
        rows = {r["source"]: r for r in sh.source_rows(ledger, NOW, ALL)}
        assert rows["barnard_faculty"]["current_record_count"] == 40
        assert rows["barnard_faculty"]["freshness"] == "stale"
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["fully_stale"] is False
        assert school["no_fresh_faculty"] is True

    def test_a_faculty_source_in_the_warn_band_still_delivers(self):
        """10 to 17 days is ``warn``, one missed weekly slot, which already
        keeps a school out of fully_stale. uiuc_faculty sat there on
        2026-10-18: last success 3,790 rows on 10-05, then failed with 3,731
        rows on 10-12 over two empty departments."""
        ledger = sh.empty_ledger()
        sh.record_attempt(
            ledger, source="uiuc_faculty", school="uiuc",
            outcome=sh.SUCCESS_NONZERO, emitted=3790, baseline=3304,
            now=NOW - timedelta(days=13))
        sh.record_attempt(
            ledger, source="uiuc_faculty", school="uiuc", outcome=sh.FAILED,
            emitted=3731, baseline=3305, now=NOW - timedelta(days=6),
            failure_reason=(
                "empty departments: ['Department of Atmospheric Sciences', "
                "'Department of Earth Science & Environmental Change']"))
        rows = {r["source"]: r for r in sh.source_rows(ledger, NOW, ALL)}
        assert rows["uiuc_faculty"]["freshness"] == "warn"
        school = sh.school_rows(ledger, NOW, ALL)[0]
        assert school["no_fresh_faculty"] is False
        assert school["fresh_faculty_shard_count"] == 1

    def test_unscheduled_sources_are_shown_but_never_counted_stale(self):
        """``manual`` seeds are carried data, not weekly producers. Judging
        them on a weekly clock reported the national shard permanently
        degraded."""
        ledger = _ledger_with({
            "nsf_reu": ("national", 4, sh.SUCCESS_NONZERO),
            "manual": ("national", 163, sh.SUCCESS_NONZERO),
        })
        eligible = monitored_sources()
        assert "nsf_reu" in eligible
        assert "manual" not in eligible

        rows = {r["source"]: r for r in sh.source_rows(ledger, NOW, eligible)}
        assert rows["manual"]["eligible"] is False
        assert rows["manual"]["freshness"] == "stale"   # shown honestly

        school = sh.school_rows(ledger, NOW, eligible)[0]
        assert school["state"] == "fully_fresh"
        assert school["total_shard_count"] == 1

    def test_open_campus_programs_are_judged_like_the_other_national_producers(self):
        """The national refresh collects the ``*_external_research`` programs
        now. Exempted as carried data, they had no scheduled refresh after
        2026-08-09 and nothing counted them stale."""
        ledger = _ledger_with({
            "nsf_reu": ("national", 4, sh.SUCCESS_NONZERO),
            "ucb_external_research": ("national", 47, sh.SUCCESS_NONZERO),
            "stanford_external_research": ("national", 71, sh.SUCCESS_NONZERO),
        })
        eligible = monitored_sources()
        school = sh.school_rows(ledger, NOW, eligible)[0]
        assert school["state"] == "partially_degraded"
        assert school["stale_shard_count"] == 2
        assert school["total_shard_count"] == 3


# ------------------------------------------------- public school freshness --
OCT18 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _attempt(ledger, source, school, outcome, emitted, at, baseline=0, reason=None):
    sh.record_attempt(
        ledger, source=source, school=school, outcome=outcome, emitted=emitted,
        baseline=baseline, now=at, failure_reason=reason)


def _committed_like_ledger() -> dict:
    """The shapes the 2026-10-17 committed ledger holds for these schools.

    Swarthmore's site has turned the runner away since 09-05 and Barnard's
    rosters moved on 08-29: every source of both has kept failing since.
    UIUC's roster missed two departments in its latest run. ucd's only
    collector is declared unsupported, so nothing of it is monitored.
    """
    ledger = sh.empty_ledger()
    sept5 = datetime(2026, 9, 5, 3, 45, 0, 802770, tzinfo=UTC)
    aug29 = datetime(2026, 8, 29, 8, 10, 26, 800836, tzinfo=UTC)
    oct17 = datetime(2026, 10, 17, 13, 30, 52, tzinfo=UTC)
    for school, last in (("swarthmore", sept5), ("barnard", aug29)):
        _attempt(ledger, f"{school}_faculty", school, sh.SUCCESS_NONZERO, 224, last, 224)
        _attempt(ledger, f"campus_graph:{school}", school, sh.SUCCESS_NONZERO, 9,
                 last - timedelta(hours=2))
        _attempt(ledger, f"{school}_faculty", school, sh.SUSPICIOUS_ZERO, 0, oct17, 231)
        _attempt(ledger, f"campus_graph:{school}", school, sh.FAILED, 9, oct17,
                 reason="Source check incomplete: seed_pages_failed")
    _attempt(ledger, "uiuc_faculty", "uiuc", sh.SUCCESS_NONZERO, 3790,
             datetime(2026, 10, 5, 16, 24, 8, tzinfo=UTC), 3304)
    _attempt(ledger, "uiuc_faculty", "uiuc", sh.FAILED, 3731,
             datetime(2026, 10, 12, 19, 13, 14, tzinfo=UTC), 3305,
             reason="empty departments: ['Department of Atmospheric Sciences']")
    _attempt(ledger, "uiuc_our_rss", "uiuc", sh.SUCCESS_NONZERO, 25,
             datetime(2026, 10, 12, 19, 13, 14, 49438, tzinfo=UTC), 17)
    _attempt(ledger, "yale_faculty", "yale", sh.SUCCESS_NONZERO, 1500, oct17, 1500)
    _attempt(ledger, "campus_graph:yale", "yale", sh.SUCCESS_NONZERO, 12, oct17, 12)
    _attempt(ledger, "campus_graph:ucd", "ucd", sh.SUCCESS_NONZERO, 7,
             datetime(2026, 7, 21, 12, 34, 51, tzinfo=UTC), 7)
    _attempt(ledger, "nsf_reu", "national", sh.SUCCESS_NONZERO, 300, oct17, 300)
    return ledger


class TestPublicSchoolFreshness:
    def test_a_school_whose_site_refuses_the_runner_is_stale_with_its_real_date(self):
        public = sh.public_school_freshness(
            _committed_like_ledger(), OCT18, monitored_sources())
        assert public["swarthmore"] == {
            "last_checked_at": "2026-09-05T03:45:00+00:00", "status": sh.PUBLIC_STALE}
        assert public["barnard"] == {
            "last_checked_at": "2026-08-29T08:10:26+00:00", "status": sh.PUBLIC_STALE}

    def test_a_fresh_campus_check_does_not_lift_a_school_whose_roster_is_empty(self):
        """The gate's faculty rule, not only fully_stale: Barnard once its
        campus check works again while every roster still parses zero."""
        ledger = _committed_like_ledger()
        _attempt(ledger, "campus_graph:barnard", "barnard", sh.SUCCESS_NONZERO, 9,
                 OCT18 - timedelta(hours=3))
        row = next(r for r in sh.school_rows(ledger, OCT18, monitored_sources())
                   if r["school"] == "barnard")
        assert row["fully_stale"] is False and row["no_fresh_faculty"] is True
        public = sh.public_school_freshness(ledger, OCT18, monitored_sources())
        assert public["barnard"] == {
            "last_checked_at": (OCT18 - timedelta(hours=3)).isoformat(),
            "status": sh.PUBLIC_STALE,
        }

    def test_a_school_with_one_failing_source_is_partly_unchecked(self):
        public = sh.public_school_freshness(
            _committed_like_ledger(), OCT18, monitored_sources())
        # The newest success among its sources, not the failed roster's.
        assert public["uiuc"] == {
            "last_checked_at": "2026-10-12T19:13:14+00:00",
            "status": sh.PUBLIC_PARTLY_UNCHECKED,
        }
        assert public["yale"] == {
            "last_checked_at": "2026-10-17T13:30:52+00:00", "status": sh.PUBLIC_CURRENT}

    def test_a_source_past_the_stale_bound_alone_makes_a_school_partly_unchecked(self):
        ledger = _committed_like_ledger()
        _attempt(ledger, "campus_graph:yale", "yale", sh.SUCCESS_NONZERO, 12,
                 OCT18 - timedelta(days=30), 12)
        public = sh.public_school_freshness(ledger, OCT18, monitored_sources())
        assert public["yale"]["status"] == sh.PUBLIC_PARTLY_UNCHECKED

    def test_a_school_with_no_monitored_source_and_the_national_pool_are_absent(self):
        public = sh.public_school_freshness(
            _committed_like_ledger(), OCT18, monitored_sources())
        assert "ucd" not in public
        assert "national" not in public
        assert set(public) == {"swarthmore", "barnard", "uiuc", "yale"}

    def test_a_school_that_never_succeeded_is_stale_without_a_date(self):
        ledger = sh.empty_ledger()
        _attempt(ledger, "yale_faculty", "yale", sh.FAILED, None, OCT18, 0,
                 reason="ReadTimeout")
        public = sh.public_school_freshness(ledger, OCT18, monitored_sources())
        assert public == {"yale": {"last_checked_at": None, "status": sh.PUBLIC_STALE}}

    def test_nothing_about_an_individual_source_leaves(self):
        public = sh.public_school_freshness(
            _committed_like_ledger(), OCT18, monitored_sources())
        assert all(set(entry) == {"last_checked_at", "status"} for entry in public.values())
        text = json.dumps(public)
        for leaked in ("faculty", "campus_graph", "seed_pages_failed", "Atmospheric", "3731"):
            assert leaked not in text

    def test_the_answer_holds_until_the_first_source_crosses_a_bound(self):
        """A ledger nobody rewrites still ages: yale_faculty, the school's one
        roster, goes stale 17 days after its last success, and an answer
        computed before then must not outlive it."""
        ledger = sh.empty_ledger()
        last = OCT18 - timedelta(days=16)
        _attempt(ledger, "yale_faculty", "yale", sh.SUCCESS_NONZERO, 1500, last, 1500)
        _attempt(ledger, "campus_graph:yale", "yale", sh.SUCCESS_NONZERO, 12, OCT18, 12)
        eligible = monitored_sources()
        warn_days, stale_days = sh.staleness_thresholds()
        change = sh.next_freshness_change(ledger, OCT18, eligible)
        assert change == last + timedelta(days=stale_days)
        before = sh.public_school_freshness(ledger, change, eligible)
        after = sh.public_school_freshness(ledger, change + timedelta(seconds=1), eligible)
        assert before["yale"]["status"] == sh.PUBLIC_CURRENT
        assert after["yale"]["status"] == sh.PUBLIC_STALE
        # The campus check's own warn bound is the next change after that.
        assert sh.next_freshness_change(
            ledger, change + timedelta(seconds=1), eligible) == OCT18 + timedelta(days=warn_days)

    def test_an_answer_computed_at_a_bound_ends_at_that_bound(self):
        """A source exactly at its stale bound still reads warn and turns stale
        the moment after, so the answer computed then must not be valid until
        the next bound: it would keep the school current for days."""
        ledger = sh.empty_ledger()
        _attempt(ledger, "yale_faculty", "yale", sh.SUCCESS_NONZERO, 1500,
                 OCT18 - timedelta(days=16), 1500)
        _attempt(ledger, "campus_graph:yale", "yale", sh.SUCCESS_NONZERO, 12, OCT18, 12)
        eligible = monitored_sources()
        bound = sh.next_freshness_change(ledger, OCT18, eligible)
        assert sh.public_school_freshness(ledger, bound, eligible)["yale"]["status"] == (
            sh.PUBLIC_CURRENT)
        assert sh.next_freshness_change(ledger, bound, eligible) == bound

    def test_a_school_turns_stale_by_age_alone_with_no_failed_attempt(self):
        """When refreshes stop, nothing fails: each source's latest attempt
        succeeded, and the school is stale once that success is older than
        the stale bound. So the public hint may say the professor pages have
        no recent successful read, never that a check failed
        (SchoolFreshnessNote.test.tsx, "stale by age alone")."""
        ledger = sh.empty_ledger()
        last = OCT18 - timedelta(days=20)
        _attempt(ledger, "yale_faculty", "yale", sh.SUCCESS_NONZERO, 1500, last, 1500)
        _attempt(ledger, "campus_graph:yale", "yale", sh.SUCCESS_NONZERO, 12, last, 12)
        assert all(row["status"] == sh.SUCCESS_NONZERO and row["consecutive_failures"] == 0
                   for row in ledger["sources"].values())
        public = sh.public_school_freshness(ledger, OCT18, monitored_sources())
        assert public["yale"] == {
            "last_checked_at": last.isoformat(timespec="seconds"), "status": sh.PUBLIC_STALE}

    def test_a_source_never_read_successfully_leaves_its_school_partly_unchecked(self):
        """Unknown, not recently failed: the one attempt on record for the
        campus check is 40 days old. The hint may say some pages lack a recent
        successful read, never that recent checks failed."""
        ledger = sh.empty_ledger()
        _attempt(ledger, "yale_faculty", "yale", sh.SUCCESS_NONZERO, 1500,
                 OCT18 - timedelta(days=1), 1500)
        _attempt(ledger, "campus_graph:yale", "yale", sh.SUSPICIOUS_ZERO, 0,
                 OCT18 - timedelta(days=40))
        eligible = monitored_sources()
        campus = next(r for r in sh.source_rows(ledger, OCT18, eligible)
                      if r["source"] == "campus_graph:yale")
        assert campus["freshness"] == "unknown"
        assert sh.public_school_freshness(ledger, OCT18, eligible)["yale"] == {
            "last_checked_at": (OCT18 - timedelta(days=1)).isoformat(),
            "status": sh.PUBLIC_PARTLY_UNCHECKED,
        }

    def test_a_campus_check_dates_a_school_stale_behind_a_deferred_roster_run(self):
        """Amherst in the ledger committed on 2026-10-05 (3886a6f2), read the
        next day: its campus page was read on Oct 5, the date the school shows,
        while its roster last succeeded on Aug 31 and the Oct 5 roster run was
        deferred by the run clock before it counted anything. So the stale hint
        may say the professor pages have no recent successful read, never
        anything tied to that date (SchoolFreshnessNote.test.tsx, "a date a
        campus page set")."""
        ledger = sh.empty_ledger()
        run = datetime(2026, 10, 5, 16, 24, 8, 608, tzinfo=UTC)
        now = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)
        _attempt(ledger, "amherst_faculty", "amherst", sh.SUCCESS_NONZERO, 266,
                 datetime(2026, 8, 31, 8, 38, 37, 634438, tzinfo=UTC), 266)
        _attempt(ledger, "amherst_faculty", "amherst", sh.FAILED, None, run, 266,
                 reason="stopped at the run time budget (deferred_deadline)")
        _attempt(ledger, "campus_graph:amherst", "amherst", sh.SUCCESS_NONZERO, 9, run)
        eligible = monitored_sources()
        roster = next(r for r in sh.source_rows(ledger, now, eligible)
                      if r["source"] == "amherst_faculty")
        assert roster["current_record_count"] is None
        assert roster["freshness"] == "stale"
        assert roster["last_success_at"].startswith("2026-08-31")
        row = next(r for r in sh.school_rows(ledger, now, eligible)
                   if r["school"] == "amherst")
        assert row["fully_stale"] is False and row["no_fresh_faculty"] is True
        assert sh.public_school_freshness(ledger, now, eligible)["amherst"] == {
            "last_checked_at": "2026-10-05T16:24:08+00:00", "status": sh.PUBLIC_STALE}

    def test_a_read_that_brought_records_back_and_failed_leaves_its_school_partly_unchecked(self):
        """A read can bring records back and still fail: Brown's campus check
        on Oct 15 (ledger f9f8df7f) emitted four records and was judged failed
        because the check was incomplete. Its last success is put five days
        before that run here, so age alone would not qualify the school; the
        failed read does. So the hint may say some pages lack a recent
        successful read, never that they have not been read
        (SchoolFreshnessNote.test.tsx, "brought records back and still failed")."""
        ledger = sh.empty_ledger()
        run = OCT18 - timedelta(days=3)
        _attempt(ledger, "brown_faculty", "brown", sh.SUCCESS_NONZERO, 1169, run, 1206)
        _attempt(ledger, "campus_graph:brown", "brown", sh.SUCCESS_NONZERO, 4,
                 OCT18 - timedelta(days=8))
        _attempt(ledger, "campus_graph:brown", "brown", sh.FAILED, 4, run, 4,
                 reason="Source check incomplete: condition_capture_failed, seed_pages_failed")
        eligible = monitored_sources()
        campus = next(r for r in sh.source_rows(ledger, OCT18, eligible)
                      if r["source"] == "campus_graph:brown")
        assert campus["status"] == sh.FAILED and campus["current_record_count"] == 4
        assert campus["last_attempt_at"] == run.isoformat()
        assert campus["freshness"] == "fresh"
        assert sh.public_school_freshness(ledger, OCT18, eligible)["brown"] == {
            "last_checked_at": run.isoformat(), "status": sh.PUBLIC_PARTLY_UNCHECKED}

    def test_no_change_is_due_once_every_bound_has_passed_or_the_source_is_unmonitored(self):
        ledger = sh.empty_ledger()
        _attempt(ledger, "yale_faculty", "yale", sh.SUCCESS_NONZERO, 1500,
                 OCT18 - timedelta(days=40), 1500)
        _attempt(ledger, "campus_graph:ucd", "ucd", sh.SUCCESS_NONZERO, 7, OCT18, 7)
        assert sh.next_freshness_change(ledger, OCT18, monitored_sources()) is None


class TestLedgerIO:
    def test_absent_ledger_reads_as_empty(self, tmp_path):
        assert sh.load_ledger(tmp_path / "nope.json") == sh.empty_ledger()

    def test_corrupt_ledger_reads_as_empty(self, tmp_path):
        path = tmp_path / "source_health.json"
        path.write_text("{not json", encoding="utf-8")
        assert sh.load_ledger(path) == sh.empty_ledger()

    def test_foreign_schema_is_not_merged_into(self, tmp_path):
        """Guessing at a future shape could overwrite an earned
        last_success_at with a fabricated one."""
        path = tmp_path / "source_health.json"
        path.write_text(
            json.dumps({"schema_version": 99, "sources": {"x": {}}}),
            encoding="utf-8",
        )
        assert sh.load_ledger(path)["sources"] == {}

    def test_round_trip(self, tmp_path):
        path = tmp_path / "source_health.json"
        ledger = sh.empty_ledger()
        sh.record_attempt(
            ledger, source="a_faculty", school="a",
            outcome=sh.SUCCESS_NONZERO, emitted=3, baseline=3, now=NOW,
        )
        sh.save_ledger(ledger, path)
        assert sh.load_ledger(path)["sources"]["a_faculty"]["last_success_at"]

    def test_thresholds_reject_nonsense_and_keep_warn_below_stale(
        self, monkeypatch,
    ):
        monkeypatch.setenv("OFE_SOURCE_WARN_DAYS", "0")
        monkeypatch.setenv("OFE_SOURCE_STALE_DAYS", "-3")
        warn, stale = sh.staleness_thresholds()
        assert warn == 10.0 and stale == 17.0
        monkeypatch.setenv("OFE_SOURCE_WARN_DAYS", "40")
        monkeypatch.setenv("OFE_SOURCE_STALE_DAYS", "20")
        warn, stale = sh.staleness_thresholds()
        assert warn <= stale

    def test_baselines_ignore_retired_records(self):
        """A source whose records were all retired has no live output to lose;
        counting retired rows would keep it permanently suspicious."""
        opps = [
            {"source": "s", "metadata": {"is_active": True}},
            {"source": "s", "metadata": {"is_active": False}},
            {"source": "t", "metadata": {}},
        ]
        assert sh.active_baselines(opps) == {"s": 1, "t": 1}


# --------------------------------------------------------- publish isolation --
def _ucb_summary(**overrides: dict) -> tuple[dict, dict]:
    """A complete, healthy deep UCB run summary, plus its policy set."""
    policies = expected_sources({"ucb"}, national=False, deep=True)
    sources: dict[str, dict] = {}
    for key in policies:
        sources[key] = {"fetched": 25, "new": 0, "updated": 25, "status": "ok"}
        if key == "ucb_campus" or key.startswith("campus_graph:"):
            sources[key].update({
                "live_pages_attempted": 10, "live_pages_loaded": 10,
                "crawl_sources_expected": 3, "crawl_sources_loaded": 3,
                "seed_pages_expected": 5, "seed_pages_loaded": 5,
                "seed_pages_failed": 0,
            })
    sources.update(overrides)
    summary = {
        "request": {"schools": ["ucb"], "national": False, "deep": True},
        "shard": {"schools": ["ucb"], "national": False},
        "sources": sources,
    }
    return summary, policies


def _verdict(summary: dict) -> dict:
    return evaluate_refresh_summary(
        summary, schools={"ucb"}, national=False, deep=True,
        require_tracking=False,
    )


class TestPublishIsolation:
    def test_healthy_school_publishes(self):
        summary, _ = _ucb_summary()
        verdict = _verdict(summary)
        assert verdict["ready"] is True
        assert verdict["publishable"] == ["ucb"]

    def test_one_suspicious_zero_department_does_not_veto_its_school(self):
        """THE regression. This verdict used to be blocked, which withheld all
        3,106 UC Berkeley records for 44 days."""
        summary, _ = _ucb_summary(ucb_ling_faculty={
            "fetched": 0, "new": 0, "updated": 0,
            "status": "suspicious_zero", "suspicious_zero_baseline": 17,
        })
        verdict = _verdict(summary)
        assert verdict["ready"] is True
        assert verdict["publishable"] == ["ucb"]
        assert verdict["by_unit"]["ucb"]["ready"] is True
        assert verdict["reasons"] == []

    def test_the_suspicious_zero_is_still_reported_as_a_degradation(self):
        """Narrowing the blast radius must not silence the failure."""
        summary, _ = _ucb_summary(ucb_ling_faculty={
            "fetched": 0, "new": 0, "updated": 0,
            "status": "suspicious_zero", "suspicious_zero_baseline": 17,
        })
        verdict = _verdict(summary)
        assert verdict["status"] == "degraded"
        degradation = next(
            d for d in verdict["degradations"]
            if d["source"] == "ucb_ling_faculty"
        )
        assert degradation["kind"] == "suspicious_zero"
        assert "17" in degradation["detail"]
        assert any("ucb_ling_faculty" in w for w in verdict["warnings"])

    def test_two_failing_departments_still_do_not_veto_the_school(self):
        summary, _ = _ucb_summary(
            ucb_ling_faculty={
                "fetched": 0, "new": 0, "updated": 0,
                "status": "suspicious_zero", "suspicious_zero_baseline": 17,
            },
            ucb_pmb_faculty={
                "fetched": 0, "new": 0, "updated": 0,
                "status": "suspicious_zero", "suspicious_zero_baseline": 31,
            },
        )
        verdict = _verdict(summary)
        assert verdict["publishable"] == ["ucb"]
        assert len([
            d for d in verdict["degradations"]
            if d["kind"] == "suspicious_zero"
        ]) == 2

    def test_a_real_collector_error_still_blocks_its_school(self):
        """Only the ZERO case is reclassified. An error means what we would
        publish may be WRONG, which is an accuracy failure, not a coverage
        one — that still fails closed."""
        summary, _ = _ucb_summary(ucb_ling_faculty={
            "status": "error", "error": "SSLError: handshake failed",
        })
        verdict = _verdict(summary)
        assert verdict["ready"] is False
        assert verdict["publishable"] == []
        assert any("ucb_ling_faculty" in r for r in verdict["reasons"])

    def test_an_error_in_one_school_leaves_another_school_publishable(self):
        policies = expected_sources({"ucb", "yale"}, national=False, deep=True)
        sources = {}
        for key in policies:
            sources[key] = {"fetched": 25, "new": 0, "updated": 25, "status": "ok"}
            if key == "ucb_campus" or key.startswith("campus_graph:"):
                sources[key].update({
                    "live_pages_attempted": 10, "live_pages_loaded": 10,
                    "crawl_sources_expected": 3, "crawl_sources_loaded": 3,
                    "seed_pages_expected": 5, "seed_pages_loaded": 5,
                    "seed_pages_failed": 0,
                })
        sources["ucb_ling_faculty"] = {"status": "error", "error": "boom"}
        verdict = evaluate_refresh_summary(
            {
                "request": {
                    "schools": ["ucb", "yale"], "national": False, "deep": True,
                },
                "shard": {"schools": ["ucb", "yale"], "national": False},
                "sources": sources,
            },
            schools={"ucb", "yale"}, national=False, deep=True,
            require_tracking=False,
        )
        assert verdict["publishable"] == ["yale"]

    def test_declared_empty_source_zero_neither_blocks_nor_degrades_hard(self):
        summary, _ = _ucb_summary(ucb_urap_projects={
            "fetched": 0, "new": 0, "updated": 0, "status": "ok",
        })
        verdict = _verdict(summary)
        assert verdict["publishable"] == ["ucb"]
        assert any("declared expected" in w for w in verdict["warnings"])
        assert not [
            d for d in verdict["degradations"]
            if d["source"] == "ucb_urap_projects"
        ]

    def test_an_unclassified_zero_fails_safe_rather_than_closed(self):
        """A summary built without refresh_all's classification pass (a
        recompute, a hand-built fixture) degrades the source — it does not
        withhold the source's siblings."""
        summary, _ = _ucb_summary(ucb_ling_faculty={
            "fetched": 0, "new": 0, "updated": 0, "status": "ok",
        })
        verdict = _verdict(summary)
        assert verdict["publishable"] == ["ucb"]
        assert any(
            d["source"] == "ucb_ling_faculty"
            and d["kind"] == "suspicious_zero"
            for d in verdict["degradations"]
        )

    def test_a_structural_failure_still_blocks_everything(self):
        summary, _ = _ucb_summary()
        summary["shard"] = {"schools": ["yale"], "national": False}
        verdict = _verdict(summary)
        assert verdict["ready"] is False
        assert verdict["publishable"] == []
        assert verdict["structural_reasons"]


class TestSourceNaming:
    def test_campus_crawl_record_source_maps_to_its_summary_key(self):
        aliases = record_source_aliases()
        assert aliases["swarthmore_research_programs"] == "campus_graph:swarthmore"
        assert aliases["ucb_research_programs"] == "ucb_campus"

    def test_every_alias_target_is_a_monitored_source(self):
        """Otherwise a school's program shard is unmonitored on one side and a
        never-recorded producer on the other."""
        monitored = monitored_sources()
        for record_source, summary_key in record_source_aliases().items():
            assert summary_key in monitored, record_source

    def test_the_broken_departments_are_all_monitored_producers(self):
        monitored = monitored_sources()
        for source in (
            "ucb_ling_faculty", "colgate_faculty", "swarthmore_faculty",
        ):
            assert source in monitored, source

    def test_a_source_resolves_to_the_shard_file_it_publishes_into(self):
        """Every source whose summary key does not look like its school. Two
        of these resolved to None through SOURCE_DEFAULTS alone, which
        silently dropped their rows out of per-school aggregation."""
        assert shard_of_source("campus_graph:colgate") == "colgate"
        assert shard_of_source("ucb_campus") == "ucb"
        assert shard_of_source("ucb_urap_projects") == "ucb"
        assert shard_of_source("ucsb_urca_projects") == "ucsb"
        assert shard_of_source("nsf_reu") == "national"
        assert shard_of_source("uiuc_sro") == "national"
        assert shard_of_source("colgate_faculty") == "colgate"
        assert shard_of_source("not_a_source") is None

    def test_every_monitored_source_resolves_to_a_shard(self):
        """A monitored producer with no shard would be counted in no school -
        present in the ledger and absent from every aggregate."""
        unresolved = sorted(
            key for key in monitored_sources() if shard_of_source(key) is None
        )
        assert unresolved == []


# ------------------------------------------------- why degrading is safe --
class TestAnEmptyHarvestCannotDeleteRecords:
    """The load-bearing assumption behind degrading instead of blocking.

    Publishing a school whose department emitted nothing is only safe because
    the merge layer physically cannot remove that department's records. If a
    merge ever became a replace, a suspicious zero would silently empty a
    department AND the school would publish it — a strictly worse failure
    than the freeze this replaced. So it is pinned here rather than assumed.
    """

    def _corpus(self, tmp_path):
        path = tmp_path / "opportunities.json"
        records = [
            {
                "id": "faculty-ucb-ling-ac3cb928",
                "source": "ucb_ling_faculty",
                "source_type": "faculty_research",
                "school": "ucb",
                "department": "Department of Linguistics",
                "metadata": {
                    "is_active": True,
                    "last_seen_at": "2026-07-21T07:08:46",
                    "first_seen_at": "2026-06-27T08:11:51",
                },
            },
        ]
        path.write_text(json.dumps(records), encoding="utf-8")
        return path

    def test_faculty_graph_merge_of_nothing_changes_nothing(
        self, monkeypatch, tmp_path,
    ):
        from src.collectors import faculty_graph, ucb_common

        path = self._corpus(tmp_path)
        monkeypatch.setattr(ucb_common, "PROCESSED_FILE", path)
        before = path.read_text(encoding="utf-8")

        assert faculty_graph.merge_into_processed([]) == (0, 0)
        assert path.read_text(encoding="utf-8") == before

    def test_ucb_merge_of_nothing_changes_nothing(self, monkeypatch, tmp_path):
        from src.collectors import ucb_common

        path = self._corpus(tmp_path)
        monkeypatch.setattr(ucb_common, "PROCESSED_FILE", path)
        before = json.loads(path.read_text(encoding="utf-8"))

        ucb_common.merge_into_processed([])
        after = json.loads(path.read_text(encoding="utf-8"))
        assert after == before
        assert after[0]["metadata"]["is_active"] is True
        assert after[0]["metadata"]["last_seen_at"] == "2026-07-21T07:08:46"


@pytest.mark.parametrize("status", ["captured", "empty", "unsupported", "failed"])
def test_b55_condition_receipt_health(status):
    counts = dict.fromkeys(("captured", "empty", "unsupported", "failed"), 0)
    counts[status] = 1
    good = status in {"captured", "empty"}
    receipt = {"condition_capture_counts": counts, "condition_capture_complete": good,
               "detail_pages_attempted": 1, "detail_pages_loaded": 0 if status == "failed" else 1,
               "detail_pages_failed": 1 if status == "failed" else 0}
    incomplete, invalid = sh.collection_evidence_issues(receipt)
    assert invalid == []
    assert bool(incomplete) is not good


@pytest.mark.parametrize("fault", ["bool", "negative", "missing_count", "sum", "no_list_page", "complete_despite_failure", "capture_count", "capture_flag", "capture_attempts", "errors_shape"])
def test_b55_rejects_malformed_collection_receipts(fault):
    receipt = {"list_pages_attempted": 1, "list_pages_loaded": 1, "list_pages_failed": 0, "list_complete": True,
               "detail_pages_attempted": 1, "detail_pages_loaded": 1, "detail_pages_failed": 0,
               "condition_capture_counts": {"captured": 0, "empty": 1, "unsupported": 0, "failed": 0}, "condition_capture_complete": True}
    if fault == "bool": receipt["list_pages_loaded"] = True
    if fault == "negative": receipt["detail_pages_failed"] = -1
    if fault == "missing_count": receipt.pop("list_pages_failed")
    if fault == "sum": receipt["list_pages_attempted"] = 2
    if fault == "no_list_page": receipt.update(list_pages_attempted=0, list_pages_loaded=0)
    if fault == "complete_despite_failure": receipt.update(list_pages_loaded=0, list_pages_failed=1)
    if fault == "capture_count": receipt["condition_capture_counts"]["empty"] = True
    if fault == "capture_flag": receipt["condition_capture_complete"] = False
    if fault == "capture_attempts": receipt["condition_capture_counts"]["empty"] = 2
    if fault == "errors_shape": receipt["list_errors"] = "private raw response"
    assert sh.collection_evidence_issues(receipt)[1]


def test_b55_partial_page_or_parse_failure_remains_incomplete():
    receipt = {"list_pages_attempted": 3, "list_pages_loaded": 2, "list_pages_failed": 1, "list_complete": False,
               "normalization_failed": 1}
    incomplete, invalid = sh.collection_evidence_issues(receipt)
    assert invalid == []
    assert set(incomplete) == {"list_pages_failed", "list_incomplete", "normalization_failed"}
