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
from src.collectors.refresh_contract import expected_sources
from src.normalizers.deactivate_stale_faculty import (
    FACULTY_SOURCES,
    identity_key,
    listed_token,
)

# All Berkeley faculty collectors wired into refresh_all's deep block. Derived
# from the canonical FACULTY_SOURCES set so this stays in lockstep as new
# department directories are added.
UCB_FACULTY_SOURCES = {s for s in FACULTY_SOURCES if s.startswith("ucb_")}


def _stub_all_collectors(monkeypatch, tmp_path):
    def conditions(records, **kwargs):
        # This registration helper performs no condition requests. The real
        # zero-budget pass still reports missing/invalid pages honestly.
        from src.collectors.faculty_condition_refresh import refresh_faculty_condition_sources
        return refresh_faculty_condition_sources(records, max_requests=0)
    monkeypatch.setattr(refresh_all, "refresh_faculty_condition_sources", conditions)
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
    # No refresh under test asks a UIUC profile page whether it is gone.
    monkeypatch.setattr("src.collectors.uiuc_faculty.profile_page_answer",
                        lambda url: pytest.fail(f"No external network permitted: {url}"))
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
        "fetch_sro_with_evidence",
        lambda **kwargs: ([], {}),
    )
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


# The schools another maintainer built. Until 2026-11-24 the title passes
# counted their rows and left them (M159).
_BUILT_BY_ANOTHER_MAINTAINER = ("bc", "emory", "georgetown", "nyu", "tufts", "uga", "unc", "uva")


def _stub_with_processed_file(monkeypatch, tmp_path, seeded):
    _stub_all_collectors(monkeypatch, tmp_path)
    processed = tmp_path / "opportunities.json"
    processed.write_text(json.dumps(seeded), encoding="utf-8")
    monkeypatch.setattr(refresh_all, "PROCESSED_FILE", processed)
    monkeypatch.setattr(
        refresh_all, "enrich_pi",
        lambda opps, save=True, max_scrapes=None, deadline=None: {
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


@pytest.mark.parametrize("identity,carried", [
    (["url", "testu.edu/users/ana-belmonte"], True),
    (["email", "person1@testu.edu"], False),
], ids=["page_observed", "address_observed"])
def test_a_kept_row_takes_another_units_date_only_through_an_observed_page(
    monkeypatch, tmp_path, identity, carried,
):
    """The same-person collapse after the retirement pass is handed the
    profile pages the run's unit ledgers observed: one person's two rows on
    one such page leave the kept row with the newer date; a page the run did
    not observe moves nothing across units."""
    def row(rid, name, dept, url, days_ago, keywords=()):
        seeded = _seed_faculty("umich_faculty", rid, days_ago)
        seeded.update(school="umich", department=dept, pi_name=name, url=url,
                      contact_email="person1@testu.edu", keywords=list(keywords))
        return seeded

    stale = row("faculty-umich-cse-0000aaaa", "Ana Belmonte, Ph.D.", "Computer Science",
                "https://www.testu.edu/users/Ana-Belmonte/", 30, ["hydrology", "climate"])
    fresh = row("faculty-umich-ece-0000bbbb", "Ana Belmonte", "Electrical Engineering",
                "https://www.testu.edu/users/ana-belmonte", 0)
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [stale, fresh])

    def fetch(unit_ledger):
        unit_ledger["ece"] = {"unit_id": "ece", "observed_entity_ids": [fresh["id"]],
                              "observed_identities": [identity],
                              "unit_url": "https://ece.testu.edu/people/"}
        return [dict(fresh)]

    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    refresh_all.refresh_all(deep=True, schools={"umich"})

    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert [(r["id"], r["metadata"]["is_active"]) for r in saved] == [
        (stale["id"], True), (fresh["id"], False)]
    expected = fresh if carried else stale
    assert saved[0]["metadata"]["last_seen_at"] == expected["metadata"]["last_seen_at"]


@pytest.mark.parametrize("moved_rows", [0, 1, 201])
def test_the_run_summary_counts_and_names_the_rows_kept_as_moved(
    monkeypatch, tmp_path, moved_rows,
):
    """A stored row its own unit, read in full, no longer lists is kept when
    another unit read the same person this run. The run summary counts all
    those rows and names them in the pass's order, the names capped as
    would_deactivate is. A row its unit still lists, a row a held source would
    retire and a row no unit read are not among them."""
    def row(rid, url, days_ago, school="umich"):
        seeded = _seed_faculty(f"{school}_faculty", rid, days_ago)
        seeded.update(school=school, department="CSE", url=url)
        return seeded

    def unit(unit_id, rows, identities, listed=()):
        coverage = dict.fromkeys(
            ("classified_nonfaculty_rows", "unparsed_rows", "ambiguous_rows",
             "duplicate_rows", "identity_match_failures", "parser_errors",
             "partial_render_rows"), 0)
        coverage.update(raw_roster_rows=len(identities),
                        parsed_faculty_rows=len(identities))
        return {"unit_id": unit_id, "unit_url": f"https://{unit_id}.testu.edu/people/",
                "fetch_status": "ok", "parse_status": "ok", "validation_status": "ok",
                "roster_source_confirmed": True, "observed_count": len(identities),
                "observed_entity_ids": [r["id"] for r in rows],
                "observed_identities": [["url", i] for i in identities],
                "listed_identities": [listed_token("url", i) for i in listed],
                "coverage": coverage}

    colleague = row("faculty-umich-cse-0000aaaa", "https://www.testu.edu/people/stays", 0)
    departed = row("faculty-umich-cse-0000bbbb", "https://www.testu.edu/people/left", 30)
    still_listed = row("faculty-umich-cse-0000cccc", "https://www.testu.edu/people/listed", 30)
    held = row("faculty-uw-cse-0000dddd", "https://www.testu.edu/people/held", 30,
               school="uw")
    # Seeded in neither id order, so a list sorted either way is not the pass's.
    order = [*range(1, moved_rows, 2), *range(0, moved_rows, 2)]
    moved = [row(f"faculty-umich-cse-{i:08x}", f"https://www.testu.edu/people/m{i}", 30)
             for i in order]
    processed = _stub_with_processed_file(
        monkeypatch, tmp_path, [colleague, departed, still_listed, held, *moved])

    def fetch_umich(unit_ledger):
        unit_ledger["cse"] = unit("cse", [colleague], ["testu.edu/people/stays"],
                                  listed=["testu.edu/people/listed"])
        unit_ledger["ece"] = unit(
            "ece", [], [f"testu.edu/people/m{i}" for i in range(moved_rows)])
        return [dict(colleague)]

    def fetch_uw(unit_ledger):
        newcomer = row("faculty-uw-cse-0000eeee", "https://www.testu.edu/people/new", 0,
                       school="uw")
        unit_ledger["cse"] = unit("cse", [newcomer], ["testu.edu/people/new"])
        return [newcomer]

    real_pass = refresh_all.deactivate_stale_faculty
    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch_umich)
    monkeypatch.setattr(refresh_all, "fetch_uw_faculty", fetch_uw)
    # The run holds only uiuc_faculty, whose count ledger proposes no one, so
    # uw_faculty is held as well to give would_deactivate a row.
    monkeypatch.setattr(
        refresh_all, "deactivate_stale_faculty",
        lambda opps, fetched, held_sources: real_pass(
            opps, fetched, held_sources={*held_sources, "uw_faculty"}))
    summary = refresh_all.refresh_all(deep=True, schools={"umich", "uw"})

    pass_info = summary["sources"]["deactivate_stale_faculty"]
    assert pass_info["newly_deactivated"] == 1
    assert pass_info["records_preserved_still_listed"] == 1
    assert pass_info["would_deactivate"] == [held["id"]]
    assert pass_info["records_preserved_moved_unit"] == moved_rows
    assert pass_info["moved_unit_ids"] == [r["id"] for r in moved][:200]
    saved = {r["id"]: r["metadata"]["is_active"]
             for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert saved == {colleague["id"]: True, departed["id"]: False,
                     still_listed["id"]: True, held["id"]: True,
                     **{r["id"]: True for r in moved}}


def test_a_list_page_person_only_another_unit_lists_is_archived_under_its_row(
    monkeypatch, tmp_path,
):
    """A list-page row past the grace window, whose own unit read its page in
    full without them while another unit read the same person, ends the run
    inactive with ``duplicate_of`` naming that unit's row, which stays live.
    The summary counts and names it; no id leaves the corpus (M178)."""
    pages = {"me": "https://me.testu.edu/people", "ece": "https://ece.testu.edu/people"}
    listing = {"me.testu.edu/people", "ece.testu.edu/people"}

    def row(rid, unit, name, days_ago, **fields):
        seeded = _seed_faculty("umich_faculty", rid, days_ago)
        seeded.update(school="umich", department=unit.upper(), pi_name=name,
                      url=pages[unit], **fields)
        return seeded

    def unit(unit_id, rows):
        coverage = dict.fromkeys(
            ("classified_nonfaculty_rows", "unparsed_rows", "ambiguous_rows",
             "duplicate_rows", "identity_match_failures", "parser_errors",
             "partial_render_rows"), 0)
        coverage.update(raw_roster_rows=len(rows), parsed_faculty_rows=len(rows))
        return {"unit_id": unit_id, "unit_url": pages[unit_id],
                "fetch_status": "ok", "parse_status": "ok", "validation_status": "ok",
                "roster_source_confirmed": True, "observed_count": len(rows),
                "observed_entity_ids": [r["id"] for r in rows],
                "observed_identities": [list(identity_key(r, listing)) for r in rows],
                "listing_urls": [pages[unit_id].split("//")[1]],
                # The page was recorded, and shows none of the stored people.
                "page_people": [], "coverage": coverage}

    colleague = row("faculty-umich-me-0000aaaa", "me", "Robin Example", 0)
    old = row("faculty-umich-me-0000bbbb", "me", "Kim Sample", 30,
              contact_email="person4@testu.edu", keywords=["optics"])
    new = row("faculty-umich-ece-0000cccc", "ece", "Kim Sample", 0,
              contact_email="person4@testu.edu")
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [colleague, old, new])

    def fetch(unit_ledger):
        unit_ledger["me"] = unit("me", [colleague])
        unit_ledger["ece"] = unit("ece", [new])
        return [dict(colleague), dict(new)]

    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})

    pass_info = summary["sources"]["deactivate_stale_faculty"]
    assert pass_info["records_archived_moved_unit"] == 1
    assert pass_info["archived_moved_unit_ids"] == [old["id"]]
    assert pass_info["records_preserved_moved_unit"] == 0
    assert pass_info["moved_unit_ids"] == []
    assert pass_info["newly_deactivated"] == 0
    saved = {r["id"]: r["metadata"] for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert sorted(saved) == sorted([colleague["id"], old["id"], new["id"]])
    assert (saved[old["id"]]["is_active"], saved[old["id"]]["deactivation_reason"],
            saved[old["id"]]["duplicate_of"]) == (False, "duplicate_of_live_record", new["id"])
    assert saved[new["id"]]["is_active"] is True and "duplicate_of" not in saved[new["id"]]


def _umich_row(rid, dept, keywords, email="person7@testu.edu"):
    """One umich faculty row of one person, seen today."""
    seeded = _seed_faculty("umich_faculty", rid, 0)
    seeded.update(school="umich", department=dept, pi_name="Avery Sample",
                  url=f"https://{dept.lower()}.testu.edu/people/{rid[-4:]}",
                  contact_email=email, keywords=keywords)
    return seeded


def test_a_published_duplicate_is_archived_and_one_minted_this_run_is_deleted(
    monkeypatch, tmp_path,
):
    """The collapse is handed the ids the corpus held when the run started: a
    duplicate it drops among those stays, inactive and naming the kept row (a
    student may have saved it); a duplicate this run's merge minted is deleted."""
    kept = _umich_row("faculty-umich-cse-0000cccc", "CSE", ["optics", "lasers", "imaging"])
    published = _umich_row("faculty-umich-ece-0000dddd", "ECE", ["optics"])
    minted = _umich_row("faculty-umich-math-0000eeee", "Math", ["optics", "lasers"])
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [kept, published])

    def merge(opps):
        corpus = json.loads(processed.read_text(encoding="utf-8"))
        processed.write_text(json.dumps(corpus + [minted]), encoding="utf-8")
        return (1, 0)

    monkeypatch.setattr(refresh_all, "merge_umich_faculty", merge)
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})

    saved = {r["id"]: r["metadata"] for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert sorted(saved) == [kept["id"], published["id"]]
    assert saved[kept["id"]]["is_active"] is True
    assert {k: saved[published["id"]][k] for k in ("is_active", "deactivation_reason", "duplicate_of")} == {
        "is_active": False, "deactivation_reason": "duplicate_of_live_record", "duplicate_of": kept["id"]}
    hygiene = summary["sources"]["faculty_hygiene"]
    assert (hygiene["removed_by_school"], hygiene["archived_by_school"]) == ({"umich": 1}, {"umich": 1})


def test_a_row_archived_before_keeps_its_date_when_its_unit_lists_it_again(
    monkeypatch, tmp_path,
):
    """The merge replaces the metadata of a row its unit lists again, so a row
    archived on an earlier run comes back active. Archived again under the same
    kept row, it keeps that run's date, and this run archives nothing new."""
    kept = _umich_row("faculty-umich-cse-0000cccc", "CSE", ["optics", "lasers", "imaging"])
    archived = _umich_row("faculty-umich-ece-0000dddd", "ECE", ["optics"])
    listed_again = json.loads(json.dumps(archived))
    archived["metadata"].update(is_active=False, deactivated_at="2026-10-30",
                                deactivation_reason="duplicate_of_live_record", duplicate_of=kept["id"])
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [kept, archived])

    def merge(opps):
        corpus = json.loads(processed.read_text(encoding="utf-8"))
        corpus = [listed_again if r["id"] == listed_again["id"] else r for r in corpus]
        processed.write_text(json.dumps(corpus), encoding="utf-8")
        return (0, 1)

    monkeypatch.setattr(refresh_all, "merge_umich_faculty", merge)
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})

    saved = {r["id"]: r["metadata"] for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert {k: saved[archived["id"]].get(k) for k in (
        "is_active", "deactivated_at", "deactivation_reason", "duplicate_of")} == {
        "is_active": False, "deactivated_at": "2026-10-30",
        "deactivation_reason": "duplicate_of_live_record", "duplicate_of": kept["id"]}
    assert summary["sources"]["faculty_hygiene"]["archived_by_school"] == {}


def test_a_published_tombstone_of_a_live_row_is_kept_naming_it(monkeypatch, tmp_path, caplog):
    """The run-start ids include inactive rows: a published tombstone of a live
    row stays, with its own retirement, naming the live row; the run log
    counts it."""
    live = _umich_row("faculty-umich-cse-0000cccc", "CSE", ["optics", "lasers"])
    tomb = _umich_row("faculty-umich-ece-0000dddd", "ECE", ["optics"])
    tomb["metadata"].update(is_active=False, deactivated_at="2026-10-01",
                            deactivation_reason="absent_from_directory_rescrape")
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [live, tomb])

    with caplog.at_level(logging.INFO, logger=refresh_all.logger.name):
        refresh_all.refresh_all(deep=True, schools={"umich"})

    saved = {r["id"]: r["metadata"] for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert {k: saved[tomb["id"]].get(k) for k in (
        "is_active", "deactivated_at", "deactivation_reason", "duplicate_of")} == {
        "is_active": False, "deactivated_at": "2026-10-01",
        "deactivation_reason": "absent_from_directory_rescrape", "duplicate_of": live["id"]}
    assert "0 duplicate person(s) removed, 1 published duplicate(s) newly archived" in caplog.text


def _uiuc_card(name, keywords):
    from src.collectors.uiuc_faculty import DEPARTMENTS, normalize_faculty

    psych = DEPARTMENTS["psych"]
    return normalize_faculty({"name": name, "email": "person1@illinois.edu",
                              "url": f"{psych['base']}/directory/profile/person1"}, psych, keywords=keywords)


def _run_the_uiuc_merge(monkeypatch, tmp_path, stored, fresh):
    """A quick uiuc run whose static fetch reads ``fresh``, merged by the real
    uiuc merge into the work file seeded with ``stored``."""
    from src.collectors import uiuc_faculty

    processed = _stub_with_processed_file(monkeypatch, tmp_path, stored)
    monkeypatch.setattr(refresh_all, "fetch_faculty", lambda *a, **k: json.loads(json.dumps(fresh)))
    monkeypatch.setattr(refresh_all, "merge_faculty", lambda opps, **kwargs: uiuc_faculty.merge_into_processed(
        opps, str(processed), **kwargs))
    refresh_all.refresh_all(deep=False, schools={"uiuc"})
    return {r["id"]: r["metadata"] for r in json.loads(processed.read_text(encoding="utf-8"))}


def test_the_uiuc_merge_keeps_a_published_duplicate_inactive(monkeypatch, tmp_path):
    """The uiuc merge's dedups are handed the run-start ids too: a published row
    they drop for a card read this run stays, inactive and naming that card."""
    published = _uiuc_card("Avery Q. Sample", ["psychology"])
    card = _uiuc_card("Avery Sample", ["memory", "attention"])
    saved = _run_the_uiuc_merge(monkeypatch, tmp_path, [published], [card])
    assert saved[card["id"]]["is_active"] is True
    assert {k: saved[published["id"]].get(k) for k in ("is_active", "deactivation_reason", "duplicate_of")} == {
        "is_active": False, "deactivation_reason": "duplicate_of_live_record", "duplicate_of": card["id"]}


def test_the_uiuc_merge_keeps_the_date_of_a_duplicate_its_page_lists_again(monkeypatch, tmp_path):
    """And the run-start stamps: a published duplicate the page lists again comes
    back active from the merge and is archived again under the same card on the
    day it was first archived."""
    card = _uiuc_card("Avery Sample", ["memory", "attention"])
    listed_again = _uiuc_card("Avery Q. Sample", ["psychology"])
    archived = json.loads(json.dumps(listed_again))
    archived["metadata"].update(is_active=False, deactivated_at="2026-10-26",
                                deactivation_reason="duplicate_of_live_record", duplicate_of=card["id"])
    saved = _run_the_uiuc_merge(monkeypatch, tmp_path, [card, archived], [card, listed_again])
    assert {k: saved[archived["id"]].get(k) for k in ("is_active", "deactivated_at", "duplicate_of")} == {
        "is_active": False, "deactivated_at": "2026-10-26", "duplicate_of": card["id"]}


def test_a_faculty_graph_fetch_reads_the_run_start_ids(monkeypatch, tmp_path):
    """The school-wide dedup inside a faculty_graph fetch keeps a stored
    person's row over one it would mint, so the fetch is handed the ids the
    corpus held before anything merged; none outside it."""
    from src.collectors import faculty_graph

    stored = _umich_row("faculty-umich-ece-0000dddd", "ECE", ["optics"])
    _stub_with_processed_file(monkeypatch, tmp_path, [stored])
    seen = []

    def fetch(unit_ledger=None):
        seen.append(faculty_graph._RUN_START_IDS)
        return []

    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    refresh_all.refresh_all(deep=True, schools={"umich"})
    assert seen == [frozenset({stored["id"]})]
    assert faculty_graph._RUN_START_IDS == frozenset()


def test_the_monthly_profile_pass_skips_a_page_the_run_start_corpus_captured(monkeypatch, tmp_path):
    """A faculty_graph fetch is handed the profile pages the corpus held a
    capture of before anything merged, with the fields their rows held, and
    the monthly pass does not fetch a page whose row holds what it reads
    (M176); none outside the fetch."""
    from src.collectors import faculty_graph
    from src.contact_instructions import CAPTURE_KEY, SOURCE_KEY, merge_contact_instruction_sources

    listed = _umich_row("faculty-umich-ece-0000dddd", "ECE", ["optics"])
    stored = json.loads(json.dumps(listed))
    stored["metadata"][CAPTURE_KEY] = {
        "version": 1, "status": "empty", "reason": None, "attempted_at": "2026-10-02T12:00:00+00:00",
        "source_url": listed["url"], "record_source_url": listed["url"], "identity_name": "Avery Sample"}
    stored["metadata"][SOURCE_KEY] = []
    merge_contact_instruction_sources(listed, stored)
    _stub_with_processed_file(monkeypatch, tmp_path, [stored])
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", True)
    fetched = []
    monkeypatch.setattr(faculty_graph, "_enrich_profile",
                        lambda url, _enr, **_k: fetched.append(url) or ("", "", [], None, False))
    other = "https://ece.testu.edu/people/eeee"

    def fetch(unit_ledger=None):
        faculty_graph._apply_profile_enrich(
            [{"name": "Avery Sample", "url": listed["url"]}, {"name": "Blake Sample", "url": other}],
            {"research_selector": ".research"})
        return []

    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    refresh_all.refresh_all(deep=True, schools={"umich"})
    assert fetched == [other]
    assert faculty_graph._RUN_START_PROFILES == {}


def _ucb_row(rid, source, dept, keywords):
    seeded = _seed_faculty(source, rid, 0)
    seeded.update(school="ucb", department=dept, pi_name="Toni Varga", keywords=keywords,
                  url=f"https://{source[4:8]}.testu.edu/people/toni-varga")
    return seeded


def test_the_berkeley_collapse_keeps_a_published_duplicate_inactive(monkeypatch, tmp_path):
    """The Berkeley joint-appointment collapse is handed the run-start ids and
    stamps too: a published row it drops stays, inactive and naming the row
    kept; the run summary counts it."""
    kept = _ucb_row("faculty-ucb-bioe-0000aaaa", "ucb_bioe_faculty", "Bioengineering", ["biomechanics", "bone"])
    dup = _ucb_row("faculty-ucb-me-0000bbbb", "ucb_me_faculty", "Mechanical Engineering", [])
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [kept, dup])
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})
    saved = {r["id"]: r["metadata"] for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert saved[kept["id"]]["is_active"] is True
    assert {k: saved[dup["id"]].get(k) for k in ("is_active", "deactivation_reason", "duplicate_of")} == {
        "is_active": False, "deactivation_reason": "duplicate_of_live_record", "duplicate_of": kept["id"]}
    collapse = summary["sources"]["faculty_joint_collapse"]
    assert (collapse["duplicates_removed"], collapse["duplicates_archived"]) == (0, 1)


def test_the_berkeley_collapse_keeps_the_date_of_a_duplicate_listed_again(monkeypatch, tmp_path):
    kept = _ucb_row("faculty-ucb-bioe-0000aaaa", "ucb_bioe_faculty", "Bioengineering", ["biomechanics", "bone"])
    listed_again = _ucb_row("faculty-ucb-me-0000bbbb", "ucb_me_faculty", "Mechanical Engineering", [])
    archived = json.loads(json.dumps(listed_again))
    archived["metadata"].update(is_active=False, deactivated_at="2026-10-30",
                                deactivation_reason="duplicate_of_live_record", duplicate_of=kept["id"])
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [kept, archived])

    def merge(opps):
        corpus = json.loads(processed.read_text(encoding="utf-8"))
        processed.write_text(json.dumps([listed_again if r["id"] == archived["id"] else r for r in corpus]),
                             encoding="utf-8")
        return (0, 1)

    monkeypatch.setattr(refresh_all, "merge_umich_faculty", merge)
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})
    saved = {r["id"]: r["metadata"] for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert {k: saved[archived["id"]].get(k) for k in ("is_active", "deactivated_at", "duplicate_of")} == {
        "is_active": False, "deactivated_at": "2026-10-30", "duplicate_of": kept["id"]}
    assert summary["sources"]["faculty_joint_collapse"]["duplicates_archived"] == 0


def test_refresh_persists_a_retained_department_for_public_freshness(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from src.collectors import source_health

    chem = _seed_faculty("umich_faculty", "faculty-umich-chem-0000cccc", 60)
    bio = _seed_faculty("umich_faculty", "faculty-umich-bio-0000dddd", 0)
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [chem, bio])

    def fetch(unit_ledger):
        unit_ledger["chem"] = {
            "source": "umich_faculty", "unit_id": "chem", "fetch_status": "ok",
            "parse_status": "zero_rows", "validation_status": "ok", "observed_count": 0,
            "observed_entity_ids": [], "observed_identities": [],
        }
        return [dict(bio)]

    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})
    ledger = source_health.load_ledger(tmp_path / "source_health.json")
    assert summary["sources"]["umich_faculty"]["status"] == "ok"
    assert ledger["sources"]["umich_faculty"]["unchecked_faculty_units"] == ["chem"]
    assert source_health.public_school_freshness(ledger, datetime.now(UTC), {"umich_faculty"})[
        "umich"]["status"] == "partly_unchecked"
    saved = {r["id"]: r for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert saved[chem["id"]]["metadata"]["last_seen_at"] == chem["metadata"]["last_seen_at"]


def test_refresh_counts_the_professors_a_school_did_not_re_observe(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from src.collectors import source_health

    unread = [_seed_faculty("umich_faculty", f"faculty-umich-chem-0000ccc{i}", 60) for i in range(2)]
    bio = _seed_faculty("umich_faculty", "faculty-umich-bio-0000dddd", 0)
    _stub_with_processed_file(monkeypatch, tmp_path, [*unread, bio])

    def fetch(unit_ledger):
        unit_ledger["chem"] = {
            "source": "umich_faculty", "unit_id": "chem", "fetch_status": "ok",
            "parse_status": "zero_rows", "validation_status": "ok", "observed_count": 0,
            "observed_entity_ids": [], "observed_identities": [],
        }
        return [dict(bio)]

    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    refresh_all.refresh_all(deep=True, schools={"umich"})
    ledger = source_health.load_ledger(tmp_path / "source_health.json")
    assert ledger["sources"]["umich_faculty"]["faculty_sightings"] == {"active": 3, "reobserved": 1}
    assert source_health.public_school_freshness(ledger, datetime.now(UTC), {"umich_faculty"})[
        "umich"]["status"] == "stale"


def test_refresh_counts_professors_in_the_rows_it_persists(monkeypatch, tmp_path):
    """The stale pass retires two of three rows after the attempts are
    recorded. Counted before it, the school would read one third re-observed."""
    from src.collectors import source_health

    seeded = [
        _seed_faculty("umich_faculty", "fac-gone-1", days_ago=30),
        _seed_faculty("umich_faculty", "fac-gone-2", days_ago=30),
        _seed_faculty("umich_faculty", "fac-fresh", days_ago=1),
    ]
    _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    monkeypatch.setattr(refresh_all, "fetch_umich_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(3)])
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 2
    ledger = source_health.load_ledger(tmp_path / "source_health.json")
    assert ledger["sources"]["umich_faculty"]["faculty_sightings"] == {"active": 1, "reobserved": 1}


def test_the_run_summary_does_not_call_a_mostly_unread_school_fully_fresh(monkeypatch, tmp_path):
    """Every source of the school succeeds and its roster returns one of three
    stored professors: too few to retire the others, and no unit to flag."""
    seeded = [
        _seed_faculty("umich_faculty", "fac-unread-1", days_ago=20),
        _seed_faculty("umich_faculty", "fac-unread-2", days_ago=20),
        _seed_faculty("umich_faculty", "fac-read", days_ago=0),
    ]
    _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", lambda *a, **k: [{"id": "fac-read"}])
    monkeypatch.setattr(
        refresh_all, "fetch_campus_graph_with_evidence",
        lambda *a, **k: ([{"id": "campus-one"}], {
            "deep": True, "crawl_sources_expected": 1, "crawl_sources_loaded": 1,
            "live_pages_attempted": 1, "live_pages_loaded": 1, "seed_records": 0,
            "discovered_records": 1, "crawl_errors": []}))
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
    assert {name: summary["zero_classes"][name] for name in ("umich_faculty", "campus_graph:umich")} == {
        "umich_faculty": "success_nonzero", "campus_graph:umich": "success_nonzero"}
    report = summary["source_health"]
    assert (report["fully_fresh_school_count"], report["partially_degraded_school_count"]) == (0, 1)


def test_the_refresh_retires_trainee_rows_before_the_unit_ledgers_count(
    monkeypatch, tmp_path,
):
    """Graduate students and postdocs are retired by title on every run, in this
    run's schools only, before finalize_unit_ledger counts a unit's active rows
    (a trainee row still active there would read as a person the scrape missed
    and block the unit)."""
    def row(rid, school, title):
        seeded = _seed_faculty(f"{school}_faculty", rid, 0)
        seeded.update(school=school, department="Earth Sciences")
        seeded["metadata"]["faculty_title"] = title
        return seeded

    student = row("faculty-umich-earth-0000cccc", "umich",
                  "Graduate Student Advisor: Professor Doe")
    professor = row("faculty-umich-earth-0000dddd", "umich", "Associate Professor")
    elsewhere = row("faculty-osu-earth-0000eeee", "osu", "Graduate Student")
    built_elsewhere = [row(f"faculty-{slug}-ads-0000ffff", slug, "PhD; Major Professor: Doe")
                       for slug in _BUILT_BY_ANOTHER_MAINTAINER]
    processed = _stub_with_processed_file(
        monkeypatch, tmp_path, [student, professor, elsewhere, *built_elsewhere])

    active_at_ledger = []
    finalize = refresh_all.finalize_unit_ledger

    def recording_finalize(ledger, opps, name):
        active_at_ledger.extend(
            o["metadata"]["is_active"] for o in opps if o["id"] == student["id"])
        return finalize(ledger, opps, name)

    def fetch(unit_ledger):
        unit_ledger["earth"] = {"unit_id": "earth", "observed_entity_ids": [professor["id"]],
                                "observed_identities": [["url", "testu.edu/people/prof"]],
                                "unit_url": "https://earth.testu.edu/people/"}
        return [dict(professor)]

    monkeypatch.setattr(refresh_all, "finalize_unit_ledger", recording_finalize)
    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    summary = refresh_all.refresh_all(deep=True, schools={"umich", *_BUILT_BY_ANOTHER_MAINTAINER})

    saved = {r["id"]: r for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert saved[student["id"]]["metadata"]["is_active"] is False
    assert saved[student["id"]]["metadata"]["deactivation_reason"] == "trainee_title"
    assert saved[professor["id"]]["metadata"]["is_active"] is True
    assert saved[elsewhere["id"]]["metadata"]["is_active"] is True
    assert active_at_ledger == [False]
    # The schools another maintainer built take the rule like any other.
    for retired in built_elsewhere:
        assert saved[retired["id"]]["metadata"]["is_active"] is False
        assert saved[retired["id"]]["metadata"]["deactivation_reason"] == "trainee_title"
    assert summary["sources"]["trainee_titles"]["by_school"] == {
        "umich": 1, **dict.fromkeys(_BUILT_BY_ANOTHER_MAINTAINER, 1)}
    assert summary["sources"]["trainee_titles"]["held"] == {}


def test_the_refresh_retires_rows_that_say_the_person_has_died_before_the_unit_ledgers_count(
    monkeypatch, tmp_path,
):
    """A row whose name or title says the person has died is retired on every
    run, in this run's schools only, before finalize_unit_ledger counts a
    unit's active rows; it keeps its id, and a chair named in someone's memory
    is a living person's title."""
    def row(rid, school, title, name="Jane Roe"):
        seeded = _seed_faculty(f"{school}_faculty", rid, 0)
        seeded.update(school=school, department="Earth Sciences", pi_name=name)
        seeded["metadata"]["faculty_title"] = title
        return seeded

    by_title = row("faculty-umich-earth-0001aaaa", "umich", "In Memoriam, Professor")
    by_name = row("faculty-umich-earth-0001bbbb", "umich", "Professor", "Jane Roe (In Memoriam)")
    chair = row("faculty-umich-earth-0001cccc", "umich", "Jane Roe Memorial Professor")
    elsewhere = row("faculty-osu-earth-0001dddd", "osu", "Professor of History, Deceased")
    built_elsewhere = [row(f"faculty-{slug}-ads-0001eeee", slug, "Professor", "In Memoriam: Jane Roe")
                       for slug in _BUILT_BY_ANOTHER_MAINTAINER]
    processed = _stub_with_processed_file(
        monkeypatch, tmp_path, [by_title, by_name, chair, elsewhere, *built_elsewhere])

    active_at_ledger = []
    finalize = refresh_all.finalize_unit_ledger

    def recording_finalize(ledger, opps, name):
        active_at_ledger.extend(
            o["metadata"]["is_active"] for o in opps if o["id"] in (by_title["id"], by_name["id"]))
        return finalize(ledger, opps, name)

    def fetch(unit_ledger):
        unit_ledger["earth"] = {"unit_id": "earth", "observed_entity_ids": [chair["id"]],
                                "observed_identities": [["url", "testu.edu/people/prof"]],
                                "unit_url": "https://earth.testu.edu/people/"}
        return [dict(chair)]

    monkeypatch.setattr(refresh_all, "finalize_unit_ledger", recording_finalize)
    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    summary = refresh_all.refresh_all(deep=True, schools={"umich", *_BUILT_BY_ANOTHER_MAINTAINER})

    saved = {r["id"]: r for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert len(saved) == 12
    # The schools another maintainer built take the rule like any other.
    for rid in (by_title["id"], by_name["id"], *(r["id"] for r in built_elsewhere)):
        assert saved[rid]["metadata"]["is_active"] is False
        assert saved[rid]["metadata"]["deactivation_reason"] == "listed_as_deceased"
    assert saved[chair["id"]]["metadata"]["is_active"] is True
    assert saved[elsewhere["id"]]["metadata"]["is_active"] is True
    assert active_at_ledger == [False, False]
    assert summary["sources"]["deceased_listings"] == {
        "deactivated": 10, "by_school": {"umich": 2, **dict.fromkeys(_BUILT_BY_ANOTHER_MAINTAINER, 1)},
        "held": {}, "status": "ok"}


def test_the_refresh_retires_rows_stored_under_an_emeritus_title_but_not_uiucs(
    monkeypatch, tmp_path,
):
    """A row stored under an emeritus title, in any spelling the rule reads, is
    retired on every run before the unit ledgers count. UIUC's collector lists
    an emeritus title beside a current role, so UIUC rows, and no other
    school's, are counted, not changed; a row that also says the person has
    died keeps that reason."""
    def row(rid, school, title):
        seeded = _seed_faculty(f"{school}_faculty", rid, 0)
        seeded.update(school=school, department="Earth Sciences", pi_name="Jane Roe")
        seeded["metadata"]["faculty_title"] = title
        return seeded

    emerit = row("faculty-umich-earth-0002aaaa", "umich", "Professor Emerit")
    emertius = row("faculty-umich-earth-0002bbbb", "umich", "Emertius, Professor of Chemistry")
    late = row("faculty-umich-earth-0002cccc", "umich", "In Memoriam, Professor Emertius")
    professor = row("faculty-umich-earth-0002dddd", "umich", "Professor of Emergency Medicine")
    uiuc = row("faculty-earth-0002eeee", "uiuc", "Research Professor, Professor Emeritus")
    built_elsewhere = [row(f"faculty-{slug}-ads-0002ffff", slug, "Professor Emerit")
                       for slug in _BUILT_BY_ANOTHER_MAINTAINER]
    elsewhere = row("faculty-osu-earth-00021111", "osu", "Professor Emerit")
    processed = _stub_with_processed_file(
        monkeypatch, tmp_path, [emerit, emertius, late, professor, uiuc, *built_elsewhere, elsewhere])

    active_at_ledger = []
    finalize = refresh_all.finalize_unit_ledger

    def recording_finalize(ledger, opps, name):
        active_at_ledger.extend(
            o["metadata"]["is_active"] for o in opps if o["id"] in (emerit["id"], emertius["id"]))
        return finalize(ledger, opps, name)

    def fetch(unit_ledger):
        unit_ledger["earth"] = {"unit_id": "earth", "observed_entity_ids": [professor["id"]],
                                "observed_identities": [["url", "testu.edu/people/prof"]],
                                "unit_url": "https://earth.testu.edu/people/"}
        return [dict(professor)]

    monkeypatch.setattr(refresh_all, "finalize_unit_ledger", recording_finalize)
    monkeypatch.setattr(refresh_all, "fetch_umich_faculty", fetch)
    summary = refresh_all.refresh_all(
        deep=True, schools={"umich", "uiuc", *_BUILT_BY_ANOTHER_MAINTAINER})

    saved = {r["id"]: r for r in json.loads(processed.read_text(encoding="utf-8"))}
    assert len(saved) == 14
    for rid in (emerit["id"], emertius["id"], *(r["id"] for r in built_elsewhere)):
        assert saved[rid]["metadata"]["is_active"] is False
        assert saved[rid]["metadata"]["deactivation_reason"] == "retired_title"
    assert saved[late["id"]]["metadata"]["deactivation_reason"] == "listed_as_deceased"
    assert active_at_ledger == [False, False]
    for rid in (professor["id"], uiuc["id"], elsewhere["id"]):
        assert saved[rid]["metadata"]["is_active"] is True
    assert summary["sources"]["retired_titles"] == {
        "deactivated": 10, "by_school": {"umich": 2, **dict.fromkeys(_BUILT_BY_ANOTHER_MAINTAINER, 1)},
        "held": {"uiuc": 1}, "status": "ok"}
    assert summary["sources"]["deceased_listings"]["by_school"] == {"umich": 1}


def test_a_partial_berkeley_scrape_with_postdoc_cards_still_retires_no_one(monkeypatch, tmp_path):
    """Berkeley sources report one count. A postdoc card must not stand in for a
    professor the scrape missed: 15 of 20 professors read alongside 6 postdoc
    cards is still a partial scrape that retires no one."""
    from src.collectors import ucb_common
    from src.collectors.ucb_math_faculty import MATH_CONFIG

    def row(rid, title):
        seeded = _seed_faculty("ucb_math_faculty", rid, days_ago=30)
        seeded["school"] = "ucb"
        seeded["metadata"]["faculty_title"] = title
        return seeded

    stored = ([row(f"faculty-ucb-math-prof{i:04d}", "Professor") for i in range(20)]
              + [row(f"faculty-ucb-math-post{i:04d}", "Postdoctoral Scholar") for i in range(6)])
    processed = _stub_with_processed_file(monkeypatch, tmp_path, stored)
    cards = ([{"name": f"Prof Number{chr(65 + i)}", "url": f"https://x/p{i}", "title": "Professor"}
              for i in range(15)]
             + [{"name": f"Post Doc{chr(65 + i)}", "url": f"https://x/d{i}",
                 "title": "Postdoctoral Scholar"} for i in range(6)])
    monkeypatch.setattr(refresh_all, "fetch_ucb_math", lambda *a, **k: [
        r for c in cards if (r := ucb_common.normalize_faculty(c, MATH_CONFIG))])

    summary = refresh_all.refresh_all(deep=True, schools={"ucb"})

    pass_info = summary["sources"]["deactivate_stale_faculty"]
    assert summary["sources"]["ucb_math_faculty"]["fetched"] == 15
    assert "ucb_math_faculty" in pass_info["skipped_partial_scrape"]
    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert all(r["metadata"]["is_active"] for r in saved if "prof" in r["id"])
    assert summary["sources"]["trainee_titles"]["by_school"] == {"ucb": 6}


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


def _uiuc_run_with_empty_departments(monkeypatch, tmp_path, stored_rows, empty):
    """A deep UIUC run whose static walk reads "Department of Wells" and none
    of ``empty``; ``stored_rows`` says how many rows, last seen 30 days ago,
    the corpus holds for each other department."""
    read = [_seed_faculty("uiuc_faculty", f"read-{index}", days_ago=0) for index in range(5)]
    for row in read:
        row["department"] = "Department of Wells"
    stored = []
    for department, count in stored_rows.items():
        for index in range(count):
            row = _seed_faculty("uiuc_faculty", f"{department} {index}", days_ago=30)
            row["department"] = department
            stored.append(row)
    processed = _stub_with_processed_file(monkeypatch, tmp_path, read + stored)
    _stub_successful_uiuc_deep_components(monkeypatch)
    monkeypatch.setattr(refresh_all, "fetch_faculty", lambda enrich: read)
    monkeypatch.setattr(refresh_all, "faculty_missing_departments", lambda _records: list(empty))
    # UIUC's other sources each read a row, so the departments are the run's only gap.
    for name in ("fetch_rss", "fetch_urap", "fetch_ursa", "fetch_drp", "fetch_siebel", "fetch_other"):
        monkeypatch.setattr(refresh_all, name, lambda *a, **k: [{"id": "listed"}])
    tracking = []
    monkeypatch.setattr(refresh_all, "_update_professor_tracking",
                        lambda *a, **k: tracking.append(k["refresh_ok"]))
    summary = refresh_all.refresh_all(deep=True, schools={"uiuc"})
    saved = {row["id"]: row for row in json.loads(processed.read_text(encoding="utf-8"))}
    return summary, [(row, saved[row["id"]]) for row in stored], tracking


@pytest.mark.parametrize("stored_rows", [
    {"Department of Tides": 3},
    {"Department of Tides": 3, "School of Kites": 1},
])
def test_one_or_two_empty_uiuc_departments_with_stored_rows_publish_uiuc(
    monkeypatch, tmp_path, stored_rows,
):
    summary, rows, tracking = _uiuc_run_with_empty_departments(
        monkeypatch, tmp_path, stored_rows, empty=sorted(stored_rows))

    faculty = summary["sources"]["uiuc_faculty"]
    release = summary["release"]
    assert faculty["status"] == "ok" and "error" not in faculty
    assert faculty["empty_departments"] == sorted(stored_rows)
    assert faculty["empty_department_baselines"] == stored_rows
    assert release["publishable"] == ["uiuc"] and release["status"] == "degraded"
    assert sorted(item["detail"] for item in release["degradations"]
                  if item["kind"] == "empty_department") == [
        f"{department}: 0 records, previously {count}"
        for department, count in sorted(stored_rows.items())]
    # The departments' rows keep the dates they had, and none is retired.
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
    for before, after in rows:
        assert after["metadata"] == before["metadata"]
    # Professor tracking reads directories as complete, so it stays closed.
    assert tracking == [False]


@pytest.mark.parametrize("stored_rows, empty", [
    ({"Department of Tides": 3, "School of Kites": 1, "Department of Maps": 2},
     ["Department of Tides", "School of Kites", "Department of Maps"]),
    ({"Department of Tides": 3}, ["Department of Tides", "School of Kites"]),
    ({}, ["Department of Tides"]),
])
def test_three_empty_uiuc_departments_or_one_without_stored_rows_withhold_uiuc(
    monkeypatch, tmp_path, stored_rows, empty,
):
    summary, rows, _ = _uiuc_run_with_empty_departments(monkeypatch, tmp_path, stored_rows, empty)

    faculty = summary["sources"]["uiuc_faculty"]
    assert faculty["status"] == "error"
    assert faculty["error"] == f"empty departments: {sorted(empty)}"
    assert summary["release"]["publishable"] == []
    # Twice, as before: once for the error status, once for the departments.
    assert summary["release"]["by_unit"]["uiuc"]["reasons"] == [
        f"source uiuc_faculty reported error: empty departments: {sorted(empty)}",
        f"uiuc_faculty reported empty departments: {sorted(empty)}",
    ]
    for before, after in rows:
        assert after["metadata"] == before["metadata"]


def test_an_inactive_stored_row_does_not_count_for_an_empty_uiuc_department(monkeypatch, tmp_path):
    retired = _seed_faculty("uiuc_faculty", "retired", days_ago=30)
    retired["department"] = "Department of Tides"
    retired["metadata"]["is_active"] = False
    _stub_with_processed_file(monkeypatch, tmp_path, [retired])
    _stub_successful_uiuc_deep_components(monkeypatch)
    monkeypatch.setattr(refresh_all, "fetch_faculty", lambda enrich: [{"id": "read"}])
    monkeypatch.setattr(refresh_all, "faculty_missing_departments",
                        lambda _records: ["Department of Tides"])

    summary = refresh_all.refresh_all(deep=True, schools={"uiuc"})

    assert summary["sources"]["uiuc_faculty"]["empty_department_baselines"] == {"Department of Tides": 0}
    assert summary["sources"]["uiuc_faculty"]["status"] == "error"
    assert summary["release"]["publishable"] == []


@pytest.mark.parametrize("outcome", ["empty_departments", "failed_component", "deferred"])
def test_the_uiuc_hold_is_reported_kept_whatever_uiuc_faculty_reported(monkeypatch, tmp_path, outcome):
    """uiuc_faculty is handed to the retirement pass only when it reports "ok",
    and then as a held source, so no run retires its rows. The summary named
    the hold only for "ok", and the verdict read every failed UIUC department
    as "deactivate_stale_faculty did not preserve the UIUC safety hold"."""
    stored = _seed_faculty("uiuc_faculty", "stored", days_ago=60)
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [stored])
    _stub_successful_uiuc_deep_components(monkeypatch)
    monkeypatch.setattr(refresh_all, "fetch_faculty", lambda enrich: [{"id": "read"}])
    budget = None
    if outcome == "empty_departments":
        monkeypatch.setattr(refresh_all, "faculty_missing_departments",
                            lambda _records: ["Department of Tides"])
    elif outcome == "failed_component":
        monkeypatch.setattr(refresh_all, "fetch_js_faculty", lambda: [])
    else:
        budget = 0

    summary = refresh_all.refresh_all(deep=True, schools={"uiuc"}, time_budget_minutes=budget)

    assert summary["sources"]["uiuc_faculty"]["status"] == (
        "deferred_deadline" if outcome == "deferred" else "error")
    assert summary["sources"]["deactivate_stale_faculty"]["deactivation_not_authorized"] == ["uiuc_faculty"]
    # UIUC is still withheld each time, for the reason that applies.
    assert summary["release"]["publishable"] == []
    assert not any("safety hold" in reason for reason in summary["release"]["reasons"])
    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert [row["metadata"]["is_active"] for row in saved] == [True]


def test_a_run_that_does_not_collect_uiuc_reports_no_hold(monkeypatch, tmp_path):
    _stub_with_processed_file(monkeypatch, tmp_path, [_seed_faculty("uw_faculty", "uw-existing", days_ago=1)])

    summary = refresh_all.refresh_all(deep=True, schools={"uw"})

    assert summary["sources"]["deactivate_stale_faculty"]["deactivation_not_authorized"] == []


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
    # The campus programs open to every school publish in national.json, so
    # this shard collects them too, one source per school.
    assert set(summary["sources"]) == set(
        expected_sources(None, national=True, deep=True)
    )
    assert {
        "uiuc_sro", "nsf_reu", "simplify_internships",
        "stanford_external_research", "ucb_external_research",
    } <= set(summary["sources"])
    assert summary["shard"] == {"schools": [], "national": True}


def test_a_config_edit_to_an_open_program_reaches_national_json_on_schedule(monkeypatch, tmp_path):
    """A campus program open to every school stamps no school, so its row lives
    in national.json, and only the national day may write that file. That run
    collected no campus programs, while the school's own day collected them
    and its split dropped them: no config edit to one reached production after
    the split was bounded to a run's own shards (#722, 2026-08-09).

    Driven through the scheduled path: the rotation names the day's shard and
    the shards it may replace, the run's verdict narrows them, and the split
    writes what is left of the assembled corpus."""
    from scripts.publishable_shards import publishable
    from scripts.refresh_rotation import scheduled_shard, target_shards
    from scripts.shard_corpus import assemble, load_shards, split
    from src.collectors import campus_graph, ucb_campus, ucb_sources
    from src.collectors.schools.stanford import SCHOOL as STANFORD
    from src.collectors.schools.uchicago import SCHOOL as UCHICAGO
    from src.collectors.schools.ucla import SCHOOL as UCLA
    from src.collectors.schools.upenn import SCHOOL as UPENN

    days = {day: scheduled_shard(day) for day in range(1, 8)}
    assert [day for day, shard in days.items() if "national" in target_shards(shard)] == [7]

    # The committed corpus: national.json holding each open row as its config
    # wrote it. The five M93 named, plus one of UC Berkeley's.
    configs = (STANFORD, UCHICAGO, UCLA, UPENN)
    stored = [row for config in configs for row in campus_graph.fetch_and_normalize(config)
              if row["school"] is None]
    stored += [row for row in ucb_campus.fetch_and_normalize() if row["school"] is None]
    edited = {"ssrp_amgen_scholars", "dsi_summer_lab", "ede_plus", "amgen_scholars_ucla",
              "singh_reu", "lbl_suli"}
    assert edited <= {row["metadata"]["collector_key"] for row in stored}
    processed = _stub_with_processed_file(monkeypatch, tmp_path, stored)
    shards = tmp_path / "shards"
    split(processed, shards)

    note = "Applications for the 2027 cohort open November 1, 2026."
    specs = [spec for config in configs for source in config["sources"] for spec in source["programs"]]
    specs += [spec for source in ucb_sources.UCB_SOURCES for spec in source["programs"]]
    for spec in specs:
        if spec["key"] in edited:
            monkeypatch.setitem(spec, "deadline_note", note)

    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence",
                        campus_graph.fetch_and_normalize_with_evidence)
    monkeypatch.setattr(refresh_all, "merge_campus_graph", campus_graph.merge_into_processed)
    monkeypatch.setattr(refresh_all, "fetch_ucb_campus_with_evidence",
                        ucb_campus.fetch_and_normalize_with_evidence)
    monkeypatch.setattr(refresh_all, "merge_ucb_campus", ucb_campus.merge_into_processed)
    for module in (campus_graph, ucb_campus):
        monkeypatch.setattr(module, "PROCESSED_FILE", processed)
        # Every page unreachable: the edit has to arrive from the config alone.
        monkeypatch.setattr(module, "_fetch", lambda url, **kwargs: None)
    # The refresh retires a row once its stated deadline has passed, and
    # lbl_suli states 2027-01-06: this run happens while every edited row is open.
    retire_past = refresh_all.deactivate_past
    monkeypatch.setattr(refresh_all, "deactivate_past",
                        lambda opps: retire_past(opps, today=date(2026, 11, 25)))

    assert days[7] == "national"
    assemble(processed, shards, force=True, allow_empty=True)
    summary = refresh_all.refresh_all(deep=True, national=True)
    targets = publishable(list(target_shards(days[7])), {"release": summary["release"]})
    assert targets == ["national"]
    split(processed, shards, only_shards=set(targets))

    published = {row["metadata"].get("collector_key"): row for row in load_shards(shards)}
    for key in edited:
        row = published[key]
        assert row["metadata"]["deadline_note"] == note, key
        assert row["eligibility"]["eligibility_text_raw"] == note, key
        # Still a national row, open to every school, and still listed.
        assert (row["school"], row["audience"]) == (None, "open"), key
        assert row["metadata"]["is_active"] is True, key
    assert {path.name for path in shards.glob("*.json")} == {"national.json"}


@pytest.mark.parametrize("school_day_first", [True, False], ids=["school_day_first", "sunday_first"])
@pytest.mark.parametrize("to_open", [True, False], ids=["into_open", "out_of_open"])
def test_a_program_moved_between_a_schools_shard_and_national_json_is_listed_once(
        monkeypatch, tmp_path, to_open, school_day_first):
    """A config edit moves a program between Stanford's own bucket and its
    open bucket and changes its URL. While both days listed every key of the
    config, the old row never retired, and the moved record published beside
    it on the new file's day. Out of the open bucket the program is SSRP,
    Stanford's only open program, so Sunday then lists no key at all.

    Driven through the scheduled path, as the test above."""
    from datetime import UTC, datetime

    from bs4 import BeautifulSoup

    from scripts.publishable_shards import publishable
    from scripts.refresh_rotation import target_shards
    from scripts.shard_corpus import assemble, load_shards, split
    from src.collectors import campus_graph
    from src.collectors.schools.stanford import SCHOOL as STANFORD

    by_name = {source["source_name"]: source for source in STANFORD["sources"]}
    campus, open_bucket = by_name["stanford_program"], by_name["stanford_program_open"]
    if to_open:
        moving = campus_graph.program("moving", "Moving Summer Fellowship",
                                      "https://example.stanford.edu/moving/", "Curated")
        moved = {**moving, "url": "https://example.stanford.edu/moving-reu/"}
        before = ([*campus["programs"], moving], open_bucket["programs"])
        after = (campus["programs"], [*open_bucket["programs"], moved])
    else:
        [moving] = open_bucket["programs"]
        moved = {**moving, "url": "https://example.stanford.edu/ssrp/"}
        before = (campus["programs"], open_bucket["programs"])
        after = ([*campus["programs"], moved], [])
    old_school, new_school = ("stanford", None) if to_open else (None, "stanford")

    def configure(programs):
        monkeypatch.setitem(campus, "programs", programs[0])
        monkeypatch.setitem(open_bucket, "programs", programs[1])

    configure(before)
    processed = _stub_with_processed_file(monkeypatch, tmp_path, campus_graph.fetch_and_normalize(STANFORD))
    shards = tmp_path / "shards"
    split(processed, shards)
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence",
                        campus_graph.fetch_and_normalize_with_evidence)
    monkeypatch.setattr(refresh_all, "merge_campus_graph", campus_graph.merge_into_processed)
    monkeypatch.setattr(campus_graph, "PROCESSED_FILE", processed)

    def page(url, **kwargs):
        # Every page loads and states no status. A source with no record and
        # no loaded page is an error that withholds national.json, and an
        # emptied open source has no record.
        soup = BeautifulSoup("<body><p>Program page</p></body>", "html.parser")
        soup._ofe_fetch_metadata = {"requested_url": url, "final_url": url,
                                    "checked_at": datetime.now(UTC).isoformat()}
        return soup

    monkeypatch.setattr(campus_graph, "_fetch", page)

    def listed():
        return [(row["school"], row["url"]) for row in load_shards(shards)
                if row["metadata"].get("collector_key") == moving["key"] and row["metadata"]["is_active"]]

    def run(shard):
        assemble(processed, shards, force=True, allow_empty=True)
        summary = (refresh_all.refresh_all(deep=True, national=True) if shard == "national"
                   else refresh_all.refresh_all(deep=True, schools={shard}))
        targets = publishable(list(target_shards(shard)), {"release": summary["release"]})
        assert targets == [shard]
        split(processed, shards, only_shards=set(targets))

    assert listed() == [(old_school, moving["url"])]
    configure(after)
    old_shard, new_shard = ("stanford", "national") if to_open else ("national", "stanford")
    if (old_shard == "stanford") == school_day_first:
        days = [(old_shard, []), (new_shard, [(new_school, moved["url"])])]
    else:
        # The moved record waits while the old row is listed.
        days = [(new_shard, [(old_school, moving["url"])]), (old_shard, []),
                (new_shard, [(new_school, moved["url"])])]
    for shard, expected in days:
        run(shard)
        assert listed() == expected, shard


@pytest.mark.parametrize("to_open", [True, False], ids=["into_open", "out_of_open"])
def test_a_closed_program_moved_with_its_url_is_listed_again_when_it_reopens(monkeypatch, tmp_path, to_open):
    """The program's page says closed, the config moves it between Stanford's
    own bucket and its open bucket with its URL, and the page later reopens.
    The merges' listing rule skipped the closed old row, which therefore kept
    its claim on the URL, and the moved record was dropped as its
    near-duplicate on every run: the program was never listed again.

    Driven through the scheduled path, as the test above."""
    from datetime import UTC, datetime

    from bs4 import BeautifulSoup

    from scripts.publishable_shards import publishable
    from scripts.refresh_rotation import target_shards
    from scripts.shard_corpus import assemble, load_shards, split
    from src.collectors import campus_graph
    from src.collectors.schools.stanford import SCHOOL as STANFORD

    by_name = {source["source_name"]: source for source in STANFORD["sources"]}
    campus, open_bucket = by_name["stanford_program"], by_name["stanford_program_open"]
    if to_open:
        moving = campus_graph.program("moving", "Moving Summer Fellowship",
                                      "https://example.stanford.edu/moving/", "Curated")
        before = ([*campus["programs"], moving], open_bucket["programs"])
        after = (campus["programs"], [*open_bucket["programs"], moving])
        old_shard, new_shard, new_school = "stanford", "national", None
    else:
        [moving] = open_bucket["programs"]
        before = (campus["programs"], open_bucket["programs"])
        after = ([*campus["programs"], moving], [])
        old_shard, new_shard, new_school = "national", "stanford", "stanford"
    for source in (campus, open_bucket):
        if moving["url"] not in source["seeds"]:
            monkeypatch.setitem(source, "seeds", [*source["seeds"], moving["url"]])

    def configure(programs):
        monkeypatch.setitem(campus, "programs", programs[0])
        monkeypatch.setitem(open_bucket, "programs", programs[1])

    configure(before)
    processed = _stub_with_processed_file(monkeypatch, tmp_path, campus_graph.fetch_and_normalize(STANFORD))
    shards = tmp_path / "shards"
    split(processed, shards)
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence",
                        campus_graph.fetch_and_normalize_with_evidence)
    monkeypatch.setattr(refresh_all, "merge_campus_graph", campus_graph.merge_into_processed)
    monkeypatch.setattr(campus_graph, "PROCESSED_FILE", processed)
    page = {"word": "Applications are now closed."}

    def fetch(url, **kwargs):
        text = page["word"] if url == moving["url"] else "Program page"
        soup = BeautifulSoup(f"<body><p>{text}</p></body>", "html.parser")
        soup._ofe_fetch_metadata = {"requested_url": url, "final_url": url,
                                    "checked_at": datetime.now(UTC).isoformat()}
        return soup

    monkeypatch.setattr(campus_graph, "_fetch", fetch)

    def run(shard):
        assemble(processed, shards, force=True, allow_empty=True)
        summary = (refresh_all.refresh_all(deep=True, national=True) if shard == "national"
                   else refresh_all.refresh_all(deep=True, schools={shard}))
        targets = publishable(list(target_shards(shard)), {"release": summary["release"]})
        assert targets == [shard]
        split(processed, shards, only_shards=set(targets))

    def listed():
        return [(row["school"], row["metadata"]["status"]) for row in load_shards(shards)
                if row["metadata"].get("collector_key") == moving["key"] and row["metadata"]["is_active"]]

    run(old_shard)
    assert listed() == []
    configure(after)
    run(old_shard)
    run(new_shard)
    page["word"] = "Applications are now open!"
    run(old_shard)
    run(new_shard)
    assert listed() == [(new_school, "open")]


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
    successful producing refresh for the tracking artifact.

    Two gates of different widths, asserted together because the difference
    is the point. The opportunity corpus PUBLISHES on this verdict: refusing
    to, because one department emitted nothing, is what froze UC Berkeley for
    44 days. Professor tracking stays fail-closed on the same evidence - its
    baselines are per-professor claims about what a directory says today, so
    a mandatory producer that emitted nothing is not a successful producing
    refresh for it.
    """

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

    # The stricter gate: tracking does not treat this as a successful run.
    assert captured["refresh_ok"] is False

    # The wider one: the corpus still publishes, and says it is degraded.
    assert summary["release"]["ready"] is True
    assert summary["release"]["status"] == "degraded"
    assert summary["release"]["publishable"] == ["uw"]
    assert summary["release"]["reasons"] == []
    assert any(
        "emitted zero records" in warning
        for warning in summary["release"]["warnings"]
    )
    assert {
        item["source"]
        for item in summary["release"]["degradations"]
        if item["kind"] == "suspicious_zero"
    } == {"uw_faculty", "campus_graph:uw"}

    # And the zero is named as a zero, not as an "ok" run.
    assert summary["sources"]["uw_faculty"]["status"] == "suspicious_zero"
    assert summary["sources"]["uw_faculty"]["suspicious_zero_baseline"] == 1


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


# --- The internship list on a school shard's day -------------------------------
#
# Listings close daily and national.json was refreshed weekly, so by Saturday a
# tenth of the internships shown as open were closed (M193). Every scheduled
# day's run now reads that one list beside its schools.

_INTERNSHIPS = frozenset({"simplify_internships"})


def _internship(ident, active=True, days_ago=7):
    seen = (date.today() - timedelta(days=days_ago)).isoformat() + "T00:00:00"
    metadata = {"first_seen_at": "2026-09-01T00:00:00", "last_seen_at": seen, "is_active": active}
    if not active:
        metadata.update(deactivated_at="2026-10-01", deactivation_reason="no_longer_listed")
    return {"id": f"simplify-intern-{ident}", "source": "simplify_internships",
            "source_type": "internship", "title": f"Intern {ident}", "deadline": None,
            "is_rolling": True, "metadata": metadata}


def _national_row(source, ident):
    return {"id": ident, "source": source, "source_type": "summer_program",
            "title": f"Program {ident}", "deadline": None,
            "metadata": {"first_seen_at": "2026-01-01T00:00:00",
                         "last_seen_at": "2026-11-01T00:00:00", "is_active": True}}


def _uw_day_with_the_internship_list(monkeypatch, tmp_path, stored, read, uw_fails=False):
    """A deep uw run that also reads the internship list: ``read`` is what the
    list answers (rows, or an exception to raise), merged into a corpus of
    ``stored`` rows and one uw professor. uw's own sources read cleanly unless
    ``uw_fails``. Returns the summary, the corpus rows by id and what the
    professor tracking pass was told."""
    from src.collectors import simplify_internships

    path = _stub_with_processed_file(
        monkeypatch, tmp_path, [_seed_faculty("uw_faculty", "uw-prof", days_ago=1), *stored])
    # The global passes reach their fixed point first, as in the shard tests below.
    refresh_all.refresh_all(deep=True, schools={"umich"})
    before = {o["id"]: json.dumps(o, sort_keys=True) for o in json.loads(path.read_text())}

    def fetch_uw(*a, **k):
        if uw_fails:
            raise RuntimeError("uw directory answered 500")
        return [{"id": "uw-prof"}]

    def fetch_internships():
        if isinstance(read, Exception):
            raise read
        return [json.loads(json.dumps(row)) for row in read]

    monkeypatch.setattr(refresh_all, "fetch_uw_faculty", fetch_uw)
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", lambda *a, **k: (
        [{"id": "uw-program"}],
        {"deep": True, "crawl_sources_expected": 1, "crawl_sources_loaded": 1, "live_pages_attempted": 1,
         "live_pages_loaded": 1, "seed_pages_expected": 1, "seed_pages_loaded": 1, "seed_pages_failed": 0,
         "crawl_errors": []}))
    monkeypatch.setattr(refresh_all, "fetch_simplify", fetch_internships)
    monkeypatch.setattr(refresh_all, "merge_simplify",
                        lambda opps: simplify_internships.merge_into_processed(opps, str(path)))
    tracking = []
    monkeypatch.setattr(refresh_all, "_update_professor_tracking",
                        lambda *a, **k: tracking.append(k["refresh_ok"]))
    summary = refresh_all.refresh_all(deep=True, schools={"uw"}, national_sources=_INTERNSHIPS)
    after = {o["id"]: o for o in json.loads(path.read_text())}
    return summary, before, after, tracking


def test_a_school_shard_asked_for_the_internship_list_reads_it_and_no_other_national_source(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=True, schools={"uw"}, national_sources=_INTERNSHIPS)
    assert set(summary["sources"]) == {"uw_faculty", "campus_graph:uw", "simplify_internships"}
    assert summary["request"] == {"schools": ["uw"], "national": False, "deep": True,
                                  "national_sources": ["simplify_internships"]}
    assert summary["shard"] == {"schools": ["uw"], "national": False}
    # Not asked, a school shard reads no national source and says nothing of one.
    plain = refresh_all.refresh_all(deep=True, schools={"uw"})
    assert set(plain["sources"]) == {"uw_faculty", "campus_graph:uw"}
    assert plain["request"] == {"schools": ["uw"], "national": False, "deep": True}


def test_only_the_internship_list_can_ride_a_school_shard(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not a national source a school shard can refresh"):
        refresh_all.refresh_all(deep=True, schools={"uw"}, national_sources={"nsf_reu"})
    # The national and the full run read it already.
    for selection in ({"national": True}, {}):
        with pytest.raises(ValueError, match="ride a school shard"):
            refresh_all.refresh_all(deep=True, national_sources=_INTERNSHIPS, **selection)


def test_the_cli_passes_the_national_sources_a_school_shard_also_reads(monkeypatch):
    asked = {}
    summary = {"timestamp": "2026-11-20T00:00:00", "sources": {}, "total_new": 0, "total_updated": 0,
               "total_in_file": 1, "release": {"ready": True, "reasons": []}}
    monkeypatch.setattr(refresh_all, "refresh_all", lambda **kwargs: asked.update(kwargs) or summary)
    monkeypatch.setattr(refresh_all, "write_status", lambda _summary: None)
    monkeypatch.setattr(refresh_all, "print_summary", lambda _summary: None)

    assert refresh_all.main(["--schools", "uw", "--national-sources", "simplify_internships"]) == 0
    assert (asked["schools"], asked["national_sources"]) == ({"uw"}, _INTERNSHIPS)
    assert refresh_all.main(["--schools", "uw"]) == 0
    assert asked["national_sources"] == frozenset()


def test_a_school_day_refreshes_the_internships_and_leaves_every_other_national_row_byte_identical(
        monkeypatch, tmp_path):
    others = [_national_row("uiuc_sro", "sro-one"), _national_row("nsf_reu", "reu-one"),
              _national_row("manual", "manual-one"), _national_row("stanford_external_research", "open-one")]
    stored = [*others, _internship("still-open"), _internship("closed-since"),
              _internship("open-again", active=False)]
    read = [_internship("still-open", days_ago=0), _internship("open-again", days_ago=0),
            _internship("new", days_ago=0)]
    summary, before, after, _ = _uw_day_with_the_internship_list(monkeypatch, tmp_path, stored, read)

    info = summary["sources"]["simplify_internships"]
    assert (info["status"], info["fetched"], info["new"], info["updated"]) == ("ok", 3, 1, 2)
    assert info["deactivated_stale"] == 1
    closed = after["simplify-intern-closed-since"]["metadata"]
    assert (closed["is_active"], closed["deactivation_reason"]) == (False, "no_longer_listed")
    for ident in ("still-open", "open-again", "new"):
        assert after[f"simplify-intern-{ident}"]["metadata"]["is_active"] is True
    # The sources that did not run are absent, not "ok, fetched 0", and their rows untouched.
    assert set(summary["sources"]) & {"uiuc_sro", "nsf_reu", "stanford_external_research",
                                      "ucb_external_research"} == set()
    for row in others:
        assert json.dumps(after[row["id"]], sort_keys=True) == before[row["id"]]
    assert set(before) <= set(after)
    assert summary["release"]["publishable"] == ["national", "uw"]


@pytest.mark.parametrize("read", [RuntimeError("list answered 503"), []], ids=["failed", "empty"])
def test_an_unread_internship_list_withholds_no_school_and_retires_no_listing(monkeypatch, tmp_path, read):
    from src.collectors import source_health

    stored = [_internship("one"), _internship("two")]
    summary, before, after, tracking = _uw_day_with_the_internship_list(monkeypatch, tmp_path, stored, read)

    release = summary["release"]
    assert "uw" in release["publishable"] and release["by_unit"]["uw"] == {"ready": True, "reasons": []}
    for row in stored:
        assert json.dumps(after[row["id"]], sort_keys=True) == before[row["id"]]
    info = summary["sources"]["simplify_internships"]
    assert "deactivated_stale" not in info
    health = source_health.load_ledger(tmp_path / "source_health.json")["sources"]["simplify_internships"]
    assert (health["school"], health["consecutive_failures"]) == ("national", 1)
    assert "last_success_at" not in health
    if isinstance(read, Exception):
        assert (info["status"], health["status"]) == ("error", source_health.FAILED)
        assert release["publishable"] == ["uw"]
        assert release["by_unit"]["national"]["reasons"] == [
            "source simplify_internships reported error: list answered 503"]
    else:
        # An empty read keeps the rows and is reported, as on the national day.
        assert (info["status"], info["suspicious_zero_baseline"]) == (source_health.SUSPICIOUS_ZERO, 2)
        assert health["status"] == source_health.SUSPICIOUS_ZERO
        assert release["publishable"] == ["national", "uw"]
        assert {"kind": "suspicious_zero", "source": "simplify_internships",
                "detail": "0 records, previously 2"} in release["degradations"]
    # uw's professors were read in full, and tracking is told so.
    assert tracking == [True]


def test_a_collapsed_internship_read_retires_no_listing_and_withholds_nothing(monkeypatch, tmp_path):
    """Only an empty read was kept from retiring: a list cut to a few rows
    closed every internship it no longer held."""
    from src.collectors import source_health

    stored = [_internship(name) for name in ("one", "two", "three", "four", "five")]
    summary, before, after, tracking = _uw_day_with_the_internship_list(
        monkeypatch, tmp_path, stored, [_internship("one", days_ago=0), _internship("two", days_ago=0)])

    info = summary["sources"]["simplify_internships"]
    assert (info["status"], info["fetched"], info["incomplete_reasons"]) == ("partial_failure", 2, ["list_errors"])
    assert info["list_errors"] == [
        "the list holds 2 internships and the corpus 5 open ones; nothing was retired on this read"]
    # The data PR and the operator alert say so from this count.
    assert info["collapsed_list_baseline"] == 5
    assert "deactivated_stale" not in info
    assert all(row["metadata"]["is_active"] is True for row in after.values())
    for name in ("three", "four", "five"):
        assert json.dumps(after[f"simplify-intern-{name}"], sort_keys=True) == before[f"simplify-intern-{name}"]
    release = summary["release"]
    assert release["publishable"] == ["national", "uw"]
    assert {"kind": "partial_failure", "source": "simplify_internships",
            "detail": "list_errors"} in release["degradations"]
    health = source_health.load_ledger(tmp_path / "source_health.json")["sources"]["simplify_internships"]
    assert health["status"] == source_health.FAILED and "last_success_at" not in health
    assert tracking == [True]

    # Half of the open listings is still a list: the other half is retired.
    (tmp_path / "half").mkdir()
    summary, _, after, _ = _uw_day_with_the_internship_list(
        monkeypatch, tmp_path / "half", stored[:4],
        [_internship("one", days_ago=0), _internship("two", days_ago=0)])
    info = summary["sources"]["simplify_internships"]
    assert (info["status"], info["deactivated_stale"]) == ("ok", 2) and "list_errors" not in info
    assert "collapsed_list_baseline" not in info
    assert [after[f"simplify-intern-{name}"]["metadata"]["is_active"]
            for name in ("one", "two", "three", "four")] == [True, True, False, False]


def test_a_collapsed_internship_read_on_the_national_day_retires_no_listing_either(monkeypatch, tmp_path):
    from src.collectors import simplify_internships

    stored = [_internship(name) for name in ("one", "two", "three")]
    path = _stub_with_processed_file(monkeypatch, tmp_path, stored)
    monkeypatch.setattr(refresh_all, "fetch_simplify", lambda: [_internship("one", days_ago=0)])
    monkeypatch.setattr(refresh_all, "merge_simplify",
                        lambda opps: simplify_internships.merge_into_processed(opps, str(path)))
    summary = refresh_all.refresh_all(deep=True, national=True)

    info = summary["sources"]["simplify_internships"]
    assert info["status"] == "partial_failure" and "deactivated_stale" not in info
    assert (info["fetched"], info["collapsed_list_baseline"]) == (1, 3)
    assert all(row["metadata"]["is_active"] is True for row in json.loads(path.read_text()))
    assert "national" in summary["release"]["publishable"]


def test_a_withheld_school_does_not_withhold_the_internships(monkeypatch, tmp_path):
    stored = [_internship("still-open"), _internship("closed-since")]
    summary, _, after, tracking = _uw_day_with_the_internship_list(
        monkeypatch, tmp_path, stored, [_internship("still-open", days_ago=0)], uw_fails=True)

    release = summary["release"]
    assert release["publishable"] == ["national"]
    assert release["by_unit"]["uw"]["reasons"] == ["source uw_faculty reported error: uw directory answered 500"]
    assert summary["sources"]["simplify_internships"]["deactivated_stale"] == 1
    assert after["simplify-intern-closed-since"]["metadata"]["is_active"] is False
    assert tracking == [False]


def _unlisted_uiuc_row(ident: str) -> dict:
    """A UIUC row no roster has listed for 60 days, with a profile page of its own."""
    return {**_seed_faculty("uiuc_faculty", ident, days_ago=60),
            "source_url": f"https://{ident}.testu.edu/directory/profile/{ident}"}


def test_a_uiuc_refresh_retires_an_unlisted_row_only_when_its_profile_page_is_gone(monkeypatch, tmp_path):
    gone, live = _unlisted_uiuc_row("gone"), _unlisted_uiuc_row("live")
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [gone, live])
    monkeypatch.setattr(refresh_all, "fetch_faculty", lambda *a, **k: [{"id": f"f{i}"} for i in range(2)])
    monkeypatch.setattr("src.collectors.uiuc_faculty.profile_page_answer",
                        lambda url: (404 if url == gone["source_url"] else 200, url))

    summary = refresh_all.refresh_all(deep=False, schools={"uiuc"})

    assert summary["sources"]["uiuc_faculty"]["profile_gone"] == {
        "candidates": 2, "probed": 2, "deactivated": 1, "deactivated_ids": ["gone"], "kept": {"http_200": 1}}
    # Absence alone still retires no UIUC row.
    assert summary["sources"]["deactivate_stale_faculty"]["deactivation_not_authorized"] == ["uiuc_faculty"]
    saved = {o["id"]: o["metadata"] for o in json.loads(processed.read_text(encoding="utf-8"))}
    assert {k: saved["gone"].get(k) for k in ("is_active", "deactivation_reason", "deactivated_at")} == {
        "is_active": False, "deactivation_reason": "profile_page_gone", "deactivated_at": date.today().isoformat()}
    assert saved["live"]["is_active"] is True
    assert "deactivation_reason" not in saved["live"]


def test_a_refresh_that_does_not_collect_uiuc_faculty_asks_for_no_profile_page(monkeypatch, tmp_path):
    # The stubbed requester fails the test when asked.
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [_unlisted_uiuc_row("gone")])
    summary = refresh_all.refresh_all(deep=True, schools={"umich"})
    assert "uiuc_faculty" not in summary["sources"]
    assert json.loads(processed.read_text(encoding="utf-8"))[0]["metadata"]["is_active"] is True


def test_rows_of_a_uiuc_department_that_read_empty_are_not_asked_about_and_uiuc_still_publishes(monkeypatch, tmp_path):
    """A department whose list page reads empty degrades UIUC while the corpus
    holds active rows for it. Retiring them for gone pages would leave none,
    and every later run would read it as a department that never had rows and
    withhold UIUC. The stubbed requester fails the test when asked."""
    read = [{**_seed_faculty("uiuc_faculty", f"read-{index}", days_ago=0), "department": "Department of Wells"}
            for index in range(5)]
    tides = [{**_unlisted_uiuc_row(f"tides-{index}"), "department": "Department of Tides"} for index in range(3)]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, read + tides)
    _stub_successful_uiuc_deep_components(monkeypatch)
    monkeypatch.setattr(refresh_all, "fetch_faculty", lambda enrich: read)
    monkeypatch.setattr(refresh_all, "faculty_missing_departments", lambda _records: ["Department of Tides"])
    for name in ("fetch_rss", "fetch_urap", "fetch_ursa", "fetch_drp", "fetch_siebel", "fetch_other"):
        monkeypatch.setattr(refresh_all, name, lambda *a, **k: [{"id": "listed"}])
    monkeypatch.setattr(refresh_all, "_update_professor_tracking", lambda *a, **k: None)

    runs = [refresh_all.refresh_all(deep=True, schools={"uiuc"}) for _ in range(2)]

    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert [row["metadata"]["is_active"] for row in saved] == [True] * 8
    for run in runs:
        faculty, release = run["sources"]["uiuc_faculty"], run["release"]
        assert faculty["profile_gone"] == {"candidates": 3, "probed": 0, "deactivated": 0, "deactivated_ids": [],
                                           "kept": {"department_unread": 3}}
        assert faculty["status"] == "ok" and "error" not in faculty
        assert faculty["empty_department_baselines"] == {"Department of Tides": 3}
        assert release["publishable"] == ["uiuc"] and release["status"] == "degraded"


def test_run_summary_reports_tombstoned_contacts_the_enricher_skipped(monkeypatch, tmp_path):
    """A tombstoned contact is never re-scraped; the run summary says how many
    were held back, so a refresh shows the guard working rather than hiding it."""
    _stub_with_processed_file(monkeypatch, tmp_path, _shard_seeds())
    monkeypatch.setattr(
        refresh_all, "enrich_pi",
        lambda opps, save=True, max_scrapes=None, deadline=None: {
            "scraped": 0, "enriched": 0, "already_has_email": 0, "skipped_budget": 0,
            "skipped_tombstoned": 3})
    monkeypatch.setattr(refresh_all, "fetch_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(2)])

    summary = refresh_all.refresh_all(deep=True)
    assert summary["sources"]["pi_enricher"]["skipped_tombstoned"] == 3


def test_run_summary_reports_inactive_rows_the_enricher_skipped(monkeypatch, tmp_path):
    _stub_with_processed_file(monkeypatch, tmp_path, _shard_seeds())
    monkeypatch.setattr(
        refresh_all, "enrich_pi",
        lambda opps, save=True, max_scrapes=None, deadline=None: {
            "scraped": 0, "enriched": 0, "already_has_email": 0, "skipped_budget": 0,
            "skipped_inactive": 4})
    summary = refresh_all.refresh_all(deep=True)
    assert summary["sources"]["pi_enricher"]["skipped_inactive"] == 4


def test_pi_enrichment_pool_scoped_to_shard_and_never_truncates(monkeypatch, tmp_path):
    """Sharded runs must call enrich_pi with save=False: enrich_pi(save=True)
    writes its INPUT list to PROCESSED_FILE, so a shard-scoped subset would
    truncate the corpus to that subset."""
    seeds = _shard_seeds()
    _stub_with_processed_file(monkeypatch, tmp_path, seeds)
    captured = {}

    def fake_enrich(opps, save=True, max_scrapes=None, deadline=None):
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


def test_pi_enrichment_stops_at_the_run_deadline(monkeypatch, tmp_path):
    """The PI pass starts after the sources and must stop where they stop.

    It used to fetch up to 1,000 pages (~45 min) whatever the clock said, so
    on the days the sources spent the whole budget the job hit its hard
    timeout inside this pass and published nothing (2026-10-01, and five of
    the first seven September runs).
    """
    _stub_with_processed_file(monkeypatch, tmp_path, _shard_seeds())
    captured = {}

    def fake_enrich(opps, save=True, max_scrapes=None, deadline=None):
        captured["deadline"] = deadline
        return {"scraped": 0, "enriched": 0, "already_has_email": 0,
                "skipped_budget": 0, "skipped_deadline": 4}

    monkeypatch.setattr(refresh_all, "enrich_pi", fake_enrich)
    monkeypatch.setattr(refresh_all, "fetch_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(2)])

    before = refresh_all.time.monotonic()
    summary = refresh_all.refresh_all(deep=True, schools={"uiuc"}, time_budget_minutes=60)
    assert before + 59 * 60 < captured["deadline"] <= refresh_all.time.monotonic() + 60 * 60
    assert summary["sources"]["pi_enricher"]["skipped_deadline"] == 4

    refresh_all.refresh_all(deep=True, schools={"uiuc"})
    assert captured["deadline"] is None


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


def test_post_merge_pass_withdraws_superseded_publication_trust(monkeypatch, tmp_path):
    """Every refresh withdraws the trust a retired works gate granted, so
    production never waits on someone running scripts/remediate_publications.py.
    A record the current gate chose and a record already withdrawn come
    through untouched, and the next refresh changes nothing."""
    from src.publication_trust import (
        CURRENT_WORKS_GATE,
        PENDING_REMEDIATION,
        VERIFIED_AUTHOR_ID,
        verified_recent_works,
    )

    def faculty(ident, papers, status, **metadata):
        record = _seed_faculty("uiuc_faculty", ident, days_ago=1)
        record["pi_name"] = f"Professor {ident}"
        record["metadata"].update(
            recent_works=[{"title": f"{ident} paper {n}", "year": 2026} for n in range(papers)],
            publication_attribution_status=status,
            **metadata,
        )
        return record

    already_withdrawn = {
        "from_gate": 1,
        "to_gate": CURRENT_WORKS_GATE,
        "withdrawn_at": "2026-09-30T17:35:43.549131+00:00",
        "prior_status": VERIFIED_AUTHOR_ID,
        "prior_author_id": None,
    }
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [
        # No works_gate: written before the field existed, i.e. gate 1.
        faculty("gate-1", 3, VERIFIED_AUTHOR_ID, publication_author_id="A-GATE-1"),
        faculty("gate-2", 2, VERIFIED_AUTHOR_ID, works_gate=2),
        faculty("pending", 1, PENDING_REMEDIATION, publication_remediation=already_withdrawn),
        faculty("current", 3, VERIFIED_AUTHOR_ID, works_gate=CURRENT_WORKS_GATE,
                publication_author_id="A-CURRENT"),
    ])

    summary = refresh_all.refresh_all(deep=False)

    assert summary["sources"]["publication_remediation"] == {
        "professors_withdrawn": 2,
        "relationships_withdrawn": 5,
        "pending_professors": 3,
        "pending_relationships": 6,
        "current_gate_professors": 1,
        "works_gate": CURRENT_WORKS_GATE,
        "status": "ok",
    }
    saved = {o["id"]: o for o in json.loads(processed.read_text(encoding="utf-8"))}
    for ident, from_gate, papers in (("gate-1", 1, 3), ("gate-2", 2, 2)):
        md = saved[ident]["metadata"]
        assert md["publication_attribution_status"] == PENDING_REMEDIATION
        assert verified_recent_works(saved[ident]) == []
        # The papers stay as the re-harvest's candidate list; only the trust goes.
        assert len(md["recent_works"]) == papers
        assert md["publication_remediation"]["from_gate"] == from_gate
        assert md["publication_remediation"]["to_gate"] == CURRENT_WORKS_GATE
    assert "publication_author_id" not in saved["gate-1"]["metadata"]
    assert saved["gate-1"]["metadata"]["publication_remediation"]["prior_author_id"] == "A-GATE-1"
    assert saved["pending"]["metadata"]["publication_attribution_status"] == PENDING_REMEDIATION
    assert saved["pending"]["metadata"]["publication_remediation"] == already_withdrawn
    current = saved["current"]["metadata"]
    assert current["publication_attribution_status"] == VERIFIED_AUTHOR_ID
    assert current["publication_author_id"] == "A-CURRENT"
    assert "publication_remediation" not in current
    assert len(verified_recent_works(saved["current"])) == 3

    second = refresh_all.refresh_all(deep=False)

    assert second["sources"]["publication_remediation"]["professors_withdrawn"] == 0
    assert second["sources"]["publication_remediation"]["pending_professors"] == 3
    again = {o["id"]: o for o in json.loads(processed.read_text(encoding="utf-8"))}
    keys = ("publication_attribution_status", "publication_author_id", "works_gate",
            "recent_works", "publication_remediation")
    for ident, record in saved.items():
        assert {k: again[ident]["metadata"].get(k) for k in keys} == \
            {k: record["metadata"].get(k) for k in keys}, ident


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


def test_cli_publishes_the_ready_units_when_one_school_is_blocked(
    monkeypatch, caplog
):
    """Exit 2 withholds everything; a per-school block must not do that.

    On 2026-08-08 one broken UCSB sitemap discarded 2h42m of collection for
    fifteen schools with nothing wrong with them.
    """
    summary = {
        "timestamp": "2026-08-08T06:12:00",
        "sources": {},
        "total_new": 0,
        "total_updated": 0,
        "total_in_file": 1,
        "release": {
            "ready": False,
            "reasons": ["source ucsb_urca_projects reported error: x"],
            "warnings": [],
            "publishable": ["caltech", "umich"],
            "by_unit": {
                "caltech": {"ready": True, "reasons": []},
                "ucsb": {"ready": False, "reasons": ["…"]},
                "umich": {"ready": True, "reasons": []},
            },
        },
    }
    monkeypatch.setattr(refresh_all, "refresh_all", lambda **_kwargs: summary)
    monkeypatch.setattr(refresh_all, "write_status", lambda _summary: None)
    monkeypatch.setattr(refresh_all, "print_summary", lambda _summary: None)

    with caplog.at_level(logging.ERROR):
        assert refresh_all.main(["--schools", "ucsb,umich,caltech"]) == 0

    assert any(
        "PARTIAL RELEASE" in r.message and "ucsb" in r.message
        for r in caplog.records
    )


def test_cli_still_returns_two_when_nothing_is_publishable(monkeypatch):
    summary = {
        "timestamp": "t",
        "sources": {},
        "total_new": 0,
        "total_updated": 0,
        "total_in_file": 1,
        "release": {
            "ready": False,
            "reasons": ["summary shard does not match request"],
            "publishable": [],
            "by_unit": {"uw": {"ready": False, "reasons": ["…"]}},
        },
    }
    monkeypatch.setattr(refresh_all, "refresh_all", lambda **_kwargs: summary)
    monkeypatch.setattr(refresh_all, "write_status", lambda _summary: None)
    monkeypatch.setattr(refresh_all, "print_summary", lambda _summary: None)

    assert refresh_all.main(["--schools", "uw"]) == 2


def test_cli_returns_two_for_a_verdict_that_predates_per_unit_publication(
    monkeypatch,
):
    """An older artifact has no publishable list; withhold, do not guess."""
    summary = {
        "timestamp": "t",
        "sources": {},
        "total_new": 0,
        "total_updated": 0,
        "total_in_file": 1,
        "release": {"ready": False, "reasons": ["required source missing: x"]},
    }
    monkeypatch.setattr(refresh_all, "refresh_all", lambda **_kwargs: summary)
    monkeypatch.setattr(refresh_all, "write_status", lambda _summary: None)
    monkeypatch.setattr(refresh_all, "print_summary", lambda _summary: None)

    assert refresh_all.main(["--schools", "uw"]) == 2


@pytest.mark.parametrize("failed_kind", ["failed", "unsupported"])
def test_b55_condition_failure_keeps_last_success_and_tracking_closed(monkeypatch, tmp_path, failed_kind):
    from datetime import UTC, datetime

    from src.collectors import source_health
    _stub_with_processed_file(monkeypatch, tmp_path, [_seed_faculty("uw_faculty", "uw-existing", days_ago=1)])
    proof = {"deep": True, "crawl_sources_expected": 1, "crawl_sources_loaded": 1,
             "live_pages_attempted": 1, "live_pages_loaded": 1, "seed_pages_expected": 1,
             "seed_pages_loaded": 1, "seed_pages_failed": 0, "crawl_errors": [],
             "condition_capture_counts": {"captured": 0, "empty": 0, "unsupported": 0, "failed": 0},
             "condition_capture_complete": False}
    proof["condition_capture_counts"][failed_kind] = 1
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", lambda *a, **k: ([{"id": "safe-listing"}], proof))
    ledger = source_health.empty_ledger()
    source_health.record_attempt(ledger, source="campus_graph:uw", school="uw", outcome=source_health.SUCCESS_NONZERO,
                                emitted=1, baseline=1, now=datetime(2026, 1, 1, tzinfo=UTC))
    source_health.save_ledger(ledger, tmp_path / "source_health.json")
    tracking = []
    monkeypatch.setattr(refresh_all, "_update_professor_tracking", lambda *a, **k: tracking.append(k["refresh_ok"]))
    summary = refresh_all.refresh_all(deep=True, schools={"uw"})
    info = summary["sources"]["campus_graph:uw"]
    assert info["status"] == "partial_failure"
    actual = source_health.load_ledger(tmp_path / "source_health.json")["sources"]["campus_graph:uw"]
    assert actual["status"] == source_health.FAILED
    assert actual["last_success_at"] == "2026-01-01T00:00:00+00:00"
    assert summary["release"]["status"] == "degraded"
    assert "uw" in summary["release"]["publishable"]
    assert tracking == [False]


@pytest.mark.parametrize("kind", ["captured", "empty", "not_attempted"])
def test_b55_capture_empty_or_unattempted_is_not_a_failure(monkeypatch, tmp_path, kind):
    _stub_all_collectors(monkeypatch, tmp_path)
    counts = {"captured": 0, "empty": 0, "unsupported": 0, "failed": 0}
    if kind != "not_attempted": counts[kind] = 1
    proof = {"condition_capture_counts": counts, "condition_capture_complete": kind != "not_attempted"}
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", lambda *a, **k: ([{"id": "safe-listing"}], proof))
    summary = refresh_all.refresh_all(deep=False, schools={"uw"})
    assert summary["sources"]["campus_graph:uw"]["status"] == "ok"


def test_b55_total_fetch_error_records_attempt_without_moving_success(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from src.collectors import source_health
    _stub_with_processed_file(monkeypatch, tmp_path, [_seed_faculty("uw_faculty", "uw-existing", days_ago=1)])
    def fail(*a, **k): raise RuntimeError("synthetic fetch failure")
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", fail)
    ledger = source_health.empty_ledger()
    source_health.record_attempt(ledger, source="campus_graph:uw", school="uw", outcome=source_health.SUCCESS_NONZERO,
                                emitted=1, baseline=1, now=datetime(2026, 1, 1, tzinfo=UTC))
    source_health.save_ledger(ledger, tmp_path / "source_health.json")
    summary = refresh_all.refresh_all(deep=True, schools={"uw"})
    actual = source_health.load_ledger(tmp_path / "source_health.json")["sources"]["campus_graph:uw"]
    assert summary["sources"]["campus_graph:uw"]["status"] == "error"
    assert actual["status"] == source_health.FAILED
    assert actual["consecutive_failures"] == 1
    assert actual["last_success_at"] == "2026-01-01T00:00:00+00:00"
    assert actual["last_attempt_at"] != actual["last_success_at"]


def test_b55_campus_failure_receipts_reach_merge_without_report_content(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    updates = [{"school": "uw", "collector_source": "sample", "requested_url": "https://example.edu/opportunities",
                "capture": {"status": "unsupported", "reason": "synthetic"}}]
    proof = {"condition_capture_counts": {"captured": 0, "empty": 0, "unsupported": 1, "failed": 0},
             "condition_capture_complete": False, "condition_capture_updates": updates}
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", lambda *a, **k: ([], proof))
    calls = []
    monkeypatch.setattr(refresh_all, "merge_campus_graph", lambda records, **kwargs: (calls.append(kwargs) or (0, 0)))
    summary = refresh_all.refresh_all(deep=False, schools={"uw"})
    assert len(calls) == 1
    assert calls[0]["condition_capture_updates"] == updates
    assert "condition_capture_updates" not in summary["sources"]["campus_graph:uw"]
    assert proof["condition_capture_updates"] == updates


def test_listed_program_keys_reach_the_campus_merge_without_report_content(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    listed, other = ["uw_first_program", "uw_second_program"], ["uw_open_program"]
    proof = {"condition_capture_counts": {"captured": 0, "empty": 0, "unsupported": 0, "failed": 0},
             "condition_capture_complete": False, "listed_program_keys": listed, "other_file_program_keys": other}
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", lambda *a, **k: ([], proof))
    calls = []
    monkeypatch.setattr(refresh_all, "merge_campus_graph", lambda records, **kwargs: (calls.append(kwargs) or (0, 0)))

    summary = refresh_all.refresh_all(deep=False, schools={"uw"})

    assert [call["listed_program_keys"] for call in calls] == [set(listed)]
    assert [call["other_file_program_keys"] for call in calls] == [set(other)]
    assert calls[0]["school_slug"] == "uw"
    assert "listed_program_keys" not in summary["sources"]["campus_graph:uw"]
    assert "other_file_program_keys" not in summary["sources"]["campus_graph:uw"]
    assert proof["listed_program_keys"] == listed
    assert proof["other_file_program_keys"] == other


def test_the_run_summary_counts_fetches_skipped_for_a_rejected_certificate(monkeypatch, tmp_path):
    from src.collectors import ucb_common
    from tests.test_ucb_common import rejected_certificate

    _stub_with_processed_file(monkeypatch, tmp_path, [])

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.verify = True

        def get(self, url, timeout=None):
            raise rejected_certificate(url)

    monkeypatch.setattr(ucb_common.requests, "Session", FakeSession)
    monkeypatch.setattr(ucb_common.time, "sleep", lambda s: None)

    def fetch_three_listings():
        for i in range(3):
            ucb_common.fetch_soup(f"https://www.udel.edu/d{i}/our-people/")
        return []

    monkeypatch.setattr(refresh_all, "fetch_ucb_urap", fetch_three_listings)
    monkeypatch.setattr(refresh_all, "enrich_pi", lambda opps, save=True, max_scrapes=None, deadline=None: {
        "scraped": 0, "enriched": 0, "already_has_email": 0, "skipped_budget": 0, "skipped_certificate": 5})
    # Left from an earlier run in this process: a run counts only its own.
    stale = "https://stale.example.edu/"
    ucb_common.note_rejected_certificate(stale, rejected_certificate(stale))
    try:
        summary = refresh_all.refresh_all(deep=False, schools={"ucb"})
    finally:
        ucb_common.reset_certificate_circuit()

    assert summary["rejected_certificates"] == {"hosts": {"www.udel.edu": 2}, "skipped": 2}
    assert summary["sources"]["pi_enricher"]["skipped_certificate"] == 5


def test_listed_program_keys_reach_the_ucb_campus_merge_without_report_content(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    listed, other = ["first_program", "second_program"], ["open_program"]
    proof = {"complete_recursive_sources": [], "listed_program_keys": listed, "other_file_program_keys": other}
    monkeypatch.setattr(refresh_all, "fetch_ucb_campus_with_evidence", lambda *a, **k: ([], proof))
    calls = []
    monkeypatch.setattr(refresh_all, "merge_ucb_campus", lambda records, **kwargs: (calls.append(kwargs) or (0, 0)))

    summary = refresh_all.refresh_all(deep=False, schools={"ucb"})

    assert [call["listed_program_keys"] for call in calls] == [set(listed)]
    assert [call["other_file_program_keys"] for call in calls] == [set(other)]
    assert "listed_program_keys" not in summary["sources"]["ucb_campus"]
    assert "other_file_program_keys" not in summary["sources"]["ucb_campus"]
    assert proof["listed_program_keys"] == listed
    assert proof["other_file_program_keys"] == other


def test_a_ucb_refresh_retires_a_program_dropped_from_its_registry(monkeypatch, tmp_path):
    from src.collectors import ucb_campus, ucb_sources

    def program(key):
        return ucb_sources._prog(key, f"{key.title()} Fellowship", f"https://example.berkeley.edu/{key}/", "Curated")

    source = {"source_name": "ucb_fixture_programs", "source_type": ucb_sources.PROGRAM,
              "emit": ucb_sources.EMIT_CAMPUS, "crawl": ucb_sources.STATIC, "crawl_depth": 1,
              "update": ucb_sources.WEEKLY, "seeds": ["https://example.berkeley.edu/"],
              "programs": [program("kept"), program("dropped")]}
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [])
    monkeypatch.setattr(ucb_campus, "PROCESSED_FILE", processed)
    monkeypatch.setattr(ucb_sources, "UCB_SOURCES", [source])
    ucb_campus.merge_into_processed(ucb_campus.fetch_and_normalize())
    source["programs"] = [program("kept")]
    monkeypatch.setattr(refresh_all, "fetch_ucb_campus_with_evidence", ucb_campus.fetch_and_normalize_with_evidence)
    monkeypatch.setattr(refresh_all, "merge_ucb_campus", ucb_campus.merge_into_processed)

    summary = refresh_all.refresh_all(deep=False, schools={"ucb"})

    assert summary["sources"]["ucb_campus"]["status"] == "ok"
    stored = {row["metadata"]["collector_key"]: row["metadata"]
              for row in json.loads(processed.read_text(encoding="utf-8"))}
    assert stored["kept"]["is_active"] is True
    assert stored["dropped"]["is_active"] is False
    assert stored["dropped"]["deactivation_reason"] == "no_longer_listed"


def test_a_campus_refresh_retires_dropped_programs_only_where_it_completed(monkeypatch, tmp_path):
    """Each school drops its "dropped" program. uw's refresh completes, duke's
    fetch fails and wisc is outside the shard, so only uw's row retires."""
    from src.collectors import campus_graph

    real = {config["school_slug"]: config for config in refresh_all.SCHOOL_CONFIGS}

    def school(slug, *keys):
        return {
            **{field: real[slug][field] for field in ("school_slug", "organization", "location", "emit")},
            "sources": [{
                "source_name": f"{slug}_fixture_programs", "source_type": campus_graph.PROGRAM,
                "emit": "campus", "crawl": campus_graph.STATIC,
                "seeds": [f"https://{slug}.example.edu/"],
                "programs": [campus_graph.program(key, f"{slug} {key} fellowship",
                                                  f"https://{slug}.example.edu/{key}/", "Curated")
                             for key in keys],
            }],
        }

    def dropped_id(slug):
        return campus_graph._hash_id(slug, real[slug]["emit"]["campus"][0], "dropped")

    slugs = ("uw", "duke", "wisc")
    processed = _stub_with_processed_file(monkeypatch, tmp_path, [])
    monkeypatch.setattr(campus_graph, "PROCESSED_FILE", processed)
    for slug in slugs:
        campus_graph.merge_into_processed(campus_graph.fetch_and_normalize(school(slug, "kept", "dropped")))

    def fetch(config, deep=False, **kwargs):
        if config["school_slug"] == "duke":
            raise RuntimeError("synthetic duke fetch failure")
        return campus_graph.fetch_and_normalize_with_evidence(config, deep=deep, **kwargs)

    monkeypatch.setattr(refresh_all, "SCHOOL_CONFIGS", [school(slug, "kept") for slug in slugs])
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", fetch)
    monkeypatch.setattr(refresh_all, "merge_campus_graph", campus_graph.merge_into_processed)

    summary = refresh_all.refresh_all(deep=False, schools={"uw", "duke"})

    assert summary["sources"]["campus_graph:uw"]["status"] == "ok"
    assert summary["sources"]["campus_graph:duke"]["status"] == "error"
    assert "campus_graph:wisc" not in summary["sources"]
    stored = {row["id"]: row["metadata"] for row in json.loads(processed.read_text(encoding="utf-8"))}
    assert stored[dropped_id("uw")]["deactivation_reason"] == "no_longer_listed"
    assert stored[dropped_id("duke")]["is_active"] is True
    assert stored[dropped_id("wisc")]["is_active"] is True


@pytest.mark.parametrize("scenario", ["captured", "empty", "detail_failed", "unsupported", "list_failed"])
def test_b55_real_sro_evidence_flows_to_health_and_safe_publish(monkeypatch, tmp_path, scenario):
    import socket
    from datetime import UTC, datetime, timedelta

    import requests

    from src.collectors import source_health, uiuc_sro
    from src.collectors.base import RawOpportunity
    from src.contact_instructions import SOURCE_KEY, source_from_html

    url = "https://researchops.web.illinois.edu/audit-program"
    now = datetime.now(UTC)
    old_time = (now - timedelta(days=3)).isoformat()
    prior = uiuc_sro.raw_to_normalized(RawOpportunity(source="uiuc_sro", source_url="https://researchops.web.illinois.edu/?page=0",
        url=url, title="Audit program", description_raw="Study sensors"))
    prior["metadata"][SOURCE_KEY] = [source_from_html("<main><h2>Minimum GPA</h2><p>3.0</p></main>", source_url=url, checked_at=old_time)]
    prior["metadata"]["last_verified"] = old_time
    path = _stub_with_processed_file(monkeypatch, tmp_path, [prior])
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("No external network permitted"))
    monkeypatch.setattr(uiuc_sro.UIUCSROCollector, "_rate_limit", lambda *a: None)
    monkeypatch.setattr(uiuc_sro.UIUCSROCollector, "MAX_PAGES", 3)
    monkeypatch.setattr(uiuc_sro, "LIST_RETRY_BACKOFF", 0)
    table = '<table class="views-table"><tbody><tr><td class="views-field-title"><a href="/audit-program">Audit program</a><br>Study sensors</td></tr></tbody></table>'
    empty = '<table class="views-table"><tbody></tbody></table>'
    class Response:
        def __init__(self, requested, html): self.url, self.text = requested, html
        def raise_for_status(self): pass
    def get(requested, **kwargs):
        if "?page=" in requested:
            if "page=1" in requested and scenario == "list_failed":
                raise requests.Timeout("synthetic failure")
            return Response(requested, table if "page=0" in requested else empty)
        assert requested == url
        if scenario == "detail_failed": raise requests.Timeout("synthetic detail failure")
        body = {"empty": "<main><p>This lab studies sensors.</p></main>",
                "unsupported": "<main><h2>Minimum GPA</h2><div>3.0</div><p>This lab studies sensors.</p></main>"}.get(
                    scenario, "<main><h2>Minimum GPA</h2><p>3.5</p></main>")
        return Response(requested, body)
    monkeypatch.setattr(uiuc_sro.requests, "get", get)
    monkeypatch.setattr(refresh_all, "fetch_sro_with_evidence", uiuc_sro.fetch_and_normalize_with_evidence)
    monkeypatch.setattr(refresh_all, "merge_sro", lambda records: uiuc_sro.merge_into_processed(records, str(path)))
    ledger = source_health.empty_ledger()
    source_health.record_attempt(ledger, source="uiuc_sro", school=None, outcome=source_health.SUCCESS_NONZERO,
                                emitted=1, baseline=1, now=now - timedelta(days=3))
    source_health.save_ledger(ledger, tmp_path / "source_health.json")
    summary = refresh_all.refresh_all(deep=True, national=True)
    info = summary["sources"]["uiuc_sro"]
    health = source_health.load_ledger(tmp_path / "source_health.json")["sources"]["uiuc_sro"]
    stored = next(row for row in json.loads(path.read_text()) if row["id"] == prior["id"])
    assert info["fetched"] == 1
    assert info["list_pages_attempted"] == info["list_pages_loaded"] + info["list_pages_failed"]
    assert sum(info["condition_capture_counts"].values()) == info["detail_pages_attempted"] == 1
    assert "national" in summary["release"]["publishable"]
    if scenario in {"captured", "empty"}:
        assert info["status"] == "ok"
        assert health["status"] == source_health.SUCCESS_NONZERO
        assert health["last_success_at"] != old_time
        assert info["condition_capture_counts"][scenario] == 1
        assert bool(stored["metadata"][SOURCE_KEY]) == (scenario == "captured")
    else:
        assert info["status"] == "partial_failure"
        assert health["status"] == source_health.FAILED
        assert health["last_success_at"] == old_time
        assert summary["release"]["status"] == "degraded"
        if scenario != "list_failed":
            assert stored["metadata"][SOURCE_KEY] == prior["metadata"][SOURCE_KEY]
            assert stored["metadata"]["last_verified"] == old_time


def _national_run_with_unread_sro_list(monkeypatch, tmp_path, list_page, stored_sro=True):
    """A deep national run whose SRO list pages all answer as ``list_page``
    does; the corpus holds one SRO program last verified three days ago,
    or with ``stored_sro`` false one row of another source."""
    import socket
    from datetime import UTC, datetime, timedelta

    from src.collectors import source_health, uiuc_sro
    from src.collectors.base import RawOpportunity

    old_time = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    prior = uiuc_sro.raw_to_normalized(RawOpportunity(
        source="uiuc_sro", source_url="https://researchops.web.illinois.edu/?page=0",
        url="https://researchops.web.illinois.edu/audit-program", title="Audit program",
        description_raw="Study sensors"))
    prior["metadata"]["last_verified"] = old_time
    if not stored_sro:
        prior["source"] = "manual"
    path = _stub_with_processed_file(monkeypatch, tmp_path, [prior])
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("No external network permitted"))
    monkeypatch.setattr(uiuc_sro.UIUCSROCollector, "_rate_limit", lambda *a: None)
    monkeypatch.setattr(uiuc_sro.UIUCSROCollector, "MAX_PAGES", 3)
    monkeypatch.setattr(uiuc_sro.requests, "get", list_page)
    monkeypatch.setattr(refresh_all, "fetch_sro_with_evidence", uiuc_sro.fetch_and_normalize_with_evidence)
    monkeypatch.setattr(refresh_all, "merge_sro", lambda records: uiuc_sro.merge_into_processed(records, str(path)))
    ledger = source_health.empty_ledger()
    source_health.record_attempt(ledger, source="uiuc_sro", school=None, outcome=source_health.SUCCESS_NONZERO,
                                emitted=1, baseline=1, now=datetime.fromisoformat(old_time))
    source_health.save_ledger(ledger, tmp_path / "source_health.json")
    tracking = []
    monkeypatch.setattr(refresh_all, "_update_professor_tracking",
                        lambda *a, **k: tracking.append(k["refresh_ok"]))
    summary = refresh_all.refresh_all(deep=True, national=True)
    health = source_health.load_ledger(tmp_path / "source_health.json")["sources"]["uiuc_sro"]
    stored = next(row for row in json.loads(path.read_text()) if row["id"] == prior["id"])
    return summary, health, prior, stored, old_time, tracking


def _sro_list_refused(requested, **kwargs):
    import requests

    response = requests.Response()
    response.status_code = 403
    raise requests.HTTPError("403 Client Error: Forbidden", response=response)


def _sro_list_without_table(requested, **kwargs):
    class Response:
        url, text = requested, "<main><p>Scheduled maintenance.</p></main>"

        def raise_for_status(self): pass
    return Response()


@pytest.mark.parametrize("list_page", [_sro_list_refused, _sro_list_without_table])
def test_an_unread_sro_list_degrades_the_national_shard_and_keeps_its_rows(monkeypatch, tmp_path, list_page):
    """On 2026-11-15 the SRO list read nothing, the source was labelled
    "error", and Simplify, NSF and every national campus program went
    unpublished with it."""
    from src.collectors import source_health

    summary, health, prior, stored, old_time, tracking = _national_run_with_unread_sro_list(
        monkeypatch, tmp_path, list_page)

    info = summary["sources"]["uiuc_sro"]
    release = summary["release"]
    assert info["fetched"] == 0 and info["list_pages_loaded"] == 0 and info["list_complete"] is False
    assert info["status"] == source_health.SUSPICIOUS_ZERO
    assert info["suspicious_zero_baseline"] == 1
    assert info["error"].startswith("Source check incomplete: list_pages_failed, list_incomplete")
    assert "national" in release["publishable"] and release["status"] == "degraded"
    assert {"kind": "suspicious_zero", "source": "uiuc_sro",
            "detail": "0 records, previously 1"} in release["degradations"]
    # The stored program is as it was: not retired, no date moved.
    assert stored["metadata"] == prior["metadata"]
    assert stored["metadata"]["is_active"] is True and stored["metadata"]["last_verified"] == old_time
    assert "unlisted" not in info
    # Its last success stays where it was, and tracking stays closed.
    assert health["status"] == source_health.SUSPICIOUS_ZERO
    assert health["last_success_at"] == old_time
    assert health["consecutive_failures"] == 1
    assert tracking == [False]


def test_an_unread_sro_list_still_withholds_national_when_the_corpus_holds_no_sro_rows(monkeypatch, tmp_path):
    summary, health, *_ = _national_run_with_unread_sro_list(
        monkeypatch, tmp_path, _sro_list_refused, stored_sro=False)

    info = summary["sources"]["uiuc_sro"]
    assert info["status"] == "error" and "suspicious_zero_baseline" not in info
    assert "national" not in summary["release"]["publishable"]
    assert any(reason.startswith("source uiuc_sro reported error: Source check incomplete")
               for reason in summary["release"]["by_unit"]["national"]["reasons"])
    assert health["status"] == "failed"


def test_an_unread_sro_list_with_invalid_evidence_still_withholds_national(monkeypatch, tmp_path):
    summary, *_ = _national_run_with_unread_sro_list(monkeypatch, tmp_path, _sro_list_refused)
    assert summary["sources"]["uiuc_sro"]["status"] == "suspicious_zero"

    # The same run with page counts that do not add up: three tried, one failed.
    monkeypatch.setattr(refresh_all, "fetch_sro_with_evidence", lambda **kwargs: ([], {
        "list_pages_attempted": 3, "list_pages_loaded": 0, "list_pages_failed": 1,
        "list_complete": False, "list_errors": []}))
    summary = refresh_all.refresh_all(deep=True, national=True)

    info = summary["sources"]["uiuc_sro"]
    assert info["status"] == "error" and info["incomplete_reasons"] == ["list_pages_counts_invalid"]
    assert "national" not in summary["release"]["publishable"]


def test_an_empty_national_campus_crawl_with_failed_pages_is_still_an_error(monkeypatch, tmp_path):
    """The rule above is for the three national list sources. A campus
    program that publishes in the national shard keeps the label it had,
    whatever rows the corpus holds for it."""
    from src.collectors.refresh_contract import national_campus_sources

    key = sorted(national_campus_sources())[0]
    stored = _seed_faculty(key, "campus-program", days_ago=3)
    stored["source_type"] = "campus_program"
    _stub_with_processed_file(monkeypatch, tmp_path, [stored])
    proof = {"deep": True, "crawl_sources_expected": 1, "crawl_sources_loaded": 0,
             "live_pages_attempted": 1, "live_pages_loaded": 0, "seed_pages_expected": 1,
             "seed_pages_loaded": 0, "seed_pages_failed": 1, "crawl_errors": ["seed fetch failed"]}
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", lambda *a, **k: ([], proof))
    monkeypatch.setattr(refresh_all, "fetch_ucb_campus_with_evidence", lambda *a, **k: ([], proof))

    summary = refresh_all.refresh_all(deep=True, national=True)

    assert summary["sources"][key]["status"] == "error"
    assert "national" not in summary["release"]["publishable"]


@pytest.mark.parametrize("scenario", ["complete", "control_refused", "list_failed", "normalization_failed",
                                      "evidence_missing", "merge_failed"])
def test_a_complete_sro_listing_retires_only_unlisted_programs_whose_page_is_gone(monkeypatch, tmp_path, scenario):
    import socket

    import requests

    from src.collectors import uiuc_sro
    from src.collectors.base import RawOpportunity

    base = "https://researchops.web.illinois.edu"

    def stored(slug, title):
        return uiuc_sro.raw_to_normalized(RawOpportunity(
            source="uiuc_sro", source_url=f"{base}/?page=0", url=f"{base}/opportunity/{slug}",
            title=title, description_raw="Study sensors"))

    listed = stored("sensor-reu", "Sensor REU")
    # The same program under its old title: the database moved its page.
    renamed = stored("sensor-reu-illinois", "Sensor REU at Illinois")
    # Still published, but a row shifting between pages kept it out of this read.
    unseen = stored("dig-week", "Dig week")
    path = _stub_with_processed_file(monkeypatch, tmp_path, [listed, renamed, unseen])
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("No external network permitted"))
    monkeypatch.setattr(uiuc_sro.UIUCSROCollector, "_rate_limit", lambda *a: None)
    monkeypatch.setattr(uiuc_sro.UIUCSROCollector, "MAX_PAGES", 3)
    monkeypatch.setattr(uiuc_sro, "LIST_RETRY_BACKOFF", 0)
    monkeypatch.setattr(uiuc_sro, "DEEP_SCRAPE_DELAY", 0)
    rows = ('<tr><td class="views-field-title"><a href="/opportunity/sensor-reu">Sensor REU</a><br>Study sensors</td></tr>'
            '<tr><td class="views-field-title"><a href="/opportunity/field-school">Field school</a><br>Dig sites</td></tr>')
    table = f'<table class="views-table"><tbody>{rows}</tbody></table>'
    empty = '<table class="views-table"><tbody></tbody></table>'
    pages = {
        f"{base}/opportunity/sensor-reu": (403 if scenario == "control_refused" else 200, None),
        f"{base}/opportunity/sensor-reu-illinois": (301, "/opportunity/sensor-reu"),
        f"{base}/opportunity/dig-week": (200, None),
    }

    class Response:
        def __init__(self, requested, html="", status=200, location=None):
            self.url, self.text, self.status_code = requested, html, status
            self.headers = {"Location": location} if location else {}

        def raise_for_status(self): pass

    def get(requested, **kwargs):
        if "?page=" in requested:
            if "page=1" in requested and scenario == "list_failed":
                raise requests.Timeout("synthetic failure")
            return Response(requested, table if "page=0" in requested else empty)
        assert kwargs.get("allow_redirects") is False
        status, location = pages[requested]
        return Response(requested, status=status, location=location)

    monkeypatch.setattr(uiuc_sro.requests, "get", get)
    fetch = uiuc_sro.fetch_and_normalize_with_evidence
    if scenario == "normalization_failed":
        normalize = uiuc_sro.raw_to_normalized

        def fail_field_school(raw):
            if raw.title == "Field school":
                raise ValueError("synthetic normalization failure")
            return normalize(raw)

        monkeypatch.setattr(uiuc_sro, "raw_to_normalized", fail_field_school)
    if scenario == "evidence_missing":
        def fetch(deep=False):
            return uiuc_sro.fetch_and_normalize_with_evidence(deep=deep)[0], {}
    def merge(records):
        if scenario == "merge_failed":
            raise OSError("synthetic merge failure")
        return uiuc_sro.merge_into_processed(records, str(path))
    monkeypatch.setattr(refresh_all, "fetch_sro_with_evidence", fetch)
    monkeypatch.setattr(refresh_all, "merge_sro", merge)

    summary = refresh_all.refresh_all(deep=False, national=True)

    info = summary["sources"]["uiuc_sro"]
    rows_after = {row["id"]: row["metadata"] for row in json.loads(path.read_text(encoding="utf-8"))}
    assert rows_after[listed["id"]]["is_active"] is True
    assert rows_after[unseen["id"]]["is_active"] is True
    if scenario == "complete":
        assert info["unlisted"] == {"deactivated": 1, "kept": 1, "control": "live"}
        assert rows_after[renamed["id"]]["is_active"] is False
        assert rows_after[renamed["id"]]["deactivation_reason"] == "no_longer_listed"
    else:
        assert rows_after[renamed["id"]]["is_active"] is True
        if scenario == "control_refused":
            assert info["unlisted"] == {"deactivated": 0, "kept": 2, "control": "gone"}
        else:
            assert "unlisted" not in info
