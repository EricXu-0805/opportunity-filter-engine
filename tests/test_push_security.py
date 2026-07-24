"""Security regression tests for persisted Web Push subscriptions.

Push endpoints are user-controlled rows that are consumed later by the reminder
cron.  These tests pin the second-order SSRF boundary: validation must happen at
send time, DNS must fail closed, and a blocked/timed-out delivery must not clear
the reminder.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable

import httpx
import pytest
import requests
from fastapi.testclient import TestClient

from backend.lib.safe_webpush import (
    UnsafePushEndpointError,
    WebPushDeliveryTimeout,
    _NoRedirectSession,
    _PinnedHTTPSAdapter,
    send_webpush_safely,
    validate_push_endpoint,
)
from backend.main import app
from backend.routes import push as push_mod

client = TestClient(app)


def _dns(*addresses: str) -> Callable[..., list[tuple]]:
    def resolve(_host: str, port: int, **_kwargs) -> list[tuple]:
        rows = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            rows.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
        return rows

    return resolve


def _assert_blocked(endpoint: str, resolver: Callable[..., list[tuple]], reason: str) -> None:
    with pytest.raises(UnsafePushEndpointError) as exc_info:
        validate_push_endpoint(endpoint, resolver=resolver)
    assert exc_info.value.reason == reason
    # Do not put attacker-controlled hosts or internal addresses in surfaced errors.
    assert endpoint not in str(exc_info.value)


class TestPushEndpointValidation:
    def test_rejects_http_loopback_endpoint(self):
        _assert_blocked(
            "http://127.0.0.1:8080/admin",
            _dns("127.0.0.1"),
            "https_required",
        )

    def test_rejects_localhost_before_dns(self):
        def should_not_resolve(*_args, **_kwargs):
            raise AssertionError("localhost must be rejected before DNS")

        _assert_blocked(
            "https://localhost/latest/meta-data/",
            should_not_resolve,
            "disallowed_hostname",
        )

    def test_rejects_hostname_resolving_to_private_ip(self):
        _assert_blocked(
            "https://push.attacker.example/subscription",
            _dns("10.23.4.5"),
            "non_public_address",
        )

    def test_dns_failure_is_fail_closed(self):
        def unavailable(*_args, **_kwargs):
            raise socket.gaierror(socket.EAI_NONAME, "not found")

        _assert_blocked(
            "https://missing.attacker.example/subscription",
            unavailable,
            "dns_resolution_failed",
        )

    def test_rejects_mixed_public_and_private_dns_answers(self):
        _assert_blocked(
            "https://rebind.attacker.example/subscription",
            _dns("93.184.216.34", "169.254.169.254"),
            "non_public_address",
        )

    def test_accepts_multiple_public_ipv4_and_ipv6_answers(self):
        validated = validate_push_endpoint(
            "https://updates.push.services.mozilla.com/wpush/v2/abc?token=def",
            resolver=_dns("93.184.216.34", "2606:4700:4700::1111"),
        )
        assert validated.hostname == "updates.push.services.mozilla.com"
        assert validated.port == 443
        assert validated.addresses == ("93.184.216.34", "2606:4700:4700::1111")

    def test_rejects_oversized_endpoint(self):
        endpoint = "https://push.example.test/" + ("x" * 2048)
        _assert_blocked(endpoint, _dns("93.184.216.34"), "endpoint_too_long")


class TestBoundedWebPushDispatch:
    def test_adapter_pins_public_ip_but_preserves_host_and_tls_identity(self):
        endpoint = "https://updates.push.services.mozilla.com/wpush/v2/abc"
        validated = validate_push_endpoint(endpoint, resolver=_dns("93.184.216.34"))
        adapter = _PinnedHTTPSAdapter(validated)
        prepared = requests.Request("POST", endpoint).prepare()

        host_params, pool_kwargs = adapter.build_connection_pool_key_attributes(
            prepared,
            verify=True,
        )
        adapter.add_headers(prepared)

        assert host_params == {"scheme": "https", "host": "93.184.216.34", "port": 443}
        assert pool_kwargs["server_hostname"] == "updates.push.services.mozilla.com"
        assert pool_kwargs["assert_hostname"] == "updates.push.services.mozilla.com"
        assert prepared.url == endpoint
        assert prepared.headers["Host"] == "updates.push.services.mozilla.com"

        # The pool and connection receive only the numeric, prevalidated IP.
        # The original hostname survives solely as Host/SNI/cert identity, so
        # urllib3 has no path to resolve attacker-controlled DNS a second time.
        pool = adapter.get_connection_with_tls_context(prepared, verify=True, proxies={})
        connection = pool._new_conn()
        assert pool.host == "93.184.216.34"
        assert connection.host == "93.184.216.34"
        assert connection.server_hostname == "updates.push.services.mozilla.com"
        assert connection.assert_hostname == "updates.push.services.mozilla.com"
        adapter.close()

    def test_adapter_refuses_cross_origin_requests(self):
        validated = validate_push_endpoint(
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            resolver=_dns("93.184.216.34"),
        )
        adapter = _PinnedHTTPSAdapter(validated)
        prepared = requests.Request("POST", "https://evil.example/wpush/v2/abc").prepare()

        with pytest.raises(ValueError):
            adapter.build_connection_pool_key_attributes(prepared, verify=True)
        adapter.close()

    def test_session_forces_redirects_off(self, monkeypatch):
        validated = validate_push_endpoint(
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            resolver=_dns("93.184.216.34"),
        )
        captured: dict = {}

        def fake_request(_self, _method, _url, *args, **kwargs):
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(requests.Session, "request", fake_request)
        with _NoRedirectSession(validated) as session:
            session.request(
                "POST",
                "https://updates.push.services.mozilla.com/wpush/v2/abc",
                allow_redirects=True,
            )

        assert captured["allow_redirects"] is False

    def test_passes_connect_read_timeout_and_disables_env_proxies(self):
        captured: dict = {}

        def fake_webpush(**kwargs):
            captured.update(kwargs)
            return object()

        result = asyncio.run(
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
            )
        )

        assert result is not None
        assert captured["timeout"] == (3.0, 5.0)
        assert captured["requests_session"].trust_env is False
        assert captured["requests_session"].max_redirects == 0

    def test_total_timeout_bounds_a_stuck_sender(self):
        entered = threading.Event()
        release = threading.Event()

        def stuck_webpush(**_kwargs):
            entered.set()
            release.wait(timeout=1.0)

        async def run() -> None:
            with pytest.raises(WebPushDeliveryTimeout):
                await send_webpush_safely(
                    subscription_info={
                        "endpoint": "https://push.example.test/wpush/v2/abc",
                        "keys": {"p256dh": "key", "auth": "auth"},
                    },
                    data="{}",
                    vapid_private_key="private",
                    vapid_claims={"sub": "mailto:ops@example.com"},
                    webpush_func=stuck_webpush,
                    resolver=_dns("93.184.216.34"),
                    total_timeout=0.05,
                )

        try:
            asyncio.run(run())
            assert entered.wait(timeout=0.5)
        finally:
            release.set()


# ── Reminder cron: the send path must go through the validated dispatcher ────

_DUE_ROW = {
    "device_id": "dev-1",
    "opportunity_id": "opp-42",
    "remind_at": "2020-01-01",
    "interaction_type": "applied",
    "notes": "",
}


class _Resp:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


def _set_cron_env(monkeypatch) -> None:
    monkeypatch.setenv("CRON_SECRET", "cron-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "vapid-priv")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "vapid-pub")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:ops@example.com")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)


def _install_cron_io(
    monkeypatch,
    *,
    endpoint: str,
    patches: list,
    deletes: list,
    webpush_calls: list,
) -> None:
    import pywebpush

    subscriptions = [
        {
            "device_id": "dev-1",
            "endpoint": endpoint,
            "p256dh": "p256dh-key",
            "auth": "auth-key",
        }
    ]

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, **_kwargs):
            if "/auth/v1/admin/users/" in url:
                return _Resp({}, status_code=404)
            if "push_subscriptions" in url:
                return _Resp(subscriptions)
            return _Resp([_DUE_ROW])

        async def patch(self, url, **kwargs):
            patches.append({"url": url, **kwargs})
            return _Resp({}, 204)

        async def delete(self, url, **kwargs):
            deletes.append({"url": url, **kwargs})
            return _Resp({}, 204)

    def fake_webpush(**kwargs):
        webpush_calls.append(kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)


def _run_cron():
    return client.get(
        "/api/cron/reminders", headers={"Authorization": "Bearer cron-ok"}
    )


class TestReminderCronSSRFBoundary:
    def test_blocked_endpoint_is_pruned_and_reminder_kept(self, monkeypatch):
        _set_cron_env(monkeypatch)
        patches: list = []
        deletes: list = []
        calls: list = []
        # A literal non-public IP is rejected by the outbound-network policy
        # without any DNS/network dependence in the test.
        _install_cron_io(
            monkeypatch,
            endpoint="https://127.0.0.1:8443/internal",
            patches=patches,
            deletes=deletes,
            webpush_calls=calls,
        )

        response = _run_cron()

        assert response.status_code == 200
        body = response.json()
        assert body["sent"] == 0
        assert body["failed"] == 1
        assert body["pruned"] == 1
        assert calls == []  # pywebpush never invoked for a blocked endpoint
        assert len(deletes) == 1
        assert patches == []  # remind_at untouched, nothing was delivered
        assert "127.0.0.1" not in response.text

    def test_timeout_is_counted_and_subscription_kept(self, monkeypatch):
        _set_cron_env(monkeypatch)
        patches: list = []
        deletes: list = []
        calls: list = []
        _install_cron_io(
            monkeypatch,
            endpoint="https://push.example.test/wpush/v2/abc",
            patches=patches,
            deletes=deletes,
            webpush_calls=calls,
        )

        async def time_out(**_kwargs):
            raise WebPushDeliveryTimeout("deadline exceeded")

        monkeypatch.setattr(push_mod, "send_webpush_safely", time_out)
        response = _run_cron()

        assert response.status_code == 200
        body = response.json()
        assert body["sent"] == 0
        assert body["failed"] == 1
        assert body["pruned"] == 0
        assert deletes == []
        assert patches == []

    def test_send_path_uses_validated_dispatcher(self, monkeypatch):
        _set_cron_env(monkeypatch)
        patches: list = []
        deletes: list = []
        calls: list = []
        _install_cron_io(
            monkeypatch,
            endpoint="https://push.example.test/wpush/v2/abc",
            patches=patches,
            deletes=deletes,
            webpush_calls=calls,
        )
        dispatched: list = []

        async def record(**kwargs):
            dispatched.append(kwargs)

        monkeypatch.setattr(push_mod, "send_webpush_safely", record)
        response = _run_cron()

        assert response.status_code == 200
        body = response.json()
        assert body["sent"] == 1
        assert body["failed"] == 0
        # The raw pywebpush entrypoint is only ever handed to the dispatcher —
        # never called directly by the route.
        assert calls == []
        assert len(dispatched) == 1
        assert dispatched[0]["subscription_info"]["endpoint"] == (
            "https://push.example.test/wpush/v2/abc"
        )
        assert callable(dispatched[0]["webpush_func"])
        sub_patches = [p for p in patches if "push_subscriptions" in p["url"]]
        assert len(sub_patches) == 1
        assert sub_patches[0]["json"].keys() == {"last_delivered_at"}
        int_patches = [p for p in patches if "interactions" in p["url"]]
        assert len(int_patches) == 1
        assert int_patches[0]["json"] == {"remind_at": None}
