"""Tests for ucb_extra_faculty's per-department accounting.

The source aggregates 10 departments under one "fetched" number in the refresh
summary, so a single department's listing breaking (moved URL, changed markup)
was invisible. The per-department summary line + zero-warnings make it show up
in refresh logs. No network: the scrapers are stubbed.
"""

from __future__ import annotations

import logging

from src.collectors import ucb_extra_faculty as extra


def _person(name: str, slug: str) -> dict:
    return {"name": name, "url": f"https://italian.berkeley.edu/people/{slug}",
            "title": "Professor", "email": "", "research_areas": ""}


def test_per_department_counts_logged_with_zero_warnings(monkeypatch, caplog):
    monkeypatch.setattr(
        extra, "_scrape_card",
        lambda config: [_person("Maria Rossi", "maria-rossi")]
        if config["short"] == "ITAL" else [])
    monkeypatch.setattr(extra, "_scrape_links", lambda config: [])

    with caplog.at_level(logging.INFO, logger="src.collectors.ucb_extra_faculty"):
        out = extra.fetch_and_normalize(enrich=False)

    assert len(out) == 1
    assert out[0]["pi_name"] == "Maria Rossi"
    summary = next(r.message for r in caplog.records
                   if "per-department" in r.message)
    # every configured department appears, zeros included
    assert "ITAL=1" in summary
    for config in extra.CONFIGS:
        assert f"{config['short']}=" in summary
    zero_warnings = [r for r in caplog.records
                     if r.levelno == logging.WARNING and "0 records" in r.message]
    assert len(zero_warnings) == len(extra.CONFIGS) - 1
    assert any("AFRICAM" in r.message for r in zero_warnings)


def test_no_warnings_when_every_department_produces(monkeypatch, caplog):
    monkeypatch.setattr(
        extra, "_scrape_card",
        lambda config: [_person(f"Ada {config['short'].title()}", "ada")])
    monkeypatch.setattr(
        extra, "_scrape_links",
        lambda config: [_person(f"Bo {config['short'].title()}", "bo")])

    with caplog.at_level(logging.INFO, logger="src.collectors.ucb_extra_faculty"):
        out = extra.fetch_and_normalize(enrich=False)

    assert len(out) == len(extra.CONFIGS)
    assert not [r for r in caplog.records
                if r.levelno == logging.WARNING and "0 records" in r.message]
