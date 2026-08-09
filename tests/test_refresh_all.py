"""Offline registration tests for src.collectors.refresh_all.

No network: every fetch_*/merge_* alias in the refresh_all namespace is
monkeypatched out and PROCESSED_FILE is pointed at a missing path (which skips
the PI-enrichment / deactivation block). What's locked in:

  * which collectors run in quick vs deep mode (UCB faculty scrapers are
    deep-only; ucb_urap's static overview runs in both), and
  * ucb_eecs_faculty merges before ucb_stat_faculty — the ucb_common
    joint-appointment dedup keeps whichever record is already in the corpus,
    so this order is what makes "keep EECS, drop STAT" hold.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.collectors.refresh_all as refresh_all
from src.collectors import ucsb_urca_projects
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES

# All Berkeley faculty collectors wired into refresh_all's deep block. Derived
# from the canonical FACULTY_SOURCES set so this stays in lockstep as new
# department directories are added.
UCB_FACULTY_SOURCES = {s for s in FACULTY_SOURCES if s.startswith("ucb_")}


def _stub_all_collectors(monkeypatch, tmp_path):
    for attr in dir(refresh_all):
        if attr.startswith("fetch_"):
            monkeypatch.setattr(refresh_all, attr, lambda *a, **k: [])
        elif attr.startswith("merge_"):
            monkeypatch.setattr(
                refresh_all,
                attr,
                lambda opps, **kwargs: (0, 0),
            )
    monkeypatch.setattr(refresh_all, "PROCESSED_FILE", tmp_path / "missing.json")
    # The post-write tracking pass must never touch the repo's real artifact
    # from a test run.
    monkeypatch.setattr(refresh_all, "TRACKING_FILE", tmp_path / "professor_tracking.json")
    live_evidence = {
        "deep": True,
        "crawl_sources_expected": 1,
        "crawl_sources_loaded": 1,
        "live_pages_attempted": 1,
        "live_pages_loaded": 1,
        "seed_records": 0,
        "discovered_records": 0,
        "crawl_errors": [],
    }
    monkeypatch.setattr(
        refresh_all,
        "fetch_campus_graph_with_evidence",
        lambda *args, **kwargs: ([], live_evidence),
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_ucb_campus_with_evidence",
        lambda *args, **kwargs: ([], live_evidence),
    )
    monkeypatch.setattr(
        refresh_all,
        "merge_ucsb_urca_projects",
        lambda *args, **kwargs: (0, 0, 0),
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_ucsb_urca_projects_with_evidence",
        lambda: (
            [],
            {
                "sitemap_complete": False,
                "sitemaps_expected": 2,
                "sitemaps_loaded": 0,
                "locations_seen": 0,
                "recognized_locations": 0,
                "unexpected_location_count": 0,
                "unexpected_location_samples": [],
                "empty_confirmed": False,
            },
        ),
    )


def test_deep_run_registers_all_ucb_collectors(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True)
    sources = summary["sources"]
    for name in {"ucb_urap", *UCB_FACULTY_SOURCES}:
        assert sources[name]["status"] == "ok", name


def test_ucb_campus_runs_in_both_quick_and_deep(monkeypatch, tmp_path):
    """Acceptance: the UC Berkeley campus opportunity graph (ucb_campus) is
    wired into refresh_all and runs in BOTH modes — its curated seed layer is
    network-free so it is not gated behind deep mode (only its live crawl is).
    Asserted explicitly so the campus collector can't be silently dropped from
    the pipeline the way it had no test coverage before."""
    for deep in (True, False):
        _stub_all_collectors(monkeypatch, tmp_path)
        summary = refresh_all.refresh_all(deep=deep)
        assert "ucb_campus" in summary["sources"], f"ucb_campus missing (deep={deep})"
        assert summary["sources"]["ucb_campus"]["status"] == "ok", deep


def test_no_silent_ucb_source_omissions(monkeypatch, tmp_path):
    """Acceptance / no-silent-omissions: a deep run must exercise EVERY UC
    Berkeley collector the system knows about — the campus graph (ucb_campus),
    URAP, and all faculty directories (FACULTY_SOURCES). Dropping any of them
    from refresh_all (e.g. forgetting to wire a newly added collector) makes
    this fail loudly instead of silently shrinking coverage."""
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True)
    ran = {name for name, info in summary["sources"].items() if info.get("status") == "ok"}
    expected = {"ucb_campus", "ucb_urap", *UCB_FACULTY_SOURCES}
    missing = expected - ran
    assert not missing, f"UC Berkeley collectors wired but not executed by refresh_all: {sorted(missing)}"


def test_every_wired_faculty_source_is_registered(monkeypatch, tmp_path):
    """Guardrail against FACULTY_SOURCES drift.

    Every faculty collector wired into refresh_all (each emits a summary key
    ending in ``_faculty``) MUST be registered in
    deactivate_stale_faculty.FACULTY_SOURCES — otherwise a professor removed
    from that department's directory would never be marked inactive, because
    the stale-deactivation pass only considers sources it knows about.

    This catches the exact failure mode "added a collector to refresh_all but
    forgot to register it for stale detection": the new source appears in the
    run summary but is absent from FACULTY_SOURCES, and this assertion fails
    loudly in CI. Introspects the real run (not the source text), so it can't
    drift out of sync with the actual wiring.
    """
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True)
    wired_faculty = {name for name in summary["sources"] if name.endswith("_faculty")}
    unregistered = wired_faculty - FACULTY_SOURCES
    assert not unregistered, (
        "faculty collectors wired into refresh_all but missing from "
        "FACULTY_SOURCES (stale detection would never retire their professors): "
        f"{sorted(unregistered)} — add them to "
        "src/normalizers/deactivate_stale_faculty.py"
    )


def test_quick_run_skips_ucb_faculty_but_keeps_ucb_urap(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=False)
    sources = summary["sources"]
    assert sources["ucb_urap"]["status"] == "ok"
    assert not UCB_FACULTY_SOURCES & sources.keys()


def test_eecs_merges_before_stat(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    order: list[str] = []
    for dept in ("eecs", "stat", "chem", "cee"):
        monkeypatch.setattr(refresh_all, f"merge_ucb_{dept}",
                            lambda opps, dept=dept: (order.append(dept), (0, 0))[1])
    refresh_all.refresh_all(deep=True)
    # EECS-before-STAT is the binding constraint (joint-appointment dedup
    # keeps the richer EECS record); chem/cee just follow.
    assert order == ["eecs", "stat", "chem", "cee"]


def test_ucb_faculty_error_is_isolated(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)

    def boom():
        raise RuntimeError("connection reset")

    monkeypatch.setattr(refresh_all, "fetch_ucb_stat", boom)
    summary = refresh_all.refresh_all(deep=True)
    sources = summary["sources"]
    assert sources["ucb_stat_faculty"]["status"] == "error"
    assert "connection reset" in sources["ucb_stat_faculty"]["error"]
    # The failure must not take down the sibling collectors.
    assert sources["ucb_eecs_faculty"]["status"] == "ok"
    assert sources["ucb_urap"]["status"] == "ok"


# --- Stale-faculty deactivation wiring ---------------------------------------
#
# Same offline stubbing, but PROCESSED_FILE points at a real tmp file seeded
# with faculty records so the post-merge block (PI enrichment is stubbed out)
# runs the deactivate_stale_faculty pass against them.


def _seed_faculty(source, ident, days_ago):
    last_seen = (date.today() - timedelta(days=days_ago)).isoformat() + "T00:00:00"
    return {
        "id": ident,
        "source": source,
        "source_type": "faculty_research",
        "department": "Test Department",
        "title": f"Research with Prof. {ident}",
        "deadline": None,
        "metadata": {
            "first_seen_at": "2026-01-01T00:00:00",
            "last_seen_at": last_seen,
            "is_active": True,
        },
    }


def _stub_with_processed_file(monkeypatch, tmp_path, seeded):
    _stub_all_collectors(monkeypatch, tmp_path)
    processed = tmp_path / "opportunities.json"
    processed.write_text(json.dumps(seeded), encoding="utf-8")
    monkeypatch.setattr(refresh_all, "PROCESSED_FILE", processed)
    monkeypatch.setattr(
        refresh_all, "enrich_pi",
        lambda opps, save=True, max_scrapes=None: {
            "scraped": 0, "enriched": 0, "already_has_email": 0, "skipped_budget": 0})
    monkeypatch.setattr(refresh_all, "_null_shared_admin_emails", lambda opps: 0)
    return processed


def _stub_successful_uiuc_deep_components(monkeypatch):
    monkeypatch.setattr(
        refresh_all,
        "fetch_js_faculty",
        lambda: [{"id": "js-one"}],
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_json_faculty",
        lambda: [{"id": "json-one"}],
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_html_faculty",
        lambda: [{"id": "html-one"}],
    )
    monkeypatch.setattr(
        refresh_all,
        "faculty_missing_departments",
        lambda _records: [],
    )


def test_discovery_quarantine_preserves_verified_seed_and_urca_records(
    monkeypatch,
    tmp_path,
):
    def row(ident, *, metadata):
        record = ucsb_urca_projects.normalize_project({
            "id": ident,
            "title": f"Project {ident}",
            "url": f"https://ucsb.example.edu/{ident}",
        })
        record["id"] = ident
        record["metadata"].update(metadata)
        return record

    legacy_crawl = row(
        "legacy-crawl",
        metadata={
            "collector_source": "ucb_ours_hub",
            "discovered": True,
            "discovered_page_verified": False,
            "urca_record_id": None,
        },
    )
    verified_crawl = row(
        "verified-crawl",
        metadata={
            "collector_source": "ucb_ours_hub",
            "discovered": True,
            "discovered_page_verified": True,
            "urca_record_id": None,
        },
    )
    curated_seed = row(
        "curated-seed",
        metadata={
            "collector_source": "ucb_summer_programs",
            "discovered": False,
            "discovered_page_verified": False,
            "urca_record_id": None,
        },
    )
    urca_sitemap = row(
        "urca-sitemap",
        metadata={
            "discovered": True,
            "discovered_page_verified": False,
            "collector_source": None,
            "urca_record_id": "urca-sitemap",
        },
    )
    static_discovery = row(
        "static-discovery",
        metadata={
            "collector_source": "ucb_summer_programs",
            "discovered": True,
            "discovered_page_verified": False,
            "urca_record_id": None,
        },
    )
    other_school_legacy = row(
        "uw-legacy-crawl",
        metadata={
            "collector_source": "uw_our_hub",
            "discovered": True,
            "discovered_page_verified": False,
            "urca_record_id": None,
        },
    )
    processed = _stub_with_processed_file(
        monkeypatch,
        tmp_path,
        [
            legacy_crawl,
            verified_crawl,
            curated_seed,
            urca_sitemap,
            static_discovery,
            other_school_legacy,
        ],
    )

    summary = refresh_all.refresh_all(deep=False, schools={"ucb"})

    saved = {
        record["id"]: record
        for record in json.loads(processed.read_text(encoding="utf-8"))
    }
    assert summary["sources"]["campus_discovery_quarantine"]["quarantined"] == 1
    assert saved["legacy-crawl"]["metadata"]["is_active"] is False
    assert saved["legacy-crawl"]["metadata"]["quarantined_unverified_discovery"] is True
    for ident in (
        "verified-crawl",
        "curated-seed",
        "urca-sitemap",
        "static-discovery",
        "uw-legacy-crawl",
    ):
        assert saved[ident]["metadata"]["is_active"] is True


def test_deep_run_deactivates_stale_faculty(monkeypatch, tmp_path):
    seeded = [
        _seed_faculty("umich_faculty", "fac-stale", days_ago=30),
        _seed_faculty("umich_faculty", "fac-fresh", days_ago=1),
    ]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    monkeypatch.setattr(
        refresh_all,
        "fetch_umich_faculty",
        lambda *a, **k: [{"id": f"f{i}"} for i in range(2)],
    )

    summary = refresh_all.refresh_all(deep=True, schools={"umich"})

    pass_info = summary["sources"]["deactivate_stale_faculty"]
    assert pass_info["status"] == "ok"
    assert pass_info["newly_deactivated"] == 1
    assert pass_info["skipped_partial_scrape"] == []
    saved = {o["id"]: o for o in json.loads(processed.read_text(encoding="utf-8"))}
    assert saved["fac-stale"]["metadata"]["is_active"] is False
    assert saved["fac-stale"]["metadata"]["deactivation_reason"] == \
        "absent_from_directory_rescrape"
    assert saved["fac-fresh"]["metadata"]["is_active"] is True


def test_quick_mode_leaves_non_run_faculty_sources_untouched(monkeypatch, tmp_path):
    # UCB faculty collectors don't run in quick mode, so their stale records
    # must survive even though they're past the grace window.
    seeded = [_seed_faculty("ucb_eecs_faculty", "ucb-stale", days_ago=60)]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)

    summary = refresh_all.refresh_all(deep=False)

    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
    saved = json.loads(processed.read_text(encoding="utf-8"))[0]
    assert saved["metadata"]["is_active"] is True


def test_js_faculty_runs_in_deep_and_folds_into_uiuc_faculty_count(monkeypatch, tmp_path):
    """uiuc_js_faculty (the ACES Drupal-AJAX directories) is browser-backed, so it
    runs only in deep mode; its records share source='uiuc_faculty', so its count
    must fold into the uiuc_faculty 'fetched' total that gates
    deactivate_stale_faculty — otherwise the ~160 ACES professors would be retired
    as absent from the re-scrape."""
    js_calls = {"n": 0}

    def fake_js(*a, **k):
        js_calls["n"] += 1
        return [{"id": f"j{i}"} for i in range(3)]

    _stub_all_collectors(monkeypatch, tmp_path)
    monkeypatch.setattr(refresh_all, "fetch_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(2)])
    monkeypatch.setattr(refresh_all, "fetch_js_faculty", fake_js)

    deep = refresh_all.refresh_all(deep=True)["sources"]["uiuc_faculty"]
    assert js_calls["n"] == 1
    assert deep["js_fetched"] == 3
    assert deep["fetched"] == 5  # 2 static + 3 JS folded into the one source count

    js_calls["n"] = 0
    quick = refresh_all.refresh_all(deep=False)["sources"]["uiuc_faculty"]
    assert js_calls["n"] == 0  # browser scrape skipped in quick mode
    assert quick["js_fetched"] == 0
    assert quick["fetched"] == 2


def test_uiuc_deep_component_failure_blocks_source_and_stale_deactivation(
    monkeypatch,
    tmp_path,
):
    processed = _stub_with_processed_file(
        monkeypatch,
        tmp_path,
        [_seed_faculty("uiuc_faculty", "uiuc-stale", days_ago=60)],
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_faculty",
        lambda *a, **k: [{"id": "static-one"}],
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_json_faculty",
        lambda: [{"id": "json-one"}],
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_html_faculty",
        lambda: [{"id": "html-one"}],
    )

    def js_failure():
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(refresh_all, "fetch_js_faculty", js_failure)

    summary = refresh_all.refresh_all(
        deep=True,
        schools={"uiuc"},
    )

    faculty = summary["sources"]["uiuc_faculty"]
    assert faculty["status"] == "error"
    assert faculty["components"]["js"] == {
        "status": "error",
        "fetched": 0,
        "error": "browser unavailable",
    }
    assert summary["release"]["ready"] is False
    assert summary["sources"]["deactivate_stale_faculty"][
        "newly_deactivated"
    ] == 0
    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert saved[0]["metadata"]["is_active"] is True


def test_errored_faculty_collector_never_deactivates(monkeypatch, tmp_path):
    seeded = [_seed_faculty("uiuc_faculty", "fac-stale", days_ago=60)]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)

    def boom(*a, **k):
        raise RuntimeError("directory down")

    monkeypatch.setattr(refresh_all, "fetch_faculty", boom)

    summary = refresh_all.refresh_all(deep=True)

    assert summary["sources"]["uiuc_faculty"]["status"] == "error"
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
    saved = json.loads(processed.read_text(encoding="utf-8"))[0]
    assert saved["metadata"]["is_active"] is True


def test_partial_scrape_gate_surfaces_in_summary(monkeypatch, tmp_path):
    seeded = [_seed_faculty("umich_faculty", f"fac-{i}", days_ago=60)
              for i in range(10)]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    # Collector "succeeds" but yields only 3 of 10 active records (< 95%).
    monkeypatch.setattr(
        refresh_all,
        "fetch_umich_faculty",
        lambda *a, **k: [{"id": f"f{i}"} for i in range(3)],
    )

    summary = refresh_all.refresh_all(deep=True, schools={"umich"})

    pass_info = summary["sources"]["deactivate_stale_faculty"]
    assert pass_info["newly_deactivated"] == 0
    assert pass_info["skipped_partial_scrape"] == ["umich_faculty"]


def test_missing_unit_ledger_surfaces_for_aggregate_faculty_source(
    monkeypatch,
    tmp_path,
):
    seeded = [
        _seed_faculty("umich_faculty", f"cs-{i}", days_ago=1)
        for i in range(95)
    ]
    seeded += [
        _seed_faculty("umich_faculty", f"stats-{i}", days_ago=60)
        for i in range(5)
    ]
    for record in seeded[:95]:
        record["department"] = "Computer Science"
    for record in seeded[95:]:
        record["department"] = "Statistics"
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    monkeypatch.setattr(
        refresh_all,
        "fetch_umich_faculty",
        lambda *a, **k: [{"id": f"f{i}"} for i in range(95)],
    )

    summary = refresh_all.refresh_all(deep=True, schools={"umich"})

    pass_info = summary["sources"]["deactivate_stale_faculty"]
    assert pass_info["newly_deactivated"] == 0
    assert pass_info["skipped_missing_unit_ledger"] == ["umich_faculty"]
    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert all(record["metadata"]["is_active"] is True for record in saved)


def test_nonzero_uiuc_component_collapse_cannot_retire_old_faculty(
    monkeypatch,
    tmp_path,
):
    seeded = [
        _seed_faculty("uiuc_faculty", f"fac-{index}", days_ago=60)
        for index in range(122)
    ]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    monkeypatch.setattr(
        refresh_all,
        "fetch_faculty",
        lambda enrich: seeded[:100],
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_js_faculty",
        lambda: seeded[100:101],
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_json_faculty",
        lambda: seeded[101:102],
    )
    monkeypatch.setattr(
        refresh_all,
        "fetch_html_faculty",
        lambda: seeded[102:103],
    )
    monkeypatch.setattr(
        refresh_all,
        "faculty_missing_departments",
        lambda _records: [],
    )

    summary = refresh_all.refresh_all(deep=True, schools={"uiuc"})

    faculty = summary["sources"]["uiuc_faculty"]
    stale = summary["sources"]["deactivate_stale_faculty"]
    assert faculty["status"] == "ok"
    assert faculty["components"]["js"]["fetched"] == 1
    assert faculty["stale_deactivation_authorized"] is False
    assert stale["newly_deactivated"] == 0
    assert stale["deactivation_not_authorized"] == ["uiuc_faculty"]
    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert all(row["metadata"]["is_active"] for row in saved)
    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert all(o["metadata"]["is_active"] is True for o in saved)


# --- Per-school shard scoping -------------------------------------------------
#
# The daily rotation runs refresh_all(schools={...}) / refresh_all(national=True).
# The single invariant that makes a partial run safe is: skipped collectors
# write NOTHING into summary["sources"] — deactivate_stale_faculty builds its
# fetched_counts only from sources reporting "ok" in this run's summary, so a
# source absent from the summary can never have its records deactivated.


def test_uw_shard_runs_only_uw_collectors(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True, schools={"uw"})
    assert set(summary["sources"]) == {"uw_faculty", "campus_graph:uw"}
    assert summary["shard"] == {"schools": ["uw"], "national": False}


def test_uiuc_shard_runs_exactly_uiuc_sources(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True, schools={"uiuc"})
    # uiuc_sro is NOT here: it catalogs external programs hosted elsewhere
    # (school=None in SOURCE_DEFAULTS), so it belongs to the national shard.
    assert set(summary["sources"]) == {
        "uiuc_our_rss", "uiuc_faculty", "uiuc_urap", "uiuc_ursa",
        "uiuc_drp", "uiuc_siebel", "uiuc_other",
    }


def test_ucb_shard_runs_exactly_ucb_sources(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True, schools={"ucb"})
    assert set(summary["sources"]) == {
        "ucb_urap", "ucb_campus", "ucb_urap_projects", *UCB_FACULTY_SOURCES,
    }


def test_national_shard_runs_exactly_national_sources(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True, national=True)
    assert set(summary["sources"]) == {"uiuc_sro", "nsf_reu", "simplify_internships"}
    assert summary["shard"] == {"schools": [], "national": True}


@pytest.mark.parametrize("structure_complete", [True, False])
def test_ucsb_empty_urca_is_never_a_publishable_single_snapshot(
    monkeypatch,
    tmp_path,
    structure_complete,
):
    _stub_all_collectors(monkeypatch, tmp_path)
    monkeypatch.setattr(
        refresh_all,
        "fetch_ucsb_urca_projects_with_evidence",
        lambda: (
            [],
            {
                "sitemap_complete": False,
                "sitemap_structure_complete": structure_complete,
                "sitemaps_expected": 1,
                "sitemaps_loaded": 1 if structure_complete else 0,
                "locations_seen": 0,
                "recognized_locations": 0,
                "unexpected_location_count": 0,
                "unexpected_location_samples": [],
                "empty_confirmed": False,
            },
        ),
    )

    summary = refresh_all.refresh_all(deep=True, schools={"ucsb"})
    info = summary["sources"]["ucsb_urca_projects"]
    assert info["status"] == "error"
    assert info["empty_confirmed"] is False


def test_unknown_or_empty_shard_raises(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="unknown school slug"):
        refresh_all.refresh_all(deep=True, schools={"uw", "notaschool"})
    with pytest.raises(ValueError, match="at least one school"):
        refresh_all.refresh_all(deep=True, schools=set())
    with pytest.raises(ValueError, match="isolated single-school"):
        refresh_all.refresh_all(deep=True, schools={"ucd", "uw"})
    with pytest.raises(ValueError, match="mutually exclusive"):
        refresh_all.refresh_all(
            deep=True,
            schools={"uw"},
            national=True,
        )


def test_release_contract_drives_tracking_refresh_ok(monkeypatch, tmp_path):
    """A process that finishes with empty mandatory sources is not a
    successful producing refresh for the tracking artifact."""

    _stub_with_processed_file(
        monkeypatch,
        tmp_path,
        [_seed_faculty("uw_faculty", "uw-existing", days_ago=1)],
    )
    captured: dict[str, bool] = {}

    def fake_tracking(_opps, summary, *, refresh_ok):
        captured["refresh_ok"] = refresh_ok
        summary["sources"]["professor_tracking"] = {
            "status": "ok",
            "release_ready": False,
        }

    monkeypatch.setattr(
        refresh_all,
        "_update_professor_tracking",
        fake_tracking,
    )
    summary = refresh_all.refresh_all(deep=True, schools={"uw"})

    assert captured["refresh_ok"] is False
    assert summary["release"]["ready"] is False
    assert any(
        "emitted zero records" in reason
        for reason in summary["release"]["reasons"]
    )


def test_cli_returns_two_after_writing_blocked_diagnostics(monkeypatch):
    summary = {
        "timestamp": "2026-07-31T00:00:00",
        "sources": {},
        "total_new": 0,
        "total_updated": 0,
        "total_in_file": 1,
        "release": {
            "ready": False,
            "reasons": ["required source missing: uw_faculty"],
        },
    }
    written: list[dict] = []
    monkeypatch.setattr(refresh_all, "refresh_all", lambda **_kwargs: summary)
    monkeypatch.setattr(refresh_all, "write_status", written.append)
    monkeypatch.setattr(refresh_all, "print_summary", lambda _summary: None)

    assert refresh_all.main(["--schools", "uw"]) == 2
    assert written == [summary]


def test_cli_reports_degraded_coverage_on_a_published_run(monkeypatch, caplog):
    """A tolerated gap that nobody prints is indistinguishable from none.

    Unreachable seed pages no longer veto the release, so the run log is
    where an operator learns a host went dark.
    """
    summary = {
        "timestamp": "2026-08-08T00:00:00",
        "sources": {},
        "total_new": 0,
        "total_updated": 0,
        "total_in_file": 1,
        "release": {
            "ready": True,
            "warnings": [
                "deep source campus_graph:umich loaded 3/12 configured "
                "seed pages (9 failed); those sources kept their previous "
                "records"
            ],
            "reasons": [],
        },
    }
    monkeypatch.setattr(refresh_all, "refresh_all", lambda **_kwargs: summary)
    monkeypatch.setattr(refresh_all, "write_status", lambda _summary: None)
    monkeypatch.setattr(refresh_all, "print_summary", lambda _summary: None)

    with caplog.at_level(logging.WARNING):
        assert refresh_all.main(["--schools", "umich"]) == 0

    assert any(
        "REFRESH RELEASE DEGRADED" in record.message
        and "campus_graph:umich" in record.message
        for record in caplog.records
    )


def test_refresh_summary_preserves_trusted_run_provenance(
    monkeypatch,
    tmp_path,
):
    _stub_all_collectors(monkeypatch, tmp_path)
    provenance = {
        "base_sha": "a" * 40,
        "run_id": "123",
        "run_attempt": "1",
    }

    summary = refresh_all.refresh_all(
        deep=True,
        schools={"uw"},
        provenance=provenance,
    )

    assert summary["provenance"] == provenance


def test_cli_cannot_reuse_old_green_status_when_snapshot_write_fails(
    monkeypatch,
    tmp_path,
):
    status_path = tmp_path / "collector_status.json"
    old_green = '{"release":{"ready":true},"run":"old"}'
    status_path.write_text(old_green, encoding="utf-8")
    monkeypatch.setattr(refresh_all, "STATUS_FILE", status_path)
    monkeypatch.setattr(
        refresh_all,
        "STATUS_HISTORY_FILE",
        tmp_path / "collector_status_history.jsonl",
    )
    monkeypatch.setattr(
        refresh_all,
        "refresh_all",
        lambda **_kwargs: {
            "timestamp": "2026-07-31T00:00:00",
            "request": {
                "schools": ["uw"],
                "national": False,
                "deep": True,
            },
            "sources": {},
            "total_new": 0,
            "total_updated": 0,
            "total_in_file": 1,
            "release": {
                "ready": True,
                "reasons": [],
            },
        },
    )
    monkeypatch.setattr(refresh_all, "print_summary", lambda _summary: None)

    def fail_snapshot(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(refresh_all, "atomic_write_json", fail_snapshot)

    with pytest.raises(OSError, match="disk full"):
        refresh_all.main(["--schools", "uw"])
    assert status_path.read_text(encoding="utf-8") == old_green


# --- Shard deactivation scoping ------------------------------------------------
#
# THE guarantee of the rotation: a shard run for school X must be provably
# unable to deactivate or degrade school Y's records — byte-identical, not
# just "still active".


def _shard_seeds():
    return [
        _seed_faculty("uiuc_faculty", "uiuc-stale", days_ago=30),
        _seed_faculty("uiuc_faculty", "uiuc-fresh", days_ago=1),
        _seed_faculty("ucb_eecs_faculty", "ucb-stale", days_ago=60),
        _seed_faculty("uw_faculty", "uw-stale", days_ago=60),
    ]


def test_uiuc_shard_leaves_other_schools_byte_identical(monkeypatch, tmp_path):
    processed = _stub_with_processed_file(monkeypatch, tmp_path, _shard_seeds())
    # First shard run brings the seeds to the global-pass fixed point (school/
    # audience stamps, rule tags, keyword hygiene) so the second run's diff is
    # attributable to the uiuc shard alone.
    refresh_all.refresh_all(deep=True, schools={"umich"})
    baseline = {o["id"]: json.dumps(o, sort_keys=True)
                for o in json.loads(processed.read_text(encoding="utf-8"))}
    assert json.loads(baseline["uiuc-stale"])["metadata"]["is_active"] is True

    # UIUC currently has no component-level lineage, so even a full-size
    # aggregate scrape is deliberately not authorized to retire old rows.
    monkeypatch.setattr(refresh_all, "fetch_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(2)])
    _stub_successful_uiuc_deep_components(monkeypatch)
    summary = refresh_all.refresh_all(deep=True, schools={"uiuc"})

    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
    saved = {o["id"]: o for o in json.loads(processed.read_text(encoding="utf-8"))}
    assert saved["uiuc-stale"]["metadata"]["is_active"] is True
    assert saved["uiuc-fresh"]["metadata"]["is_active"] is True
    # ucb/uw are both past GRACE_DAYS, yet must come out byte-identical —
    # active flags, keywords, emails, everything.
    for ident in ("ucb-stale", "uw-stale"):
        assert saved[ident]["metadata"]["is_active"] is True
        assert json.dumps(saved[ident], sort_keys=True) == baseline[ident]


def test_uiuc_shard_summary_has_no_other_school_sources(monkeypatch, tmp_path):
    """The invariant §safety rests on: sources that did not run this shard are
    entirely ABSENT from summary["sources"] — not present as "ok, fetched: 0"."""
    _stub_with_processed_file(monkeypatch, tmp_path, _shard_seeds())
    monkeypatch.setattr(refresh_all, "fetch_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(2)])
    summary = refresh_all.refresh_all(deep=True, schools={"uiuc"})
    sources = set(summary["sources"])
    assert not {s for s in sources if s.startswith(("ucb_", "uw_", "campus_graph:"))}
    assert sources & FACULTY_SOURCES == {"uiuc_faculty"}


def test_national_run_touches_no_faculty(monkeypatch, tmp_path):
    seeded = [_seed_faculty("uiuc_faculty", "uiuc-stale", days_ago=60)]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    summary = refresh_all.refresh_all(deep=True, national=True)
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
    saved = json.loads(processed.read_text(encoding="utf-8"))[0]
    assert saved["metadata"]["is_active"] is True


def test_pi_enrichment_pool_scoped_to_shard_and_never_truncates(monkeypatch, tmp_path):
    """Sharded runs must call enrich_pi with save=False: enrich_pi(save=True)
    writes its INPUT list to PROCESSED_FILE, so a shard-scoped subset would
    truncate the corpus to that subset."""
    seeds = _shard_seeds()
    _stub_with_processed_file(monkeypatch, tmp_path, seeds)
    captured = {}

    def fake_enrich(opps, save=True, max_scrapes=None):
        captured["sources"] = {o["source"] for o in opps}
        captured["size"] = len(opps)
        captured["save"] = save
        return {"scraped": 0, "enriched": 0, "already_has_email": 0, "skipped_budget": 0}

    monkeypatch.setattr(refresh_all, "enrich_pi", fake_enrich)
    monkeypatch.setattr(refresh_all, "fetch_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(2)])

    refresh_all.refresh_all(deep=True, schools={"uiuc"})
    assert captured["sources"] == {"uiuc_faculty"}
    assert captured["save"] is False

    refresh_all.refresh_all(deep=True)
    assert captured["size"] == len(seeds)
    assert captured["save"] is True


def test_post_merge_pass_stamps_school_audience(monkeypatch, tmp_path):
    """The school/audience stamp runs in the post-merge block, persists to the
    processed file, and surfaces its per-source counts in the run summary —
    same wiring contract as deactivate_stale_faculty."""
    seeded = [
        _seed_faculty("uiuc_faculty", "fac-1", days_ago=1),
        {"id": "man-1", "source": "manual", "title": "Hand import",
         "school": "MIT", "audience": "open", "metadata": {"is_active": True}},
        {"id": "man-2", "source": "manual", "title": "Untagged hand import",
         "metadata": {"is_active": True}},
    ]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)

    summary = refresh_all.refresh_all(deep=False)

    pass_info = summary["sources"]["school_audience"]
    assert pass_info["status"] == "ok"
    assert pass_info["tagged"] == 3
    assert pass_info["by_source"] == {"uiuc_faculty": 1, "manual": 2}

    saved = {o["id"]: o for o in json.loads(processed.read_text(encoding="utf-8"))}
    # uiuc_faculty is (uiuc, unknown) like every other school's directory —
    # cross-school visibility is the matcher toggle's job, not the audience tag.
    assert (saved["fac-1"]["school"], saved["fac-1"]["audience"]) == ("uiuc", "unknown")
    # Manual explicit values win (school normalized to a lowercase slug)...
    assert (saved["man-1"]["school"], saved["man-1"]["audience"]) == ("mit", "open")
    # ...and untagged manual records fall back to the conservative default.
    assert (saved["man-2"]["school"], saved["man-2"]["audience"]) == (None, "unknown")


def test_time_budget_defers_unstarted_sources(monkeypatch, tmp_path):
    """A run whose wall-clock budget is exhausted must stop STARTING sources
    (status ``deferred_deadline``, fetch never called) instead of letting the
    CI job timeout kill the whole run mid-write — 2026-08-07's scheduled
    refresh hit the 300-minute cap inside jhu_faculty and published nothing,
    losing even the schools that had already completed."""
    _stub_all_collectors(monkeypatch, tmp_path)
    called: list[str] = []
    monkeypatch.setattr(
        refresh_all, "fetch_jhu_faculty", lambda *a, **k: called.append("jhu") or [],
    )

    summary = refresh_all.refresh_all(deep=True, time_budget_minutes=0)

    info = summary["sources"].get("jhu_faculty")
    assert info is not None, "budget-deferred source must still appear in the ledger"
    assert info["status"] == "deferred_deadline"
    assert called == [], "an expired budget must not start the fetch at all"
    # A deferral is not a failure: nothing may look 'ok' for the deferred
    # source, and the summary must surface that the run was budget-cut.
    assert summary["time_budget"]["deferred"] >= 1


def test_no_time_budget_means_no_deferrals(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True)
    deferred = {
        n for n, i in summary["sources"].items()
        if i.get("status") == "deferred_deadline"
    }
    assert deferred == set()


def test_budget_cut_mid_source_merges_partial_and_reports_partial_deadline(
    monkeypatch, tmp_path,
):
    """A source mid-flight when the run deadline passes must return its partial
    harvest, merge it, and report ``partial_deadline`` — never "ok" (so
    deactivate_stale_faculty cannot retire the unvisited departments' records)
    and never unbounded (the started-just-under-the-wire hole in the #712
    budget: the job's 300-minute hard kill would publish nothing)."""
    from src.collectors import faculty_graph

    _stub_all_collectors(monkeypatch, tmp_path)

    def fake_jhu(*a, **k):
        budget = faculty_graph._ACTIVE_BUDGET
        assert budget.deadline is not None, (
            "refresh_all must arm the engine's source budget around the fetch"
        )
        budget.deadline = 0.0  # the clock runs out inside this source...
        assert faculty_graph._source_budget_spent()  # ...and a check fires
        return [{"id": "jhu-1"}]

    monkeypatch.setattr(refresh_all, "fetch_jhu_faculty", fake_jhu)

    summary = refresh_all.refresh_all(
        deep=True, schools={"jhu"}, time_budget_minutes=60,
    )

    info = summary["sources"]["jhu_faculty"]
    assert info["status"] == "partial_deadline"
    assert info["fetched"] == 1, "the partial harvest must still merge"
    assert summary["time_budget"]["partial"] >= 1
    # A truncated source is not a pipeline failure — the shard still publishes.
    assert refresh_all.refresh_run_ok(summary) is True


def test_complete_fetch_under_expired_clock_stays_ok(monkeypatch, tmp_path):
    """``partial_deadline`` means data was truncated, not that time ran out:
    a fetch that completed fully (no engine check fired) reports "ok" even if
    the deadline passed while it ran — its data is complete and stale
    retirement for it remains sound."""
    from src.collectors import faculty_graph

    _stub_all_collectors(monkeypatch, tmp_path)

    def fake_jhu(*a, **k):
        faculty_graph._ACTIVE_BUDGET.deadline = 0.0  # expires, no check fires
        return [{"id": "jhu-1"}]

    monkeypatch.setattr(refresh_all, "fetch_jhu_faculty", fake_jhu)

    summary = refresh_all.refresh_all(
        deep=True, schools={"jhu"}, time_budget_minutes=60,
    )
    assert summary["sources"]["jhu_faculty"]["status"] == "ok"
    assert summary["time_budget"].get("partial", 0) == 0
