"""Shared private PDF archive for applications and confirmed contacts. No model or outbound email."""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response

from backend.lib.material_archive import MaterialService, new_client, settings, validate_pdf
from backend.lib.material_archive_schema import (
    MAX_FILE_BYTES,
    PRIVATE,
    ArchiveScope,
    ContactMaterialDeletion,
    ContactMaterialInput,
    ContactScope,
    MaterialDeletion,
    MaterialError,
    MaterialInput,
    Scope,
    timestamp,
    uuid_text,
)

_IO_CAPACITY = threading.BoundedSemaphore(2)
_REQUEST_TIMEOUT_SECONDS = 110


class MaterialRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                async with asyncio.timeout(_REQUEST_TIMEOUT_SECONDS):
                    return await original(request)
            except MaterialError as exc:
                return JSONResponse({"detail": {"code": exc.code}}, status_code=exc.status, headers=PRIVATE)
            except (ValidationError, ValueError, UnicodeError, json.JSONDecodeError):
                return JSONResponse({"detail": {"code": "material_invalid_request"}}, status_code=422, headers=PRIVATE)
            except HTTPException as exc:
                code = "material_too_large" if exc.status_code == 413 else "material_invalid_request"
                return JSONResponse({"detail": {"code": code}}, status_code=exc.status_code, headers=PRIVATE)
            except (httpx.HTTPError, TimeoutError, OSError, ClientDisconnect):
                return JSONResponse({"detail": {"code": "material_unavailable"}}, status_code=503, headers=PRIVATE)
        return handler


@asynccontextmanager
async def service_for(request: Request):
    url, key = settings()
    async with new_client() as client:
        yield MaterialService(client, url, key, request.headers.get("authorization"))


@asynccontextmanager
async def io_slot():
    if not _IO_CAPACITY.acquire(blocking=False):
        raise MaterialError("material_busy", 503)
    try:
        yield
    finally:
        _IO_CAPACITY.release()


def scope_from_query(request: Request, *, scope_type=Scope, list_query: bool = False) -> tuple[ArchiveScope, str | None, str | None]:
    allowed = {"expected_owner_id", "opportunity_id", scope_type.event_field}
    if list_query:
        allowed |= {"cursor_linked_at", "cursor_record_id"}
    pairs = list(request.query_params.multi_items())
    if len(pairs) != len(dict(pairs)) or any(key not in allowed for key, _ in pairs):
        raise MaterialError("material_invalid_request", 422)
    params = dict(pairs)
    cursor_time, cursor_id = params.pop("cursor_linked_at", None), params.pop("cursor_record_id", None)
    if (cursor_time is None) != (cursor_id is None):
        raise MaterialError("material_invalid_request", 422)
    if cursor_time is not None:
        timestamp(cursor_time)
        uuid_text(cursor_id)
    return scope_type.model_validate(params), cursor_time, cursor_id


def material_router(prefix: str, scope_type, input_type, deletion_type) -> APIRouter:
    # Bind the kind at registration, never from untrusted request metadata.
    router = APIRouter(prefix=prefix, route_class=MaterialRoute)

    @router.post("")
    async def archive_pdf(request: Request):
        async with io_slot(), service_for(request) as service:
            # Reject guests before accepting/spooling their potentially large body.
            uid = await service.authenticate()
            if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
                raise MaterialError("material_invalid_request", 422)
            async with request.form(max_files=1, max_fields=1, max_part_size=8192) as form:
                if len(form.multi_items()) != 2 or set(form) != {"metadata", "file"}:
                    raise MaterialError("material_invalid_request", 422)
                metadata, file = form["metadata"], form["file"]
                if not isinstance(metadata, str) or len(metadata.encode("utf-8")) > 8192 or not isinstance(file, UploadFile):
                    raise MaterialError("material_invalid_request", 422)
                data = input_type.model_validate_json(metadata)
                if data.expected_owner_id != uid:
                    raise MaterialError("material_owner_mismatch", 409)
                if file.content_type not in (None, "", "application/pdf", "application/octet-stream"):
                    raise MaterialError("material_invalid_pdf", 422)
                contents = await file.read(MAX_FILE_BYTES + 1)
                if len(contents) > MAX_FILE_BYTES:
                    raise MaterialError("material_too_large", 413)
                if len(contents) != data.byte_length or hashlib.sha256(contents).hexdigest() != data.bytes_sha256:
                    raise MaterialError("material_invalid_request", 422)
                try:
                    await validate_pdf(contents)
                except TimeoutError:
                    raise MaterialError("material_invalid_pdf", 422) from None
                result = await service.archive(data, contents)
                return JSONResponse(result, headers=PRIVATE)


    @router.get("")
    async def list_materials(request: Request):
        scope, cursor_time, cursor_id = scope_from_query(request, scope_type=scope_type, list_query=True)
        async with service_for(request) as service:
            await service.authenticate(scope)
            result = await service.list(scope, cursor_time, cursor_id)
        return JSONResponse(result, headers=PRIVATE)


    @router.get("/{record_id}")
    async def get_material(request: Request, record_id: str):
        uuid_text(record_id)
        scope, _, _ = scope_from_query(request, scope_type=scope_type)
        async with service_for(request) as service:
            await service.authenticate(scope)
            record = await service.lookup(scope, record_id)
        return JSONResponse({"version": 1, "record": record}, headers=PRIVATE)


    @router.get("/{record_id}/file")
    async def download_material(request: Request, record_id: str):
        uuid_text(record_id)
        scope, _, _ = scope_from_query(request, scope_type=scope_type)
        async with io_slot(), service_for(request) as service:
            await service.authenticate(scope)
            record, contents = await service.download(scope, record_id)
        return Response(contents, media_type="application/pdf", headers={
            **PRIVATE, "Content-Disposition": f"attachment; filename=\"material.pdf\"; filename*=UTF-8''{quote(record['filename'], safe='')}",
            "x-ofe-material-id": record["material_id"], "x-ofe-material-record": record["record_id"],
            "x-ofe-material-sha256": record["bytes_sha256"],
        })


    @router.delete("/{record_id}")
    async def delete_material(request: Request, record_id: str):
        uuid_text(record_id)
        scope = deletion_type.model_validate(await request.json())
        async with service_for(request) as service:
            await service.authenticate(scope)
            result = await service.delete(scope, record_id, scope.material_id)
        return JSONResponse(result, headers=PRIVATE)
    return router


router = APIRouter()
router.include_router(material_router("/application-materials", Scope, MaterialInput, MaterialDeletion))
router.include_router(material_router("/contact-materials", ContactScope, ContactMaterialInput, ContactMaterialDeletion))
