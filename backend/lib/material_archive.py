"""Private original-PDF archive, with scoped RPC authority and exact retries."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

from backend.lib.material_archive_schema import (
    BUCKET,
    MAX_FILE_BYTES,
    ArchiveInput,
    ArchiveScope,
    MaterialError,
    receipt,
    require_input_match,
    timestamp,
    utc_timestamp,
    uuid_text,
)
from backend.lib.release_scope import session_provider_accepted

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def settings() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key or os.environ.get("OFE_MATERIAL_ARCHIVE_ENABLED", "1") != "1":
        raise MaterialError("material_not_configured", 503)
    return url, key


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(45, connect=5), follow_redirects=False, trust_env=False)


async def validate_pdf(data: bytes) -> None:
    if not data or len(data) > MAX_FILE_BYTES:
        raise MaterialError("material_too_large", 413)
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        raise MaterialError("material_invalid_pdf", 422)
    # A malformed parser input cannot keep a thread alive forever. The child
    # receives only bytes, never service keys, request identities or filenames.
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR") if k in os.environ}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "backend.lib.material_pdf_check", cwd=PROJECT_ROOT, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.communicate(data), timeout=10)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise MaterialError("material_invalid_pdf", 422)


class MaterialService:
    def __init__(self, client: httpx.AsyncClient, url: str, key: str, authorization: str | None = None):
        self.client, self.url, self.key, self.authorization = client, url, key, authorization

    def headers(self, *, user: bool = False) -> dict:
        return {"apikey": self.key, "Authorization": self.authorization if user else f"Bearer {self.key}"}

    async def authenticate(self, scope: ArchiveScope | None = None) -> str:
        if (not self.authorization or not self.authorization.startswith("Bearer ")
                or not self.authorization[7:].strip() or len(self.authorization) > 16384):
            raise MaterialError("material_auth_required", 401)
        response = await self.client.get(f"{self.url}/auth/v1/user", headers=self.headers(user=True))
        if response.status_code in (401, 403, 404):
            raise MaterialError("material_auth_required", 401)
        if response.status_code != 200:
            raise MaterialError()
        try:
            user = response.json()
            uid = uuid_text(user["id"])
            if user.get("is_anonymous") is not False or not session_provider_accepted(user):
                raise MaterialError("material_auth_required", 401)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise MaterialError("material_auth_required", 401) from None
        if scope is not None and uid != scope.expected_owner_id:
            raise MaterialError("material_owner_mismatch", 409)
        return uid

    async def rpc(self, name: str, data: dict, *, user: bool = True) -> dict:
        response = await self.client.post(f"{self.url}/rest/v1/rpc/{name}", headers=self.headers(user=user), json=data)
        try:
            result = response.json()
        except ValueError:
            raise MaterialError("material_invalid_receipt", 502) from None
        if response.status_code >= 400:
            sqlstate = result.get("code") if isinstance(result, dict) else None
            errors = {
                "42501": ("material_auth_required", 401),
                "22023": ("material_invalid_request", 422),
                "23505": ("material_conflict", 409),
                "P0002": ("material_not_found", 404),
                "55000": ("material_not_ready", 409),
            }
            code, status = errors.get(sqlstate, ("material_unavailable", 503))
            raise MaterialError(code, status)
        if not 200 <= response.status_code < 300 or not isinstance(result, dict):
            raise MaterialError("material_invalid_receipt", 502)
        return result

    @staticmethod
    def scope_args(scope: ArchiveScope) -> dict:
        return {
            "p_expected_owner": scope.expected_owner_id, f"p_{scope.event_field}": getattr(scope, scope.event_field),
            "p_opportunity_id": scope.opportunity_id,
        }

    async def lookup(self, scope: ArchiveScope, record_id: str) -> dict:
        result = await self.rpc(f"get_{scope.material_kind}_material", {**self.scope_args(scope), "p_record_id": record_id})
        if set(result) != {"artifact"}:
            raise MaterialError("material_invalid_receipt", 502)
        if result["artifact"] is None:
            raise MaterialError("material_not_found", 404)
        return receipt(result["artifact"], scope, record_id=record_id)

    async def list(self, scope: ArchiveScope, cursor_time: str | None, cursor_id: str | None) -> dict:
        result = await self.rpc(f"list_{scope.material_kind}_materials", {
            **self.scope_args(scope), "p_limit": 20, "p_before_recorded_at": cursor_time, "p_before_record_id": cursor_id,
        })
        try:
            if set(result) != {"items", "next_cursor"} or not isinstance(result["items"], list) or len(result["items"]) > 20:
                raise ValueError
            items = [receipt(row, scope) for row in result["items"]]
            previous = (datetime.fromisoformat(cursor_time.replace("Z", "+00:00")), cursor_id) if cursor_time else None
            ids = set()
            for item in items:
                if item["status"] == "staged" or item["linked_at"] is None or item["record_id"] in ids:
                    raise ValueError
                ids.add(item["record_id"])
                key = (datetime.fromisoformat(item["linked_at"].replace("Z", "+00:00")), item["record_id"])
                if previous is not None and key >= previous:
                    raise ValueError
                previous = key
            cursor = result["next_cursor"]
            if cursor is not None:
                if (not isinstance(cursor, dict) or set(cursor) != {"recorded_at", "record_id"} or len(items) != 20
                        or utc_timestamp(cursor["recorded_at"]) != items[-1]["linked_at"] or cursor["record_id"] != items[-1]["record_id"]):
                    raise ValueError
                cursor = {"linked_at": utc_timestamp(cursor["recorded_at"]), "record_id": cursor["record_id"]}
        except (ValueError, TypeError, KeyError, AttributeError):
            raise MaterialError("material_invalid_receipt", 502) from None
        return {"version": 1, "items": items, "next_cursor": cursor}

    @staticmethod
    def object_path(material_id: str) -> str:
        return f"pdf/{uuid_text(material_id)}.pdf"

    def verify_location(self, result: dict, record: dict) -> str:
        expected = self.object_path(record["material_id"])
        if result.get("bucket") != BUCKET or result.get("object_key") != expected:
            raise MaterialError("material_invalid_receipt", 502)
        return expected

    async def object_bytes(self, key: str, expected_length: int, expected_sha: str) -> bytes:
        async with self.client.stream("GET", f"{self.url}/storage/v1/object/{BUCKET}/{key}", headers=self.headers()) as response:
            if response.status_code != 200:
                raise MaterialError()
            length = response.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) != expected_length):
                raise MaterialError("material_invalid_receipt", 502)
            chunks, size, digest = [], 0, hashlib.sha256()
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > expected_length or size > MAX_FILE_BYTES:
                    raise MaterialError("material_invalid_receipt", 502)
                digest.update(chunk)
                chunks.append(chunk)
            if size != expected_length or digest.hexdigest() != expected_sha:
                raise MaterialError("material_invalid_receipt", 502)
        return b"".join(chunks)

    async def archive(self, data: ArchiveInput, contents: bytes) -> dict:
        stage = await self.rpc(f"stage_{data.material_kind}_material", {
            **self.scope_args(data), "p_material_id": data.material_id, "p_record_id": data.record_id,
            "p_filename": data.filename, "p_byte_length": data.byte_length, "p_sha256": data.bytes_sha256,
        })
        if set(stage) != {"artifact", "upload", "replayed"} or type(stage["replayed"]) is not bool:
            raise MaterialError("material_invalid_receipt", 502)
        record = receipt(stage["artifact"], data, record_id=data.record_id)
        if record["status"] == "deleted":
            raise MaterialError("material_deleted", 410)
        require_input_match(record, data)
        if record["status"] == "ready":
            if stage["upload"] is not None:
                raise MaterialError("material_invalid_receipt", 502)
            return {"version": 1, "record": record, "replayed": True}
        upload = stage["upload"]
        try:
            if not isinstance(upload, dict) or set(upload) != {"bucket", "object_key", "stage_token", "session_id", "authorized_until"}:
                raise ValueError
            key = self.verify_location(upload, record)
            uuid_text(upload["stage_token"])
            uuid_text(upload["session_id"])
            timestamp(upload["authorized_until"])
        except (TypeError, ValueError, KeyError):
            raise MaterialError("material_invalid_receipt", 502) from None
        response = await self.client.post(
            f"{self.url}/storage/v1/object/{BUCKET}/{key}", content=contents,
            headers={**self.headers(), "Content-Type": "application/pdf", "x-upsert": "false", "Cache-Control": "no-store"},
        )
        if response.status_code not in (200, 201, 400, 409):
            raise MaterialError()
        if response.status_code == 400:
            try:
                duplicate = response.json()
                if duplicate.get("statusCode") not in ("409", 409) and duplicate.get("error") != "Duplicate":
                    raise MaterialError()
            except (ValueError, TypeError, AttributeError):
                raise MaterialError() from None
        # Always hash the bytes read from Storage, not an upload acknowledgement.
        await self.object_bytes(key, data.byte_length, data.bytes_sha256)
        result = await self.rpc(f"finalize_{data.material_kind}_material", {
            "p_verified_owner": data.expected_owner_id, "p_verified_session_id": upload["session_id"],
            "p_material_id": data.material_id, "p_stage_token": upload["stage_token"],
            "p_verified_byte_length": data.byte_length, "p_verified_sha256": data.bytes_sha256,
        }, user=False)
        if set(result) != {"artifact", "replayed"} or type(result["replayed"]) is not bool:
            raise MaterialError("material_invalid_receipt", 502)
        ready = receipt(result["artifact"], data, record_id=data.record_id)
        if ready["status"] == "deleted":
            raise MaterialError("material_deleted", 410)
        if ready["status"] != "ready":
            raise MaterialError("material_invalid_receipt", 502)
        require_input_match(ready, data)
        return {"version": 1, "record": ready, "replayed": result["replayed"]}

    async def authorize_download(self, scope: ArchiveScope, record_id: str) -> tuple[dict, str]:
        result = await self.rpc(f"authorize_{scope.material_kind}_material_download", {
            **self.scope_args(scope), "p_record_id": record_id,
        })
        if set(result) != {"artifact", "bucket", "object_key"}:
            raise MaterialError("material_invalid_receipt", 502)
        record = receipt(result["artifact"], scope, record_id=record_id)
        if record["status"] != "ready":
            raise MaterialError("material_not_ready", 409)
        return record, self.verify_location(result, record)

    async def download(self, scope: ArchiveScope, record_id: str) -> tuple[dict, bytes]:
        record, key = await self.authorize_download(scope, record_id)
        contents = await self.object_bytes(key, record["byte_length"], record["bytes_sha256"])
        current, current_key = await self.authorize_download(scope, record_id)
        if current != record or current_key != key:
            raise MaterialError("material_invalid_receipt", 502)
        return record, contents

    async def delete(self, scope: ArchiveScope, record_id: str, material_id: str) -> dict:
        result = await self.rpc(f"delete_{scope.material_kind}_material", {**self.scope_args(scope), "p_record_id": record_id, "p_material_id": material_id})
        if set(result) != {"artifact", "replayed"} or type(result["replayed"]) is not bool:
            raise MaterialError("material_invalid_receipt", 502)
        record = receipt(result["artifact"], scope, record_id=record_id)
        if record["status"] != "deleted" or record["material_id"] != material_id:
            raise MaterialError("material_invalid_receipt", 502)
        return {"version": 1, "record": record}

    async def object_absent(self, key: str) -> bool:
        url = f"{self.url}/storage/v1/object/{BUCKET}/{key}"
        check = await self.client.head(url, headers=self.headers())
        if check.status_code == 404:
            return True
        if check.status_code != 400:
            return False
        # Storage may use an empty HTTP 400 for a missing-object HEAD. Read only
        # its bounded error envelope, never a remaining PDF, before accepting it.
        async with self.client.stream("GET", url, headers=self.headers()) as response:
            if response.status_code != 400:
                return False
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=1024):
                data.extend(chunk)
                if len(data) > 4096:
                    return False
            try:
                error = json.loads(data)
            except (ValueError, UnicodeError):
                return False
            return (isinstance(error, dict) and error.get("statusCode") in (404, "404")
                    and error.get("error") == "not_found")

    async def cleanup(self) -> dict:
        result = await self.rpc("claim_material_cleanup", {"p_limit": 20}, user=False)
        jobs = result.get("jobs")
        if set(result) != {"jobs"} or not isinstance(jobs, list) or len(jobs) > 20:
            raise MaterialError("material_invalid_receipt", 502)
        succeeded = failed = 0
        for job in jobs:
            try:
                if not isinstance(job, dict) or set(job) != {"material_id", "bucket", "object_key", "claim_token", "claimed_until"}:
                    raise ValueError
                key = self.object_path(job["material_id"])
                uuid_text(job["claim_token"])
                timestamp(job["claimed_until"])
                if job["bucket"] != BUCKET or job["object_key"] != key:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise MaterialError("material_invalid_receipt", 502) from None
            success = False
            try:
                response = await self.client.request("DELETE", f"{self.url}/storage/v1/object/{BUCKET}",
                                                     headers=self.headers(), json={"prefixes": [key]})
                if response.status_code == 200 and isinstance(response.json(), list):
                    # HEAD avoids reading any remaining file. An authorization or
                    # network failure must not be reported as successful removal.
                    success = await self.object_absent(key)
            except (httpx.HTTPError, ValueError):
                success = False
            ack = await self.rpc("ack_material_cleanup", {
                "p_material_id": job["material_id"], "p_claim_token": job["claim_token"], "p_success": success,
            }, user=False)
            if set(ack) != {"accepted"} or type(ack["accepted"]) is not bool:
                raise MaterialError("material_invalid_receipt", 502)
            if success and ack["accepted"]:
                succeeded += 1
            else:
                failed += 1
        return {"claimed": len(jobs), "succeeded": succeeded, "failed": failed}
