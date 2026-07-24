"""Contract tests for the concierge order endpoints (backend/routes/orders.py).

All Supabase traffic (GoTrue token check + PostgREST reads/writes) is stubbed
at the httpx.AsyncClient boundary — tests never touch the network. Pinned:

  * mark-paid-claimed: bearer-token boundary (missing/invalid → 401),
    wrong owner → 404 (no existence leak), non-pending → 409,
    happy path PATCHes status=awaiting_confirm scoped to id+uid+pending
  * admin list/confirm: X-Admin-Token gate (503 unset / 401 wrong),
    list forwards status + since_hours filters, confirm sets paid+paid_at
    via the manual channel adapter and is idempotent for already-paid
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.lib import payments
from backend.main import app

client = TestClient(app)

ORDER_ID = "11111111-2222-4333-8444-555555555555"
UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_UID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
USER_AUTH = {"Authorization": "Bearer user-jwt"}
ADMIN_AUTH = {"X-Admin-Token": "admin-ok"}


def _order(**overrides):
    row = {
        "id": ORDER_ID,
        "device_id": UID,
        "package": "single_email",
        "amount_cents": 990,
        "currency": "usd",
        "status": "pending",
        "channel": "manual",
        "note": None,
        "created_at": "2026-07-05T00:00:00+00:00",
        "paid_at": None,
    }
    row.update(overrides)
    return row


def _set_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")


class _Resp:
    def __init__(self, data=None, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def _install_client(monkeypatch, *, auth_status=200, auth_uid=UID, orders=None,
                    gets=None, patches=None, patch_rows=None):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            if gets is not None:
                gets.append({"url": url, **kwargs})
            if "/auth/v1/user" in url:
                return _Resp({"id": auth_uid} if auth_uid else {}, auth_status)
            return _Resp(orders if orders is not None else [])

        async def patch(self, url, **kwargs):
            if patches is not None:
                patches.append({"url": url, **kwargs})
            if patch_rows is not None:
                return _Resp(patch_rows)
            # Default: echo the conditional PATCH back as PostgREST's
            # return=representation would for a one-row match.
            if orders and isinstance(orders[0], dict):
                updated = dict(orders[0])
                updated.update(kwargs.get("json") or {})
                return _Resp([updated])
            return _Resp([])

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


class TestMarkPaidClaimed:
    def test_400_on_malformed_order_id(self, monkeypatch):
        _set_env(monkeypatch)
        r = client.post("/api/orders/not-a-uuid/mark-paid-claimed", headers=USER_AUTH)
        assert r.status_code == 400

    def test_503_when_supabase_env_missing(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        r = client.post(f"/api/orders/{ORDER_ID}/mark-paid-claimed", headers=USER_AUTH)
        assert r.status_code == 503

    def test_401_without_bearer_token(self, monkeypatch):
        _set_env(monkeypatch)
        _install_client(monkeypatch)
        r = client.post(f"/api/orders/{ORDER_ID}/mark-paid-claimed")
        assert r.status_code == 401

    def test_401_when_gotrue_rejects_token(self, monkeypatch):
        _set_env(monkeypatch)
        _install_client(monkeypatch, auth_status=401, auth_uid=None)
        r = client.post(f"/api/orders/{ORDER_ID}/mark-paid-claimed", headers=USER_AUTH)
        assert r.status_code == 401

    def test_404_when_order_missing(self, monkeypatch):
        _set_env(monkeypatch)
        _install_client(monkeypatch, orders=[])
        r = client.post(f"/api/orders/{ORDER_ID}/mark-paid-claimed", headers=USER_AUTH)
        assert r.status_code == 404

    def test_404_when_order_belongs_to_someone_else(self, monkeypatch):
        _set_env(monkeypatch)
        patches = []
        _install_client(monkeypatch, orders=[_order(device_id=OTHER_UID)], patches=patches)
        r = client.post(f"/api/orders/{ORDER_ID}/mark-paid-claimed", headers=USER_AUTH)
        assert r.status_code == 404
        assert patches == []

    def test_409_when_not_pending(self, monkeypatch):
        _set_env(monkeypatch)
        _install_client(monkeypatch, orders=[_order(status="paid")])
        r = client.post(f"/api/orders/{ORDER_ID}/mark-paid-claimed", headers=USER_AUTH)
        assert r.status_code == 409

    def test_happy_path_patches_awaiting_confirm(self, monkeypatch):
        _set_env(monkeypatch)
        patches = []
        _install_client(monkeypatch, orders=[_order()], patches=patches)
        r = client.post(f"/api/orders/{ORDER_ID}/mark-paid-claimed", headers=USER_AUTH)
        assert r.status_code == 200
        assert r.json() == {"id": ORDER_ID, "status": "awaiting_confirm"}
        assert len(patches) == 1
        assert patches[0]["json"] == {"status": "awaiting_confirm"}
        # The write is scoped to id + owner + still-pending, not just id.
        assert patches[0]["params"] == {
            "id": f"eq.{ORDER_ID}", "device_id": f"eq.{UID}", "status": "eq.pending",
        }
        # return=representation is what lets the route PROVE the conditional
        # PATCH matched a row (PostgREST answers 200 + [] on zero matches).
        assert patches[0]["headers"]["Prefer"] == "return=representation"

    def test_409_when_pending_transition_loses_a_race(self, monkeypatch):
        _set_env(monkeypatch)
        _install_client(monkeypatch, orders=[_order()], patch_rows=[])
        r = client.post(f"/api/orders/{ORDER_ID}/mark-paid-claimed", headers=USER_AUTH)
        assert r.status_code == 409
        assert "concurrently" in r.json()["detail"]


class TestAdminOrders:
    def test_503_when_admin_token_unset(self, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        r = client.get("/api/admin/orders")
        assert r.status_code == 503

    def test_401_on_wrong_admin_token(self, monkeypatch):
        _set_env(monkeypatch)
        r = client.get("/api/admin/orders", headers={"X-Admin-Token": "nope"})
        assert r.status_code == 401

    def test_skipped_when_supabase_env_missing(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        r = client.get("/api/admin/orders", headers=ADMIN_AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"

    def test_400_on_unknown_status_filter(self, monkeypatch):
        _set_env(monkeypatch)
        r = client.get("/api/admin/orders?status=weird", headers=ADMIN_AUTH)
        assert r.status_code == 400

    def test_list_forwards_filters_newest_first(self, monkeypatch):
        _set_env(monkeypatch)
        gets = []
        _install_client(monkeypatch, orders=[_order(status="awaiting_confirm")], gets=gets)
        r = client.get(
            "/api/admin/orders?status=awaiting_confirm&since_hours=25", headers=ADMIN_AUTH,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["count"] == 1
        assert body["orders"][0]["id"] == ORDER_ID
        params = gets[0]["params"]
        assert params["order"] == "created_at.desc"
        assert params["status"] == "eq.awaiting_confirm"
        assert params["created_at"].startswith("gte.")


class TestAdminConfirm:
    def test_401_on_wrong_admin_token(self, monkeypatch):
        _set_env(monkeypatch)
        r = client.post(f"/api/admin/orders/{ORDER_ID}/confirm", headers={"X-Admin-Token": "nope"})
        assert r.status_code == 401

    def test_404_when_order_missing(self, monkeypatch):
        _set_env(monkeypatch)
        _install_client(monkeypatch, orders=[])
        r = client.post(f"/api/admin/orders/{ORDER_ID}/confirm", headers=ADMIN_AUTH)
        assert r.status_code == 404

    def test_409_when_cancelled(self, monkeypatch):
        _set_env(monkeypatch)
        _install_client(monkeypatch, orders=[_order(status="cancelled")])
        r = client.post(f"/api/admin/orders/{ORDER_ID}/confirm", headers=ADMIN_AUTH)
        assert r.status_code == 409

    def test_idempotent_when_already_paid(self, monkeypatch):
        _set_env(monkeypatch)
        patches = []
        _install_client(
            monkeypatch,
            orders=[_order(status="paid", paid_at="2026-07-04T00:00:00+00:00")],
            patches=patches,
        )
        r = client.post(f"/api/admin/orders/{ORDER_ID}/confirm", headers=ADMIN_AUTH)
        assert r.status_code == 200
        assert r.json()["paid_at"] == "2026-07-04T00:00:00+00:00"
        assert patches == []

    def test_happy_path_sets_paid_and_paid_at(self, monkeypatch):
        _set_env(monkeypatch)
        patches = []
        _install_client(monkeypatch, orders=[_order(status="awaiting_confirm")], patches=patches)
        r = client.post(f"/api/admin/orders/{ORDER_ID}/confirm", headers=ADMIN_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "paid"
        assert body["paid_at"]
        assert len(patches) == 1
        assert patches[0]["json"]["status"] == "paid"
        assert patches[0]["json"]["paid_at"]
        # Conditional on the pre-paid states + representation, so a concurrent
        # cancel/refund can never be silently overwritten to paid.
        assert patches[0]["params"] == {
            "id": f"eq.{ORDER_ID}", "status": "in.(pending,awaiting_confirm)",
        }
        assert patches[0]["headers"]["Prefer"] == "return=representation"

    def test_refuses_to_confirm_a_tampered_price(self, monkeypatch):
        # The pending row is client-INSERTed via RLS: a modified browser could
        # write any amount_cents. Confirm must reject anything off-catalog.
        _set_env(monkeypatch)
        patches = []
        _install_client(
            monkeypatch,
            orders=[_order(status="awaiting_confirm", amount_cents=1)],
            patches=patches,
        )
        r = client.post(f"/api/admin/orders/{ORDER_ID}/confirm", headers=ADMIN_AUTH)
        assert r.status_code == 409
        assert patches == []

    def test_refuses_to_confirm_an_unknown_package(self, monkeypatch):
        _set_env(monkeypatch)
        patches = []
        _install_client(
            monkeypatch,
            orders=[_order(status="awaiting_confirm", package="free_everything")],
            patches=patches,
        )
        r = client.post(f"/api/admin/orders/{ORDER_ID}/confirm", headers=ADMIN_AUTH)
        assert r.status_code == 409
        assert patches == []

    def test_409_when_confirm_transition_loses_a_race(self, monkeypatch):
        _set_env(monkeypatch)
        _install_client(
            monkeypatch, orders=[_order(status="awaiting_confirm")], patch_rows=[],
        )
        r = client.post(f"/api/admin/orders/{ORDER_ID}/confirm", headers=ADMIN_AUTH)
        assert r.status_code == 409
        assert "concurrently" in r.json()["detail"]


class TestPaymentsAdapter:
    def test_manual_create_order_shape(self):
        row = payments.create_order(
            "manual", device_id=UID, package="full_package", amount_cents=4900,
        )
        assert row["status"] == "pending"
        assert row["channel"] == "manual"
        assert row["amount_cents"] == 4900

    def test_nonpositive_amount_rejected(self):
        with pytest.raises(ValueError):
            payments.create_order("manual", device_id=UID, package="x", amount_cents=0)

    @pytest.mark.parametrize("channel", ["wechat", "alipay", "stripe"])
    def test_real_channels_unimplemented(self, channel):
        with pytest.raises(NotImplementedError):
            payments.create_order(channel, device_id=UID, package="x", amount_cents=1)
        with pytest.raises(NotImplementedError):
            payments.confirm_order(channel, {})
        with pytest.raises(NotImplementedError):
            payments.handle_webhook(channel, {})

    def test_manual_has_no_webhook(self):
        with pytest.raises(NotImplementedError):
            payments.handle_webhook("manual", {})

    def test_unknown_channel_rejected(self):
        with pytest.raises(ValueError):
            payments.confirm_order("paypal", {})

    def test_catalog_accepts_canonical_orders(self):
        for package, offer in payments.PACKAGE_CATALOG.items():
            assert payments.order_matches_catalog(_order(
                package=package,
                amount_cents=offer["amount_cents"],
                currency=offer["currency"],
            ))

    @pytest.mark.parametrize("overrides", [
        {"amount_cents": 1},
        {"currency": "eur"},
        {"package": "free_everything"},
        {"package": None},
        {"channel": "stripe"},
    ])
    def test_catalog_rejects_tampered_orders(self, overrides):
        assert not payments.order_matches_catalog(_order(**overrides))

    def test_confirm_order_rejects_off_catalog_row(self):
        with pytest.raises(ValueError):
            payments.confirm_order("manual", _order(amount_cents=1))
