"""Whole and selected refinement share explicit limits, never partial input."""
import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import cold_email as ce
from tests.experience_fixtures import confirmed_experience
from tests.test_cold_email_selection_refine import OPP, PROFILE, body, selected

LIMITS = {"current_body": 5000, "instruction": 500, "subject": 2000}


@pytest.fixture
def environment(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: deepcopy(OPP)})
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    calls = []

    def provider(messages, **kwargs):
        calls.append((messages, kwargs))
        return body("I am interested in Python parser research.")

    monkeypatch.setattr(ce, "chat_completion", provider)
    return TestClient(app), calls


def payload(**updates):
    return {"profile": PROFILE, "opportunity_id": OPP["id"], "current_body": body(),
            "instruction": "Make this clearer.", "subject": "Research inquiry", **updates}


def post(environment, value):
    return environment[0].post("/api/cold-email/refine", content=json.dumps(value),
                               headers={"Content-Type": "application/json"})


def editing_inputs(calls):
    return json.loads(calls[0][0][1]["content"].split("Editing inputs (not evidence):\n", 1)[1])


def test_provider_gets_complete_body_fact_after_3000_and_complete_instruction(environment):
    claim = "I wrote parser tests."
    whole = body("Plain context. " * 220 + "\r\n\r\n" + claim + "\n中文😀 e\u0301")
    instruction = "  Keep this context. " * 19 + "\r\nFINAL_REQUIREMENT_完整\t"
    assert 3000 < len(whole) < 5000 and 300 < len(instruction) < 500
    response = post(environment, payload(current_body=whole, instruction=instruction,
                                        experience_evidence=confirmed_experience([claim])))
    assert response.status_code == 200, response.text
    inputs = editing_inputs(environment[1])
    assert inputs == {"current_body": whole, "instruction": instruction, "subject": "Research inquiry"}
    assert "editing inputs" in environment[1][0][0][0]["content"]
    assert "NOT new factual evidence" in environment[1][0][0][0]["content"]


@pytest.mark.parametrize("scope", ["whole", "selection"])
@pytest.mark.parametrize("field,limit", LIMITS.items())
@pytest.mark.parametrize("character", ["x", "😀"])
def test_over_limit_is_structured_422_before_provider(environment, scope, field, limit, character):
    value = payload()
    if scope == "selection":
        value["selection"] = selected("Python", value["current_body"])
    value[field] = character * (limit // (2 if character == "😀" else 1) + 1)
    response = post(environment, value)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "code": "EMAIL_REFINE_LIMIT", "field": field, "max_utf16": limit,
        "message": f"{field} must be at most {limit} UTF-16 code units.",
    }
    assert environment[1] == []
    assert value[field] not in response.text


@pytest.mark.parametrize("field,limit", LIMITS.items())
@pytest.mark.parametrize("character", ["x", "😀"])
def test_exact_utf16_limit_reaches_provider_unchanged(environment, field, limit, character):
    text = character * (limit // (2 if character == "😀" else 1))
    response = post(environment, payload(**{field: text}))
    assert response.status_code == 200, response.text
    assert editing_inputs(environment[1])[field] == text


@pytest.mark.parametrize("field", LIMITS)
@pytest.mark.parametrize("invalid", ["PRIVATE\x00TEXT", "PRIVATE\ud800TEXT"])
def test_unsafe_unicode_or_nul_is_rejected_without_private_echo(environment, field, invalid):
    response = post(environment, payload(**{field: invalid}))
    assert response.status_code == 422, response.text
    assert environment[1] == []
    assert "PRIVATE" not in response.text
    assert all("input" not in error for error in response.json()["detail"])


@pytest.mark.parametrize("field", ["current_body", "instruction"])
@pytest.mark.parametrize("mode", ["missing", "null"])
def test_legacy_required_text_fields_remain_required(environment, field, mode):
    value = payload()
    if mode == "missing":
        value.pop(field)
    else:
        value[field] = None
    assert post(environment, value).status_code == 422
    assert environment[1] == []


def test_whole_legacy_empty_text_optional_profile_subject_and_extra_keys_remain_compatible(environment):
    value = {"opportunity_id": OPP["id"], "current_body": "", "instruction": "", "old_extra": "ignored"}
    response = post(environment, value)
    assert response.status_code == 200, response.text
    assert editing_inputs(environment[1]) == {"current_body": "", "instruction": "", "subject": ""}


def test_local_quick_rules_use_complete_instruction_and_body(environment, monkeypatch):
    monkeypatch.setattr(ce, "is_configured", lambda: False)
    whole = body("Plain context. " * 220 + "\nI would love to discuss Python parser research.")
    instruction = "Please preserve all details. " * 16 + "make it formal"
    assert 3000 < len(whole) < 5000 and 300 < len(instruction) < 500
    response = post(environment, payload(current_body=whole, instruction=instruction))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["method"] == "local" and result["applied"] == ["formal"]
    assert "Plain context. " * 220 in result["body"]
    assert "I would greatly appreciate to discuss Python parser research." in result["body"]
    assert "Audit Student" in result["body"]
    assert environment[1] == []


def test_complete_inputs_preserve_existing_email_redaction(environment):
    response = post(environment, payload(current_body=body("Write to hidden@example.edu."),
                                        instruction="Use hidden@example.edu as the contact.",
                                        subject="Contact hidden@example.edu"))
    assert response.status_code == 200, response.text
    inputs = editing_inputs(environment[1])
    assert all("hidden@example.edu" not in value for value in inputs.values())


@pytest.mark.parametrize("scope", ["whole", "selection"])
@pytest.mark.parametrize("reason", ["stop", "length"])
def test_routes_opt_into_complete_sdk_output_without_retry(environment, monkeypatch, scope, reason):
    from types import SimpleNamespace

    import openai

    from backend.lib import llm

    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-key")
    replacement = "I would welcome a conversation about Python parser research."
    content = body(replacement) if scope == "whole" else json.dumps({"replacement": replacement})
    calls, spends = [], []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=reason,
                                                        message=SimpleNamespace(content=content))])

    monkeypatch.setattr(openai, "OpenAI", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(llm.llm_budget, "spend", lambda: spends.append(True))
    monkeypatch.setattr(llm.time, "sleep", lambda *_: pytest.fail("A completed provider response must not be retried"))
    monkeypatch.setattr(ce, "chat_completion", llm.chat_completion)
    value = payload()
    if scope == "selection":
        value["selection"] = selected("I am interested in Python parser research.", value["current_body"])
    response = post(environment, value)
    assert response.status_code == 200, response.text
    result = response.json()
    if scope == "whole":
        assert calls[0]["max_tokens"] == 6000
        assert result["method"] == ("llm" if reason == "stop" else "local")
        assert (replacement in result["body"]) is (reason == "stop")
    else:
        assert result["outcome"] == ("proposal" if reason == "stop" else "no_change")
        if reason != "stop":
            assert result["reason"] == "provider_unavailable" and "proposal" not in result
    assert len(calls) == len(spends) == 1
