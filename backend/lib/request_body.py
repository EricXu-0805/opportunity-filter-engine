"""Refuse, before it is parsed, a JSON request body whose structure is larger than its route allows.

Each route bounds two counts of a body, both read outside JSON strings: its lists and objects
(structural_containers), and the commas between items (structural_separators), one before every
item of a list or object but the first. Text inside strings counts for nothing, so a résumé or a
profile may hold any brackets and commas its own limits allow.

Every endpoint that reads a JSON body declares its bounds (json_body_bounds), and its route class
(BoundedJSONRoute, or the full-target routes' request lane) refuses a body past either before the
body is parsed. The bounds sit well above what the route's legitimate requests hold:
scripts/request_body_containers.py finds every route of the app that reads a JSON body, builds the
largest body each request schema accepts and prints both counts beside the bounds, and
scripts/worst_inputs_lag.py measures bodies at and past them.

/api/tailor/extract-bullets and /api/tailor/structure take one résumé of up to
MAX_RESUME_TEXT_CHARACTERS, which origin/main reads whole (criterion E). They have a container bound
of their own and keep the comma bound round 5 gave them (a comma per résumé character, plus 100),
set when commas inside strings still counted.
"""
from __future__ import annotations

import json
from typing import NamedTuple

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from backend.lib.blocking import run_request_work
from backend.lib.resume_input import MAX_RESUME_TEXT_CHARACTERS

# Lists and objects outside JSON strings, per route. The largest body each route's request schema
# accepts holds 651 (/api/tailor/renovate), 522 (/api/tailor), 520 (/api/tailor/bullet), 1 (either
# extraction route) and 4,435 (a full-target draft at the master's caps, plus at most 49 for support
# groups); scripts/request_body_containers.py builds and prints them.
MAX_JSON_CONTAINERS = 10_000
MAX_RESUME_JSON_CONTAINERS = 100
MAX_FULL_TARGET_JSON_CONTAINERS = 20_000
# Commas outside JSON strings. The same largest bodies hold at most 10,467 (the full-target draft),
# 3,855 on the other writing routes and 1 on either extraction route.
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


def _outside_strings(text: bytes | str) -> bytes | str:
    """The pieces of a JSON text that lie outside its strings, joined.

    Escaped backslashes go first, then escaped quotes, so every quote left opens or
    closes a string; the pieces between them alternate outside and inside. For a body
    json.loads rejects, the pieces agree with it up to the first error, and nothing after
    that is built.
    """
    quote, backslash = ('"', "\\") if isinstance(text, str) else (b'"', b"\\")
    empty = text[:0]
    if backslash in text:
        text = text.replace(backslash + backslash, empty).replace(backslash + quote, empty)
    return empty.join(text.split(quote)[::2])


def structural_containers(text: bytes | str) -> int:
    """The '[' and '{' of a JSON text that json.loads reads as lists and objects."""
    lists, objects = ("[", "{") if isinstance(text, str) else (b"[", b"{")
    outside = _outside_strings(text)
    return outside.count(lists) + outside.count(objects)


def structural_separators(text: bytes | str) -> int:
    """The ',' of a JSON text that json.loads reads between the items of a list or object."""
    return _outside_strings(text).count("," if isinstance(text, str) else b",")


def check_body_bounds(body: bytes, max_separators: int = MAX_JSON_SEPARATORS,
                      max_containers: int = MAX_JSON_CONTAINERS) -> None:
    """Raise the RequestValidationError each route already answers when the body holds more lists
    and objects, or more commas between items, than its route's bounds.

    The counts read the whole body in C. Only a body with more brackets or commas than a bound
    anywhere has its strings set aside before they are counted again.
    """
    text = _json_text(body)
    lists, objects, commas = (b"[", b"{", b",") if isinstance(text, bytes) else ("[", "{", ",")
    if text.count(commas) <= max_separators and text.count(lists) + text.count(objects) <= max_containers:
        return
    outside = _outside_strings(text)
    if outside.count(commas) > max_separators or outside.count(lists) + outside.count(objects) > max_containers:
        raise RequestValidationError([{"type": "too_long", "loc": ("body",), "msg": "Request input is invalid.",
                                       "input": None}])


class JSONBodyBounds(NamedTuple):
    """At most this many lists and objects, and commas between items, outside a body's strings."""

    containers: int
    separators: int


# Each route's bounds are at least four times what the largest body its request schema accepts holds
# (scripts/request_body_containers.py prints both for every JSON route). A profile and a few lists:
# the matching, chat and writing routes, and a private import's save.
WRITING_BOUNDS = JSONBodyBounds(MAX_JSON_CONTAINERS, MAX_JSON_SEPARATORS)
# A résumé master, a full-target draft or an export projection: the cold-email routes and those two.
DOCUMENT_BOUNDS = JSONBodyBounds(MAX_FULL_TARGET_JSON_CONTAINERS, MAX_JSON_SEPARATORS)
# A profile and the ids of every saved or dismissed target. The schema keeps any number of ids, so
# the comma bound sits above what real ids fill the body limit with.
ID_LIST_BOUNDS = JSONBodyBounds(MAX_JSON_CONTAINERS, 100_000)
RESUME_BOUNDS = JSONBodyBounds(MAX_RESUME_JSON_CONTAINERS, MAX_RESUME_JSON_SEPARATORS)
# A few fields, at most 200 ids or 50 mailed items.
SMALL_BOUNDS = JSONBodyBounds(1_000, 5_000)


def json_body_bounds(bounds: JSONBodyBounds):
    """Declare the structural bounds of an endpoint's JSON body (BoundedJSONRoute enforces them)."""
    def declare(endpoint):
        endpoint.json_body_bounds = bounds
        return endpoint
    return declare


def declared_bounds(route: APIRoute) -> JSONBodyBounds | None:
    """The bounds a route's endpoint declares, or None."""
    return getattr(route.endpoint, "json_body_bounds", None)


# A body larger than the default body limit (backend.main) is counted on the request lane.
LANE_BODY_BYTES = 1024 * 1024


async def refuse_container_heavy_body(request: Request, max_separators: int = MAX_JSON_SEPARATORS,
                                      max_containers: int = MAX_JSON_CONTAINERS) -> None:
    """check_body_bounds on the request's body, before FastAPI parses it.

    A body of up to LANE_BODY_BYTES is counted on the event loop. A larger one, which only the
    routes with a larger body limit accept, is counted on the request lane
    (blocking.run_request_work), where the full-target routes run their whole check
    (routes/target_resume_ai.py).
    """
    body = await request.body()
    if len(body) > LANE_BODY_BYTES:
        await run_request_work(check_body_bounds, body, max_separators, max_containers)
    else:
        check_body_bounds(body, max_separators, max_containers)


class BoundedJSONRoute(APIRoute):
    """An APIRoute that refuses a JSON body past its endpoint's declared bounds before the body is parsed.

    The check runs inside any handler a subclass wraps around this one, so a refusal takes the form
    of that route's own validation errors. An endpoint that declares no bounds (one that takes no
    JSON body, or a multipart upload) reads its body as an APIRoute does.
    """

    def get_route_handler(self):
        original = super().get_route_handler()
        bounds = declared_bounds(self)
        if bounds is None:
            return original

        async def handler(request: Request):
            await refuse_container_heavy_body(request, bounds.separators, bounds.containers)
            return await original(request)

        return handler
