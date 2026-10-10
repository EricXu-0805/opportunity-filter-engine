"""What the writing routes run before any worker is bounded or runs off the event loop (criterion 4).

scripts/request_parse_lag.py, scripts/worst_inputs_lag.py and scripts/plan_output_lag.py measure
these paths; these tests pin the behaviour they measure.
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import functools
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import Request

from backend.lib import request_body
from backend.lib import target_resume_plan as plan
from backend.lib.resume_input import MAX_RESUME_TEXT_CHARACTERS
from backend.lib.target_resume_ai_validation import InvalidTargetResume
from backend.main import app
from backend.routes import tailor
from backend.routes import target_resume_ai as route
from scripts import request_body_containers as largest
from tests import test_target_resume_plan as plan_tests
from tests.test_target_resume_plan import endpoint  # noqa: F401

HEAVY = [[]] * (request_body.MAX_JSON_CONTAINERS + 1)
FULL_HEAVY = [[]] * (request_body.MAX_FULL_TARGET_JSON_CONTAINERS + 1)
# At the container bound, and well under the comma bound.
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
    response = TestClient(app).post(path, json={**FULL, **extra, "draft": {"kind": "full_resume", "junk": FULL_HEAVY}})
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
    """Round 2, criterion (4): a body past the comma bound is refused before it is parsed."""
    response = TestClient(app).post(path, json=body)
    assert response.status_code == 422 and parsed == []


# Round 5 (criterion E): an extraction route reads one résumé, which may hold a comma in each of its
# 60,000 characters. origin/main reads such a résumé whole; the 50,000-comma bound refused it with 422.
EXTRACTION_PATHS = ["/api/tailor/extract-bullets", "/api/tailor/structure"]


@pytest.mark.parametrize("path", EXTRACTION_PATHS)
def test_an_extraction_route_reads_a_resume_of_commas_whole(parsed, monkeypatch, path):
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    resume = "Built a robot, " + "," * (MAX_RESUME_TEXT_CHARACTERS - 15)
    response = TestClient(app).post(path, json={"resume_text": resume})
    assert response.status_code == 200 and parsed == [path]


@pytest.mark.parametrize("path", EXTRACTION_PATHS)
def test_an_extraction_body_past_its_own_comma_bound_is_refused_unparsed(parsed, path):
    padding = [0] * (request_body.MAX_RESUME_JSON_SEPARATORS + 1)
    response = TestClient(app).post(path, json={"resume_text": "Built a robot.", "padding": padding})
    assert response.status_code == 422 and parsed == []


@pytest.mark.parametrize(("path", "extra"), [
    ("/api/tailor/full-target/suggestions", {"selected_unit_ids": ["line-1"]}),
    ("/api/tailor/full-target/selection-plan", {"options": {"target_pages": 1}}),
])
def test_the_draft_is_validated_on_a_thread(monkeypatch, path, extra):
    """Round 1, criterion (4): the draft is validated off the event loop."""
    threads = []

    def validate(value):
        threads.append(on_the_event_loop())
        raise InvalidTargetResume("invalid_document")

    monkeypatch.setattr(route, "validate_document", validate)
    response = TestClient(app).post(path, json={**FULL, **extra, "draft": {"kind": "full_resume"}})
    assert response.status_code == 422 and threads == [False]


def test_the_plan_answer_is_parsed_on_a_thread(endpoint, monkeypatch):  # noqa: F811
    """Round 1, criterion (4): the plan's answer is parsed off the event loop."""
    threads, real = [], plan.parse_plan_output

    def parse(*args, **kwargs):
        threads.append(on_the_event_loop())
        return real(*args, **kwargs)

    monkeypatch.setattr(plan, "parse_plan_output", parse)
    plan_tests.completed(endpoint, endpoint.submit(endpoint.doc()), endpoint.doc())
    assert threads == [False]


# ------------------------------------------------------------------ round 3: ten requests at once
# Ten requests is one client's limit for /api/tailor* (backend/main.py RATE_LIMITS). The full-target
# routes parse, validate and prepare each body on one request lane, so the event loop shares the GIL
# with one thread whatever the number of requests (scripts/worst_inputs_lag.py and
# scripts/rewrite_route_lag.py --concurrent 10).


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
        for junk in (FULL_HEAVY, ITEMS):
            response = TestClient(app).post(path, json={**FULL, **extra, "draft": {"kind": "full_resume", "junk": junk}})
            assert (response.status_code, response.json()) == (422, {"detail": {"code": "invalid_request"}})


# ------------------------------------------------------------------ round 6: a structural bound per route
# Each route refuses, before parsing, a body that holds more lists and objects outside its JSON strings
# than its bound; scripts/request_body_containers.py prints each bound beside the largest body the
# route's request schema accepts. Brackets inside strings are not counted, so any résumé within the
# 60,000-character cap is still parsed as on origin/main (criterion E).
WRITING_BOUND = request_body.MAX_JSON_CONTAINERS
RESUME_BOUND = request_body.MAX_RESUME_JSON_CONTAINERS
ROUTE_BOUNDS = [
    ("/api/tailor", {**TAILOR, "original_bullets": ["Built a robot."]}, WRITING_BOUND, 404),
    ("/api/tailor/bullet", {**TAILOR, "current_text": "Built a robot."}, WRITING_BOUND, 404),
    ("/api/tailor/renovate", {**TAILOR, "sections": []}, WRITING_BOUND, 404),
    ("/api/tailor/extract-bullets", {"resume_text": "Built a robot."}, RESUME_BOUND, 200),
    ("/api/tailor/structure", {"resume_text": "Built a robot.", "locale": "en"}, RESUME_BOUND, 200),
]


def chains(total, depth=50):
    """`total` lists, in chains nested `depth` deep."""
    def chain(size):
        return json.loads("[" * size + "]" * size)
    return [chain(depth)] * (total // depth) + ([chain(total % depth)] if total % depth else [])


def holds(body) -> int:
    return request_body.structural_containers(json.dumps(body).encode())


def separators(body) -> int:
    return request_body.structural_separators(json.dumps(body).encode())


PAST_EVERY_BOUND = 2 * request_body.MAX_FULL_TARGET_JSON_CONTAINERS


@pytest.mark.parametrize(("path", "frame", "bound", "answer"), ROUTE_BOUNDS, ids=[row[0] for row in ROUTE_BOUNDS])
def test_a_body_one_list_past_its_routes_bound_is_refused_unparsed(parsed, monkeypatch, path, frame, bound, answer):
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    frame = {**frame, "note": "[{" * bound}  # brackets in a string: more than the bound, none of them counted
    own = holds({**frame, "padding": []})
    at = {**frame, "padding": chains(bound - own)}
    over = {**frame, "padding": chains(bound - own + 1)}
    assert (holds(at), holds(over)) == (bound, bound + 1)
    client = TestClient(app)
    assert client.post(path, json=over).status_code == 422 and parsed == []
    assert client.post(path, json=at).status_code == answer and parsed == [path]


@pytest.mark.parametrize(("path", "extra"), [
    ("/api/tailor/full-target/suggestions", {"selected_unit_ids": ["line-1"]}),
    ("/api/tailor/full-target/selection-plan", {"options": {"target_pages": 1}}),
])
def test_a_full_target_body_past_its_bound_is_refused_before_the_lane_parses_it(monkeypatch, path, extra):
    seen, real_loads = [], route.json.loads

    class Json:
        @staticmethod
        def loads(body):
            seen.append(holds(real_loads(body)))
            return real_loads(body)

    monkeypatch.setattr(route, "json", Json)
    bound = request_body.MAX_FULL_TARGET_JSON_CONTAINERS
    own = holds({**FULL, **extra, "draft": {"kind": "full_resume", "junk": []}})
    client = TestClient(app)
    for total, parsed_holds in ((bound - own + 1, []), (bound - own, [bound])):
        response = client.post(path, json={**FULL, **extra, "draft": {"kind": "full_resume", "junk": chains(total)}})
        assert response.status_code == 422 and seen == parsed_holds


def test_each_route_refuses_a_body_past_every_bound(monkeypatch):
    """A body past every route's bounds is refused on each of the seven writing routes, in the form of
    that route's own validation errors."""
    from scripts import request_body_containers as largest

    monkeypatch.setattr(tailor, "load_opportunities_by_id", lambda: {})
    monkeypatch.setattr(route, "load_opportunities_by_id", lambda: {})
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    client = TestClient(app)
    for _, path, _, body in largest.tailor_bodies(largest.Pick()):
        response = client.post(path, json={**body, "padding": chains(PAST_EVERY_BOUND)})
        assert response.status_code == 422 and response.json()["detail"][0]["type"] == "too_long", path
    for path, body in largest.full_target_bodies():
        response = client.post(path, json={**body, "draft": chains(PAST_EVERY_BOUND)})
        assert (response.status_code, response.json()) == (422, {"detail": {"code": "invalid_request"}}), path


# Résumés of 60,000 characters whose brackets sit among quotes and backslashes, which JSON escapes.
BRACKET_RESUMES = {
    "brackets": "[" * 60_000,
    "quote-bracket": '"[' * 30_000,
    "backslash-quote-brace": '\\"{' * 20_000,
    "backslashes-then-brackets": "\\" * 30_000 + "[{" * 15_000,
    "quoted-json": '{"a": ["b", {"c": "\\\\"}]}, ' * 2_000,
}


@pytest.mark.parametrize("path", EXTRACTION_PATHS)
@pytest.mark.parametrize("resume", BRACKET_RESUMES.values(), ids=BRACKET_RESUMES.keys())
def test_an_extraction_route_reads_a_resume_of_brackets_quotes_and_backslashes_whole(parsed, monkeypatch, path, resume):
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    assert len(resume) <= MAX_RESUME_TEXT_CHARACTERS
    for ensure_ascii in (True, False):
        content = json.dumps({"resume_text": resume}, ensure_ascii=ensure_ascii).encode()
        response = TestClient(app).post(path, content=content, headers={"content-type": "application/json"})
        assert response.status_code == 200
    assert parsed == [path, path]


def test_legitimate_bodies_whose_text_is_commas_are_read_whole():
    """Round 7: commas inside strings are not counted. A full-target draft whose résumé is 60,000 commas
    and a profile of 159,000 commas hold more commas than MAX_JSON_SEPARATORS, all inside strings; and
    the browser sends every saved and dismissed id, which real ids fill the body limit with. Each
    route reads them."""
    from scripts import request_body_containers as largest

    client = TestClient(app)
    bodies = list(largest.comma_dense_bodies())
    assert len(bodies) == 4
    with largest.reading() as parsed:
        for name, path, body in bodies:
            content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            assert len(content) <= 1024 * 1024 or path in largest.FULL_TARGET, name
            assert content.count(b",") > request_body.MAX_JSON_SEPARATORS, name
            parsed.clear()
            largest.send(client, "POST", path, content)
            assert parsed in ([path], ["full-target lane"]), name


def test_a_writing_route_reads_profile_text_of_brackets_whole(parsed):
    profile = {**TAILOR["profile"], "research_interests_text": '"[{' * 20_000}
    response = TestClient(app).post("/api/tailor", json={**TAILOR, "profile": profile,
                                                         "original_bullets": ["Built a robot."]})
    assert response.status_code == 404 and parsed == ["/api/tailor"]


@pytest.mark.parametrize("path", EXTRACTION_PATHS)
def test_a_utf16_body_is_counted_as_json_reads_it(parsed, monkeypatch, path):
    """In UTF-16 the byte 0x22 is also half of a character such as '∀' (U+2200): read as bytes, the
    quotes would pair wrongly and hide the lists after it."""
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    client = TestClient(app)
    for padding, answer in ((chains(RESUME_BOUND + 1), 422), ([], 200)):
        content = json.dumps({"resume_text": "Built a robot ∀.", "padding": padding}, ensure_ascii=False).encode("utf-16")
        assert client.post(path, content=content, headers={"content-type": "application/json"}).status_code == answer
    assert parsed == [path]


@pytest.mark.parametrize(("path", "extra"), [
    ("/api/tailor/extract-bullets", {"expected_pipeline_version": tailor.TAILOR_PIPELINE_VERSION}),
    ("/api/tailor/structure", {"locale": "en"}),
])
def test_a_resume_of_commas_with_the_browsers_other_field_is_read_whole(parsed, monkeypatch, path, extra):
    """The browser sends the pipeline version (extraction) or the locale (structure) beside the résumé
    (frontend/src/lib/api.ts), one comma more than the résumé holds. Round 6's margin was for these;
    since round 7 the résumé's commas sit inside its string and are not counted at all."""
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    body = {"resume_text": "," * MAX_RESUME_TEXT_CHARACTERS, **extra}
    assert json.dumps(body).count(",") == MAX_RESUME_TEXT_CHARACTERS + 1
    response = TestClient(app).post(path, json=body)
    assert response.status_code == 200 and parsed == [path]


def _values(rng, depth=0):
    """A random JSON value whose strings are made of the characters a structural count must read past."""
    alphabet = '[]{}",:\\ab∀ '
    kind = rng.randrange(6 if depth < 6 else 3)
    if kind == 0:
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(12)))
    if kind == 1:
        return rng.choice([0, -1.5, True, None])
    if kind == 2:
        return ""
    if kind in (3, 4):
        return [_values(rng, depth + 1) for _ in range(rng.randrange(4))]
    return {_values(rng, 6): _values(rng, depth + 1) for _ in range(rng.randrange(4))}


def _containers(value) -> int:
    if isinstance(value, list):
        return 1 + sum(_containers(item) for item in value)
    if isinstance(value, dict):
        return 1 + sum(_containers(item) for item in value.values())
    return 0


def _separators(value) -> int:
    if isinstance(value, list):
        return max(len(value) - 1, 0) + sum(_separators(item) for item in value)
    if isinstance(value, dict):
        return max(len(value) - 1, 0) + sum(_separators(item) for item in value.values())
    return 0


def test_the_structural_comma_count_is_the_number_of_separators_json_reads():
    import random

    rng = random.Random(7)
    for _ in range(2_000):
        value = _values(rng)
        expected = _separators(value)
        for ensure_ascii in (True, False):
            text = json.dumps(value, ensure_ascii=ensure_ascii)
            assert request_body.structural_separators(text.encode()) == expected
            for encoding in ("utf-16", "utf-16-be", "utf-32"):
                assert request_body.structural_separators(request_body._json_text(text.encode(encoding))) == expected


def test_the_structural_count_is_the_number_of_lists_and_objects_json_reads():
    import random

    rng = random.Random(6)
    for _ in range(2_000):
        value = _values(rng)
        expected = _containers(value)
        for ensure_ascii in (True, False):
            text = json.dumps(value, ensure_ascii=ensure_ascii)
            assert request_body.structural_containers(text.encode()) == expected
            for encoding in ("utf-16", "utf-16-be", "utf-32"):
                assert request_body.structural_containers(request_body._json_text(text.encode(encoding))) == expected


def test_a_json_body_is_refused_exactly_when_it_is_past_a_bound():
    """Whatever its strings hold, a JSON body is refused when its lists and objects or its commas
    between items outnumber the bounds, and only then, down to bounds small enough that the count of
    its strings decides."""
    import random

    from fastapi.exceptions import RequestValidationError

    rng = random.Random(5)
    for _ in range(3_000):
        value = _values(rng)
        max_separators, max_containers = rng.randrange(8), rng.randrange(6)
        past = _separators(value) > max_separators or _containers(value) > max_containers
        for ensure_ascii in (True, False):
            text = json.dumps(value, ensure_ascii=ensure_ascii)
            for body in (text.encode(), text.encode("utf-16")):
                try:
                    request_body.check_body_bounds(body, max_separators, max_containers)
                except RequestValidationError:
                    refused = True
                else:
                    refused = False
                assert refused == past, (text, max_separators, max_containers)


def test_a_body_past_a_bound_is_refused_without_reading_its_strings(monkeypatch):
    """A body within both bounds holds at most 2 * (separators + containers) + 1 strings, so one that
    holds more is refused without reading them."""
    from fastapi.exceptions import RequestValidationError

    seen, real = [], request_body._unescaped

    class Counted(bytes):
        def split(self, *args):
            pieces = bytes.split(self, *args)
            seen.append(len(pieces))
            return pieces

    monkeypatch.setattr(request_body, "_unescaped", lambda text: Counted(real(text)))
    bounds = request_body.WRITING_BOUNDS
    quotes = 2 * (2 * (bounds.separators + bounds.containers) + 1)
    for body in (b'{"padding":' + b'"' * (quotes + 1) + b"," * (bounds.separators + 1) + b"}",
                 b'{"padding":' + b'"' * (quotes + 1) + b"[" * (bounds.containers + 1) + b"}"):
        with pytest.raises(RequestValidationError):
            request_body.check_body_bounds(body, bounds.separators, bounds.containers)
    assert seen == []
    commas = json.dumps({"text": "," * (bounds.separators + 1)}).encode()
    request_body.check_body_bounds(commas, bounds.separators, bounds.containers)
    assert seen == [5]


# ------------------------------------------------------------------ every route that reads a JSON body
# scripts/request_body_containers.py finds them in the app (json_routes): a body parameter FastAPI
# parses, or an endpoint that reads its Request's json() or body(). Each declares its bounds
# (request_body.json_body_bounds) and refuses a body past them before it is parsed.
JSON_ROUTES = largest.json_routes(app)
ROUTE_IDS = [f"{method} {path}" for method, path, _ in JSON_ROUTES]


def test_the_app_routes_that_read_a_json_body_are_found():
    found = {(method, path) for method, path, _ in JSON_ROUTES}
    assert len(found) >= 37
    # A body parameter, a body read by the endpoint itself, and bodies parsed on the request lane.
    assert {("POST", "/api/matches"), ("DELETE", "/api/application-materials/{record_id}"),
            ("POST", "/api/tailor/full-target/suggestions"), ("PUT", "/api/private-import-targets/{target_id}")} <= found
    # A multipart upload and a route without a body are not JSON routes.
    assert ("POST", "/api/application-materials") not in found and ("GET", "/api/tailor/status") not in found


class _NewBody(BaseModel):
    name: str


def test_a_json_route_without_bounds_is_found_by_the_check():
    """The check below fails for a new route that reads a JSON body and declares no bounds."""
    from fastapi import APIRouter, FastAPI

    probe, router = FastAPI(), APIRouter(route_class=request_body.BoundedJSONRoute)

    @router.post("/unbounded")
    async def unbounded(body: _NewBody):
        return {}

    @router.post("/reads-itself")
    async def reads_itself(request: Request):
        return await request.json()

    @router.post("/on-the-lane")
    async def on_the_lane(body=request_body.json_body_on_lane(_NewBody)):
        return {}

    probe.include_router(router)
    routes = {path: route for _, path, route in largest.json_routes(probe)}
    assert set(routes) == {"/unbounded", "/reads-itself", "/on-the-lane"}
    assert all(request_body.declared_bounds(route) is None for route in routes.values())


async def _read_json(request: Request):
    return await request.json()


async def _read_through(request):
    return await _read_json(request)


def test_a_route_that_reads_its_body_in_a_dependency_or_a_helper_is_found_by_the_check():
    """A route whose dependency, or a helper it hands its Request to, reads the body is a JSON route
    too, and so is one whose helper is a closure; a route that only reads its Request's URL is not."""
    from fastapi import APIRouter, Depends, FastAPI

    probe, router = FastAPI(), APIRouter(route_class=request_body.BoundedJSONRoute)

    async def nested(request: Request):
        return await request.body()

    @router.post("/in-a-dependency")
    async def in_a_dependency(body=Depends(_read_json)):
        return {}

    @router.post("/in-a-helper")
    async def in_a_helper(request: Request):
        return await _read_through(request)

    @router.post("/in-a-closure")
    async def in_a_closure(request: Request):
        return await nested(request)

    @router.post("/no-body")
    async def no_body(request: Request):
        return {"path": request.url.path}

    probe.include_router(router)
    assert {path for _, path, _ in largest.json_routes(probe)} == {"/in-a-dependency", "/in-a-helper", "/in-a-closure"}


@pytest.mark.parametrize(("method", "path", "json_route"), JSON_ROUTES, ids=ROUTE_IDS)
def test_every_json_route_declares_bounds_its_route_enforces(method, path, json_route):
    bounds = request_body.declared_bounds(json_route)
    assert bounds is not None, f"{method} {path} reads a JSON body and declares no bounds (json_body_bounds)"
    # The full-target routes enforce theirs on the request lane (_parsed); every other route's class does.
    assert isinstance(json_route, request_body.BoundedJSONRoute) or path in largest.FULL_TARGET


def _concrete():
    return {(method, path): concrete for method, path, concrete, _ in largest.largest_bodies()}


@pytest.mark.parametrize(("method", "path", "json_route"), JSON_ROUTES, ids=ROUTE_IDS)
def test_every_json_route_reads_a_body_at_its_bounds_and_refuses_one_past_either_unparsed(method, path, json_route):
    bounds = request_body.declared_bounds(json_route)
    concrete = _concrete()[method, path]
    client = TestClient(app)
    with largest.reading() as parsed:
        for at, over in ((chains(bounds.containers - 1), chains(bounds.containers)),
                         ([0] * (bounds.separators + 1), [0] * (bounds.separators + 2))):
            assert holds(at) <= bounds.containers and separators(at) <= bounds.separators
            assert holds(over) > bounds.containers or separators(over) > bounds.separators
            parsed.clear()
            response = largest.send(client, method, concrete, json.dumps(over).encode())
            assert response.status_code == 422 and parsed == [], (method, path)
            largest.send(client, method, concrete, json.dumps(at).encode())
            assert len(parsed) == 1, (method, path)


def test_every_json_route_has_a_largest_body():
    assert {(method, path) for method, path, *_ in largest.largest_bodies()} == {
        (method, path) for method, path, _ in JSON_ROUTES}


@pytest.mark.parametrize(("method", "path", "json_route"), JSON_ROUTES, ids=ROUTE_IDS)
def test_every_json_route_reads_its_largest_valid_body_with_a_wide_margin(method, path, json_route):
    """The largest body each request schema accepts is valid, holds at most a quarter of each of its
    route's bounds, and its route reads it."""
    bounds = request_body.declared_bounds(json_route)
    concrete, body = next((c, b) for m, p, c, b in largest.largest_bodies() if (m, p) == (method, path))
    largest.validate(json_route, body)
    content = json.dumps(body, ensure_ascii=False).encode()
    assert largest.containers(content) * 4 <= bounds.containers
    assert largest.separators(content) * 4 <= bounds.separators
    with largest.reading() as parsed:
        largest.send(TestClient(app), method, concrete, content)
    assert len(parsed) == 1


def test_random_valid_bodies_are_read_on_every_json_route():
    """Random valid bodies, with lists of random lengths within their caps and text made of the
    characters a structural count must read past, are read on every route."""
    import random

    routes = {(method, path): json_route for method, path, json_route in JSON_ROUTES}
    client = TestClient(app)
    with largest.reading() as parsed:
        for seed in range(4):
            pick = largest.Pick(random.Random(seed))
            for method, path, concrete, body in largest.largest_bodies(pick):
                largest.validate(routes[method, path], body)
                bounds = request_body.declared_bounds(routes[method, path])
                for ensure_ascii in (True, False):
                    content = json.dumps(body, ensure_ascii=ensure_ascii).encode()
                    assert largest.containers(content) <= bounds.containers, (seed, method, path)
                    assert largest.separators(content) <= bounds.separators, (seed, method, path)
                    parsed.clear()
                    largest.send(client, method, concrete, content)
                    assert len(parsed) == 1, (seed, method, path)


def test_the_lane_threshold_is_the_default_body_limit(monkeypatch):
    """The size past which a body is counted on the request lane is the body limit of every route
    without a larger one of its own, defined in one place."""
    from backend import main

    monkeypatch.delenv("OFE_MAX_REQUEST_BODY_BYTES", raising=False)
    assert main._request_body_limit_from_env() == request_body.DEFAULT_MAX_REQUEST_BODY_BYTES
    assert request_body.LANE_BODY_BYTES == request_body.DEFAULT_MAX_REQUEST_BODY_BYTES
    monkeypatch.setenv("OFE_MAX_REQUEST_BODY_BYTES", "not a size")
    assert main._request_body_limit_from_env() == request_body.DEFAULT_MAX_REQUEST_BODY_BYTES


def test_a_body_past_the_default_body_limit_is_counted_on_the_request_lane(monkeypatch):
    """Only the routes with a larger body limit accept such a body; it is counted off the event loop,
    one at a time, and a smaller one on the loop."""
    import threading

    seen, real = [], request_body.check_body_bounds

    def check(body, *args):
        seen.append((len(body) > request_body.LANE_BODY_BYTES, on_the_event_loop(),
                     threading.current_thread().name.startswith("ofe-request-work")))
        return real(body, *args)

    monkeypatch.setattr(request_body, "check_body_bounds", check)
    method, path, concrete, body = next(row for row in largest.largest_bodies()
                                        if row[:2] == ("PUT", "/api/private-import-targets/{target_id}"))
    large = {**body, "opportunity": {**body["opportunity"], "description_raw": "Join the lab. " * 120_000}}
    client = TestClient(app)
    with largest.reading() as parsed:
        for sent in (body, large):
            largest.send(client, method, concrete, json.dumps(sent).encode())
    assert seen == [(False, True, False), (True, False, True)] and len(parsed) == 2


# ------------------------------------------------------------------ bodies above the default body limit
# A route whose body limit is above the default (backend.main.RequestBodyLimitMiddleware) reads and
# validates its body on the request lane: through request_body.json_body_on_lane, or, on the two
# full-target routes, in their own preparation there.
LANE_ROUTES = [(method, path, json_route) for method, path, json_route in JSON_ROUTES
               if largest.lane_body_model(json_route) is not None]


LANE_PATHS = {
    ("PUT", "/api/private-import-targets/{target_id}"),
    ("POST", "/api/private-import-targets/{target_id}/cold-email/variants"),
    ("POST", "/api/private-import-targets/{target_id}/cold-email/validate"),
    ("POST", "/api/resume/full-target/export"),
    ("POST", "/api/cold-email"), ("POST", "/api/cold-email/stream"), ("POST", "/api/cold-email/variants"),
    ("POST", "/api/cold-email/refine"), ("POST", "/api/cold-email/validate"),
}


def test_the_routes_that_take_their_body_on_the_lane_are_found():
    """The routes with the largest structured bodies read and validate them on the request lane
    (request_body.json_body_on_lane), off the event loop: the four with a body limit above the
    default, and the five public cold-email routes. The full-target routes read their body on the
    lane in their own preparation, not here."""
    assert {(method, path) for method, path, _ in LANE_ROUTES} == LANE_PATHS


@pytest.mark.parametrize(("method", "path", "json_route"), JSON_ROUTES, ids=ROUTE_IDS)
def test_no_route_parses_a_body_past_the_default_body_limit_on_the_event_loop(method, path, json_route):
    """Each route either refuses such a body before reading it (413) or reads it on the request lane.
    None parses a body over the default limit on the event loop."""
    content = json.dumps({"padding": "a" * (request_body.LANE_BODY_BYTES + 1024)}).encode()
    with largest.reading() as parsed:
        response = largest.send(TestClient(app), method, _concrete()[method, path], content)
    assert parsed in ([], ["request lane"], ["full-target lane"]), (method, path)
    assert parsed or response.status_code == 413, (method, path)


@pytest.mark.parametrize(("method", "path", "json_route"), LANE_ROUTES, ids=[f"{m} {p}" for m, p, _ in LANE_ROUTES])
def test_a_lane_route_reads_its_body_on_the_lane_for_a_body_within_the_default_limit(method, path, json_route):
    """A valid-sized body is read and validated on the request lane even when it fits the default
    limit, so its json.loads never runs on the event loop."""
    concrete, body = next((c, b) for m, p, c, b in largest.largest_bodies() if (m, p) == (method, path))
    content = json.dumps(body).encode()
    assert len(content) <= request_body.LANE_BODY_BYTES
    with largest.reading() as parsed:
        largest.send(TestClient(app), method, concrete, content)
    assert parsed == ["request lane"], (method, path)


def test_a_route_reads_and_validates_its_body_on_the_lane_off_the_event_loop(monkeypatch):
    """Each lane route's largest valid body is read and validated off the loop, one at a time on the
    request-work thread, and the export's signature is checked there too (never on the event loop)."""
    import threading

    from backend.lib.target_resume_export_schema import ExportRequest

    seen, real_body, real_signature = [], request_body.validated_json_body, ExportRequest.verify_signature

    def off_loop(name) -> bool:
        return not on_the_event_loop() and threading.current_thread().name.startswith("ofe-request-work")

    def body(*args):
        where = off_loop("body")
        result = real_body(*args)
        seen.append(("body", type(result).__name__, where))
        return result

    def signature(self):
        seen.append(("signature", off_loop("signature")))
        return real_signature(self)

    @contextlib.asynccontextmanager
    async def verified(*args, **kwargs):
        yield

    from backend.lib import private_import_targets as storage
    from backend.routes import private_import_targets as targets
    from backend.routes import target_resume_export as export

    monkeypatch.setattr(storage, "caller_verified_before_parsing", verified)
    monkeypatch.setattr(targets, "caller_verified_before_parsing", verified)
    monkeypatch.setattr(export, "render_export", lambda *args, **kwargs: b"%PDF-1.7")
    monkeypatch.setattr(request_body, "validated_json_body", body)
    monkeypatch.setattr(ExportRequest, "verify_signature", signature)
    client = TestClient(app)
    lane = {(m, p): largest.lane_body_model(r).__name__ for m, p, r in LANE_ROUTES}
    for method, path, concrete, sent in largest.largest_bodies():
        if (method, path) in lane:
            client.request(method, concrete, content=json.dumps(sent).encode(),
                           headers={"content-type": "application/json", "authorization": "Bearer reader"})
    read = [row for row in seen if row[0] == "body"]
    assert len(read) == len(lane)
    assert all(where for _, _, where in read), read
    assert {name for _, name, _ in read} == set(lane.values())
    assert ("signature", True) in seen


def _answers(model):
    """A probe app that takes `model` as a body parameter (/parameter) and through
    json_body_on_lane (/lane), answering every validation error in full."""
    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    probe = FastAPI()

    @probe.exception_handler(RequestValidationError)
    async def errors(request, exc):
        return JSONResponse([[error["type"], list(error["loc"]), error["msg"], repr(error.get("input")),
                              repr(error.get("ctx"))] for error in exc.errors()], status_code=422)

    async def parameter(data):
        return {"read": type(data).__name__}

    async def lane(data=request_body.json_body_on_lane(model)):
        return {"read": type(data).__name__}

    parameter.__annotations__ = {"data": model}
    probe.post("/parameter")(parameter)
    probe.post("/lane")(lane)
    return TestClient(probe, raise_server_exceptions=False)


@pytest.mark.parametrize(("method", "path", "json_route"), LANE_ROUTES, ids=[f"{m} {p}" for m, p, _ in LANE_ROUTES])
def test_a_body_taken_on_the_lane_is_read_and_refused_as_a_body_parameter_is(method, path, json_route):
    model = largest.lane_body_model(json_route)
    body = next(sent for m, p, _, sent in largest.largest_bodies() if (m, p) == (method, path))
    valid = json.dumps(body).encode()
    wrong = {key: [1] for key in body}
    sends = [
        (valid, "application/json"), (valid, "application/json; charset=utf-8"), (valid, "application/merge-patch+json"),
        (valid, None), (valid, "text/plain"), (b"", "application/json"), (b"null", "application/json"),
        (b"[]", "application/json"), (b'{"a":', "application/json"), (b'{"a":"\xff"}', "application/json"),
        (b"[" * 5_000 + b"]" * 5_000, "application/json"), (json.dumps(body).encode("utf-16"), "application/json"),
        (json.dumps({**body, "padding": 1}).encode(), "application/json"), (json.dumps(wrong).encode(), "application/json"),
    ]
    client = _answers(model)
    for content, content_type in sends:
        headers = {"content-type": content_type} if content_type else {}
        expected = client.post("/parameter", content=content, headers=headers)
        answered = client.post("/lane", content=content, headers=headers)
        assert (answered.status_code, answered.json()) == (expected.status_code, expected.json()), (content[:40], content_type)
    assert client.post("/lane", content=valid, headers={"content-type": "application/json"}).json() == {"read": model.__name__}


def test_the_per_character_checks_read_every_code_point_as_before():
    """The private import's surrogate check and the export's XML check accept and refuse exactly the
    code points they did before."""
    from backend.lib import private_import_targets_schema as private
    from backend.lib import target_resume_export_schema as export

    def xml(point):
        return point in (9, 10, 13) or 0x20 <= point <= 0xD7FF or 0xE000 <= point <= 0xFFFD or 0x10000 <= point <= 0x10FFFF

    for point in range(0x110000):
        character = chr(point)
        assert (export._NOT_XML.search(character) is None) == xml(point), hex(point)
        assert (private._SURROGATE.search(character) is not None) == (0xD800 <= point <= 0xDFFF), hex(point)
    assert export.xml_text("Built a rig.\tIn 2026.\n") == "Built a rig.\tIn 2026.\n"
    with pytest.raises(export.ExportError):
        export.xml_text("Built a rig.\x0b")
    with pytest.raises(ValueError):
        private.opportunity({"source": "text_parser", "title": "Lab", "description_raw": "Join \ud800 us."})


# ------------------------------------------------------------------ what validating a body may build
# Validation errors one body within its route's bounds may make validation build: on the event loop,
# and on the request lane (LANE_ROUTES and the full-target routes), where the route's class reads them.
LOOP_ERRORS = 1_000
LANE_ERRORS = 5_000


@functools.cache
def _validation_bodies() -> dict:
    bodies = collections.defaultdict(list)
    for method, path, concrete, name, body in largest.validation_bodies(app):
        bodies[method, path].append((name, concrete, body))
    return bodies


def _on_the_lane(path, json_route) -> bool:
    return largest.lane_body_model(json_route) is not None or path in largest.FULL_TARGET


@pytest.mark.parametrize(("method", "path", "json_route"), JSON_ROUTES, ids=ROUTE_IDS)
def test_validating_a_body_within_its_routes_bounds_builds_few_errors(method, path, json_route):
    """Each list, typed map and closed model of a route's request schema, filled within the route's
    bounds and body limit with items of every JSON type or with undeclared keys, in one copy and in as
    many copies as the lists that hold it allow (largest.validation_bodies), makes validation build at
    most LOOP_ERRORS errors, or LANE_ERRORS on a route that validates on the request lane."""
    bounds = request_body.declared_bounds(json_route)
    cap = LANE_ERRORS if _on_the_lane(path, json_route) else LOOP_ERRORS
    bodies = _validation_bodies()[method, path]
    model = largest.request_model(json_route)
    sites = {".".join(map(str, site)) or "(body)" for _, site, _ in largest.schema_sites(getattr(model, "_type", model))}
    assert sites <= {name.split(": ")[0] for name, _, _ in bodies}, (method, path)
    for name, _, body in bodies:
        content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        request_body.check_body_bounds(content, bounds.separators, bounds.containers)
        assert len(content) <= largest.body_limit(method, path)
        assert largest.validation_errors(json_route, body) <= cap, (method, path, name)


def test_a_closed_model_refuses_more_keys_than_it_has_fields_as_one_error():
    from pydantic import ConfigDict, ValidationError, model_validator

    class Closed(BaseModel):
        model_config = ConfigDict(extra="forbid")
        _known_keys = model_validator(mode="before")(request_body.known_keys)
        name: str
        level: int = 0

    assert Closed.model_validate({"name": "a", "level": 1}).level == 1
    with pytest.raises(ValidationError) as one:
        Closed.model_validate({"name": "a", "x": 1})
    assert [error["type"] for error in one.value.errors()] == ["extra_forbidden"]
    with pytest.raises(ValidationError) as many:
        Closed.model_validate({"name": "a", **{f"x{i}": 1 for i in range(1_000)}})
    assert [(error["type"], error["loc"]) for error in many.value.errors()] == [("extra_forbidden", ())]


def test_every_closed_request_model_refuses_more_keys_than_it_has_fields_as_one_error():
    """Every model of a JSON route's request schema that refuses unknown keys does so for an object
    with more keys than it has fields as one error (request_body.known_keys)."""
    from pydantic import ValidationError

    closed = {detail for _, _, json_route in JSON_ROUTES for kind, _, detail in largest.schema_sites(
        getattr(largest.request_model(json_route), "_type", largest.request_model(json_route))) if kind == "keys"}
    assert len(closed) >= 20
    for model in closed:
        with pytest.raises(ValidationError) as refused:
            model.model_validate({f"undeclared{i}": 0 for i in range(len(model.model_fields) + 1)})
        assert refused.value.error_count() == 1, model.__name__


@pytest.mark.parametrize(("body", "errors"), [
    ({"favorite_ids": [0] * 20_000}, 1), ({"dismissed_ids": [None] * 20_000}, 1),
    ({"favorite_ids": ["a"] * 6_000 + [0] * 6_000}, 0), ({"favorite_ids": [0]}, 1),
])
def test_a_match_view_reads_and_validates_only_the_ids_it_keeps(body, errors):
    from pydantic import ValidationError

    from backend.schemas import MatchViewState

    try:
        state = MatchViewState.model_validate({"today": "2026-10-09", **body})
    except ValidationError as exc:
        assert exc.error_count() == errors
    else:
        assert errors == 0 and len(state.favorite_ids) == 1


def test_a_list_kept_whole_is_refused_as_one_error_when_an_item_is_not_a_string():
    from pydantic import ValidationError

    from backend.schemas import RoadmapRequest

    ids = [f"{i:016x}" for i in range(20_000)]
    assert RoadmapRequest.model_validate({"profile": {}, "opportunity_ids": ids}).opportunity_ids == ids
    for wrong in (0, None, {}, []):
        with pytest.raises(ValidationError) as refused:
            RoadmapRequest.model_validate({"profile": {}, "opportunity_ids": ids + [wrong] * 20_000})
        assert refused.value.error_count() == 1


@pytest.mark.parametrize("model_path", ["backend.schemas.ColdEmailRequest", "backend.routes.cold_email.EmailRefineRequest"])
def test_only_the_bullets_a_cold_email_reads_are_validated(model_path):
    import importlib

    from pydantic import ValidationError

    module, name = model_path.rsplit(".", 1)
    model = getattr(importlib.import_module(module), name)
    body = {"profile": {"name": "Sample Student"}, "opportunity_id": "o", "current_body": "Hi.", "instruction": "Shorter."}
    kept = model.model_validate({**body, "resume_bullets": ["Built a rig.", " ", *(["Led a team."] * 20), 0]})
    assert kept.resume_bullets == ["Built a rig."] + ["Led a team."] * 10
    with pytest.raises(ValidationError) as refused:
        model.model_validate({**body, "resume_bullets": [0] * 20_000})
    assert refused.value.error_count() == 12


def test_an_export_past_its_block_or_line_limits_is_refused_before_its_sections_are_validated():
    from pydantic import ValidationError

    from backend.lib.target_resume_export_schema import ExportProjection

    head = {"version": 1, "template": "standard-v1", "locale": "en", "page_size": "letter"}
    for blocks in ([{"lines": [0] * 601}], [{"lines": [0]}] * 601, [{"lines": [0] * 300}] * 3):
        with pytest.raises(ValidationError) as refused:
            ExportProjection.model_validate({**head, "sections": [{"kind": "other", "heading": "", "blocks": blocks}]})
        assert [error["msg"] for error in refused.value.errors()] == ["Value error, projection_limit"]


def test_the_app_builds_few_errors_for_a_body_on_a_route_that_validates_on_the_event_loop(monkeypatch):
    """Through the app: every route that validates its body on the event loop builds at most
    LOOP_ERRORS errors for the longest body largest.validation_bodies makes for each of its lists,
    typed maps and closed models, and for the one whose model builds the most."""
    from fastapi import exceptions

    from backend.lib import private_import_targets as storage
    from backend.routes import private_import_targets as targets

    sizes, real = [], exceptions.RequestValidationError.__init__

    def recorded(self, errors, *args, **kwargs):
        errors = list(errors)
        sizes.append(len(errors))
        real(self, errors, *args, **kwargs)

    @contextlib.asynccontextmanager
    async def verified(*args, **kwargs):
        yield

    monkeypatch.setattr(exceptions.RequestValidationError, "__init__", recorded)
    monkeypatch.setattr(storage, "caller_verified_before_parsing", verified)
    monkeypatch.setattr(targets, "caller_verified_before_parsing", verified)
    client, sent = TestClient(app, raise_server_exceptions=False), 0
    for method, path, json_route in JSON_ROUTES:
        if _on_the_lane(path, json_route):
            continue
        chosen = {}
        for name, _, body in _validation_bodies()[method, path]:
            site, content = name.split(": ")[0], json.dumps(body, separators=(",", ":")).encode()
            chosen[site] = max(chosen.get(site, (0, "", b"")), (len(content), name, content))
        most = max(_validation_bodies()[method, path], default=None,
                   key=lambda row: largest.validation_errors(json_route, row[2]))
        if most:
            chosen["most"] = (0, most[0], json.dumps(most[2], separators=(",", ":")).encode())
        for _, name, content in chosen.values():
            sizes.clear()
            response = largest.send(client, method, _concrete()[method, path], content)
            assert response.status_code != 500, (method, path, name)
            assert max(sizes, default=0) <= LOOP_ERRORS, (method, path, name, sizes)
            sent += 1
    assert sent >= 40


def test_every_json_route_answers_an_invalid_body_without_the_values_it_sent(monkeypatch):
    """Every JSON route, sent each value of its request schema as a list of numbers no field of that
    type takes (largest.validation_bodies, in one copy), answers without any of the values sent, and a
    list of errors names at most MAX_VALIDATION_ERRORS of them by type, location and message."""
    from backend.lib import private_import_targets as storage
    from backend.lib.profile_validation import MAX_VALIDATION_ERRORS
    from backend.routes import private_import_targets as targets

    @contextlib.asynccontextmanager
    async def verified(*args, **kwargs):
        yield

    monkeypatch.setattr(storage, "caller_verified_before_parsing", verified)
    monkeypatch.setattr(targets, "caller_verified_before_parsing", verified)
    monkeypatch.setenv("ADMIN_TOKEN", "probe-admin")
    headers = {"content-type": "application/json", "authorization": "Bearer reader", "x-admin-token": "probe-admin"}
    client, refused = TestClient(app, raise_server_exceptions=False), collections.Counter()
    sent = json.dumps(largest.WRONG_ITEM).encode()
    for method, path, _ in JSON_ROUTES:
        for name, concrete, body in _validation_bodies()[method, path]:
            if ": a list of " not in name or " copies of " in name:
                continue
            content = json.dumps(body, separators=(",", ":")).encode()
            response = client.request(method, concrete, content=content, headers=headers)
            assert response.status_code != 500 and sent not in response.content, (method, path, name)
            detail = response.json().get("detail") if response.status_code == 422 else None
            if isinstance(detail, list):
                assert 0 < len(detail) <= MAX_VALIDATION_ERRORS, (method, path, name)
                assert all(set(error) == {"type", "loc", "msg"} for error in detail), (method, path, name)
            refused[method, path] += response.status_code == 422
    assert all(refused[method, path] for method, path, _ in JSON_ROUTES), refused


class _Items(BaseModel):
    names: list[str]
    title: str


def test_a_validation_error_list_names_the_first_errors_without_their_values():
    from fastapi import FastAPI

    probe = FastAPI(exception_handlers=app.exception_handlers)

    @probe.post("/items")
    async def items(body: _Items):
        return {}

    client = TestClient(probe)
    response = client.post("/items", json={"names": [0] * 50, "title": ["Built a rig."] * 3})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0] == {"type": "string_type", "loc": ["body", "names", 0], "msg": "Input should be a valid string"}
    assert len(detail) == 20 and "Built a rig." not in response.text
    response = client.post("/items", json={"names": ["a"], "title": 1.5e300})
    assert response.json()["detail"] == [{"type": "string_type", "loc": ["body", "title"],
                                          "msg": "Input should be a valid string"}]


def test_a_route_that_reads_its_body_in_a_helper_without_bounds_fails_the_test_that_reaches_it(unbounded_body_reads):
    """tests/conftest.py records a backend route that reads its request body, wherever it reads it,
    without declaring its bounds."""
    from fastapi import APIRouter, Depends, FastAPI

    router = APIRouter()

    async def helper(request: Request):
        return await request.json()

    async def in_a_dependency(body=Depends(helper)):
        return {}

    async def in_a_helper(request: Request):
        return await helper(request)

    @request_body.json_body_bounds(request_body.SMALL_BOUNDS)
    async def bounded(request: Request):
        return await helper(request)

    for name, probe_endpoint in (("dependency", in_a_dependency), ("helper", in_a_helper), ("bounded", bounded)):
        probe_endpoint.__module__ = "backend.routes.probe"
        router.post(f"/{name}")(probe_endpoint)
    probe = FastAPI()
    probe.include_router(router)
    client = TestClient(probe)
    for name in ("dependency", "helper", "bounded"):
        client.post(f"/{name}", json={"a": 1})
    assert unbounded_body_reads == ["POST /dependency", "POST /helper"]
    unbounded_body_reads.clear()


def _metadata_save(extra: dict) -> dict:
    method, path, concrete, body = next(row for row in largest.largest_bodies()
                                        if row[:2] == ("PUT", "/api/private-import-targets/{target_id}"))
    return {**body, "opportunity": {**body["opportunity"], "extra_fields": extra}}


def test_a_save_reads_metadata_of_as_many_lists_objects_and_commas_as_its_size_limit_holds(parsed):
    """A private import's metadata may hold anything within MAX_EXTRA_BYTES of compact JSON nested at
    most as deep as the schema allows; the save's bounds hold the most lists and objects, and the
    most commas, such metadata can."""
    from backend.lib.private_import_targets_schema import MAX_EXTRA_BYTES, SaveRequest, encoded

    room = MAX_EXTRA_BYTES - len(encoded({"": []}))
    chain = json.loads("[" * 30 + "]" * 30)
    lists = {"": [chain] * ((room + 1) // 61)}
    commas = {"": [0] * ((room + 1) // 2)}
    client = TestClient(app)
    for extra in (lists, commas):
        assert MAX_EXTRA_BYTES - 61 < len(encoded(extra)) <= MAX_EXTRA_BYTES
        body = _metadata_save(extra)
        SaveRequest.model_validate(body)
        content = json.dumps(body).encode()
        assert largest.containers(content) > request_body.WRITING_BOUNDS.containers or \
            largest.separators(content) > request_body.WRITING_BOUNDS.separators
        with largest.reading() as read:
            largest.send(client, "PUT", f"/api/private-import-targets/{largest.PRIVATE_TARGET}", content)
        assert read == ["request lane"]
