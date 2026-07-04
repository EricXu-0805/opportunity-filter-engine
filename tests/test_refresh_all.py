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
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.collectors.refresh_all as refresh_all
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
            monkeypatch.setattr(refresh_all, attr, lambda opps: (0, 0))
    monkeypatch.setattr(refresh_all, "PROCESSED_FILE", tmp_path / "missing.json")


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


def test_deep_run_deactivates_stale_faculty(monkeypatch, tmp_path):
    seeded = [
        _seed_faculty("uiuc_faculty", "fac-stale", days_ago=30),
        _seed_faculty("uiuc_faculty", "fac-fresh", days_ago=1),
    ]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    # uiuc_faculty collector "succeeds" with a full-size scrape this run.
    monkeypatch.setattr(refresh_all, "fetch_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(2)])

    summary = refresh_all.refresh_all(deep=True)

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
    seeded = [_seed_faculty("uiuc_faculty", f"fac-{i}", days_ago=60)
              for i in range(10)]
    processed = _stub_with_processed_file(monkeypatch, tmp_path, seeded)
    # Collector "succeeds" but yields only 3 of 10 active records (< 70%).
    monkeypatch.setattr(refresh_all, "fetch_faculty",
                        lambda *a, **k: [{"id": f"f{i}"} for i in range(3)])

    summary = refresh_all.refresh_all(deep=True)

    pass_info = summary["sources"]["deactivate_stale_faculty"]
    assert pass_info["newly_deactivated"] == 0
    assert pass_info["skipped_partial_scrape"] == ["uiuc_faculty"]
    saved = json.loads(processed.read_text(encoding="utf-8"))
    assert all(o["metadata"]["is_active"] is True for o in saved)


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
