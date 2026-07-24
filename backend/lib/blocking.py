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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
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
