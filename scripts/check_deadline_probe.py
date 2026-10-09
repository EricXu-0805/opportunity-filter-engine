"""What the checks' worker deadline (CHECK_TIMEOUT_SECONDS) bounds, and what it does not.

/api/tailor runs the contract and the claim locks through run_blocking with a deadline;
past it the route keeps every original as review_unavailable. This script makes the check
slow on purpose (the real checks take well under a second at the caps; see
scripts/rewrite_route_lag.py) and drives /api/tailor with the provider stubbed, with the
deadline lowered to 0.2 s:

  python-slow  a check that spends 1.5 s in Python bytecode
  regex-slow   a check whose single regex call takes about 1.5 s (a catastrophic pattern,
               not one of the lock patterns)

For each it prints: when the response arrived, its outcome, how long the worker thread
kept running after the response, and the longest event-loop stall meanwhile. The
deadline bounds the wait, not the work: the thread runs to the end either way, holding a
pool slot, and a single long C call stalls the event loop for its whole length.

Run from the repository root:  python scripts/check_deadline_probe.py
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import re
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("OFE_DISABLE_RATE_LIMIT", "1")

import httpx  # noqa: E402

from backend import main as main_module  # noqa: E402
from backend.lib import evidence_map as em  # noqa: E402
from backend.lib import release_scope  # noqa: E402
from backend.routes import tailor  # noqa: E402

OPPORTUNITY = {"id": "probe-target", "title": "Research Tools", "organization": "Example Lab",
               "source_url": "https://example.edu/lab", "description_clean": "Research Python parsers.",
               "eligibility": {"skills_required": ["Python"]}, "source_type": "campus_program",
               "opportunity_type": "research", "metadata": {"is_active": True}}
CURRENT = "Responsible for building a parser for the lab."
SECONDS = 1.5
CATASTROPHIC = re.compile(r"^(a+)+$")


def _calibrated_regex_input() -> str:
    """An input on which CATASTROPHIC takes about SECONDS in one call."""
    n = 18
    while True:
        text = "a" * n + "b"
        started = time.perf_counter()
        CATASTROPHIC.match(text)
        if time.perf_counter() - started >= SECONDS / 2.2:
            return "a" * (n + 1) + "b"
        n += 1


def model(messages, **kwargs):
    if messages[0]["content"].startswith("FAITHFULNESS REVIEW"):
        pairs = json.loads(messages[1]["content"])["pairs"]
        return json.dumps({"verdicts": [{"index": p["index"], "changes": "", "faithful": True, "links": [],
                                         "problem": ""} for p in pairs]})
    units = json.loads(messages[1]["content"].split("DATA (JSON):\n", 1)[1])["units"]
    return json.dumps({"bullets": [{"unit_id": u["unit_id"], "links": [], "decision": "rewrite",
                                    "ops": [{"op": "verb_first"}], "text": "Built a parser for the lab.",
                                    "keep_reason": None} for u in units]})


async def drive(slow_check) -> dict:
    finished = {}
    real_check = em.check_rewrite

    def check(*args, **kwargs):
        slow_check()
        finished["at"] = time.perf_counter()
        return real_check(*args, **kwargs)

    tailor.check_rewrite = check
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe", timeout=60) as client:
        stop, worst = asyncio.Event(), [0.0]

        async def wake():
            while not stop.is_set():
                before = time.perf_counter()
                await asyncio.sleep(0.001)
                worst[0] = max(worst[0], time.perf_counter() - before - 0.001)

        waker = asyncio.create_task(wake())
        began = time.perf_counter()
        response = await client.post("/api/tailor", json={
            "profile": {"name": "Sample Student"}, "opportunity_id": OPPORTUNITY["id"], "locale": "en",
            "original_bullets": [CURRENT]})
        answered = time.perf_counter()
        while "at" not in finished:
            await asyncio.sleep(0.01)
        stop.set()
        await waker
    tailor.check_rewrite = real_check
    row = response.json()["tailored_bullets"][0]
    return {"answered": answered - began, "outcome": f"{row['status']}:{row['reason_code']}",
            "ran_after_answer": finished["at"] - answered, "worst_stall": worst[0],
            "workers": [t.name for t in threading.enumerate() if t.name.startswith("ofe-blocking-ai")]}


def main() -> int:
    main_module.feature_enabled = lambda feature: True
    release_scope.feature_enabled = lambda feature: True
    tailor.load_opportunities_by_id = lambda: {OPPORTUNITY["id"]: deepcopy(OPPORTUNITY)}
    tailor.is_configured = lambda: True
    tailor.model_for = em.model_for = lambda *args: {}
    tailor.chat_completion = em.chat_completion = model
    tailor.CHECK_TIMEOUT_SECONDS = 0.2
    gc.collect()
    gc.freeze()
    text = _calibrated_regex_input()

    def python_slow():
        deadline = time.perf_counter() + SECONDS
        while time.perf_counter() < deadline:
            sum(range(200))

    def regex_slow():
        CATASTROPHIC.match(text)

    for name, slow in (("python-slow", python_slow), ("regex-slow", regex_slow)):
        result = asyncio.run(drive(slow))
        print(f"{name:12} answered after {result['answered']:.3f} s ({result['outcome']}); the worker ran "
              f"{result['ran_after_answer']:.3f} s more; longest event-loop stall {result['worst_stall']:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
