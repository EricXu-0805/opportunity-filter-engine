"""W10b contact tightening: verified-only send targets + auth-gated reveal.

Pins the two-bar contract in backend.lib.contact_visibility and its wiring:

  * provenance bar — constructed/synthesized ``metadata.email_source`` is
    NEVER offered as a send target; harvested stamps and unstamped legacy
    scrapes pass
  * session bar — the detail + cold-email routes reveal the address only to a
    signed-in (non-anonymous) Supabase account, resolved server-side from the
    opportunity id (the request carries no address)
  * degrade-not-error — a stale/invalid token yields the SAME 200 anonymous
    shape (hidden + ``sign_in_required``), never a 401

GoTrue traffic is stubbed at the httpx.AsyncClient boundary (same technique
as tests/test_orders_routes.py); no test touches the network.
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.lib.contact_visibility import contact_email_status, verified_send_target
from backend.lib.supabase_auth import authenticated_uid
from backend.main import app

client = TestClient(app)

UID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
AUTH = {"Authorization": "Bearer user-jwt"}


def _opp(opp_id: str, email, email_source: str | None = None) -> dict:
    metadata = {"is_active": True}
    if email_source is not None:
        metadata["email_source"] = email_source
    return {
        "id": opp_id,
        "title": "Undergraduate Research Assistant — ML Lab",
        "organization": "Test University",
        "department": "Computer Science",
        "opportunity_type": "research",
        "source": "uiuc_faculty",
        "source_type": "faculty",
        "pi_name": "Jane Doe",
        "lab_or_program": "ML Lab",
        "contact_email": email,
        "url": "https://cs.example.edu/lab",
        "paid": "unknown",
        "keywords": ["machine learning"],
        "eligibility": {"majors": ["CS"], "international_friendly": "yes"},
        "application": {"contact_method": "email"},
        "description_clean": "Research on machine learning.",
        "metadata": metadata,
    }


CORPUS = {
    "harvested": _opp("harvested", "jdoe@example.edu", "profile_page"),
    "wayback": _opp("wayback", "jdoe@example.edu", "wayback"),
    "legacy": _opp("legacy", "jdoe@example.edu"),
    "constructed": _opp("constructed", "jdoe@stanford.edu", "constructed_sunetid"),
    "constructed-netid": _opp("constructed-netid", "jdoe@illinois.edu", "constructed_netid"),
    "no-email": _opp("no-email", None),
}


@pytest.fixture
def fake_corpus(monkeypatch):
    monkeypatch.setattr(
        "backend.routes.opportunities.load_opportunities_by_id", lambda: CORPUS,
    )
    monkeypatch.setattr(
        "backend.routes.cold_email.load_opportunities_by_id", lambda: CORPUS,
    )


@pytest.fixture
def authed(monkeypatch):
    async def _uid(authorization):
        return UID if authorization == "Bearer user-jwt" else None
    monkeypatch.setattr("backend.routes.opportunities.authenticated_uid", _uid)
    monkeypatch.setattr("backend.routes.cold_email.authenticated_uid", _uid)


@pytest.fixture
def sample_profile_req():
    return {
        "name": "Test Student",
        "school": "UIUC",
        "year": "sophomore",
        "major": "CS",
        "international_student": True,
        "seeking_type": ["research"],
        "hard_skills": [{"name": "Python", "level": "experienced"}],
        "coursework": ["CS 124"],
        "experience_level": "beginner",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": "machine learning",
    }


class TestVerifiedSendTarget:
    def test_harvested_stamps_pass(self):
        for source in ("profile_page", "wayback", "digitalmeasures_profile"):
            assert verified_send_target(_opp("x", "a@b.edu", source)) == "a@b.edu"

    def test_legacy_unstamped_passes(self):
        assert verified_send_target(_opp("x", "a@b.edu")) == "a@b.edu"

    def test_constructed_never_offered(self):
        for source in ("constructed_sunetid", "constructed_netid", "constructed"):
            assert verified_send_target(_opp("x", "a@b.edu", source)) == ""

    def test_missing_or_null_email(self):
        assert verified_send_target(_opp("x", None)) == ""
        assert verified_send_target(_opp("x", "")) == ""
        assert verified_send_target(_opp("x", "   ")) == ""

    def test_status_matrix(self):
        assert contact_email_status(_opp("x", "a@b.edu"), authenticated=True) == (
            "revealed", "a@b.edu",
        )
        assert contact_email_status(_opp("x", "a@b.edu"), authenticated=False) == (
            "sign_in_required", "",
        )
        assert contact_email_status(
            _opp("x", "a@b.edu", "constructed_netid"), authenticated=True,
        ) == ("unavailable", "")
        assert contact_email_status(_opp("x", None), authenticated=True) == (
            "unavailable", "",
        )


class _Resp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _install_gotrue(monkeypatch, *, status=200, body=None, raise_error=False):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            if raise_error:
                raise httpx.ConnectError("boom")
            assert "/auth/v1/user" in url
            return _Resp(status, body or {})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def _set_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")


class TestAuthenticatedUid:
    async def _run(self, authorization):
        return await authenticated_uid(authorization)

    def test_no_or_malformed_header(self, monkeypatch):
        _set_env(monkeypatch)
        import asyncio
        assert asyncio.run(self._run(None)) is None
        assert asyncio.run(self._run("Token abc")) is None
        assert asyncio.run(self._run("Bearer ")) is None

    def test_env_unconfigured(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        import asyncio
        assert asyncio.run(self._run("Bearer user-jwt")) is None

    def test_gotrue_rejects(self, monkeypatch):
        _set_env(monkeypatch)
        _install_gotrue(monkeypatch, status=401)
        import asyncio
        assert asyncio.run(self._run("Bearer expired")) is None

    def test_gotrue_unreachable(self, monkeypatch):
        _set_env(monkeypatch)
        _install_gotrue(monkeypatch, raise_error=True)
        import asyncio
        assert asyncio.run(self._run("Bearer user-jwt")) is None

    def test_anonymous_session_is_not_signed_in(self, monkeypatch):
        # Guests hold REAL tokens (signInAnonymously) — is_anonymous is the
        # separator, not token validity.
        _set_env(monkeypatch)
        _install_gotrue(monkeypatch, body={"id": UID, "is_anonymous": True})
        import asyncio
        assert asyncio.run(self._run("Bearer anon-jwt")) is None

    def test_signed_in_account_resolves(self, monkeypatch):
        _set_env(monkeypatch)
        _install_gotrue(monkeypatch, body={"id": UID, "is_anonymous": False})
        import asyncio
        assert asyncio.run(self._run("Bearer user-jwt")) == UID


class TestDetailRevealGate:
    def test_anonymous_hidden_with_flag(self, fake_corpus, authed):
        body = client.get("/api/opportunities/harvested").json()
        assert "contact_email" not in body
        assert body["contact_email_status"] == "sign_in_required"

    def test_authed_revealed(self, fake_corpus, authed):
        body = client.get("/api/opportunities/harvested", headers=AUTH).json()
        assert body["contact_email"] == "jdoe@example.edu"
        assert body["contact_email_status"] == "revealed"

    def test_authed_legacy_unstamped_revealed(self, fake_corpus, authed):
        body = client.get("/api/opportunities/legacy", headers=AUTH).json()
        assert body["contact_email"] == "jdoe@example.edu"
        assert body["contact_email_status"] == "revealed"

    def test_constructed_unavailable_even_authed(self, fake_corpus, authed):
        for oid in ("constructed", "constructed-netid"):
            body = client.get(f"/api/opportunities/{oid}", headers=AUTH).json()
            assert "contact_email" not in body
            assert body["contact_email_status"] == "unavailable"

    def test_no_email_unavailable(self, fake_corpus, authed):
        body = client.get("/api/opportunities/no-email", headers=AUTH).json()
        assert "contact_email" not in body
        assert body["contact_email_status"] == "unavailable"

    def test_stale_token_degrades_to_anon_shape(self, fake_corpus, monkeypatch):
        # Real helper + GoTrue saying 401: the route must serve the SAME shape
        # as anonymous with HTTP 200 — never propagate a 401 to the page.
        _set_env(monkeypatch)
        _install_gotrue(monkeypatch, status=401)
        resp = client.get(
            "/api/opportunities/harvested",
            headers={"Authorization": "Bearer expired"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "contact_email" not in body
        assert body["contact_email_status"] == "sign_in_required"
        anon = client.get("/api/opportunities/harvested").json()
        assert body["contact_email_status"] == anon["contact_email_status"]

    def test_pi_email_stays_redacted(self, fake_corpus, authed):
        body = client.get("/api/opportunities/harvested", headers=AUTH).json()
        assert "pi_email" not in body


class TestColdEmailSendTargetGate:
    def _post(self, opp_id, sample_profile_req, headers=None, extra=None):
        payload = {
            "profile": sample_profile_req,
            "opportunity_id": opp_id,
            "engine": "template",
        }
        if extra:
            payload.update(extra)
        resp = client.post("/api/cold-email", json=payload, headers=headers or {})
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_anonymous_gets_draft_without_target(self, fake_corpus, authed, sample_profile_req):
        body = self._post("harvested", sample_profile_req)
        assert body["subject"] and body["body"]  # the draft is the value
        assert body["recipient_email"] == ""
        assert body["recipient_status"] == "sign_in_required"
        assert "jdoe@example.edu" not in body["mailto_link"]

    def test_authed_gets_verified_target(self, fake_corpus, authed, sample_profile_req):
        body = self._post("harvested", sample_profile_req, headers=AUTH)
        assert body["recipient_email"] == "jdoe@example.edu"
        assert body["recipient_status"] == "revealed"
        assert "jdoe%40example.edu" in body["mailto_link"]

    def test_constructed_never_a_target(self, fake_corpus, authed, sample_profile_req):
        body = self._post("constructed", sample_profile_req, headers=AUTH)
        assert body["subject"] and body["body"]
        assert body["recipient_email"] == ""
        assert body["recipient_status"] == "unavailable"
        assert "stanford.edu" not in body["mailto_link"]

    def test_client_supplied_address_is_ignored(self, fake_corpus, authed, sample_profile_req):
        # The schema has no recipient field; a smuggled one must not steer the
        # send target — it is always resolved server-side from the record.
        body = self._post(
            "constructed", sample_profile_req, headers=AUTH,
            extra={"recipient_email": "attacker@evil.com", "to": "attacker@evil.com"},
        )
        assert body["recipient_email"] == ""
        assert "attacker" not in body["mailto_link"]

    def test_stale_token_degrades_not_401(self, fake_corpus, monkeypatch, sample_profile_req):
        _set_env(monkeypatch)
        _install_gotrue(monkeypatch, status=401)
        resp = client.post(
            "/api/cold-email",
            json={
                "profile": sample_profile_req,
                "opportunity_id": "harvested",
                "engine": "template",
            },
            headers={"Authorization": "Bearer expired"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["recipient_email"] == ""
        assert body["recipient_status"] == "sign_in_required"


class TestVariantsSendTargetGate:
    def test_anonymous_hidden(self, fake_corpus, authed, sample_profile_req):
        resp = client.post(
            "/api/cold-email/variants",
            json={"profile": sample_profile_req, "opportunity_id": "harvested"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["recipient_status"] == "sign_in_required"
        for v in body["variants"]:
            assert v["recipient_email"] == ""
            assert "jdoe" not in v["mailto_link"]

    def test_authed_revealed(self, fake_corpus, authed, sample_profile_req):
        resp = client.post(
            "/api/cold-email/variants",
            json={"profile": sample_profile_req, "opportunity_id": "harvested"},
            headers=AUTH,
        )
        body = resp.json()
        assert body["recipient_status"] == "revealed"
        for v in body["variants"]:
            assert v["recipient_email"] == "jdoe@example.edu"

    def test_constructed_unavailable(self, fake_corpus, authed, sample_profile_req):
        resp = client.post(
            "/api/cold-email/variants",
            json={"profile": sample_profile_req, "opportunity_id": "constructed"},
            headers=AUTH,
        )
        body = resp.json()
        assert body["recipient_status"] == "unavailable"
        for v in body["variants"]:
            assert v["recipient_email"] == ""
