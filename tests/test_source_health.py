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

    def test_unscheduled_sources_are_shown_but_never_counted_stale(self):
        """``manual`` seeds and opportunistic ``*_external_research`` pages are
        carried data, not weekly producers. Judging them on a weekly clock
        reported the national shard permanently degraded."""
        ledger = _ledger_with({
            "nsf_reu": ("national", 4, sh.SUCCESS_NONZERO),
            "manual": ("national", 163, sh.SUCCESS_NONZERO),
            "ucb_external_research": ("national", 47, sh.SUCCESS_NONZERO),
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
