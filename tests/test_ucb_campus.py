"""Tests for the UC Berkeley campus-wide opportunity collector + registry.

Exercises the seed path only (no network) — the live BFS crawl lazy-imports its
HTTP deps and is not unit-tested here. Locks in the invariants the data-quality
gate and the multi-school scope filter depend on, so a registry edit can't
silently ship records that break either.
"""

from __future__ import annotations

import json

import pytest

from src.collectors import ucb_campus
from src.collectors import ucb_sources as reg
from src.normalizers.school_audience import SOURCE_DEFAULTS, VALID_AUDIENCES


class _StaticSoup:
    def __init__(self, text: str = "Applications open"):
        self._text = text

    def get_text(self, *_args, **_kwargs):
        return self._text

    def find_all(self, *_args, **_kwargs):
        return []

    def find(self, *_args, **_kwargs):
        return None

# --- Registry integrity ----------------------------------------------------

class TestRegistry:
    def test_registry_is_structurally_valid(self):
        assert reg.validate_registry() == []

    def test_all_five_source_types_present(self):
        present = {s["source_type"] for s in reg.UCB_SOURCES}
        assert reg.SOURCE_TYPES <= present, (
            f"missing source types: {reg.SOURCE_TYPES - present}"
        )

    def test_source_names_unique(self):
        names = reg.all_source_names()
        assert len(names) == len(set(names))

    def test_program_keys_unique(self):
        keys = [p["key"] for _, p in reg.iter_programs()]
        assert len(keys) == len(set(keys))

    def test_every_emit_bucket_maps_to_source_defaults(self):
        """Each emit bucket must resolve to a (source, school, audience) whose
        (school, audience) matches school_audience.SOURCE_DEFAULTS — the
        contract the DQ gate enforces."""
        for emit, (source, school, audience) in ucb_campus.EMIT_TO_SCHOOL_AUDIENCE.items():
            assert emit in reg.EMIT_BUCKETS
            assert source in SOURCE_DEFAULTS
            assert SOURCE_DEFAULTS[source] == (school, audience)


# --- Seed normalization -----------------------------------------------------

@pytest.fixture(scope="module")
def seed_records():
    return ucb_campus.fetch_and_normalize(deep=False)


class TestSeedNormalization:
    def test_produces_many_records(self, seed_records):
        # The whole point is breadth — expect well past the URAP+faculty baseline
        # delta the acceptance criteria call for.
        assert len(seed_records) >= 50

    def test_every_record_has_required_schema_fields(self, seed_records):
        for o in seed_records:
            assert o["id"] and o["title"] and o["url"]
            assert isinstance(o["eligibility"], dict)
            assert isinstance(o["metadata"], dict)
            assert isinstance(o["keywords"], list)
            assert "description_clean" in o
            assert len(o["description_clean"]) <= 1500

    def test_ids_unique(self, seed_records):
        ids = [o["id"] for o in seed_records]
        assert len(ids) == len(set(ids))

    def test_school_audience_matches_source_defaults(self, seed_records):
        for o in seed_records:
            assert o["audience"] in VALID_AUDIENCES
            assert (o["school"], o["audience"]) == SOURCE_DEFAULTS[o["source"]]

    def test_no_pi_or_contact_email(self, seed_records):
        """Program/lab pages are not individuals — leaving pi_name/contact_email
        unset keeps them out of the ucb_* shared-email/name DQ gate."""
        for o in seed_records:
            assert o.get("pi_name") is None
            assert o.get("contact_email") is None

    def test_rolling_with_no_deadline(self, seed_records):
        """No structured deadlines (cycles live in the description), so every
        record must be rolling — otherwise deactivate_past can't reason about it
        and the UI shows a blank timing block."""
        for o in seed_records:
            assert o.get("deadline") is None
            assert o.get("is_rolling") is True

    def test_clear_separation_of_levels(self, seed_records):
        """Program / lab / department / career / announcement must each be
        represented and individually addressable via ucb_source_type."""
        levels = {o["ucb_source_type"] for o in seed_records}
        assert {"program", "lab", "department", "career", "announcement"} <= levels

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Applications are now open.", "open"),
            ("Applications are currently open.", "open"),
            ("Applications open.", "open"),
            ("Status: Applications open.", "open"),
            ("Apply now.", "open"),
            ("Now accepting applications.", "open"),
            ("Applications are closed.", "closed"),
            ("Application is closed.", "closed"),
            ("Applications are currently closed.", "closed"),
            ("The application is now closed.", "closed"),
            ("Applications are temporarily closed.", "closed"),
            ("Application period is closed.", "closed"),
            ("The application window is currently closed.", "closed"),
            ("Applications are not being accepted.", "closed"),
            ("No applications are being accepted.", "closed"),
            ("Submissions are closed.", "closed"),
            ("The application cycle has ended.", "closed"),
            ("Applications have closed.", "closed"),
            ("We are not accepting applications.", "closed"),
            ("We are not accepting new applications.", "closed"),
            ("We are not now accepting applications.", "closed"),
            ("The deadline has now passed.", "closed"),
            ("Deadline passed.", "closed"),
            ("Applications open. Applications closed.", "closed"),
            ("Applications are now open. Application period is closed.", "closed"),
            ("Applications closed. Applications open next fall.", "closed"),
            (
                "Applications are currently closed. "
                "Applications open each September.",
                "closed",
            ),
            ("Applications open next fall.", "unknown"),
            ("Applications open each September.", "unknown"),
            ("Applications open: next fall.", "unknown"),
            ("Applications open — next fall.", "unknown"),
            ("Applications open (next fall).", "unknown"),
            ("Applications open in September.", "unknown"),
            ("Applications open September 1, 2027.", "unknown"),
            ("Applications open 9/1/2027.", "unknown"),
            ("Applications open during fall.", "unknown"),
            ("Applications open annually in September.", "unknown"),
            ("Applications open yearly in September.", "unknown"),
            ("Applications open in mid-September.", "unknown"),
            ("Learn when applications open.", "unknown"),
            ("Please do not apply now.", "unknown"),
            ("Please don't apply now.", "unknown"),
            ("You must not apply now.", "unknown"),
            ("Never apply now.", "unknown"),
            (
                "You cannot apply now; applications will open next fall.",
                "unknown",
            ),
            ("Apply Now button is disabled.", "unknown"),
            ("The Apply Now button has been disabled.", "unknown"),
            ("The Apply Now link remains disabled.", "unknown"),
            ("Apply Now is not enabled.", "unknown"),
            ("2025 status: Applications open.", "unknown"),
            ("Last year: Applications open.", "unknown"),
            ("Previous application cycle: Applications open.", "unknown"),
            ("Archived notice: Applications open.", "unknown"),
            ("Historical record: Applications open.", "unknown"),
            ("Program information only.", "unknown"),
        ],
    )
    def test_status_detection_is_fail_closed(self, text, expected):
        assert ucb_campus._detect_status(text) == expected

    def test_summer_programs_typed_for_seasonal_boost(self, seed_records):
        summer = [o for o in seed_records if o["opportunity_type"] == "summer_program"]
        assert summer, "expected some summer_program records for the seasonal boost"

    def test_deep_total_outage_is_visible_in_evidence(self, monkeypatch):
        monkeypatch.setattr(ucb_campus, "_fetch", lambda url: None)

        records, evidence = ucb_campus.fetch_and_normalize_with_evidence(
            deep=True
        )

        assert records
        assert evidence["seed_records"] > 0
        assert evidence["live_pages_attempted"] > 0
        assert evidence["live_pages_loaded"] == 0
        assert evidence["crawl_sources_loaded"] == 0
        assert evidence["seed_pages_loaded"] == 0
        assert evidence["seed_pages_failed"] == evidence["seed_pages_expected"]
        assert evidence["crawl_errors"]

    def test_partial_live_seed_fetch_records_complete_evidence(self, monkeypatch):
        failed_url = reg.UCB_SOURCES[0]["seeds"][0]
        monkeypatch.setattr(
            ucb_campus,
            "_fetch",
            lambda url: None if url == failed_url else _StaticSoup(),
        )

        records, evidence = ucb_campus.fetch_and_normalize_with_evidence(
            deep=True
        )

        expected = sum(len(set(source["seeds"])) for source in reg.UCB_SOURCES)
        assert records
        assert evidence["seed_pages_expected"] == expected
        assert evidence["seed_pages_loaded"] == expected - 1
        assert evidence["seed_pages_failed"] == 1
        assert any(failed_url in error for error in evidence["crawl_errors"])

    def test_quick_unverified_seed_does_not_reactivate_old_closed_record(
        self,
        monkeypatch,
        tmp_path,
    ):
        source = reg.UCB_SOURCES[0]
        program = source["programs"][0]
        closed = ucb_campus._normalize_program(
            source,
            program,
            status="closed",
            seed_page_verified=True,
        )
        closed["metadata"]["last_verified"] = "2026-06-01T00:00:00"
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([closed]), encoding="utf-8")
        monkeypatch.setattr(ucb_campus, "PROCESSED_FILE", processed)

        unverified = ucb_campus._normalize_program(source, program)
        assert unverified["metadata"]["is_active"] is True
        assert unverified["metadata"]["last_verified"] is None
        ucb_campus.merge_into_processed([unverified])

        [merged] = json.loads(processed.read_text(encoding="utf-8"))
        assert merged["metadata"]["status"] == "closed"
        assert merged["metadata"]["is_active"] is False
        assert merged["metadata"]["last_verified"] == "2026-06-01T00:00:00"
        assert merged["title"].endswith("(applications closed)")

    def test_verified_unknown_status_does_not_reopen_closed_seed(
        self,
        monkeypatch,
        tmp_path,
    ):
        source = reg.UCB_SOURCES[0]
        program = source["programs"][0]
        closed = ucb_campus._normalize_program(
            source,
            program,
            status="closed",
            seed_page_verified=True,
        )
        closed["metadata"]["last_verified"] = "2026-06-01T00:00:00"
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([closed]), encoding="utf-8")
        monkeypatch.setattr(ucb_campus, "PROCESSED_FILE", processed)

        unknown = ucb_campus._normalize_program(
            source,
            program,
            status="unknown",
            seed_page_verified=True,
        )
        ucb_campus.merge_into_processed([unknown])

        [merged] = json.loads(processed.read_text(encoding="utf-8"))
        assert merged["metadata"]["status"] == "closed"
        assert merged["metadata"]["is_active"] is False
        assert merged["metadata"]["last_verified"] != "2026-06-01T00:00:00"
        assert merged["title"].endswith("(applications closed)")

    def test_discovered_anchor_requires_its_own_page_before_emission(
        self,
        monkeypatch,
    ):
        from bs4 import BeautifulSoup

        seed_url = "https://example.berkeley.edu/research"
        detail_url = (
            "https://example.berkeley.edu/research/summer-fellowship"
        )
        source = {
            "source_name": "ucb_example",
            "source_type": reg.PROGRAM,
            "emit": reg.EMIT_CAMPUS,
            "crawl": reg.RECURSIVE,
            "crawl_depth": 1,
            "seeds": [seed_url],
            "programs": [],
        }
        seed = BeautifulSoup(
            f'<a href="{detail_url}">Summer Research Fellowship 2026</a>',
            "html.parser",
        )
        monkeypatch.setattr(
            ucb_campus,
            "_fetch",
            lambda url: seed if url == seed_url else None,
        )
        _status, discovered, evidence = ucb_campus._crawl_source(source)
        assert discovered == []
        assert evidence["degraded_page_errors"] == [detail_url]

        detail = BeautifulSoup(
            "<main>Applications are now open for undergraduate researchers.</main>",
            "html.parser",
        )
        monkeypatch.setattr(
            ucb_campus,
            "_fetch",
            lambda url: seed if url == seed_url else detail,
        )
        _status, discovered, _evidence = ucb_campus._crawl_source(source)
        assert len(discovered) == 1
        assert discovered[0]["metadata"]["discovered_page_verified"] is True
        assert discovered[0]["metadata"]["status"] == "open"
        assert discovered[0]["metadata"]["is_active"] is True

    def test_absent_discovery_retires_only_for_complete_recursive_source(
        self,
        monkeypatch,
        tmp_path,
    ):
        recursive = [
            source
            for source in reg.UCB_SOURCES
            if source["crawl"] == reg.RECURSIVE
        ]
        failed_source, complete_source = recursive[:2]
        static_source = next(
            source
            for source in reg.UCB_SOURCES
            if source["crawl"] == reg.STATIC
        )

        def old_discovery(source, suffix):
            record = ucb_campus._normalize_discovered(
                source,
                f"Old {suffix} fellowship",
                f"https://example.berkeley.edu/{suffix}",
                suffix,
            )
            record["metadata"].update(
                {
                    "discovered_page_verified": True,
                    "status": "open",
                    "is_active": True,
                }
            )
            return record

        failed = old_discovery(failed_source, "failed")
        complete = old_discovery(complete_source, "complete")
        static = old_discovery(static_source, "static")
        other_school = json.loads(json.dumps(complete))
        other_school["id"] = "other-school-discovery"
        other_school["school"] = "other"
        processed = tmp_path / "opportunities.json"
        processed.write_text(
            json.dumps([failed, complete, static, other_school]),
            encoding="utf-8",
        )
        monkeypatch.setattr(ucb_campus, "PROCESSED_FILE", processed)

        failed_url = failed_source["seeds"][0]
        monkeypatch.setattr(
            ucb_campus,
            "_fetch",
            lambda url: None if url == failed_url else _StaticSoup(),
        )
        records, evidence = ucb_campus.fetch_and_normalize_with_evidence(
            deep=True
        )
        complete_sources = set(evidence["complete_recursive_sources"])
        assert failed_source["source_name"] not in complete_sources
        assert complete_source["source_name"] in complete_sources
        assert static_source["source_name"] not in complete_sources

        ucb_campus.merge_into_processed(
            records,
            complete_recursive_sources=complete_sources,
        )

        saved = {
            record["id"]: record
            for record in json.loads(processed.read_text(encoding="utf-8"))
        }
        assert saved[failed["id"]]["metadata"]["is_active"] is True
        assert saved[complete["id"]]["metadata"]["is_active"] is False
        assert saved[complete["id"]]["metadata"]["deactivation_reason"] == (
            "absent_from_complete_recursive_crawl"
        )
        assert saved[static["id"]]["metadata"]["is_active"] is True
        assert saved[other_school["id"]]["metadata"]["is_active"] is True

    def test_closed_seed_is_not_active(self):
        source = reg.UCB_SOURCES[0]
        program = source["programs"][0]

        record = ucb_campus._normalize_program(
            source,
            program,
            status="closed",
        )

        assert record["metadata"]["status"] == "closed"
        assert record["metadata"]["is_active"] is False


# --- Source breakdown -------------------------------------------------------

class TestSourceBreakdown:
    def test_breakdown_totals_consistent(self, seed_records):
        bd = ucb_campus.source_breakdown(seed_records)
        assert bd["total"] == len(seed_records)
        assert sum(bd["by_source_type"].values()) == len(seed_records)
        assert sum(bd["by_emit_bucket"].values()) == len(seed_records)


class TestCrawlDiscoverySpecificity:
    """The crawl only emits a discovered record for a *specific* posting anchor,
    not a bare section/CTA link — keeps discovery from flooding the corpus (and
    the DQ gate) with generic 'Undergraduate Research' / 'Apply' rows."""

    def test_generic_anchors_rejected(self):
        for a in ["Undergraduate Research", "Research", "Apply", "Apply now",
                  "Learn more", "internships", "Fellowship", "Get involved"]:
            assert ucb_campus._is_specific_opportunity(a) is False, a

    def test_specific_anchors_accepted(self):
        for a in ["SURF Summer Research Fellowship",
                  "Sky Computing Lab — Undergraduate Researchers",
                  "Join the Smith Lab (research assistant)"]:
            assert ucb_campus._is_specific_opportunity(a) is True, a

    def test_too_short_rejected(self):
        assert ucb_campus._is_specific_opportunity("REU") is False

    def test_noise_headlines_emails_gradnav_rejected(self):
        # News headlines, an email-as-title, application-instruction / grad-program
        # nav, and employer-facing CTAs carry a priority keyword + clear the length
        # bar, but are not student opportunities — they must be rejected.
        for a in [
            "Sophia Young (’25) Receives Lafayette Fellowship to Study AI in France",
            "2025-2026 Scholarships Wrap-Up",
            "ourscholarships@berkeley.edu",
            "Read more about Undergraduate Research",
            "read through the programs available and apply",
            "How to Apply",
            "Apply or Transfer",
            "MEng How to apply",
            "Interested in recruiting our students and alumni?",
        ]:
            assert ucb_campus._is_noise_discovered(a) is True, a
            assert ucb_campus._is_specific_opportunity(a) is False, a

    def test_real_program_pages_not_flagged_as_noise(self):
        # Generic-but-legitimate program/resource pages must survive the filter.
        for a in ["SURF Summer Research Fellowship",
                  "Amgen Scholars Program at UC Berkeley",
                  "Biology Scholars Program research"]:
            assert ucb_campus._is_noise_discovered(a) is False, a
