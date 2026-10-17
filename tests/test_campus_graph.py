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
from datetime import UTC, datetime

import pytest
from bs4 import BeautifulSoup

from scripts.shard_corpus import assemble, load_shards, split
from src.collectors import campus_graph as cg
from src.collectors.import_document import MAX_DEPTH, MAX_NODES
from src.collectors.schools import SCHOOL_CONFIGS
from src.collectors.schools.boulder import SCHOOL as BOULDER
from src.collectors.schools.princeton import SCHOOL as PRINCETON
from src.collectors.schools.uci import SCHOOL as UCI
from src.collectors.schools.ucsb import SCHOOL as UCSB
from src.collectors.schools.ucsd import SCHOOL as UCSD
from src.contact_instructions import CAPTURE_KEY
from src.normalizers.school_audience import SOURCE_DEFAULTS, VALID_AUDIENCES
from tests.test_faculty_graph import fake_chromium
from tests.test_import_document import CROWDED_MARKUP, _growth, crawled_page


def _observed(soup, url):
    soup._ofe_fetch_metadata = {"requested_url": url, "final_url": url,
                                "checked_at": datetime.now(UTC).isoformat()}
    return soup


def _StaticSoup(url, text="Applications open"):
    return _observed(BeautifulSoup(f"<body><p>{text}</p></body>", "html.parser"), url)

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

    def test_two_school_less_sources_flagged(self):
        # The national refresh reports a school's open programs under the one
        # source they carry (national_source).
        bad = {"school_slug": "x", "sources": [], "emit": {
            "open": ("x_external_research", None, "open"),
            "lab": ("x_external_labs", None, "open"),
        }}
        assert "more than one emit bucket stamps no school" in cg.validate(bad)


def test_splitting_a_config_by_shard_changes_no_record():
    """refresh_all collects the sources that publish in national.json on the
    national shard's run and the rest on the school's. Each half must yield
    exactly the records the whole config did, or the split itself would move
    a program between files."""
    for config in SCHOOL_CONFIGS:
        whole, _ = cg.fetch_and_normalize_with_evidence(config)
        national, _ = cg.fetch_and_normalize_with_evidence(config, national=True)
        own, _ = cg.fetch_and_normalize_with_evidence(config, national=False)
        slug = config["school_slug"]
        assert {row["id"] for row in national} | {row["id"] for row in own} == {
            row["id"] for row in whole}, slug
        assert all(row["school"] is None for row in national), slug
        assert all(row["school"] == slug for row in own), slug
        assert bool(national) is (cg.national_source(config) is not None), slug


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
        monkeypatch.setattr(cg, "_fetch", lambda url, **_: None)

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
            lambda url, **_: _StaticSoup(url) if url == urls[0] else None,
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

    @pytest.mark.parametrize("stored", ["closed", "open"])
    def test_a_loaded_page_that_states_no_status_ends_the_stored_one(
        self,
        monkeypatch,
        tmp_path,
        stored,
    ):
        # The stored word was the page's, and the page has stopped saying it:
        # Wisconsin's Sophomore Research Fellowship kept "(applications open)"
        # for three months of loaded pages that said nothing of the kind.
        source = PRINCETON["sources"][0]
        spec = source["programs"][0]
        before = cg._normalize_program(
            PRINCETON,
            source,
            spec,
            status=stored,
            seed_page_verified=True,
        )
        before["metadata"]["last_verified"] = "2026-06-01T00:00:00"
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([before]), encoding="utf-8")
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
        assert merged["metadata"]["status"] == "unknown"
        assert merged["metadata"]["is_active"] is True
        assert merged["metadata"]["last_verified"] != "2026-06-01T00:00:00"
        assert "(applications" not in merged["title"]

    def test_a_loaded_page_that_states_no_status_keeps_a_retirement(
        self,
        monkeypatch,
        tmp_path,
    ):
        source = PRINCETON["sources"][0]
        spec = source["programs"][0]
        retired = cg._normalize_program(
            PRINCETON,
            source,
            spec,
            status="open",
            seed_page_verified=True,
        )
        retired["metadata"]["is_active"] = False
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([retired]), encoding="utf-8")
        monkeypatch.setattr(cg, "PROCESSED_FILE", processed)

        cg.merge_into_processed([cg._normalize_program(
            PRINCETON, source, spec, status="unknown", seed_page_verified=True,
        )])

        [merged] = json.loads(processed.read_text(encoding="utf-8"))
        assert merged["metadata"]["status"] == "unknown"
        assert merged["metadata"]["is_active"] is False
        assert "(applications" not in merged["title"]

    @pytest.mark.parametrize("stored", ["open", "closed"])
    def test_a_discovery_whose_loaded_page_states_no_status_is_inactive(self, monkeypatch, processed, stored):
        """A discovery is active only while its own page says applications are
        open, so ending its stored word leaves it inactive either way: a
        stored "open" one that students saw leaves the listings, and a stored
        "closed" one stays hidden."""
        school = _listing_school("kept")
        source = school["sources"][0]
        source["crawl"] = cg.RECURSIVE
        hub_url, page_url = source["seeds"][0], "https://example.edu/lab/"
        anchor = "Summer Lab Research Fellowship"
        before = cg._normalize_discovered(school, source, anchor, page_url, anchor)
        before["metadata"].update({"discovered_page_verified": True, "status": stored, "is_active": stored == "open"})
        processed.write_text(json.dumps([before]), encoding="utf-8")
        hub = f'<body><p>Programs</p><a href="{page_url}">{anchor}</a></body>'
        monkeypatch.setattr(cg, "_fetch", lambda url, **_: (
            _observed(BeautifulSoup(hub, "html.parser"), url) if url == hub_url
            else _StaticSoup(url, "The application opens December 14, 2026.")))

        evidence = _refresh_school(school, deep=True, national=False)

        assert evidence["discovered_records"] == 1
        merged = _stored(processed)[before["id"]]["metadata"]
        assert merged["status"] == "unknown"
        assert merged["is_active"] is False
        assert "deactivation_reason" not in merged

    def test_div_only_closed_page_still_closes_prior_open_seed(
        self,
        monkeypatch,
        tmp_path,
    ):
        from bs4 import BeautifulSoup

        url = "https://example.edu/summer"
        source = {
            "source_name": "example_programs",
            "source_type": cg.PROGRAM,
            "emit": "campus",
            "crawl": cg.STATIC,
            "seeds": [url],
            "programs": [cg.program("summer", "Summer Research Program", url, "Curated")],
        }
        school = {
            "school_slug": "example",
            "organization": "Example University",
            "location": "Example, EX",
            "emit": {"campus": ("example_programs", "example", "campus")},
            "sources": [source],
        }
        prior = cg._normalize_program(
            school, source, source["programs"][0], status="open", seed_page_verified=True,
        )
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([prior]), encoding="utf-8")
        monkeypatch.setattr(cg, "PROCESSED_FILE", processed)
        page = BeautifulSoup(
            "<body><h1>Summer Research Program</h1>"
            "<div>The 2026 cohort has been selected.</div></body>",
            "html.parser",
        )
        monkeypatch.setattr(cg, "_fetch", lambda u, **_: _observed(page, u))

        records, evidence = cg.fetch_and_normalize_with_evidence(school, deep=True)
        assert records[0]["metadata"]["seed_page_verified"] is True
        assert records[0]["metadata"]["status"] == "closed"
        assert evidence["crawl_errors"] == []
        assert evidence["condition_capture_counts"]["unsupported"] == 1
        assert evidence["condition_capture_complete"] is False
        cg.merge_into_processed(records)

        [merged] = json.loads(processed.read_text(encoding="utf-8"))
        assert merged["metadata"]["status"] == "closed"
        assert merged["metadata"]["is_active"] is False
        assert merged["metadata"]["contact_instruction_capture"]["reason"] == "no_supported_content"

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
            lambda url, **_: _observed(seed, url) if url == seed_url else None,
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
            lambda url, **_: _observed(seed if url == seed_url else detail, url),
        )
        _status, discovered, evidence = cg._crawl_source(school, source)
        assert len(discovered) == 1
        assert discovered[0]["metadata"]["discovered_page_verified"] is True
        assert discovered[0]["metadata"]["status"] == "open"
        assert discovered[0]["metadata"]["is_active"] is True
        # Neither page has condition-capture DOM; that gap is a capture
        # receipt, not a failed page load.
        assert evidence["seed_page_errors"] == []
        assert evidence["degraded_page_errors"] == []
        assert evidence["live_pages_loaded"] == 2
        assert evidence["condition_capture_counts"]["unsupported"] == 2

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
            lambda url, **_: None if url == failed_url else _StaticSoup(url),
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

    @pytest.mark.parametrize("html", [
        "",
        "<body><div id=\"root\"></div><script>window.boot()</script></body>",
        "<title>Sign in</title><form><input type=\"password\"></form>",
    ])
    def test_a_blank_shell_or_sign_in_seed_never_completes_a_crawl(self, monkeypatch, tmp_path, html):
        # These pages carry no capture DOM either, but unlike a link hub or a
        # div-only page they show nothing to observe. Counting them as loaded
        # would retire every earlier discovery of the source.
        source = next(source for source in PRINCETON["sources"] if source["crawl"] == cg.RECURSIVE)
        prior = cg._normalize_discovered(PRINCETON, source, "Old fellowship", "https://example.edu/old", "old")
        prior["metadata"].update({"discovered_page_verified": True, "status": "open", "is_active": True})
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([prior]), encoding="utf-8")
        monkeypatch.setattr(cg, "PROCESSED_FILE", processed)
        monkeypatch.setattr(cg, "_fetch", lambda url, **_: _observed(BeautifulSoup(html, "html.parser"), url))

        records, evidence = cg.fetch_and_normalize_with_evidence(PRINCETON, deep=True)

        assert source["source_name"] not in set(evidence["complete_recursive_sources"])
        cg.merge_into_processed(records, complete_recursive_sources=set(evidence["complete_recursive_sources"]),
                                school_slug=PRINCETON["school_slug"])
        saved = {r["id"]: r for r in json.loads(processed.read_text(encoding="utf-8"))}
        assert saved[prior["id"]]["metadata"]["is_active"] is True

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


# --- A program dropped from a config retires its stored row -----------------

def _listing_school(*keys, open_keys=(), titles=None, urls=None):
    """One school: ``keys`` in a campus source, ``open_keys`` in an open one."""
    titles, urls = titles or {}, urls or {}

    def programs(names):
        return [
            cg.program(key, titles.get(key, f"{key.title()} Fellowship"),
                       urls.get(key, f"https://example.edu/{key}/"), "Curated")
            for key in names
        ]

    def source(name, emit, names):
        return {"source_name": name, "source_type": cg.PROGRAM, "emit": emit,
                "crawl": cg.STATIC, "seeds": [f"https://example.edu/{name}/"],
                "programs": programs(names)}

    return {
        "school_slug": "example",
        "organization": "Example University",
        "location": "Example, EX",
        "emit": {"campus": ("example_programs", "example", "campus"),
                 "open": ("example_external", None, "open")},
        "sources": [source("example_programs", "campus", keys),
                    source("example_external", "open", open_keys)],
    }


def _program_id(school, bucket, key):
    return cg._hash_id(school["school_slug"], school["emit"][bucket][0], key)


def _refresh_school(school, deep=False, national=None):
    """One refresh of ``school``, quick by default, merged the way refresh_all
    merges it. ``national`` picks the half: False is the school's day, True
    Sunday's, None both at once."""
    records, evidence = cg.fetch_and_normalize_with_evidence(school, deep=deep, national=national)
    listed = evidence["listed_program_keys"]
    cg.merge_into_processed(
        records,
        complete_recursive_sources=set(evidence["complete_recursive_sources"]),
        condition_capture_updates=evidence["condition_capture_updates"],
        listed_program_keys=None if listed is None else set(listed),
        national=national,
        school_slug=school["school_slug"],
    )
    return evidence


def _stored(processed):
    return {row["id"]: row for row in json.loads(processed.read_text(encoding="utf-8"))}


@pytest.fixture
def processed(monkeypatch, tmp_path):
    path = tmp_path / "opportunities.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cg, "PROCESSED_FILE", path)
    return path


class TestDroppedProgramRetirement:
    """Merge only upserts, so a program dropped from a school config used to
    keep its stored row active for good. Duke's Program II and Macalester's
    Serie Center kept sending students to 404s until fba47cb6 retired them by
    hand, and Duke's two dead Data+/Climate+ duplicates needed the same."""

    def test_a_dropped_program_is_retired_not_deleted(self, processed):
        before = _listing_school("kept", "dropped")
        _refresh_school(before)

        _refresh_school(_listing_school("kept"))

        saved = _stored(processed)
        assert len(saved) == 2
        kept = saved[_program_id(before, "campus", "kept")]["metadata"]
        dropped = saved[_program_id(before, "campus", "dropped")]["metadata"]
        assert kept["is_active"] is True
        assert dropped["is_active"] is False
        assert dropped["deactivation_reason"] == "no_longer_listed"
        assert dropped["deactivated_at"] == datetime.now(UTC).date().isoformat()

    def test_an_empty_config_retires_nothing_and_a_failed_record_stays_listed(self, monkeypatch, processed):
        school = _listing_school("first", "second", "third")
        _refresh_school(school)

        assert _refresh_school(_listing_school())["listed_program_keys"] is None
        assert all(row["metadata"]["is_active"] for row in _stored(processed).values())

        normalize = cg._normalize_program

        def fail_second(school, source, spec, **kwargs):
            if spec["key"] == "second":
                raise RuntimeError("synthetic normalization failure")
            return normalize(school, source, spec, **kwargs)

        monkeypatch.setattr(cg, "_normalize_program", fail_second)
        evidence = _refresh_school(_listing_school("first", "second"))
        assert evidence["normalization_failed"] == 1
        assert evidence["listed_program_keys"] == ["first", "second"]

        saved = _stored(processed)
        assert saved[_program_id(school, "campus", "second")]["metadata"]["is_active"] is True
        third = saved[_program_id(school, "campus", "third")]["metadata"]
        assert third["deactivation_reason"] == "no_longer_listed"

    def test_other_sources_other_schools_and_otherwise_retired_rows_are_left_alone(self, processed):
        school = _listing_school("kept", "dropped", "closed", "unsupported", open_keys=("open_dropped",))
        _refresh_school(school)
        rows = json.loads(processed.read_text(encoding="utf-8"))
        closed_id = _program_id(school, "campus", "closed")
        unsupported_id = _program_id(school, "campus", "unsupported")
        for row in rows:
            if row["id"] == closed_id:
                row["metadata"].update({"status": "closed", "is_active": False})
            if row["id"] == unsupported_id:
                row["metadata"].update({"is_active": False, "deactivated_at": "2026-09-01",
                                        "deactivation_reason": "school_unsupported"})
        source = school["sources"][0]
        discovery = cg._normalize_discovered(
            school, source, "Summer Lab Fellowship", "https://example.edu/lab/", "lab")
        discovery["metadata"].update(
            {"discovered_page_verified": True, "status": "open", "is_active": True})
        # Same source name and key, another school: only the id tells them apart.
        other_school = {**school, "school_slug": "other",
                        "emit": {"campus": ("other_programs", "other", "campus")}}
        other = cg._normalize_program(other_school, source, source["programs"][1])
        faculty = {"id": "faculty-example-1", "source": "example_faculty",
                   "source_type": "faculty_research", "school": "example",
                   "metadata": {"is_active": True}}
        processed.write_text(json.dumps([*rows, discovery, other, faculty]), encoding="utf-8")

        _refresh_school(_listing_school("kept"), national=False)

        saved = _stored(processed)
        assert saved[_program_id(school, "campus", "dropped")]["metadata"]["is_active"] is False
        # An "open" row lives in national.json, which the school's day does
        # not publish, so retiring it then would never reach production: the
        # national day retires it (the next test).
        open_row = saved[_program_id(school, "open", "open_dropped")]
        assert open_row["school"] is None
        assert open_row["metadata"]["is_active"] is True
        assert "deactivation_reason" not in open_row["metadata"]
        # A closed row retires too, and keeps its closure.
        closed = saved[closed_id]
        assert (closed["metadata"]["status"], closed["metadata"]["is_active"]) == ("closed", False)
        assert closed["metadata"]["deactivation_reason"] == "no_longer_listed"
        assert saved[unsupported_id] == next(row for row in rows if row["id"] == unsupported_id)
        for row in (discovery, other, faculty):
            assert saved[row["id"]]["metadata"]["is_active"] is True
            assert "deactivation_reason" not in saved[row["id"]]["metadata"]

    @pytest.mark.parametrize("open_kept", [("open_kept",), ()], ids=["one_left", "none_left"])
    def test_the_national_day_retires_a_dropped_open_program_and_no_school_row(self, processed, open_kept):
        """The school's day lists only its own sources' keys and the national
        day only the open source's, each retiring in the file it publishes.
        An open source left with no program lists none, and its last row
        retires too."""
        _refresh_school(_listing_school("kept", "dropped", open_keys=("open_dropped", *open_kept)))
        after = _listing_school("kept", open_keys=open_kept)

        evidence = _refresh_school(after, national=True)

        assert evidence["listed_program_keys"] == list(open_kept)
        saved = _stored(processed)
        dropped = saved[_program_id(after, "open", "open_dropped")]
        assert dropped["school"] is None
        assert dropped["metadata"]["is_active"] is False
        assert dropped["metadata"]["deactivation_reason"] == "no_longer_listed"
        for key in open_kept:
            assert saved[_program_id(after, "open", key)]["metadata"]["is_active"] is True
        # The school's own rows are its day's to retire.
        assert saved[_program_id(after, "campus", "dropped")]["metadata"]["is_active"] is True

    def test_a_program_listed_again_comes_back(self, processed):
        school = _listing_school("kept", "back")
        back_id = _program_id(school, "campus", "back")
        _refresh_school(school)
        _refresh_school(_listing_school("kept"))
        assert _stored(processed)[back_id]["metadata"]["is_active"] is False

        _refresh_school(school)

        metadata = _stored(processed)[back_id]["metadata"]
        assert metadata["is_active"] is True
        assert "deactivated_at" not in metadata
        assert "deactivation_reason" not in metadata

    def test_a_second_run_changes_nothing_it_already_retired(self, processed):
        before = _listing_school("kept", "dropped")
        dropped_id = _program_id(before, "campus", "dropped")
        _refresh_school(before)
        _refresh_school(_listing_school("kept"))
        rows = json.loads(processed.read_text(encoding="utf-8"))
        for row in rows:
            if row["id"] == dropped_id:
                row["metadata"]["deactivated_at"] = "2026-09-01"
        processed.write_text(json.dumps(rows), encoding="utf-8")
        retired = _stored(processed)[dropped_id]

        _refresh_school(_listing_school("kept"))

        assert _stored(processed)[dropped_id] == retired

    def test_a_renamed_key_takes_over_the_page_of_its_retired_row(self, processed):
        """The new record shares the old row's URL and title, which the
        near-duplicate filter would otherwise hold against it: the program
        would vanish, its old row retired and its new one suppressed."""
        url = "https://example.edu/summer/"
        before = _listing_school("old_key", titles={"old_key": "Summer Fellowship"},
                                 urls={"old_key": url})
        after = _listing_school("new_key", titles={"new_key": "Summer Fellowship"},
                                urls={"new_key": url})
        _refresh_school(before)

        _refresh_school(after)

        saved = _stored(processed)
        old = saved[_program_id(before, "campus", "old_key")]["metadata"]
        assert old["deactivation_reason"] == "no_longer_listed"
        assert saved[_program_id(after, "campus", "new_key")]["metadata"]["is_active"] is True

    def test_a_closed_program_renamed_with_its_url_is_listed_again_when_it_reopens(self, monkeypatch, processed):
        url = "https://example.edu/summer/"
        before = _listing_school("old_key", titles={"old_key": "Summer Fellowship"}, urls={"old_key": url})
        after = _listing_school("new_key", titles={"new_key": "Summer Fellowship"}, urls={"new_key": url})
        for school in (before, after):
            school["sources"][0]["seeds"] = [url]
        page = {"word": "Applications are now closed."}
        monkeypatch.setattr(cg, "_fetch", lambda requested, **_: _StaticSoup(requested, page["word"]))
        _refresh_school(before, deep=True)

        _refresh_school(after, deep=True)
        page["word"] = "Applications are now open!"
        _refresh_school(after, deep=True)

        saved = _stored(processed)
        assert [(row["metadata"]["collector_key"], row["metadata"]["status"])
                for row in saved.values() if row["metadata"]["is_active"]] == [("new_key", "open")]
        old = saved[_program_id(before, "campus", "old_key")]["metadata"]
        assert (old["status"], old["is_active"], old["deactivation_reason"]) == ("closed", False, "no_longer_listed")

    @pytest.mark.parametrize("unread", ["page_fails", "quick_run"])
    def test_a_closed_program_renamed_with_its_url_waits_for_a_run_that_reads_its_page(
            self, monkeypatch, processed, unread):
        """Its retired row gives up its page only to a record whose page
        loaded. Landing on a run that read nothing, the record was listed
        under a plain title, though the page last said closed."""
        url = "https://example.edu/summer/"
        before = _listing_school("old_key", titles={"old_key": "Summer Fellowship"}, urls={"old_key": url})
        after = _listing_school("new_key", titles={"new_key": "Summer Fellowship"}, urls={"new_key": url})
        for school in (before, after):
            school["sources"][0]["seeds"] = [url]
        monkeypatch.setattr(cg, "_fetch", lambda requested, **_: _StaticSoup(requested, "Applications are now closed."))
        _refresh_school(before, deep=True)
        old_id, new_id = _program_id(before, "campus", "old_key"), _program_id(after, "campus", "new_key")
        stored = _stored(processed)[old_id]

        if unread == "page_fails":
            monkeypatch.setattr(cg, "_fetch", lambda requested, **_: None)
        _refresh_school(after, deep=unread == "page_fails")

        saved = _stored(processed)
        assert new_id not in saved
        old = saved[old_id]
        assert (old["title"], old["metadata"]["status"], old["metadata"]["is_active"]) == (
            stored["title"], "closed", False)
        assert old["metadata"]["deactivation_reason"] == "no_longer_listed"

        monkeypatch.setattr(cg, "_fetch", lambda requested, **_: _StaticSoup(requested, "Applications are now open!"))
        _refresh_school(after, deep=True)

        assert [(row["metadata"]["collector_key"], row["metadata"]["status"])
                for row in _stored(processed).values() if row["metadata"]["is_active"]] == [("new_key", "open")]

    @pytest.mark.parametrize("unread", ["page_fails", "quick_run"])
    def test_a_closed_program_on_a_shared_page_renamed_with_its_url_waits_for_a_run_that_reads_its_page(
            self, monkeypatch, processed, unread):
        """A record on a page its config shares with another program
        (shared_program_page) skips the near-duplicate filter, so it took no
        retired row's claim, and landed listed under a plain title on a run
        that read nothing, though the page last said closed."""
        url = "https://example.edu/hub/"
        titles = {"alpha": "Alpha Fellowship", "alpha2": "Alpha Fellowship", "beta": "Beta Grant"}
        before = _listing_school("alpha", "beta", titles=titles, urls={"alpha": url, "beta": url})
        after = _listing_school("alpha2", "beta", titles=titles, urls={"alpha2": url, "beta": url})
        for school in (before, after):
            school["sources"][0]["seeds"] = [url]
        page = {"word": "Applications are now closed."}
        monkeypatch.setattr(cg, "_fetch", lambda requested, **_: (
            None if page["word"] is None else _StaticSoup(requested, page["word"])))
        _refresh_school(before, deep=True)
        assert not any(row["metadata"]["is_active"] for row in _stored(processed).values())

        if unread == "page_fails":
            page["word"] = None
        _refresh_school(after, deep=unread == "page_fails")

        saved = _stored(processed)
        assert _program_id(after, "campus", "alpha2") not in saved
        assert not any(row["metadata"]["is_active"] for row in saved.values())

        page["word"] = "Applications are now open!"
        _refresh_school(after, deep=True)

        assert sorted((row["metadata"]["collector_key"], row["metadata"]["status"])
                      for row in _stored(processed).values() if row["metadata"]["is_active"]) == [
            ("alpha2", "open"), ("beta", "open")]

    @pytest.mark.parametrize("unread", ["page_fails", "quick_run"])
    def test_a_closed_program_moved_to_the_lab_bucket_on_a_shared_page_waits_by_its_key(
            self, monkeypatch, processed, unread):
        """Moved from the campus bucket to the lab bucket of its school's
        file, a program gets a new id but keeps its key. On a page its config
        shares with another program its record skips the near-duplicate
        filter, and the closed row with its key holds it until a run reads
        its page."""
        url = "https://example.edu/hub/"
        titles = {"alpha": "Alpha Fellowship", "beta": "Beta Grant"}
        before = _listing_school("alpha", "beta", titles=titles, urls={"alpha": url, "beta": url})
        after = _listing_school("beta", titles=titles, urls={"beta": url})
        after["sources"].append({"source_name": "example_labs", "source_type": cg.LAB, "emit": "lab",
                                 "crawl": cg.STATIC, "seeds": [url],
                                 "programs": [cg.program("alpha", titles["alpha"], url, "Curated")]})
        for school in (before, after):
            school["emit"]["lab"] = ("example_labs", "example", "unknown")
            school["sources"][0]["seeds"] = [url]
        page = {"word": "Applications are now closed."}
        monkeypatch.setattr(cg, "_fetch", lambda requested, **_: (
            None if page["word"] is None else _StaticSoup(requested, page["word"])))
        _refresh_school(before, deep=True)
        moved = _program_id(after, "lab", "alpha")

        if unread == "page_fails":
            page["word"] = None
        _refresh_school(after, deep=unread == "page_fails")

        assert moved not in _stored(processed)

        page["word"] = "Applications are now open!"
        _refresh_school(after, deep=True)

        metadata = _stored(processed)[moved]["metadata"]
        assert (metadata["status"], metadata["is_active"]) == ("open", True)

    @staticmethod
    def _in_bucket(bucket, url):
        """``alpha`` on ``url`` in the campus or the lab source of the school's
        file, beside ``kept`` in the campus source."""
        school = _listing_school("kept", *(["alpha"] if bucket == "campus" else []),
                                 titles={"alpha": "Alpha Fellowship"}, urls={"alpha": url})
        school["emit"]["lab"] = ("example_labs", "example", "unknown")
        school["sources"][0]["seeds"] = [url]
        school["sources"].append({"source_name": "example_labs", "source_type": cg.LAB, "emit": "lab",
                                  "crawl": cg.STATIC, "seeds": [url], "programs": [
                                      cg.program("alpha", "Alpha Fellowship", url, "Curated")] if bucket == "lab" else []})
        return school

    @pytest.mark.parametrize("before,after", [("campus", "lab"), ("lab", "campus")])
    def test_a_closed_program_moved_between_the_campus_and_lab_sources_is_listed_when_its_page_reopens(
            self, monkeypatch, processed, before, after):
        """Moved between the campus and lab sources of its school's file, a
        program keeps its key but gets a new id. Its old row, its key still
        listed, never retired, and held its page against the new record as a
        near-duplicate, so the program stayed hidden after its page reopened.
        The new record replaces the old row, which retires, and waits for a run
        that reads the page as a renamed one does."""
        url = "https://example.edu/alpha/"
        page = {"word": "Applications are now closed."}
        monkeypatch.setattr(cg, "_fetch", lambda requested, **_: (
            None if page["word"] is None else _StaticSoup(requested, page["word"])))
        _refresh_school(self._in_bucket(before, url), deep=True)
        old_id, new_id = _program_id(self._in_bucket(before, url), before, "alpha"), _program_id(
            self._in_bucket(after, url), after, "alpha")

        _refresh_school(self._in_bucket(after, url))

        saved = _stored(processed)
        assert new_id not in saved
        old = saved[old_id]["metadata"]
        assert (old["status"], old["is_active"], old["deactivation_reason"]) == ("closed", False, "no_longer_listed")
        assert [row["id"] for row in saved.values() if row["metadata"].get("deactivation_reason")] == [old_id]

        page["word"] = "Applications are now open!"
        _refresh_school(self._in_bucket(after, url), deep=True)

        saved = _stored(processed)
        assert sorted((row["id"], row["metadata"]["status"]) for row in saved.values()
                      if row["metadata"]["is_active"] and row["metadata"]["collector_key"] == "alpha") == [
            (new_id, "open")]
        assert [row["id"] for row in saved.values() if row["metadata"].get("deactivation_reason")] == [old_id]

    @pytest.mark.parametrize("before,after", [("campus", "lab"), ("lab", "campus")])
    def test_an_open_program_moved_between_the_campus_and_lab_sources_is_hidden_when_its_page_closes(
            self, monkeypatch, processed, before, after):
        """The old row stayed listed open after a deep run read the page
        closed: the reading went to the new record, dropped as the old row's
        near-duplicate."""
        url = "https://example.edu/alpha/"
        page = {"word": "Applications are now open!"}
        monkeypatch.setattr(cg, "_fetch", lambda requested, **_: _StaticSoup(requested, page["word"]))
        _refresh_school(self._in_bucket(before, url), deep=True)
        old_id, new_id = _program_id(self._in_bucket(before, url), before, "alpha"), _program_id(
            self._in_bucket(after, url), after, "alpha")

        _refresh_school(self._in_bucket(after, url), deep=True)
        page["word"] = "Applications are now closed."
        _refresh_school(self._in_bucket(after, url), deep=True)

        saved = _stored(processed)
        assert not any(row["metadata"]["is_active"] for row in saved.values()
                       if row["metadata"]["collector_key"] == "alpha")
        assert (saved[new_id]["metadata"]["status"], saved[new_id]["metadata"]["is_active"]) == ("closed", False)
        old = saved[old_id]["metadata"]
        assert (old["status"], old["is_active"], old["deactivation_reason"]) == ("open", False, "no_longer_listed")
        assert [row["id"] for row in saved.values() if row["metadata"].get("deactivation_reason")] == [old_id]

    def test_a_near_duplicate_of_another_program_is_still_dropped_and_retires_nothing(self, processed):
        """Only a record under a row's own key replaces it. A new key titled
        like a program still listed in its source, or on another school's
        page, is that row's near-duplicate, as before."""
        url = "https://example.edu/alpha/"
        before = self._in_bucket("lab", url)
        _refresh_school(before)
        other_school = {**before, "school_slug": "other", "emit": {"campus": ("other_programs", "other", "campus")}}
        theirs = cg._normalize_program(other_school, other_school["sources"][0], cg.program(
            "theirs", "Their Fellowship", "https://example.edu/theirs/", "Curated"))
        rows = json.loads(processed.read_text(encoding="utf-8"))
        processed.write_text(json.dumps([*rows, theirs]), encoding="utf-8")
        after = self._in_bucket("lab", url)
        after["sources"][1]["programs"].append(
            cg.program("alpha_twin", "Alpha Fellowship", "https://example.edu/alpha-twin/", "Curated"))
        after["sources"][1]["programs"].append(
            cg.program("their_twin", "Twin Grant", theirs["url"], "Curated"))

        _refresh_school(after)

        saved = _stored(processed)
        assert _program_id(after, "lab", "alpha_twin") not in saved
        assert _program_id(after, "lab", "their_twin") not in saved
        assert all(row["metadata"]["is_active"] and "deactivation_reason" not in row["metadata"]
                   for row in saved.values())

    @pytest.mark.parametrize("unread", ["page_fails", "quick_run"])
    def test_a_program_renamed_back_after_its_page_closed_waits_for_a_run_that_reads_its_page(
            self, monkeypatch, processed, unread):
        """Renamed back, the program's record is its first key's retired row,
        which came back as it was retired, listed open, though the page had
        since said closed on the second key's row."""
        url = "https://example.edu/summer/"
        first = _listing_school("first_key", titles={"first_key": "Summer Fellowship"}, urls={"first_key": url})
        second = _listing_school("second_key", titles={"second_key": "Summer Fellowship"}, urls={"second_key": url})
        for school in (first, second):
            school["sources"][0]["seeds"] = [url]
        page = {"word": "Applications are now open!"}
        monkeypatch.setattr(cg, "_fetch", lambda requested, **_: (
            None if page["word"] is None else _StaticSoup(requested, page["word"])))
        _refresh_school(first, deep=True)
        _refresh_school(second, deep=True)
        page["word"] = "Applications are now closed."
        _refresh_school(second, deep=True)
        assert not any(row["metadata"]["is_active"] for row in _stored(processed).values())

        if unread == "page_fails":
            page["word"] = None
        _refresh_school(first, deep=unread == "page_fails")

        saved = _stored(processed)
        assert not any(row["metadata"]["is_active"] for row in saved.values())
        first_row = saved[_program_id(first, "campus", "first_key")]
        assert first_row["metadata"]["deactivation_reason"] == "no_longer_listed"

        page["word"] = "Applications are now open!"
        _refresh_school(first, deep=True)

        assert [(row["metadata"]["collector_key"], row["metadata"]["status"])
                for row in _stored(processed).values() if row["metadata"]["is_active"]] == [("first_key", "open")]

    def test_a_closed_program_listed_again_comes_back_closed(self, processed):
        """Its row retired keeping its closure. A quick run reads no page and
        carries the row's state forward, so the closure comes back with it."""
        school = _listing_school("kept", "back")
        back_id = _program_id(school, "campus", "back")
        _refresh_school(school)
        rows = json.loads(processed.read_text(encoding="utf-8"))
        for row in rows:
            if row["id"] == back_id:
                row["metadata"].update({"status": "closed", "is_active": False})
        processed.write_text(json.dumps(rows), encoding="utf-8")
        _refresh_school(_listing_school("kept"))
        assert _stored(processed)[back_id]["metadata"]["deactivation_reason"] == "no_longer_listed"

        _refresh_school(school)

        metadata = _stored(processed)[back_id]["metadata"]
        assert (metadata["status"], metadata["is_active"]) == ("closed", False)
        assert "deactivation_reason" not in metadata

    def test_other_retired_rows_keep_their_page_against_a_new_program(self, processed):
        """Only this school's own program rows retired as no longer listed give
        up their page. Other collectors retire rows with the same reason
        (simplify_internships does), and another school's retired program is
        no replacement of this one's: both keep the claim every stored row has
        against a new near-duplicate."""
        _refresh_school(_listing_school("kept"))
        retired = {"is_active": False, "deactivated_at": "2026-09-01", "deactivation_reason": "no_longer_listed"}
        internship = {"id": "simplify-0001", "source": "simplify_internships", "source_type": "internship",
                      "school": None, "title": "Data Internship", "url": "https://example.edu/internship/",
                      "metadata": dict(retired)}
        other_school = {**_listing_school(), "school_slug": "other",
                        "emit": {"campus": ("other_programs", "other", "campus")}}
        theirs = cg._normalize_program(other_school, other_school["sources"][0], cg.program(
            "theirs", "Their Fellowship", "https://example.edu/theirs/", "Curated"))
        theirs["metadata"].update(retired)
        rows = json.loads(processed.read_text(encoding="utf-8"))
        processed.write_text(json.dumps([*rows, internship, theirs]), encoding="utf-8")

        after = _listing_school("kept", "new_a", "new_b",
                                urls={"new_a": internship["url"], "new_b": theirs["url"]})
        _refresh_school(after)

        saved = _stored(processed)
        assert _program_id(after, "campus", "new_a") not in saved
        assert _program_id(after, "campus", "new_b") not in saved

    def test_a_retired_row_keeps_its_page_against_a_discovery(self, monkeypatch, processed):
        """A crawl that finds a link to a dropped program's page has found the
        page, not the program's replacement."""
        before = _listing_school("kept", "dropped")
        dropped_id = _program_id(before, "campus", "dropped")
        dropped_url = "https://example.edu/dropped/"
        _refresh_school(before)
        after = _listing_school("kept")
        after["sources"][0]["crawl"] = cg.RECURSIVE
        hub_url = after["sources"][0]["seeds"][0]
        hub = f'<body><p>Programs</p><a href="{dropped_url}">Dropped Summer Research Fellowship</a></body>'
        monkeypatch.setattr(cg, "_fetch", lambda url, **_: (
            _observed(BeautifulSoup(hub, "html.parser"), url) if url == hub_url else _StaticSoup(url)))

        evidence = _refresh_school(after, deep=True)

        assert evidence["discovered_records"] == 1
        saved = _stored(processed)
        assert [row["id"] for row in saved.values() if row["url"] == dropped_url] == [dropped_id]
        assert saved[dropped_id]["metadata"]["deactivation_reason"] == "no_longer_listed"

    def test_a_stored_discovery_on_a_retired_rows_page_still_updates(self, monkeypatch, processed):
        """Holding the retired row's page against discoveries stops a new one
        landing there; one already stored is an upsert, not a near-duplicate."""
        before = _listing_school("kept", "dropped")
        _refresh_school(before)
        after = _listing_school("kept")
        after["sources"][0]["crawl"] = cg.RECURSIVE
        hub_url, dropped_url = after["sources"][0]["seeds"][0], "https://example.edu/dropped/"
        anchor = "Dropped Summer Research Fellowship"
        stored = cg._normalize_discovered(after, after["sources"][0], anchor, dropped_url, anchor)
        stored["metadata"].update({"discovered_page_verified": True, "status": "open", "is_active": True,
                                   "last_verified": "2026-09-01T00:00:00"})
        rows = json.loads(processed.read_text(encoding="utf-8"))
        processed.write_text(json.dumps([*rows, stored]), encoding="utf-8")
        hub = f'<body><p>Programs</p><a href="{dropped_url}">{anchor}</a></body>'
        monkeypatch.setattr(cg, "_fetch", lambda url, **_: (
            _observed(BeautifulSoup(hub, "html.parser"), url) if url == hub_url else _StaticSoup(url)))

        _refresh_school(after, deep=True)

        saved = _stored(processed)
        assert saved[_program_id(before, "campus", "dropped")]["metadata"]["deactivation_reason"] == "no_longer_listed"
        assert saved[stored["id"]]["metadata"]["last_verified"] != "2026-09-01T00:00:00"

    def test_a_listed_program_the_fetch_drops_as_a_duplicate_stays(self, processed):
        """Listing is the config's, not the dedupe's: a configured program
        whose record lost a near-duplicate tie this run is still listed."""
        _refresh_school(_listing_school(
            "first", "second", titles={"first": "Summer Fellowship", "second": "Winter Fellowship"}))
        clash = _listing_school(
            "first", "second", titles={"first": "Summer Fellowship", "second": "Summer Fellowship"})
        second_id = _program_id(clash, "campus", "second")
        records, evidence = cg.fetch_and_normalize_with_evidence(clash, deep=False)
        assert second_id not in {record["id"] for record in records}
        assert "second" in evidence["listed_program_keys"]

        _refresh_school(clash)

        assert _stored(processed)[second_id]["metadata"]["is_active"] is True


class TestProgramMovesBetweenShards:
    """A program moved between a school's own bucket and its open bucket
    changes file: its stored row is in the school's shard or national.json,
    and its record now publishes in the other. Each file is written by its own
    day only (refresh-data.yml splits --only-shards), the school's shard on
    the school's day and national.json on Sunday. While every day listed every
    key of the config, the old row never retired: with the same URL the
    program stayed frozen in its old file, and with a new URL it was listed
    twice."""

    OLD_URL = "https://example.edu/moving/"
    # national.json always holds other sources' rows, so Sunday always has a
    # shard to write.
    NATIONAL_ROW = {"id": "nsf-reu-0001", "source": "nsf_reu", "source_type": "reu", "school": None,
                    "title": "Example REU Site", "url": "https://example.org/reu/",
                    "metadata": {"is_active": True}}

    @staticmethod
    def _move(to_open, url):
        """The config before and after the move, and the school value of the
        old and the new file."""
        if to_open:
            return (_listing_school("kept", "moving"),
                    _listing_school("kept", open_keys=("moving",), urls={"moving": url}), "example", None)
        return (_listing_school("kept", open_keys=("moving",)),
                _listing_school("kept", "moving", urls={"moving": url}), None, "example")

    def _commit(self, processed, shards, school):
        """The committed corpus: ``school`` refreshed and every shard written."""
        _refresh_school(school)
        rows = json.loads(processed.read_text(encoding="utf-8"))
        processed.write_text(json.dumps([*rows, self.NATIONAL_ROW]), encoding="utf-8")
        split(processed, shards)

    @staticmethod
    def _day(processed, shards, school, national, deep=False):
        """One scheduled run: assemble the work file from the committed
        shards, refresh the half of ``school`` the day publishes, and split
        back only that day's shard."""
        assemble(processed, shards, force=True, allow_empty=True)
        _refresh_school(school, deep=deep, national=national)
        split(processed, shards, only_shards={"national" if national else school["school_slug"]})

    @staticmethod
    def _listed(shards, key):
        return [(row["school"], row["url"]) for row in load_shards(shards)
                if row["metadata"].get("collector_key") == key and row["metadata"]["is_active"]]

    @pytest.mark.parametrize("old_day_first", [True, False], ids=["old_file_day_first", "new_file_day_first"])
    @pytest.mark.parametrize("url", [OLD_URL, "https://example.edu/moving-reu/"], ids=["same_url", "new_url"])
    @pytest.mark.parametrize("to_open", [True, False], ids=["into_open", "out_of_open"])
    def test_a_moved_program_changes_file_and_is_never_listed_twice(
            self, processed, tmp_path, to_open, url, old_day_first):
        before, after, old_school, new_school = self._move(to_open, url)
        shards = tmp_path / "shards"
        self._commit(processed, shards, before)
        assert self._listed(shards, "moving") == [(old_school, self.OLD_URL)]

        # The national flag of the day that publishes the old file, and of
        # the day that publishes the new one.
        old_day, new_day = old_school is None, new_school is None
        if old_day_first:
            # The old row retires, and the program is missing until the new
            # file's day publishes it.
            days = [(old_day, []), (new_day, [(new_school, url)])]
        else:
            # The moved record waits while the old row is listed, and
            # publishes on the new file's next day after that row retired.
            days = [(new_day, [(old_school, self.OLD_URL)]), (old_day, []), (new_day, [(new_school, url)])]
        for national, listed in days:
            self._day(processed, shards, after, national)
            assert self._listed(shards, "moving") == listed, national

        [old] = [row for row in load_shards(shards)
                 if row["metadata"].get("collector_key") == "moving" and row["school"] == old_school]
        assert old["metadata"]["deactivation_reason"] == "no_longer_listed"
        assert self._listed(shards, "kept") == [("example", "https://example.edu/kept/")]
        assert self.NATIONAL_ROW in load_shards(shards)

    @pytest.mark.parametrize("old_day_first", [True, False], ids=["old_file_day_first", "new_file_day_first"])
    @pytest.mark.parametrize("to_open", [True, False], ids=["into_open", "out_of_open"])
    def test_a_closed_program_moved_with_its_url_is_listed_again_when_it_reopens(
            self, monkeypatch, processed, tmp_path, to_open, old_day_first):
        """The listing rule skipped a closed row, so the row kept its claim on
        its URL, and the moved record was dropped as its near-duplicate on
        every run, even after the page reopened."""
        before, after, old_school, new_school = self._move(to_open, self.OLD_URL)
        for school in (before, after):
            for source in school["sources"]:
                source["seeds"].append(self.OLD_URL)
        page = {"word": "Applications are now closed."}
        monkeypatch.setattr(cg, "_fetch", lambda url, **_: _StaticSoup(
            url, page["word"] if url == self.OLD_URL else "Program page"))
        shards = tmp_path / "shards"
        self._commit(processed, shards, before)
        old_day, new_day = old_school is None, new_school is None
        self._day(processed, shards, before, old_day, deep=True)
        assert self._listed(shards, "moving") == []

        for national in (old_day, new_day) if old_day_first else (new_day, old_day):
            self._day(processed, shards, after, national, deep=True)
            assert self._listed(shards, "moving") == []
        page["word"] = "Applications are now open!"
        for national in (old_day, new_day):
            self._day(processed, shards, after, national, deep=True)

        assert self._listed(shards, "moving") == [(new_school, self.OLD_URL)]
        [old] = [row["metadata"] for row in load_shards(shards)
                 if row["metadata"].get("collector_key") == "moving" and row["school"] == old_school]
        assert (old["status"], old["is_active"], old["deactivation_reason"]) == ("closed", False, "no_longer_listed")

    @pytest.mark.parametrize("unread", ["page_fails", "quick_run"])
    @pytest.mark.parametrize("to_open", [True, False], ids=["into_open", "out_of_open"])
    def test_a_closed_program_moved_with_its_url_waits_for_a_day_that_reads_its_page(
            self, monkeypatch, processed, tmp_path, to_open, unread):
        """The old file's day retires the closed row, which gives up its page
        only to a record whose page loaded. Landing on a day that read
        nothing, the record was listed though the page last said closed."""
        before, after, old_school, new_school = self._move(to_open, self.OLD_URL)
        for school in (before, after):
            for source in school["sources"]:
                source["seeds"].append(self.OLD_URL)
        page = {"word": "Applications are now closed."}
        monkeypatch.setattr(cg, "_fetch", lambda url, **_: None if url == self.OLD_URL and page["word"] is None
                            else _StaticSoup(url, page["word"] if url == self.OLD_URL else "Program page"))
        shards = tmp_path / "shards"
        self._commit(processed, shards, before)
        old_day, new_day = old_school is None, new_school is None
        self._day(processed, shards, before, old_day, deep=True)
        self._day(processed, shards, after, old_day, deep=True)
        assert self._listed(shards, "moving") == []

        if unread == "page_fails":
            page["word"] = None
        self._day(processed, shards, after, new_day, deep=unread == "page_fails")
        assert self._listed(shards, "moving") == []
        assert [row["school"] for row in load_shards(shards) if row["metadata"].get("collector_key") == "moving"] == [
            old_school]
        page["word"] = "Applications are now open!"
        self._day(processed, shards, after, new_day, deep=True)

        assert self._listed(shards, "moving") == [(new_school, self.OLD_URL)]

    @pytest.mark.parametrize("unread", ["page_fails", "quick_run"])
    @pytest.mark.parametrize("away_day_first", [True, False], ids=["away_file_day_first", "home_file_day_first"])
    @pytest.mark.parametrize("to_open", [True, False], ids=["into_open", "out_of_open"])
    def test_a_program_moved_back_after_its_page_closed_waits_for_a_day_that_reads_its_page(
            self, monkeypatch, processed, tmp_path, to_open, away_day_first, unread):
        """Moved back, the program's record is its retired row in its home
        file, which came back as it was retired, listed open, though the page
        had since said closed on its row in the other file, retired or not."""
        home, away, home_school, away_school = self._move(to_open, self.OLD_URL)
        for school in (home, away):
            for source in school["sources"]:
                source["seeds"].append(self.OLD_URL)
        page = {"word": "Applications are now open!"}
        monkeypatch.setattr(cg, "_fetch", lambda url, **_: None if url == self.OLD_URL and page["word"] is None
                            else _StaticSoup(url, page["word"] if url == self.OLD_URL else "Program page"))
        shards = tmp_path / "shards"
        self._commit(processed, shards, home)
        home_day, away_day = home_school is None, away_school is None
        for school, national in ((home, home_day), (away, home_day), (away, away_day)):
            self._day(processed, shards, school, national, deep=True)
        assert self._listed(shards, "moving") == [(away_school, self.OLD_URL)]
        page["word"] = "Applications are now closed."
        self._day(processed, shards, away, away_day, deep=True)
        assert self._listed(shards, "moving") == []

        if away_day_first:
            self._day(processed, shards, home, away_day, deep=True)
        if unread == "page_fails":
            page["word"] = None
        self._day(processed, shards, home, home_day, deep=unread == "page_fails")
        assert self._listed(shards, "moving") == []
        page["word"] = "Applications are now open!"
        self._day(processed, shards, home, home_day, deep=True)

        assert self._listed(shards, "moving") == [(home_school, self.OLD_URL)]

    @pytest.mark.parametrize("url", [OLD_URL, "https://example.edu/moving-reu/"], ids=["same_url", "new_url"])
    @pytest.mark.parametrize("to_open", [True, False], ids=["into_open", "out_of_open"])
    def test_one_call_that_publishes_both_files_moves_the_program_at_once(self, processed, to_open, url):
        """With national=None one call collects and publishes both halves: the
        moved key is listed, but for the other file, so its old row retires
        and its record lands in the same call."""
        before, after, old_school, new_school = self._move(to_open, url)
        _refresh_school(before)

        _refresh_school(after)

        rows = [row for row in _stored(processed).values() if row["metadata"].get("collector_key") == "moving"]
        assert sorted(((row["school"] or ""), row["url"], row["metadata"]["is_active"]) for row in rows) == sorted([
            ((old_school or ""), self.OLD_URL, False), ((new_school or ""), url, True)])

    def test_a_program_gone_from_the_whole_config_still_retires(self, processed, tmp_path):
        shards = tmp_path / "shards"
        self._commit(processed, shards, _listing_school("kept", "dropped"))

        self._day(processed, shards, _listing_school("kept"), national=False)

        [row] = [row for row in load_shards(shards) if row["metadata"].get("collector_key") == "dropped"]
        assert row["school"] == "example"
        assert row["metadata"]["is_active"] is False
        assert row["metadata"]["deactivation_reason"] == "no_longer_listed"


def test_jhu_leadership_alliance_row_is_kept_but_never_served():
    """JHU's open-bucket SR-EIP record said Johns Hopkins hosts SR-EIP sites.
    The program page's research-site list (28 entries, read 2026-10-10) names
    no Johns Hopkins site, so the record leaves the config. Its stored row is
    an "open" row in national.json, where no refresh retires it (see
    test_other_sources_other_schools_and_inactive_rows_are_left_alone), so it
    is retired in the committed shard instead, the way fba47cb6 retired Duke's
    and Macalester's rows."""
    from pathlib import Path

    from src.collectors.schools.jhu import SCHOOL as JHU
    from src.evidence import target_truth
    from src.matcher.ranker import _filter_context, hard_exclusion

    page = "https://theleadershipalliance.org/summer-research-early-identification-program"
    assert not any(
        spec["key"] == "leadership_alliance_sreip_jhu" or spec["url"] == page
        for source in JHU["sources"] for spec in source.get("programs", [])
    )
    assert not any(page in source.get("seeds", []) for source in JHU["sources"])

    national = Path(__file__).resolve().parents[1] / "data" / "processed" / "shards" / "national.json"
    [row] = [row for row in json.loads(national.read_text(encoding="utf-8"))
             if row["id"] == cg._hash_id("jhu", "jhu_external_research", "leadership_alliance_sreip_jhu")]
    assert row["metadata"]["is_active"] is False
    assert row["metadata"]["deactivation_reason"] == "no_longer_listed"
    assert row["metadata"]["deactivated_at"] == "2026-10-10"
    assert target_truth(row).actionable is False
    for profile in ({"home_school": "jhu"}, {"home_school": "uiuc", "include_cross_school": True}):
        assert hard_exclusion(row, _filter_context(profile)) == "inactive"


def test_uf_newcastle_row_is_kept_but_never_served():
    """UF's Research in Newcastle record is taken down. Its page
    (cur.aa.ufl.edu/research-in-newcastle/) returned 404 with no redirect on
    2026-10-11 and is in no sitemap, while the record said the exchange was
    "launching Summer B 2026", which no live page states. The row stays in
    uf.json for the record, retired the way a UF refresh would retire it once
    the program is out of the config, and never served."""
    from pathlib import Path

    from src.collectors.schools.uf import SCHOOL as UF
    from src.evidence import target_truth
    from src.matcher.ranker import _filter_context, hard_exclusion

    page = "https://cur.aa.ufl.edu/research-in-newcastle/"
    assert not any(
        spec["key"] == "newcastle_exchange" or spec["url"] == page
        for source in UF["sources"] for spec in source.get("programs", [])
    )
    assert not any(page in source.get("seeds", []) for source in UF["sources"])

    uf = Path(__file__).resolve().parents[1] / "data" / "processed" / "shards" / "uf.json"
    [row] = [row for row in json.loads(uf.read_text(encoding="utf-8"))
             if row["id"] == cg._hash_id("uf", "uf_research_programs", "newcastle_exchange")]
    assert row["metadata"]["is_active"] is False
    assert row["metadata"]["deactivation_reason"] == "no_longer_listed"
    assert row["metadata"]["deactivated_at"] == "2026-10-11"
    assert target_truth(row).actionable is False
    for profile in ({"home_school": "uf"}, {"home_school": "uiuc", "include_cross_school": True}):
        assert hard_exclusion(row, _filter_context(profile)) == "inactive"


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


def test_seed_fetch_completes_the_incommon_chain(monkeypatch):
    """Three seeds fail verification on certifi alone and load with the bundle.

    Measured 2026-08-08: urfm.psu.edu, www.science.smith.edu and
    labcit.ligo.caltech.edu each raise CERTIFICATE_VERIFY_FAILED against
    certifi's roots and return 200 once the InCommon intermediates are
    appended. campus_graph called requests.get without them.
    """
    import requests

    from src.collectors.ucb_common import _ca_bundle

    seen: dict = {}

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after capturing the request")

    monkeypatch.setattr(requests, "get", fake_get)
    cg._fetch("https://urfm.psu.edu/research-home")

    assert seen.get("verify") == _ca_bundle()


def test_render_source_goes_through_chromium_not_requests(monkeypatch):
    """A Cloudflare-walled source must not be fetched with a plain GET.

    Eleven of the twelve incidents open on 2026-08-15 were one wall: every
    failing seed for jhu, princeton, stanford and uva returned 403, three with
    ``cf-mitigated: challenge``, from two unrelated egresses. requests cannot
    answer that no matter what headers it sends; a real browser can, and does
    (measured 2026-08-15 against all four).
    """
    import requests

    from src.collectors import faculty_graph

    def fail_get(*args, **kwargs):
        raise AssertionError("render source fetched with requests.get")

    rendered: list[str] = []

    def fake_render(url, **kwargs):
        rendered.append(url)
        return "SOUP"

    monkeypatch.setattr(requests, "get", fail_get)
    monkeypatch.setattr(faculty_graph, "_render_soup", fake_render)

    assert cg._fetch("https://biox.stanford.edu/x", render=True) == "SOUP"
    assert rendered == ["https://biox.stanford.edu/x"]


def test_render_defaults_off_so_every_other_source_is_unchanged(monkeypatch):
    import requests

    seen: list[str] = []

    def fake_get(url, **kwargs):
        seen.append(url)
        raise RuntimeError("stop after capturing the request")

    monkeypatch.setattr(requests, "get", fake_get)
    cg._fetch("https://urfm.psu.edu/research-home")

    assert seen == ["https://urfm.psu.edu/research-home"]


def test_the_four_walled_sources_carry_render():
    """Named, because the flag is the whole fix and a merge could drop it."""
    from src.collectors.schools.jhu import SCHOOL as JHU
    from src.collectors.schools.stanford import SCHOOL as STANFORD
    from src.collectors.schools.uva import SCHOOL as UVA

    def source(config: dict, name: str) -> dict:
        return next(s for s in config["sources"] if s["source_name"] == name)

    assert source(UVA, "uva_ugr_hub")["render"] is True
    assert source(JHU, "jhu_announcement_campus")["render"] is True
    assert source(PRINCETON, "princeton_career")["render"] is True
    assert source(PRINCETON, "princeton_department_research")["render"] is True
    assert source(STANFORD, "stanford_lab")["render"] is True


# ── application status: a future or finished cycle is not an open one ──────
# Production, 2026-08-31. Northwestern SynBREU ranked #3 for a JHU biology
# sophomore as "Northwestern SynBREU — Synthetic Biology REU (applications
# open)". The program page, verbatim: "Thank you for your interest in SynBREU
# 2026! Our cohort has been formed. Applications for 2027 will be open in
# November 2026." — with an Apply Now button in the site chrome. The record's
# own deadline_note had captured the truth; the status detector had not.

SYNBREU = (
    "Apply Now  Application Deadlines  Thank you for your interest in SynBREU 2026! "
    "Our cohort has been formed. Applications for 2027 will be open in November 2026. "
    "Stay tuned!  FAQ  Q: When will applications open? A: The application site opens "
    "mid November 2026."
)


def test_a_formed_cohort_is_closed_whatever_the_navigation_says():
    assert cg.detect_application_status(SYNBREU) == "closed"


def test_a_cycle_that_opens_on_a_future_date_is_not_open_now():
    # No cohort sentence, just the FAQ and the button. Not "closed" either: the
    # detector has no calendar, and a page saying "opens November 2026" may be
    # read in December. It is simply not evidence that applications are open.
    page = "Apply Now  Q: When will applications open? A: The application site opens mid November 2026."
    assert cg.detect_application_status(page) == "unknown"
    page2 = "Apply now. Applications for 2027 will be open in November 2026."
    assert cg.detect_application_status(page2) == "unknown"


def test_a_present_tense_open_page_still_reads_open():
    assert cg.detect_application_status("Applications are now open. Apply now.") == "open"
    assert cg.detect_application_status("Applications are closed for this year.") == "closed"


def test_crawl_domain_boundary_rejects_suffix_spoofing():
    assert cg._same_site(
        "https://research.princeton.edu/program",
        "https://apply.princeton.edu/program",
    )
    assert not cg._same_site(
        "https://research.princeton.edu/program",
        "https://evilprinceton.edu/program",
    )


def test_crawl_domain_boundary_keeps_the_bare_root_and_rejects_other_schools():
    assert cg._same_site("https://research.princeton.edu/program", "https://princeton.edu/research")
    # bu.edu is a string suffix of cbu.edu, a different university.
    assert not cg._same_site("https://www.bu.edu/urop/", "https://www.cbu.edu/research/")


# ── configured pages are parsed within the import reader's limits ───────────
# campus_graph parsed each fetched page with plain bs4, outside the limits #1018
# gave URL import: on 2026-10-09 a seed page of 30,000 <br> then 30,000 </p>
# held one crawl 3.2 s of CPU, a <meta> content of 100,000 line breaks 5.4 s,
# and 2.4 MB opening with '<meta ' 3.6 s, each time quadratic in the markup.

_PAGE_A, _PAGE_B = "https://example.edu/summer", "https://example.edu/fellows"
_TWO_SEEDS = {
    "school_slug": "example", "organization": "Example University", "location": "Example",
    "emit": {"campus": ("example_research_programs", "example", "campus")},
    "sources": [{"source_name": "example_programs", "source_type": cg.PROGRAM, "emit": "campus",
                 "crawl": cg.STATIC, "crawl_depth": 1, "seeds": [_PAGE_A, _PAGE_B],
                 "programs": [cg.program("summer", "Summer research program", _PAGE_A, "Curated description"),
                              cg.program("fellows", "Research fellows program", _PAGE_B, "Curated description")]}],
}


class _Fetched:
    def __init__(self, url, html):
        self.url, self.content = url, html.encode()

    def raise_for_status(self):
        pass


def _serve(monkeypatch, pages):
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **_: _Fetched(url, pages[url]))


@pytest.mark.parametrize(("where", "build", "size"), CROWDED_MARKUP)
def test_a_crowded_configured_page_is_crawled_in_linear_time(monkeypatch, where, build, size):
    pages = {_PAGE_B: crawled_page("body", "")}
    _serve(monkeypatch, pages)

    def crawl(html):
        pages[_PAGE_A] = html
        records, _evidence = cg.fetch_and_normalize_with_evidence(_TWO_SEEDS, deep=True)
        return [record["metadata"][CAPTURE_KEY]["status"] for record in records]
    small, large = (crawled_page(where, build(count)) for count in (size // 4, size))
    assert crawl(small) == crawl(large) == ["captured", "captured"]
    growth = _growth(crawl, small, large)
    assert growth < 8, f"four times the markup took {growth:.1f} times as long"


@pytest.mark.parametrize("markup", [
    pytest.param("<div>" * (MAX_DEPTH + 1) + "x", id="too-deep"),
    pytest.param("<i></i>" * MAX_NODES, id="too-many-nodes"),
])
def test_a_configured_page_past_the_limits_fails_that_page_alone(monkeypatch, markup):
    _serve(monkeypatch, {_PAGE_A: crawled_page("body", markup), _PAGE_B: crawled_page("body", "")})
    records, evidence = cg.fetch_and_normalize_with_evidence(_TWO_SEEDS, deep=True)
    captures = {record["url"]: record["metadata"][CAPTURE_KEY] for record in records}
    assert (captures[_PAGE_A]["status"], captures[_PAGE_A]["reason"]) == ("failed", "too_large")
    assert captures[_PAGE_B]["status"] == "captured"
    assert evidence["crawl_errors"] == [f"example_programs: seed fetch failed: {_PAGE_A}"]
    assert (evidence["seed_pages_loaded"], evidence["seed_pages_failed"]) == (1, 1)


def test_a_rendered_page_past_the_limits_fails_that_page_alone(monkeypatch):
    rendered = {_PAGE_A: crawled_page("body", "<div>" * (MAX_DEPTH + 1) + "x"), _PAGE_B: crawled_page("body", "")}
    fake_chromium(monkeypatch, rendered)
    school = {**_TWO_SEEDS, "sources": [{**_TWO_SEEDS["sources"][0], "render": True}]}
    records, evidence = cg.fetch_and_normalize_with_evidence(school, deep=True)
    captures = {record["url"]: record["metadata"][CAPTURE_KEY] for record in records}
    assert (captures[_PAGE_A]["status"], captures[_PAGE_A]["reason"]) == ("failed", "too_large")
    assert captures[_PAGE_B]["status"] == "captured"
    assert evidence["crawl_errors"] == [f"example_programs: seed fetch failed: {_PAGE_A}"]
    assert len(rendered["calls"]) == 2, "a page past the limits is not rendered again"

