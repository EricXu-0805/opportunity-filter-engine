"""Event-loop stall on the request bodies the round-1 CPU review named as worst, and on new shapes at the bounds.

The round-1 CPU review measured, on 6ed0396, these stalls before any worker ran:
/api/tailor source_bullets of 524k ints 5,897 ms; original_bullets of ints 5,083 ms and of
empty lists 4,471 ms; a full-target or selection-plan draft just under 2 MiB of nested lists
2,253 ms, empty lists 1,425 ms, empty dicts 902 ms, ints 439 ms; 1 MiB of nested lists in an
unknown field 166-321 ms. This script replays those bodies and adds shapes aimed at the
round-1 bounds (100,000 lists and objects per body, 200 bullets per list, 20 errors per 422):
dicts or small lists just under the container bound, a body nested past the parser's recursion
limit, a profile at its text limits (scanned in Python before pydantic), and 422 error lists
from fields the 200-item bound does not cover.

Each request goes through backend.main.app over httpx.ASGITransport. The corpus is stubbed
out, so a body that passes validation ends in a 404 before any model work; the garbage
collector is frozen as backend.main._warmup freezes it. While a request runs, the event loop
wakes every millisecond (longest wake-up delay = longest stall) and a heartbeat asks
/api/tailor/status (longest gap between answers). A case over the threshold is re-run up to
three times and reported with its best run.

Round 2 added --concurrent (identical requests sent at once: four 2 MiB bodies of ints held the
loop 0.30-0.39 s at --concurrent 4 on 99241b5) and the bodies at the comma bound
(backend.lib.request_body.MAX_JSON_SEPARATORS), the most items a body may now hold.

Run from the repository root:  python scripts/worst_inputs_lag.py [--threshold 0.25] [--only TEXT] [--concurrent N]
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
from backend.lib import release_scope  # noqa: E402
from backend.lib.request_body import MAX_JSON_CONTAINERS, MAX_JSON_SEPARATORS  # noqa: E402
from backend.routes import tailor  # noqa: E402
from backend.routes import target_resume_ai as full_route  # noqa: E402

ONE_MIB = 1024 * 1024 - 2048
FULL_BODY = 2 * 1024 * 1024 + 64 * 1024 - 2048
DRAFT = 2 * 1024 * 1024 - 1024
NESTED30 = json.loads("[" * 30 + "0" + "]" * 30)
UNDER = MAX_JSON_CONTAINERS - 40  # the rest of the body holds a few containers of its own
UNDER_SEPARATORS = MAX_JSON_SEPARATORS - 40
PROFILE = {"name": "Sample Student", "major": "Psychology"}
TAILOR = {"profile": PROFILE, "opportunity_id": "probe-target", "locale": "en"}
SIGNATURE = "v1:sha256:" + "0" * 64


def fill(kind: str, size: int):
    """A JSON value of about `size` bytes of one shape."""
    if kind == "ints":
        return [0] * (size // 2)
    if kind == "empty lists":
        return [[]] * (size // 3)
    if kind == "empty dicts":
        return [{}] * (size // 3)
    if kind == "nested":
        return [NESTED30] * (size // 62)
    if kind == "dicts at the bound, then ints":
        return [{}] * UNDER + [0] * ((size - 3 * UNDER) // 2)
    if kind == "4-int lists at the bound":
        per = max(1, (size // UNDER - 2) // 2)
        return [[0] * per] * UNDER
    if kind == "1-key dicts at the bound":
        return [{"k": 0}] * min(UNDER, UNDER_SEPARATORS, size // 8)
    if kind == "floats":
        return [1e5] * (size // 9)
    if kind == "strings":
        return [""] * (size // 3)
    if kind == "ints at the comma bound, then a string":
        return [[0] * UNDER_SEPARATORS, "a" * max(0, size - 2 * UNDER_SEPARATORS - 8)]
    if kind == "strings at the comma bound, then a string":
        return [[""] * UNDER_SEPARATORS, "a" * max(0, size - 3 * UNDER_SEPARATORS - 8)]
    raise KeyError(kind)


def raw(name: str, path: str, body: bytes):
    return name, path, body


def cases():
    # Round-1 worst bodies, replayed.
    yield "R1 /api/tailor source_bullets: 1 MiB ints", "/api/tailor", {
        **TAILOR, "original_bullets": ["Built a robot."], "source_bullets": fill("ints", ONE_MIB)}
    yield "R1 /api/tailor original_bullets: 1 MiB ints", "/api/tailor", {
        **TAILOR, "original_bullets": fill("ints", ONE_MIB)}
    yield "R1 /api/tailor original_bullets: 1 MiB empty lists", "/api/tailor", {
        **TAILOR, "original_bullets": fill("empty lists", ONE_MIB)}
    for kind in ("nested", "empty lists", "empty dicts", "ints"):
        draft = {"kind": "full_resume", "junk": fill(kind, DRAFT)}
        yield f"R1 full-target draft: 2 MiB {kind}", "/api/tailor/full-target/suggestions", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "selected_unit_ids": ["line-1"]}
        yield f"R1 selection-plan draft: 2 MiB {kind}", "/api/tailor/full-target/selection-plan", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "options": {"target_pages": 1}}
    yield "R1 /api/tailor unknown field: 1 MiB nested", "/api/tailor", {
        **TAILOR, "original_bullets": ["Built a robot."], "padding": fill("nested", ONE_MIB)}

    # New shapes at the round-1 bounds.
    for kind in ("dicts at the bound, then ints", "4-int lists at the bound", "1-key dicts at the bound",
                 "floats", "strings", "ints at the comma bound, then a string",
                 "strings at the comma bound, then a string"):
        yield f"NEW /api/tailor unknown field: 1 MiB {kind}", "/api/tailor", {
            **TAILOR, "original_bullets": ["Built a robot."], "padding": fill(kind, ONE_MIB)}
        yield f"NEW /api/tailor/renovate unknown field: 1 MiB {kind}", "/api/tailor/renovate", {
            **TAILOR, "sections": [], "padding": fill(kind, ONE_MIB)}
        draft = {"kind": "full_resume", "junk": fill(kind, DRAFT)}
        yield f"NEW full-target draft: 2 MiB {kind}", "/api/tailor/full-target/suggestions", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "selected_unit_ids": ["line-1"]}
        yield f"NEW selection-plan draft: 2 MiB {kind}", "/api/tailor/full-target/selection-plan", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "options": {"target_pages": 1}}
    # A body nested past the parser's recursion limit, under the container bound.
    deep = b'{"profile":{"name":"S"},"opportunity_id":"probe-target","padding":' + b"[" * UNDER + b"]" * UNDER + b"}"
    yield raw("NEW /api/tailor unknown field: nested 99,960 deep", "/api/tailor", deep)
    deep_full = (b'{"version":1,"request_id":"p","locale":"en","document_signature":"' + SIGNATURE.encode()
                 + b'","selected_unit_ids":["line-1"],"draft":' + b"[" * UNDER + b"]" * UNDER + b"}")
    yield raw("NEW full-target draft: nested 99,960 deep", "/api/tailor/full-target/suggestions", deep_full)
    # Profile text at its limits: complete_profile_input scans each string for surrogates in Python.
    yield "NEW /api/tailor profile.desired_fields: 17 x 60,000 characters", "/api/tailor", {
        **TAILOR, "profile": {**PROFILE, "desired_fields": ["a" * 60_000] * 17}, "original_bullets": ["Built a robot."]}
    yield "NEW /api/tailor profile.name: 1 MiB characters", "/api/tailor", {
        **TAILOR, "profile": {**PROFILE, "name": "a" * (ONE_MIB - 200)}, "original_bullets": ["Built a robot."]}
    yield "NEW /api/tailor profile.coursework: 512 x 2,000 characters", "/api/tailor", {
        **TAILOR, "profile": {**PROFILE, "coursework": ["a" * 2_000] * 512}, "original_bullets": ["Built a robot."]}
    # Error lists from fields the 200-item bound does not name.
    yield "NEW /api/tailor/renovate sections[0].bullets: 1 MiB ints", "/api/tailor/renovate", {
        **TAILOR, "sections": [{"id": "s1", "bullets": fill("ints", ONE_MIB)}]}
    yield "NEW /api/tailor/renovate sections: 15 x 1-key dicts, bullets of ids as ints", "/api/tailor/renovate", {
        **TAILOR, "sections": [{"id": 1, "heading": 1, "kind": 1, "bullets": [{"id": 1, "text": 1}] * 6}] * 15}
    yield "NEW /api/tailor profile.hard_skills: 1 MiB ints", "/api/tailor", {
        **TAILOR, "profile": {**PROFILE, "hard_skills": fill("ints", ONE_MIB - 200)}, "original_bullets": ["x"]}
    yield "NEW /api/tailor/bullet instruction: 1 MiB string", "/api/tailor/bullet", {
        **TAILOR, "current_text": "Built a robot.", "instruction": "a" * (ONE_MIB - 300)}
    yield "NEW full-target support_groups: 24 x 24 ids, then ints", "/api/tailor/full-target/suggestions", {
        "version": 1, "request_id": "probe", "locale": "en", "draft": {}, "document_signature": SIGNATURE,
        "selected_unit_ids": ["line-1"],
        "support_groups": [{"unit_id": "u", "support_unit_ids": fill("ints", (FULL_BODY - 400) // 24),
                            "confirmed": True}] * 24}


async def probe(path: str, content: bytes, concurrent: int = 1):
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
        responses = await asyncio.gather(*(client.post(path, content=content, headers={"content-type": "application/json"})
                                           for _ in range(concurrent)))
        response = responses[0]
        stop.set()
        await asyncio.gather(*tasks)
        return response, lag[0], max(gaps, default=0.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--only", default="")
    parser.add_argument("--concurrent", type=int, default=1, help="identical requests sent at once")
    args = parser.parse_args()
    main_module.feature_enabled = lambda feature: True
    release_scope.feature_enabled = lambda feature: True
    tailor.load_opportunities_by_id = full_route.load_opportunities_by_id = lambda: {}
    gc.collect()
    gc.freeze()
    over = worst = 0
    worst_name = ""
    for name, path, body in cases():
        if args.only and args.only not in name:
            continue
        content = body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
        containers = content.count(b"[") + content.count(b"{")
        best = None
        for _ in range(3):
            result = asyncio.run(probe(path, content, args.concurrent))
            best = result if best is None or result[1] < best[1] else best
            if best[1] <= args.threshold:
                break
        response, lag, gap = best
        flag = "OVER" if lag > args.threshold else "ok  "
        over += lag > args.threshold
        if lag > worst:
            worst, worst_name = lag, name
        print(f"{flag} {lag * 1000:8.1f} ms lag {gap * 1000:8.1f} ms gap {len(content) / 1024:6.0f} KiB "
              f"{containers:7d} containers  {response.status_code} {len(response.content):6d} B  {name}", flush=True)
    print(f"\nover {args.threshold:.2f} s: {over}; worst {worst * 1000:.1f} ms ({worst_name})")
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
