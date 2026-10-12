"""The request lane's capacity (backend/lib/blocking.py REQUEST_LANE_CAPACITY).

Only work submitted to the lane counts, while it waits for the lane or runs on it. A request's first
work on the lane is refused with a 503, and not submitted, when the lane already holds CAPACITY pieces
of work. Until then the request counts for nothing, whether its body is still arriving or it waits on
Supabase, and its later work is never refused. However a request ends, its work stops counting.

The lane work here waits until the test lets it finish, so no assertion depends on how fast a runner
is: AT_ONCE and WAIT only bound how long a broken build takes to fail. The lane is one thread shared
by every test, so each test starts once the work earlier tests left there has finished.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import random
import re
import threading

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from backend.lib import blocking, request_body
from scripts import request_body_containers as largest

AT_ONCE = 10
WAIT = 30
CAPACITY = blocking.REQUEST_LANE_CAPACITY


class _Gate:
    """Holds each piece of lane work that asks it to until a permit lets it finish. The lane runs one
    piece at a time, so each permit lets the work running on it finish."""

    def __init__(self):
        self.permits = threading.Semaphore(0)
        self.ran: list[str] = []
        self.validated: list[str] = []
        # The probe routes' later lane work waits for this event, set in the test's own loop.
        self.proceed: asyncio.Event | None = None
        self.arrived = 0

    def hold(self, name: str) -> None:
        self.ran.append(name)
        if not self.permits.acquire(timeout=WAIT):
            raise TimeoutError("the lane work was never let through")

    def open(self) -> None:
        self.permits.release(10_000)


class _Body(BaseModel):
    name: str


def _drain_the_lane() -> None:
    """Wait until every piece of work on the lane has finished; this one is not counted."""
    blocking._REQUEST_WORK_EXECUTOR.submit(lambda: None).result(timeout=WAIT)


def _leave_the_lane_empty(gate: _Gate) -> None:
    gate.open()
    _drain_the_lane()


@contextlib.contextmanager
def _holding(monkeypatch, module, name: str):
    """Every call of ``module.name`` is held on the lane until the gate lets it finish."""
    _drain_the_lane()
    gate, real = _Gate(), getattr(module, name)

    def held(*args, **kwargs):
        gate.hold(name)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, held)
    try:
        yield gate
    finally:
        _leave_the_lane_empty(gate)


@pytest.fixture
def gate(monkeypatch):
    """The body of a request named held-* is held on the lane, one named fails raises there, and any
    other body is read and validated as before."""
    _drain_the_lane()
    gate, real = _Gate(), request_body.validated_json_body

    def validated(body, content_type, adapter):
        try:
            name = json.loads(body).get("name", "")
        except ValueError:
            name = ""
        gate.validated.append(name)
        if name == "fails":
            raise RuntimeError("lane work failed")
        if name.startswith("held"):
            gate.hold(name)
        return real(body, content_type, adapter)

    monkeypatch.setattr(request_body, "validated_json_body", validated)
    yield gate
    _leave_the_lane_empty(gate)


def _probe_app(gate: _Gate) -> FastAPI:
    probe, router = FastAPI(), APIRouter(route_class=request_body.BoundedJSONRoute)

    @router.post("/lane")
    @request_body.json_body_bounds(request_body.SMALL_BOUNDS)
    async def lane(body: _Body = request_body.json_body_on_lane(_Body)):
        return {"name": body.name}

    @router.post("/lane-then-fails")
    @request_body.json_body_bounds(request_body.SMALL_BOUNDS)
    async def lane_then_fails(body: _Body = request_body.json_body_on_lane(_Body)):
        raise RuntimeError("the endpoint failed after its lane work")

    @router.post("/later")
    @request_body.json_body_bounds(request_body.SMALL_BOUNDS)
    async def later(body: _Body = request_body.json_body_on_lane(_Body)):
        gate.arrived += 1
        await gate.proceed.wait()
        await blocking.run_request_work(gate.hold, "later")
        return {"later": True}

    @router.post("/checked")
    @request_body.json_body_bounds(request_body.SMALL_BOUNDS)
    async def checked(body: _Body = request_body.json_body_on_lane(_Body)):
        gate.arrived += 1
        await gate.proceed.wait()
        try:
            await blocking.run_request_work(gate.hold, "checked", timeout_seconds=0.05)
        except blocking.BlockingWorkTimeout:
            return {"timed_out": True}
        return {"timed_out": False}

    @router.post("/stream")
    @request_body.json_body_bounds(request_body.SMALL_BOUNDS)
    async def stream(body: _Body = request_body.json_body_on_lane(_Body)):
        async def frames():
            yield b"first\n"
            await gate.proceed.wait()
            await blocking.run_request_work(gate.hold, "held-stream")
            yield b"second\n"
        return StreamingResponse(frames())

    @router.post("/counted")
    @request_body.json_body_bounds(request_body.SMALL_BOUNDS)
    async def counted(body: _Body):
        return {"length": len(body.name)}

    probe.include_router(router)
    return probe


class _Request:
    """One request sent straight to an ASGI app, as a server sends it. ``reads`` counts the times the
    app asked for the request's body; a client that is not told to leave stays connected."""

    def __init__(self, app, path="/lane", *, name="probe", body=None, method="POST", incoming=None,
                 send_fails=False, headers=()):
        self.body = json.dumps({"name": name}).encode() if body is None else body
        self.incoming = [{"type": "http.request", "body": self.body, "more_body": False}] \
            if incoming is None else list(incoming)
        self.reads, self.messages, self.send_fails = 0, [], send_fails
        self.leave = asyncio.Event()
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
                 "root_path": "", "client": ("127.0.0.1", 50000), "server": ("probe", 80),
                 "headers": [(b"host", b"probe"), (b"content-type", b"application/json"),
                             (b"content-length", str(len(self.body)).encode()), *headers]}
        self.task = asyncio.create_task(app(scope, self._receive, self._send))

    async def _receive(self):
        self.reads += 1
        if self.incoming:
            return self.incoming.pop(0)
        await self.leave.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message):
        if self.send_fails:
            raise OSError("the client has gone")
        self.messages.append(message)

    @property
    def status(self) -> int:
        return self.messages[0]["status"]

    @property
    def headers(self) -> dict[str, str]:
        return {key.decode().lower(): value.decode() for key, value in self.messages[0]["headers"]}

    def json(self):
        return json.loads(b"".join(message.get("body", b"") for message in self.messages[1:]))


def _stalled(app, path="/lane", **kwargs) -> _Request:
    """A request whose client sends the start of its body and nothing more, until told to leave."""
    return _Request(app, path, incoming=[{"type": "http.request", "body": b'{"na', "more_body": True}], **kwargs)


async def _until(condition) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT
    while not condition():
        assert loop.time() < deadline, "timed out waiting"
        await asyncio.sleep(0.005)


async def _ended(*requests: _Request) -> None:
    await asyncio.wait_for(asyncio.gather(*(request.task for request in requests), return_exceptions=True), WAIT)


def _queued() -> int:
    return blocking._REQUEST_WORK_EXECUTOR._work_queue.qsize()


def _load() -> int:
    return blocking._request_lane_load


async def _fill(app, count=CAPACITY, path="/lane", **kwargs) -> list[_Request]:
    """``count`` requests admitted, each with its first work held on the lane (one running, the others
    waiting), so the lane holds ``count`` pieces of work."""
    requests = [_Request(app, path, name=f"held-{index}", **kwargs) for index in range(count)]
    await _until(lambda: _load() == count)
    return requests


def _assert_refused(request: _Request) -> None:
    assert request.status == 503
    assert request.json() == {"detail": {"code": "request_lane_full"}}
    assert request.headers["retry-after"] == "5"
    assert request.headers["connection"] == "close"
    assert "no-store" in request.headers["cache-control"]


async def _refused_at_once(app, path="/lane", **kwargs) -> _Request:
    load = _load()
    request = _Request(app, path, name="refused", **kwargs)
    await asyncio.wait_for(request.task, AT_ONCE)
    _assert_refused(request)
    assert _load() == load, "none of a refused request's work is submitted"
    return request


def _cold_email_content(monkeypatch) -> bytes:
    """A template draft request for /api/cold-email, from a guest."""
    from backend.routes import cold_email
    from tests.experience_fixtures import confirmed_experience
    from tests.test_email_attribution_routes import OPP, PROFILE, PROJECTS

    async def anonymous(_authorization):
        return None

    monkeypatch.setattr(cold_email, "load_opportunities_by_id", lambda: {OPP["id"]: copy.deepcopy(OPP)})
    monkeypatch.setattr(cold_email, "corpus_version", lambda: "lane-capacity-fixture")
    monkeypatch.setattr(cold_email, "authenticated_uid", anonymous)
    return json.dumps({"profile": PROFILE, "opportunity_id": OPP["id"], "engine": "template",
                       "experience_evidence": confirmed_experience(PROJECTS)}).encode()


# ------------------------------------------------------------------ refused at its first work, admitted again
def test_a_full_lane_refuses_a_request_at_its_first_work_and_admits_one_when_a_place_frees(gate):
    app = _probe_app(gate)

    async def scenario():
        holding = await _fill(app)
        # Answered at once while every admitted request's work still holds the lane.
        await _refused_at_once(app)
        assert _load() == CAPACITY
        gate.permits.release()  # The work running on the lane finishes: its place frees.
        done, _ = await asyncio.wait([request.task for request in holding], timeout=WAIT,
                                     return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == 1
        admitted = _Request(app, name="held-admitted")
        await _until(lambda: _load() == CAPACITY)
        await _refused_at_once(app)
        gate.open()
        await _ended(*holding, admitted)
        # The requests already admitted are answered as before.
        assert [request.status for request in holding + [admitted]] == [200] * (CAPACITY + 1)
        assert sorted(request.json()["name"] for request in holding) == sorted(f"held-{i}" for i in range(CAPACITY))
        assert "refused" not in gate.validated
        assert _load() == 0

    asyncio.run(scenario())


def test_a_refused_request_takes_no_place(gate):
    app = _probe_app(gate)

    async def scenario():
        holding = await _fill(app)
        refused = [_Request(app, name="refused") for _ in range(3 * CAPACITY)]
        await asyncio.wait_for(asyncio.gather(*(request.task for request in refused)), AT_ONCE)
        for request in refused:
            _assert_refused(request)
        assert _load() == CAPACITY
        # One place frees: exactly one more request is admitted, and the next is refused again.
        gate.permits.release()
        await asyncio.wait([request.task for request in holding], timeout=WAIT, return_when=asyncio.FIRST_COMPLETED)
        admitted = _Request(app, name="held-admitted")
        await _until(lambda: _load() == CAPACITY)
        await _refused_at_once(app)
        gate.open()
        await _ended(*holding, admitted)
        assert [request.status for request in holding + [admitted]] == [200] * (CAPACITY + 1)
        assert "refused" not in gate.validated
        assert _load() == 0

    asyncio.run(scenario())


def test_a_request_counts_for_nothing_until_its_first_work_reaches_the_lane(gate):
    """Requests whose bodies have not finished arriving, and admitted requests between their pieces of
    lane work, hold no place: a request is refused only when its first work finds the lane holding
    CAPACITY pieces of work."""
    app = _probe_app(gate)

    async def scenario():
        gate.proceed = asyncio.Event()
        between = [_Request(app, "/later") for _ in range(CAPACITY)]
        await _until(lambda: gate.arrived == CAPACITY)
        stalled = [_stalled(app) for _ in range(CAPACITY)]
        await _until(lambda: all(request.reads == 2 for request in stalled))
        assert _load() == 0
        holding = await _fill(app, CAPACITY - 1)
        admitted = _Request(app, name="held-admitted")
        await _until(lambda: _load() == CAPACITY)
        await _refused_at_once(app)
        for request in stalled:
            request.leave.set()
        gate.proceed.set()
        gate.open()
        await _ended(*stalled, *between, *holding, admitted)
        assert [request.status for request in holding + [admitted]] == [200] * CAPACITY
        assert [request.json() for request in between] == [{"later": True}] * CAPACITY
        assert _load() == 0

    asyncio.run(scenario())


def test_an_admitted_requests_later_work_is_never_refused(gate):
    """Work an admitted request sends to the lane after its first is submitted even when the lane is
    full, and counts: the lane then holds more than its capacity, and new requests are refused."""
    app = _probe_app(gate)

    async def scenario():
        gate.proceed = asyncio.Event()
        later = _Request(app, "/later")
        stream = _Request(app, "/stream")
        await _until(lambda: gate.arrived == 1 and len(stream.messages) == 2)
        holding = await _fill(app)
        await _refused_at_once(app)
        gate.proceed.set()
        await _until(lambda: _load() == CAPACITY + 2)
        await _refused_at_once(app)
        gate.open()
        await _ended(later, stream, *holding)
        assert later.status == 200 and later.json() == {"later": True}
        assert [message.get("body") for message in stream.messages[1:3]] == [b"first\n", b"second\n"]
        assert {"later", "held-stream"} <= set(gate.ran)
        assert [request.status for request in holding] == [200] * CAPACITY
        assert _load() == 0

    asyncio.run(scenario())


def test_a_body_counted_on_the_lane_is_its_requests_first_work(gate):
    """A body past the default body limit is counted on the lane on any JSON route
    (request_body.refuse_container_heavy_body), and that count is the request's first work there."""
    app = _probe_app(gate)
    large = json.dumps({"name": "x" * (request_body.LANE_BODY_BYTES + 1)}).encode()

    async def scenario():
        holding = await _fill(app)
        await _refused_at_once(app, "/counted", body=large)
        gate.open()
        await _ended(*holding)
        admitted = _Request(app, "/counted", body=large)
        await _ended(admitted)
        assert admitted.status == 200 and admitted.json() == {"length": request_body.LANE_BODY_BYTES + 1}
        assert _load() == 0

    asyncio.run(scenario())


# ------------------------------------------------------------------ waits off the lane hold no place
def test_requests_still_sending_their_bodies_leave_the_lane_to_others(monkeypatch):
    """As many cold-email requests as the lane holds, each sending part of its body and then nothing,
    take no place: a draft sent meanwhile is answered."""
    from backend.main import app

    content = _cold_email_content(monkeypatch)

    async def scenario():
        _drain_the_lane()
        stalled = [_stalled(app, "/api/cold-email", body=content) for _ in range(CAPACITY)]
        await _until(lambda: all(request.reads >= 2 for request in stalled))
        assert _load() == 0
        draft = _Request(app, "/api/cold-email", body=content)
        await asyncio.wait_for(draft.task, AT_ONCE)
        assert draft.status == 200 and draft.json()["body"]
        for request in stalled:
            request.leave.set()
        await _ended(*stalled)
        assert not any(request.messages and request.status == 503 for request in stalled)
        assert _load() == 0

    asyncio.run(scenario())


def test_requests_waiting_on_supabase_leave_the_lane_to_others(monkeypatch):
    """As many private requests as the lane holds, each waiting on the Supabase check made before its
    body is parsed (a private save and a private draft check), take no place: a draft sent meanwhile is
    answered."""
    from backend.lib import private_import_targets as storage
    from backend.main import app
    from backend.routes import private_import_targets as private_route

    content = _cold_email_content(monkeypatch)
    waiting, answer = [], None  # The Supabase answer is an event of the test's own loop.

    class SlowSupabase:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *_args, **_kwargs):
            waiting.append(1)
            await answer.wait()
            raise storage.httpx.ConnectTimeout("no answer")

    monkeypatch.setattr(storage, "settings", lambda: ("https://supabase.invalid", "probe-key"))
    monkeypatch.setattr(storage, "new_client", SlowSupabase)
    monkeypatch.setattr(private_route, "new_client", SlowSupabase)
    target = "/api/private-import-targets/00000000-0000-4000-8000-000000000000"
    bearer = [(b"authorization", b"Bearer probe-token")]

    async def scenario():
        nonlocal answer
        answer = asyncio.Event()
        _drain_the_lane()
        private = [_Request(app, target + "/cold-email/validate", headers=bearer) if index % 2 else
                   _Request(app, target, method="PUT", headers=bearer) for index in range(CAPACITY)]
        await _until(lambda: len(waiting) == CAPACITY)
        assert _load() == 0
        draft = _Request(app, "/api/cold-email", body=content)
        await asyncio.wait_for(draft.task, AT_ONCE)
        assert draft.status == 200 and draft.json()["body"]
        answer.set()
        await _ended(*private)
        assert {(request.status, request.json()["detail"]["code"]) for request in private} == \
            {(503, "private_target_unavailable")}
        assert _load() == 0

    asyncio.run(scenario())


# ------------------------------------------------------------------ however a request ends
async def _work_raises(app, gate):
    request = _Request(app, name="fails")
    await _ended(request)
    assert request.status == 500


async def _invalid_json_refused_on_the_lane(app, gate):
    request = _Request(app, body=b'{"name": ')
    await _ended(request)
    assert request.status == 422


async def _refused_by_its_bounds_before_the_lane(app, gate):
    request = _Request(app, body=json.dumps({"name": "probe", "padding": [[]] * 1_001}).encode())
    await _ended(request)
    assert request.status == 422


async def _endpoint_raises_after_its_lane_work(app, gate):
    request = _Request(app, "/lane-then-fails")
    await _ended(request)
    assert request.status == 500


async def _client_disconnects_before_its_body(app, gate):
    request = _Request(app, incoming=[{"type": "http.disconnect"}])
    await _ended(request)
    assert request.reads == 1


async def _client_disconnects_part_way_through_its_body(app, gate):
    request = _stalled(app)
    await _until(lambda: request.reads == 2)
    assert _load() == 0
    request.leave.set()
    await _ended(request)


async def _client_gone_when_the_answer_is_sent(app, gate):
    request = _Request(app, send_fails=True)
    await _ended(request)
    assert isinstance(request.task.exception(), OSError)


async def _cancelled_while_its_body_is_read(app, gate):
    request = _Request(app, incoming=[])
    await _until(lambda: request.reads == 1)
    assert _load() == 0
    request.task.cancel()
    await _ended(request)


async def _cancelled_while_its_work_waits_for_the_lane(app, gate):
    running = _Request(app, name="held-running")
    await _until(lambda: gate.ran == ["held-running"])
    waiting = _Request(app, name="held-waiting")
    await _until(lambda: _queued() == 1)
    assert _load() == 2
    waiting.task.cancel()
    await _ended(waiting)
    await _until(lambda: _load() == 1)
    gate.permits.release()
    await _ended(running)
    assert running.status == 200 and gate.ran == ["held-running"]


async def _cancelled_while_its_work_runs(app, gate):
    running = _Request(app, name="held-running")
    await _until(lambda: gate.ran == ["held-running"])
    running.task.cancel()
    await _ended(running)
    # Work already running finishes on the lane, and counts until then.
    assert _load() == 1
    gate.permits.release()
    await _until(lambda: _load() == 0)


async def _cancelled_between_its_pieces_of_lane_work(app, gate):
    gate.proceed = asyncio.Event()
    request = _Request(app, "/later")
    await _until(lambda: gate.arrived == 1)
    assert _load() == 0
    request.task.cancel()
    await _ended(request)


async def _cancelled_while_its_later_work_waits_for_the_lane(app, gate):
    gate.proceed = asyncio.Event()
    later = _Request(app, "/later")
    await _until(lambda: gate.arrived == 1)
    running = _Request(app, name="held-running")
    await _until(lambda: gate.ran == ["held-running"])
    gate.proceed.set()
    await _until(lambda: _load() == 2)
    later.task.cancel()
    await _ended(later)
    await _until(lambda: _load() == 1)
    gate.permits.release()
    await _ended(running)
    assert gate.ran == ["held-running"]


async def _its_later_work_times_out_waiting_for_the_lane(app, gate):
    gate.proceed = asyncio.Event()
    checked = _Request(app, "/checked")
    await _until(lambda: gate.arrived == 1)  # Its body is read and validated: nothing of it is on the lane.
    running = _Request(app, name="held-running")
    await _until(lambda: gate.ran == ["held-running"])
    gate.proceed.set()
    await _ended(checked)
    assert checked.json() == {"timed_out": True}
    assert _load() == 1
    gate.permits.release()
    await _ended(running)
    assert gate.ran == ["held-running"]


async def _client_leaves_while_the_stream_work_waits_for_the_lane(app, gate):
    gate.proceed = asyncio.Event()
    stream = _Request(app, "/stream")
    await _until(lambda: [message.get("body") for message in stream.messages[1:]] == [b"first\n"])
    running = _Request(app, name="held-running")
    await _until(lambda: gate.ran == ["held-running"])
    gate.proceed.set()
    await _until(lambda: _queued() == 1)
    assert _load() == 2
    stream.leave.set()
    await _ended(stream)
    await _until(lambda: _load() == 1)
    gate.permits.release()
    await _ended(running)
    assert gate.ran == ["held-running"]


@pytest.mark.parametrize("ending", [
    _work_raises, _invalid_json_refused_on_the_lane, _refused_by_its_bounds_before_the_lane,
    _endpoint_raises_after_its_lane_work, _client_disconnects_before_its_body,
    _client_disconnects_part_way_through_its_body, _client_gone_when_the_answer_is_sent,
    _cancelled_while_its_body_is_read, _cancelled_while_its_work_waits_for_the_lane,
    _cancelled_while_its_work_runs, _cancelled_between_its_pieces_of_lane_work,
    _cancelled_while_its_later_work_waits_for_the_lane, _its_later_work_times_out_waiting_for_the_lane,
    _client_leaves_while_the_stream_work_waits_for_the_lane,
], ids=lambda ending: ending.__name__.strip("_"))
def test_no_way_a_request_ends_leaves_its_work_counted(gate, ending):
    app = _probe_app(gate)

    async def scenario():
        await ending(app, gate)
        assert _load() == 0
        # The whole capacity is there: as many requests as it holds are admitted, and one more is not.
        holding = await _fill(app)
        await _refused_at_once(app)
        gate.open()
        await _ended(*holding)
        assert [request.status for request in holding] == [200] * CAPACITY
        assert _load() == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("seed", range(5))
def test_requests_ending_every_way_at_once_leave_no_work_counted(gate, seed):
    """Requests of every kind sent together, some refused, some cancelled at random and the lane let
    through at random: the count never goes below zero, and it returns to zero with the whole
    capacity there."""
    app = _probe_app(gate)
    rng = random.Random(seed)

    async def scenario():
        gate.proceed = asyncio.Event()
        kinds = [
            lambda: _Request(app), lambda: _Request(app, name="held"), lambda: _Request(app, name="fails"),
            lambda: _Request(app, body=b'{"name": '), lambda: _Request(app, "/later"),
            lambda: _Request(app, "/checked"), lambda: _Request(app, "/stream"),
            lambda: _Request(app, incoming=[{"type": "http.disconnect"}]), lambda: _stalled(app),
        ]
        requests = []
        for _ in range(60):
            requests.append(rng.choice(kinds)())
            await asyncio.sleep(rng.random() * 0.002)
            if rng.random() < 0.3:
                rng.choice(requests).task.cancel()
            if rng.random() < 0.2:
                gate.permits.release()
            assert _load() >= 0
        gate.proceed.set()
        for request in requests:
            request.leave.set()
        gate.open()
        await _ended(*requests)
        await _until(lambda: _load() == 0)
        gate.permits = threading.Semaphore(0)
        holding = await _fill(app)
        await _refused_at_once(app)
        gate.open()
        await _ended(*holding)
        assert _load() == 0

    asyncio.run(scenario())


# ------------------------------------------------------------------ the app's routes
def test_normal_concurrent_use_below_the_capacity_is_answered_as_before(monkeypatch):
    """As many template drafts at once as the lane holds are each answered as the same draft alone is,
    their bodies and their drafting run on the lane; only a request whose first work finds the lane
    full is refused."""
    from backend.main import app

    content = _cold_email_content(monkeypatch)

    async def scenario(gate):
        gate.permits.release()
        alone = _Request(app, "/api/cold-email", body=content)
        await _ended(alone)
        assert alone.status == 200 and alone.json()["body"]
        holding = await _fill(app, path="/api/cold-email", body=content)
        await _refused_at_once(app, "/api/cold-email", body=content)
        gate.open()
        await _ended(*holding)

        def answer(request):
            return request.status, {key: value for key, value in request.json().items() if key != "generated_at"}

        assert [answer(request) for request in holding] == [answer(alone)] * CAPACITY
        assert _load() == 0

    with _holding(monkeypatch, request_body, "validated_json_body") as gate:
        asyncio.run(scenario(gate))


def _probe_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-000000000000", path)


def _reads_body_on_lane(route: APIRoute) -> bool:
    """Whether a route's endpoint takes its JSON body on the request lane (json_body_on_lane)."""
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        if hasattr(dependency.call, "json_body_model"):
            return True
        pending.extend(dependency.dependencies)
    return False


def test_every_route_that_works_on_the_lane_refuses_a_request_at_its_first_work(monkeypatch):
    """With no room on the lane, each route that works on it refuses a request when its first work
    reaches the lane (for a private route, after the caller is verified); every other JSON route
    answers as it does with room on the lane."""
    from backend.lib import private_import_targets as storage
    from backend.main import app
    from backend.routes import private_import_targets as private_route

    @contextlib.asynccontextmanager
    async def verified(_authorization, _client_factory):
        yield

    monkeypatch.setattr(storage, "caller_verified_before_parsing", verified)
    monkeypatch.setattr(private_route, "caller_verified_before_parsing", verified)
    monkeypatch.setattr(blocking, "REQUEST_LANE_CAPACITY", 0)
    routes = largest.json_routes(app)
    lane = {(method, path) for method, path, route in routes
            if _reads_body_on_lane(route) or path in largest.FULL_TARGET}
    assert lane == {
        ("POST", "/api/cold-email"), ("POST", "/api/cold-email/stream"), ("POST", "/api/cold-email/variants"),
        ("POST", "/api/cold-email/refine"), ("POST", "/api/cold-email/validate"),
        ("POST", "/api/tailor/full-target/suggestions"), ("POST", "/api/tailor/full-target/selection-plan"),
        ("POST", "/api/resume/full-target/export"), ("PUT", "/api/private-import-targets/{target_id}"),
        ("POST", "/api/private-import-targets/{target_id}/cold-email/variants"),
        ("POST", "/api/private-import-targets/{target_id}/cold-email/validate"),
    }

    async def refusals():
        _drain_the_lane()
        for method, path in sorted(lane):
            request = _Request(app, _probe_path(path), method=method, body=b'{"name": "probe"}',
                               headers=[(b"authorization", b"Bearer probe-token")])
            await asyncio.wait_for(request.task, AT_ONCE)
            _assert_refused(request)
            assert "x-refused-before-work" not in request.headers, (method, path)
        assert _load() == 0

    asyncio.run(refusals())
    # Malformed JSON, which every route refuses before it does any work.
    client = TestClient(app, raise_server_exceptions=False)
    for method, path, _ in routes:
        if (method, path) not in lane:
            response = largest.send(client, method, _probe_path(path), b"[")
            assert "request_lane_full" not in response.text, (method, path)


def test_a_refusal_gives_back_the_global_spend_slot_it_took(monkeypatch):
    """Nothing was spent on a refused request, so the rate limiter gives back the global slot it took.
    The per-client count keeps its slot, as it does for every request that reaches a route
    (backend/main.py RateLimitMiddleware): the refused request's body was read first."""
    from backend import main

    monkeypatch.setattr(main, "RATE_LIMIT_DISABLED", False)
    monkeypatch.setattr(blocking, "REQUEST_LANE_CAPACITY", 0)
    main._rate_buckets.clear()
    main._global_buckets.clear()
    try:
        response = TestClient(main.app).post("/api/tailor/full-target/suggestions", json={"name": "probe"},
                                             headers={"x-forwarded-for": "198.51.100.7"})
        assert response.status_code == 503 and response.json() == {"detail": {"code": "request_lane_full"}}
        assert "x-refused-before-work" not in response.headers
        assert main._global_buckets["llm"] == []
        assert len(main._rate_buckets["198.51.100.7:/api/tailor"]) == 1
    finally:
        main._rate_buckets.clear()
        main._global_buckets.clear()


def test_a_full_target_request_is_admitted_by_its_own_preparation(monkeypatch):
    """The full-target routes read and prepare their body on the lane in their own preparation, their
    first work there; the route's own refusal is private, as its other answers are."""
    from backend.main import app
    from backend.routes import target_resume_ai as route

    bare = FastAPI()  # The route alone, without the app's header middleware.
    bare.include_router(route.router, prefix="/api")
    path = "/api/tailor/full-target/suggestions"
    content = json.dumps({"version": 1, "request_id": "probe", "locale": "en", "document_signature": "v1:sha256:"
                          + "0" * 64, "selected_unit_ids": ["line-1"], "draft": {"kind": "full_resume"}}).encode()

    async def scenario(gate):
        holding = await _fill(app, path=path, body=content)
        await _refused_at_once(app, path, body=content)
        refused = await _refused_at_once(bare, path, body=content)
        assert refused.headers["pragma"] == "no-cache"
        gate.open()
        await _ended(*holding)
        assert [(request.status, request.json()) for request in holding] == \
            [(422, {"detail": {"code": "invalid_full_target_request"}})] * CAPACITY
        assert _load() == 0

    with _holding(monkeypatch, route, "validate_document") as gate:
        asyncio.run(scenario(gate))
