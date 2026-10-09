"""Event-loop stall of /api/tailor/extract-bullets and /api/tailor/structure on 60,000-character résumés.

Both routes run origin/main's extraction (round 4): the local fallback (_heuristic_bullets) reads every
row of each chunk the model did not answer on the event loop, and _bullet_grounded normalizes the chunk
again for every line the model returned, on a provider worker. The shapes below are the row shapes the
earlier row reader (rounds 3 to 3d) found dearest; they also give the fallback a row per line.

Each request goes through backend.main.app over httpx.ASGITransport; the garbage collector is
frozen as backend.main._warmup freezes it. While the requests run, the event loop wakes every
millisecond (longest wake-up delay = longest stall). Each case runs twice and reports its best run.
Without --model no provider is configured, so every chunk takes the local extraction; with --model
a stub answers at once with 60 lines of the résumé's shape, so every chunk's answer is grounded.

Run from the repository root:  python scripts/extract_route_lag.py [--concurrent 1,4,10] [--model]
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("OFE_DISABLE_RATE_LIMIT", "1")
for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(key, None)

import httpx  # noqa: E402

from backend import main as main_module  # noqa: E402
from backend.routes import tailor  # noqa: E402

LIMIT = 60_000
CASES = {
    "mixed-case rows under a glyph": "• Ab\n" + "Xx abcd efgh\n" * 5000,
    "distinct mixed-case rows": "• Ab\n" + "".join(f"X{i} abcd efgh\n" for i in range(5000)),
    "digit rows under a glyph": "• Ab\n" + "12 abcd efgh\n" * 5000,
    "CJK rows under a glyph": "• 用\n" + "数据清洗并完成了分析工作内容\n" * 4000,
    "status rows": "• Built a dashboard for the lab\nUnder review at the ICRA 2026 workshop not yet submitted\n" * 700,
    "glyph rows": "• Built a dashboard for the lab with R\n" * 1500,
    # Round 3d's shapes: entry-shaped status rows, soft rows with a status last, camel-case rows, marks
    # before every row, and Word's "o" and list numbers.
    "entry-shaped status rows": "• Ab\n" + "Team of 4, Fall 2024 | Under Review at ICRA (Draft)\n" * 1100,
    "soft rows, status last": "• Ab\n" + "Machine learning for sleep staging xx\n" * 1550 + "Under review\n",
    "camel-case rows": "• Ab\n" + "iGEM Team of 4, Fall 2024 abcd\n" * 1900,
    "marks before rows": "• Ab\n" + "※★√ Xx abcd efgh\n" * 3500,
    "list numbers and o": "".join(f"({index % 99})Xx abcd efgh\no Yy abcd efgh\n" for index in range(2400)),
}
PATHS = ("/api/tailor/extract-bullets", "/api/tailor/structure")


def _stub_model(messages, **kwargs):
    lines = [f"Xx abcd efgh {index}" for index in range(60)]
    if "Structure it now" in messages[1]["content"]:
        return json.dumps({"sections": [{"heading": "Experience", "kind": "experience", "bullets": lines}]})
    return json.dumps({"bullets": lines})


async def _stall(path: str, text: str, concurrent: int) -> tuple[float, set[int]]:
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe", timeout=120) as client:
        worst, done = 0.0, False

        async def ticker():
            nonlocal worst
            last = time.perf_counter()
            while not done:
                await asyncio.sleep(0.001)
                now = time.perf_counter()
                worst, last = max(worst, now - last - 0.001), now

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0.01)
        body = {"resume_text": text[:LIMIT], "locale": "en"}
        if path.endswith("extract-bullets"):
            body["expected_pipeline_version"] = tailor.TAILOR_PIPELINE_VERSION
        responses = await asyncio.gather(*(client.post(path, json=body) for _ in range(concurrent)))
        done = True
        await task
        return worst, {response.status_code for response in responses}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrent", default="1,4,10")
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--model", action="store_true", help="a stub model answers every chunk at once")
    args = parser.parse_args()
    if args.model:
        tailor.chat_completion = _stub_model
        tailor.is_configured = lambda: True
        tailor.model_for = lambda *a: {}
    gc.freeze()
    levels = [int(level) for level in args.concurrent.split(",")]
    for level in levels:
        over, worst = 0, (0.0, "")
        for name, text in CASES.items():
            for path in PATHS:
                stall, statuses = min([await _stall(path, text, level) for _ in range(2)], key=lambda run: run[0])
                over += stall > args.threshold
                worst = max(worst, (stall, f"{path} {name}"))
                print(f"x{level:<3} {path:30s} {name:32s} stall {stall * 1000:7.1f} ms  status {sorted(statuses)}")
        print(f"at {level} concurrent ({'model stub' if args.model else 'no model'}): over {args.threshold:g} s: {over}; "
              f"worst {worst[0] * 1000:.1f} ms ({worst[1]})")


if __name__ == "__main__":
    asyncio.run(main())
