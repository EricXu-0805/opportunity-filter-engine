"""The seed-rot canary: what it alerts on, and what it deliberately ignores.

Five configured seeds had 404'd undetected by 2026-08 — Bates, Caltech,
Notre Dame, Northwestern and MIT's Wellesley page. Nothing watched for it
because a dead seed only ever showed up as one line among hundreds in a
refresh log.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "check_campus_seeds.py"
_spec = importlib.util.spec_from_file_location("check_campus_seeds", _SCRIPT)
_checker = importlib.util.module_from_spec(_spec)
sys.modules["check_campus_seeds"] = _checker
_spec.loader.exec_module(_checker)


class TestClassify:
    def test_a_missing_page_is_the_only_thing_worth_waking_someone_for(self):
        assert _checker.classify(404) == _checker.GONE
        assert _checker.classify(410) == _checker.GONE

    def test_bot_walls_and_rate_limits_are_not_rot(self):
        """Michigan, JHU and ccrf.uchicago answer 403 to every non-browser.

        Alerting on those means alerting every week forever, which is how a
        check stops being read.
        """
        for status in (401, 403, 406, 429, 451):
            assert _checker.classify(status) == _checker.BLOCKED

    def test_any_success_or_redirect_is_ok(self):
        for status in (200, 202, 301, 302, 308):
            assert _checker.classify(status) == _checker.OK

    def test_a_transport_failure_is_neither_ok_nor_rot(self):
        assert _checker.classify("SSLError") == _checker.UNREACHABLE
        assert _checker.classify("ConnectTimeout") == _checker.UNREACHABLE
        assert _checker.classify(None) == _checker.UNREACHABLE

    def test_a_server_error_is_not_a_missing_page(self):
        assert _checker.classify(500) == _checker.UNREACHABLE
        assert _checker.classify(503) == _checker.UNREACHABLE


class TestSeedInventory:
    def test_every_configured_seed_is_enumerated(self):
        from src.collectors.schools import SCHOOL_CONFIGS

        expected = sum(
            len(source.get("seeds", []) or [])
            for config in SCHOOL_CONFIGS
            for source in config.get("sources", [])
        )
        seeds = _checker.configured_seeds()

        assert len(seeds) == expected
        assert expected > 500, "the registry should not have collapsed"
        assert all(url.startswith("http") for _slug, _src, url in seeds)

    def test_the_five_rotted_urls_are_gone_from_the_configs(self):
        """Pin the successors so a revert reintroduces a known-dead page."""
        urls = {url for _slug, _src, url in _checker.configured_seeds()}
        retired = {
            "https://www.bates.edu/academics/student-research/summer-grants-summary/",
            "https://deans.caltech.edu/Grants_Funding/gwhfund",
            "https://kellogg.nd.edu/opportunities/undergraduate-students/",
            "https://www.tgs.northwestern.edu/success/recruitment/summer-research-opportunity-program/",
            "https://urop.mit.edu/urop-for-wellesley-college-students/",
        }

        assert not (urls & retired)
