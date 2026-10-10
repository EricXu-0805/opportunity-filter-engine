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
quote, and the legitimate bodies whose text or id lists are commas (scripts/request_body_containers.py).
ROUTES runs the R6 and R7 shapes and the NEW unknown-field shapes on every other route of the app that
reads a JSON body (request_body_containers.json_routes), against that route's declared bounds and
body limit, and sends every route its largest valid body, and a private import's save and an export
at their body limits. VALIDATION sends every route the bodies request_body_containers.validation_bodies
builds for each value, list, typed map and closed model of its request schema, within the route's bounds.
NUMBERS sends every route lists of numbers of each shape the JSON number grammar allows, with its parts
at two widths each, at and past its digit bound.
The admin routes are sent an operator token they accept, so they validate their bodies.

Each request goes through backend.main.app over httpx.ASGITransport, as a caller whose credential
is already verified. The corpus is stubbed out, so a body that passes validation ends in a 404, or
in its route's refusal for a missing credential or service, before any model work; startup objects are
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
for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY"):
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
from scripts.request_body_containers import body_limit  # noqa: E402

ONE_MIB = 1024 * 1024 - 2048
FULL_BODY = 2 * 1024 * 1024 + 64 * 1024 - 2048
DRAFT = 2 * 1024 * 1024 - 1024
NESTED30 = json.loads("[" * 30 + "0" + "]" * 30)
UNDER = MAX_JSON_CONTAINERS - 40  # the rest of the body holds a few containers of its own
UNDER_SEPARATORS = MAX_JSON_SEPARATORS - 40
PROFILE = {"name": "Sample Student", "major": "Psychology"}
TAILOR = {"profile": PROFILE, "opportunity_id": "probe-target", "locale": "en"}
SIGNATURE = "v1:sha256:" + "0" * 64
ADMIN_TOKEN = "probe-admin"


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
    # Every route that reads a JSON body.
    yield from json_route_cases()
    yield from validation_cases()
    yield from number_cases()


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


def json_route_cases():
    from backend.lib.request_body import declared_bounds
    from scripts import request_body_containers as largest

    covered = {path for path, *_ in ROUTE_FRAMES}
    routes = {(method, path): route for method, path, route in largest.json_routes(main_module.app)}
    frame = b'{"padding":%s}'
    own = 2  # the frame's object and the padding list
    for method, template, path, body in largest.largest_bodies():
        yield f"ROUTES {method} {template} legitimate: its largest valid body", path, body, method
        if template in covered:
            continue
        bounds = declared_bounds(routes[method, template])
        bound, separators = bounds.containers, bounds.separators
        cap = body_limit(method, path) - 400
        levels = [(bound - own, "at its bound"), (bound - own + 1, "one over its bound"), (PAST - own, "past every bound")]
        for shape, depth in enumerate((2, 50, 900), 1):
            for total, where in levels:
                if depth > total or total // depth > separators - 50 or 2 * total > cap:
                    continue
                yield (f"ROUTES {method} {template} unknown field: lists, shape {shape}, {where}", path,
                       frame % chains(total, depth), method)
        count = min(separators - 40, (cap - 400) // 12)
        yield (f"ROUTES {method} {template} unknown field: strings of brackets at the comma bound", path,
               frame % ("[" + ",".join(['"[[[{{{[]"'] * count) + "]").encode(), method)
        yield (f"ROUTES {method} {template} unknown field: quoted brackets to the body limit, not JSON", path,
               frame % (b'"[{' * ((cap - 400) // 3)), method)
        items = min(separators - 40, (cap - 400) // 2)
        yield f"ROUTES {method} {template} unknown field: ints at the comma bound", path, {"padding": [0] * items}, method
        yield (f"ROUTES {method} {template} unknown field: 1-key dicts at the bound", path,
               {"padding": [{"k": 0}] * min(bound - 40, separators // 2 - 40, cap // 8)}, method)
        yield (f"ROUTES {method} {template} unknown field: quotes, then commas past the bound", path,
               frame % (b'"' * (cap - separators - 10) + b"," * (separators + 1)), method)
        yield (f"ROUTES {method} {template} unknown field: quotes, then brackets past the bound", path,
               frame % (b'"' * (cap - bound - 10) + b"[" * (bound + 1)), method)
    yield from limit_bodies()


def number_forms(width: int, exponent_width: int):
    """One JSON number of each shape the grammar allows: an integer part, an optional fraction and an
    optional exponent of either sign."""
    whole, half, power = "9" * width, "9" * (width // 2 or 1), "9" * exponent_width
    mantissas = {"int": whole, "frac": "0." + whole, "int.frac": half + "." + half}
    exponents = {"": "", "e": "e" + power, "e-": "e-" + power, "e+": "e+" + power}
    for m_tag, mantissa in mantissas.items():
        for e_tag, exponent in exponents.items():
            yield f"{m_tag}{e_tag}", (mantissa + exponent).encode()


# The digits number_cases puts in a number's integer part or fraction, and in its exponent.
NUMBER_WIDTHS = (1, 6)
EXPONENT_WIDTHS = (1, 3)


def number_cases():
    """Every route: a list of numbers of each grammar shape (number_forms), at each width of its parts,
    at the route's digit bound, and to its comma bound or body limit, past it."""
    from backend.lib.request_body import declared_bounds, structural_digits
    from scripts import request_body_containers as largest

    forms = {}
    for width in NUMBER_WIDTHS:
        for exponent_width in EXPONENT_WIDTHS:
            for tag, item in number_forms(width, exponent_width):
                forms.setdefault(item, f"{tag} width {width}" + (f"/{exponent_width}" if "e" in tag else ""))
    routes = {(method, path): route for method, path, route in largest.json_routes(main_module.app)}
    for method, template, path, _ in largest.largest_bodies():
        bounds = declared_bounds(routes[method, template])
        cap = body_limit(method, path) - 400
        for item, form in forms.items():
            most = min(bounds.separators - 50, cap // (len(item) + 1))
            at = bounds.digits // structural_digits(item)
            positions = ((at, "at the digit bound"), (most, "past it, to the comma bound or body limit")) if at < most \
                else ((most, "to the comma bound or body limit"),)
            for count, where in positions:
                body = b'{"padding":[' + b",".join([item] * count) + b"]}"
                yield f"NUMBERS {method} {template} {count:,} x form {form}, {where}", path, body, method


def validation_cases():
    """Every route's bodies for each list, typed map and closed model of its request schema
    (request_body_containers.validation_bodies)."""
    from scripts import request_body_containers as largest

    for method, template, path, name, body in largest.validation_bodies(main_module.app):
        yield f"VALIDATION {method} {template} {name}", path, body, method


def limit_bodies():
    """Legitimate bodies at their body limits: a private import's save with its text, and an export
    with its lines' text, each filling its route's limit."""
    from backend.lib.target_resume_export_schema import export_signature
    from scripts import request_body_containers as largest

    bodies = {(method, template): (path, body) for method, template, path, body in largest.largest_bodies()}
    path, body = bodies["PUT", "/api/private-import-targets/{target_id}"]
    room = body_limit("PUT", path) - len(json.dumps(body).encode()) - 70_000
    opportunity = {**body["opportunity"], "description_raw": "Join the lab. " * (5 * 1024 * 1024 // 14)}
    opportunity["raw_html"] = "<p>Join.</p>" * ((room - len(opportunity["description_raw"])) // 12)
    yield "ROUTES PUT private import legitimate: text to the body limit", path, {**body, "opportunity": opportunity}, "PUT"
    path, body = bodies["POST", "/api/resume/full-target/export"]
    projection = json.loads(json.dumps(body["projection"]))
    per_line = (body_limit("POST", path) - len(json.dumps(body).encode()) - 70_000) // 600
    for section in projection["sections"]:
        for block in section["blocks"]:
            for row in block["lines"]:
                row["text"] = ("Built a rig. " * (per_line // 13 + 1))[:per_line]
    yield "ROUTES POST export legitimate: text to the body limit", path, {
        **body, "projection": projection, "export_signature": export_signature(projection)}


async def probe(path: str, content: bytes, concurrent: int = 1, method: str = "POST"):
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
        headers = {"content-type": "application/json", "authorization": "Bearer probe", "x-admin-token": ADMIN_TOKEN}
        responses = await asyncio.gather(*(client.request(method, path, content=content, headers=headers)
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


def stub_corpus_and_credentials() -> None:
    """No corpus in any route module, and a private caller whose credential is already verified."""
    import contextlib
    import importlib
    import pkgutil

    from backend import routes
    from backend.lib import private_import_targets as storage

    for info in pkgutil.iter_modules(routes.__path__):
        module = importlib.import_module(f"backend.routes.{info.name}")
        for name, empty in (("load_opportunities_by_id", dict), ("load_opportunities", list),
                            ("load_opportunities_generation", lambda: ([], "probe"))):
            if hasattr(module, name):
                setattr(module, name, empty)

    @contextlib.asynccontextmanager
    async def verified(*args, **kwargs):
        yield

    storage.caller_verified_before_parsing = verified
    importlib.import_module("backend.routes.private_import_targets").caller_verified_before_parsing = verified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--only", default="")
    parser.add_argument("--concurrent", type=levels, default=[1],
                        help="identical requests sent at once; a list such as 1,4,10 measures each in turn")
    args = parser.parse_args()
    main_module.feature_enabled = lambda feature: True
    release_scope.feature_enabled = lambda feature: True
    stub_corpus_and_credentials()
    os.environ["ADMIN_TOKEN"] = ADMIN_TOKEN
    gc.collect()
    gc.freeze()
    rows = []
    for concurrent in args.concurrent:
        for case in cases():
            name, path, body, method = (*case, "POST")[:4]
            if args.only and args.only not in name:
                continue
            content = body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
            containers = content.count(b"[") + content.count(b"{")
            best = None
            for _ in range(3):
                result = asyncio.run(probe(path, content, concurrent, method))
                best = result if best is None or result[1] < best[1] else best
                if best[1] <= args.threshold:
                    break
            response, lag, gap = best
            rows.append((concurrent, f"{method} {path}", lag, name))
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
