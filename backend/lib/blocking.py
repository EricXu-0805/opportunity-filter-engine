"""Bounded bridge for synchronous provider work called by async routes.

The OpenAI-compatible SDK used by :mod:`backend.lib.llm` is synchronous.  A
direct call from an ``async def`` route blocks the process event loop, which
also stalls liveness checks and every unrelated request on the single-worker
deployment.  All such work goes through the small shared pool below and is
given an outer wall-clock timeout.

Cancelling an asyncio Future cannot stop an already-running Python thread, so
the provider's own HTTP timeout remains the first line of defence.  The bounded
pool is the second: timed-out calls cannot create unbounded active threads.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger("ofe.blocking")


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


BLOCKING_AI_MAX_WORKERS = _bounded_int("OFE_BLOCKING_AI_MAX_WORKERS", 4, minimum=1, maximum=16)
BLOCKING_AI_MAX_PENDING = _bounded_int("OFE_BLOCKING_AI_MAX_PENDING", 4, minimum=0, maximum=64)
SINGLE_LLM_TIMEOUT_SECONDS = float(_bounded_int("OFE_SINGLE_LLM_TIMEOUT_SECONDS", 45, minimum=5, maximum=180))
MULTI_LLM_TIMEOUT_SECONDS = float(_bounded_int("OFE_MULTI_LLM_TIMEOUT_SECONDS", 180, minimum=15, maximum=600))
# Full-corpus matching currently takes about 14 seconds in the broadest local
# profile.  Fifteen seconds left no scheduling/host-pressure headroom and could
# turn healthy work into a timeout at the release boundary, so local CPU/network
# work gets a reviewed 30-second outer budget.  Provider calls keep their own
# stricter HTTP timeouts inside this process-level guard.
LOCAL_WORK_TIMEOUT_SECONDS = float(_bounded_int("OFE_LOCAL_WORK_TIMEOUT_SECONDS", 30, minimum=1, maximum=60))

_BLOCKING_AI_EXECUTOR = ThreadPoolExecutor(
    max_workers=BLOCKING_AI_MAX_WORKERS,
    thread_name_prefix="ofe-blocking-ai",
)
_BLOCKING_AI_CAPACITY = threading.BoundedSemaphore(
    BLOCKING_AI_MAX_WORKERS + BLOCKING_AI_MAX_PENDING
)


class BlockingWorkTimeout(TimeoutError):
    """Raised when blocking provider work exceeds its route-level budget."""


class BlockingWorkOverloaded(BlockingWorkTimeout):
    """Raised immediately when both workers and the bounded queue are full."""


async def run_blocking(
    func: Callable[..., T],
    /,
    *args,
    timeout_seconds: float = SINGLE_LLM_TIMEOUT_SECONDS,
    **kwargs,
) -> T:
    """Run ``func`` outside the event loop with bounded concurrency + timeout.

    ThreadPoolExecutor's native submission queue is unbounded. The separate
    capacity semaphore covers running *and* queued calls so a burst cannot turn
    an upstream outage into an in-process memory/latency queue. Capacity is
    released by the underlying concurrent future, not by the asyncio wrapper;
    cancelling a timed-out wrapper therefore cannot pretend a still-running
    provider thread has finished.
    """
    if not _BLOCKING_AI_CAPACITY.acquire(blocking=False):
        logger.warning(
            "blocking_work_overloaded function=%s capacity=%d",
            getattr(func, "__qualname__", getattr(func, "__name__", type(func).__name__)),
            BLOCKING_AI_MAX_WORKERS + BLOCKING_AI_MAX_PENDING,
        )
        raise BlockingWorkOverloaded("blocking work queue is saturated")

    loop = asyncio.get_running_loop()
    try:
        concurrent_future = _BLOCKING_AI_EXECUTOR.submit(
            partial(func, *args, **kwargs),
        )
    except BaseException:
        _BLOCKING_AI_CAPACITY.release()
        raise
    concurrent_future.add_done_callback(lambda _future: _BLOCKING_AI_CAPACITY.release())
    future = asyncio.wrap_future(concurrent_future, loop=loop)
    try:
        return await asyncio.wait_for(future, timeout=max(0.001, timeout_seconds))
    except TimeoutError as exc:
        # This cancels queued work when possible. An already-running provider
        # call is released by its own HTTP timeout; pool size bounds the damage.
        future.cancel()
        logger.warning(
            "blocking_work_timeout function=%s timeout_seconds=%g",
            getattr(func, "__qualname__", getattr(func, "__name__", type(func).__name__)),
            timeout_seconds,
        )
        raise BlockingWorkTimeout(f"blocking work exceeded {timeout_seconds:g}s") from exc


# One lane for the CPU-bound request work of the routes that take the largest bodies: parsing and
# validating a full-target draft, checking it against its target and building its prompt. That work
# holds the GIL. On one thread, the event loop shares the GIL with that thread alone, so its longest
# wait is one request's longest C call, whatever the number of requests; the requests queue on the
# lane instead (scripts/worst_inputs_lag.py and scripts/rewrite_route_lag.py measure it with
# --concurrent). The contract and claim-lock checks of a full-target answer run here too, rather than
# on run_blocking's workers, and so do the structural count of a body past the default body limit
# (request_body), the reading and validating of the bodies of the other routes with a larger body
# limit (request_body.json_body_on_lane) and the cold-email drafting and claim checks. Provider calls
# never run here (run_blocking does those).
_REQUEST_WORK_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ofe-request-work")

# The capacity of the request lane, in pieces of work waiting for it or running on it. Only work
# submitted to the lane (run_request_work) counts: a request counts for nothing while its body arrives,
# while it waits on Supabase or a provider, or while it does anything else off the lane. A request's
# first work on the lane is its admission: when the lane already holds REQUEST_LANE_CAPACITY pieces of
# work, that work is not submitted and the request is refused at once (RequestLaneFull,
# request_body.admitted_to_request_lane). Every later piece of work of an admitted request is
# submitted and counted, never refused, so the lane can hold more than its capacity; while it does,
# every new request is refused. The API runs one worker process (render.yaml, --workers 1) and the
# lane one thread, so work waits behind all the work submitted before it. Sixteen is above the most
# requests at once the lane is measured with (ten: scripts/worst_inputs_lag.py --concurrent 1,4,10),
# and a request sends its work to the lane one piece after another, so that use is not refused.
REQUEST_LANE_CAPACITY = 16
_REQUEST_LANE_LOCK = threading.Lock()
# Work submitted to the lane that is waiting for it or running on it.
_request_lane_load = 0
# A refusal is logged at most once a minute, with the number of refusals since the last line.
_REFUSAL_LOG_INTERVAL_SECONDS = 60.0
_refusals_not_logged = 0
_refusal_logged_at: float | None = None


class RequestLaneFull(Exception):
    """A request's first work found the request lane at its capacity, and was not submitted."""


class _LaneRequest:
    """Whether the current request has been admitted to the request lane (its first work submitted)."""

    __slots__ = ("admitted",)

    def __init__(self) -> None:
        self.admitted = False


_LANE_REQUEST: ContextVar[_LaneRequest | None] = ContextVar("ofe_request_lane_request", default=None)


def _leave_request_lane(*_args) -> None:
    global _request_lane_load
    with _REQUEST_LANE_LOCK:
        _request_lane_load -= 1


def _log_refusal() -> None:
    global _refusals_not_logged, _refusal_logged_at
    now = time.monotonic()
    with _REQUEST_LANE_LOCK:
        _refusals_not_logged += 1
        if _refusal_logged_at is not None and now - _refusal_logged_at < _REFUSAL_LOG_INTERVAL_SECONDS:
            return
        refused, _refusals_not_logged, _refusal_logged_at = _refusals_not_logged, 0, now
    logger.warning("request_lane_full capacity=%d refused=%d", REQUEST_LANE_CAPACITY, refused)


@contextmanager
def request_lane_admission() -> Iterator[None]:
    """Within it, the current request is admitted to the request lane by its first work there, or
    refused then (run_request_work). Nothing is counted for the request itself."""
    token = _LANE_REQUEST.set(_LaneRequest())
    try:
        yield
    finally:
        _LANE_REQUEST.reset(token)


async def run_request_work(func: Callable[..., T], /, *args, timeout_seconds: float | None = None, **kwargs) -> T:
    """Run ``func`` on the single request lane, one request at a time, off the event loop.

    Work that is cancelled, or runs out of ``timeout_seconds`` (BlockingWorkTimeout), while it
    waits for the lane never runs; work already running finishes on the lane. Within
    request_lane_admission, the request's first work raises RequestLaneFull, without being submitted,
    when the lane already holds REQUEST_LANE_CAPACITY pieces of work; no other work is refused.
    """
    global _request_lane_load
    loop = asyncio.get_running_loop()
    lane_request = _LANE_REQUEST.get()
    with _REQUEST_LANE_LOCK:
        refused = (lane_request is not None and not lane_request.admitted
                   and _request_lane_load >= REQUEST_LANE_CAPACITY)
        if not refused:
            if lane_request is not None:
                lane_request.admitted = True
            _request_lane_load += 1
    if refused:
        _log_refusal()
        raise RequestLaneFull(f"the request lane holds {REQUEST_LANE_CAPACITY} pieces of work")
    try:
        concurrent_future = _REQUEST_WORK_EXECUTOR.submit(partial(func, *args, **kwargs))
    except BaseException:
        _leave_request_lane()
        raise
    # It stops counting when the work itself finishes or is cancelled before it starts, not when the
    # asyncio wrapper does: cancelling the wrapper cannot stop work that is already running.
    concurrent_future.add_done_callback(_leave_request_lane)
    future = asyncio.wrap_future(concurrent_future, loop=loop)
    if timeout_seconds is None:
        return await future
    try:
        return await asyncio.wait_for(future, timeout=max(0.001, timeout_seconds))
    except TimeoutError as exc:
        logger.warning("request_work_timeout function=%s timeout_seconds=%g",
                       getattr(func, "__qualname__", getattr(func, "__name__", type(func).__name__)), timeout_seconds)
        raise BlockingWorkTimeout(f"request work exceeded {timeout_seconds:g}s") from exc
