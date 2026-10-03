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
"""
from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

MAX_JSON_CONTAINERS = 100_000


async def refuse_container_heavy_body(request: Request) -> None:
    """Raise the RequestValidationError each route already answers when the body holds too many containers."""
    body = await request.body()
    if body.count(b"[") + body.count(b"{") > MAX_JSON_CONTAINERS:
        raise RequestValidationError([{"type": "too_long", "loc": ("body",), "msg": "Request input is invalid.",
                                       "input": None}])


class BoundedJSONRoute(APIRoute):
    """An APIRoute that refuses a container-heavy JSON body before FastAPI parses it."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            await refuse_container_heavy_body(request)
            return await original(request)

        return handler
