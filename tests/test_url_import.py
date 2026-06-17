"""Tests for src.collectors.url_parser V2 + backend /api/import-url route.

Network-free: every external dependency (requests.get, LLM provider)
is mocked. parse_url_llm is exercised end-to-end with a stubbed LLM
response so the merge logic + schema validation are covered.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
from src.collectors.base import RawOpportunity
from src.collectors.url_parser import (
    MAX_FETCH_BYTES,
    _merge_llm_into_base,
    _parse_llm_json,
    _safe_fetch,
    is_safe_url,
    parse_url_llm,
)

client = TestClient(app)


def _streamed_mock(text: str, *, content_length=None, status=200,
                   is_redirect=False, location=None):
    """A minimal stand-in for a streamed requests.Response: yields the body via
    iter_content (so _safe_fetch's byte-budget loop runs) and decodes .text from
    the bytes _safe_fetch caps and assigns to _content."""
    body = text.encode("utf-8")

    class _R:
        def __init__(self):
            self.status_code = status
            self.is_redirect = is_redirect
            self.headers: dict = {}
            if content_length is not None:
                self.headers["Content-Length"] = str(content_length)
            if location is not None:
                self.headers["Location"] = location
            self._content: object = False

        def iter_content(self, chunk_size):
            step = max(1, chunk_size)
            for i in range(0, len(body), step):
                yield body[i:i + step]

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception("http error")

        def close(self):
            pass

        @property
        def text(self):
            data = self._content if self._content is not False else body
            return data.decode("utf-8")

    return _R()


# ---------- is_safe_url ----------

class TestIsSafeUrl:
    @pytest.mark.parametrize("url,expected_ok", [
        ("https://example.com/job", True),
        ("http://example.com/job", True),
        ("https://uiuc.edu/research/abc", True),
        ("https://www.linkedin.com/jobs/view/12345", True),
    ])
    def test_allows_public_http_urls(self, url, expected_ok):
        ok, _ = is_safe_url(url)
        assert ok is expected_ok

    @pytest.mark.parametrize("url,reason_match", [
        ("file:///etc/passwd", "scheme"),
        ("gopher://example.com", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("ftp://example.com", "scheme"),
    ])
    def test_blocks_non_http_schemes(self, url, reason_match):
        ok, reason = is_safe_url(url)
        assert ok is False
        assert reason_match in reason.lower()

    @pytest.mark.parametrize("url", [
        "http://localhost/x",
        "http://localhost.localdomain/x",
        "http://0.0.0.0/x",
        "http://[::1]/x",
        "http://service.local/x",
        "http://api.internal/x",
        "http://something.localdomain/x",
    ])
    def test_blocks_localhost_and_private_tlds(self, url):
        ok, _ = is_safe_url(url)
        assert ok is False

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/x",
        "http://10.0.0.1/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://[fe80::1]/x",
    ])
    def test_blocks_literal_ip_addresses(self, url):
        ok, reason = is_safe_url(url)
        assert ok is False
        assert "ip" in reason.lower() or "localhost" in reason.lower()

    def test_returns_specific_reason(self):
        ok, reason = is_safe_url("ftp://x.com")
        assert ok is False
        assert "ftp" in reason


# ---------- _parse_llm_json ----------

class TestParseLlmJson:
    def test_plain_json_object(self):
        assert _parse_llm_json('{"title": "Hello"}') == {"title": "Hello"}

    def test_strips_json_code_fence(self):
        wrapped = '```json\n{"title": "X"}\n```'
        assert _parse_llm_json(wrapped) == {"title": "X"}

    def test_strips_bare_code_fence(self):
        wrapped = '```\n{"title": "X"}\n```'
        assert _parse_llm_json(wrapped) == {"title": "X"}

    def test_falls_back_to_regex_when_prefaced(self):
        prefaced = 'Sure, here is the JSON: {"title": "X", "paid": "yes"}'
        result = _parse_llm_json(prefaced)
        assert result == {"title": "X", "paid": "yes"}

    def test_returns_none_for_garbage(self):
        assert _parse_llm_json("nope, no json here at all") is None

    def test_returns_none_for_non_object_top_level(self):
        assert _parse_llm_json('"just a string"') is None
        assert _parse_llm_json('[1, 2, 3]') is None

    def test_handles_multiline_json(self):
        text = '{\n  "title": "X",\n  "paid": "yes"\n}'
        assert _parse_llm_json(text) == {"title": "X", "paid": "yes"}


# ---------- _merge_llm_into_base ----------

class TestMergeLlmIntoBase:
    @pytest.fixture
    def base(self) -> RawOpportunity:
        return RawOpportunity(
            source="url_parser",
            source_url="https://example.com/job",
            title="Untitled Opportunity",
            description_raw="",
            url="https://example.com/job",
            organization="example.com",
            extra_fields={"domain": "example.com", "needs_manual_review": True},
        )

    def test_applies_valid_fields(self, base):
        llm = {
            "title": "Software Engineering Intern",
            "organization": "Acme Corp",
            "opportunity_type": "internship",
            "location": "Champaign, IL",
            "on_campus": True,
            "paid": "stipend",
            "deadline": "2026-03-15",
            "description": "Build cool stuff with us.",
            "skills_required": ["Python", "React"],
            "skills_preferred": ["TypeScript"],
            "preferred_year": ["junior", "senior"],
            "international_friendly": "yes",
        }
        merged = _merge_llm_into_base(base, llm)
        assert merged.title == "Software Engineering Intern"
        assert merged.organization == "Acme Corp"
        assert merged.location == "Champaign, IL"
        assert merged.deadline == "2026-03-15"
        assert merged.description_raw == "Build cool stuff with us."
        assert merged.extra_fields["opportunity_type"] == "internship"
        assert merged.extra_fields["on_campus"] is True
        assert merged.extra_fields["paid"] == "stipend"
        assert merged.extra_fields["skills_required"] == ["Python", "React"]
        assert merged.extra_fields["preferred_year"] == ["junior", "senior"]
        assert merged.extra_fields["international_friendly"] == "yes"
        assert merged.extra_fields["llm_enriched"] is True
        assert merged.extra_fields["needs_manual_review"] is False

    def test_drops_invalid_enum_values(self, base):
        llm = {
            "opportunity_type": "made_up_kind",
            "paid": "free pizza included",
            "international_friendly": "maybe",
        }
        merged = _merge_llm_into_base(base, llm)
        assert "opportunity_type" not in merged.extra_fields
        assert "paid" not in merged.extra_fields
        assert "international_friendly" not in merged.extra_fields

    def test_drops_invalid_deadline_format(self, base):
        llm = {"deadline": "next March"}
        merged = _merge_llm_into_base(base, llm)
        assert merged.deadline is None

    def test_accepts_iso_deadline_only(self, base):
        llm = {"deadline": "2026-03-15"}
        merged = _merge_llm_into_base(base, llm)
        assert merged.deadline == "2026-03-15"

    def test_drops_invalid_year_enums(self, base):
        llm = {"preferred_year": ["junior", "phd", "postdoc"]}
        merged = _merge_llm_into_base(base, llm)
        assert merged.extra_fields["preferred_year"] == ["junior"]

    def test_preserves_base_when_llm_empty(self, base):
        merged = _merge_llm_into_base(base, {})
        assert merged.title == base.title
        assert merged.organization == base.organization
        assert merged.extra_fields["llm_enriched"] is True

    def test_skips_empty_strings(self, base):
        llm = {"title": "  ", "organization": ""}
        merged = _merge_llm_into_base(base, llm)
        assert merged.title == base.title
        assert merged.organization == base.organization

    def test_skips_wrong_types(self, base):
        llm = {
            "title": 42,
            "on_campus": "true",
            "skills_required": "Python, React",
        }
        merged = _merge_llm_into_base(base, llm)
        assert merged.title == base.title
        assert "on_campus" not in merged.extra_fields
        assert "skills_required" not in merged.extra_fields


# ---------- parse_url_llm end-to-end ----------

class TestParseUrlLlm:
    SAMPLE_HTML = """
    <html>
      <head>
        <meta property="og:title" content="Research Assistant - ECE">
        <meta property="og:description" content="Join our ML lab.">
        <title>ECE Research</title>
      </head>
      <body><main>Looking for sophomores or juniors with Python skills.</main></body>
    </html>
    """

    @pytest.fixture(autouse=True)
    def _stub_dns_resolution(self):
        # _safe_fetch resolves the host to reject public names that map to
        # internal IPs; stub it so these end-to-end tests stay network-free.
        with patch("src.collectors.url_parser._host_resolves_to_blocked_ip", return_value=False):
            yield

    def _mock_response(self, text: str):
        return _streamed_mock(text)

    def test_returns_v1_when_no_llm_configured(self):
        with patch("src.collectors.url_parser.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(self.SAMPLE_HTML)
            with patch("backend.lib.llm.is_configured", return_value=False):
                result = parse_url_llm("https://example.com/job")
        assert result is not None
        assert result.title == "Research Assistant - ECE"
        assert result.extra_fields.get("llm_enriched") is not True

    def test_enriches_with_llm_response(self):
        llm_json = json.dumps({
            "opportunity_type": "research",
            "paid": "stipend",
            "skills_required": ["Python", "ML"],
            "preferred_year": ["sophomore", "junior"],
            "deadline": "2026-04-01",
        })
        with patch("src.collectors.url_parser.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(self.SAMPLE_HTML)
            with patch("backend.lib.llm.is_configured", return_value=True):
                with patch("backend.lib.llm.chat_completion", return_value=llm_json):
                    result = parse_url_llm("https://example.com/job")
        assert result is not None
        assert result.extra_fields["opportunity_type"] == "research"
        assert result.extra_fields["paid"] == "stipend"
        assert result.deadline == "2026-04-01"
        assert result.extra_fields["llm_enriched"] is True

    def test_falls_back_to_v1_on_unparseable_llm(self):
        with patch("src.collectors.url_parser.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(self.SAMPLE_HTML)
            with patch("backend.lib.llm.is_configured", return_value=True):
                with patch("backend.lib.llm.chat_completion", return_value="not json at all"):
                    result = parse_url_llm("https://example.com/job")
        assert result is not None
        assert result.title == "Research Assistant - ECE"
        assert result.extra_fields.get("llm_enriched") is not True

    def test_returns_none_on_fetch_failure(self):
        with patch("src.collectors.url_parser.requests.get", side_effect=Exception("connect refused")):
            result = parse_url_llm("https://example.com/job")
        assert result is None

    def test_fetches_url_only_once(self):
        # SSRF/DoS: the V1 parse and the LLM-excerpt must share a single fetch,
        # not round-trip to the (attacker-controllable) URL twice.
        with patch("src.collectors.url_parser._safe_fetch") as mock_sf:
            mock_sf.return_value = _streamed_mock(self.SAMPLE_HTML)
            with patch("backend.lib.llm.is_configured", return_value=False):
                result = parse_url_llm("https://example.com/job")
        assert result is not None
        assert mock_sf.call_count == 1


class TestSafeFetchByteCap:
    """SSRF/DoS: _safe_fetch must bound how much it buffers, so an attacker URL
    serving an unbounded body can't OOM the dyno."""

    @pytest.fixture(autouse=True)
    def _stub_dns_resolution(self):
        with patch("src.collectors.url_parser._host_resolves_to_blocked_ip", return_value=False):
            yield

    def test_rejects_oversized_content_length(self):
        with patch("src.collectors.url_parser.requests.get") as mock_get:
            mock_get.return_value = _streamed_mock("ok", content_length=MAX_FETCH_BYTES + 1)
            assert _safe_fetch("https://example.com/big") is None

    def test_caps_streamed_body_without_content_length(self):
        big = "x" * (MAX_FETCH_BYTES + 100)
        with patch("src.collectors.url_parser.requests.get") as mock_get:
            mock_get.return_value = _streamed_mock(big)  # no Content-Length header
            assert _safe_fetch("https://example.com/big") is None

    def test_returns_capped_body_under_limit(self):
        with patch("src.collectors.url_parser.requests.get") as mock_get:
            mock_get.return_value = _streamed_mock("<html>ok</html>")
            resp = _safe_fetch("https://example.com/ok")
        assert resp is not None
        assert resp.text == "<html>ok</html>"


# ---------- /api/import-url route ----------

class TestImportUrlRoute:
    def test_rejects_unsafe_url_400(self):
        resp = client.post("/api/import-url", json={"url": "file:///etc/passwd"})
        assert resp.status_code == 400
        assert "unsafe" in resp.json()["detail"]

    def test_rejects_localhost(self):
        resp = client.post("/api/import-url", json={"url": "http://localhost:8080/admin"})
        assert resp.status_code == 400

    def test_rejects_literal_ip(self):
        resp = client.post("/api/import-url", json={"url": "http://192.168.1.1/x"})
        assert resp.status_code == 400


# ---------- SEC-1: SSRF-hardened fetch ----------

class TestSafeFetchSSRF:
    def test_ip_is_blocked_for_internal_ranges(self):
        from src.collectors.url_parser import _ip_is_blocked
        for ip in ["169.254.169.254", "127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "::1"]:
            assert _ip_is_blocked(ip), ip
        for ip in ["93.184.216.34", "8.8.8.8"]:
            assert not _ip_is_blocked(ip), ip

    def test_host_resolving_to_private_ip_is_blocked(self):
        from src.collectors import url_parser as up
        priv = [(2, 1, 6, "", ("10.0.0.5", 0))]
        with patch.object(up.socket, "getaddrinfo", return_value=priv):
            assert up._host_resolves_to_blocked_ip("rebind.evil.example")
        pub = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch.object(up.socket, "getaddrinfo", return_value=pub):
            assert not up._host_resolves_to_blocked_ip("example.com")

    def test_safe_fetch_blocks_redirect_to_metadata(self):
        # A public URL 302-ing to the cloud-metadata IP must NOT be followed.
        from src.collectors import url_parser as up
        redirect = type("R", (), {})()
        redirect.is_redirect = True
        redirect.status_code = 302
        redirect.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}
        redirect.text = ""
        with patch.object(up, "_host_resolves_to_blocked_ip", return_value=False), \
             patch.object(up.requests, "get", return_value=redirect) as mock_get:
            assert up._safe_fetch("https://evil.example.com/start") is None
        # Only the first (public) hop was fetched; the metadata URL never was.
        assert mock_get.call_count == 1

    def test_returns_opportunity_on_parse_success(self):
        sample_opp = RawOpportunity(
            source="url_parser",
            source_url="https://example.com/job",
            title="Sample Job",
            description_raw="desc",
            url="https://example.com/job",
            organization="Sample Co",
            extra_fields={"llm_enriched": True},
        )
        with patch("backend.routes.import_url.parse_url_llm", return_value=sample_opp):
            resp = client.post("/api/import-url", json={"url": "https://example.com/job"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["llm_enriched"] is True
        assert body["opportunity"]["title"] == "Sample Job"
        assert body["opportunity"]["organization"] == "Sample Co"

    def test_returns_ok_false_when_parse_returns_none(self):
        with patch("backend.routes.import_url.parse_url_llm", return_value=None):
            resp = client.post("/api/import-url", json={"url": "https://example.com/job"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "failed" in body["error"].lower()

    def test_validates_request_body(self):
        resp = client.post("/api/import-url", json={"url": ""})
        assert resp.status_code == 422
        resp = client.post("/api/import-url", json={})
        assert resp.status_code == 422
