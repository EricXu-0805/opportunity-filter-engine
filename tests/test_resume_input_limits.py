"""Complete raw input is separate from the bounded experience projection.

No provider traffic: every test either disables configuration or replaces the
provider call. Tests exercise the HTTP boundary and production chunk scheduler.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest
from fastapi.testclient import TestClient

from backend.lib.blocking import BlockingWorkTimeout
from backend.lib.resume_input import (
    MAX_RESUME_TEXT_CHARACTERS,
    RESUME_AI_CHUNK_CHARACTERS,
    RESUME_AI_MAX_CHUNKS,
    resume_chunks,
)
from backend.main import app
from backend.routes import tailor
from backend.schemas import ProfileRequest, RenovateRequest

client = TestClient(app)


@pytest.fixture(autouse=True)
def local_provider_only(monkeypatch):
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    monkeypatch.setattr(tailor.llm_budget, "exhausted", lambda: False)
    monkeypatch.setattr(tailor, "chat_completion", lambda *_a, **_kw: None)


@pytest.mark.parametrize("text", [
    "文" * 60_000,
    "🧪" * 60_000,
    ("x" * 7_499 + "\n") * 8,
    "a short resume",
])
def test_chunks_cover_the_exact_source_with_bounded_calls(text):
    chunks = resume_chunks(text)
    assert "".join(chunk for _, _, chunk in chunks) == text
    assert len(chunks) <= RESUME_AI_MAX_CHUNKS
    assert all(0 < len(chunk) <= RESUME_AI_CHUNK_CHARACTERS for _, _, chunk in chunks)
    assert chunks[0][0] == 0 and chunks[-1][1] == len(text)
    assert all(a[1] == b[0] for a, b in zip(chunks, chunks[1:], strict=False))


@pytest.mark.parametrize("endpoint", ["extract-bullets", "structure"])
def test_accepts_60000_characters_and_retains_tail_in_local_result(endpoint):
    tail = "\n• Final page research evidence in the laboratory"
    text = "文" * (MAX_RESUME_TEXT_CHARACTERS - len(tail)) + tail
    response = client.post(f"/api/tailor/{endpoint}", json={"resume_text": text})
    assert response.status_code == 200
    body = response.json()
    bullets = body.get("bullets") or [b["text"] for s in body["sections"] for b in s["bullets"]]
    assert "Final page research evidence in the laboratory" in bullets
    assert body["processing"]["input_characters"] == 60_000
    assert body["processing"]["chunks"][-1]["end"] == 60_000
    assert body["processing"]["ai_chunks"] == 0
    assert "local_extraction_only" in body["warnings"]


@pytest.mark.parametrize("endpoint", ["extract-bullets", "structure"])
def test_rejects_oversize_input_before_any_model_call(endpoint, monkeypatch):
    calls = []
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "chat_completion", lambda *a, **k: calls.append(a))
    response = client.post(f"/api/tailor/{endpoint}", json={"resume_text": "🧪" * 60_001})
    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("endpoint", ["extract-bullets", "structure"])
def test_ai_sees_the_tail_and_never_gets_an_unbounded_prompt(endpoint, monkeypatch):
    text = "Earlier source. " * 1700 + "\nFinal page research evidence in the laboratory"
    prompts = []

    def completion(messages, **kwargs):
        prompt = messages[1]["content"]
        chunk = prompt.removeprefix("RESUME:\n").rsplit("\n\n", 1)[0]
        prompts.append(chunk)
        bullet = "Final page research evidence in the laboratory"
        items = [bullet] if bullet in chunk else []
        if endpoint == "extract-bullets":
            return json.dumps({"bullets": items})
        return json.dumps({"sections": [{"heading": "Research", "kind": "research", "bullets": items}]})

    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "chat_completion", completion)
    response = client.post(f"/api/tailor/{endpoint}", json={"resume_text": text})
    assert response.status_code == 200
    body = response.json()
    bullets = body.get("bullets") or [b["text"] for s in body["sections"] for b in s["bullets"]]
    assert "Final page research evidence in the laboratory" in bullets
    assert sorted(prompts) == sorted(chunk for _, _, chunk in resume_chunks(text))
    assert all(len(prompt) <= 8_000 for prompt in prompts)
    assert body["method"] == "mixed"
    assert body["processing"]["ai_chunks"] == 1
    assert "partial_ai_processing" in body["warnings"]


def test_one_failed_chunk_uses_local_tail_with_explicit_mixed_status(monkeypatch):
    first = "Built the first laboratory experiment"
    last = "Built the final laboratory experiment"
    text = first + "\n" + "x" * 7_970 + "\n• " + last
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "chat_completion", lambda messages, **_kw:
                        json.dumps({"bullets": [first]}) if first in messages[1]["content"] else None)
    body = client.post("/api/tailor/extract-bullets", json={"resume_text": text}).json()
    assert body["bullets"] == [first, last]
    assert body["method"] == "mixed"
    assert body["processing"]["chunks"][-1]["reason"] == "invalid_output"


def test_extraction_selection_shares_twelve_slots_with_later_chunks():
    groups = [[f"Chunk {i} bullet {j} with original evidence" for j in range(12)] for i in range(8)]
    bullets, limited = tailor._select_bullets_across_chunks(groups)
    assert len(bullets) == 12 and limited
    assert all(any(f"Chunk {i} bullet" in bullet for bullet in bullets) for i in range(8))
    assert bullets == sorted(bullets)


def test_structure_merges_chunk_ids_into_a_valid_renovation_tree_and_keeps_tail(monkeypatch):
    # One labelled experience per source chunk; every model call starts with
    # the same local s1/b1 identity before the route merges the result.
    text = "\n".join((f"Evidence from page {i} for research\n" + "x" * 7_600) for i in range(7))

    def completion(messages, **kwargs):
        chunk = messages[1]["content"]
        bullets = [line for line in chunk.splitlines() if line.startswith("Evidence from page")]
        return json.dumps({"sections": [{"heading": "Research", "kind": "research", "bullets": bullets}]})

    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "chat_completion", completion)
    response = client.post("/api/tailor/structure", json={"resume_text": text})
    assert response.status_code == 200
    body = response.json()
    tree = RenovateRequest(profile=ProfileRequest(), opportunity_id="local-test", sections=body["sections"])
    bullets = [b for s in tree.sections for b in s.bullets]
    assert any("page 6" in b.text for b in bullets)
    assert len({b.id for b in bullets}) == len(bullets)
    assert "selected_bullets_only" in body["warnings"]


def test_chunk_scheduler_shares_one_deadline_and_never_exceeds_two_calls(monkeypatch):
    state = {"active": 0, "peak": 0, "calls": 0}
    timeouts = []

    async def slow_call(_fn, _text, *, timeout_seconds, **kwargs):
        state["active"] += 1
        state["calls"] += 1
        state["peak"] = max(state["peak"], state["active"])
        timeouts.append(timeout_seconds)
        try:
            # Each first pair runs beyond the shared deadline. No subsequent
            # chunk can receive a fresh per-chunk 45-second budget.
            await asyncio.sleep(timeout_seconds)
            raise BlockingWorkTimeout("test timeout")
        finally:
            state["active"] -= 1

    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "run_blocking", slow_call)
    monkeypatch.setattr(tailor, "RESUME_AI_TIME_BUDGET_SECONDS", 0.02)
    results, coverage = asyncio.run(tailor._process_resume_chunks("x" * 60_000, lambda _: None))
    assert state == {"active": 0, "peak": 2, "calls": 2}
    assert all(0 < timeout <= 0.02 for timeout in timeouts)
    assert results == [None] * 8
    assert coverage.heuristic_chunks == 8
    assert [c.reason for c in coverage.chunks[:2]] == ["timeout_or_busy"] * 2
    assert all(c.reason == "not_attempted_within_budget" for c in coverage.chunks[2:])


def test_no_provider_never_schedules_blocking_work(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("no provider must not schedule calls")

    monkeypatch.setattr(tailor, "run_blocking", forbidden)
    results, coverage = asyncio.run(tailor._process_resume_chunks("x" * 60_000, lambda _: None))
    assert results == [None] * 8
    assert all(c.reason == "llm_not_configured" for c in coverage.chunks)


def test_budget_exhaustion_stops_new_chunks_and_marks_every_omitted_ai_range(monkeypatch):
    calls = []

    async def first_call(_fn, text, *, timeout_seconds, **kwargs):
        calls.append(text)
        return ["Existing grounded evidence"]

    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "run_blocking", first_call)
    monkeypatch.setattr(tailor.llm_budget, "exhausted", lambda: bool(calls))
    results, coverage = asyncio.run(tailor._process_resume_chunks("x" * 60_000, lambda _: None))
    assert len(calls) == 1
    assert results[0] == ["Existing grounded evidence"]
    assert results[1:] == [None] * 7
    assert coverage.ai_chunks == 1 and coverage.heuristic_chunks == 7
    assert all(c.reason == "daily_budget_exhausted" for c in coverage.chunks[1:])


def test_exhausted_budget_never_dispatches_even_the_first_chunk(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("budget is already exhausted")

    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "run_blocking", forbidden)
    monkeypatch.setattr(tailor.llm_budget, "exhausted", lambda: True)
    results, coverage = asyncio.run(tailor._process_resume_chunks("x" * 60_000, lambda _: None))
    assert results == [None] * 8
    assert all(c.reason == "daily_budget_exhausted" for c in coverage.chunks)


def test_each_chunk_and_provider_retry_uses_the_existing_attempt_counter(monkeypatch):
    # Exercise the real provider wrapper with an in-memory SDK. The fake SDK
    # has no network transport; the assertion binds route fan-out to the
    # existing per-attempt accounting rather than a per-request mock.
    from backend.lib import llm

    calls = []
    spends = []
    sdk_options = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("one controlled retry")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=json.dumps({"bullets": ["x" * 20]})),
        )])

    def sdk(**kwargs):
        sdk_options.append(kwargs)
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=sdk))
    monkeypatch.setattr(llm, "_resolve", lambda _provider=None: types.SimpleNamespace(
        pid="local-test", api_key="unused-test-key", base_url="", model="test-model",
    ))
    monkeypatch.setattr(llm, "_RETRY_BASE_DELAY_SECONDS", 0)
    monkeypatch.setattr(llm.llm_budget, "spend", lambda calls=1: spends.append(calls))
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "chat_completion", llm.chat_completion)
    body = client.post("/api/tailor/extract-bullets", json={"resume_text": "x" * 60_000}).json()
    assert body["processing"]["ai_chunks"] == 8
    assert len(calls) == sum(spends) == 9  # eight chunks plus one provider retry
    assert all(options["max_retries"] == 0 for options in sdk_options)
