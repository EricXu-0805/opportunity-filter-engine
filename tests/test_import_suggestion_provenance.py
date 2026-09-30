"""Synthetic API imports keep source text separate from unverified model output."""

import json
import socket
from copy import deepcopy
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from src.collectors import url_parser
from src.collectors.base import RawOpportunity
from src.normalizers.normalizer import normalize
from tests.test_url_import_sources import HTML, URL, response


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    monkeypatch.setattr("backend.main._warmup", lambda: None)
    monkeypatch.setattr("backend.lib.material_cleanup.configured", lambda: False)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("No network allowed"))
    monkeypatch.setattr(url_parser, "_host_resolves_to_blocked_ip", lambda host: False)
    monkeypatch.setattr("backend.lib.llm.is_configured", lambda: True)
    monkeypatch.setattr(
        "backend.lib.llm.chat_completion",
        lambda *a, **k: json.dumps(
            {
                "title": "Python software engineer",
                "description": "Java and R programming are required.",
                "skills_required": ["Java", "R"],
                "skills_preferred": ["C++", "Java"],
            }
        ),
    )


def test_actual_url_route_retains_source_and_separates_model_suggestions(monkeypatch):
    monkeypatch.setattr(url_parser.requests, "get", lambda *a, **k: response())
    with TestClient(app) as client:
        reply = client.post("/api/import-url", json={"url": URL}).json()
    raw = reply["opportunity"]
    assert reply["ok"] is True
    assert raw["description_raw"] == url_parser.parse_url(URL, html=HTML).description_raw
    assert raw["extra_fields"]["suggested_description"] == "Java and R programming are required."
    assert raw["extra_fields"]["suggested_skills"] == ["Java", "R", "C++"]
    assert raw["extra_fields"]["needs_manual_review"] is True
    assert "skills_required" not in raw["extra_fields"]
    assert "skills_preferred" not in raw["extra_fields"]
    assert raw["extra_fields"]["contact_instruction_sources"][0]["sections"][0]["text"] == "A CV is required."


def test_actual_text_route_keeps_complete_paste_beyond_model_excerpt():
    text = "This is the original internship description. " + "source text " * 500 + " LAST SOURCE SENTENCE."
    with TestClient(app) as client:
        reply = client.post("/api/import-text", json={"text": text}).json()
    raw = reply["opportunity"]
    assert raw["description_raw"] == text
    assert raw["extra_fields"]["suggested_description"] == "Java and R programming are required."
    assert raw["extra_fields"]["needs_manual_review"] is True
    assert "contact_instruction_sources" not in raw["extra_fields"]


def test_model_summary_and_title_cannot_supply_normalized_eligibility():
    base = RawOpportunity(
        source="text_parser",
        source_url="",
        url="",
        title="Untitled Opportunity",
        description_raw="We study bird migration in field surveys.",
        extra_fields={},
    )
    merged = url_parser._merge_llm_into_base(
        base,
        {
            "title": "Python Java information science intern",
            "description": "Python and Java programming are required.",
            "skills_required": ["Python", "Java"],
        },
    )
    normalized = normalize(asdict(merged))
    assert not normalized["eligibility"]["skills_required"]
    assert not normalized["eligibility"]["skills_preferred"]
    assert not normalized["eligibility"]["majors"]
    assert "Python" not in normalized["metadata"].get("skill_mentions", [])
    assert "Java" not in normalized["metadata"].get("skill_mentions", [])


def test_model_merge_does_not_mutate_or_restamp_source_receipt():
    original = {
        "contact_instruction_capture": {"status": "unsupported"},
        "contact_instruction_sources": [],
        "needs_manual_review": True,
    }
    base = RawOpportunity(
        source="url_parser",
        source_url=URL,
        url=URL,
        title="Source title",
        description_raw="Original source.",
        extra_fields=deepcopy(original),
    )
    merged = url_parser._merge_llm_into_base(
        base,
        {
            "description": "Generated summary.",
            "needs_manual_review": False,
            "contact_instruction_sources": [{"quote": "invented"}],
            "contact_instruction_capture": {"status": "captured"},
        },
    )
    assert base.extra_fields == original
    assert merged.extra_fields["contact_instruction_capture"] == original["contact_instruction_capture"]
    assert merged.extra_fields["contact_instruction_sources"] == []
    assert merged.description_raw == "Original source."
    assert merged.extra_fields["needs_manual_review"] is True


@pytest.mark.parametrize("model_output", [None, "", "not json"])
def test_model_failure_keeps_url_excerpt_and_review_state(monkeypatch, model_output):
    monkeypatch.setattr(url_parser.requests, "get", lambda *a, **k: response())
    monkeypatch.setattr("backend.lib.llm.chat_completion", lambda *a, **k: model_output)
    result = url_parser.parse_url_llm(URL)
    assert result.description_raw == url_parser.parse_url(URL, html=HTML).description_raw
    assert result.extra_fields["needs_manual_review"] is True
    assert not result.extra_fields.get("llm_enriched")
    assert "suggested_description" not in result.extra_fields


def test_empty_source_is_not_filled_with_model_prose():
    base = RawOpportunity(
        source="url_parser", source_url=URL, url=URL, title="Empty source", description_raw="", extra_fields={}
    )
    result = url_parser._merge_llm_into_base(base, {"description": "Model-only prose."})
    assert result.description_raw == ""
    assert result.extra_fields["suggested_description"] == "Model-only prose."
    assert result.extra_fields["needs_manual_review"] is True
