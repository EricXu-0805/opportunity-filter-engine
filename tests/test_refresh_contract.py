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


def test_deep_campus_graph_total_live_outage_is_degraded_not_blocked():
    """Measured umich, 2026-08-08: 0/9 seeds, 0 live pages, 6/6 sources dark.

    Every Michigan campus_graph seed host answers the Cloudflare managed
    challenge, so this school's crawl cannot come back non-empty again. Its
    12 seed records still emit from config with seed_page_verified=False,
    and merge_into_processed hands them back their previous status,
    is_active and last_verified — the corpus keeps saying exactly what it
    said before. Blocking here withheld fifteen other schools' fresh data
    for three weeks and changed nothing about Michigan's.
    """
    graph = _graph_ok(fetched=12)
    graph["crawl_sources_expected"] = 6
    graph["crawl_sources_loaded"] = 0
    graph["live_pages_attempted"] = 9
    graph["live_pages_loaded"] = 0
    graph["seed_pages_expected"] = 9
    graph["seed_pages_loaded"] = 0
    graph["seed_pages_failed"] = 9

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
    assert verdict["status"] == "degraded"
    assert any("loaded no live page at all" in w for w in verdict["warnings"])


def test_deep_campus_graph_partial_configured_seed_fetch_is_degraded_only():
    """An unreachable seed costs coverage; it cannot corrupt what we keep.

    campus_graph only lets ``merge_into_processed`` retire discoveries for
    sources whose crawl came back ``crawl_complete``, so a failed seed
    already preserves every prior record. Vetoing the release on top of
    that bought no safety and cost the Saturday shard three weeks of
    publication when Michigan put its UROP pages behind a Cloudflare
    challenge (observed 2026-08-08, run 31243355936).
    """
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

    assert verdict["ready"] is True
    assert verdict["status"] == "degraded"
    assert any("2/3 configured seed pages" in w for w in verdict["warnings"])
    assert any("seed fetch failed" in w for w in verdict["warnings"])


def test_deep_campus_graph_wholly_unreachable_source_is_degraded_only():
    """The exact Saturday shape: one source blocked, the rest crawled.

    Georgia Tech's bioresearch source timed out while its siblings loaded,
    so ``crawl_sources_loaded`` fell short of expected. That mismatch was
    filed under "inconsistent evidence" — an arithmetic contradiction —
    when it is just an unreached host.
    """
    graph = _graph_ok(
        crawl_sources_expected=3,
        crawl_sources_loaded=2,
        live_pages_attempted=4,
        live_pages_loaded=3,
        seed_pages_expected=3,
        seed_pages_loaded=2,
        seed_pages_failed=1,
        crawl_errors=["gt_lab: crawl failed: read timeout"],
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
    assert any("2/3 configured crawl sources" in w for w in verdict["warnings"])


def test_deep_campus_graph_seed_arithmetic_contradiction_still_blocks():
    """Unreachable is tolerated; evidence that cannot be true is not."""
    graph = _graph_ok(
        seed_pages_expected=3,
        seed_pages_loaded=1,
        seed_pages_failed=1,
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
    assert any(
        "inconsistent live-crawl" in reason for reason in verdict["reasons"]
    )


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


def test_missing_and_errored_required_sources_block_release():
    """Accuracy failures still fail closed.

    A source absent from the summary, or one that reported an error, means
    what we would publish may be WRONG - the run cannot vouch for it. That
    still blocks. Only the EMPTY case is reclassified (next test): a zero
    costs coverage, never accuracy, and blocking on it withheld every sibling
    department in the school.
    """
    cases = [
        {},
        {"campus_graph:uw": _graph_ok(), "uw_faculty": {"status": "error", "error": "down"}},
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
        assert verdict["publishable"] == []


def test_zero_emitting_required_source_degrades_instead_of_blocking():
    """The department-vetoes-school fix, at the contract's own level."""
    verdict = evaluate_refresh_summary(
        _summary({"uw"}, {"campus_graph:uw": _graph_ok(), "uw_faculty": _ok(0)}),
        schools={"uw"},
        national=False,
        deep=True,
    )
    assert verdict["ready"] is True
    assert verdict["status"] == "degraded"
    assert verdict["publishable"] == ["uw"]
    assert verdict["reasons"] == []
    assert any(
        item["kind"] == "suspicious_zero" and item["source"] == "uw_faculty"
        for item in verdict["degradations"]
    )


def test_reconciled_raw_fetch_with_zero_emitted_degrades_publication():
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
    # Fetched 20 and kept none. Still a zero - it publishes nothing - so it
    # degrades its own source rather than withholding its school, and the
    # emptiness is reported rather than swallowed.
    assert verdict["ready"] is True
    assert verdict["publishable"] == ["uw"]
    assert any("emitted zero records" in warning for warning in verdict["warnings"])
    assert any(
        item["kind"] == "suspicious_zero" and item["source"] == "uw_faculty"
        for item in verdict["degradations"]
    )


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


def test_quick_uiuc_empty_static_faculty_is_reported_every_run():
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

    # Reported, every run, until it emits records again - but the other UIUC
    # producers are not withheld along with it.
    assert verdict["status"] == "degraded"
    assert verdict["publishable"] == ["uiuc"]
    assert any("uiuc_faculty" in warning for warning in verdict["warnings"])
    assert any(
        item["kind"] == "suspicious_zero" and item["source"] == "uiuc_faculty"
        for item in verdict["degradations"]
    )


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


def test_urca_empty_snapshot_blocks_on_evidence_not_on_emptiness():
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
    # Still blocked - but now on the reason that was always the real one.
    # ``sitemap_complete`` is false, so the snapshot cannot be trusted for
    # what it DID emit; that is an accuracy failure and stays fail-closed.
    # It no longer ALSO blocks for being empty, which is what used to take
    # the rest of UC Santa Barbara down with it.
    assert structurally_complete_but_empty["ready"] is False
    assert structurally_complete_but_empty["publishable"] == []
    assert any(
        "lacks complete sitemap evidence" in reason
        for reason in structurally_complete_but_empty["reasons"]
    )
    assert not any(
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


def test_a_partial_faculty_scrape_degrades_without_withholding_its_school():
    """It used to block, and blocking cost the school its other departments.

    ``skipped_partial_scrape`` IS deactivate_stale_faculty's own record that it
    declined to retire from that source, and merges are upsert-only, so the
    records are already preserved twice over. Vetoing publication on top of
    that re-spends a safety budget already spent and charges every sibling
    department for it.
    """
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
    assert uw["ready"] is True
    assert uw["status"] == "degraded"
    assert uw["publishable"] == ["uw"]
    # Degraded, not waived: keyed so ops opens one incident for the source.
    assert any(
        item["kind"] == "partial_scrape" and item["source"] == "uw_faculty"
        for item in uw["degradations"]
    )
    assert any("cannot claim the source is complete" in w for w in uw["warnings"])


def test_uiuc_empty_departments_still_block_release():
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


def test_ucd_zero_is_explicitly_degraded_without_withholding_ucd():
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
    # UC Davis faculty is walled off by Cloudflare and has never emitted a
    # record. It is degraded, and reported so on every run - but it no longer
    # withholds the seven UC Davis programs that DO collect.
    assert verdict["ready"] is True
    assert verdict["status"] == "degraded"
    assert verdict["publishable"] == ["ucd"]
    assert any("UC Davis" in warning for warning in verdict["warnings"])
    assert any(
        item["kind"] == "suspicious_zero" and item["source"] == "ucd_faculty"
        for item in verdict["degradations"]
    )


def test_ucd_quick_mode_cannot_skip_faculty_and_report_ready():
    verdict = evaluate_refresh_summary(
        _summary(
            {"ucd"},
            {"campus_graph:ucd": _ok(4)},
            deep=False,
        ),
        schools={"ucd"},
        national=False,
        deep=False,
    )

    assert verdict["ready"] is False
    assert verdict["status"] == "blocked"
    assert any(
        "UC Davis publication requires deep mode" in reason
        for reason in verdict["reasons"]
    )


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


def test_budget_deferred_source_is_degraded_not_blocked():
    """A source the run's wall-clock budget never started must not block the
    schools that DID finish from publishing — that is the entire point of the
    budget (#712). The contract predates those statuses and rejected anything
    that was not exactly "ok", so refresh_all exited 2 and the workflow threw
    away the whole run: the precise loss the budget was added to prevent.

    Safe to publish: a deferred source wrote nothing, so its school keeps the
    records from its previous refresh, and deactivate_stale_faculty only
    considers sources reporting "ok" — it provably cannot retire them.
    """
    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": _graph_ok(),
                "uw_faculty": {"status": "deferred_deadline"},
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is True
    assert verdict["status"] == "degraded"
    assert any("time budget" in warning for warning in verdict["warnings"])


def test_budget_truncated_source_is_degraded_not_blocked():
    """Same for a source cut mid-flight (#714): its partial harvest merged
    (upsert-only, richer-guard), and stale retirement skips it, so the shard
    publishes what it has rather than losing every school in the run."""
    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": _graph_ok(),
                "uw_faculty": {
                    "status": "partial_deadline",
                    "fetched": 40,
                    "skipped_departments": 12,
                },
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is True
    assert verdict["status"] == "degraded"
    assert any("time budget" in warning for warning in verdict["warnings"])


def test_budget_status_does_not_excuse_an_empty_completed_source():
    """The budget exemption must not launder an empty completed source.

    A source that finished and found nothing is NOT "stopped at the run time
    budget", and must not be reported as though it were - the two have
    different causes and different fixes. It gets its own degradation kind.
    """
    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": _graph_ok(),
                "uw_faculty": _ok(0),
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is True
    kinds = {
        item["kind"] for item in verdict["degradations"]
        if item["source"] == "uw_faculty"
    }
    assert kinds == {"suspicious_zero"}
    assert "time_budget" not in kinds
    assert any("emitted zero records" in warning for warning in verdict["warnings"])


def test_every_budget_status_the_engine_emits_is_known_to_the_contract():
    """Pin the producer's status vocabulary to the contract's. refresh_all
    grew two statuses (#712, #714) that the contract had never heard of, and
    nothing failed until a real run hit the budget. A new status added to
    refresh_all without a decision here must fail this test instead.
    """
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "collectors" / "refresh_all.py"
    ).read_text(encoding="utf-8")
    emitted = set(re.findall(r'"status": "([a-z_]+)"', source))
    emitted |= set(re.findall(r'\["status"\] = "([a-z_]+)"', source))

    from src.collectors.refresh_contract import RELEASABLE_INCOMPLETE_STATUSES

    known = {"ok", "error"} | RELEASABLE_INCOMPLETE_STATUSES
    assert emitted <= known, (
        f"refresh_all emits status(es) the release contract has never been "
        f"told how to judge: {sorted(emitted - known)}. Decide explicitly: "
        f"blocking, or releasable-with-warning."
    )


def test_degradations_are_keyed_for_the_operator_queue():
    """A warning nobody can dedupe is a warning nobody tracks.

    #725 stopped an unreachable seed from vetoing publication, which is
    right — but it left the gap visible only as prose in a run log. These
    keys are what let ops-scan open one incident per gap and close it when
    a later run stops reporting it.
    """
    graph = _graph_ok(fetched=12)
    graph["crawl_sources_expected"] = 6
    graph["crawl_sources_loaded"] = 0
    graph["live_pages_attempted"] = 9
    graph["live_pages_loaded"] = 0
    graph["seed_pages_expected"] = 9
    graph["seed_pages_loaded"] = 0
    graph["seed_pages_failed"] = 9
    graph["crawl_errors"] = ["umich_urop_hub: seed fetch failed: https://x"]

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
    keys = {(d["kind"], d["source"]) for d in verdict["degradations"]}
    assert ("dark_crawl", "campus_graph:uw") in keys
    assert ("crawl_errors", "campus_graph:uw") in keys
    # Every degradation must also read as prose, and vice versa: one list
    # cannot quietly grow past the other.
    assert len(verdict["degradations"]) <= len(verdict["warnings"])
    assert all(
        isinstance(d.get("detail"), str) and d["detail"]
        for d in verdict["degradations"]
    )


def test_a_clean_run_reports_no_degradations():
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
    assert verdict["degradations"] == []


def test_a_budget_stop_is_a_keyed_degradation():
    verdict = evaluate_refresh_summary(
        _summary(
            {"uw"},
            {
                "campus_graph:uw": _graph_ok(),
                "uw_faculty": {"status": "partial_deadline", "fetched": 0},
            },
        ),
        schools={"uw"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is True
    assert {
        (d["kind"], d["source"], d["detail"]) for d in verdict["degradations"]
    } == {("time_budget", "uw_faculty", "partial_deadline")}


def test_one_broken_school_no_longer_withholds_the_others():
    """2026-08-08: UCSB's sitemap errored and fifteen schools lost their run.

    Publication is per shard file, so the verdict is too. The broken school
    keeps its previously committed shard; the rest publish.
    """
    graph = _graph_ok(fetched=20)
    verdict = evaluate_refresh_summary(
        _summary(
            {"ucsb", "umich", "caltech"},
            {
                "campus_graph:ucsb": graph,
                "campus_graph:umich": _graph_ok(fetched=12),
                "campus_graph:caltech": _graph_ok(fetched=31),
                "ucsb_faculty": _ok(300),
                "umich_faculty": _ok(1420),
                "caltech_faculty": _ok(469),
                "ucsb_urca_projects": {
                    "status": "error",
                    "error": "URCA sitemap evidence is incomplete",
                },
            },
        ),
        schools={"ucsb", "umich", "caltech"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is False
    assert verdict["publishable"] == ["caltech", "umich"]
    assert verdict["by_unit"]["ucsb"]["ready"] is False
    assert any(
        "ucsb_urca_projects" in reason
        for reason in verdict["by_unit"]["ucsb"]["reasons"]
    )
    assert verdict["by_unit"]["umich"]["reasons"] == []
    assert verdict["structural_reasons"] == []


def test_a_structural_failure_publishes_nothing():
    """A shard that does not match the request invalidates every unit.

    Per-school publication is only safe while the summary can be trusted to
    describe the run that produced it.
    """
    summary = _summary(
        {"uw", "wisc"},
        {
            "campus_graph:uw": _graph_ok(),
            "campus_graph:wisc": _graph_ok(),
            "uw_faculty": _ok(100),
            "wisc_faculty": _ok(100),
        },
    )
    summary["shard"] = {"schools": ["uw"], "national": False}

    verdict = evaluate_refresh_summary(
        summary, schools={"uw", "wisc"}, national=False, deep=True
    )

    assert verdict["ready"] is False
    assert verdict["publishable"] == []
    assert verdict["structural_reasons"]
    assert all(not v["ready"] for v in verdict["by_unit"].values())


def test_a_clean_shard_publishes_every_unit_it_targeted():
    verdict = evaluate_refresh_summary(
        _summary(
            {"uw", "wisc"},
            {
                "campus_graph:uw": _graph_ok(),
                "campus_graph:wisc": _graph_ok(),
                "uw_faculty": _ok(100),
                "wisc_faculty": _ok(100),
                "deactivate_stale_faculty": {
                    "status": "ok",
                    "skipped_partial_scrape": [],
                },
            },
        ),
        schools={"uw", "wisc"},
        national=False,
        deep=True,
    )

    assert verdict["ready"] is True
    assert verdict["publishable"] == ["uw", "wisc"]


def test_a_broken_national_source_withholds_only_national():
    verdict = evaluate_refresh_summary(
        _summary(
            None,
            {
                key: (
                    {"status": "error", "error": "NSF API 500"}
                    if key == "nsf_reu" else _ok(3)
                )
                for key in NATIONAL_SOURCES
            },
            national=True,
        ),
        schools=None,
        national=True,
        deep=True,
    )

    assert verdict["ready"] is False
    assert verdict["publishable"] == []
    assert verdict["by_unit"]["national"]["ready"] is False


# ---------------------------------------------------------------------------
# The UC Berkeley shape, from the run recorded on 2026-09-05: 56 sources, 55
# harvesting cleanly, one silent zero, and five departments scraping 94-100%
# of their stored counts. That run published nothing for a fourth consecutive
# week, and 3,062 records went on aging.
# ---------------------------------------------------------------------------

_UCB_PARTIAL = [
    "ucb_datascience_faculty", "ucb_econ_faculty", "ucb_ling_faculty",
    "ucb_scandinavian_faculty", "ucb_soc_faculty",
]


def _ucb_summary(**over):
    """UCB as it actually ran: every source ok except the ones named here."""
    sources = {
        key: _ok(40)
        for key in expected_sources({"ucb"}, national=False, deep=True)
    }
    sources["ucb_campus"] = _graph_ok()
    sources["ucb_eecs_faculty"] = {
        "status": "suspicious_zero", "fetched": 0,
        "suspicious_zero_baseline": 144, "zero_class": "suspicious_zero",
    }
    sources["deactivate_stale_faculty"] = {
        "status": "ok",
        "skipped_partial_scrape": list(_UCB_PARTIAL),
    }
    sources.update(over)
    return evaluate_refresh_summary(
        _summary({"ucb"}, sources), schools={"ucb"}, national=False, deep=True,
    )


class TestUcbShardIsolation:
    def test_healthy_departments_publish_while_one_is_dead_and_five_are_short(self):
        verdict = _ucb_summary()
        assert verdict["ready"] is True
        assert verdict["publishable"] == ["ucb"]
        assert verdict["reasons"] == []

    def test_the_school_is_partially_degraded_not_blocked(self):
        verdict = _ucb_summary()
        assert verdict["status"] == "degraded"
        assert verdict["by_unit"]["ucb"]["ready"] is True

    def test_a_suspicious_zero_is_not_published_as_data(self):
        """It degrades and keeps its baseline; nothing claims it was seen."""
        verdict = _ucb_summary()
        zero = [d for d in verdict["degradations"]
                if d["kind"] == "suspicious_zero"]
        assert [d["source"] for d in zero] == ["ucb_eecs_faculty"]
        assert "144" in zero[0]["detail"]

    def test_every_short_department_is_reported_individually(self):
        """One incident per source, so a second one going short is visible."""
        verdict = _ucb_summary()
        short = sorted(d["source"] for d in verdict["degradations"]
                       if d["kind"] == "partial_scrape")
        assert short == sorted(_UCB_PARTIAL)

    def test_one_dead_department_does_not_veto_unrelated_schools(self):
        """The between-school half of the invariant, which already held."""
        sources = {
            key: _ok(40)
            for key in expected_sources({"ucb", "uw"}, national=False, deep=True)
        }
        sources["ucb_campus"] = _graph_ok()
        sources["campus_graph:uw"] = _graph_ok()
        sources["ucb_eecs_faculty"] = {
            "status": "suspicious_zero", "fetched": 0,
            "suspicious_zero_baseline": 144,
        }
        sources["deactivate_stale_faculty"] = {
            "status": "ok", "skipped_partial_scrape": list(_UCB_PARTIAL),
        }
        verdict = evaluate_refresh_summary(
            _summary({"ucb", "uw"}, sources),
            schools={"ucb", "uw"}, national=False, deep=True,
        )
        assert verdict["publishable"] == ["ucb", "uw"]

    def test_a_structural_fault_still_withholds_everything(self):
        """Degrading a department must not have loosened the real blocks.

        A reason nobody can pin to a shard describes the run itself, and
        publishing on that evidence would be a guess.
        """
        verdict = _ucb_summary(**{"ucb_stat_faculty": {"status": "error",
                                                       "error": "boom"}})
        assert verdict["ready"] is False
        assert verdict["publishable"] == []

    def test_an_error_status_still_blocks_its_own_school(self):
        verdict = _ucb_summary(**{"ucb_chem_faculty": {"status": "error",
                                                       "error": "boom"}})
        assert verdict["by_unit"]["ucb"]["ready"] is False
