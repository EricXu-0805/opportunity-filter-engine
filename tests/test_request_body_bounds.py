"""What the writing routes run before any worker is bounded or runs off the event loop (criterion 4).

scripts/request_parse_lag.py, scripts/worst_inputs_lag.py and scripts/plan_output_lag.py measure
these paths; these tests pin the behaviour they measure.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.lib import request_body
from backend.lib import target_resume_plan as plan
from backend.lib.resume_input import MAX_RESUME_TEXT_CHARACTERS
from backend.lib.target_resume_ai_validation import InvalidTargetResume
from backend.main import app
from backend.routes import tailor
from backend.routes import target_resume_ai as route
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


def test_each_route_reads_its_largest_valid_body_with_a_wide_margin_and_refuses_one_past_every_bound(monkeypatch):
    """The largest body each request schema accepts (scripts/request_body_containers.py) is read and
    answered as before, at most a quarter of each of its route's bounds; a body past every route's
    bound is refused on every route."""
    from scripts import request_body_containers as largest

    monkeypatch.setattr(tailor, "load_opportunities_by_id", lambda: {})
    monkeypatch.setattr(route, "load_opportunities_by_id", lambda: {})
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    client = TestClient(app)
    bodies = [*largest.schema_bodies(), *largest.full_target_bodies()]
    assert sorted(path for path, _ in bodies) == sorted(largest.BOUNDS)
    for path, body in bodies:
        assert holds(body) * 4 <= largest.BOUNDS[path], path
        assert separators(body) * 4 <= largest.SEPARATOR_BOUNDS[path], path
        assert client.post(path, json=body).status_code in (200, 404), path
        past = {**body, ("draft" if path in largest.FULL_TARGET else "padding"): chains(PAST_EVERY_BOUND)}
        response = client.post(path, json=past)
        detail = response.json()["detail"]
        assert response.status_code == 422, path
        assert detail == {"code": "invalid_request"} if path in largest.FULL_TARGET else detail[0]["type"] == "too_long"


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


def test_legitimate_bodies_whose_text_is_commas_are_read_whole(parsed, monkeypatch):
    """Round 7: commas inside strings are not counted. A full-target draft whose résumé is 60,000 commas
    and a profile of 159,000 commas hold more commas than MAX_JSON_SEPARATORS, all inside strings; their
    routes parse and answer them as main does (404 for the stubbed-out target)."""
    from scripts import request_body_containers as largest

    monkeypatch.setattr(tailor, "load_opportunities_by_id", lambda: {})
    monkeypatch.setattr(route, "load_opportunities_by_id", lambda: {})
    client = TestClient(app)
    bodies = list(largest.comma_dense_bodies())
    assert len(bodies) == 2
    for name, path, body in bodies:
        content = json.dumps(body, ensure_ascii=False).encode()
        assert content.count(b",") > request_body.MAX_JSON_SEPARATORS >= 4 * separators(body), name
        response = client.post(path, content=content, headers={"content-type": "application/json"})
        assert response.status_code == 404, name
    assert parsed == ["/api/tailor"]


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
