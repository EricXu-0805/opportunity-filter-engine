"""Event-loop stall while the résumé-rewrite routes read request bodies within their byte limits.

The cases are the bodies round 1's CPU review chose; the routes now bound a body's structure
before parsing it (backend.lib.request_body). No provider or corpus is needed: every case is
answered (422, or 404 for the stubbed-out corpus) before a model call.

Run from the repository root:
    python scripts/request_parse_lag.py [--threshold 0.25] [--only TEXT]
Prints, per case, the longest event-loop wake-up delay and the longest gap between
/api/tailor/status answers while the request ran. Over-threshold cases are re-run up to
three times and reported with their best run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("OFE_DISABLE_RATE_LIMIT", "1")
for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(key, None)

import gc  # noqa: E402

import httpx  # noqa: E402

from backend import main as main_module  # noqa: E402
from backend.lib import release_scope  # noqa: E402
from backend.routes import tailor  # noqa: E402
from backend.routes import target_resume_ai as full_route  # noqa: E402

ONE_MIB = 1024 * 1024 - 2048
TWO_MIB = 2 * 1024 * 1024 + 64 * 1024 - 2048
# A draft just under MAX_DOCUMENT_BYTES passes the size check.
DRAFT = 2 * 1024 * 1024 - 1024
NESTED = [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]
PROFILE = {"name": "Sample Student", "major": "Psychology"}
TAILOR = {"profile": PROFILE, "opportunity_id": "probe-target", "locale": "en"}
SIGNATURE = "v1:sha256:" + "0" * 64


# Round 1's container bound; each route now has a bound of its own (backend.lib.request_body).
UNDER_THE_BOUND = 99_990


def junk(kind: str, size: int) -> list:
    if kind == "empty lists at the bound, then ints":
        return [[]] * UNDER_THE_BOUND + [0] * ((size - 3 * UNDER_THE_BOUND) // 2)
    return {"nested": [NESTED] * (size // 62), "empty lists": [[]] * (size // 3),
            "empty dicts": [{}] * (size // 3), "ints": [0] * (size // 2)}[kind]


def cases():
    yield "/api/tailor original_bullets: ints", "/api/tailor", {**TAILOR, "original_bullets": junk("ints", ONE_MIB)}
    yield "/api/tailor original_bullets: empty lists", "/api/tailor", {
        **TAILOR, "original_bullets": junk("empty lists", ONE_MIB)}
    yield "/api/tailor source_bullets: ints", "/api/tailor", {
        **TAILOR, "original_bullets": ["Built a robot."], "source_bullets": junk("ints", ONE_MIB)}
    yield "/api/tailor original_bullets: blank strings", "/api/tailor", {
        **TAILOR, "original_bullets": [""] * (ONE_MIB // 3)}
    for kind in ("nested", "empty lists", "empty lists at the bound, then ints"):
        yield f"/api/tailor unknown field: {kind}", "/api/tailor", {
            **TAILOR, "original_bullets": ["Built a robot."], "padding": junk(kind, ONE_MIB)}
        yield f"/api/tailor/bullet unknown field: {kind}", "/api/tailor/bullet", {
            **TAILOR, "current_text": "Built a robot.", "padding": junk(kind, ONE_MIB)}
        yield f"/api/tailor/renovate unknown field: {kind}", "/api/tailor/renovate", {
            **TAILOR, "sections": [], "padding": junk(kind, ONE_MIB)}
    for kind in ("nested", "empty lists", "empty dicts", "ints", "empty lists at the bound, then ints"):
        draft = {"kind": "full_resume", "junk": junk(kind, DRAFT)}
        yield f"full-target draft: {kind}", "/api/tailor/full-target/suggestions", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "selected_unit_ids": ["line-1"]}
        yield f"selection-plan draft: {kind}", "/api/tailor/full-target/selection-plan", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "options": {"target_pages": 1}}
    yield "full-target selected_unit_ids: ints", "/api/tailor/full-target/suggestions", {
        "version": 1, "request_id": "probe", "locale": "en", "draft": {}, "document_signature": SIGNATURE,
        "selected_unit_ids": junk("ints", TWO_MIB - 300)}


async def probe(path: str, content: bytes):
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe", timeout=300) as client:
        stop, lag, gaps = asyncio.Event(), [0.0], []

        async def wake():
            while not stop.is_set():
                before = time.perf_counter()
                await asyncio.sleep(0.001)
                lag[0] = max(lag[0], time.perf_counter() - before - 0.001)

        async def heartbeat():
            last = time.perf_counter()
            while not stop.is_set():
                await client.get("/api/tailor/status")
                now = time.perf_counter()
                gaps.append(now - last)
                last = now
                await asyncio.sleep(0.005)

        tasks = [asyncio.create_task(wake()), asyncio.create_task(heartbeat())]
        await asyncio.sleep(0.02)
        response = await client.post(path, content=content, headers={"content-type": "application/json"})
        stop.set()
        await asyncio.gather(*tasks)
        return response, lag[0], max(gaps, default=0.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    main_module.feature_enabled = lambda feature: True
    release_scope.feature_enabled = lambda feature: True
    # No corpus: a request that passes validation ends in a 404. Production freezes its startup
    # objects (backend.main._warmup), and so does this script.
    tailor.load_opportunities_by_id = full_route.load_opportunities_by_id = lambda: {}
    gc.collect()
    gc.freeze()
    over = 0
    for name, path, body in cases():
        if args.only and args.only not in name:
            continue
        content = json.dumps(body, separators=(",", ":")).encode()
        best = None
        for _ in range(3):
            result = asyncio.run(probe(path, content))
            best = result if best is None or result[1] < best[1] else best
            if best[1] <= args.threshold:
                break
        response, lag, gap = best
        size = len(response.content)
        flag = "OVER" if lag > args.threshold else "ok  "
        over += lag > args.threshold
        print(f"{flag} {lag * 1000:8.1f} ms lag {gap * 1000:8.1f} ms status gap  {len(content) / 1024:6.0f} KiB in "
              f"{size / 1024:8.0f} KiB out  {response.status_code}  {name}", flush=True)
    print(f"\nover {args.threshold:.2f} s: {over}")
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
