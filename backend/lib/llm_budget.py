"""Day ceiling on paid provider calls, counted where the spend happens.

The per-minute ceiling in ``backend.main`` bounds a burst. It does not bound a
drip: 240/min sustained is 345,600 requests a day against a shared provider key.

Counting billable HTTP REQUESTS for the day figure would be badly wrong in the
other direction, though. The match snapshot and the rerank score cache absorb
most of a session's paging, filtering and tab switching without ever reaching a
provider, so a request-counted ceiling would degrade a working feature while
the real bill sat near zero. This counts completions — the unit the provider
actually charges for — by instrumenting the one function every paid path goes
through.

Recording and enforcing are deliberately separate. This module only counts;
``backend.main``'s middleware decides what a spent budget means, and that
differs by endpoint: the matching routes degrade to the rule ranking, while the
endpoints whose whole product IS the completion refuse. A module that blocked
calls itself could not express that difference.

Per worker and in memory, like every other ceiling here — a backstop against a
runaway, not an accounting ledger. On a multi-worker deploy the effective
ceiling is N×, which is still a ceiling.
"""

from __future__ import annotations

import os
import threading
import time

# Provider completions per UTC day.
#
# Priced from OpenRouter's public rate for the rerank model
# (anthropic/claude-sonnet-5: $2/M prompt, $10/M completion) against a measured
# payload: two calls and roughly $0.012 per fresh match refine, and that is a
# floor — the reconstruction could not see research_areas_raw or recent works,
# and each candidate may carry up to 600 characters against the ~220 observed.
# Call it $0.012-0.02.
#
# 400 completions is therefore about 200 fresh profiles and $2.40-4.00 a day,
# far above real traffic and a bounded loss if something runs away. The key
# this spends belongs to a professor and cannot be revoked, which is the whole
# reason the ceiling is low rather than comfortable. Raise it on Render when
# real traffic justifies it; going over degrades to the rule ranking, it does
# not error.
DEFAULT_PER_DAY = 400

_lock = threading.Lock()
_day = ""
_count = 0


def limit() -> int:
    """Read the env on every call so a deploy-time change needs no restart."""
    try:
        return int(os.environ.get("OFE_GLOBAL_LLM_PER_DAY", str(DEFAULT_PER_DAY)))
    except ValueError:
        return DEFAULT_PER_DAY


def _roll(now: float) -> None:
    """Caller holds the lock."""
    global _day, _count
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    if today != _day:
        _day = today
        _count = 0


def spend(calls: int = 1) -> None:
    """Record provider calls that were actually issued.

    Called from the provider boundary itself, so a cache hit, an unconfigured
    provider, and a missing SDK all correctly cost nothing.
    """
    global _count
    with _lock:
        _roll(time.time())
        _count += calls


def spent() -> int:
    with _lock:
        _roll(time.time())
        return _count


def exhausted() -> bool:
    """Whether today's budget is gone. A limit of 0 means every call is over."""
    return spent() >= limit()


def reset_for_tests() -> None:
    global _day, _count
    with _lock:
        _day = ""
        _count = 0
