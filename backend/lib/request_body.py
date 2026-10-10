"""Refuse, before it is parsed, a JSON request body whose structure is larger than its route allows.

Each route bounds two counts of a body, both read outside JSON strings: its lists and objects
(structural_containers), and the commas between items (structural_separators), one before every
item of a list or object but the first. Text inside strings counts for nothing, so a résumé or a
profile may hold any brackets and commas its own limits allow.

Every endpoint that reads a JSON body declares its bounds (json_body_bounds), and its route class
(BoundedJSONRoute, or the full-target routes' request lane) refuses a body past either before the
body is parsed. A route whose body limit is above the default reads and validates its body on the
request lane (json_body_on_lane, or the full-target routes' own preparation there). The bounds sit
well above what the route's legitimate requests hold:
scripts/request_body_containers.py finds every route of the app that reads a JSON body, builds the
largest body each request schema accepts and prints both counts beside the bounds, and
scripts/worst_inputs_lag.py measures bodies at and past them.

The models of those bodies bound how many items and keys of a body they validate: a model that
refuses unknown keys refuses an object with more keys than it has fields (known_keys), and a list the
schema leaves unbounded is cut to the most its route reads, or refused at once when an item is not a
string, before its items are validated (backend.schemas; the export checks its block and line limits
first). scripts/request_body_containers.py (validation_bodies) builds, for every JSON route, bodies
within its bounds for each list and object its schema declares.

/api/tailor/extract-bullets and /api/tailor/structure take one résumé of up to
MAX_RESUME_TEXT_CHARACTERS, which origin/main reads whole (criterion E). They have a container bound
of their own and keep the comma bound round 5 gave them (a comma per résumé character, plus 100),
set when commas inside strings still counted.
"""
from __future__ import annotations

import email.message
import json
from itertools import repeat
from typing import NamedTuple

from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import TypeAdapter, ValidationError
from pydantic_core import PydanticCustomError

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


def _unescaped(text: bytes | str) -> bytes | str:
    """A JSON text without its escaped backslashes, then without its escaped quotes, so every
    quote left opens or closes a string."""
    quote, backslash = ('"', "\\") if isinstance(text, str) else (b'"', b"\\")
    if backslash in text:
        text = text.replace(backslash + backslash, text[:0]).replace(backslash + quote, text[:0])
    return text


def _outside_strings(text: bytes | str) -> bytes | str:
    """The pieces of a JSON text that lie outside its strings, joined.

    Once the text is _unescaped, the pieces between its quotes alternate outside and inside.
    For a body json.loads rejects, the pieces agree with it up to the first error, and nothing
    after that is built.
    """
    text = _unescaped(text)
    return text[:0].join(text.split('"' if isinstance(text, str) else b'"')[::2])


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
    anywhere has its strings set aside before they are counted again, and only once its quotes are
    counted: each string of a JSON text is a key or an item of a list or object, or the whole text,
    and a text within both bounds has at most max_separators + max_containers items, so at most
    twice that many strings plus one. A text with more is past a bound, or is not JSON.
    """
    text = _json_text(body)
    lists, objects, commas, quote = (b"[", b"{", b",", b'"') if isinstance(text, bytes) else ("[", "{", ",", '"')
    if text.count(commas) <= max_separators and text.count(lists) + text.count(objects) <= max_containers:
        return
    text = _unescaped(text)
    if text.count(quote) <= 2 * (2 * (max_separators + max_containers) + 1):
        outside = text[:0].join(text.split(quote)[::2])
        if outside.count(commas) <= max_separators and outside.count(lists) + outside.count(objects) <= max_containers:
            return
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


# The body limit of every route without a larger one of its own (backend.main.RequestBodyLimitMiddleware;
# OFE_MAX_REQUEST_BODY_BYTES can change it, docs/RELEASE.md). A body larger than it is counted on the
# request lane.
DEFAULT_MAX_REQUEST_BODY_BYTES = 1024 * 1024
LANE_BODY_BYTES = DEFAULT_MAX_REQUEST_BODY_BYTES


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


def known_keys(cls, value):
    """A model that refuses unknown keys refuses, as one error, an object with more keys than the model
    has fields, before any of its keys is validated. Use as model_validator(mode="before")(known_keys).

    Such an object holds at least one unknown key, so the model refuses it either way."""
    if isinstance(value, dict) and len(value) > len(cls.model_fields):
        raise PydanticCustomError("extra_forbidden", "Extra inputs are not permitted")
    return value


def string_items(values):
    """A list refused, as one error, when an item is not a string, before its items are validated.
    Use as field_validator(name, mode="before")(string_items) on a list[str] field."""
    if isinstance(values, list) and not all(map(isinstance, values, repeat(str))):
        raise PydanticCustomError("string_type", "Input should be a valid string")
    return values


def validated_json_body(body: bytes, content_type: str | None, adapter: TypeAdapter):
    """The body read and validated as FastAPI reads a body parameter of the adapter's type
    (fastapi.routing.get_request_handler and fastapi.dependencies.utils.request_body_to_args), with
    the same errors: only an application/json (or +json) body is read as JSON, invalid JSON is a
    validation error, any other failure to parse is a 400, and no body is a missing one."""
    value = None
    if body:
        value = body
        message = email.message.Message()
        message["content-type"] = content_type or ""
        subtype = message.get_content_subtype()
        if content_type and message.get_content_maintype() == "application" and (
                subtype == "json" or subtype.endswith("+json")):
            try:
                value = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RequestValidationError([{"type": "json_invalid", "loc": ("body", exc.pos), "msg": "JSON decode error",
                                               "input": {}, "ctx": {"error": exc.msg}}]) from None
            except Exception:  # noqa: BLE001 — FastAPI answers 400 to any other parse failure (bad UTF-8, recursion)
                raise HTTPException(status_code=400, detail="There was an error parsing the body") from None
    if value is None:
        raise RequestValidationError([{"type": "missing", "loc": ("body",), "msg": "Field required", "input": None}])
    try:
        return adapter.validate_python(value, from_attributes=True)
    except ValidationError as exc:
        raise RequestValidationError([{**error, "loc": ("body", *error["loc"])}
                                      for error in exc.errors(include_url=False)]) from None


def json_body_on_lane(model):
    """A dependency that gives an endpoint its JSON body, read and validated for ``model``
    (validated_json_body) on the request lane (blocking.run_request_work) instead of the event loop.

    For a route whose body limit is above the default, the endpoint takes its body this way rather
    than as a body parameter; its route class still refuses a body past its declared bounds first.
    """
    adapter = TypeAdapter(model)

    async def json_body(request: Request):
        return await run_request_work(validated_json_body, await request.body(), request.headers.get("content-type"),
                                      adapter)

    json_body.json_body_model = model
    return Depends(json_body)


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
