"""Offline tests for src.collectors.uiuc_other.

Mocks requests.get so the suite stays hermetic — no network access, no
live URL flakiness. Confirms the registry shape, the open/closed status
keyword detection, the seed-fallback path on fetch failure, and the
normalized output schema. Each PROGRAMS entry is exercised in parallel
so adding a new entry without testing it gets caught here.

Network calls are forbidden. The collector's _rate_limit() is bypassed
by instantiating with rate_limit_delay=0 so the suite doesn't sleep 14s
on every run (conftest's OFE_DISABLE_RATE_LIMIT only governs HTTP
fastapi rate limits, not collector inter-request delays).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.uiuc_other import (
    PROGRAMS,
    UIUCOtherCollector,
    _hash_id,
    _to_normalized,
)


def _mock_response(text: str = "page content"):
    r = MagicMock()
    r.text = text
    r.status_code = 200
    r.raise_for_status = MagicMock()
    return r


def _collector() -> UIUCOtherCollector:
    return UIUCOtherCollector(config={"rate_limit_delay": 0})


class TestProgramsRegistry:
    def test_each_program_has_required_fields(self):
        for spec in PROGRAMS:
            assert "key" in spec and spec["key"]
            assert "url" in spec and spec["url"].startswith("https://")
            assert "title" in spec and len(spec["title"]) > 0
            assert "organization" in spec and spec["organization"]
            assert "fallback_desc" in spec and len(spec["fallback_desc"]) > 50
            assert spec.get("paid") in {"yes", "no", "stipend", "unknown"}
            assert isinstance(spec.get("majors", []), list)
            assert isinstance(spec.get("preferred_year", []), list)

    def test_program_keys_are_unique(self):
        keys = [p["key"] for p in PROGRAMS]
        assert len(keys) == len(set(keys)), f"Duplicate keys in PROGRAMS: {keys}"

    def test_program_urls_are_unique(self):
        urls = [p["url"] for p in PROGRAMS]
        assert len(urls) == len(set(urls)), "Duplicate URLs in PROGRAMS"

    def test_research_park_is_registered(self):
        keys = {p["key"] for p in PROGRAMS}
        assert "research_park_internships" in keys

    def test_research_park_spec_shape(self):
        rp = next(p for p in PROGRAMS if p["key"] == "research_park_internships")
        assert rp["organization"] == "Research Park"
        assert rp["paid"] == "yes"
        assert rp["contact_email"] == "uirp-jobs@illinois.edu"
        assert "researchpark.illinois.edu" in rp["url"]


class TestStatusDetection:
    @patch("src.collectors.uiuc_other.requests.get")
    def test_open_keyword_promotes_status_and_title(self, mock_get):
        mock_get.return_value = _mock_response("Welcome — applications open until Dec 15")
        records = _collector().collect()
        assert len(records) == len(PROGRAMS)
        for r in records:
            assert r.extra_fields["status"] == "open"
            assert "(applications open)" in r.title

    @patch("src.collectors.uiuc_other.requests.get")
    def test_closed_keyword_promotes_status_and_title(self, mock_get):
        mock_get.return_value = _mock_response("applications closed for the 2026 cycle")
        records = _collector().collect()
        for r in records:
            assert r.extra_fields["status"] == "closed"
            assert "(applications closed)" in r.title

    @patch("src.collectors.uiuc_other.requests.get")
    def test_no_keyword_leaves_status_unknown_with_clean_title(self, mock_get):
        mock_get.return_value = _mock_response("general program description with no status text")
        records = _collector().collect()
        for r, spec in zip(records, PROGRAMS, strict=True):
            assert r.extra_fields["status"] == "unknown"
            assert r.title == spec["title"]


class TestFallbackOnFetchFailure:
    @patch("src.collectors.uiuc_other.requests.get")
    def test_network_exception_falls_back_to_seed_text(self, mock_get):
        mock_get.side_effect = RuntimeError("DNS lookup failed")
        records = _collector().collect()
        assert len(records) == len(PROGRAMS), "all records returned despite total failure"
        for r, spec in zip(records, PROGRAMS, strict=True):
            assert r.description_raw == spec["fallback_desc"]
            assert r.extra_fields["status"] == "unknown"

    @patch("src.collectors.uiuc_other.requests.get")
    def test_http_error_falls_back_to_seed_text(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.side_effect = RuntimeError("502 bad gateway")
        mock_get.return_value = resp
        records = _collector().collect()
        for r, spec in zip(records, PROGRAMS, strict=True):
            assert r.description_raw == spec["fallback_desc"]


class TestNormalization:
    def test_hash_id_is_deterministic_and_collision_free(self):
        ids = {_hash_id(p["key"], "uiuc_other") for p in PROGRAMS}
        assert len(ids) == len(PROGRAMS), "hash collision across PROGRAMS keys"
        for p in PROGRAMS:
            a = _hash_id(p["key"], "uiuc_other")
            b = _hash_id(p["key"], "uiuc_other")
            assert a == b

    @patch("src.collectors.uiuc_other.requests.get")
    def test_normalized_records_have_program_overview_schema(self, mock_get):
        mock_get.return_value = _mock_response()
        raw = _collector().collect()
        opps = [_to_normalized(r) for r in raw]
        assert len(opps) == len(PROGRAMS)
        for opp in opps:
            assert opp["metadata"]["is_active"] is True
            assert opp["on_campus"] is True
            assert opp["is_rolling"] is True
            assert opp["eligibility"]["international_friendly"] == "yes"
            assert opp["application"]["application_url"].startswith("https://")
            assert "program_overview" in opp["keywords"]
            assert opp["source"] == "uiuc_other"

    @patch("src.collectors.uiuc_other.requests.get")
    def test_research_park_normalized_record_fields(self, mock_get):
        mock_get.return_value = _mock_response()
        raw = _collector().collect()
        opps = [_to_normalized(r) for r in raw]
        rp = next((o for o in opps if o.get("program_key") == "research_park_internships"), None)
        assert rp is not None
        assert rp["organization"] == "Research Park"
        assert rp["paid"] == "yes"
        assert rp["contact_email"] == "uirp-jobs@illinois.edu"
        assert "Research Park" in rp["title"]
        assert "research_park_internships" in rp["keywords"]
