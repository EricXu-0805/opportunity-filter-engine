"""What the writing routes run before any worker stays off the event loop or bounded (criterion 4, round 1).

scripts/request_parse_lag.py and scripts/plan_output_lag.py measure the event-loop stall these
paths cause at the body limits; these tests pin the behaviour that keeps it under 0.25 s.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.lib import request_body
from backend.lib import target_resume_plan as plan
from backend.lib.target_resume_ai_validation import InvalidTargetResume
from backend.main import app
from backend.routes import target_resume_ai as route
from tests import test_target_resume_plan as plan_tests
from tests.test_target_resume_plan import endpoint  # noqa: F401

HEAVY = [[]] * (request_body.MAX_JSON_CONTAINERS + 1)
# Containers in chains 99 deep: at the container bound with few commas (a list of siblings needs one per item).
CHAINS = [json.loads("[" * 98 + "0" + "]" * 98)] * ((request_body.MAX_JSON_CONTAINERS - 200) // 99)
ITEMS = [0] * (request_body.MAX_JSON_SEPARATORS + 1)


def on_the_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True
TAILOR = {"profile": {"name": "Sample Student"}, "opportunity_id": "no-such-target", "locale": "en"}
SIGNATURE = "v1:sha256:" + "0" * 64
FULL = {"version": 1, "request_id": "probe", "locale": "en", "document_signature": SIGNATURE}


@pytest.fixture
def parsed(monkeypatch):
    """Paths whose JSON body Starlette parsed."""
    seen, real = [], Request.json

    async def recording(self):
        seen.append(self.url.path)
        return await real(self)

    monkeypatch.setattr(Request, "json", recording)
    return seen


@pytest.mark.parametrize(("path", "extra"), [
    ("/api/tailor", {"original_bullets": ["Built a robot."]}),
    ("/api/tailor/bullet", {"current_text": "Built a robot."}),
    ("/api/tailor/renovate", {"sections": []}),
])
def test_a_container_heavy_writing_request_is_refused_unparsed(parsed, path, extra):
    response = TestClient(app).post(path, json={**TAILOR, **extra, "padding": HEAVY})
    assert response.status_code == 422 and parsed == []
    assert response.json()["detail"] == [{"type": "too_long", "loc": ["body"], "msg": "Request input is invalid."}]


@pytest.mark.parametrize(("path", "extra"), [
    ("/api/tailor/full-target/suggestions", {"selected_unit_ids": ["line-1"]}),
    ("/api/tailor/full-target/selection-plan", {"options": {"target_pages": 1}}),
])
def test_a_container_heavy_full_target_request_is_refused_unparsed_and_private(parsed, path, extra):
    response = TestClient(app).post(path, json={**FULL, **extra, "draft": {"kind": "full_resume", "junk": HEAVY}})
    assert (response.status_code, response.json(), parsed) == (422, {"detail": {"code": "invalid_request"}}, [])
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("padding", [CHAINS, [0] * (request_body.MAX_JSON_SEPARATORS - 20)],
                         ids=["containers-at-the-bound", "items-at-the-bound"])
def test_a_body_at_the_bound_is_parsed_and_answered_as_before(parsed, padding):
    response = TestClient(app).post("/api/tailor", json={**TAILOR, "original_bullets": ["Built a robot."],
                                                        "padding": padding})
    assert response.status_code == 404 and parsed == ["/api/tailor"]


@pytest.mark.parametrize(("path", "body"), [
    ("/api/tailor", {**TAILOR, "original_bullets": ["Built a robot."], "padding": ITEMS}),
    ("/api/tailor/full-target/suggestions", {**FULL, "selected_unit_ids": ["line-1"],
                                             "draft": {"kind": "full_resume", "junk": ITEMS}}),
    ("/api/tailor/full-target/selection-plan", {**FULL, "options": {"target_pages": 1},
                                                "draft": {"kind": "full_resume", "junk": ITEMS}}),
], ids=["tailor", "full-target", "selection-plan"])
def test_an_item_heavy_body_is_refused_unparsed(parsed, path, body):
    """Four 2 MiB bodies of ints sent at once held the loop 0.30-0.39 s (round-2 review, criterion 4)."""
    response = TestClient(app).post(path, json=body)
    assert response.status_code == 422 and parsed == []


@pytest.mark.parametrize(("path", "extra"), [
    ("/api/tailor/full-target/suggestions", {"selected_unit_ids": ["line-1"]}),
    ("/api/tailor/full-target/selection-plan", {"options": {"target_pages": 1}}),
])
def test_the_draft_is_validated_on_a_thread(monkeypatch, path, extra):
    """A 2 MiB draft's canonical walk and deepcopy took up to 2.25 s on the event loop."""
    threads = []

    def validate(value):
        threads.append(on_the_event_loop())
        raise InvalidTargetResume("invalid_document")

    monkeypatch.setattr(route, "validate_document", validate)
    response = TestClient(app).post(path, json={**FULL, **extra, "draft": {"kind": "full_resume"}})
    assert response.status_code == 422 and threads == [False]


def test_the_plan_answer_is_parsed_on_a_thread(endpoint, monkeypatch):  # noqa: F811
    """Anchoring 600 one-character quotes in a 6,000-character line took 0.39 s on the event loop."""
    threads, real = [], plan.parse_plan_output

    def parse(*args, **kwargs):
        threads.append(on_the_event_loop())
        return real(*args, **kwargs)

    monkeypatch.setattr(plan, "parse_plan_output", parse)
    plan_tests.completed(endpoint, endpoint.submit(endpoint.doc()), endpoint.doc())
    assert threads == [False]


# ------------------------------------------------------------------ round 3: ten requests at once
# Ten requests is one client's limit for /api/tailor* (backend/main.py RATE_LIMITS). The full-target
# routes parsed and validated each body on the event loop, built its prompt there, and prepared the
# draft on asyncio's default pool, where up to eight such threads asked for the GIL at once: the loop
# stalled 0.28-0.60 s (scripts/worst_inputs_lag.py and scripts/rewrite_route_lag.py --concurrent 10).


def _concurrent_posts(path, body, count=10):
    import httpx

    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
            return await asyncio.gather(*(client.post(path, json=body) for _ in range(count)))
    return asyncio.run(send())


@pytest.mark.parametrize(("path", "extra"), [
    ("/api/tailor/full-target/suggestions", {"selected_unit_ids": ["line-1"]}),
    ("/api/tailor/full-target/selection-plan", {"options": {"target_pages": 1}}),
])
def test_ten_full_target_requests_prepare_one_at_a_time_off_the_loop(monkeypatch, path, extra):
    import threading
    import time

    lock, state = threading.Lock(), {"running": 0, "most": 0, "loop": [], "threads": set()}

    def validate(value):
        with lock:
            state["running"] += 1
            state["most"] = max(state["most"], state["running"])
        state["loop"].append(on_the_event_loop())
        state["threads"].add(threading.current_thread().name)
        time.sleep(0.02)
        with lock:
            state["running"] -= 1
        raise InvalidTargetResume("invalid_document")

    monkeypatch.setattr(route, "validate_document", validate)
    responses = _concurrent_posts(path, {**FULL, **extra, "draft": {"kind": "full_resume"}})
    assert [response.status_code for response in responses] == [422] * 10
    assert state["loop"] == [False] * 10
    assert state["most"] == 1 and all(name.startswith("ofe-request-work") for name in state["threads"])


def test_the_body_is_parsed_off_the_loop(monkeypatch):
    seen = []
    real_loads = route.json.loads

    class Json:
        @staticmethod
        def loads(body):
            seen.append(("parse", on_the_event_loop()))
            return real_loads(body)

    def validate(value):
        seen.append(("validate", on_the_event_loop()))
        raise InvalidTargetResume("invalid_document")

    monkeypatch.setattr(route, "json", Json)
    monkeypatch.setattr(route, "validate_document", validate)
    for path, extra in (("/api/tailor/full-target/suggestions", {"selected_unit_ids": ["line-1"]}),
                        ("/api/tailor/full-target/selection-plan", {"options": {"target_pages": 1}})):
        response = TestClient(app).post(path, json={**FULL, **extra, "draft": {"kind": "full_resume"}})
        assert response.status_code == 422
    assert seen == [("parse", False), ("validate", False)] * 2


def test_the_plan_prompt_is_built_off_the_loop(endpoint, monkeypatch):  # noqa: F811
    threads, real = [], plan.plan_preflight

    def preflight(*args, **kwargs):
        threads.append(on_the_event_loop())
        return real(*args, **kwargs)

    monkeypatch.setattr(plan, "plan_preflight", preflight)
    plan_tests.completed(endpoint, endpoint.submit(endpoint.doc()), endpoint.doc())
    assert threads == [False]


def test_a_heavy_full_target_body_is_refused_before_the_lane_parses_it(monkeypatch):
    class Json:
        @staticmethod
        def loads(body):
            raise AssertionError("parsed a body over the bounds")

    monkeypatch.setattr(route, "json", Json)
    for path, extra in (("/api/tailor/full-target/suggestions", {"selected_unit_ids": ["line-1"]}),
                        ("/api/tailor/full-target/selection-plan", {"options": {"target_pages": 1}})):
        for junk in (HEAVY, ITEMS):
            response = TestClient(app).post(path, json={**FULL, **extra, "draft": {"kind": "full_resume", "junk": junk}})
            assert (response.status_code, response.json()) == (422, {"detail": {"code": "invalid_request"}})
