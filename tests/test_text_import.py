"""Tests for src.collectors.url_parser.parse_text_llm + the
backend /api/import-text route.

Network-free: the LLM provider is always mocked. parse_text_llm shares
its merge/parse machinery with parse_url_llm (see tests/test_url_import.py
for the schema-validation coverage), so these tests focus on the
text-specific contracts:
  - no V1 fallback (returns None when LLM is not configured)
  - skeleton RawOpportunity has source='text_parser', no url
  - route enforces min/max length + post-strip empty check
  - rate-limit key is shared with /api/import-url's 5/min ceiling
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
from src.collectors.url_parser import (
    PASTE_TEXT_MAX_CHARS,
    PASTE_TEXT_MIN_CHARS,
    parse_text_llm,
)

client = TestClient(app)


SAMPLE_TEXT = (
    "Software Engineering Internship at Acme Robotics. "
    "We're looking for sophomores or juniors with Python and ROS experience. "
    "Stipend of $30/hr. Apply by 2026-04-15. Champaign, IL office (on campus)."
)


class TestParseTextLlm:
    def test_returns_none_when_no_llm_configured(self):
        with patch("backend.lib.llm.is_configured", return_value=False):
            result = parse_text_llm(SAMPLE_TEXT)
        assert result is None

    def test_returns_none_when_chat_completion_empty(self):
        with patch("backend.lib.llm.is_configured", return_value=True):
            with patch("backend.lib.llm.chat_completion", return_value=None):
                result = parse_text_llm(SAMPLE_TEXT)
        assert result is None

    def test_returns_none_on_unparseable_llm_response(self):
        with patch("backend.lib.llm.is_configured", return_value=True):
            with patch("backend.lib.llm.chat_completion", return_value="not a json reply"):
                result = parse_text_llm(SAMPLE_TEXT)
        assert result is None

    def test_extracts_with_llm(self):
        llm_json = json.dumps({
            "title": "Software Engineering Internship",
            "organization": "Acme Robotics",
            "opportunity_type": "internship",
            "location": "Champaign, IL",
            "on_campus": True,
            "paid": "stipend",
            "deadline": "2026-04-15",
            "skills_required": ["Python", "ROS"],
            "preferred_year": ["sophomore", "junior"],
        })
        with patch("backend.lib.llm.is_configured", return_value=True):
            with patch("backend.lib.llm.chat_completion", return_value=llm_json):
                result = parse_text_llm(SAMPLE_TEXT)
        assert result is not None
        assert result.source == "text_parser"
        assert result.source_url == ""
        assert result.title == "Software Engineering Internship"
        assert result.organization == "Acme Robotics"
        assert result.location == "Champaign, IL"
        assert result.deadline == "2026-04-15"
        assert result.extra_fields["opportunity_type"] == "internship"
        assert result.extra_fields["on_campus"] is True
        assert result.extra_fields["paid"] == "stipend"
        assert result.extra_fields["skills_required"] == ["Python", "ROS"]
        assert result.extra_fields["preferred_year"] == ["sophomore", "junior"]
        assert result.extra_fields["llm_enriched"] is True
        assert result.extra_fields["needs_manual_review"] is False

    def test_minimal_llm_response_still_succeeds(self):
        llm_json = json.dumps({"title": "Cool Thing"})
        with patch("backend.lib.llm.is_configured", return_value=True):
            with patch("backend.lib.llm.chat_completion", return_value=llm_json):
                result = parse_text_llm(SAMPLE_TEXT)
        assert result is not None
        assert result.title == "Cool Thing"
        assert result.extra_fields["llm_enriched"] is True

    def test_truncates_body_to_excerpt_limit(self):
        very_long = "x" * 100_000 + " THIS SHOULD NOT REACH THE LLM " + "y" * 100_000
        captured = {}

        def fake_chat(messages, **kwargs):
            captured["messages"] = messages
            return json.dumps({"title": "OK"})

        with patch("backend.lib.llm.is_configured", return_value=True):
            with patch("backend.lib.llm.chat_completion", side_effect=fake_chat):
                result = parse_text_llm(very_long)
        assert result is not None
        user_msg = next(m for m in captured["messages"] if m["role"] == "user")
        assert "THIS SHOULD NOT REACH THE LLM" not in user_msg["content"]
        assert len(user_msg["content"]) < 10_000


class TestImportTextRoute:
    def test_rejects_too_short_text(self):
        resp = client.post("/api/import-text", json={"text": "too short"})
        assert resp.status_code == 422

    def test_rejects_too_long_text(self):
        resp = client.post(
            "/api/import-text",
            json={"text": "x" * (PASTE_TEXT_MAX_CHARS + 1)},
        )
        assert resp.status_code == 422

    def test_rejects_empty_after_strip(self):
        whitespace = "   \n\t " * 20
        assert len(whitespace) >= PASTE_TEXT_MIN_CHARS
        resp = client.post("/api/import-text", json={"text": whitespace})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "too short" in body["error"].lower()

    def test_returns_opportunity_on_parse_success(self):
        from src.collectors.base import RawOpportunity
        sample_opp = RawOpportunity(
            source="text_parser",
            source_url="",
            title="Sample From Paste",
            description_raw="paste body",
            url="",
            organization="Sample Co",
            extra_fields={"llm_enriched": True},
        )
        with patch("backend.routes.import_text.parse_text_llm", return_value=sample_opp):
            resp = client.post("/api/import-text", json={"text": SAMPLE_TEXT})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["llm_enriched"] is True
        assert body["opportunity"]["title"] == "Sample From Paste"
        assert body["opportunity"]["source"] == "text_parser"

    def test_returns_ok_false_when_parse_returns_none(self):
        with patch("backend.routes.import_text.parse_text_llm", return_value=None):
            resp = client.post("/api/import-text", json={"text": SAMPLE_TEXT})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "ai" in body["error"].lower() or "llm" in body["error"].lower()

    def test_validates_missing_text_field(self):
        resp = client.post("/api/import-text", json={})
        assert resp.status_code == 422

    def test_validates_non_string_text(self):
        resp = client.post("/api/import-text", json={"text": 12345})
        assert resp.status_code == 422

    @pytest.mark.parametrize("at_boundary", [
        PASTE_TEXT_MIN_CHARS,
        PASTE_TEXT_MAX_CHARS,
    ])
    def test_accepts_boundary_lengths(self, at_boundary):
        text = "a " * (at_boundary // 2)
        text = text[:at_boundary]
        assert len(text) == at_boundary
        with patch("backend.routes.import_text.parse_text_llm", return_value=None):
            resp = client.post("/api/import-text", json={"text": text})
        assert resp.status_code == 200
