"""Event-loop stall while the selection plan parses a model answer at its output budget.

/api/tailor/full-target/selection-plan parses the model answer with parse_plan_output, on a
thread since round 1 (it ran inline in the async route before). It re-anchors every quote the
model gives by finding every occurrence of it in the named field, so its cost is (quotes) x
(occurrences): 600 quotes took 394.5 ms on the event loop inline, and stall it about 11 ms now. The answer is capped by
the plan call's 12,000 output tokens; a résumé line can steer what the model quotes. This
script stubs the plan model to quote a one-character string many times from a
6,000-character experience line (and once, validly, from the target), and prints the
longest event-loop stall per quote count.

Run from the repository root:  python scripts/plan_output_lag.py
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import sys
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("OFE_DISABLE_RATE_LIMIT", "1")

import httpx  # noqa: E402

from backend import main as main_module  # noqa: E402
from backend.lib import release_scope  # noqa: E402
from backend.lib import target_resume_ai as engine  # noqa: E402
from backend.routes import target_resume_ai as full_route  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rewrite_route_lag import OPPORTUNITY, full_doc, full_payload  # noqa: E402

LINE = "a " * 3000
ANSWER = {"characters": 0}


def plan_model(quotes: int):
    def model(messages, **kwargs):
        data = json.loads(messages[1]["content"])
        requirement = data["target"]["requirements"][0]
        items = []
        for block in data["blocks"]:
            line = max(block["lines"], key=lambda row: len(row["original"]))
            many = quotes if len(line["original"]) >= len(LINE) - 1 else 1
            items.append({"section_id": block["section_id"], "block_id": block["block_id"], "action": "keep",
                          "reason": "Relevant.", "rewrites": [],
                          "target_evidence": [{"field": "requirement", "requirement_index": 0, "start": 0,
                                               "end": len(requirement), "quote": requirement}],
                          "source_evidence": [{"unit_id": line["unit_id"], "start": 0, "end": 1,
                                               "quote": line["original"][:1]}] * many})
        answer = json.dumps({"items": items})
        ANSWER["characters"] = len(answer)
        return answer
    return model


async def probe(content: bytes):
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe", timeout=120) as client:
        stop, worst = asyncio.Event(), [0.0]

        async def wake():
            while not stop.is_set():
                before = time.perf_counter()
                await asyncio.sleep(0.001)
                worst[0] = max(worst[0], time.perf_counter() - before - 0.001)

        waker = asyncio.create_task(wake())
        response = await client.post("/api/tailor/full-target/selection-plan", content=content,
                                     headers={"content-type": "application/json"})
        stop.set()
        await waker
        return response, worst[0]


def main() -> int:
    main_module.feature_enabled = lambda feature: True
    release_scope.feature_enabled = lambda feature: True
    full_route.load_opportunities_by_id = lambda: {OPPORTUNITY["id"]: deepcopy(OPPORTUNITY)}
    full_route.is_configured = lambda: True
    engine.llm_budget.exhausted = lambda: False
    engine.model_for = lambda *args: {}
    gc.collect()
    gc.freeze()
    doc = full_doc([LINE.strip()], ["Python"])
    content = json.dumps(full_payload(doc, plan=True), separators=(",", ":")).encode()
    for quotes in (1, 100, 300, 600):
        engine.chat_completion = plan_model(quotes)
        best = None
        for _ in range(3):
            response, lag = asyncio.run(probe(content))
            best = (response, lag) if best is None or lag < best[1] else best
        response, lag = best
        body = response.json()
        print(f"{quotes:4d} quotes ({ANSWER['characters']:6d} characters of model answer): longest stall {lag * 1000:7.1f} ms  "
              f"-> {response.status_code} complete={body.get('complete')} reason={body.get('reason_code')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
