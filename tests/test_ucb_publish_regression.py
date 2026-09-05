"""The UC Berkeley regression, reconstructed from the real committed shard.

What happened, and what these tests hold shut:

  2026-07-21  ucb_ling_faculty last succeeded (17 Linguistics records).
  2026-08-18  the department had moved to lx.berkeley.edu; the parser matched
              nothing and reported {"fetched": 0, "status": "ok"}.
              refresh_contract read the zero as an accuracy failure, attributed
              it to unit "ucb" - the SHARD FILE, which is per school - and
              by_unit["ucb"].ready went False. publishable dropped "ucb", so
              shard_corpus never wrote ucb.json.
  2026-08-25  the same thing, again.
  2026-09-03  3,018 of ucb.json's 3,106 records still stamped 2026-07-21.
              44 days stale. 53 healthy departments re-scraped twice and
              discarded both times.

These are driven by the real ``data/processed/shards/ucb.json``, not by a
synthetic single-school fixture, so the department names, counts and
timestamps are the production ones. They skip (rather than pass vacuously) if
the shard is not checked out.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors import source_health as sh
from src.collectors.refresh_contract import (
    evaluate_refresh_summary,
    expected_sources,
)
from src.normalizers.deactivate_stale_faculty import (
    FACULTY_SOURCES,
    deactivate_stale_faculty,
)

UCB_SHARD = (
    Path(__file__).resolve().parents[1]
    / "data" / "processed" / "shards" / "ucb.json"
)
BROKEN_DEPARTMENT = "ucb_ling_faculty"


@pytest.fixture(scope="module")
def ucb_records() -> list[dict]:
    if not UCB_SHARD.exists():
        pytest.skip("data/processed/shards/ucb.json is not checked out")
    with UCB_SHARD.open(encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list) or not records:
        pytest.skip("ucb shard is empty")
    return records


@pytest.fixture(scope="module")
def ucb_by_source(ucb_records) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in ucb_records:
        source = record.get("source")
        if isinstance(source, str) and source:
            grouped.setdefault(source, []).append(record)
    return grouped


class TestTheRealShardShowsTheFailure:
    def test_the_shard_has_many_independent_department_sources(self, ucb_by_source):
        """The premise: "one school" is really dozens of separate collectors,
        which is why collapsing them onto one verdict was so costly."""
        faculty_sources = [s for s in ucb_by_source if s in FACULTY_SOURCES]
        assert len(faculty_sources) > 40

    def test_the_broken_department_still_holds_its_last_known_good(
        self, ucb_by_source,
    ):
        """Nothing was lost - the records were preserved throughout. What was
        lost was every OTHER department's refresh."""
        ling = ucb_by_source.get(BROKEN_DEPARTMENT, [])
        assert ling, f"{BROKEN_DEPARTMENT} has no records in the shard"
        assert all(
            (r.get("metadata") or {}).get("is_active") is not False for r in ling
        ), "preserved records must stay active, not be retired for absence"


class TestOneDepartmentNoLongerFreezesTheSchool:
    def _summary(self, sources: dict) -> dict:
        return {
            "request": {"schools": ["ucb"], "national": False, "deep": True},
            "shard": {"schools": ["ucb"], "national": False},
            "sources": sources,
        }

    def _healthy_run(self, ucb_by_source) -> dict:
        """A UCB deep run where every mandatory producer succeeded, counts
        taken from what the real shard actually holds per source."""
        sources: dict[str, dict] = {}
        for key in expected_sources({"ucb"}, national=False, deep=True):
            held = len(ucb_by_source.get(key, ())) or 25
            sources[key] = {
                "fetched": held, "new": 0, "updated": held, "status": "ok",
            }
            if key == "ucb_campus" or key.startswith("campus_graph:"):
                sources[key].update({
                    "live_pages_attempted": 12, "live_pages_loaded": 12,
                    "crawl_sources_expected": 4, "crawl_sources_loaded": 4,
                    "seed_pages_expected": 6, "seed_pages_loaded": 6,
                    "seed_pages_failed": 0,
                })
        return sources

    def _verdict(self, sources: dict) -> dict:
        return evaluate_refresh_summary(
            self._summary(sources), schools={"ucb"}, national=False,
            deep=True, require_tracking=False,
        )

    def test_the_2026_08_18_run_would_now_publish(self, ucb_by_source):
        """Replay of the exact run that published nothing."""
        sources = self._healthy_run(ucb_by_source)
        baseline = len(ucb_by_source.get(BROKEN_DEPARTMENT, ()))
        sources[BROKEN_DEPARTMENT] = {
            "fetched": 0, "new": 0, "updated": 0,
            "status": sh.SUSPICIOUS_ZERO,
            "suspicious_zero_baseline": baseline,
        }
        verdict = self._verdict(sources)

        assert verdict["publishable"] == ["ucb"], (
            "one broken department must not withhold the UCB shard"
        )
        assert verdict["by_unit"]["ucb"]["ready"] is True
        assert verdict["reasons"] == []

    def test_and_still_reports_the_broken_department(self, ucb_by_source):
        sources = self._healthy_run(ucb_by_source)
        sources[BROKEN_DEPARTMENT] = {
            "fetched": 0, "new": 0, "updated": 0,
            "status": sh.SUSPICIOUS_ZERO, "suspicious_zero_baseline": 17,
        }
        verdict = self._verdict(sources)
        assert verdict["status"] == "degraded"
        assert any(
            d["source"] == BROKEN_DEPARTMENT and d["kind"] == "suspicious_zero"
            for d in verdict["degradations"]
        )

    def test_healthy_departments_get_new_publish_timestamps(self, ucb_by_source):
        """The other half of the fix: the healthy departments' successes are
        recorded, so they read as fresh while the broken one reads as stale."""
        now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
        stale_since = datetime(2026, 7, 21, 7, 8, 46, tzinfo=UTC)
        ledger = sh.empty_ledger()

        # Every department last succeeded when the shard froze...
        for source in ucb_by_source:
            if source not in FACULTY_SOURCES:
                continue
            sh.record_attempt(
                ledger, source=source, school="ucb",
                outcome=sh.SUCCESS_NONZERO,
                emitted=len(ucb_by_source[source]),
                baseline=len(ucb_by_source[source]), now=stale_since,
            )
        # ...then a run today succeeds everywhere except linguistics.
        for source in list(ledger["sources"]):
            if source == BROKEN_DEPARTMENT:
                sh.record_attempt(
                    ledger, source=source, school="ucb",
                    outcome=sh.SUSPICIOUS_ZERO, emitted=0,
                    baseline=len(ucb_by_source[source]), now=now,
                    failure_reason="emitted 0 against a stored baseline",
                )
            else:
                sh.record_attempt(
                    ledger, source=source, school="ucb",
                    outcome=sh.SUCCESS_NONZERO,
                    emitted=len(ucb_by_source[source]),
                    baseline=len(ucb_by_source[source]), now=now,
                )
        sh.record_publish(ledger, shards={"ucb": len(ucb_by_source)}, now=now)

        rows = {r["source"]: r for r in sh.source_rows(ledger, now, None)}
        assert rows[BROKEN_DEPARTMENT]["freshness"] == "stale"
        assert rows[BROKEN_DEPARTMENT]["last_success_at"] == stale_since.isoformat()
        healthy = [
            r for s, r in rows.items() if s != BROKEN_DEPARTMENT
        ]
        assert healthy, "expected sibling departments in the ledger"
        assert all(r["freshness"] == "fresh" for r in healthy)

        school = sh.school_rows(ledger, now, None)[0]
        assert school["school"] == "ucb"
        assert school["fully_stale"] is False, (
            "UCB is not a dead school - one department is stale"
        )
        assert school["state"] == "partially_degraded"
        assert school["stale_shard_count"] == 1
        assert school["fresh_shard_count"] == len(healthy)
        assert school["last_publish_at"] == now.isoformat()

    def test_publishing_ucb_does_not_backdate_the_broken_department_fresh(
        self, ucb_by_source,
    ):
        """Stale-source masking, the explicit prohibition: "UCB published
        today" must never become "ucb_ling_faculty succeeded today"."""
        now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
        ledger = sh.empty_ledger()
        sh.record_attempt(
            ledger, source=BROKEN_DEPARTMENT, school="ucb",
            outcome=sh.SUCCESS_NONZERO, emitted=17, baseline=17,
            now=now - timedelta(days=44),
        )
        sh.record_attempt(
            ledger, source=BROKEN_DEPARTMENT, school="ucb",
            outcome=sh.SUSPICIOUS_ZERO, emitted=0, baseline=17, now=now,
        )
        sh.record_publish(ledger, shards={"ucb": 3106}, now=now)

        row = ledger["sources"][BROKEN_DEPARTMENT]
        assert sh.freshness_of(row, now) == "stale"
        assert row["last_attempt_at"] == now.isoformat()
        assert row["last_success_at"] == (now - timedelta(days=44)).isoformat()


class TestTheZeroCannotTakeTheRecordsWithIt:
    def test_a_zero_emitting_department_does_not_retire_its_records(
        self, ucb_records, ucb_by_source,
    ):
        """The reason degrading rather than blocking is SAFE: retirement is
        authorized only for sources that reported "ok", and a suspicious zero
        does not. Run the real retirement pass over the real shard with the
        broken department reporting a zero and assert nothing is retired.
        """
        ling = ucb_by_source.get(BROKEN_DEPARTMENT, [])
        assert ling
        records = json.loads(json.dumps(ucb_records))  # deep copy

        # Exactly what refresh_all now passes: only "ok" sources appear, so a
        # suspicious_zero source is simply absent from fetched_counts.
        counts = deactivate_stale_faculty(
            records,
            {},  # linguistics omitted - it did not report ok
            today=datetime(2026, 9, 3, tzinfo=UTC).date(),
        )
        assert counts["newly_deactivated"] == 0

        still_active = [
            r for r in records
            if r.get("source") == BROKEN_DEPARTMENT
            and (r.get("metadata") or {}).get("is_active") is not False
        ]
        assert len(still_active) == len(ling)

    def test_a_zero_would_retire_them_if_it_were_reported_ok(
        self, ucb_records, ucb_by_source,
    ):
        """The counterfactual that shows the guard is load-bearing, not
        incidental: had the zero kept its "ok" status AND supplied a per-unit
        ledger claiming the department was fully scraped, the records would be
        retired for absence. That is the outcome the classification prevents.
        """
        ling = ucb_by_source.get(BROKEN_DEPARTMENT, [])
        assert ling
        records = json.loads(json.dumps(ucb_records))
        departments = {
            (r.get("department") or "").strip() for r in ling
        }
        assert len(departments) == 1, "linguistics is one named unit"

        counts = deactivate_stale_faculty(
            records,
            {BROKEN_DEPARTMENT: {next(iter(departments)): 0}},
            today=datetime(2026, 9, 3, tzinfo=UTC).date(),
        )
        # 0 against N active is below MIN_SCRAPE_RATIO, so the partial-scrape
        # guard catches it even here - defence in depth, and worth pinning.
        assert counts["newly_deactivated"] == 0
        assert any(
            label.startswith(BROKEN_DEPARTMENT)
            for label in counts["skipped_partial_scrape"]
        )
