"""Contact trust: identity-bound send targets + auth-gated reveal.

Pins the two-bar contract in backend.lib.contact_visibility and its wiring:

  * evidence bar — only a fresh, identity-bound collector observation with a
    matching address and safe source URL is eligible; legacy, merely harvested,
    inferred, stale, and mismatched rows all fail closed
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
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.lib.contact_visibility import (
    CONTACT_VERIFICATION_TTL_DAYS,
    _has_identity_bound_contact_evidence,
    contact_email_status,
    verified_send_target,
)
from backend.lib.supabase_auth import authenticated_uid
from backend.main import app

client = TestClient(app)

UID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
AUTH = {"Authorization": "Bearer user-jwt"}


def _opp(
    opp_id: str,
    email,
    email_source: str | None = None,
    *,
    verified: bool = False,
    metadata_overrides: dict | None = None,
) -> dict:
    metadata = {"is_active": True}
    if email_source is not None:
        metadata["email_source"] = email_source
    if verified:
        metadata.update({
            "identity_bound": True,
            "email_source": email_source or "bound_profile_container",
            "contact_verified_email": email,
            "contact_source_url": "https://cs.example.edu/people/jane-doe",
            "contact_verified_at": datetime.now(UTC).isoformat(),
        })
    if metadata_overrides:
        metadata.update(metadata_overrides)
    return {
        "id": opp_id,
        "title": "Undergraduate Research Assistant — ML Lab",
        "organization": "Test University",
        "department": "Computer Science",
        "opportunity_type": "research",
        "source": "uiuc_faculty",
        "source_type": "faculty_research",
        "pi_name": "Jane Doe",
        "lab_or_program": "ML Lab",
        "contact_email": email,
        # Profile-bound evidence is valid only for the profile URL currently
        # carried by the record. Directory-bound sources do not use this
        # equality, but keeping one honest profile URL makes the shared fixture
        # suitable for both source families.
        "url": "https://cs.example.edu/people/jane-doe",
        "source_url": "https://cs.example.edu/people/jane-doe",
        "paid": "unknown",
        "keywords": ["machine learning"],
        "eligibility": {"majors": ["CS"], "international_friendly": "yes"},
        "application": {"contact_method": "email"},
        "description_clean": "Research on machine learning.",
        "metadata": metadata,
    }


CORPUS = {
    "verified": _opp(
        "verified",
        "jdoe@example.edu",
        "bound_profile_container",
        verified=True,
    ),
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
    def test_reviewed_identity_bound_sources_pass_with_complete_evidence(self):
        for source in (
            "bound_directory_card",
            "bound_directory_name_join",
            "bound_profile_container",
            "bound_profile_custom_obfuscated",
            "bound_profile_obfuscated",
        ):
            assert verified_send_target(
                _opp("x", "a@b.edu", source, verified=True)
            ) == "a@b.edu"

    def test_synthesized_sources_fail_closed_but_unstamped_legacy_passes(self):
        # W7a reconciliation (the W12 merge): an email_source alone is
        # pre-contract provenance INFO, not a binding claim — the corpus'
        # 114k emailed rows carry zero binding stamps, and failing them all
        # would black out recipient reveal product-wide. Harvested-looking
        # legacy rows therefore PASS; a constructed/synthesized source is
        # still never a send target; and the moment any BINDING field
        # appears, the full three-part contract applies (below).
        for source in (None, "profile_page", "wayback", "digitalmeasures_profile"):
            assert verified_send_target(_opp("x", "a@b.edu", source)) == "a@b.edu"
        for source in ("constructed_sunetid", "constructed_netid", "constructed"):
            assert verified_send_target(_opp("x", "a@b.edu", source)) == ""
        # An unknown future collector name is not synthesized and not bound —
        # it rides the legacy rule until it stamps binding fields.
        assert verified_send_target(_opp("x", "a@b.edu", "unknown_future_collector")) == "a@b.edu"

    def test_partial_binding_stamp_fails_closed(self):
        # Any binding field without the complete contract = fail closed; the
        # legacy pass-through never applies once a collector has spoken.
        opp = _opp("x", "a@b.edu", "profile_page",
                   metadata_overrides={"identity_bound": False})
        assert verified_send_target(opp) == ""
        opp2 = _opp("x", "a@b.edu", "profile_page",
                    metadata_overrides={"contact_verified_at": "2026-08-01T00:00:00+00:00"})
        assert verified_send_target(opp2) == ""

    def test_profile_bound_source_must_match_current_record_profile_url(self):
        opp = _opp(
            "x",
            "a@b.edu",
            "bound_profile_container",
            verified=True,
        )
        opp["url"] = "https://cs.example.edu/people/grace-hopper"
        assert verified_send_target(opp) == ""

        # A stale duplicate projection cannot rescue a changed primary URL.
        opp["source_url"] = "https://cs.example.edu/people/jane-doe"
        opp["application"]["application_url"] = (
            "https://cs.example.edu/people/jane-doe"
        )
        assert verified_send_target(opp) == ""

        # A trailing slash is the only redirect/canonicalization difference
        # accepted by the first reviewed profile producer.
        opp["url"] = "https://cs.example.edu/people/jane-doe/"
        assert verified_send_target(opp) == "a@b.edu"
        opp["url"] = "https://cs.example.edu/people/jane-doe////"
        assert verified_send_target(opp) == ""

        # An application URL may only corroborate the authoritative profile
        # fields; it cannot resurrect proof after both of them disappear.
        opp["url"] = None
        opp["source_url"] = None
        opp["application"]["application_url"] = (
            "https://cs.example.edu/people/jane-doe"
        )
        assert verified_send_target(opp) == ""

    def test_directory_bound_source_does_not_use_profile_url_equality(self):
        opp = _opp(
            "x",
            "a@b.edu",
            "bound_directory_card",
            verified=True,
            metadata_overrides={
                "contact_source_url": (
                    "https://cs.example.edu/faculty-directory"
                ),
            },
        )
        assert opp["url"] == "https://cs.example.edu/people/jane-doe"
        assert verified_send_target(opp) == "a@b.edu"

    def test_missing_or_null_email(self):
        assert verified_send_target(_opp("x", None)) == ""
        assert verified_send_target(_opp("x", "")) == ""
        assert verified_send_target(_opp("x", "   ")) == ""

    @pytest.mark.parametrize(
        ("override", "expected"),
        [
            ({"identity_bound": False}, ""),
            ({"identity_bound": None}, ""),
            ({"contact_verified_email": "other@b.edu"}, ""),
            ({"contact_verified_email": None}, ""),
            ({"contact_source_url": None}, ""),
            ({"contact_source_url": "mailto:a@b.edu"}, ""),
            ({"contact_source_url": "https://a@b.edu/profile"}, ""),
            ({"contact_verified_at": None}, ""),
            ({"contact_verified_at": "not-a-date"}, ""),
            ({"contact_verified_at": "2026-07-31T12:00:00"}, ""),
        ],
    )
    def test_every_identity_evidence_field_is_required(self, override, expected):
        opp = _opp(
            "x",
            "a@b.edu",
            "bound_profile_container",
            verified=True,
            metadata_overrides=override,
        )
        assert verified_send_target(opp) == expected

    @pytest.mark.parametrize(
        "email",
        [
            "missing-at.example.edu",
            "a@localhost",
            "a b@example.edu",
            "@example.edu",
            ".a@example.edu",
            "a.@example.edu",
            "a..b@example.edu",
            f"{'a' * 65}@example.edu",
            f"{'a' * 245}@example.edu",
        ],
    )
    def test_invalid_recipient_syntax_fails_closed(self, email):
        assert verified_send_target(
            _opp(
                "x",
                email,
                "bound_profile_container",
                verified=True,
            )
        ) == ""

    def test_verification_age_and_clock_skew_boundaries(self):
        now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
        email = "a@b.edu"

        def has_evidence(verified_at: datetime) -> bool:
            opp = _opp(
                "x",
                email,
                "bound_profile_container",
                verified=True,
                metadata_overrides={"contact_verified_at": verified_at.isoformat()},
            )
            return _has_identity_bound_contact_evidence(opp, email, now=now)

        ttl = timedelta(days=CONTACT_VERIFICATION_TTL_DAYS)
        assert has_evidence(now - ttl + timedelta(microseconds=1))
        assert has_evidence(now - ttl)
        assert not has_evidence(now - ttl - timedelta(microseconds=1))
        assert has_evidence(now + timedelta(minutes=5))
        assert not has_evidence(now + timedelta(minutes=5, microseconds=1))

    def test_status_matrix(self):
        verified = _opp(
            "x",
            "a@b.edu",
            "bound_profile_container",
            verified=True,
        )
        assert contact_email_status(verified, authenticated=True) == (
            "revealed", "a@b.edu",
        )
        assert contact_email_status(verified, authenticated=False) == (
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
        response = client.get("/api/opportunities/verified")
        body = response.json()
        assert "contact_email" not in body
        assert body["contact_email_status"] == "sign_in_required"
        assert response.headers["Vary"] == "Authorization"
        assert "no-store" not in response.headers.get("Cache-Control", "")

    def test_authed_revealed(self, fake_corpus, authed):
        response = client.get("/api/opportunities/verified", headers=AUTH)
        body = response.json()
        assert body["contact_email"] == "jdoe@example.edu"
        assert body["contact_email_status"] == "revealed"
        assert response.headers["Vary"] == "Authorization"
        assert response.headers["Cache-Control"] == (
            "private, no-store, max-age=0"
        )
        assert response.headers["Pragma"] == "no-cache"

    def test_legacy_and_harvested_rows_reveal_to_a_signed_in_caller(self, fake_corpus, authed):
        # W7a reconciliation: pre-stamping rows (no binding fields at all)
        # are the entire corpus today — they reveal under the ordinary W10b
        # bar (signed-in session) instead of being blacked out wholesale.
        # Synthesized sources stay unavailable (the test below).
        for oid in ("legacy", "harvested", "wayback"):
            body = client.get(f"/api/opportunities/{oid}", headers=AUTH).json()
            assert body["contact_email_status"] == "revealed"
            assert body["contact_email"]

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
            "/api/opportunities/verified",
            headers={"Authorization": "Bearer expired"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "contact_email" not in body
        assert body["contact_email_status"] == "sign_in_required"
        anon = client.get("/api/opportunities/verified").json()
        assert body["contact_email_status"] == anon["contact_email_status"]

    def test_pi_email_stays_redacted(self, fake_corpus, authed):
        response = client.get("/api/opportunities/verified", headers=AUTH)
        assert response.status_code == 200, response.text
        body = response.json()
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
        body = self._post("verified", sample_profile_req)
        assert body["subject"] and body["body"]  # the draft is the value
        assert body["recipient_email"] == ""
        assert body["recipient_status"] == "sign_in_required"
        assert "jdoe@example.edu" not in body["mailto_link"]

    def test_authed_gets_verified_target(self, fake_corpus, authed, sample_profile_req):
        body = self._post("verified", sample_profile_req, headers=AUTH)
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
                "opportunity_id": "verified",
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
            json={"profile": sample_profile_req, "opportunity_id": "verified"},
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
            json={"profile": sample_profile_req, "opportunity_id": "verified"},
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


class TestTheCorpusStaysReachable:
    """Cold email is the product's core step; a corpus it cannot address is a
    dead feature, and nothing here was watching that number.

    On 2026-08-17 a single refresh stamped ``identity_bound: False`` across the
    corpus — the tombstone that means "reviewed and NOT bound" — on records
    nobody had reviewed. uiuc went from 0 such rows on 08-14 to 3,125 on 08-17;
    corpus-wide, reachable addresses fell from 116,430 to 10,949 without one
    test going red. Every unit bar below still passed, because each one asks
    about a record it constructs itself.

    Deliberately a FLOOR with headroom rather than a pinned count: an exact
    number turns every data-refresh PR into a test edit (this repo has been
    bitten by that), while a floor at 80% is stable across refreshes and would
    still have caught a collapse to 9.4%.
    """

    MIN_REACHABLE_SHARE = 0.80

    def test_no_record_holds_an_address_and_a_tombstone(self):
        """The exact invariant, because the ratio below is too coarse to see a
        partial regression.

        A real rejection goes through ``clear_contact_claim``, which nulls the
        address in the same breath as it stamps the tombstone. So an address
        sitting next to ``identity_bound: False`` was never rejected — it was
        stamped by a merge path that reviewed nothing.

        Keyed on the address rather than on "no other evidence":
        ``clear_contact_evidence`` strips every evidence field before stamping,
        so a genuine tombstone and a false one look identical in what remains.
        The address is the only thing that separates them.

        This is what the 80% floor missed. A refresh that had started 24 minutes
        before the fix landed committed 18,297 stale tombstones onto main; the
        corpus read 82.9% reachable, cleared the floor, and shipped. Shard by
        shard, each weekly refresh would have walked it back down.

        If this ever fires on a tombstone that SHOULD keep its address, the
        contract needs a positive marker for "reviewed, rejected, address
        retained" — no path produces that today, and inventing one silently by
        loosening this test would restore exactly the hole it closes.
        """
        from backend.data_loader import load_opportunities

        offenders = [
            o["id"]
            for o in load_opportunities()
            if (o.get("metadata") or {}).get("identity_bound") is False
            and (o.get("contact_email") or "").strip()
        ]
        assert not offenders, (
            f"{len(offenders)} records carry a tombstone AND an address, e.g. "
            f"{offenders[:5]} — a merge path stamped a review that never "
            "happened, and each one is a professor the product can no longer "
            "reach."
        )

    def test_most_harvested_addresses_are_still_send_targets(self):
        from backend.data_loader import load_opportunities

        held = reachable = 0
        for record in load_opportunities():
            email = record.get("contact_email")
            if not isinstance(email, str) or not email.strip():
                continue
            held += 1
            if verified_send_target(record):
                reachable += 1

        assert held > 1000, (
            f"only {held} records hold an address — the corpus fixture is not "
            "the real one, so this guard is not measuring anything"
        )
        share = reachable / held
        assert share >= self.MIN_REACHABLE_SHARE, (
            f"{reachable}/{held} ({share:.1%}) of harvested addresses are "
            f"reachable, below the {self.MIN_REACHABLE_SHARE:.0%} floor. A "
            "gate started refusing addresses in bulk — check for tombstones "
            "written by a merge path that reviewed nothing."
        )
