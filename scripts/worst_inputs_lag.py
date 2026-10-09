"""Event-loop stall on adversarial request bodies within every cap, one request at a time and several at once.

The cases come in groups. R1 replays the bodies round 1's CPU review named as worst. NEW adds
shapes aimed at round 1's bounds: bodies just under a bound, a body nested past the parser's
recursion limit, a profile at its text limits, and 422 error lists from fields the 200-item bound
does not cover. R5 adds the extraction routes' bodies at their own comma bound
(backend.lib.request_body.MAX_RESUME_JSON_SEPARATORS) and résumés of commas, brackets and braces.
R6 adds bodies of lists at, one over and past each route's container bound
(MAX_JSON_CONTAINERS, MAX_RESUME_JSON_CONTAINERS, MAX_FULL_TARGET_JSON_CONTAINERS), and bodies whose
brackets sit inside strings, which the count must read past. R7 counts commas outside strings too,
and adds bodies of quotes past each route's comma or container bound, which the count splits at every
quote, and the two legitimate bodies whose text is commas (scripts/request_body_containers.py).

Each request goes through backend.main.app over httpx.ASGITransport. The corpus is stubbed
out, so a body that passes validation ends in a 404 before any model work; startup objects are
frozen as backend.main._warmup freezes them. While a request runs, the event loop wakes every
millisecond (longest wake-up delay = longest stall) and a heartbeat asks /api/tailor/status
(longest gap between answers). A case over the threshold is re-run up to three times and reported
with its best run. --concurrent sends that many identical requests at once; a list (1,4,10)
measures every case at each level in turn and prints the worst stall per route at each.

Run from the repository root:  python scripts/worst_inputs_lag.py [--threshold 0.25] [--only TEXT] [--concurrent 1,4,10]
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
from backend.lib.request_body import (  # noqa: E402
    MAX_FULL_TARGET_JSON_CONTAINERS,
    MAX_JSON_CONTAINERS,
    MAX_JSON_SEPARATORS,
    MAX_RESUME_JSON_CONTAINERS,
    MAX_RESUME_JSON_SEPARATORS,
)
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
    yield "R1 /api/tailor source_bullets: ints", "/api/tailor", {
        **TAILOR, "original_bullets": ["Built a robot."], "source_bullets": fill("ints", ONE_MIB)}
    yield "R1 /api/tailor original_bullets: ints", "/api/tailor", {
        **TAILOR, "original_bullets": fill("ints", ONE_MIB)}
    yield "R1 /api/tailor original_bullets: empty lists", "/api/tailor", {
        **TAILOR, "original_bullets": fill("empty lists", ONE_MIB)}
    for kind in ("nested", "empty lists", "empty dicts", "ints"):
        draft = {"kind": "full_resume", "junk": fill(kind, DRAFT)}
        yield f"R1 full-target draft: {kind}", "/api/tailor/full-target/suggestions", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "selected_unit_ids": ["line-1"]}
        yield f"R1 selection-plan draft: {kind}", "/api/tailor/full-target/selection-plan", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "options": {"target_pages": 1}}
    yield "R1 /api/tailor unknown field: nested", "/api/tailor", {
        **TAILOR, "original_bullets": ["Built a robot."], "padding": fill("nested", ONE_MIB)}

    # New shapes at the round-1 bounds.
    for kind in ("dicts at the bound, then ints", "4-int lists at the bound", "1-key dicts at the bound",
                 "floats", "strings", "ints at the comma bound, then a string",
                 "strings at the comma bound, then a string"):
        yield f"NEW /api/tailor unknown field: {kind}", "/api/tailor", {
            **TAILOR, "original_bullets": ["Built a robot."], "padding": fill(kind, ONE_MIB)}
        yield f"NEW /api/tailor/renovate unknown field: {kind}", "/api/tailor/renovate", {
            **TAILOR, "sections": [], "padding": fill(kind, ONE_MIB)}
        draft = {"kind": "full_resume", "junk": fill(kind, DRAFT)}
        yield f"NEW full-target draft: {kind}", "/api/tailor/full-target/suggestions", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "selected_unit_ids": ["line-1"]}
        yield f"NEW selection-plan draft: {kind}", "/api/tailor/full-target/selection-plan", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": draft,
            "document_signature": SIGNATURE, "options": {"target_pages": 1}}
    # A body nested past the parser's recursion limit, under the container bound.
    deep = b'{"profile":{"name":"S"},"opportunity_id":"probe-target","padding":' + b"[" * UNDER + b"]" * UNDER + b"}"
    yield raw("NEW /api/tailor unknown field: nested past the recursion limit", "/api/tailor", deep)
    deep_full = (b'{"version":1,"request_id":"p","locale":"en","document_signature":"' + SIGNATURE.encode()
                 + b'","selected_unit_ids":["line-1"],"draft":' + b"[" * UNDER + b"]" * UNDER + b"}")
    yield raw("NEW full-target draft: nested past the recursion limit", "/api/tailor/full-target/suggestions", deep_full)
    # Profile text at its limits.
    yield "NEW /api/tailor profile.desired_fields: 17 x 60,000 characters", "/api/tailor", {
        **TAILOR, "profile": {**PROFILE, "desired_fields": ["a" * 60_000] * 17}, "original_bullets": ["Built a robot."]}
    yield "NEW /api/tailor profile.name: characters to the body limit", "/api/tailor", {
        **TAILOR, "profile": {**PROFILE, "name": "a" * (ONE_MIB - 200)}, "original_bullets": ["Built a robot."]}
    yield "NEW /api/tailor profile.coursework: 512 x 2,000 characters", "/api/tailor", {
        **TAILOR, "profile": {**PROFILE, "coursework": ["a" * 2_000] * 512}, "original_bullets": ["Built a robot."]}
    # Error lists from fields the 200-item bound does not name.
    yield "NEW /api/tailor/renovate sections[0].bullets: ints", "/api/tailor/renovate", {
        **TAILOR, "sections": [{"id": "s1", "bullets": fill("ints", ONE_MIB)}]}
    yield "NEW /api/tailor/renovate sections: 15 x 1-key dicts, bullets of ids as ints", "/api/tailor/renovate", {
        **TAILOR, "sections": [{"id": 1, "heading": 1, "kind": 1, "bullets": [{"id": 1, "text": 1}] * 6}] * 15}
    yield "NEW /api/tailor profile.hard_skills: ints", "/api/tailor", {
        **TAILOR, "profile": {**PROFILE, "hard_skills": fill("ints", ONE_MIB - 200)}, "original_bullets": ["x"]}
    yield "NEW /api/tailor/bullet instruction: a string to the body limit", "/api/tailor/bullet", {
        **TAILOR, "current_text": "Built a robot.", "instruction": "a" * (ONE_MIB - 300)}
    yield "NEW full-target support_groups: 24 x 24 ids, then ints", "/api/tailor/full-target/suggestions", {
        "version": 1, "request_id": "probe", "locale": "en", "draft": {}, "document_signature": SIGNATURE,
        "selected_unit_ids": ["line-1"],
        "support_groups": [{"unit_id": "u", "support_unit_ids": fill("ints", (FULL_BODY - 400) // 24),
                            "confirmed": True}] * 24}
    # Round 5: the extraction routes at their own comma bound, and résumés of commas and brackets.
    under = MAX_RESUME_JSON_SEPARATORS - 40
    for path, extra in (("/api/tailor/extract-bullets", {}), ("/api/tailor/structure", {"locale": "en"})):
        body = {"resume_text": "Built a robot.", **extra}
        yield f"R5 {path} unknown field: {under:,} 1-key dicts", path, {**body, "padding": [{"k": 0}] * under}
        yield f"R5 {path} unknown field: {under:,} ints, then a string", path, {
            **body, "padding": [[0] * under, "a" * (ONE_MIB - 2 * under - 200)]}
        yield f"R5 {path} unknown field: {under:,} strings, then a string", path, {
            **body, "padding": [[""] * under, "a" * (ONE_MIB - 3 * under - 200)]}
        yield f"R5 {path} unknown field: {under:,} empty lists", path, {**body, "padding": [[]] * under}
        for character, name in ((",", "commas"), ("[", "brackets"), ("{", "braces")):
            yield f"R5 {path} resume_text: 60,000 {name}", path, {**extra, "resume_text": character * 60_000}
    # Round 6: each route's container bound, counted outside strings.
    yield from bound_cases()
    # Round 7: commas counted outside strings.
    yield from quote_cases()


def chains(total: int, depth: int) -> bytes:
    """A list of chains of lists nested `depth` deep (the last one shorter), `total` lists in all."""
    parts = [b"[" * depth + b"]" * depth] * (total // depth) + ([b"[" * (total % depth) + b"]" * (total % depth)]
                                                               if total % depth else [])
    return b"[" + b",".join(parts) + b"]"


PAST = 100_000  # lists and objects past every route's bound


_FULL_FRAME = (b'{"version":1,"request_id":"p","locale":"en","document_signature":"' + SIGNATURE.encode()
        + b'","selected_unit_ids":["line-1"],"draft":{"kind":"full_resume","junk":%s}}')
_PLAN_FRAME = (b'{"version":1,"request_id":"p","locale":"en","document_signature":"' + SIGNATURE.encode()
        + b'","options":{"target_pages":1},"draft":{"kind":"full_resume","junk":%s}}')
ROUTE_FRAMES = (
    ("/api/tailor", b'{"profile":{"name":"S"},"opportunity_id":"probe-target","original_bullets":["x"],"padding":%s}',
     MAX_JSON_CONTAINERS, MAX_JSON_SEPARATORS),
    ("/api/tailor/bullet", b'{"profile":{"name":"S"},"opportunity_id":"probe-target","current_text":"x","padding":%s}',
     MAX_JSON_CONTAINERS, MAX_JSON_SEPARATORS),
    ("/api/tailor/renovate", b'{"profile":{"name":"S"},"opportunity_id":"probe-target","sections":[],"padding":%s}',
     MAX_JSON_CONTAINERS, MAX_JSON_SEPARATORS),
    ("/api/tailor/extract-bullets", b'{"resume_text":"x","padding":%s}', MAX_RESUME_JSON_CONTAINERS,
     MAX_RESUME_JSON_SEPARATORS),
    ("/api/tailor/structure", b'{"resume_text":"x","locale":"en","padding":%s}', MAX_RESUME_JSON_CONTAINERS,
     MAX_RESUME_JSON_SEPARATORS),
    ("/api/tailor/full-target/suggestions", _FULL_FRAME, MAX_FULL_TARGET_JSON_CONTAINERS, MAX_JSON_SEPARATORS),
    ("/api/tailor/full-target/selection-plan", _PLAN_FRAME, MAX_FULL_TARGET_JSON_CONTAINERS, MAX_JSON_SEPARATORS),
)


def bound_cases():
    for path, frame, bound, separators in ROUTE_FRAMES:
        own = (frame % b"[]").count(b"[") + (frame % b"[]").count(b"{")  # the frame's own, the padding list included
        levels = [(bound - own, "at its bound"), (bound - own + 1, "one over its bound"), (PAST - own, "past every bound")]
        for shape, depth in enumerate((2, 50, 900), 1):
            for total, where in levels:
                if depth > total or total // depth > separators - 50:
                    continue
                yield raw(f"R6 {path} unknown field: lists, shape {shape}, {where}", path, frame % chains(total, depth))
        cap = FULL_BODY if path.startswith("/api/tailor/full-target") else ONE_MIB
        count = min(separators - 40, (cap - 400) // 12)
        yield raw(f"R6 {path} unknown field: strings of brackets at the comma bound", path,
                  frame % ("[" + ",".join(['"[[[{{{[]"'] * count) + "]").encode())
        yield raw(f"R6 {path} unknown field: quoted brackets to the body limit, not JSON", path,
                  frame % (b'"[{' * ((cap - 400) // 3)))


def quote_cases():
    from scripts.request_body_containers import comma_dense_bodies

    for path, frame, containers, separators in ROUTE_FRAMES:
        room = (FULL_BODY if path.startswith("/api/tailor/full-target") else ONE_MIB) - 400
        yield raw(f"R7 {path} unknown field: quotes, then commas past the bound", path,
                  frame % (b'"' * (room - separators - 10) + b"," * (separators + 1)))
        yield raw(f"R7 {path} unknown field: quotes, then brackets past the bound", path,
                  frame % (b'"' * (room - containers - 10) + b"[" * (containers + 1)))
        yield raw(f"R7 {path} unknown field: escaped quotes, then commas past the bound", path,
                  frame % (b'\\"' * ((room - separators) // 2 - 10) + b"," * (separators + 1)))
    for name, path, body in comma_dense_bodies():
        yield f"R7 {path} legitimate: {name}", path, body


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


def levels(value: str) -> list[int]:
    """--concurrent: one number, or a comma-separated list measured one after the other (1,4,10)."""
    out = [int(part) for part in value.split(",") if part.strip()]
    if not out or min(out) < 1:
        raise argparse.ArgumentTypeError("--concurrent takes positive numbers, e.g. 1,4,10")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--only", default="")
    parser.add_argument("--concurrent", type=levels, default=[1],
                        help="identical requests sent at once; a list such as 1,4,10 measures each in turn")
    args = parser.parse_args()
    main_module.feature_enabled = lambda feature: True
    release_scope.feature_enabled = lambda feature: True
    tailor.load_opportunities_by_id = full_route.load_opportunities_by_id = lambda: {}
    gc.collect()
    gc.freeze()
    rows = []
    for concurrent in args.concurrent:
        for name, path, body in cases():
            if args.only and args.only not in name:
                continue
            content = body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
            containers = content.count(b"[") + content.count(b"{")
            best = None
            for _ in range(3):
                result = asyncio.run(probe(path, content, concurrent))
                best = result if best is None or result[1] < best[1] else best
                if best[1] <= args.threshold:
                    break
            response, lag, gap = best
            rows.append((concurrent, path, lag, name))
            flag = "OVER" if lag > args.threshold else "ok  "
            print(f"{flag} {lag * 1000:8.1f} ms lag {gap * 1000:8.1f} ms gap {len(content) / 1024:6.0f} KiB "
                  f"{containers:7d} containers  {response.status_code} {len(response.content):6d} B  x{concurrent}  {name}",
                  flush=True)
    status = 0
    for concurrent in args.concurrent:
        level = [row for row in rows if row[0] == concurrent]
        print(f"\nworst per route at {concurrent} concurrent (longest stall):")
        for path in sorted({row[1] for row in level}):
            _, _, lag, name = max((row for row in level if row[1] == path), key=lambda row: row[2])
            print(f"{lag * 1000:8.1f} ms lag  {path}  ({name})")
        over = sum(row[2] > args.threshold for row in level)
        worst = max(level, key=lambda row: row[2], default=None)
        status |= bool(over)
        print(f"over {args.threshold:.2f} s at {concurrent} concurrent: {over}; "
              + (f"worst {worst[2] * 1000:.1f} ms ({worst[3]})" if worst else "no cases"))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
