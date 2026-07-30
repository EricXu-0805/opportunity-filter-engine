"""Tests for the generic campus-graph engine + the per-school configs it drives.

Exercises the seed path only (no network) — the live BFS crawl lazy-imports its
HTTP deps and is not unit-tested here. Locks in the invariants the data-quality
gate and the multi-school scope filter depend on, so adding/editing a school
config can't silently ship records that break either.

This is the Top-50 rollout's safety net: every school in
``schools.SCHOOL_CONFIGS`` is validated and normalized the same way, so the test
surface grows automatically as the registry grows — no per-school test file.
"""

from __future__ import annotations

import json

import pytest

from src.collectors import campus_graph as cg
from src.collectors.schools import SCHOOL_CONFIGS
from src.collectors.schools.boulder import SCHOOL as BOULDER
from src.collectors.schools.princeton import SCHOOL as PRINCETON
from src.collectors.schools.uci import SCHOOL as UCI
from src.collectors.schools.ucsb import SCHOOL as UCSB
from src.collectors.schools.ucsd import SCHOOL as UCSD
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
    def test_registry_non_empty(self):
        assert SCHOOL_CONFIGS, "expected at least one school config"

    def test_every_config_is_structurally_valid(self):
        for cfg in SCHOOL_CONFIGS:
            assert cg.validate(cfg) == [], f"{cfg.get('school_slug')}: {cg.validate(cfg)}"

    def test_school_slugs_unique(self):
        slugs = [c["school_slug"] for c in SCHOOL_CONFIGS]
        assert len(slugs) == len(set(slugs))

    def test_every_emit_bucket_maps_to_source_defaults(self):
        """Each config's emit map must resolve to a (source, school, audience)
        whose (school, audience) matches school_audience.SOURCE_DEFAULTS — the
        contract the DQ gate enforces."""
        for cfg in SCHOOL_CONFIGS:
            for _bucket, (source, school, audience) in cfg["emit"].items():
                assert source in SOURCE_DEFAULTS, f"{source} missing from SOURCE_DEFAULTS"
                assert SOURCE_DEFAULTS[source] == (school, audience), (
                    f"{source}: config {(school, audience)} != "
                    f"SOURCE_DEFAULTS {SOURCE_DEFAULTS[source]}"
                )

    def test_program_keys_unique_within_each_school(self):
        for cfg in SCHOOL_CONFIGS:
            keys = [p["key"] for s in cfg["sources"] for p in s.get("programs", [])]
            assert len(keys) == len(set(keys)), f"{cfg['school_slug']}: dup program key"


# --- Validator catches bad configs -----------------------------------------

class TestValidator:
    def test_missing_slug_flagged(self):
        assert any("school_slug" in e for e in cg.validate({"emit": {}, "sources": []}))

    def test_bad_emit_bucket_flagged(self):
        bad = {"school_slug": "x", "emit": {"wat": ("s", "x", "campus")}, "sources": []}
        assert any("emit bucket" in e for e in cg.validate(bad))

    def test_bad_source_type_flagged(self):
        bad = {
            "school_slug": "x",
            "emit": {"campus": ("s", "x", "campus")},
            "sources": [{"source_name": "n", "source_type": "bogus", "emit": "campus",
                         "crawl": cg.STATIC, "seeds": ["http://x"], "programs": []}],
        }
        assert any("source_type" in e for e in cg.validate(bad))

    def test_source_emit_not_in_map_flagged(self):
        bad = {
            "school_slug": "x",
            "emit": {"campus": ("s", "x", "campus")},
            "sources": [{"source_name": "n", "source_type": cg.PROGRAM, "emit": "lab",
                         "crawl": cg.STATIC, "seeds": ["http://x"], "programs": []}],
        }
        assert any("not in school's emit map" in e for e in cg.validate(bad))

    def test_bad_program_enums_flagged(self):
        # Regression: jhu_ustar shipped international_friendly="ask" (#547),
        # which passed PR CI but detonated the shard refresh's integrity gate.
        bad = {
            "school_slug": "x",
            "emit": {"campus": ("s", "x", "campus")},
            "sources": [{"source_name": "n", "source_type": cg.PROGRAM, "emit": "campus",
                         "crawl": cg.STATIC, "seeds": ["http://x"],
                         "programs": [cg.program(
                             "k", "T", "http://x", "d",
                             international_friendly="ask", paid="hourly",
                         )]}],
        }
        errors = cg.validate(bad)
        assert any("bad international_friendly 'ask'" in e for e in errors)
        assert any("bad paid 'hourly'" in e for e in errors)

    def test_fetch_rejects_invalid_config(self):
        with pytest.raises(ValueError):
            cg.fetch_and_normalize({"school_slug": "x", "emit": {}, "sources": [
                {"source_name": "n", "source_type": "bogus", "emit": "campus",
                 "crawl": cg.STATIC, "seeds": [], "programs": []}]})


# --- Seed normalization (driven over the whole registry) --------------------

@pytest.fixture(scope="module")
def all_records():
    out = []
    for cfg in SCHOOL_CONFIGS:
        out.extend(cg.fetch_and_normalize(cfg, deep=False))
    return out


class TestSeedNormalization:
    def test_produces_records(self, all_records):
        assert len(all_records) >= len(SCHOOL_CONFIGS)

    def test_required_schema_fields(self, all_records):
        for o in all_records:
            assert o["id"] and o["title"] and o["url"]
            assert isinstance(o["eligibility"], dict)
            assert isinstance(o["metadata"], dict)
            assert isinstance(o["keywords"], list)
            assert "description_clean" in o
            assert len(o["description_clean"]) <= 1500

    def test_ids_unique(self, all_records):
        ids = [o["id"] for o in all_records]
        assert len(ids) == len(set(ids))

    def test_ids_namespaced_by_school(self, all_records):
        """Each id is prefixed with its school slug, so two schools can't collide
        and a record is traceable to its config."""
        slugs = {c["school_slug"] for c in SCHOOL_CONFIGS}
        for o in all_records:
            assert any(o["id"].startswith(f"{s}-") for s in slugs)

    def test_school_audience_matches_source_defaults(self, all_records):
        for o in all_records:
            assert o["audience"] in VALID_AUDIENCES
            assert (o["school"], o["audience"]) == SOURCE_DEFAULTS[o["source"]]

    def test_no_pi_or_contact_email(self, all_records):
        """Program/lab pages are not individuals — leaving pi_name/contact_email
        unset keeps them clear of any shared-email/name DQ gate."""
        for o in all_records:
            assert o.get("pi_name") is None
            assert o.get("contact_email") is None

    def test_rolling_with_no_deadline(self, all_records):
        for o in all_records:
            assert o.get("deadline") is None
            assert o.get("is_rolling") is True

    def test_source_type_never_faculty(self, all_records):
        """campus_* source_type must never read as faculty_research (that triggers
        faculty-only re-weighting in the ranker)."""
        for o in all_records:
            assert o["source_type"].startswith("campus_")
            assert "faculty" not in o["source_type"]

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
        assert cg._detect_status(text) == expected

    def test_deep_total_outage_is_visible_in_evidence(self, monkeypatch):
        monkeypatch.setattr(cg, "_fetch", lambda url: None)

        records, evidence = cg.fetch_and_normalize_with_evidence(
            PRINCETON,
            deep=True,
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
        urls = ("https://example.edu/ok", "https://example.edu/missing")
        source = {
            "source_name": "example_programs",
            "source_type": cg.PROGRAM,
            "emit": "campus",
            "crawl": cg.STATIC,
            "seeds": list(urls),
            "programs": [
                cg.program("ok", "Live program", urls[0], "live"),
                cg.program("missing", "Missing program", urls[1], "missing"),
            ],
        }
        school = {
            "school_slug": "example",
            "organization": "Example University",
            "location": "Example, EX",
            "emit": {"campus": ("example_programs", "example", "campus")},
            "sources": [source],
        }
        monkeypatch.setattr(
            cg,
            "_fetch",
            lambda url: _StaticSoup() if url == urls[0] else None,
        )

        records, evidence = cg.fetch_and_normalize_with_evidence(
            school,
            deep=True,
        )

        assert evidence["seed_pages_expected"] == 2
        assert evidence["seed_pages_loaded"] == 1
        assert evidence["seed_pages_failed"] == 1
        assert evidence["crawl_errors"] == [
            f"example_programs: seed fetch failed: {urls[1]}"
        ]
        by_key = {record["metadata"]["collector_key"]: record for record in records}
        assert by_key["ok"]["metadata"]["seed_page_verified"] is True
        assert by_key["missing"]["metadata"]["seed_page_verified"] is False

    def test_quick_unverified_seed_does_not_reactivate_old_closed_record(
        self,
        monkeypatch,
        tmp_path,
    ):
        source = PRINCETON["sources"][0]
        spec = source["programs"][0]
        closed = cg._normalize_program(
            PRINCETON,
            source,
            spec,
            status="closed",
            seed_page_verified=True,
        )
        closed["metadata"]["last_verified"] = "2026-06-01T00:00:00"
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([closed]), encoding="utf-8")
        monkeypatch.setattr(cg, "PROCESSED_FILE", processed)

        unverified = cg._normalize_program(PRINCETON, source, spec)
        assert unverified["metadata"]["is_active"] is True
        assert unverified["metadata"]["last_verified"] is None
        cg.merge_into_processed([unverified])

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
        source = PRINCETON["sources"][0]
        spec = source["programs"][0]
        closed = cg._normalize_program(
            PRINCETON,
            source,
            spec,
            status="closed",
            seed_page_verified=True,
        )
        closed["metadata"]["last_verified"] = "2026-06-01T00:00:00"
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([closed]), encoding="utf-8")
        monkeypatch.setattr(cg, "PROCESSED_FILE", processed)

        unknown = cg._normalize_program(
            PRINCETON,
            source,
            spec,
            status="unknown",
            seed_page_verified=True,
        )
        cg.merge_into_processed([unknown])

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

        seed_url = "https://example.edu/research"
        detail_url = "https://example.edu/research/summer-fellowship"
        source = {
            "source_name": "example_programs",
            "source_type": cg.PROGRAM,
            "emit": "campus",
            "crawl": cg.RECURSIVE,
            "crawl_depth": 1,
            "seeds": [seed_url],
            "programs": [],
        }
        school = {
            "school_slug": "example",
            "organization": "Example University",
            "location": "Example, EX",
            "emit": {"campus": ("example_programs", "example", "campus")},
            "sources": [source],
        }
        seed = BeautifulSoup(
            f'<a href="{detail_url}">Summer Research Fellowship 2026</a>',
            "html.parser",
        )
        monkeypatch.setattr(
            cg,
            "_fetch",
            lambda url: seed if url == seed_url else None,
        )
        _status, discovered, evidence = cg._crawl_source(school, source)
        assert discovered == []
        assert evidence["degraded_page_errors"] == [detail_url]

        detail = BeautifulSoup(
            "<main>Applications are now open for undergraduate researchers.</main>",
            "html.parser",
        )
        monkeypatch.setattr(
            cg,
            "_fetch",
            lambda url: seed if url == seed_url else detail,
        )
        _status, discovered, _evidence = cg._crawl_source(school, source)
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
            for source in PRINCETON["sources"]
            if source["crawl"] == cg.RECURSIVE
        ]
        failed_source, complete_source = recursive[:2]
        static_source = next(
            source
            for source in PRINCETON["sources"]
            if source["crawl"] == cg.STATIC
        )

        def old_discovery(source, suffix):
            record = cg._normalize_discovered(
                PRINCETON,
                source,
                f"Old {suffix} fellowship",
                f"https://example.edu/{suffix}",
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
        monkeypatch.setattr(cg, "PROCESSED_FILE", processed)

        failed_url = failed_source["seeds"][0]
        monkeypatch.setattr(
            cg,
            "_fetch",
            lambda url: None if url == failed_url else _StaticSoup(),
        )
        records, evidence = cg.fetch_and_normalize_with_evidence(
            PRINCETON,
            deep=True,
        )
        complete_sources = set(evidence["complete_recursive_sources"])
        assert failed_source["source_name"] not in complete_sources
        assert complete_source["source_name"] in complete_sources
        assert static_source["source_name"] not in complete_sources

        cg.merge_into_processed(
            records,
            complete_recursive_sources=complete_sources,
            school_slug=PRINCETON["school_slug"],
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

    def test_legacy_unverified_discovery_is_quarantined(self):
        legacy = {
            "id": "legacy-discovered",
            "source_type": "campus_program",
            "metadata": {
                "discovered": True,
                "collector_source": "example_programs",
                "is_active": True,
                "last_verified": "2026-06-01T00:00:00",
            },
        }
        verified = {
            "id": "verified-discovered",
            "source_type": "ucb_program",
            "metadata": {
                "discovered": True,
                "collector_source": "ucb_ours_hub",
                "discovered_page_verified": True,
                "is_active": True,
            },
        }
        urca = {
            "id": "verified-urca-sitemap",
            "source_type": "campus_program",
            "metadata": {
                "discovered": True,
                "urca_record_id": "a0W1",
                "is_active": True,
            },
        }
        seed = {
            "id": "curated-seed",
            "source_type": "campus_program",
            "metadata": {
                "discovered": False,
                "collector_source": "example_programs",
                "is_active": True,
            },
        }

        count = cg.quarantine_unverified_discovered(
            [legacy, verified, urca, seed],
            collector_sources={"example_programs", "ucb_ours_hub"},
        )

        assert count == 1
        assert legacy["metadata"]["is_active"] is False
        assert legacy["metadata"]["deactivation_reason"] == (
            "legacy_discovery_missing_detail_page_evidence"
        )
        assert verified["metadata"]["is_active"] is True
        assert urca["metadata"]["is_active"] is True
        assert seed["metadata"]["is_active"] is True

    def test_closed_seed_is_not_active(self):
        source = PRINCETON["sources"][0]
        spec = source["programs"][0]

        record = cg._normalize_program(
            PRINCETON,
            source,
            spec,
            status="closed",
        )

        assert record["metadata"]["status"] == "closed"
        assert record["metadata"]["is_active"] is False


# --- Per-school: Princeton (the reference config) ---------------------------

class TestPrinceton:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(PRINCETON, deep=False)

    def test_in_registry(self):
        assert PRINCETON in SCHOOL_CONFIGS

    def test_all_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "career", "lab"} <= levels

    def test_summer_programs_present(self, recs):
        assert any(o["opportunity_type"] == "summer_program" for o in recs)

    def test_every_record_is_princeton_scoped(self, recs):
        for o in recs:
            # campus + lab buckets are princeton-homed; open (if any) is national.
            assert o["school"] in ("princeton", None)
            assert o["organization"]
            assert o["location"] == "Princeton, NJ"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)
        assert sum(bd["by_opportunity_type"].values()) == len(recs)


# --- Per-school: UC San Diego (first UC-system rollout school) --------------

class TestUcsd:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(UCSD, deep=False)

    def test_in_registry(self):
        assert UCSD in SCHOOL_CONFIGS

    def test_all_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "career", "lab"} <= levels

    def test_summer_programs_present(self, recs):
        assert any(o["opportunity_type"] == "summer_program" for o in recs)

    def test_every_record_is_ucsd_scoped(self, recs):
        for o in recs:
            # campus + lab buckets are ucsd-homed; open (if any) is national.
            assert o["school"] in ("ucsd", None)
            assert o["organization"]
            assert o["location"] == "La Jolla, CA"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)
        assert sum(bd["by_opportunity_type"].values()) == len(recs)


class TestUci:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(UCI, deep=False)

    def test_in_registry(self):
        assert UCI in SCHOOL_CONFIGS

    def test_all_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "career", "lab"} <= levels

    def test_summer_programs_present(self, recs):
        assert any(o["opportunity_type"] == "summer_program" for o in recs)

    def test_every_record_is_uci_scoped(self, recs):
        for o in recs:
            assert o["school"] in ("uci", None)
            assert o["organization"]
            assert o["location"] == "Irvine, CA"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)


class TestUcsb:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(UCSB, deep=False)

    def test_in_registry(self):
        assert UCSB in SCHOOL_CONFIGS

    def test_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "lab"} <= levels

    def test_summer_programs_present(self, recs):
        assert any(o["opportunity_type"] == "summer_program" for o in recs)

    def test_open_bucket_is_national(self, recs):
        # Cal-Bridge is a statewide consortium — emitted open (school None).
        assert any(o["school"] is None for o in recs)

    def test_every_record_is_ucsb_scoped(self, recs):
        for o in recs:
            assert o["school"] in ("ucsb", None)
            assert o["organization"]
            assert o["location"] == "Santa Barbara, CA"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)


class TestBoulder:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(BOULDER, deep=False)

    def test_in_registry(self):
        assert BOULDER in SCHOOL_CONFIGS

    def test_all_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "career", "lab"} <= levels

    def test_every_record_is_boulder_scoped(self, recs):
        for o in recs:
            assert o["school"] in ("boulder", None)
            assert o["organization"]
            assert o["location"] == "Boulder, CO"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)
