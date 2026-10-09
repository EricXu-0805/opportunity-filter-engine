"""Owner-bound imports and local preparation receipts; no model or publication."""

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from pydantic import Field, ValidationError, field_validator
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from backend.lib.private_email_context import resolve_private_email_context
from backend.lib.private_import_targets import (
    PrivateTargetService,
    caller_verified_before_parsing,
    new_client,
    settings,
)
from backend.lib.private_import_targets_schema import (
    MAX_BODY_BYTES,
    MAX_PAYLOAD_BYTES,
    PRIVATE,
    DeleteRequest,
    PrivateTargetError,
    SaveRequest,
    Scope,
    identifier,
    timestamp,
)
from backend.lib.private_target_resolution import project_private_target, resolve_private_import_target
from backend.lib.request_body import SMALL_BOUNDS, WRITING_BOUNDS, BoundedJSONRoute, json_body_bounds

TRACKER_BATCH_LIMIT = 100
_TRACKER_BATCH_CONCURRENCY = 4
# Only a save carries an import. A delete or a tracker batch is an owner id, a
# revision and at most 100 ids, so the 8 MiB allowance the body middleware
# grants this whole prefix is never a legitimate size for them.
_SMALL_BODY_BYTES = MAX_BODY_BYTES - MAX_PAYLOAD_BYTES


async def _screen_body(request: Request) -> None:
    """Size, then credential shape, before FastAPI parses the JSON.

    Parsing and validating an 8 MiB import is real event-loop work, and it used
    to run for callers with no credential at all, ahead of the 401. The shape
    check mirrors the first gate of PrivateTargetService.authenticate. A save
    additionally has its token verified over the network before parsing (see
    the route handler); the small delete and batch bodies keep this screen only.
    """
    limit = MAX_BODY_BYTES if request.method == "PUT" else _SMALL_BODY_BYTES
    declared = request.headers.get("content-length", "")
    if (declared.isdecimal() and int(declared) > limit) or len(await request.body()) > limit:
        raise PrivateTargetError("private_target_too_large", 413)
    authorization = request.headers.get("authorization")
    if (
        not authorization
        or not authorization.startswith("Bearer ")
        or not authorization[7:].strip()
        or len(authorization) > 16384
    ):
        raise PrivateTargetError("private_target_auth_required", 401)


class PrivateTargetRoute(BoundedJSONRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                if request.method in ("PUT", "DELETE", "POST"):
                    await _screen_body(request)
                if request.method == "PUT":
                    async with caller_verified_before_parsing(request.headers.get("authorization"), new_client):
                        return await original(request)
                return await original(request)
            except PrivateTargetError as exc:
                return JSONResponse({"detail": {"code": exc.code}}, status_code=exc.status, headers=PRIVATE)
            except (RequestValidationError, ValidationError, ValueError, UnicodeError, RecursionError):
                return JSONResponse(
                    {"detail": {"code": "private_target_invalid_request"}}, status_code=422, headers=PRIVATE
                )
            except HTTPException as exc:
                code = "private_target_too_large" if exc.status_code == 413 else "private_target_invalid_request"
                return JSONResponse({"detail": {"code": code}}, status_code=exc.status_code, headers=PRIVATE)
            except (httpx.HTTPError, TimeoutError, OSError):
                return JSONResponse(
                    {"detail": {"code": "private_target_unavailable"}}, status_code=503, headers=PRIVATE
                )

        return handler


router = APIRouter(prefix="/private-import-targets", route_class=PrivateTargetRoute)


@asynccontextmanager
async def service_for(request: Request, scope: Scope):
    url, key = settings()
    async with new_client() as client:
        service = PrivateTargetService(client, url, key, request.headers.get("authorization"))
        await service.authenticate(scope)
        yield service


def query(request: Request, *, listing=False):
    allowed = {"expected_owner_id"} | ({"before_updated_at", "before_id", "limit"} if listing else set())
    pairs = list(request.query_params.multi_items())
    if len(pairs) != len(dict(pairs)) or any(key not in allowed for key, _ in pairs):
        raise ValueError("Invalid query")
    params = dict(pairs)
    scope = Scope(expected_owner_id=params.pop("expected_owner_id", None))
    return scope, params


@router.get("")
async def list_targets(request: Request):
    scope, params = query(request, listing=True)
    before_time, before_id = params.get("before_updated_at"), params.get("before_id")
    if (before_time is None) != (before_id is None):
        raise ValueError("Incomplete cursor")
    if before_time is not None:
        timestamp(before_time)
        identifier(before_id)
    raw_limit = params.get("limit", "20")
    if not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= 50:
        raise ValueError("Invalid limit")
    async with service_for(request, scope) as service:
        result = await service.list(scope, before_time, before_id, int(raw_limit))
    return JSONResponse(result, headers=PRIVATE)


class TrackerBatchRequest(Scope):
    ids: list[str] = Field(min_length=1, max_length=TRACKER_BATCH_LIMIT)

    @field_validator("ids")
    @classmethod
    def private_unique(cls, value: list[str]) -> list[str]:
        for item in value:
            identifier(item)
        if len(set(value)) != len(value):
            raise ValueError("Duplicate identifier")
        return value


@router.post("/resolved")
@json_body_bounds(SMALL_BOUNDS)
async def read_resolved_targets(data: TrackerBatchRequest, request: Request):
    """Tracker identity for many owned targets in one rate-limited request.

    Each row goes through the same read and projection as /{id}/resolved; only a
    deleted or missing row becomes a per-item status, any other failure fails
    the whole batch so an outage is never shown as a missing target.
    """
    if request.query_params:
        raise ValueError("Unexpected query")
    async with service_for(request, data) as service:
        gate = asyncio.Semaphore(_TRACKER_BATCH_CONCURRENCY)

        async def one(target_id: str) -> dict:
            async with gate:
                try:
                    target = (await service.read(target_id, data))["target"]
                except PrivateTargetError as exc:
                    if exc.code == "private_target_not_found":
                        return {"id": target_id, "status": "not_found"}
                    raise
            if target["deleted_at"] is not None:
                return {"id": target_id, "status": "deleted"}
            resolved = project_private_target(target, expected_owner_id=data.expected_owner_id, target_id=target_id)
            return {"id": target_id, "status": "resolved", "revision": resolved.revision, "tracker": resolved.tracker}

        results = await asyncio.gather(*(one(target_id) for target_id in data.ids), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return JSONResponse({"version": 1, "items": results}, headers=PRIVATE)


@router.get("/{target_id}")
async def read_target(target_id: str, request: Request):
    identifier(target_id)
    scope, _ = query(request)
    async with service_for(request, scope) as service:
        result = await service.read(target_id, scope)
    return JSONResponse(result, headers=PRIVATE)


@router.put("/{target_id}")
@json_body_bounds(WRITING_BOUNDS)
async def save_target(target_id: str, data: SaveRequest, request: Request):
    identifier(target_id)
    if request.query_params:
        raise ValueError("Unexpected query")
    async with service_for(request, data) as service:
        result = await service.save(target_id, data)
    return JSONResponse(result, headers=PRIVATE)


@router.delete("/{target_id}")
@json_body_bounds(SMALL_BOUNDS)
async def delete_target(target_id: str, data: DeleteRequest, request: Request):
    identifier(target_id)
    if request.query_params:
        raise ValueError("Unexpected query")
    async with service_for(request, data) as service:
        result = await service.delete(target_id, data)
    return JSONResponse(result, headers=PRIVATE)


@router.get("/{target_id}/resolved")
async def read_resolved_target(target_id: str, request: Request):
    pairs = list(request.query_params.multi_items())
    if len(pairs) != len(dict(pairs)) or any(
        key not in {"expected_owner_id", "expected_target_version"} for key, _ in pairs
    ):
        raise ValueError("Invalid query")
    params = dict(pairs)
    result = await resolve_private_import_target(
        target_id,
        authorization=request.headers.get("authorization"),
        expected_owner_id=params.get("expected_owner_id"),
        expected_target_version=params.get("expected_target_version"),
    )
    return JSONResponse(result.as_dict(), headers=PRIVATE)


@router.get("/{target_id}/email-context")
async def read_private_email_context(target_id: str, request: Request):
    scope, _ = query(request)
    result = await resolve_private_email_context(
        target_id, authorization=request.headers.get("authorization"),
        expected_owner_id=scope.expected_owner_id,
    )
    return JSONResponse(result, headers=PRIVATE)
