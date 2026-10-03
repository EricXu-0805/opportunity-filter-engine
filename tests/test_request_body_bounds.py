"""What the writing routes run before any worker stays off the event loop or bounded (criterion 4, round 1).

scripts/request_parse_lag.py and scripts/plan_output_lag.py measure the event-loop stall these
paths cause at the body limits; these tests pin the behaviour that keeps it under 0.25 s.
"""
from __future__ import annotations

import asyncio

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


def test_a_body_at_the_bound_is_parsed_and_answered_as_before(parsed):
    padding = [[]] * (request_body.MAX_JSON_CONTAINERS - 10)
    response = TestClient(app).post("/api/tailor", json={**TAILOR, "original_bullets": ["Built a robot."],
                                                        "padding": padding})
    assert response.status_code == 404 and parsed == ["/api/tailor"]


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
