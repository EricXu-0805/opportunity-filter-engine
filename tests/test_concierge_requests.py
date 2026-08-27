"""The operator's read path for opportunity-bound concierge requests.

A concierge request is fulfilled by hand, so the queue is the feature: a row
the operator cannot see is indistinguishable from a button that did nothing.
These tests cover the three ways that can silently fail — the route being
readable without a token, the corpus join dropping a request whose target
moved, and an unconfigured backend answering 500 instead of saying so.
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
from backend.routes import admin as admin_module

client = TestClient(app)

TARGETED = {
    "id": "req-1",
    "device_id": "dev-1",
    "email": "student@illinois.edu",
    "opportunity_id": "faculty-ece-known",
    "created_at": "2026-08-27T10:00:00+00:00",
}
ORPHANED = {
    "id": "req-2",
    "device_id": "dev-2",
    "email": None,
    "opportunity_id": "faculty-ece-vanished",
    "created_at": "2026-08-26T10:00:00+00:00",
}

CORPUS = {
    "faculty-ece-known": {
        "title": "Naresh Shanbhag",
        "pi_name": "Naresh Shanbhag",
        "organization": "University of Illinois Urbana-Champaign",
        "department": "Electrical and Computer Engineering",
        "source_url": "https://ece.illinois.edu/directory/shanbhag",
    },
}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


@pytest.fixture
def supabase_rows(monkeypatch):
    """Serve `rows` from a fake PostgREST and record what was asked for."""
    calls: list[dict] = []

    def _install(rows):
        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, params=None, headers=None, **kwargs):
                calls.append({"url": url, "params": params or {}})
                return _Resp(rows)

        monkeypatch.setattr(admin_module.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(
            admin_module, "load_opportunities_by_id", lambda: CORPUS,
        )
        return calls

    return _install


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")


HEADERS = {"X-Admin-Token": "admin-ok"}


def test_the_queue_is_never_readable_without_the_admin_token(monkeypatch):
    """It carries student email addresses. There is no anonymous read of it."""
    monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")
    assert client.get("/api/admin/concierge-requests").status_code == 401
    assert client.get(
        "/api/admin/concierge-requests", headers={"X-Admin-Token": "nope"},
    ).status_code == 401

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert client.get("/api/admin/concierge-requests").status_code == 503


def test_it_asks_only_for_targeted_rows(admin_env, supabase_rows):
    """The untargeted 015-era rows are a different, unactionable thing: they say
    somebody wanted help without saying with what. Mixing them into this queue
    would put work in it that nobody can do."""
    calls = supabase_rows([TARGETED])

    response = client.get("/api/admin/concierge-requests", headers=HEADERS)

    assert response.status_code == 200
    assert calls[0]["params"]["opportunity_id"] == "not.is.null"
    assert calls[0]["params"]["order"] == "created_at.desc"


def test_a_request_says_what_the_work_is(admin_env, supabase_rows):
    supabase_rows([TARGETED])

    body = client.get("/api/admin/concierge-requests", headers=HEADERS).json()

    assert body["status"] == "ok"
    assert body["total"] == 1
    request = body["requests"][0]
    assert request["email"] == "student@illinois.edu"
    assert request["target"]["pi_name"] == "Naresh Shanbhag"
    assert request["target"]["department"] == "Electrical and Computer Engineering"
    assert request["target"]["url"] == "https://ece.illinois.edu/directory/shanbhag"


def test_a_request_survives_its_target_leaving_the_corpus(admin_env, supabase_rows):
    """Faculty pages move and records are re-keyed on every refresh. The student
    still asked for something real, so the row stays with an explicit null
    target — dropping it would hide a debt instead of showing it."""
    supabase_rows([TARGETED, ORPHANED])

    body = client.get("/api/admin/concierge-requests", headers=HEADERS).json()

    assert body["total"] == 2
    orphan = next(r for r in body["requests"] if r["id"] == "req-2")
    assert orphan["opportunity_id"] == "faculty-ece-vanished"
    assert orphan["target"] is None


def test_an_unconfigured_backend_says_so_instead_of_failing(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    body = client.get("/api/admin/concierge-requests", headers=HEADERS).json()

    assert body["status"] == "unconfigured"
    assert body["requests"] == []
    assert "SUPABASE_URL" in body["missing"]
