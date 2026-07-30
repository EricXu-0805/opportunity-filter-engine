"""Fail-closed publication contracts for one isolated refresh summary."""

from __future__ import annotations

from src.collectors.refresh_contract import (
    NATIONAL_SOURCES,
    evaluate_refresh_summary,
    expected_sources,
)


def _ok(fetched: int = 1, **extra) -> dict:
    return {"status": "ok", "fetched": fetched, **extra}


def _graph_ok(fetched: int = 4, **extra) -> dict:
    evidence = {
        "deep": True,
        "crawl_sources_expected": 1,
        "crawl_sources_loaded": 1,
        "live_pages_attempted": 1,
        "live_pages_loaded": 1,
        "seed_pages_expected": 1,
        "seed_pages_loaded": 1,
        "seed_pages_failed": 0,
        "seed_records": fetched,
        "discovered_records": 0,
        "crawl_errors": [],
        "degraded_page_errors": [],
    }
    evidence.update(extra)
    return _ok(fetched, **evidence)


def _summary(
    schools: set[str] | None,
    sources: dict,
    *,
    national: bool = False,
    deep: bool = True,
) -> dict:
    payload = {
        "request": {
            "schools": sorted(schools) if schools is not None else None,
            "national": national,
            "deep": deep,
        },
        "sources": {
            **sources,
            "professor_tracking": {
                "status": "ok",
                "release_ready": True,
            },
        }
    }
    if schools is not None or national:
        payload["shard"] = {
            "schools": sorted(schools or ()),
            "national": national,
        }
    return payload


def test_generic_deep_school_requires_graph_and_faculty():
    assert set(expected_sources({"uw"}, national=False, deep=True)) == {
        "campus_graph:uw",
        "uw_faculty",
    }
    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": _graph_ok(),
                "uw_faculty": _ok(100),
                "deactivate_stale_faculty": {
                    "status": "ok",
                    "skipped_partial_scrape": [],
                },
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )
    assert verdict["ready"] is True


def test_aggregate_faculty_retirement_hold_is_explicitly_degraded():
    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": _graph_ok(),
                "uw_faculty": _ok(100),
                "deactivate_stale_faculty": {
                    "status": "ok",
                    "skipped_partial_scrape": [],
                    "skipped_missing_unit_ledger": ["uw_faculty"],
                },
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is True
    assert verdict["status"] == "degraded"
    assert any("per-unit lineage" in warning for warning in verdict["warnings"])


def test_quick_school_excludes_deep_faculty_but_keeps_seed_graph():
    assert set(expected_sources({"uw"}, national=False, deep=False)) == {
        "campus_graph:uw",
    }


def test_quick_faculty_only_school_cannot_report_vacuous_success():
    verdict = evaluate_refresh_summary(
        _summary({"unc"}, {}, deep=False),
        schools={"unc"},
        national=False,
        deep=False,
    )

    assert verdict["ready"] is False
    assert any("no mandatory producer" in reason for reason in verdict["reasons"])


def test_deep_campus_graph_total_live_outage_blocks_seed_only_success():
    graph = _graph_ok()
    graph["crawl_sources_loaded"] = 0
    graph["live_pages_loaded"] = 0

    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": graph,
                "uw_faculty": _ok(100),
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is False
    assert any("live-crawl" in reason for reason in verdict["reasons"])


def test_deep_campus_graph_partial_configured_seed_fetch_fails_closed():
    graph = _graph_ok(
        live_pages_attempted=3,
        live_pages_loaded=2,
        seed_pages_expected=3,
        seed_pages_loaded=2,
        seed_pages_failed=1,
        crawl_errors=["uw_hub: seed fetch failed: https://example.edu/missing"],
    )

    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": graph,
                "uw_faculty": _ok(100),
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is False
    assert any("2/3 configured seed pages" in reason for reason in verdict["reasons"])


def test_deep_campus_graph_recursive_page_failure_is_degraded_only():
    graph = _graph_ok(
        live_pages_attempted=2,
        live_pages_loaded=1,
        degraded_page_errors=[
            "uw_hub: discovered-page fetch failed: https://example.edu/detail"
        ],
    )

    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": graph,
                "uw_faculty": _ok(100),
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is True
    assert any("degraded on recursive" in warning for warning in verdict["warnings"])


def test_national_requires_exact_three_external_sources():
    assert set(expected_sources(None, national=True, deep=True)) == set(
        NATIONAL_SOURCES
    )
    verdict = evaluate_refresh_summary(
        _summary(
            None,
            {key: _ok(3) for key in NATIONAL_SOURCES},
            national=True,
        ),
        schools=None,
        national=True,
        deep=True,
    )
    assert verdict["ready"] is True


def test_uiuc_and_ucb_special_source_sets_are_explicit():
    uiuc = set(expected_sources({"uiuc"}, national=False, deep=True))
    assert {
        "uiuc_our_rss",
        "uiuc_urap",
        "uiuc_ursa",
        "uiuc_drp",
        "uiuc_siebel",
        "uiuc_other",
        "uiuc_faculty",
    } <= uiuc

    ucb = set(expected_sources({"ucb"}, national=False, deep=True))
    assert {"ucb_urap", "ucb_campus", "ucb_urap_projects"} <= ucb
    assert "ucb_pmb_faculty" in ucb


def test_missing_error_and_zero_required_sources_block_release():
    cases = [
        {},
        {"campus_graph:uw": _graph_ok(), "uw_faculty": {"status": "error", "error": "down"}},
        {"campus_graph:uw": _graph_ok(), "uw_faculty": _ok(0)},
    ]
    for sources in cases:
        verdict = evaluate_refresh_summary(
            _summary({"uw"}, sources),
            schools={"uw"},
            national=False,
            deep=True,
        )
        assert verdict["ready"] is False
        assert verdict["reasons"]


def test_reconciled_raw_fetch_with_zero_emitted_blocks_publication():
    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": _graph_ok(),
                "uw_faculty": {
                    "status": "ok",
                    "raw_fetched": 20,
                    "fetched": 0,
                    "emitted": 0,
                    "rejected": 20,
                },
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )
    assert verdict["ready"] is False
    assert any("emitted zero records" in reason for reason in verdict["reasons"])


def test_incomplete_or_inconsistent_source_count_accounting_blocks_release():
    for faculty in (
        {
            "status": "ok",
            "raw_fetched": 20,
            "emitted": 0,
        },
        {
            "status": "ok",
            "raw_fetched": 20,
            "emitted": 10,
            "rejected": 5,
        },
    ):
        verdict = evaluate_refresh_summary(
            _summary(
                {"uw"},
                {
                    "campus_graph:uw": _graph_ok(),
                    "uw_faculty": faculty,
                },
            ),
            schools={"uw"},
            national=False,
            deep=True,
        )
        assert verdict["ready"] is False
        assert any("count" in reason for reason in verdict["reasons"])


def test_quick_uiuc_still_requires_nonempty_static_faculty():
    expected = expected_sources({"uiuc"}, national=False, deep=False)
    assert "uiuc_faculty" in expected
    sources = {key: _ok(1) for key in expected}
    sources["uiuc_faculty"] = _ok(
        0,
        stale_deactivation_authorized=False,
    )

    verdict = evaluate_refresh_summary(
        _summary({"uiuc"}, sources, deep=False),
        schools={"uiuc"},
        national=False,
        deep=False,
    )

    assert verdict["ready"] is False
    assert any("uiuc_faculty" in reason for reason in verdict["reasons"])


def test_uiuc_release_requires_explicit_stale_deactivation_hold():
    expected = expected_sources({"uiuc"}, national=False, deep=True)
    sources = {key: _ok(1) for key in expected}
    sources["uiuc_faculty"]["stale_deactivation_authorized"] = False
    sources["deactivate_stale_faculty"] = {
        "status": "ok",
        "skipped_partial_scrape": [],
        "deactivation_not_authorized": ["uiuc_faculty"],
    }

    held = evaluate_refresh_summary(
        _summary({"uiuc"}, sources),
        schools={"uiuc"},
        national=False,
        deep=True,
    )

    assert held["ready"] is True
    assert held["status"] == "degraded"

    sources["uiuc_faculty"].pop("stale_deactivation_authorized")
    unsafe = evaluate_refresh_summary(
        _summary({"uiuc"}, sources),
        schools={"uiuc"},
        national=False,
        deep=True,
    )
    assert unsafe["ready"] is False


def test_national_and_school_selector_cannot_be_combined():
    verdict = evaluate_refresh_summary(
        _summary({"uw"}, {}, national=True),
        schools={"uw"},
        national=True,
        deep=True,
    )
    assert verdict["ready"] is False
    assert any("mutually exclusive" in reason for reason in verdict["reasons"])


def test_urca_single_empty_snapshot_cannot_authorize_publication():
    base = {
        "campus_graph:ucsb": _graph_ok(),
        "ucsb_faculty": _ok(100),
    }
    blocked = evaluate_refresh_summary(
        _summary({"ucsb"}, {**base, "ucsb_urca_projects": _ok(0)}),
        schools={"ucsb"},
        national=False,
        deep=True,
    )
    assert blocked["ready"] is False

    structurally_complete_but_empty = evaluate_refresh_summary(
        _summary(
            {"ucsb"},
            {
                **base,
                "ucsb_urca_projects": _ok(
                    0,
                    empty_confirmed=False,
                    sitemap_complete=False,
                    sitemap_structure_complete=True,
                    sitemaps_expected=1,
                    sitemaps_loaded=1,
                    unexpected_location_count=0,
                ),
            },
        ),
        schools={"ucsb"},
        national=False,
        deep=True,
    )
    assert structurally_complete_but_empty["ready"] is False
    assert any(
        "emitted zero records" in reason
        for reason in structurally_complete_but_empty["reasons"]
    )


def test_urca_positive_rows_still_require_complete_sitemap_evidence():
    verdict = evaluate_refresh_summary(
        _summary(
            {"ucsb"},
            {
                "campus_graph:ucsb": _graph_ok(),
                "ucsb_faculty": _ok(100),
                "ucsb_urca_projects": _ok(
                    1,
                    empty_confirmed=False,
                    sitemap_complete=False,
                    sitemaps_expected=2,
                    sitemaps_loaded=1,
                    unexpected_location_count=0,
                ),
            },
        ),
        schools={"ucsb"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is False
    assert any("complete sitemap evidence" in reason for reason in verdict["reasons"])


def test_partial_faculty_and_uiuc_empty_departments_block_release():
    uw = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": _graph_ok(),
                "uw_faculty": _ok(100),
                "deactivate_stale_faculty": {
                    "status": "ok",
                    "skipped_partial_scrape": ["uw_faculty"],
                },
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )
    assert uw["ready"] is False
    assert any("partial" in reason for reason in uw["reasons"])

    uiuc_sources = {
        key: _ok(1)
        for key in expected_sources({"uiuc"}, national=False, deep=True)
    }
    uiuc_sources["uiuc_faculty"]["empty_departments"] = ["matse"]
    uiuc = evaluate_refresh_summary(
        _summary({"uiuc"}, uiuc_sources),
        schools={"uiuc"},
        national=False,
        deep=True,
    )
    assert uiuc["ready"] is False
    assert any("empty departments" in reason for reason in uiuc["reasons"])


def test_ucd_zero_is_explicitly_degraded_and_blocked():
    verdict = evaluate_refresh_summary(
        _summary(
            {"ucd"},
            {
                "campus_graph:ucd": _graph_ok(),
                "ucd_faculty": _ok(0),
            },
        ),
        schools={"ucd"},
        national=False,
        deep=True,
    )
    assert verdict["ready"] is False
    assert verdict["status"] == "blocked"
    assert any("UC Davis" in warning for warning in verdict["warnings"])


def test_tracking_not_ready_warns_but_does_not_block_corpus_release():
    summary = _summary(
        {"uw"},
        {
            "campus_graph:uw": _graph_ok(),
            "uw_faculty": _ok(100),
        },
    )
    summary["sources"]["professor_tracking"]["release_ready"] = False
    verdict = evaluate_refresh_summary(
        summary,
        schools={"uw"},
        national=False,
        deep=True,
    )
    assert verdict["ready"] is True
    assert verdict["status"] == "degraded"
    assert any("remain hidden" in warning for warning in verdict["warnings"])


def test_local_only_tracking_failure_cannot_block_opportunity_artifact():
    summary = _summary(
        {"uw"},
        {
            "campus_graph:uw": _graph_ok(),
            "uw_faculty": _ok(100),
        },
    )
    summary["sources"]["professor_tracking"] = {
        "status": "error",
        "error": "ledger write failed",
        "publication_status": "local_only_not_in_refresh_artifact",
    }

    verdict = evaluate_refresh_summary(
        summary,
        schools={"uw"},
        national=False,
        deep=True,
        require_tracking=False,
    )

    assert verdict["ready"] is True
    assert verdict["status"] == "degraded"
    assert any("local-only" in warning for warning in verdict["warnings"])
