"""Refuse a JSON request body with more containers than any valid request holds, before it is parsed.

Starlette parses a request's JSON with ``json.loads`` on the event loop, and a
thread would not help: the C parser holds the GIL. Parsing itself is fast; what
stalls the loop is the cyclic garbage collector, which runs again and again while
a body of many tiny lists or objects is built. At the body limits the résumé-writing
routes accept (1 MiB, and 2 MiB + 64 KiB for full target) such a body held the loop
0.2-0.5 s before any validation ran (scripts/request_parse_lag.py).

Only lists and objects are tracked by the collector, so their number bounds that
cost. Each route has its own bound, set far above the largest body its legitimate
requests hold (scripts/request_body_containers.py prints both), and counted outside
JSON strings (structural_containers), so a bracket in a résumé's text costs nothing.

Items cost too: a 2 MiB list of ints holds four containers, but json.loads and
the validation after it build a million items, 80-120 ms per body, and four such
bodies sent at once held the loop 0.30-0.39 s (scripts/worst_inputs_lag.py
--concurrent 4). Every item after the first in a list or object follows a comma,
so the comma count bounds them, commas inside strings included. A full-target
draft of 100 entries holds a few thousand, a 60,000-character résumé of English
prose about 1,200 (one in every 50 characters); the bound is 50,000.

/api/tailor/extract-bullets and /api/tailor/structure take one résumé of up to
MAX_RESUME_TEXT_CHARACTERS, every character of which may be a comma or a bracket, and
origin/main reads such a résumé whole (criterion E). Their routes (ResumeJSONRoute) allow as
many commas as the résumé has characters, plus the few between the request's own fields; a
résumé's brackets sit inside its string, which the container count skips.
"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from backend.lib.resume_input import MAX_RESUME_TEXT_CHARACTERS

# Lists and objects outside JSON strings, per route. The largest body each route's request schema
# accepts holds 651 (/api/tailor/renovate), 522 (/api/tailor), 520 (/api/tailor/bullet), 1 (either
# extraction route) and 4,435 (a full-target draft at the master's caps, plus at most 49 for support
# groups); scripts/request_body_containers.py builds and prints them.
MAX_JSON_CONTAINERS = 10_000
MAX_RESUME_JSON_CONTAINERS = 100
MAX_FULL_TARGET_JSON_CONTAINERS = 20_000
MAX_JSON_SEPARATORS = 50_000
MAX_RESUME_JSON_SEPARATORS = MAX_RESUME_TEXT_CHARACTERS + 100


def _json_text(body: bytes) -> bytes | str:
    """The body as json.loads reads it: UTF-8 bytes as they are, UTF-16 or UTF-32 decoded.

    In UTF-8 a quote, backslash or bracket byte is always that character; in UTF-16 or
    UTF-32 it can be half of another one. A body that does not decode is refused by
    json.loads before it builds anything, so it holds no containers.
    """
    encoding = json.detect_encoding(body)
    if encoding in ("utf-8", "utf-8-sig"):
        return body
    try:
        return body.decode(encoding, "surrogatepass")
    except UnicodeDecodeError:
        return ""


def structural_containers(text: bytes | str) -> int:
    """The '[' and '{' of a JSON text that json.loads reads as lists and objects.

    Escaped backslashes go first, then escaped quotes, so every quote left opens or
    closes a string; the pieces between them alternate outside and inside. For a body
    json.loads rejects, the count agrees with it up to the first error, and nothing after
    that is built.
    """
    quote, backslash, lists, objects = ('"', "\\", "[", "{") if isinstance(text, str) else (b'"', b"\\", b"[", b"{")
    empty = text[:0]
    if backslash in text:
        text = text.replace(backslash + backslash, empty).replace(backslash + quote, empty)
    outside = empty.join(text.split(quote)[::2])
    return outside.count(lists) + outside.count(objects)


def check_body_bounds(body: bytes, max_separators: int = MAX_JSON_SEPARATORS,
                      max_containers: int = MAX_JSON_CONTAINERS) -> None:
    """Raise the RequestValidationError each route already answers when the body holds too many containers
    or too many items (commas).

    The counts read the whole body in C: a few milliseconds for 1 MiB. Only a body with more
    brackets than its bound anywhere has its strings set aside before the count.
    """
    text = _json_text(body)
    lists, objects, commas = (b"[", b"{", b",") if isinstance(text, bytes) else ("[", "{", ",")
    if text.count(commas) > max_separators or (
            text.count(lists) + text.count(objects) > max_containers and structural_containers(text) > max_containers):
        raise RequestValidationError([{"type": "too_long", "loc": ("body",), "msg": "Request input is invalid.",
                                       "input": None}])


async def refuse_container_heavy_body(request: Request, max_separators: int = MAX_JSON_SEPARATORS,
                                      max_containers: int = MAX_JSON_CONTAINERS) -> None:
    """check_body_bounds on the request's body, on the event loop, before FastAPI parses it.

    The full-target routes, whose bodies reach 2 MiB, run it on their request lane instead
    (routes/target_resume_ai.py).
    """
    check_body_bounds(await request.body(), max_separators, max_containers)


class BoundedJSONRoute(APIRoute):
    """An APIRoute that refuses a container-heavy JSON body before FastAPI parses it."""

    max_separators = MAX_JSON_SEPARATORS
    max_containers = MAX_JSON_CONTAINERS

    def get_route_handler(self):
        original = super().get_route_handler()
        max_separators, max_containers = self.max_separators, self.max_containers

        async def handler(request: Request):
            await refuse_container_heavy_body(request, max_separators, max_containers)
            return await original(request)

        return handler


class ResumeJSONRoute(BoundedJSONRoute):
    """BoundedJSONRoute for a route that reads one résumé: a comma may stand in each of its characters."""

    max_separators = MAX_RESUME_JSON_SEPARATORS
    max_containers = MAX_RESUME_JSON_CONTAINERS
