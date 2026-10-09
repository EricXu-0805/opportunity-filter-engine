#!/usr/bin/env python3
"""Measure the results page's first page and one API worker's memory (M27).

Starts the real FastAPI app in this process: one uvicorn server on a
background thread, which is one production API worker. The app loads the
corpus the deployed API loads (the committed shards by default) through its
own lifespan warmup. The script then sends the results page's own first
request, POST /api/matches/view?llm=false with the default view and 50 rows,
for fixed synthetic personas, over real HTTP on 127.0.0.1.

Scenarios, in run order:

  boot              lifespan warmup: read, canonicalize, fit TF-IDF, register
  first             the first first-page request after boot (home school)
  home_cold         home-school first page after the snapshot store is cleared
  home_warm         the same request again, served from its snapshot
  cross_cold        cross-school first page after the snapshot store is cleared
  cross_warm        the same request again
  home_after_cross  a home-school miss right after a cross-school ranking
  cancel            a cross-school request dropped after --cancel-after
                    seconds, then the same profile and a home-school profile
                    sent together while the dropped ranking still runs, then
                    the same profile once more
  concurrent_home   four home-school misses sent at once
  concurrent_mixed  a cross-school miss, then three home-school misses at once
  concurrent_warm   four warm cross-school first pages sent at once
  concurrent_same   four copies of one home-school miss

It also records, without changing app code:

  - where each ranking's time goes (rank, card projection, result-set id), by
    wrapping the route module's and the ranker's own functions;
  - how long /api/health waited during each request: every request on a
    worker shares one event loop and one GIL with the ranking;
  - memory sampled every 50 ms per scenario and the kernel's peak, and, from
    tracemalloc, what one ranking allocates at its peak and what its stored
    snapshot keeps;
  - a cProfile of card projection over a sample of cross-school cards;
  - whether /matches/view gives the same answer for a set of views when it
    reads the canonical records instead of the projected cards, which is what
    projecting only the served page would need.

Output: a table on stdout, then the JSON document (or --json PATH). Nothing
leaves the machine: provider, Supabase and Sentry settings are blanked before
the app is imported, so no model call, database call or error report can
happen, and the material-cleanup loop does not start. The rate limiter is off
so the health probe is not throttled.

Numbers are this machine's. macOS RSS is not Render's Linux RSS (another
allocator; the deploy sets MALLOC_ARENA_MAX=2), so read memory as relative.

    python scripts/measure_match_latency.py --json match-latency.json
"""
from __future__ import annotations

import argparse
import asyncio
import contextvars
import cProfile
import ctypes
import functools
import gc
import io
import json
import os
import platform
import pstats
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Set before the app is imported. load_dotenv never overrides a variable that
# is already set, so a developer's backend/.env cannot switch these back on.
ISOLATION_ENV = {
    "OFE_DISABLE_RATE_LIMIT": "1",
    "OPENROUTER_API_KEY": "",
    "SUPABASE_URL": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "OFE_MATERIAL_ARCHIVE_ENABLED": "0",
    "SENTRY_DSN": "",
}

# What the results page sends for page 1 with no URL parameters:
# MATCH_VIEW_PAGE_SIZE in frontend/src/app/results/use-results-data.ts and the
# fallbacks in readInitialFiltersFromUrl (use-results-url.ts).
PAGE_SIZE = 50
FIRST_PAGE_VIEW = {
    "tab": "high_priority",
    "search_query": "",
    "paid": "",
    "intl": "",
    "source": "",
    "on_campus": "",
    "deadline": "",
    "min_score": 0,
    "scope": "",
    "sort_by": "score",
    "show_dismissed": False,
    "favorite_ids": [],
    "dismissed_ids": [],
}


def _profile(
    key: str,
    *,
    home_school: str,
    school: str,
    year: str,
    major: str,
    college: str,
    interests: str,
    seeking: list[str],
    skills: list[tuple[str, str]],
    coursework: list[str],
    international: bool = False,
) -> dict:
    """A synthetic request body shaped like toProfileRequest (frontend/src/lib/api.ts).

    ``name`` carries the persona key. Nothing that ranks reads it and it is
    not in the snapshot key, so it only lets a ranking be attributed.
    """
    return {
        "name": key,
        "school": school,
        "home_school": home_school,
        "year": year,
        "major": major,
        "college": college,
        "secondary_interests": [],
        "international_student": international,
        "seeking_type": seeking,
        "desired_fields": [part.strip() for part in interests.split(",") if part.strip()],
        "hard_skills": [{"name": name, "level": level} for name, level in skills],
        "coursework": coursework,
        "experience_level": "beginner",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": interests,
        "linkedin_url": "",
        "github_url": "",
        "scholar_url": "",
        "search_weight": 50,
        "exploring": False,
        "include_cross_school": False,
    }


HOME_PERSONAS = {
    "uiuc_cs": _profile(
        "uiuc_cs", home_school="uiuc", school="UIUC", year="sophomore",
        major="Computer Science", college="Grainger College of Engineering",
        interests="machine learning, computer vision, robot perception",
        seeking=["research", "summer_program"],
        skills=[("Python", "experienced"), ("PyTorch", "beginner"), ("C++", "beginner")],
        coursework=["CS 225", "CS 446", "MATH 415"],
    ),
    "uiuc_neuro_intl": _profile(
        "uiuc_neuro_intl", home_school="uiuc", school="UIUC", year="junior",
        major="Molecular and Cellular Biology", college="College of Liberal Arts & Sciences",
        interests="neuroscience, neural circuits, calcium imaging",
        seeking=["research"],
        skills=[("MATLAB", "experienced"), ("Python", "beginner")],
        coursework=["MCB 252", "MCB 461"],
        international=True,
    ),
    "ucb_eecs": _profile(
        "ucb_eecs", home_school="ucb", school="UC Berkeley", year="junior",
        major="Electrical Engineering and Computer Sciences", college="College of Engineering",
        interests="power electronics, control systems, energy storage",
        seeking=["research", "summer_program"],
        skills=[("Python", "experienced"), ("MATLAB", "beginner")],
        coursework=["EECS 16B", "EE 120"],
    ),
    "jhu_public_health": _profile(
        "jhu_public_health", home_school="jhu", school="Johns Hopkins", year="sophomore",
        major="Public Health Studies", college="Krieger School of Arts and Sciences",
        interests="epidemiology, global health, health policy",
        seeking=["research", "internship", "summer_program"],
        skills=[("R", "beginner"), ("Excel", "experienced")],
        coursework=["Introduction to Epidemiology", "Biostatistics"],
    ),
}

CROSS_PERSONAS = {
    "uiuc_cs_cross_all3": {
        **HOME_PERSONAS["uiuc_cs"],
        "name": "uiuc_cs_cross_all3",
        "seeking_type": ["research", "internship", "summer_program"],
        "include_cross_school": True,
    },
    "ucb_eecs_cross": {
        **HOME_PERSONAS["ucb_eecs"],
        "name": "ucb_eecs_cross",
        "include_cross_school": True,
    },
}

PERSONAS = {**HOME_PERSONAS, **CROSS_PERSONAS}

# Views compared on the projected cards and on the canonical records.
PARITY_VIEWS = {
    "first_page": {},
    "tab_all": {"tab": "all"},
    "paid_yes": {"tab": "all", "paid": "yes"},
    "intl_yes": {"tab": "all", "intl": "yes"},
    "on_campus_yes": {"tab": "all", "on_campus": "yes"},
    "deadline_rolling": {"tab": "all", "deadline": "rolling"},
    "deadline_30": {"tab": "all", "deadline": "30"},
    "scope_campus": {"tab": "all", "scope": "campus"},
    "scope_open": {"tab": "all", "scope": "open"},
    "min_score_60": {"tab": "all", "min_score": 60},
    "sort_newest": {"tab": "all", "sort_by": "newest"},
    "sort_deadline": {"tab": "all", "sort_by": "deadline"},
    "search_machine_learning": {"tab": "all", "search_query": "machine learning"},
    "search_ai": {"tab": "all", "search_query": "ai"},
    "search_prof": {"tab": "all", "search_query": "prof"},
    "search_edu": {"tab": "all", "search_query": "edu"},
}

REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("measure_request_id", default=None)
MB = 1024 * 1024


def _log(started: float, message: str) -> None:
    print(f"[{time.perf_counter() - started:7.1f}s] {message}", file=sys.stderr, flush=True)


# --- memory --------------------------------------------------------------------------------


class _TaskVmInfo(ctypes.Structure):
    """struct task_vm_info from <mach/task_info.h>, through its rev3 fields."""

    _pack_ = 4
    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("region_count", ctypes.c_int32),
        ("page_size", ctypes.c_int32),
        ("resident_size", ctypes.c_uint64),
        ("resident_size_peak", ctypes.c_uint64),
        ("device", ctypes.c_uint64),
        ("device_peak", ctypes.c_uint64),
        ("internal", ctypes.c_uint64),
        ("internal_peak", ctypes.c_uint64),
        ("external", ctypes.c_uint64),
        ("external_peak", ctypes.c_uint64),
        ("reusable", ctypes.c_uint64),
        ("reusable_peak", ctypes.c_uint64),
        ("purgeable_volatile_pmap", ctypes.c_uint64),
        ("purgeable_volatile_resident", ctypes.c_uint64),
        ("purgeable_volatile_virtual", ctypes.c_uint64),
        ("compressed", ctypes.c_uint64),
        ("compressed_peak", ctypes.c_uint64),
        ("compressed_lifetime", ctypes.c_uint64),
        ("phys_footprint", ctypes.c_uint64),
        ("min_address", ctypes.c_uint64),
        ("max_address", ctypes.c_uint64),
        ("ledger_phys_footprint_peak", ctypes.c_int64),
        # The kernel fills rev3 only when the whole rev3 block fits.
        ("ledger_rev3_rest", ctypes.c_int64 * 20),
    ]


def _memory_reader():
    """Return (reader, description); reader() gives byte counts or None.

    Linux reads /proc/self/status (VmRSS, VmHWM). macOS asks the kernel for
    task_vm_info: the resident size, and the physical footprint, which also
    counts pages compressed under memory pressure. On a busy Mac those pages
    leave the resident set, so RSS alone undercounts there.
    """
    if sys.platform.startswith("linux") and Path("/proc/self/status").exists():
        def read_linux() -> dict | None:
            values: dict[str, int] = {}
            with open("/proc/self/status", encoding="ascii") as status:
                for line in status:
                    name, _, rest = line.partition(":")
                    if name in ("VmRSS", "VmHWM"):
                        values[name] = int(rest.split()[0]) * 1024
            return {
                "rss": values.get("VmRSS"),
                "rss_peak": values.get("VmHWM"),
                "footprint": None,
                "footprint_peak": None,
            }
        return read_linux, "linux /proc/self/status VmRSS and VmHWM"

    if sys.platform == "darwin":
        try:
            libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            task = ctypes.c_uint32.in_dll(libc, "mach_task_self_").value
            libc.task_info.argtypes = [
                ctypes.c_uint32, ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
            ]
            libc.task_info.restype = ctypes.c_int32
        except (OSError, ValueError, AttributeError):
            libc = None
        if libc is not None:
            task_vm_info = 22
            peak_end = (_TaskVmInfo.ledger_phys_footprint_peak.offset + 8) // 4

            def read_darwin() -> dict | None:
                info = _TaskVmInfo()
                count = ctypes.c_uint32(ctypes.sizeof(info) // 4)
                if libc.task_info(task, task_vm_info, ctypes.byref(info), ctypes.byref(count)) != 0:
                    return None
                return {
                    "rss": info.resident_size,
                    "rss_peak": info.resident_size_peak,
                    "footprint": info.phys_footprint,
                    "footprint_peak": info.ledger_phys_footprint_peak if count.value >= peak_end else None,
                }
            if read_darwin() is not None:
                return read_darwin, "macOS task_info(TASK_VM_INFO) resident_size and phys_footprint"

    def read_nothing() -> dict | None:
        return None
    return read_nothing, "getrusage ru_maxrss only"


def _ru_maxrss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def _mb(value: float | None) -> float | None:
    return None if value is None else round(value / MB, 1)


def _memory_now(reader) -> dict:
    reading = reader() or {}
    return {"rss_mb": _mb(reading.get("rss")), "footprint_mb": _mb(reading.get("footprint"))}


def _settled_memory(reader) -> dict:
    gc.collect()
    return _memory_now(reader)


class MemorySampler(threading.Thread):
    """Samples this process's memory every ``interval`` seconds.

    Each reading counts toward the current scenario and the current phase
    within it (a persona's cold or warm requests), so both have a peak.
    """

    def __init__(self, reader, interval: float = 0.05):
        super().__init__(name="measure-memory", daemon=True)
        self.reader = reader
        self.interval = interval
        self.lock = threading.Lock()
        self.scenario = self.phase = "startup"
        self.peaks: dict[str, dict[str, int]] = {}
        self.stop_event = threading.Event()

    def _sample(self) -> None:
        reading = self.reader()
        if not reading:
            return
        with self.lock:
            for label in {self.scenario, self.phase}:
                peak = self.peaks.setdefault(label, {})
                for name in ("rss", "footprint"):
                    value = reading.get(name)
                    if value is not None and value > peak.get(name, -1):
                        peak[name] = value

    def run(self) -> None:
        while not self.stop_event.wait(self.interval):
            self._sample()

    def set_scenario(self, scenario: str) -> None:
        self._sample()
        with self.lock:
            self.scenario = self.phase = scenario
        self._sample()

    def set_phase(self, phase: str) -> None:
        self._sample()
        with self.lock:
            self.phase = phase
        self._sample()

    def peak(self, phase: str) -> dict | None:
        with self.lock:
            values = self.peaks.get(phase)
            if values is None:
                return None
            values = dict(values)
        return {"rss_mb": _mb(values.get("rss")), "footprint_mb": _mb(values.get("footprint"))}

    def peak_over(self, labels: list[str]) -> dict:
        with self.lock:
            chosen = [self.peaks[label] for label in labels if label in self.peaks]
        rss = max((p.get("rss", 0) for p in chosen), default=0)
        footprint = max((p.get("footprint", 0) for p in chosen), default=0)
        return {"rss_mb": _mb(rss or None), "footprint_mb": _mb(footprint or None)}


# --- instrumentation -----------------------------------------------------------------------


@dataclass
class ComputeRecord:
    """One rule ranking job on the match executor thread."""

    key: str
    persona: str
    scenario: str
    start: float
    universe: int
    end: float | None = None
    visible: int | None = None
    error: str | None = None
    seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))


@dataclass
class RequestRecord:
    """What the server did for one measured request (keyed by x-measure-id)."""

    rid: str
    start: float | None = None
    end: float | None = None
    status: int | None = None
    key: str | None = None
    joined: bool = False
    miss_start: float | None = None
    miss_end: float | None = None
    seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    rows: dict[str, int] = field(default_factory=lambda: defaultdict(int))


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.local = threading.local()
        self.computes: list[ComputeRecord] = []
        self.requests: dict[str, RequestRecord] = {}
        self.boot: dict[str, float] = defaultdict(float)

    def request(self, rid: str) -> RequestRecord:
        with self.lock:
            record = self.requests.get(rid)
            if record is None:
                record = self.requests[rid] = RequestRecord(rid)
            return record

    def compute_for(self, request: RequestRecord) -> ComputeRecord | None:
        """The ranking that answered this miss.

        The first ranking of the same key still running when the miss began
        (one it joined) or started during its wait (its own). A later one is
        another request's ranking of the same key and did not answer this one.
        """
        if request.key is None or request.miss_start is None:
            return None
        wait_end = request.miss_end if request.miss_end is not None else float("inf")
        with self.lock:
            candidates = [
                record for record in self.computes
                if record.key == request.key
                and record.start <= wait_end
                and (record.end is None or record.end >= request.miss_start)
            ]
        return min(candidates, key=lambda record: record.start, default=None)


class Patches:
    def __init__(self) -> None:
        self._originals: list[tuple[object, str, object]] = []

    def wrap(self, module, name: str, make) -> None:
        # getattr raises on a renamed function, so a refactor of the route
        # stops this script instead of leaving its breakdown silently empty.
        original = getattr(module, name)
        setattr(module, name, functools.wraps(original)(make(original)))
        self._originals.append((module, name, original))

    def restore(self) -> None:
        while self._originals:
            module, name, original = self._originals.pop()
            setattr(module, name, original)


def _in_compute(recorder: Recorder, phase: str):
    clock = time.perf_counter
    local = recorder.local

    def make(original):
        def wrapper(*args, **kwargs):
            record = getattr(local, "compute", None)
            if record is None:
                return original(*args, **kwargs)
            started = clock()
            try:
                return original(*args, **kwargs)
            finally:
                record.seconds[phase] += clock() - started
                record.calls[phase] += 1
        return wrapper
    return make


def _in_request(recorder: Recorder, phase: str, rows=None):
    clock = time.perf_counter

    def make(original):
        def wrapper(*args, **kwargs):
            rid = REQUEST_ID.get()
            if rid is None:
                return original(*args, **kwargs)
            started = clock()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = clock() - started
                record = recorder.request(rid)
                with recorder.lock:
                    record.seconds[phase] += elapsed
                    if rows is not None:
                        record.rows[phase] += rows(args)
        return wrapper
    return make


def _boot_phase(recorder: Recorder, phase: str):
    def make(original):
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                recorder.boot[phase] += time.perf_counter() - started
        return wrapper
    return make


def _install(recorder: Recorder, patches: Patches, breakdown: bool, sampler: MemorySampler) -> None:
    from backend import data_loader
    from backend import main as app_main
    from backend.routes import matches
    from src.matcher import ranker

    clock = time.perf_counter

    def compute(original):
        def wrapper(*args, **kwargs):
            key, profile, _identity, opportunities = args[:4]
            record = ComputeRecord(
                key=key,
                persona=str(profile.get("name") or "?"),
                scenario=sampler.scenario,
                start=clock(),
                universe=len(opportunities),
            )
            with recorder.lock:
                recorder.computes.append(record)
            recorder.local.compute = record
            try:
                snapshot = original(*args, **kwargs)
                record.visible = len(snapshot.visible)
                return snapshot
            except BaseException as exc:
                record.error = type(exc).__name__
                raise
            finally:
                record.end = clock()
                recorder.local.compute = None
        return wrapper

    def miss(original):
        async def wrapper(*args, **kwargs):
            rid = REQUEST_ID.get()
            if rid is None:
                return await original(*args, **kwargs)
            key, _profile, corpus_identity = args[:3]
            with matches._match_inflight_lock:
                joined = (key, corpus_identity) in matches._match_inflight
            record = recorder.request(rid)
            record.key, record.joined, record.miss_start = key, joined, clock()
            try:
                return await original(*args, **kwargs)
            finally:
                record.miss_end = clock()
        return wrapper

    patches.wrap(matches, "_compute_rule_snapshot", compute)
    patches.wrap(matches, "_get_or_compute_rule_snapshot", miss)
    patches.wrap(matches, "load_opportunities_generation", _in_request(recorder, "corpus_lookup"))
    patches.wrap(matches, "release_visible_opportunities", _in_request(recorder, "release_filter"))
    patches.wrap(matches, "actionable_opportunities", _in_request(recorder, "actionable_filter"))
    patches.wrap(matches, "_apply_match_view", _in_request(recorder, "view_pass", rows=lambda args: len(args[0])))
    patches.wrap(matches, "_match_result_response", _in_request(recorder, "page_rows", rows=lambda args: 1))
    patches.wrap(matches, "rank_visible_universe", _in_compute(recorder, "rank"))
    patches.wrap(matches, "_match_card", _in_compute(recorder, "cards"))
    patches.wrap(matches, "_result_set_id", _in_compute(recorder, "result_set_id"))
    patches.wrap(matches, "_store_snapshot", _in_compute(recorder, "store"))
    if breakdown:
        patches.wrap(ranker, "hard_exclusion", _in_compute(recorder, "hard_exclusion"))
        patches.wrap(ranker, "score_eligibility", _in_compute(recorder, "eligibility"))
        patches.wrap(ranker, "_chunk_similarities", _in_compute(recorder, "tfidf"))
        patches.wrap(ranker, "_rank_opportunity_unlocked", _in_compute(recorder, "score"))
        patches.wrap(ranker, "_build_opp_static", _in_compute(recorder, "static_builds"))
    patches.wrap(app_main, "_warmup", _boot_phase(recorder, "warmup"))
    patches.wrap(data_loader, "load_opportunities_by_id", _boot_phase(recorder, "load"))
    patches.wrap(data_loader, "_canonicalize_corpus", _boot_phase(recorder, "canonicalize"))
    patches.wrap(data_loader, "_maybe_fit_tfidf", _boot_phase(recorder, "fit_tfidf"))
    patches.wrap(ranker, "_register_corpus_unlocked", _boot_phase(recorder, "register_matrix"))


def _wrapper_overhead_seconds() -> float:
    """Per-call cost of an _in_compute wrapper, to size the breakdown's own overhead."""
    recorder = Recorder()
    recorder.local.compute = ComputeRecord(key="", persona="", scenario="", start=0.0, universe=0)

    def plain(value):
        return value
    wrapped = _in_compute(recorder, "probe")(plain)
    calls = 200_000
    started = time.perf_counter()
    for index in range(calls):
        plain(index)
    baseline = time.perf_counter() - started
    started = time.perf_counter()
    for index in range(calls):
        wrapped(index)
    return max(0.0, (time.perf_counter() - started - baseline) / calls)


class MeasuredApp:
    """ASGI wrapper naming each request by its x-measure-id header."""

    def __init__(self, app, recorder: Recorder):
        self.app = app
        self.recorder = recorder

    async def __call__(self, scope, receive, send):
        rid = None
        if scope["type"] == "http":
            for name, value in scope.get("headers", []):
                if name == b"x-measure-id":
                    rid = value.decode("latin-1")
        if rid is None:
            await self.app(scope, receive, send)
            return
        record = self.recorder.request(rid)
        token = REQUEST_ID.set(rid)
        record.start = time.perf_counter()

        async def tracking_send(message):
            if message["type"] == "http.response.start":
                record.status = message["status"]
            await send(message)
        try:
            await self.app(scope, receive, tracking_send)
        finally:
            record.end = time.perf_counter()
            REQUEST_ID.reset(token)


# --- server and client ---------------------------------------------------------------------


class ServerThread:
    def __init__(self, app, port: int):
        import uvicorn

        self.config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            lifespan="on",
            log_level="warning",
            access_log=False,
            # Idle gaps between scenarios outlast the 5 s default; a reused
            # connection the server just closed would surface as a client error.
            timeout_keep_alive=600,
        )
        self.server = uvicorn.Server(self.config)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="measure-uvicorn", daemon=True)
        self.error: BaseException | None = None

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.server.serve())
        except BaseException as exc:  # reported by start()
            self.error = exc

    def start(self, timeout: float) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.thread.is_alive():
                raise RuntimeError(f"server stopped during startup: {self.error!r}")
            if time.monotonic() > deadline:
                raise TimeoutError("server did not finish its lifespan warmup in time")
            time.sleep(0.05)

    @property
    def port(self) -> int:
        return self.server.servers[0].sockets[0].getsockname()[1]

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=60)


@dataclass
class Sample:
    scenario: str
    persona: str
    rid: str
    note: str | None = None
    t_start: float | None = None
    t_end: float | None = None
    wall_start: float | None = None
    wall_end: float | None = None
    status: int | None = None
    error: str | None = None
    payload: dict | None = None
    response_bytes: int = 0


# A separate process, so its own requests do not compete with the server for
# this interpreter's GIL the way an in-process client would.
PROBE_PROGRAM = r"""
import http.client, sys, time
port, interval = int(sys.argv[1]), float(sys.argv[2])
connection = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
while True:
    started = time.time()
    try:
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        response.read()
        status = response.status
    except Exception:
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
        status = 0
    print(f"{started:.6f} {time.time() - started:.6f} {status}", flush=True)
    time.sleep(interval)
"""


class HealthProbe:
    """GETs /api/health from a child process, one at a time, every ``interval`` seconds."""

    def __init__(self, port: int, interval: float = 0.2):
        self.samples: list[tuple[float, float, int]] = []
        self.process = subprocess.Popen(
            [sys.executable, "-c", PROBE_PROGRAM, str(port), str(interval)],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.reader = threading.Thread(target=self._read, name="measure-health", daemon=True)
        self.reader.start()

    def _read(self) -> None:
        for line in self.process.stdout:
            started, wait, status = line.split()
            self.samples.append((float(started), float(wait), int(status)))

    def stop(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)
        self.reader.join(timeout=5)

    def window(self, start: float | None, end: float | None) -> dict:
        """Probes sent between two wall-clock times."""
        if start is None or end is None:
            return {"probes": 0, "max_ms": None}
        waits = [wait for begun, wait, _ in list(self.samples) if start <= begun <= end]
        if not waits:
            return {"probes": 0, "max_ms": None}
        return {"probes": len(waits), "max_ms": round(max(waits) * 1000, 1)}


# --- run -----------------------------------------------------------------------------------


class Run:
    def __init__(self, args, recorder: Recorder, sampler: MemorySampler, reader, started: float):
        self.args = args
        self.recorder = recorder
        self.sampler = sampler
        self.reader = reader
        self.started = started
        self.samples: list[Sample] = []
        self.scenarios: list[dict] = []
        self.counter = 0
        self.today = date.today().isoformat()
        self.client = None
        self.probe: HealthProbe | None = None
        self.kernel_peak_serving: dict = {}

    def log(self, message: str) -> None:
        _log(self.started, message)

    def new_sample(self, scenario: str, persona: str, note: str | None = None) -> Sample:
        self.counter += 1
        sample = Sample(scenario=scenario, persona=persona, rid=f"{scenario}:{persona}:{self.counter}", note=note)
        self.samples.append(sample)
        return sample

    async def send(self, sample: Sample) -> Sample:
        body = {
            "profile": PERSONAS[sample.persona],
            "view": {**FIRST_PAGE_VIEW, "today": self.today},
            "page_size": PAGE_SIZE,
            "cursor": None,
        }
        sample.wall_start, sample.t_start = time.time(), time.perf_counter()
        try:
            response = await self.client.post(
                "/api/matches/view",
                params={"llm": "false"},
                json=body,
                headers={"x-measure-id": sample.rid},
            )
            sample.status = response.status_code
            sample.response_bytes = len(response.content)
            payload = response.json()
            if response.status_code == 200:
                sample.payload = {
                    name: payload.get(name)
                    for name in (
                        "total", "filtered_total", "returned_count", "high_priority",
                        "good_match", "reach", "low_fit", "result_set_id",
                    )
                }
            else:
                detail = payload.get("detail") if isinstance(payload, dict) else None
                sample.error = detail.get("code") if isinstance(detail, dict) else str(detail)
        except asyncio.CancelledError:
            sample.error = "cancelled"
            raise
        except Exception as exc:  # recorded; the run goes on
            sample.error = type(exc).__name__
        finally:
            sample.wall_end, sample.t_end = time.time(), time.perf_counter()
        return sample

    async def first_page(self, scenario: str, persona: str, note: str | None = None) -> Sample:
        return await self.send(self.new_sample(scenario, persona, note))

    async def idle(self, timeout: float = 900.0) -> float:
        """Wait until no ranking is queued or running; return how long that took."""
        from backend.routes import matches

        started = time.perf_counter()
        while True:
            with matches._match_inflight_lock:
                busy = bool(matches._match_inflight)
            if not busy:
                return time.perf_counter() - started
            if time.perf_counter() - started > timeout:
                raise TimeoutError("the match executor stayed busy")
            await asyncio.sleep(0.02)

    async def ranking_started(self, request: asyncio.Task, timeout: float = 10.0) -> None:
        """Wait until ``request`` has a ranking queued or running, or has finished."""
        from backend.routes import matches

        started = time.perf_counter()
        while not request.done() and time.perf_counter() - started < timeout:
            with matches._match_inflight_lock:
                if matches._match_inflight:
                    return
            await asyncio.sleep(0.005)

    def clear_snapshots(self) -> None:
        from backend.routes import matches

        with matches._match_inflight_lock:
            matches._match_snapshots.clear()

    def stored_snapshots(self) -> list:
        from backend.routes import matches

        with matches._match_inflight_lock:
            return list(matches._match_snapshots.values())

    def snapshot_by_result_set(self, result_set_id: str):
        from backend.routes import matches

        with matches._match_inflight_lock:
            for snapshot in matches._match_snapshots.values():
                if snapshot.result_set_id == result_set_id:
                    return snapshot
        return None

    async def scenario(self, name: str, runner) -> None:
        await self.idle()
        self.sampler.set_scenario(name)
        before = len(self.samples)
        wall_start, started = time.time(), time.perf_counter()
        extra = await runner()
        await self.idle()
        wall_end, ended = time.time(), time.perf_counter()
        self.sampler.set_scenario("between")
        self.scenarios.append({
            "name": name,
            "seconds": round(ended - started, 3),
            "wall_start": wall_start,
            "wall_end": wall_end,
            "samples": len(self.samples) - before,
            **(extra or {}),
        })
        self.log(f"{name}: {ended - started:.1f}s")

    # -- scenario bodies --

    async def cold_then_warm(self, persona: str, cold: str, warm: str, cold_n: int, warm_n: int) -> None:
        self.sampler.set_phase(f"{cold}:{persona}")
        for _ in range(cold_n):
            await self.idle()
            self.clear_snapshots()
            await self.first_page(cold, persona)
        await self.idle()
        if warm_n:
            self.sampler.set_phase(f"{warm}:{persona}")
            for _ in range(warm_n):
                await self.first_page(warm, persona)
        self.sampler.set_phase(self.sampler.scenario)

    async def cancel(self) -> dict:
        cross = next(iter(CROSS_PERSONAS))
        home = list(HOME_PERSONAS)[1]
        self.clear_snapshots()
        dropped_sample = self.new_sample("cancel", cross, note="dropped")
        dropped = asyncio.create_task(self.send(dropped_sample))
        await asyncio.sleep(self.args.cancel_after)
        cancelled_at = time.perf_counter()
        finished_first = dropped.done()
        if not finished_first:
            dropped.cancel()
            try:
                await dropped
            except asyncio.CancelledError:
                pass
        await asyncio.gather(
            self.first_page("cancel", cross, note="resent"),
            self.first_page("cancel", home, note="queued"),
        )
        await self.idle()
        await self.first_page("cancel", cross, note="after")
        request = self.recorder.requests.get(dropped_sample.rid)
        compute = self.recorder.compute_for(request) if request is not None else None
        busy = None
        if not finished_first and compute is not None and compute.end is not None:
            busy = round(compute.end - cancelled_at, 3)
        return {
            "cancel_after_s": self.args.cancel_after,
            "finished_before_cancel": finished_first,
            "dropped_ranking_ran_on_s": busy,
            "dropped_ranking_s": round(compute.end - compute.start, 3)
            if compute is not None and compute.end is not None else None,
        }

    async def concurrent(self, name: str, personas: list[str], lead: str | None = None) -> None:
        self.clear_snapshots()
        tasks = []
        if lead is not None:
            tasks.append(asyncio.create_task(self.first_page(name, lead, note="lead")))
            await self.ranking_started(tasks[0])
        tasks.extend(asyncio.create_task(self.first_page(name, persona)) for persona in personas)
        await asyncio.gather(*tasks)

    async def concurrent_warm(self, persona: str) -> None:
        await self.first_page("concurrent_warm", persona, note="prime")
        await self.idle()
        await asyncio.gather(*(self.first_page("concurrent_warm", persona) for _ in range(4)))

    async def trace_memory(self, persona: str) -> dict:
        """Python allocations one ranking makes and keeps, from tracemalloc.

        Tracing slows every allocation, so this request's latency is reported
        nowhere. Only memory allocated while tracing counts, so the corpus
        loaded at boot is not in these figures.
        """
        await self.idle()
        self.clear_snapshots()
        gc.collect()
        tracemalloc.start()
        try:
            sample = await self.first_page("memory_trace", persona, note="traced, timing not comparable")
            # A traced cross-school ranking can outlast the route's timeout;
            # it still finishes and stores its snapshot, the only one stored.
            await self.idle()
            gc.collect()
            kept, peak = tracemalloc.get_traced_memory()
            stored = self.stored_snapshots()
            rows = sum(len(snapshot.visible) for snapshot in stored)
            for snapshot in stored:
                snapshot.opportunities_by_id.clear()
            # The loop variable would otherwise keep the last snapshot, and
            # with it the ranked rows, alive past clear_snapshots below.
            stored = snapshot = None
            gc.collect()
            without_cards, _ = tracemalloc.get_traced_memory()
            self.clear_snapshots()
            gc.collect()
            without_snapshot, _ = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return {
            "persona": persona,
            "status": sample.status or sample.error,
            "snapshot_rows": rows,
            "peak_mb": _mb(peak),
            "kept_after_request_mb": _mb(kept),
            "snapshot_mb": _mb(kept - without_snapshot),
            "snapshot_cards_mb": _mb(kept - without_cards),
            "kept_outside_snapshot_mb": _mb(without_snapshot),
        }


def _unwrapped(function):
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__
    return function


def _profile_cards(snapshot, limit: int) -> dict | None:
    """cProfile the card projection itself over ``limit`` visible rows."""
    from backend import data_loader
    from backend.routes import matches

    if snapshot is None or limit <= 0:
        return None
    by_id = _unwrapped(data_loader.load_opportunities_by_id)()
    records = [by_id[result.opportunity_id] for result in snapshot.visible[:limit] if result.opportunity_id in by_id]
    if not records:
        return None
    project = _unwrapped(matches._match_card)
    started = time.perf_counter()
    for record in records:
        project(record)
    unprofiled = time.perf_counter() - started
    profiler = cProfile.Profile()
    profiler.enable()
    for record in records:
        project(record)
    profiler.disable()
    stats = pstats.Stats(profiler, stream=io.StringIO())
    code = project.__code__
    own = stats.stats.get((code.co_filename, code.co_firstlineno, code.co_name))
    total = own[3] if own else stats.total_tt
    rows = []
    for (filename, line, function), (_cc, _nc, _tt, cumulative, _callers) in stats.stats.items():
        if (filename, line, function) == (code.co_filename, code.co_firstlineno, code.co_name):
            continue
        rows.append({
            "function": f"{Path(filename).name}:{line}:{function}",
            "share_of_projection": round(cumulative / total, 3) if total else None,
        })
    rows.sort(key=lambda row: row["share_of_projection"] or 0, reverse=True)
    return {
        "cards": len(records),
        "microseconds_per_card": round(unprofiled / len(records) * 1e6, 1),
        "top_by_inclusive_share": rows[:15],
    }


def _view_parity(snapshot, home_school: str, today: str) -> list[dict]:
    """Run /matches/view's own pass over the cards and over the canonical records."""
    from backend import data_loader
    from backend.routes import matches
    from backend.schemas import MatchViewState

    if snapshot is None:
        return []
    apply = _unwrapped(matches._apply_match_view)
    canonical = _unwrapped(data_loader.load_opportunities_by_id)()
    out = []
    for name, overrides in PARITY_VIEWS.items():
        view = MatchViewState(**{**FIRST_PAGE_VIEW, **overrides, "today": today})
        started = time.perf_counter()
        on_cards = apply(snapshot.visible, snapshot.opportunities_by_id, view, home_school)
        cards_seconds = time.perf_counter() - started
        started = time.perf_counter()
        on_canonical = apply(snapshot.visible, canonical, view, home_school)
        canonical_seconds = time.perf_counter() - started
        card_ids = [result.opportunity_id for result in on_cards[0]]
        canonical_ids = [result.opportunity_id for result in on_canonical[0]]
        first_difference = next(
            (index for index, (left, right) in enumerate(zip(card_ids, canonical_ids, strict=False)) if left != right),
            None if len(card_ids) == len(canonical_ids) else min(len(card_ids), len(canonical_ids)),
        )
        out.append({
            "view": name,
            "rows_on_cards": len(card_ids),
            "rows_on_canonical": len(canonical_ids),
            "ids_only_on_cards": len(set(card_ids) - set(canonical_ids)),
            "ids_only_on_canonical": len(set(canonical_ids) - set(card_ids)),
            "first_order_difference": first_difference,
            "tab_counts_equal": on_cards[1] == on_canonical[1],
            "source_facets_equal": on_cards[2] == on_canonical[2],
            "scope_available_equal": on_cards[3] == on_canonical[3],
            "deadline_facets_equal": on_cards[4] == on_canonical[4],
            "seconds_on_cards": round(cards_seconds, 3),
            "seconds_on_canonical": round(canonical_seconds, 3),
        })
    return out


def _round_map(values: dict[str, float], digits: int = 3) -> dict[str, float]:
    return {name: round(value, digits) for name, value in sorted(values.items())}


def _sample_record(run: Run, sample: Sample, overhead: float) -> dict:
    request = run.recorder.requests.get(sample.rid)
    compute = run.recorder.compute_for(request) if request is not None else None
    record = {
        "scenario": sample.scenario,
        "persona": sample.persona,
        "note": sample.note,
        "status": sample.status,
        "error": sample.error,
        "latency_s": round(sample.t_end - sample.t_start, 3)
        if sample.t_end is not None and sample.t_start is not None else None,
        "response_bytes": sample.response_bytes,
        "health": run.probe.window(sample.wall_start, sample.wall_end),
        **(sample.payload or {}),
    }
    if request is not None:
        served_from = "snapshot"
        if request.key is not None:
            served_from = "joined_ranking" if request.joined else "new_ranking"
        record.update({
            "server_s": round(request.end - request.start, 3)
            if request.end is not None and request.start is not None else None,
            "server_status": request.status,
            "served_from": served_from,
            "ranking_wait_s": round(request.miss_end - request.miss_start, 3)
            if request.miss_end is not None and request.miss_start is not None else None,
            "request_phases_s": _round_map(request.seconds),
            "view_rows": request.rows.get("view_pass"),
        })
    if compute is not None and request is not None and request.miss_start is not None:
        wrapped_calls = sum(count for phase, count in compute.calls.items() if phase != "rank")
        record["ranking"] = {
            "persona": compute.persona,
            "queue_wait_s": round(max(0.0, compute.start - request.miss_start), 3),
            "executor_s": round(compute.end - compute.start, 3) if compute.end is not None else None,
            "universe": compute.universe,
            "visible": compute.visible,
            "error": compute.error,
            "phases_s": _round_map(compute.seconds),
            "calls": dict(sorted(compute.calls.items())),
            "instrumentation_overhead_s": round(wrapped_calls * overhead, 3),
        }
    return record


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _summary(records: list[dict], sampler: MemorySampler) -> list[dict]:
    groups: dict[tuple[str, str, str | None], list[dict]] = defaultdict(list)
    for record in records:
        groups[(record["scenario"], record["persona"], record.get("note"))].append(record)
    rows = []
    for (scenario, persona, note), items in groups.items():
        latencies = [item["latency_s"] for item in items if item.get("latency_s") is not None]
        rankings = [item["ranking"] for item in items if item.get("ranking")]
        views = [
            item["request_phases_s"]["view_pass"]
            for item in items if "view_pass" in item.get("request_phases_s", {})
        ]
        health = [item["health"]["max_ms"] for item in items if item["health"]["max_ms"] is not None]
        statuses: dict[str, int] = defaultdict(int)
        for item in items:
            statuses[str(item.get("status") or item.get("error"))] += 1
        peak = sampler.peak(f"{scenario}:{persona}") or sampler.peak(scenario) or {}
        rows.append({
            "scenario": scenario,
            "persona": persona + (f" ({note})" if note else ""),
            "n": len(items),
            "status": ",".join(f"{status}x{count}" if count > 1 else status for status, count in statuses.items()),
            "latency_p50_s": _median(latencies),
            "latency_max_s": round(max(latencies), 3) if latencies else None,
            "queue_wait_s": _median([r["queue_wait_s"] for r in rankings]),
            "executor_s": _median([r["executor_s"] for r in rankings if r.get("executor_s") is not None]),
            "rank_s": _median([r["phases_s"].get("rank", 0.0) for r in rankings]),
            "cards_s": _median([r["phases_s"].get("cards", 0.0) for r in rankings]),
            "view_pass_s": _median(views),
            "visible_rows": next((item.get("total") for item in items if item.get("total") is not None), None),
            "health_max_ms": max(health) if health else None,
            "peak_rss_mb": peak.get("rss_mb"),
            "peak_footprint_mb": peak.get("footprint_mb"),
        })
    return rows


TABLE_COLUMNS = (
    ("scenario", "scenario", 16),
    ("persona", "persona", 29),
    ("n", "n", 2),
    ("status", "status", 9),
    ("latency_p50_s", "p50 s", 6),
    ("latency_max_s", "max s", 6),
    ("queue_wait_s", "queue s", 7),
    ("executor_s", "exec s", 6),
    ("rank_s", "rank s", 6),
    ("cards_s", "cards s", 7),
    ("view_pass_s", "view s", 6),
    ("visible_rows", "rows", 6),
    ("health_max_ms", "health ms", 9),
    ("peak_rss_mb", "RSS MB", 7),
    ("peak_footprint_mb", "foot MB", 7),
)


def _table(rows: list[dict]) -> str:
    def cell(value) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.3f}" if value < 10 else f"{value:.1f}"
        return str(value)

    lines = ["  ".join(title.ljust(width) for _, title, width in TABLE_COLUMNS)]
    lines.append("  ".join("-" * width for _, _, width in TABLE_COLUMNS))
    for row in rows:
        lines.append("  ".join(cell(row.get(key)).ljust(width) for key, _, width in TABLE_COLUMNS))
    return "\n".join(lines)


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _point_loader_at(data_dir: Path, corpus: str) -> tuple[str, Path | None]:
    """Choose the files the loader reads. Returns (source, temporary directory)."""
    from backend import data_loader

    data_loader.DATA_DIR = data_dir
    work_file = data_dir / "opportunities.json"
    shards = data_dir / "shards"
    has_shards = shards.is_dir() and any(shards.glob("*.json"))
    if work_file.exists() and corpus == "shards":
        if not has_shards:
            raise SystemExit(f"--corpus shards: no shards under {shards}")
        # The loader prefers an assembled work file, which the deployed API
        # never has. A directory holding only a link to the shards makes it
        # read them the way production does.
        holder = Path(tempfile.mkdtemp(prefix="ofe-measure-"))
        (holder / "shards").symlink_to(shards.resolve(), target_is_directory=True)
        data_loader.DATA_DIR = holder
        return "shards", holder
    if work_file.exists():
        return "work file", None
    if has_shards:
        return "shards", None
    return "examples fallback", None


async def _drive(run: Run, server: ServerThread) -> dict:
    import httpx

    from backend.routes import matches

    args = run.args
    timeout = httpx.Timeout(max(240.0, matches._MATCH_TIMEOUT_SECONDS * 3))
    base_url = f"http://127.0.0.1:{server.port}"
    home = list(HOME_PERSONAS)
    cross = list(CROSS_PERSONAS)
    diagnostics: dict = {}
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        run.client = client
        run.probe = HealthProbe(server.port)
        try:
            async def first():
                await run.first_page("first", home[0])

            async def home_cold():
                for persona in home:
                    await run.cold_then_warm(persona, "home_cold", "home_warm", args.repeats, args.warm_repeats)

            async def cross_cold():
                for persona in cross:
                    await run.cold_then_warm(persona, "cross_cold", "cross_warm", args.cross_repeats, args.warm_repeats)

            async def home_after_cross():
                await run.cold_then_warm(home[0], "home_after_cross", "home_warm", 1, 0)

            async def concurrent_home():
                await run.concurrent("concurrent_home", home[:4])

            async def concurrent_mixed():
                await run.concurrent("concurrent_mixed", home[:3], lead=cross[0])

            async def concurrent_warm():
                await run.concurrent_warm(cross[0])

            async def concurrent_same():
                await run.concurrent("concurrent_same", [home[0]] * 4)

            await run.scenario("first", first)
            await run.scenario("home_cold", home_cold)
            await run.scenario("cross_cold", cross_cold)
            await run.scenario("home_after_cross", home_after_cross)
            await run.scenario("cancel", run.cancel)
            await run.scenario("concurrent_home", concurrent_home)
            await run.scenario("concurrent_mixed", concurrent_mixed)
            await run.scenario("concurrent_warm", concurrent_warm)

            run.kernel_peak_serving = run.reader() or {}
            lead = next((s for s in reversed(run.samples) if s.persona == cross[0] and s.payload), None)
            snapshot = run.snapshot_by_result_set(lead.payload["result_set_id"]) if lead else None
            run.sampler.set_scenario("diagnostics")
            run.log("profiling card projection and comparing views on the canonical records")
            diagnostics = {
                "snapshot_persona": cross[0] if snapshot is not None else None,
                "snapshot_visible_rows": len(snapshot.visible) if snapshot is not None else None,
                "card_projection_profile": _profile_cards(snapshot, args.profile_cards),
                "view_parity": _view_parity(snapshot, PERSONAS[cross[0]]["home_school"], run.today)
                if args.view_parity else [],
            }
            snapshot = None
            run.sampler.set_scenario("between")

            await run.scenario("concurrent_same", concurrent_same)

            if args.trace_memory:
                run.sampler.set_scenario("memory_trace")
                run.log("tracing what one ranking allocates and keeps (slow by design)")
                diagnostics["memory_trace"] = [
                    await run.trace_memory(home[0]),
                    await run.trace_memory(cross[0]),
                ]
                run.sampler.set_scenario("between")
        finally:
            run.probe.stop()
    return diagnostics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", type=Path, help="write the JSON document here instead of stdout")
    parser.add_argument("--port", type=int, default=0, help="loopback port for the server (default: any free port)")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "processed")
    parser.add_argument(
        "--corpus", choices=("shards", "auto"), default="shards",
        help="shards (default): read the shards as production does, even if an assembled work file exists",
    )
    parser.add_argument("--repeats", type=int, default=3, help="cold samples per home-school persona")
    parser.add_argument("--cross-repeats", type=int, default=1, help="cold samples per cross-school persona")
    parser.add_argument("--warm-repeats", type=int, default=3, help="warm samples per persona")
    parser.add_argument("--cancel-after", type=float, default=5.0, help="seconds before the cancel scenario drops")
    parser.add_argument("--profile-cards", type=int, default=2000, help="cards to cProfile (0 skips)")
    parser.add_argument("--no-view-parity", dest="view_parity", action="store_false")
    parser.add_argument(
        "--no-trace-memory", dest="trace_memory", action="store_false",
        help="skip the tracemalloc pass (one home-school and one cross-school ranking, traced)",
    )
    parser.add_argument(
        "--no-breakdown", dest="breakdown", action="store_false",
        help="skip the per-record ranker wrappers (keeps the per-ranking ones)",
    )
    parser.add_argument("--startup-timeout", type=float, default=900.0)
    args = parser.parse_args(argv)
    for name in ("repeats", "cross_repeats"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")

    started = time.perf_counter()
    for name, value in ISOLATION_ENV.items():
        os.environ[name] = value
    reader, memory_source = _memory_reader()
    sampler = MemorySampler(reader)
    sampler.start()
    load_start = os.getloadavg() if hasattr(os, "getloadavg") else None
    memory_marks = {"interpreter": _memory_now(reader)}

    import_started = time.perf_counter()
    from backend import data_loader
    from backend import main as app_main
    from backend.routes import matches
    import_seconds = time.perf_counter() - import_started
    memory_marks["after_imports"] = _settled_memory(reader)

    if matches._SNAPSHOT_TTL_SECONDS <= 0:
        _log(started, "warning: OFE_MATCH_SNAPSHOT_TTL is 0, so every warm request ranks again")
    corpus_source, holder = _point_loader_at(args.data_dir.resolve(), args.corpus)
    recorder = Recorder()
    patches = Patches()
    _install(recorder, patches, args.breakdown, sampler)
    overhead = _wrapper_overhead_seconds() if args.breakdown else 0.0
    run = Run(args, recorder, sampler, reader, started)
    server = ServerThread(MeasuredApp(app_main.app, recorder), args.port)
    _log(started, f"booting the app on the {corpus_source} under {args.data_dir}")
    sampler.set_scenario("boot")
    boot_started = time.perf_counter()
    try:
        server.start(args.startup_timeout)
        boot_seconds = time.perf_counter() - boot_started
        boot_phases = dict(recorder.boot)
        sampler.set_scenario("between")
        corpus, _token = data_loader.load_opportunities_generation()
        records = len(corpus)
        corpus = None
        memory_marks["after_boot"] = _settled_memory(reader)
        _log(started, f"boot: {boot_seconds:.1f}s, {records:,} records, port {server.port}")
        if records == 0:
            raise SystemExit("the app loaded no corpus")

        diagnostics = asyncio.run(_drive(run, server))

        memory_marks["end_with_snapshots"] = _settled_memory(reader)
        with matches._match_inflight_lock:
            stored = len(matches._match_snapshots)
            matches._match_snapshots.clear()
        memory_marks["end_snapshots_cleared"] = _settled_memory(reader)
    finally:
        server.stop()
        patches.restore()
        sampler.stop_event.set()
        sampler.join(timeout=5)
        if holder is not None:
            (holder / "shards").unlink(missing_ok=True)
            holder.rmdir()

    kernel = reader() or {}
    records_out = [_sample_record(run, sample, overhead) for sample in run.samples]
    summary = _summary([record for record in records_out if record["scenario"] != "memory_trace"], sampler)
    measured = sum(boot_phases.get(name, 0.0) for name in ("canonicalize", "fit_tfidf", "register_matrix"))
    document = {
        "schema": "ofe-match-latency/1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": {"commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain"))},
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "load_average_start": [round(value, 2) for value in load_start] if load_start else None,
            "load_average_end": [round(value, 2) for value in os.getloadavg()] if hasattr(os, "getloadavg") else None,
            "memory_source": memory_source,
        },
        "settings": {
            "endpoint": "POST /api/matches/view?llm=false",
            "page_size": PAGE_SIZE,
            "view": {**FIRST_PAGE_VIEW, "today": run.today},
            "cross_school_matching": matches.feature_enabled("cross_school_matching"),
            "match_timeout_s": matches._MATCH_TIMEOUT_SECONDS,
            "match_executor_workers": matches._MATCH_MAX_WORKERS,
            "match_max_pending": matches._MATCH_MAX_PENDING,
            "snapshot_ttl_s": matches._SNAPSHOT_TTL_SECONDS,
            "snapshot_max_entries": matches._SNAPSHOT_MAX_ENTRIES,
            "isolation_env": sorted(ISOLATION_ENV),
            "repeats": {"home_cold": args.repeats, "cross_cold": args.cross_repeats, "warm": args.warm_repeats},
            "cancel_after_s": args.cancel_after,
            "breakdown": args.breakdown,
            "wrapper_overhead_us_per_call": round(overhead * 1e6, 3),
            "run_seconds": round(time.perf_counter() - started, 1),
        },
        "corpus": {"source": corpus_source, "data_dir": str(args.data_dir), "records": records},
        "boot": {
            "import_s": round(import_seconds, 3),
            "lifespan_s": round(boot_seconds, 3),
            "phases_s": {
                "read_parse_index": round(max(0.0, boot_phases.get("load", 0.0) - measured), 3),
                **_round_map({
                    name: value for name, value in boot_phases.items() if name in (
                        "canonicalize", "fit_tfidf", "register_matrix")
                }),
                "gc_collect_freeze": round(max(0.0, boot_phases.get("warmup", 0.0) - boot_phases.get("load", 0.0)), 3),
                "warmup_total": round(boot_phases.get("warmup", 0.0), 3),
            },
            "peak": sampler.peak("boot"),
        },
        "personas": {
            name: {"cross_school": name in CROSS_PERSONAS, "profile": profile} for name, profile in PERSONAS.items()
        },
        "summary": summary,
        "scenarios": [
            {key: value for key, value in entry.items() if key not in ("wall_start", "wall_end")}
            | {"health": run.probe.window(entry["wall_start"], entry["wall_end"]), "peak": sampler.peak(entry["name"])}
            for entry in run.scenarios
        ],
        "samples": records_out,
        # Every ranking the executor ran, in order. The cold scenarios rank a
        # profile once per repeat on purpose; anywhere else, two entries with
        # one key in one scenario mean the app ranked one profile twice.
        "rankings": [
            {
                "scenario": record.scenario,
                "persona": record.persona,
                "key": record.key[:12],
                "start_s": round(record.start - started, 3),
                "seconds": round(record.end - record.start, 3) if record.end is not None else None,
                "visible": record.visible,
                "error": record.error,
            }
            for record in recorder.computes
        ],
        "memory": {
            "marks": memory_marks,
            # Request scenarios only: boot, the cProfile/parity pass and the
            # tracemalloc pass allocate for the measurement itself.
            "serving_peak_sampled": sampler.peak_over([entry["name"] for entry in run.scenarios]),
            "kernel_peak_before_diagnostics": {
                "rss_peak_mb": _mb(run.kernel_peak_serving.get("rss_peak")),
                "footprint_peak_mb": _mb(run.kernel_peak_serving.get("footprint_peak")),
            },
            "kernel_peak_whole_run": {
                "ru_maxrss_mb": _mb(_ru_maxrss_bytes()),
                "rss_peak_mb": _mb(kernel.get("rss_peak")),
                "footprint_peak_mb": _mb(kernel.get("footprint_peak")),
            },
            "snapshots_stored_at_end": stored,
        },
        "diagnostics": diagnostics,
    }

    print(_table(summary))
    print()
    text = json.dumps(document, indent=2)
    if args.json is not None:
        args.json.write_text(text + "\n", encoding="utf-8")
        print(f"JSON written to {args.json}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
