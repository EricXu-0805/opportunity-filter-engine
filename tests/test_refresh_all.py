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

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.collectors.refresh_all as refresh_all

UCB_FACULTY_SOURCES = {"ucb_eecs_faculty", "ucb_stat_faculty"}


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


def test_quick_run_skips_ucb_faculty_but_keeps_ucb_urap(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    summary = refresh_all.refresh_all(deep=False)
    sources = summary["sources"]
    assert sources["ucb_urap"]["status"] == "ok"
    assert not UCB_FACULTY_SOURCES & sources.keys()


def test_eecs_merges_before_stat(monkeypatch, tmp_path):
    _stub_all_collectors(monkeypatch, tmp_path)
    order: list[str] = []
    monkeypatch.setattr(refresh_all, "merge_ucb_eecs",
                        lambda opps: (order.append("eecs"), (0, 0))[1])
    monkeypatch.setattr(refresh_all, "merge_ucb_stat",
                        lambda opps: (order.append("stat"), (0, 0))[1])
    refresh_all.refresh_all(deep=True)
    assert order == ["eecs", "stat"]


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
