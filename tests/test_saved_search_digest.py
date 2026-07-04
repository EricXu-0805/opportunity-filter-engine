"""Contract tests for the saved-search weekly email digest.

Covers GET /api/cron/saved-searches/digest (CRON_SECRET-guarded sender)
and GET /api/email/digest-unsubscribe (HMAC-token opt-out). All Supabase
and Resend traffic is stubbed at the httpx / _send_via_resend boundary —
tests never touch the network. The core invariants pinned here:

  * no email is ever sent without digest_opt_in (the Supabase query
    filters on it; rows the stub returns ARE the opted-in set)
  * one digest per search per 7 days (last_digest_sent_at throttle)
  * RESEND env unset -> status "skipped", zero sends (push.py pattern)
  * unsubscribe signing-secret unset -> sender refuses to run at all
  * unsubscribe token: valid flips the row off; tampered/expired -> 400
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
from backend.routes import saved_searches as ss_mod

client = TestClient(app)

AUTH = {"Authorization": "Bearer cron-ok"}

_OPP_A = {"id": "opp-a", "title": "Vision Lab RA", "organization": "UIUC ECE",
          "deadline": "2026-07-01"}
_OPP_B = {"id": "opp-b", "title": "NLP Internship", "organization": "Acme AI",
          "deadline": ""}


def _digest_row(**overrides):
    row = {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "ML research",
        "digest_email": "user@example.com",
        "new_match_ids": ["opp-a", "opp-b"],
        "last_digest_sent_at": None,
    }
    row.update(overrides)
    return row


def _set_digest_env(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "cron-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("RESEND_API_KEY", "fake")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    monkeypatch.setenv("RESTORE_LINK_SECRET", "digest-secret")


def _install_stubs(monkeypatch, *, rows, sends=None, patches=None,
                   opportunities=None):
    """Stub the digest route's three exits: Supabase httpx traffic,
    the Resend send helper, and the opportunities data file."""

    class _Resp:
        def __init__(self, data=None):
            self._data = data
            self.status_code = 200
            self.text = ""

        def json(self):
            return self._data

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            return _Resp(rows)

        async def patch(self, url, **kwargs):
            if patches is not None:
                patches.append({"url": url, **kwargs})
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    async def _fake_send(**kwargs):
        if sends is not None:
            sends.append(kwargs)

    monkeypatch.setattr(ss_mod, "_send_via_resend", _fake_send)
    monkeypatch.setattr(
        ss_mod, "load_opportunities",
        lambda: opportunities if opportunities is not None else [_OPP_A, _OPP_B],
    )
    # Per-recipient quota is in-memory module state shared across tests.
    from backend.routes import email as email_mod
    email_mod._recipient_sends.clear()


class TestDigestCronAuth:
    def test_503_when_cron_secret_unset(self, monkeypatch):
        monkeypatch.delenv("CRON_SECRET", raising=False)
        r = client.get("/api/cron/saved-searches/digest")
        assert r.status_code == 503

    def test_401_when_wrong_secret(self, monkeypatch):
        monkeypatch.setenv("CRON_SECRET", "cron-ok")
        r = client.get("/api/cron/saved-searches/digest",
                       headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


class TestDigestCronSkips:
    def test_skipped_when_supabase_env_missing(self, monkeypatch):
        monkeypatch.setenv("CRON_SECRET", "cron-ok")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "skipped"
        assert "SUPABASE_URL" in body["missing"]

    def test_skipped_when_resend_unset(self, monkeypatch):
        _set_digest_env(monkeypatch)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "skipped"
        assert body["reason"] == "resend not configured"

    def test_skipped_when_signing_secret_unset(self, monkeypatch):
        # Opt-in mail without a working unsubscribe link must never go out.
        _set_digest_env(monkeypatch)
        monkeypatch.delenv("RESTORE_LINK_SECRET", raising=False)
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row()], sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"
        assert sends == []


class TestDigestCronSend:
    def test_happy_path_sends_one_email_and_stamps_sent_at(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        patches: list = []
        _install_stubs(monkeypatch, rows=[_digest_row()], sends=sends, patches=patches)

        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["sent"] == 1
        assert body["errors"] == []

        assert len(sends) == 1
        send = sends[0]
        assert send["to"] == "user@example.com"
        assert "ML research" in send["subject"]
        assert "Vision Lab RA" in send["html"]
        assert "/opportunities/opp-a" in send["html"]
        assert "digest-unsubscribe" in send["html"]
        assert "digest-unsubscribe" in send["text"]

        assert len(patches) == 1
        assert patches[0]["json"].keys() == {"last_digest_sent_at", "new_match_ids"}
        assert patches[0]["json"]["new_match_ids"] == []
        assert patches[0]["params"]["id"] == f"eq.{_digest_row()['id']}"

    def test_caps_items_at_ten(self, monkeypatch):
        _set_digest_env(monkeypatch)
        opps = [{"id": f"opp-{i}", "title": f"Opp {i}", "organization": "Org",
                 "deadline": ""} for i in range(15)]
        sends: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=[o["id"] for o in opps])],
            sends=sends, opportunities=opps,
        )
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.json()["sent"] == 1
        assert "Opp 9" in sends[0]["html"]
        assert "Opp 10" not in sends[0]["html"]

    def test_throttles_within_seven_days(self, monkeypatch):
        _set_digest_env(monkeypatch)
        recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(last_digest_sent_at=recent)],
                       sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        body = r.json()
        assert body["sent"] == 0
        assert body["throttled"] == 1
        assert sends == []

    def test_sends_again_after_seven_days(self, monkeypatch):
        _set_digest_env(monkeypatch)
        stale = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(last_digest_sent_at=stale)],
                       sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.json()["sent"] == 1
        assert len(sends) == 1

    def test_skips_rows_without_new_matches(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(new_match_ids=[])], sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        body = r.json()
        assert body["sent"] == 0
        assert body["skipped"] == 1
        assert sends == []

    def test_skips_invalid_stored_email(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(digest_email="not-an-email")],
                       sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        body = r.json()
        assert body["sent"] == 0
        assert body["skipped"] == 1
        assert sends == []

    def test_escapes_html_in_titles(self, monkeypatch):
        _set_digest_env(monkeypatch)
        evil = {"id": "opp-x", "title": "<script>alert(1)</script>",
                "organization": "Org", "deadline": ""}
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(new_match_ids=["opp-x"])],
                       sends=sends, opportunities=[evil])
        client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert "<script>alert(1)</script>" not in sends[0]["html"]
        assert "&lt;script&gt;" in sends[0]["html"]


class TestRefreshAccumulatesNewMatches:
    """new_match_ids must survive nightly refreshes until a digest is sent —
    the digest is throttled to one per 7 days, so overwriting the column with
    each night's diff would silently drop ~6/7 of a week's matches."""

    def _refresh_row(self, **overrides):
        row = {
            "id": "11111111-2222-3333-4444-555555555555",
            "filters_json": {},
            "query": "",
            "last_result_ids": [],
            "new_match_ids": [],
        }
        row.update(overrides)
        return row

    def test_unions_fresh_diff_with_pending_ids(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        # opp-a was already in last night's result set; opp-old accumulated
        # from an earlier refresh and has since left the corpus — it must
        # survive until the digest clears it, not vanish overnight.
        row = self._refresh_row(last_result_ids=["opp-a"],
                                new_match_ids=["opp-old", "opp-b"])
        _install_stubs(monkeypatch, rows=[row], patches=patches)

        r = client.get("/api/cron/saved-searches/refresh", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        body = patches[0]["json"]
        assert body["last_result_ids"] == ["opp-a", "opp-b"]
        # opp-b is both pending and freshly diffed — deduped, order kept
        assert body["new_match_ids"] == ["opp-old", "opp-b"]

    def test_cap_keeps_newest_ids(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        pending = [f"pending-{i}" for i in range(ss_mod.NEW_MATCH_IDS_CAP - 1)]
        row = self._refresh_row(new_match_ids=pending)
        _install_stubs(monkeypatch, rows=[row], patches=patches)

        client.get("/api/cron/saved-searches/refresh", headers=AUTH)

        got = patches[0]["json"]["new_match_ids"]
        assert len(got) == ss_mod.NEW_MATCH_IDS_CAP
        assert "pending-0" not in got  # oldest aged out
        assert got[-2:] == ["opp-a", "opp-b"]  # fresh matches kept


SID = "11111111-2222-3333-4444-555555555555"


def _unsub_url(sid: str = SID, ts: int | None = None, sig: str | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    sig = ss_mod._sign_digest_unsub(sid, ts) if sig is None else sig
    return f"/api/email/digest-unsubscribe?sid={sid}&t={ts}&s={sig}"


class TestDigestUnsubscribe:
    def _install_patch_stub(self, monkeypatch, patches, status_code=204):
        class _Resp:
            def __init__(self):
                self.status_code = status_code
                self.text = ""

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def patch(self, url, **kwargs):
                patches.append({"url": url, **kwargs})
                return _Resp()

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", _Client)

    def test_valid_token_flips_opt_in_off(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        self._install_patch_stub(monkeypatch, patches)

        r = client.get(_unsub_url())
        assert r.status_code == 200
        assert "unsubscribed" in r.text.lower()

        assert len(patches) == 1
        body = patches[0]["json"]
        assert body["digest_opt_in"] is False
        assert body["digest_unsubscribed_at"]
        assert patches[0]["params"]["id"] == f"eq.{SID}"

    def test_tampered_sid_rejected(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        self._install_patch_stub(monkeypatch, patches)
        ts = int(time.time())
        sig = ss_mod._sign_digest_unsub(SID, ts)
        other_sid = "99999999-2222-3333-4444-555555555555"
        r = client.get(_unsub_url(sid=other_sid, ts=ts, sig=sig))
        assert r.status_code == 400
        assert patches == []

    def test_garbage_signature_rejected(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        self._install_patch_stub(monkeypatch, patches)
        r = client.get(_unsub_url(sig="00" * 16))
        assert r.status_code == 400
        assert patches == []

    def test_expired_token_rejected(self, monkeypatch):
        _set_digest_env(monkeypatch)
        old = int(time.time()) - (ss_mod.DIGEST_UNSUB_TTL_DAYS * 86400 + 60)
        r = client.get(_unsub_url(ts=old))
        assert r.status_code == 400

    def test_non_uuid_sid_rejected(self, monkeypatch):
        _set_digest_env(monkeypatch)
        r = client.get("/api/email/digest-unsubscribe?sid=..%2Fetc&t=1&s=ab")
        assert r.status_code == 400

    def test_503_when_secret_unset(self, monkeypatch):
        monkeypatch.delenv("RESTORE_LINK_SECRET", raising=False)
        r = client.get(_unsub_url(sig="ab" * 16))
        assert r.status_code == 503

    def test_bare_payload_signature_rejected(self, monkeypatch):
        # The "digest-unsub|" context prefix is what scopes the token to this
        # action: a signature over the bare "id|ts" (no prefix) — the shape any
        # other feature signing under RESTORE_LINK_SECRET would produce — must
        # be rejected, so tokens can't be replayed across contexts.
        import hashlib
        import hmac
        _set_digest_env(monkeypatch)
        ts = int(time.time())
        secret = ss_mod._restore_signing_secret().encode()
        bare_sig = hmac.new(secret, f"{SID}|{ts}".encode(), hashlib.sha256).digest()[:16].hex()
        digest_sig = ss_mod._sign_digest_unsub(SID, ts)
        assert bare_sig != digest_sig
        r = client.get(_unsub_url(ts=ts, sig=bare_sig))
        assert r.status_code == 400


class TestDigestRenderer:
    def test_subject_singular_plural(self):
        s1, _, _ = ss_mod._render_digest_email("X", [_OPP_A], "https://u")
        s2, _, _ = ss_mod._render_digest_email("X", [_OPP_A, _OPP_B], "https://u")
        assert s1.startswith("1 new match ")
        assert s2.startswith("2 new matches ")

    def test_unsubscribe_link_present_in_both_bodies(self):
        url = "https://api.example.com/api/email/digest-unsubscribe?sid=x&t=1&s=ab"
        _, html, text = ss_mod._render_digest_email("X", [_OPP_A], url)
        # html attribute-escapes the query-string ampersands; text keeps it raw
        assert url.replace("&", "&amp;") in html
        assert url in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
