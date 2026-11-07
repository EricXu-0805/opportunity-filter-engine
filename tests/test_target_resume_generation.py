"""No provider traffic: the opt-in full-target generation version and what it identifies."""
import re
from pathlib import Path

import pytest

from backend.lib import (
    evidence_map,
    llm,
    target_resume_ai,
    target_resume_ai_grounding,
    target_resume_ai_schema,
    target_resume_output_budget,
    target_resume_plan,
    target_resume_plan_schema,
)
from backend.lib.target_resume_generation import VERSION_PATTERN, generation_version
from backend.routes import target_resume_ai as route
from tests import test_target_resume_ai as suggestion_tests
from tests import test_target_resume_plan as plan_tests

endpoint = suggestion_tests.endpoint
plan_endpoint = plan_tests.endpoint


@pytest.fixture(autouse=True)
def model_config(monkeypatch):
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "OFE_STRONG_MODEL",
                "OFE_MODEL_TAILOR", "OFE_MODEL_TAILOR_REVIEW", "OFE_MODEL_COLD_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key-a")
    monkeypatch.setenv("OFE_MODEL_TAILOR", "test/writer-a")
    monkeypatch.setenv("OFE_MODEL_TAILOR_REVIEW", "test/reviewer-a")


def _post(kind, request, **extra):
    # Both fixtures patch the same opportunity loader, so only one is set up per test.
    if kind == "suggestions":
        client, doc, _, _ = request.getfixturevalue("endpoint")
        return client.post(suggestion_tests.PATH, json={**suggestion_tests.payload(doc), **extra})
    plan = request.getfixturevalue("plan_endpoint")
    return plan.client.post(plan_tests.PATH, json={**plan_tests.payload(plan.doc()), **extra})


@pytest.mark.parametrize("kind", ["suggestions", "plan"])
def test_version_is_returned_only_when_asked(request, kind):
    legacy = _post(kind, request)
    assert legacy.status_code == 200, legacy.text
    assert "generation_version" not in legacy.json()
    asked = _post(kind, request, include_generation_version=True)
    assert asked.status_code == 200, asked.text
    assert asked.json()["generation_version"] == generation_version()
    assert re.fullmatch(VERSION_PATTERN, asked.json()["generation_version"])
    assert "synthetic-key-a" not in asked.text and "writer-a" not in asked.text
    assert set(asked.json()) - set(legacy.json()) == {"generation_version"}


@pytest.mark.parametrize("kind", ["suggestions", "plan"])
def test_asking_only_for_the_check_version_returns_no_generation_version(request, kind):
    # What the browser live today sends; its strict check refuses a response key it does not know.
    result = _post(kind, request, include_check_version=True)
    assert result.status_code == 200, result.text
    assert "check_version" in result.json() and "generation_version" not in result.json()


@pytest.mark.parametrize("kind", ["suggestions", "plan"])
def test_version_comes_back_when_no_model_ran(request, monkeypatch, kind):
    request.getfixturevalue("endpoint" if kind == "suggestions" else "plan_endpoint")
    monkeypatch.setattr(route, "is_configured", lambda: False)
    result = _post(kind, request, include_generation_version=True)
    assert result.status_code == 200 and result.json()["method"] == "unavailable"
    assert result.json()["generation_version"] == generation_version()
    # Unasked, it stays out of the answer: today's browser refuses a key it does not know.
    unasked = _post(kind, request)
    assert unasked.status_code == 200 and unasked.json()["method"] == "unavailable"
    assert "generation_version" not in unasked.json()


@pytest.mark.parametrize("kind", ["suggestions", "plan"])
@pytest.mark.parametrize("value", ["true", 1, None])
def test_flag_is_a_strict_boolean_and_the_version_is_server_owned(request, kind, value):
    assert _post(kind, request, include_generation_version=value).status_code == 422
    forged = _post(kind, request, generation_version="target-resume-generation-v1:" + "a" * 64)
    assert forged.status_code == 422


@pytest.mark.parametrize("key,value", [
    ("OFE_MODEL_TAILOR", "test/writer-b"),
    ("OFE_MODEL_TAILOR_REVIEW", "test/reviewer-b"),
    ("OPENROUTER_API_KEY", ""),
])
def test_writer_and_reviewer_routes_change_the_version(monkeypatch, key, value):
    before = generation_version()
    monkeypatch.setenv(key, value)
    assert generation_version() != before


def test_fallback_provider_and_model_change_the_version(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-b")
    openai_default = generation_version()
    monkeypatch.setenv("OFE_STRONG_MODEL", "test/fallback-model")
    assert generation_version() != openai_default
    monkeypatch.delenv("OFE_STRONG_MODEL")
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key-c")
    gemini_default = generation_version()
    assert gemini_default != openai_default
    monkeypatch.delenv("GEMINI_API_KEY")
    unconfigured = generation_version()
    assert unconfigured not in (openai_default, gemini_default) and re.fullmatch(VERSION_PATTERN, unconfigured)


def test_the_same_model_name_on_another_provider_is_another_route(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OFE_STRONG_MODEL", "test/shared-name")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-b")
    on_openai = generation_version()
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key-c")
    assert generation_version() != on_openai


def test_the_fallback_providers_default_model_is_part_of_the_route(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-b")
    before = generation_version()
    monkeypatch.setattr(llm, "_PROVIDERS", tuple(
        (pid, env, url, "test/new-default" if pid == "openai" else model) for pid, env, url, model in llm._PROVIDERS))
    assert generation_version() != before


def test_credentials_and_unrelated_settings_do_not_change_the_version(monkeypatch):
    before = generation_version()
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key-rotated")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-unused")
    monkeypatch.setenv("OFE_STRONG_MODEL", "test/unused-fallback")
    monkeypatch.setenv("OFE_MODEL_COLD_EMAIL", "test/unrelated")
    assert generation_version() == before


@pytest.mark.parametrize("module,attribute", [
    (target_resume_ai, "SYSTEM_PROMPT"),
    (target_resume_plan, "SYSTEM_PROMPT"),
    (evidence_map, "REVIEW_SYSTEM_PROMPT"),
    (target_resume_ai_schema, "PIPELINE_VERSION"),
    (target_resume_plan_schema, "PIPELINE_VERSION"),
    (target_resume_ai_grounding, "SOURCE_CHECK_VERSION"),
])
def test_prompts_and_declared_versions_change_the_version(monkeypatch, module, attribute):
    before = generation_version()
    monkeypatch.setattr(module, attribute, getattr(module, attribute) + " changed")
    assert generation_version() != before


def test_output_budget_policy_changes_the_version(monkeypatch):
    before = generation_version()
    policy = {**target_resume_output_budget.OUTPUT_BUDGET_POLICY}
    policy["max_tokens"] += 1
    monkeypatch.setattr(target_resume_output_budget, "OUTPUT_BUDGET_POLICY", policy)
    assert generation_version() != before


def test_browser_checks_the_same_version_format():
    protocol = (Path(__file__).parents[1] / "frontend/src/lib/target-resume-ai-protocol.ts").read_text()
    browser = re.search(r"export const TARGET_RESUME_GENERATION_VERSION_PATTERN = /(.+)/;", protocol)[1]
    assert browser == VERSION_PATTERN
