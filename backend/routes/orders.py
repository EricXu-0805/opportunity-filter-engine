"""Concierge manual-payment order endpoints.

User path: the client INSERTs its own pending order directly via Supabase
RLS (019_orders.sql), then POSTs /orders/{id}/mark-paid-claimed here after
scanning the QR code. Status transitions are service-role only — the same
service-role httpx pattern as saved_searches.py — so a client can never
flip its own row past 'pending'. The caller is authenticated by handing
their Supabase access token to GoTrue (/auth/v1/user), which returns the
uid the order must belong to.

Operator path: /admin/orders list + /admin/orders/{id}/confirm behind the
X-Admin-Token pattern from admin.py; confirm applies the 'manual' channel
adapter (backend/lib/payments.py).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Header, HTTPException, Query

from backend.lib import payments
from backend.routes.admin import _authenticate
from backend.routes.push import _required_env

router = APIRouter()

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

ORDER_STATUSES = ("pending", "awaiting_confirm", "paid", "cancelled", "refunded")


def _supabase_env() -> tuple[str, dict]:
    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        raise HTTPException(status_code=503, detail="Storage not configured")
    env = env_result
    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
    }
    return supabase_url, headers


async def _caller_uid(
    client: httpx.AsyncClient, supabase_url: str, service_key: str, authorization: str | None,
) -> str:
    """Resolve the caller's Supabase uid by validating their JWT with GoTrue."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    resp = await client.get(
        f"{supabase_url}/auth/v1/user",
        headers={"apikey": service_key, "Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    uid = (resp.json() or {}).get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return str(uid)


async def _fetch_order(
    client: httpx.AsyncClient, supabase_url: str, headers: dict, order_id: str,
) -> dict | None:
    resp = await client.get(
        f"{supabase_url}/rest/v1/orders",
        params={"id": f"eq.{order_id}", "select": "*", "limit": "1"},
        headers=headers,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


@router.post("/orders/{order_id}/mark-paid-claimed")
async def mark_paid_claimed(
    order_id: str,
    authorization: str | None = Header(default=None),
):
    """Authenticated user flags their OWN pending order as awaiting_confirm."""
    if not _UUID_RE.match(order_id):
        raise HTTPException(status_code=400, detail="Invalid order id")

    supabase_url, headers = _supabase_env()

    async with httpx.AsyncClient(timeout=15.0) as client:
        uid = await _caller_uid(client, supabase_url, headers["apikey"], authorization)

        order = await _fetch_order(client, supabase_url, headers, order_id)
        # 404 for both missing and not-yours: don't leak other users' order ids.
        if order is None or order.get("device_id") != uid:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.get("status") != "pending":
            raise HTTPException(
                status_code=409, detail=f"Order is {order.get('status')}, not pending"
            )

        patch_resp = await client.patch(
            f"{supabase_url}/rest/v1/orders",
            params={"id": f"eq.{order_id}", "device_id": f"eq.{uid}", "status": "eq.pending"},
            headers={**headers, "Prefer": "return=minimal"},
            json={"status": "awaiting_confirm"},
        )
        patch_resp.raise_for_status()

    return {"id": order_id, "status": "awaiting_confirm"}


@router.get("/admin/orders")
async def admin_list_orders(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    status: str | None = Query(default=None),
    since_hours: int | None = Query(default=None, ge=1, le=720),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Operator order inbox, newest first. `since_hours` scopes the daily
    new-orders digest; `status` filters (e.g. awaiting_confirm)."""
    _authenticate(x_admin_token)

    if status is not None and status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status filter")

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "skipped", "reason": "supabase env not configured", "missing": missing}

    supabase_url, headers = _supabase_env()
    params: dict[str, str] = {
        "select": "*",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if status is not None:
        params["status"] = f"eq.{status}"
    if since_hours is not None:
        cutoff = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()
        params["created_at"] = f"gte.{cutoff}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{supabase_url}/rest/v1/orders", params=params, headers=headers
            )
            resp.raise_for_status()
            orders = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e

    return {"status": "ok", "orders": orders, "count": len(orders)}


@router.post("/admin/orders/{order_id}/confirm")
async def admin_confirm_order(
    order_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Operator confirms the money actually arrived → paid + paid_at."""
    _authenticate(x_admin_token)

    if not _UUID_RE.match(order_id):
        raise HTTPException(status_code=400, detail="Invalid order id")

    supabase_url, headers = _supabase_env()

    async with httpx.AsyncClient(timeout=15.0) as client:
        order = await _fetch_order(client, supabase_url, headers, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.get("status") == "paid":
            return {"id": order_id, "status": "paid", "paid_at": order.get("paid_at")}
        if order.get("status") not in ("pending", "awaiting_confirm"):
            raise HTTPException(
                status_code=409, detail=f"Order is {order.get('status')} — cannot confirm"
            )

        fields = payments.confirm_order("manual", order)
        patch_resp = await client.patch(
            f"{supabase_url}/rest/v1/orders",
            params={"id": f"eq.{order_id}"},
            headers={**headers, "Prefer": "return=minimal"},
            json=fields,
        )
        patch_resp.raise_for_status()

    return {"id": order_id, **fields}
