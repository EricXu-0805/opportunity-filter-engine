"""W16 notification-delivery idempotency and ambiguous-outcome handling.

W14 pinned the acknowledgment ordering (``remind_at`` clears only after the
provider accepts). What it left open was the meaning of a wall-clock timeout:
it was counted as a failure, which fired the email fallback in the SAME run and
re-sent the push the NEXT night. If the push service had already accepted, both
were duplicate notifications for one reminder.

The invariants pinned here:

    ambiguous push   -> no same-run email fallback, incident marked ambiguous
    ambiguous push   -> remind_at retained (at-least-once, by decision)
    every push       -> stable RFC 8030 Topic + bounded TTL, so the retry
                        REPLACES a pending copy instead of stacking on it
    every auto email -> stable Idempotency-Key: identical across a retry of the
                        same logical send, different for a different send
    digest failure   -> ambiguous vs definitive is visible, and durable in the
                        ops_incidents queue
"""

from __future__ import annotations

import asyncio
import re
import socket
from datetime import UTC, date, datetime

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.lib.safe_webpush import (
    PUSH_TOPIC_MAX_LENGTH,
    WEBPUSH_DEFAULT_TTL_SECONDS,
    derive_push_topic,
    send_webpush_safely,
)
from backend.main import app
from backend.routes import email as email_mod
from backend.routes import push as push_mod
from backend.routes import saved_searches as ss_mod

client = TestClient(app)

AUTH = {"Authorization": "Bearer cron-ok"}

# RFC 8030 §5.4: <=32 characters of the URL and filename-safe base64 alphabet.
_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

_DUE = {
    "device_id": "dev-1", "opportunity_id": "opp-42",
    "remind_at": "2026-08-01", "interaction_type": "applied", "notes": "",
}
_SUB = {"device_id": "dev-1", "endpoint": "https://push.example.test/wpush/v2/abc",
        "p256dh": "k", "auth": "a"}


class _Resp:
    def __init__(self, data=None, status_code: int = 200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


def _dns(*addresses: str):
    def resolve(_host: str, port: int, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
            for address in addresses
        ]

    return resolve


# ── reminder cron harness ───────────────────────────────────────────────────


def _set_push_env(monkeypatch, *, resend: bool = True) -> None:
    monkeypatch.setenv("CRON_SECRET", "cron-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:ops@example.com")
    if resend:
        monkeypatch.setenv("RESEND_API_KEY", "fake")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    else:
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)


def _install_reminder_io(
    monkeypatch,
    *,
    due=None,
    subscriptions=None,
    dispatch=None,
    emails=None,
    patches=None,
    rpcs=None,
    account_email: str | None = "user@example.com",
    send_impl=None,
    today: str = "2026-08-01",
) -> None:
    """Stub the reminder cron's Supabase, Resend and dispatcher boundaries."""

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, url, **_kwargs):
            if "/auth/v1/admin/users/" in url:
                if account_email is None:
                    return _Resp({}, status_code=404)
                return _Resp({"email": account_email})
            if "ops_incidents" in url:
                return _Resp([])
            if "push_subscriptions" in url:
                return _Resp([_SUB] if subscriptions is None else subscriptions)
            return _Resp([_DUE] if due is None else due)

        async def post(self, url, json=None, **_kwargs):
            if rpcs is not None:
                rpcs.append({"url": url, "json": json})
            return _Resp(True)

        async def patch(self, url, **kwargs):
            if patches is not None:
                patches.append({"url": url, **kwargs})
            return _Resp({}, status_code=204)

        async def delete(self, url, **_kwargs):
            return _Resp({}, status_code=204)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    async def _dispatch(**kwargs):
        if dispatch is not None:
            dispatch.append(kwargs)
        return kwargs["webpush_func"](
            subscription_info=kwargs["subscription_info"],
            data=kwargs["data"],
            vapid_private_key=kwargs["vapid_private_key"],
            vapid_claims=kwargs["vapid_claims"],
            ttl=kwargs.get("ttl"),
            headers=kwargs.get("headers"),
        )

    monkeypatch.setattr(push_mod, "send_webpush_safely", _dispatch)

    async def _record_send(**kwargs):
        if emails is not None:
            emails.append(kwargs)

    monkeypatch.setattr(push_mod, "_send_via_resend", send_impl or _record_send)

    # Freeze the cron's notion of "today" so the reminder idempotency key is
    # reproducible (and cannot flake across a midnight boundary).
    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return date.fromisoformat(today)

    monkeypatch.setattr(push_mod, "date", _FrozenDate)
    email_mod._recipient_sends.clear()


def _run_reminders():
    return client.get("/api/cron/reminders", headers=AUTH)


async def _timeout_dispatch(**_kwargs):
    from backend.lib.safe_webpush import WebPushDeliveryTimeout

    raise WebPushDeliveryTimeout("deadline exceeded")


def _incident_rpcs(rpcs: list) -> list[dict]:
    return [c["json"] for c in rpcs if c["url"].endswith("/rpc/record_ops_incident")]


# ── 1. an ambiguous push is not compensated by a second channel ─────────────


class TestAmbiguousPushOutcome:
    def test_timeout_does_not_trigger_the_same_run_email_fallback(self, monkeypatch):
        _set_push_env(monkeypatch)  # Resend fully configured and reachable
        emails: list = []
        patches: list = []
        _install_reminder_io(monkeypatch, emails=emails, patches=patches)
        monkeypatch.setattr(push_mod, "send_webpush_safely", _timeout_dispatch)

        body = _run_reminders().json()

        assert body["status"] == "ok"
        assert body["sent"] == 0
        assert body["ambiguous"] == 1
        assert body["failed"] == 1
        # The push MAY have landed; an email now would be the second copy.
        assert emails == []
        assert body["emailed"] == 0

    def test_timeout_retains_remind_at_at_least_once(self, monkeypatch):
        _set_push_env(monkeypatch)
        patches: list = []
        _install_reminder_io(monkeypatch, patches=patches)
        monkeypatch.setattr(push_mod, "send_webpush_safely", _timeout_dispatch)

        _run_reminders()

        # Decision (W16): retain. A repeat is collapsed by the Topic; clearing
        # would risk losing a reminder that genuinely never arrived.
        assert [p for p in patches if "interactions" in p["url"]] == []

    def test_timeout_records_an_incident_marked_ambiguous(self, monkeypatch):
        _set_push_env(monkeypatch)
        rpcs: list = []
        _install_reminder_io(monkeypatch, rpcs=rpcs)
        monkeypatch.setattr(push_mod, "send_webpush_safely", _timeout_dispatch)

        _run_reminders()

        (incident,) = _incident_rpcs(rpcs)
        detail = incident["p_detail"]
        assert detail["outcome"] == "ambiguous"
        assert detail["may_have_been_delivered"] is True
        assert detail["email_fallback_suppressed"] is True
        assert detail["remind_at_retained"] is True
        # migration 031 constrains failure_state; the observation stays
        # 'timed_out' and the OUTCOME's ambiguity lives in the detail.
        assert incident["p_failure_state"] == "timed_out"
        assert detail["error_category"] == "delivery_timeout"

    def test_definitive_provider_rejection_still_falls_back_to_email(self, monkeypatch):
        """The suppression is specific to ambiguity, not to every failure."""
        from pywebpush import WebPushException

        _set_push_env(monkeypatch)
        emails: list = []
        _install_reminder_io(monkeypatch, emails=emails)

        class _Rejected:
            status_code = 400

        async def _rejected_dispatch(**_kwargs):
            raise WebPushException("rejected", response=_Rejected())

        monkeypatch.setattr(push_mod, "send_webpush_safely", _rejected_dispatch)
        body = _run_reminders().json()

        assert body["ambiguous"] == 0
        assert body["emailed"] == 1
        assert len(emails) == 1

    def test_no_subscription_at_all_still_falls_back(self, monkeypatch):
        _set_push_env(monkeypatch)
        emails: list = []
        _install_reminder_io(monkeypatch, subscriptions=[], emails=emails)

        body = _run_reminders().json()
        assert body["emailed"] == 1
        assert body["ambiguous"] == 0


# ── 2. Web Push protocol idempotency (RFC 8030 Topic + TTL) ─────────────────


class TestPushTopicAndTtl:
    def test_topic_is_stable_and_spec_legal(self):
        first = derive_push_topic("reminder-opp-42")
        second = derive_push_topic("reminder-opp-42")

        assert first == second  # a retry must reuse the identity, not mint one
        assert _TOPIC_RE.match(first), first
        assert len(first) <= PUSH_TOPIC_MAX_LENGTH
        assert derive_push_topic("reminder-opp-43") != first

    def test_topic_survives_identities_longer_than_the_spec_budget(self):
        topic = derive_push_topic("reminder-" + "x" * 500)
        assert _TOPIC_RE.match(topic)
        assert len(topic) == PUSH_TOPIC_MAX_LENGTH

    def test_dispatcher_passes_ttl_and_headers_to_pywebpush(self):
        captured: dict = {}

        def fake_webpush(**kwargs):
            captured.update(kwargs)
            return object()

        topic = derive_push_topic("reminder-opp-42")
        asyncio.run(
            send_webpush_safely(
                subscription_info={
                    "endpoint": "https://push.example.test/wpush/v2/abc",
                    "keys": {"p256dh": "key", "auth": "auth"},
                },
                data="{}",
                vapid_private_key="private",
                vapid_claims={"sub": "mailto:ops@example.com"},
                webpush_func=fake_webpush,
                resolver=_dns("93.184.216.34"),
                total_timeout=1.0,
                ttl=WEBPUSH_DEFAULT_TTL_SECONDS,
                headers={"Topic": topic},
            )
        )

        assert captured["ttl"] == WEBPUSH_DEFAULT_TTL_SECONDS
        assert captured["headers"] == {"Topic": topic}
        # The SSRF boundary is untouched by the new kwargs.
        assert captured["requests_session"].trust_env is False
        assert captured["timeout"] == (3.0, 5.0)

    def test_dispatcher_rejects_an_illegal_topic(self):
        async def run():
            await send_webpush_safely(
                subscription_info={"endpoint": "https://push.example.test/wpush/v2/abc"},
                data="{}",
                vapid_private_key="private",
                vapid_claims={"sub": "mailto:ops@example.com"},
                webpush_func=lambda **_kw: None,
                resolver=_dns("93.184.216.34"),
                headers={"Topic": "not/legal+base64" * 4},
            )

        with pytest.raises(ValueError):
            asyncio.run(run())

    def test_installed_pywebpush_accepts_ttl_and_headers(self):
        """Wiring these through is only safe because the real signature takes them."""
        import inspect

        from pywebpush import webpush

        params = inspect.signature(webpush).parameters
        assert "ttl" in params
        assert "headers" in params

    def test_cron_sends_the_same_topic_for_the_same_reminder_across_runs(self, monkeypatch):
        topics = []
        for _ in range(2):
            _set_push_env(monkeypatch, resend=False)
            dispatch: list = []
            _install_reminder_io(monkeypatch, dispatch=dispatch)
            assert _run_reminders().status_code == 200
            (call,) = dispatch
            topics.append(call["headers"]["Topic"])
            assert call["ttl"] == WEBPUSH_DEFAULT_TTL_SECONDS

        assert topics[0] == topics[1] == derive_push_topic("reminder-opp-42")
        assert _TOPIC_RE.match(topics[0])

    def test_cron_topic_differs_per_reminder(self, monkeypatch):
        _set_push_env(monkeypatch, resend=False)
        dispatch: list = []
        other = dict(_DUE, opportunity_id="opp-99")
        _install_reminder_io(monkeypatch, due=[_DUE, other], dispatch=dispatch)

        assert _run_reminders().status_code == 200
        topics = {call["headers"]["Topic"] for call in dispatch}
        assert len(topics) == 2


# ── 3. Resend idempotency keys ─────────────────────────────────────────────


class TestResendIdempotencyKey:
    def test_send_via_resend_sends_the_header_when_given_a_key(self, monkeypatch):
        posts: list = []

        class _Client:
            def __init__(self, *_a, **_k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def post(self, url, json=None, headers=None, **_kwargs):
                posts.append({"url": url, "json": json, "headers": headers})
                return _Resp({}, status_code=200)

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        asyncio.run(
            email_mod._send_via_resend(
                api_key="k", from_addr="a@b.c", to="d@e.f",
                subject="s", html="<p>h</p>", text="t",
                idempotency_key="digest-abc",
            )
        )
        assert posts[0]["headers"]["Idempotency-Key"] == "digest-abc"

        posts.clear()
        asyncio.run(
            email_mod._send_via_resend(
                api_key="k", from_addr="a@b.c", to="d@e.f",
                subject="s", html="<p>h</p>", text="t",
            )
        )
        # A user-initiated send is a deliberate request, not a retry.
        assert "Idempotency-Key" not in posts[0]["headers"]

    def test_key_is_deterministic_in_its_inputs(self):
        build = email_mod.build_idempotency_key
        assert build("reminder", "dev-1", "opp-42", "2026-08-01") == \
            build("reminder", "dev-1", "opp-42", "2026-08-01")
        assert build("reminder", "dev-1", "opp-42", "2026-08-01") != \
            build("reminder", "dev-1", "opp-42", "2026-08-02")
        assert build("reminder", "dev-1", "opp-42", "2026-08-01") != \
            build("digest", "dev-1", "opp-42", "2026-08-01")
        # Bounded well under Resend's 256-character ceiling for any input.
        assert len(build("reminder", "x" * 4000, "y" * 4000, "2026-08-01")) < 64

    def test_reminder_fallback_key_is_stable_across_a_retry(self, monkeypatch):
        keys = []
        for _ in range(2):  # same logical send, attempted on two cron runs
            _set_push_env(monkeypatch)
            emails: list = []
            _install_reminder_io(monkeypatch, subscriptions=[], emails=emails)
            assert _run_reminders().status_code == 200
            keys.append(emails[0]["idempotency_key"])

        assert keys[0] == keys[1]
        assert keys[0] == email_mod.build_idempotency_key(
            "reminder", "dev-1", "opp-42", "2026-08-01",
        )

    def test_reminder_fallback_key_differs_per_send(self, monkeypatch):
        _set_push_env(monkeypatch)
        emails: list = []
        other = dict(_DUE, opportunity_id="opp-99")
        _install_reminder_io(
            monkeypatch, due=[_DUE, other], subscriptions=[], emails=emails,
        )
        assert _run_reminders().status_code == 200
        assert len({e["idempotency_key"] for e in emails}) == 2

        # A different day is a different logical reminder.
        emails.clear()
        _install_reminder_io(
            monkeypatch, subscriptions=[], emails=emails, today="2026-08-02",
        )
        assert _run_reminders().status_code == 200
        assert emails[0]["idempotency_key"] != email_mod.build_idempotency_key(
            "reminder", "dev-1", "opp-42", "2026-08-01",
        )


# ── 4. digest: idempotency, ambiguity, incidents ───────────────────────────


_OPP_A = {"id": "opp-a", "title": "Vision Lab RA", "organization": "UIUC ECE",
          "deadline": "2026-07-01"}
_SID = "11111111-2222-3333-4444-555555555555"


def _digest_row(**overrides):
    row = {
        "id": _SID,
        "name": "ML research",
        "digest_email": "user@example.com",
        "new_match_ids": ["opp-a"],
        "last_digest_sent_at": None,
    }
    row.update(overrides)
    return row


def _set_digest_env(monkeypatch) -> None:
    monkeypatch.setenv("CRON_SECRET", "cron-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("RESEND_API_KEY", "fake")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    monkeypatch.setenv("RESTORE_LINK_SECRET", "digest-secret")


def _install_digest_io(monkeypatch, *, rows, sends=None, rpcs=None,
                       send_impl=None, patch_status: int = 204) -> None:
    class _Client:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, url, **_kwargs):
            if "ops_incidents" in url:
                return _Resp([])
            return _Resp(rows)

        async def post(self, url, json=None, **_kwargs):
            if rpcs is not None:
                rpcs.append({"url": url, "json": json})
            return _Resp(True)

        async def patch(self, _url, **_kwargs):
            return _Resp({}, status_code=patch_status)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    async def _record_send(**kwargs):
        if sends is not None:
            sends.append(kwargs)

    monkeypatch.setattr(ss_mod, "_send_via_resend", send_impl or _record_send)
    monkeypatch.setattr(ss_mod, "load_opportunities", lambda: [_OPP_A])
    email_mod._recipient_sends.clear()


def _run_digest():
    return client.get("/api/cron/saved-searches/digest", headers=AUTH)


class TestDigestIdempotencyKey:
    def test_digest_key_is_stable_across_a_retry_of_the_same_window(self, monkeypatch):
        keys = []
        for _ in range(2):  # e.g. the stamp failed and the cron ran again
            _set_digest_env(monkeypatch)
            sends: list = []
            _install_digest_io(monkeypatch, rows=[_digest_row()], sends=sends)
            assert _run_digest().status_code == 200
            keys.append(sends[0]["idempotency_key"])

        assert keys[0] == keys[1]
        assert keys[0] == email_mod.build_idempotency_key(
            "digest", _SID, datetime.now(UTC).date().isoformat(),
        )

    def test_digest_key_differs_per_saved_search(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        other = _digest_row(id="99999999-2222-3333-4444-555555555555")
        _install_digest_io(monkeypatch, rows=[_digest_row(), other], sends=sends)

        assert _run_digest().status_code == 200
        assert len({s["idempotency_key"] for s in sends}) == 2

    def test_digest_key_differs_per_window(self):
        build = email_mod.build_idempotency_key
        assert build("digest", _SID, "2026-08-01") != build("digest", _SID, "2026-08-08")


class TestDigestFailureClassification:
    def test_ambiguous_transport_failure_is_labelled_and_counted(self, monkeypatch):
        _set_digest_env(monkeypatch)

        async def _hangs(**_kwargs):
            raise httpx.ReadTimeout("resend hung")

        _install_digest_io(monkeypatch, rows=[_digest_row()], send_impl=_hangs)
        body = _run_digest().json()

        assert body["sent"] == 0
        assert body["ambiguous"] == 1
        (err,) = body["errors"]
        assert "AMBIGUOUS" in err
        assert "may have been delivered" in err
        assert "Idempotency-Key" in err

    def test_definitive_rejection_is_labelled_differently(self, monkeypatch):
        _set_digest_env(monkeypatch)

        async def _rejected(**_kwargs):
            raise HTTPException(status_code=502, detail="Email delivery failed")

        _install_digest_io(monkeypatch, rows=[_digest_row()], send_impl=_rejected)
        body = _run_digest().json()

        assert body["sent"] == 0
        assert body["ambiguous"] == 0
        (err,) = body["errors"]
        assert "FAILED (definitively not delivered)" in err
        assert "AMBIGUOUS" not in err

    def test_provider_5xx_is_ambiguous_not_definitive(self, monkeypatch):
        """_send_via_resend preserves the upstream status for exactly this."""
        _set_digest_env(monkeypatch)

        async def _provider_500(**_kwargs):
            failure = HTTPException(status_code=502, detail="Email delivery failed")
            failure.upstream_status = 503
            raise failure

        _install_digest_io(monkeypatch, rows=[_digest_row()], send_impl=_provider_500)
        assert _run_digest().json()["ambiguous"] == 1

    def test_failed_send_is_not_stamped_so_it_retries(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []

        async def _hangs(**_kwargs):
            raise httpx.ReadTimeout("resend hung")

        class _Client:
            def __init__(self, *_a, **_k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def get(self, url, **_kwargs):
                return _Resp([] if "ops_incidents" in url else [_digest_row()])

            async def post(self, _url, json=None, **_kwargs):
                return _Resp(True)

            async def patch(self, url, **kwargs):
                patches.append({"url": url, **kwargs})
                return _Resp({}, status_code=204)

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        monkeypatch.setattr(ss_mod, "_send_via_resend", _hangs)
        monkeypatch.setattr(ss_mod, "load_opportunities", lambda: [_OPP_A])
        email_mod._recipient_sends.clear()

        _run_digest()
        assert [p for p in patches if "last_digest_sent_at" in (p.get("json") or {})] == []


class TestDigestIncidents:
    def test_send_failure_records_an_incident(self, monkeypatch):
        _set_digest_env(monkeypatch)
        rpcs: list = []

        async def _hangs(**_kwargs):
            raise httpx.ReadTimeout("resend hung")

        _install_digest_io(
            monkeypatch, rows=[_digest_row()], rpcs=rpcs, send_impl=_hangs,
        )
        body = _run_digest().json()

        assert body["incidents_recorded"] == 1
        assert body["incident_errors"] == 0
        (incident,) = _incident_rpcs(rpcs)
        assert incident["p_kind"] == "notification_failure"
        assert incident["p_dedup_key"] == f"notification_failure:digest:{_SID}"
        assert incident["p_scope"] == "digest_cron"
        assert incident["p_entity_type"] == "saved_search"
        assert incident["p_entity_id"] == _SID
        detail = incident["p_detail"]
        assert detail["outcome"] == "ambiguous"
        assert detail["may_have_been_delivered"] is True
        assert detail["stamped"] is False
        # The observation (a read timeout) and the outcome (unknown) are
        # recorded separately — failure_state cannot express ambiguity.
        assert incident["p_failure_state"] == "timed_out"
        # No recipient address and no message body in an operator record.
        assert "user@example.com" not in str(incident)

    def test_definitive_failure_incident_says_not_delivered(self, monkeypatch):
        _set_digest_env(monkeypatch)
        rpcs: list = []

        async def _rejected(**_kwargs):
            raise HTTPException(status_code=502, detail="Email delivery failed")

        _install_digest_io(
            monkeypatch, rows=[_digest_row()], rpcs=rpcs, send_impl=_rejected,
        )
        _run_digest()

        (incident,) = _incident_rpcs(rpcs)
        assert incident["p_failure_state"] == "failed"
        assert incident["p_detail"]["outcome"] == "definitive"
        assert incident["p_detail"]["may_have_been_delivered"] is False

    def test_stamp_failure_after_acceptance_is_a_partial_incident(self, monkeypatch):
        _set_digest_env(monkeypatch)
        rpcs: list = []
        _install_digest_io(
            monkeypatch, rows=[_digest_row()], rpcs=rpcs, patch_status=500,
        )
        body = _run_digest().json()

        assert body["sent"] == 1  # the provider DID accept it
        (incident,) = _incident_rpcs(rpcs)
        assert incident["p_dedup_key"] == f"notification_failure:digest:bookkeeping:{_SID}"
        # 'partial': the digest went out, only the record of it failed.
        assert incident["p_failure_state"] == "partial"
        assert incident["p_detail"]["provider_accepted"] is True

    def test_incident_write_failure_never_breaks_the_digest_cron(self, monkeypatch):
        _set_digest_env(monkeypatch)

        async def _hangs(**_kwargs):
            raise httpx.ReadTimeout("resend hung")

        class _Client:
            def __init__(self, *_a, **_k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def get(self, url, **_kwargs):
                return _Resp([] if "ops_incidents" in url else [_digest_row()])

            async def post(self, *_a, **_k):
                raise RuntimeError("supabase unreachable")

            async def patch(self, *_a, **_k):
                return _Resp({}, status_code=204)

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        monkeypatch.setattr(ss_mod, "_send_via_resend", _hangs)
        monkeypatch.setattr(ss_mod, "load_opportunities", lambda: [_OPP_A])
        email_mod._recipient_sends.clear()

        response = _run_digest()
        assert response.status_code == 200
        body = response.json()
        # The run's own error list stays authoritative; the cron completes.
        assert body["incidents_recorded"] == 0
        assert body["incident_errors"] == 1
        assert any("AMBIGUOUS" in e for e in body["errors"])

    def test_healthy_digest_run_makes_no_incident_calls(self, monkeypatch):
        _set_digest_env(monkeypatch)
        rpcs: list = []
        _install_digest_io(monkeypatch, rows=[_digest_row()], rpcs=rpcs)

        assert _run_digest().json()["sent"] == 1
        assert rpcs == []  # nothing failed, nothing open to recover
