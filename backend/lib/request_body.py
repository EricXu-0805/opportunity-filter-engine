"""Refuse a JSON request body with more containers than any valid request holds, before it is parsed.

Starlette parses a request's JSON with ``json.loads`` on the event loop, and a
thread would not help: the C parser holds the GIL. Parsing itself is fast; what
stalls the loop is the cyclic garbage collector, which runs again and again while
a body of many tiny lists or objects is built. At the body limits the résumé-writing
routes accept (1 MiB, and 2 MiB + 64 KiB for full target) such a body held the loop
0.2-0.5 s before any validation ran (scripts/request_parse_lag.py).

Only lists and objects are tracked by the collector, so their number bounds that
cost. ``bytes.count`` reads it from the raw body in about a millisecond; brackets
inside strings count too, which only makes the bound stricter. A full-target draft
of 100 entries and 20 units holds about 600 containers, so the bound is far above
any real request.

Items cost too: a 2 MiB list of ints holds four containers, but json.loads and
the validation after it build a million items, 80-120 ms per body, and four such
bodies sent at once held the loop 0.30-0.39 s (scripts/worst_inputs_lag.py
--concurrent 4). Every item after the first in a list or object follows a comma,
so the comma count bounds them, commas inside strings included. A full-target
draft of 100 entries holds a few thousand, a 60,000-character résumé of English
prose about 1,200 (one in every 50 characters); the bound is 50,000. With it the
worst body four requests send at once holds the loop about 0.15 s (50,000
one-key objects), and the container bound is reached only by nesting.

/api/tailor/extract-bullets and /api/tailor/structure take one résumé of up to
MAX_RESUME_TEXT_CHARACTERS, every character of which may be a comma or a bracket, and
origin/main reads such a résumé whole (criterion E). Their routes (ResumeJSONRoute) allow as
many commas as the résumé has characters, plus the few between the request's own fields; the
container bound already sits above any résumé.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from backend.lib.resume_input import MAX_RESUME_TEXT_CHARACTERS

MAX_JSON_CONTAINERS = 100_000
MAX_JSON_SEPARATORS = 50_000
MAX_RESUME_JSON_SEPARATORS = MAX_RESUME_TEXT_CHARACTERS + 100


def check_body_bounds(body: bytes, max_separators: int = MAX_JSON_SEPARATORS) -> None:
    """Raise the RequestValidationError each route already answers when the body holds too many containers
    or too many items (commas)."""
    if body.count(b"[") + body.count(b"{") > MAX_JSON_CONTAINERS or body.count(b",") > max_separators:
        raise RequestValidationError([{"type": "too_long", "loc": ("body",), "msg": "Request input is invalid.",
                                       "input": None}])


async def refuse_container_heavy_body(request: Request, max_separators: int = MAX_JSON_SEPARATORS) -> None:
    """check_body_bounds on the request's body, on the event loop, before FastAPI parses it.

    The three counts read the whole body: about 4 ms for 2 MiB. The full-target routes, whose
    bodies reach 2 MiB, run them on their request lane instead (routes/target_resume_ai.py).
    """
    check_body_bounds(await request.body(), max_separators)


class BoundedJSONRoute(APIRoute):
    """An APIRoute that refuses a container-heavy JSON body before FastAPI parses it."""

    max_separators = MAX_JSON_SEPARATORS

    def get_route_handler(self):
        original = super().get_route_handler()
        max_separators = self.max_separators

        async def handler(request: Request):
            await refuse_container_heavy_body(request, max_separators)
            return await original(request)

        return handler


class ResumeJSONRoute(BoundedJSONRoute):
    """BoundedJSONRoute for a route that reads one résumé: a comma may stand in each of its characters."""

    max_separators = MAX_RESUME_JSON_SEPARATORS
