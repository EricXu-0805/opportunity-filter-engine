"""Owner-bound private imports. CRUD only; no writing, network import, or publication."""

from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from backend.lib.private_import_targets import PrivateTargetService, new_client, settings
from backend.lib.private_import_targets_schema import (
    PRIVATE,
    DeleteRequest,
    PrivateTargetError,
    SaveRequest,
    Scope,
    identifier,
    timestamp,
)
from backend.lib.private_target_resolution import resolve_private_import_target


class PrivateTargetRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
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


@router.get("/{target_id}")
async def read_target(target_id: str, request: Request):
    identifier(target_id)
    scope, _ = query(request)
    async with service_for(request, scope) as service:
        result = await service.read(target_id, scope)
    return JSONResponse(result, headers=PRIVATE)


@router.put("/{target_id}")
async def save_target(target_id: str, data: SaveRequest, request: Request):
    identifier(target_id)
    if request.query_params:
        raise ValueError("Unexpected query")
    async with service_for(request, data) as service:
        result = await service.save(target_id, data)
    return JSONResponse(result, headers=PRIVATE)


@router.delete("/{target_id}")
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
