"""Async AI routes must not starve process liveness.

Each fake blocking model call waits on a gate for up to 400ms.  With correct
executor isolation, ``/api/health`` responds promptly while the gate is held;
if a route calls the fake directly on the event loop, the probe is delayed for
the full 400ms and the regression fails.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from backend import data_loader
from backend.lib import blocking
from backend.lib.blocking import BlockingWorkOverloaded, BlockingWorkTimeout, run_blocking
from backend.main import app
from backend.routes import cold_email, import_text, import_url, matches, opportunities, tailor


@pytest.fixture
def profile() -> dict:
    return {
        "name": "Test Student",
        "school": "UIUC",
        "home_school": "uiuc",
        "year": "junior",
        "major": "Computer Science",
        "college": "Grainger College of Engineering",
        "hard_skills": [{"name": "Python", "level": "experienced"}],
        "coursework": ["CS 124"],
        "research_interests_text": "machine learning systems",
    }


@pytest.fixture
def opportunity_id() -> str:
    return data_loader.load_opportunities()[0]["id"]


class _Gate:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()


def _gated(callback: Callable):
    gate = _Gate()

    def wrapped(*args, **kwargs):
        gate.started.set()
        gate.release.wait(0.4)
        gate.finished.set()
        return callback(*args, **kwargs)

    return wrapped, gate


async def _probe_health(client: httpx.AsyncClient, gate: _Gate, path: str) -> None:
    """While the gated call is still in flight, /api/health must answer."""
    # Generous: the route may pay a one-time corpus load before the gated call.
    deadline = time.perf_counter() + 10.0
    while not gate.started.is_set() and time.perf_counter() < deadline:
        await asyncio.sleep(0.005)
    assert gate.started.is_set(), f"blocking call was not reached for {path}"
    probe_began = time.perf_counter()
    live = await client.get("/api/health")
    probe_elapsed = time.perf_counter() - probe_began
    assert live.status_code == 200
    assert probe_elapsed < 0.25, f"{path} blocked the event loop for {probe_elapsed:.3f}s"
    # The gate is held for 400ms: a health response that only got through after
    # the gated call ended means the event loop was blocked the whole time.
    assert not gate.finished.is_set(), (
        f"{path}: /api/health only answered after the blocking call finished"
    )


async def _probe_live(path: str, payload: dict, gate: _Gate):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        request_task = asyncio.create_task(client.post(path, json=payload))
        try:
            await _probe_health(client, gate, path)
        finally:
            gate.release.set()
        response = await request_task
        assert response.status_code == 200, response.text
        return response


def _run_probe(path: str, payload: dict, gate: _Gate):
    return asyncio.run(_probe_live(path, payload, gate))


def _post(path: str, payload: dict):
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=payload)

    return asyncio.run(request())


def test_import_text_does_not_block_live(monkeypatch):
    fake, gate = _gated(lambda _text: None)
    monkeypatch.setattr(import_text, "parse_text_llm", fake)
    response = _run_probe(
        "/api/import-text",
        {"text": "A sufficiently detailed pasted opportunity description. " * 3},
        gate,
    )
    assert response.json()["ok"] is False


def test_import_url_does_not_block_live(monkeypatch):
    fake, gate = _gated(lambda _url: None)
    monkeypatch.setattr(import_url, "parse_url_llm", fake)
    response = _run_probe(
        "/api/import-url",
        {"url": "https://example.com/opportunity"},
        gate,
    )
    assert response.json()["ok"] is False


def _fake_matches_corpus(monkeypatch, opportunity_id: str) -> list[dict]:
    """A one-opportunity corpus for BOTH loaders the /matches route touches.

    Deliberately hermetic: the real ``load_opportunities_by_id`` parses the
    full multi-hundred-MB corpus, and the route calls it on the event loop —
    on a cold CI runner that alone can outlast the probe window before the
    gated call is ever reached.
    """
    opp = {
        "id": opportunity_id,
        "title": "Threaded rerank opportunity",
        "organization": "Example Lab",
        "opportunity_type": "research",
        "audience": "open",
        "school": "uiuc",
        "on_campus": True,
        "paid": "unknown",
        "eligibility": {},
        "application": {},
        "metadata": {"is_active": True},
    }
    corpus = [opp]
    monkeypatch.setattr(
        matches,
        "load_opportunities_generation",
        lambda: (corpus, "async-test-generation"),
    )
    monkeypatch.setattr(
        matches,
        "registered_corpus_identity_nowait",
        lambda: id(corpus),
    )
    monkeypatch.setattr(
        matches,
        "registered_corpus_identity",
        lambda: id(corpus),
    )
    monkeypatch.setattr(matches, "load_opportunities_by_id", lambda: {opp["id"]: opp})
    return corpus


def test_match_cache_hit_does_not_block_live_while_scorer_holds_generation_lock(
    monkeypatch,
    profile,
):
    from src.matcher.ranker import RankedMatchUniverse

    _fake_matches_corpus(monkeypatch, "threaded-rule-score")
    fake, gate = _gated(
        lambda *_args, **_kwargs: RankedMatchUniverse(
            visible=[],
            buckets={
                "high_priority": 0,
                "good_match": 0,
                "reach": 0,
                "low_fit": 0,
            },
            field_relevant_count=0,
        )
    )
    monkeypatch.setattr(matches, "rank_visible_universe", fake)
    matches._match_snapshots.clear()

    async def probe_two_requests():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = asyncio.create_task(client.post("/api/matches", json=profile))
            deadline = time.perf_counter() + 2
            while not gate.started.is_set() and time.perf_counter() < deadline:
                await asyncio.sleep(0.005)
            assert gate.started.is_set()

            second_profile = {**profile, "coursework": ["CS 225"]}
            second = asyncio.create_task(
                client.post("/api/matches", json=second_profile)
            )
            await asyncio.sleep(0.01)
            began = time.perf_counter()
            live = await client.get("/api/health")
            elapsed = time.perf_counter() - began
            assert live.status_code == 200
            assert elapsed < 0.25
            assert not gate.finished.is_set()
            gate.release.set()
            first_response, second_response = await asyncio.gather(first, second)
            assert first_response.status_code == 200
            assert second_response.status_code == 200

    asyncio.run(probe_two_requests())


def test_matches_llm_rerank_does_not_block_live(monkeypatch, profile):
    fake, gate = _gated(
        lambda _profile, results, _lookup: results
    )
    _fake_matches_corpus(monkeypatch, "threaded-rerank")
    monkeypatch.setattr(matches, "llm_rerank", fake)
    response = _run_probe(
            "/api/matches?limit=1&llm=true",
        profile,
        gate,
    )
    assert "results" in response.json()


def test_match_explain_llm_does_not_block_live(monkeypatch, profile, opportunity_id):
    fake, gate = _gated(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(matches, "_llm_explanation", fake)
    response = _run_probe(
        f"/api/matches/{opportunity_id}/explain?llm=true",
        profile,
        gate,
    )
    assert response.json()["method"] == "local"


def test_opportunity_chat_does_not_block_live(monkeypatch, opportunity_id):
    fake, gate = _gated(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(opportunities, "_llm_chat_call", fake)
    response = _run_probe(
        f"/api/opportunities/{opportunity_id}/chat",
        {"message": "Is this opportunity paid?"},
        gate,
    )
    assert response.json()["method"] == "local"


@pytest.mark.parametrize("path", ["/api/cold-email", "/api/cold-email/stream"])
def test_cold_email_generation_paths_do_not_block_live(
    monkeypatch,
    profile,
    opportunity_id,
    path,
):
    fake, gate = _gated(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cold_email, "is_configured", lambda: True)
    monkeypatch.setattr(cold_email, "_pipeline_generate", fake)
    response = _run_probe(
        path,
        {"profile": profile, "opportunity_id": opportunity_id, "engine": "ai"},
        gate,
    )
    assert response.text


def test_cold_email_variants_do_not_block_live(monkeypatch, profile, opportunity_id):
    original = cold_email.generate_variants
    fake, gate = _gated(original)
    monkeypatch.setattr(cold_email, "generate_variants", fake)
    response = _run_probe(
        "/api/cold-email/variants",
        {"profile": profile, "opportunity_id": opportunity_id},
        gate,
    )
    assert response.json()["variants"]


def test_cold_email_refine_does_not_block_live(monkeypatch):
    fake, gate = _gated(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cold_email, "is_configured", lambda: True)
    monkeypatch.setattr(cold_email, "chat_completion", fake)
    response = _run_probe(
        "/api/cold-email/refine",
        {"current_body": "Dear Professor,\nHello.\nBest,\nStudent", "instruction": "concise"},
        gate,
    )
    assert response.json()["method"] == "local"


def test_tailor_extract_does_not_block_live(monkeypatch):
    fake, gate = _gated(lambda _text: None)
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "_ai_extract_bullets", fake)
    response = _run_probe(
        "/api/tailor/extract-bullets",
        {"resume_text": "- Built a Python research prototype for a class project"},
        gate,
    )
    assert response.json()["method"] == "heuristic"


def test_tailor_main_does_not_block_live(monkeypatch, profile, opportunity_id):
    fake, gate = _gated(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "_ai_tailor_bullets", fake)
    response = _run_probe(
        "/api/tailor",
        {
            "profile": profile,
            "opportunity_id": opportunity_id,
            "original_bullets": ["Built a Python research prototype"],
        },
        gate,
    )
    assert response.json()["method"] == "fallback"


def test_tailor_structure_does_not_block_live(monkeypatch):
    fake, gate = _gated(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "_ai_structure_resume", fake)
    response = _run_probe(
        "/api/tailor/structure",
        {"resume_text": "- Built a Python research prototype for a class project"},
        gate,
    )
    assert response.json()["method"] == "heuristic"


def test_tailor_renovate_does_not_block_live(monkeypatch, profile, opportunity_id):
    fake, gate = _gated(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "_ai_renovation_plan", fake)
    response = _run_probe(
        "/api/tailor/renovate",
        {
            "profile": profile,
            "opportunity_id": opportunity_id,
            "sections": [
                {
                    "id": "s1",
                    "heading": "Projects",
                    "kind": "projects",
                    "bullets": [{"id": "s1b1", "text": "Built a Python research prototype"}],
                }
            ],
        },
        gate,
    )
    assert response.json()["method"] == "fallback"


def test_tailor_bullet_does_not_block_live(monkeypatch, profile, opportunity_id):
    fake, gate = _gated(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "_ai_optimize_bullet", fake)
    response = _run_probe(
        "/api/tailor/bullet",
        {
            "profile": profile,
            "opportunity_id": opportunity_id,
            "current_text": "Built a Python research prototype",
            "base_text": "Built a Python research prototype",
        },
        gate,
    )
    assert response.json()["changed"] is False


def test_blocking_bridge_enforces_outer_timeout():
    async def exercise():
        with pytest.raises(BlockingWorkTimeout):
            await run_blocking(time.sleep, 0.1, timeout_seconds=0.01)

    asyncio.run(exercise())


def test_blocking_bridge_rejects_an_unbounded_queue(monkeypatch):
    executor = ThreadPoolExecutor(max_workers=1)
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(blocking, "_BLOCKING_AI_EXECUTOR", executor)
    monkeypatch.setattr(blocking, "_BLOCKING_AI_CAPACITY", capacity)
    started = threading.Event()
    release = threading.Event()

    def occupied():
        started.set()
        release.wait(1.0)
        return "done"

    async def exercise():
        first = asyncio.create_task(blocking.run_blocking(occupied, timeout_seconds=1.0))
        while not started.is_set():
            await asyncio.sleep(0.001)
        with pytest.raises(BlockingWorkOverloaded):
            await blocking.run_blocking(lambda: "must not queue", timeout_seconds=1.0)
        release.set()
        assert await first == "done"
        # The underlying future callback, rather than the caller's timeout,
        # releases capacity for a subsequent request.
        assert await blocking.run_blocking(lambda: "next", timeout_seconds=1.0) == "next"

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        executor.shutdown(wait=True)


@pytest.mark.parametrize(
    "error",
    [
        BlockingWorkOverloaded("queue full"),
        BlockingWorkTimeout("deadline exceeded"),
    ],
)
def test_rerank_pool_rejection_serves_rule_order(monkeypatch, profile, error):
    async def reject(*_args, **_kwargs):
        raise error

    _fake_matches_corpus(monkeypatch, "rule-order-floor")
    monkeypatch.setattr(matches, "run_blocking", reject)
    response = _post("/api/matches?limit=1", profile)

    assert response.status_code == 200
    assert "results" in response.json()


def test_cold_email_timeout_preserves_template_fallback(
    monkeypatch,
    profile,
    opportunity_id,
):
    monkeypatch.setattr(cold_email, "is_configured", lambda: True)
    monkeypatch.setattr(cold_email, "MULTI_LLM_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        cold_email,
        "_pipeline_generate",
        lambda *_args, **_kwargs: time.sleep(0.05) or None,
    )
    response = _post(
        "/api/cold-email",
        {"profile": profile, "opportunity_id": opportunity_id, "engine": "ai"},
    )
    assert response.status_code == 200
    assert response.json()["method"] == "template"
    assert response.json()["fallback_reason"] == "unavailable"


def test_tailor_timeout_preserves_passthrough_fallback(
    monkeypatch,
    profile,
    opportunity_id,
):
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "SINGLE_LLM_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        tailor,
        "_ai_tailor_bullets",
        lambda *_args, **_kwargs: time.sleep(0.05) or None,
    )
    original = "Built a Python research prototype"
    response = _post(
        "/api/tailor",
        {
            "profile": profile,
            "opportunity_id": opportunity_id,
            "original_bullets": [original],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "fallback"
    assert body["tailored_bullets"][0]["text"] == original
