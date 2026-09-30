"""Authenticated private import CRUD. Never resolves a canonical writing target."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime

import httpx

from backend.lib.private_import_targets_schema import (
    DeleteRequest,
    PrivateTargetError,
    SaveRequest,
    Scope,
    identifier,
    opportunity,
    owner,
    timestamp,
)
from backend.lib.release_scope import session_provider_accepted
from src.import_source import import_source_from_raw


def settings() -> tuple[str, str]:
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise PrivateTargetError()
    return url, key


def new_client():
    return httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False)


def target_receipt(raw: object, expected_owner: str, target_id: str | None = None) -> dict:
    keys = {"id", "owner_id", "revision", "opportunity", "created_at", "updated_at", "deleted_at"}
    try:
        if not isinstance(raw, dict) or set(raw) != keys:
            raise ValueError
        identifier(raw["id"])
        owner(raw["owner_id"])
        if raw["owner_id"] != expected_owner or (target_id is not None and raw["id"] != target_id):
            raise ValueError
        if type(raw["revision"]) is not int or not 1 <= raw["revision"] <= 9007199254740991:
            raise ValueError
        timestamp(raw["created_at"])
        timestamp(raw["updated_at"])
        created = datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00"))
        updated = datetime.fromisoformat(raw["updated_at"].replace("Z", "+00:00"))
        if updated < created:
            raise ValueError
        if raw["deleted_at"] is not None:
            timestamp(raw["deleted_at"])
            if datetime.fromisoformat(raw["deleted_at"].replace("Z", "+00:00")) != updated:
                raise ValueError
            if raw["opportunity"] is not None:
                raise ValueError
        else:
            opportunity(raw["opportunity"])
        labels = import_source_from_raw(raw["opportunity"]) if raw["opportunity"] is not None else None
        material = json.dumps(
            {key: raw[key] for key in ("id", "owner_id", "revision")},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, KeyError, UnicodeError, PrivateTargetError):
        raise PrivateTargetError("private_target_invalid_receipt", 502) from None
    return {
        **raw,
        "import_source": labels,
        "target_scope": "private_import",
        "verification": "unverified",
        "target_version": "pit1:" + hashlib.sha256(material).hexdigest(),
    }


# (exact Authorization header, verified user id) for the current request only.
_verified_caller: ContextVar[tuple[str, str] | None] = ContextVar("private_verified_caller", default=None)


@asynccontextmanager
async def caller_verified_before_parsing(authorization: str | None, client_factory):
    """Verify the bearer over the network before a private body is parsed.

    The owner comparison needs the parsed expected_owner_id, so it stays in
    authenticate(); within this block authenticate() reuses this lookup for the
    same header instead of asking Supabase a second time.
    """
    url, key = settings()
    async with client_factory() as client:
        uid = await PrivateTargetService(client, url, key, authorization).verify_user()
    token = _verified_caller.set((authorization, uid))
    try:
        yield
    finally:
        _verified_caller.reset(token)


class PrivateTargetService:
    def __init__(self, client, url: str, key: str, authorization: str | None):
        self.client, self.url, self.key, self.authorization = client, url, key, authorization

    def headers(self):
        return {"apikey": self.key, "Authorization": self.authorization}

    async def verify_user(self) -> str:
        """Supabase's own answer for this bearer token; no owner comparison."""
        if (
            not self.authorization
            or not self.authorization.startswith("Bearer ")
            or not self.authorization[7:].strip()
            or len(self.authorization) > 16384
        ):
            raise PrivateTargetError("private_target_auth_required", 401)
        verified = _verified_caller.get()
        if verified is not None and verified[0] == self.authorization:
            return verified[1]
        response = await self.client.get(f"{self.url}/auth/v1/user", headers=self.headers())
        if response.status_code in (401, 403, 404):
            raise PrivateTargetError("private_target_auth_required", 401)
        if response.status_code != 200:
            raise PrivateTargetError()
        try:
            user = response.json()
            uid = owner(user["id"])
            if user.get("is_anonymous") is not False or not session_provider_accepted(user):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            raise PrivateTargetError("private_target_auth_required", 401) from None
        return uid

    async def authenticate(self, scope: Scope):
        uid = await self.verify_user()
        if uid != scope.expected_owner_id:
            raise PrivateTargetError("private_target_owner_changed", 409)
        return uid

    async def rpc(self, name: str, args: dict) -> dict:
        response = await self.client.post(f"{self.url}/rest/v1/rpc/{name}", headers=self.headers(), json=args)
        try:
            result = response.json()
        except ValueError:
            raise PrivateTargetError("private_target_invalid_receipt", 502) from None
        if response.status_code >= 400:
            code = result.get("code") if isinstance(result, dict) else None
            mapped = {
                "42501": ("private_target_auth_required", 401),
                "22023": ("private_target_invalid_request", 422),
                "54000": ("private_target_too_large", 413),
                "23505": ("private_target_conflict", 409),
                "P0002": ("private_target_not_found", 404),
                "55000": ("private_target_deleted", 409),
            }
            raise PrivateTargetError(*mapped.get(code, ("private_target_unavailable", 503)))
        if not 200 <= response.status_code < 300 or not isinstance(result, dict):
            raise PrivateTargetError("private_target_invalid_receipt", 502)
        return result

    async def read(self, target_id: str, scope: Scope):
        result = await self.rpc(
            "read_private_import_target", {"p_expected_owner": scope.expected_owner_id, "p_id": target_id}
        )
        if set(result) != {"target"}:
            raise PrivateTargetError("private_target_invalid_receipt", 502)
        if result["target"] is None:
            raise PrivateTargetError("private_target_not_found", 404)
        return {
            "version": 1,
            "target": target_receipt(result["target"], scope.expected_owner_id, target_id),
            "replayed": False,
        }

    async def save(self, target_id: str, request: SaveRequest):
        result = await self.rpc(
            "save_private_import_target",
            {
                "p_expected_owner": request.expected_owner_id,
                "p_id": target_id,
                "p_expected_revision": request.expected_revision,
                "p_opportunity": request.opportunity,
            },
        )
        receipt = self._mutation_receipt(result, target_id, request)
        if (
            json.dumps(receipt["target"]["opportunity"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            != json.dumps(request.opportunity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            or receipt["target"]["revision"] != request.expected_revision + 1
            or receipt["target"]["deleted_at"] is not None
        ):
            raise PrivateTargetError("private_target_invalid_receipt", 502)
        return receipt

    async def delete(self, target_id: str, request: DeleteRequest):
        result = await self.rpc(
            "delete_private_import_target",
            {
                "p_expected_owner": request.expected_owner_id,
                "p_id": target_id,
                "p_expected_revision": request.expected_revision,
            },
        )
        receipt = self._mutation_receipt(result, target_id, request)
        if (
            receipt["target"]["opportunity"] is not None
            or receipt["target"]["revision"] != request.expected_revision + 1
            or receipt["target"]["deleted_at"] is None
        ):
            raise PrivateTargetError("private_target_invalid_receipt", 502)
        return receipt

    @staticmethod
    def _mutation_receipt(result, target_id, scope):
        if set(result) != {"target", "replayed"} or type(result["replayed"]) is not bool:
            raise PrivateTargetError("private_target_invalid_receipt", 502)
        return {
            "version": 1,
            "target": target_receipt(result["target"], scope.expected_owner_id, target_id),
            "replayed": result["replayed"],
        }

    async def list(self, scope: Scope, before_updated_at=None, before_id=None, limit=20):
        result = await self.rpc(
            "list_private_import_targets",
            {
                "p_expected_owner": scope.expected_owner_id,
                "p_before_updated_at": before_updated_at,
                "p_before_id": before_id,
                "p_limit": limit,
            },
        )
        if (
            set(result) != {"items", "next_cursor"}
            or not isinstance(result["items"], list)
            or len(result["items"]) > limit
        ):
            raise PrivateTargetError("private_target_invalid_receipt", 502)
        items = [summary_receipt(raw, scope.expected_owner_id) for raw in result["items"]]
        if any(item["deleted_at"] is not None for item in items) or len({item["id"] for item in items}) != len(items):
            raise PrivateTargetError("private_target_invalid_receipt", 502)
        cursor = result["next_cursor"]
        if cursor is not None and (
            not items or cursor != {"updated_at": items[-1]["updated_at"], "id": items[-1]["id"]}
        ):
            raise PrivateTargetError("private_target_invalid_receipt", 502)
        return {"version": 1, "items": items, "next_cursor": cursor}


def summary_receipt(raw: object, expected_owner: str) -> dict:
    fields = {
        "id",
        "owner_id",
        "revision",
        "created_at",
        "updated_at",
        "deleted_at",
        "title",
        "organization",
        "source_url",
        "url",
        "source",
    }
    if not isinstance(raw, dict) or set(raw) != fields or raw.get("deleted_at") is not None:
        raise PrivateTargetError("private_target_invalid_receipt", 502)
    payload = {key: raw[key] for key in ("title", "organization", "source_url", "url", "source")}
    payload["description_raw"] = "Summary validation only."
    validated = target_receipt(
        {key: raw[key] for key in ("id", "owner_id", "revision", "created_at", "updated_at", "deleted_at")}
        | {"opportunity": payload},
        expected_owner,
    )
    return {**raw, **{key: validated[key] for key in ("target_scope", "verification", "target_version")}}
