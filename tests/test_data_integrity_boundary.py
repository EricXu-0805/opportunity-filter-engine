"""W14 data-integrity boundary — notification bookkeeping + Flow B additions.

Backend halves of the W14 invariants:

    no provider acknowledgment -> no cleared reminder / no "sent"
    bookkeeping failure        -> loud counter, retry next cron (never silent)
    one row's failure          -> never aborts the rest of the batch
    'contacted' (W12)          -> its reminders fire like any other status
    anonymous purchases        -> survive a Flow B account merge (SQL pinned
                                  live by supabase/tests/flow_b_merge_test.sql
                                  scenario 8 in the Migrations CI job; the
                                  content tripwires here keep the migration
                                  from silently regressing in-repo)

Frontend halves (truthful zero states, cross-tab uid isolation, merge-token
retention, save honesty) are pinned by the frontend suites.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

_REPO = Path(__file__).resolve().parents[1]
client = TestClient(app)

_DUE = {
    "device_id": "dev-1", "opportunity_id": "opp-42",
    "remind_at": "2026-08-01", "interaction_type": "applied", "notes": "",
}
_DUE2 = {
    "device_id": "dev-2", "opportunity_id": "opp-77",
    "remind_at": "2026-08-01", "interaction_type": "contacted", "notes": "",
}
_SUB = {"device_id": "dev-1", "endpoint": "https://push.example/one",
        "p256dh": "k", "auth": "a"}
_SUB2 = {"device_id": "dev-2", "endpoint": "https://push.example/two",
         "p256dh": "k", "auth": "a"}


def _set_push_env(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "cron-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://sb.example")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:ops@example.com")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)


def _install_stubs(monkeypatch, *, interactions, subscriptions, gets=None,
                   patches=None, patch_plan=None, webpush_impl=None,
                   account_email=None, send_impl=None):
    """W14-flavored cron stub: captures GET params and lets a test script
    per-PATCH status codes (``patch_plan`` maps a url substring to a list of
    status codes popped per call; default 204)."""
    import httpx
    import pywebpush

    from backend.routes import push as push_mod

    # Reminder delivery is release-scoped: these tests exercise transport and
    # bookkeeping, so make their target-visibility precondition explicit.
    monkeypatch.setattr(
        push_mod,
        "load_opportunities_by_id",
        lambda: {
            row["opportunity_id"]: {
                "id": row["opportunity_id"],
                "source_type": "campus_program",
                "opportunity_type": "research",
                "metadata": {"is_active": True},
            }
            for row in interactions
        },
    )

    class _Resp:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code

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
            if gets is not None:
                gets.append({"url": url, **kwargs})
            if "/auth/v1/admin/users/" in url:
                if account_email is None:
                    return _Resp({}, status_code=404)
                return _Resp({"email": account_email})
            if "push_subscriptions" in url:
                return _Resp(subscriptions)
            return _Resp(interactions)

        async def patch(self, url, **kwargs):
            if patches is not None:
                patches.append({"url": url, **kwargs})
            if patch_plan:
                for needle, plan in patch_plan.items():
                    if needle in url and plan:
                        return _Resp({}, status_code=plan.pop(0))
            return _Resp({}, status_code=204)

        async def delete(self, url, **kwargs):
            return _Resp({}, status_code=204)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    def _default_webpush(**kwargs):
        return None

    monkeypatch.setattr(pywebpush, "webpush", webpush_impl or _default_webpush)

    async def _pass_through(*, subscription_info, data, vapid_private_key,
                            vapid_claims, webpush_func, **_transport):
        # ``**_transport`` absorbs the delivery-shaping kwargs the route now
        # hands the real dispatcher (ttl + the RFC 8030 Topic header); they are
        # pinned by tests/test_notification_idempotency.py.
        return webpush_func(
            subscription_info=subscription_info, data=data,
            vapid_private_key=vapid_private_key, vapid_claims=vapid_claims,
        )

    monkeypatch.setattr(push_mod, "send_webpush_safely", _pass_through)
    if send_impl is not None:
        monkeypatch.setattr(push_mod, "_send_via_resend", send_impl)


def _run():
    return client.get("/api/cron/reminders",
                      headers={"Authorization": "Bearer cron-ok"})


# ---------------------------------------------------------------------------
# 'contacted' reminders fire (W12 regression fixed)
# ---------------------------------------------------------------------------

class TestContactedReminders:
    def test_due_query_includes_contacted(self, monkeypatch):
        _set_push_env(monkeypatch)
        gets: list = []
        _install_stubs(monkeypatch, interactions=[], subscriptions=[], gets=gets)
        assert _run().status_code == 200
        due_get = next(g for g in gets if "interactions" in g["url"])
        assert due_get["params"]["interaction_type"] == \
            "in.(contacted,applied,replied,interviewing)"

    def test_contacted_row_is_delivered_and_cleared(self, monkeypatch):
        _set_push_env(monkeypatch)
        patches: list = []
        _install_stubs(monkeypatch, interactions=[_DUE2], subscriptions=[_SUB2],
                       patches=patches)
        body = _run().json()
        assert body["sent"] == 1
        clear = [p for p in patches if "interactions" in p["url"]]
        assert clear and clear[0]["json"] == {"remind_at": None}


# ---------------------------------------------------------------------------
# Bookkeeping is verified, retried, and loud — never silent
# ---------------------------------------------------------------------------

class TestARescheduleDuringTheRunSurvives:
    """The batch is read once and then worked through with a network round trip
    per row, so a student can reschedule a reminder while the job is still
    running. The clear used to filter on (device, opportunity) only and set
    remind_at to NULL unconditionally, so the new date the tracker had just
    accepted and painted was silently deleted — with no counter for it.
    """

    def test_the_clear_names_the_value_this_run_read(self, monkeypatch):
        _set_push_env(monkeypatch)
        patches: list = []
        _install_stubs(monkeypatch, interactions=[_DUE], subscriptions=[_SUB],
                       patches=patches)
        assert _run().json()["sent"] == 1
        clear = next(p for p in patches if "interactions" in p["url"])
        assert clear["params"]["remind_at"] == f"eq.{_DUE['remind_at']}"
        assert clear["params"]["device_id"] == f"eq.{_DUE['device_id']}"
        assert clear["json"] == {"remind_at": None}

    def test_the_retry_carries_the_same_guard(self, monkeypatch):
        """A retry that dropped the guard would reintroduce the clobber on
        exactly the runs where the first attempt was slowest."""
        _set_push_env(monkeypatch)
        patches: list = []
        _install_stubs(
            monkeypatch, interactions=[_DUE], subscriptions=[_SUB],
            patches=patches, patch_plan={"interactions": [500, 204]},
        )
        _run()
        clears = [p for p in patches if "interactions" in p["url"]]
        assert len(clears) == 2
        for attempt in clears:
            assert attempt["params"]["remind_at"] == f"eq.{_DUE['remind_at']}"


class TestBookkeepingTruth:
    def test_remind_at_clear_failure_is_counted(self, monkeypatch):
        _set_push_env(monkeypatch)
        patches: list = []
        _install_stubs(
            monkeypatch, interactions=[_DUE], subscriptions=[_SUB],
            patches=patches, patch_plan={"interactions": [500, 500]},
        )
        body = _run().json()
        assert body["sent"] == 1
        # Both attempts happened; the failure is visible, not swallowed.
        assert len([p for p in patches if "interactions" in p["url"]]) == 2
        assert body["bookkeeping_failed"] == 1

    def test_remind_at_clear_retry_recovers(self, monkeypatch):
        _set_push_env(monkeypatch)
        patches: list = []
        _install_stubs(
            monkeypatch, interactions=[_DUE], subscriptions=[_SUB],
            patches=patches, patch_plan={"interactions": [500, 204]},
        )
        body = _run().json()
        assert body["bookkeeping_failed"] == 0
        assert len([p for p in patches if "interactions" in p["url"]]) == 2

    def test_delivery_stamp_failure_is_counted_not_fatal(self, monkeypatch):
        _set_push_env(monkeypatch)
        _install_stubs(
            monkeypatch, interactions=[_DUE], subscriptions=[_SUB],
            patch_plan={"push_subscriptions": [500]},
        )
        body = _run().json()
        assert body["sent"] == 1
        assert body["bookkeeping_failed"] == 1


# ---------------------------------------------------------------------------
# One row's failure never aborts the batch
# ---------------------------------------------------------------------------

class TestRowIsolation:
    def test_unexpected_row_error_does_not_abort_batch(self, monkeypatch):
        _set_push_env(monkeypatch)

        def _explodes_for_dev1(**kwargs):
            if kwargs["subscription_info"]["endpoint"].endswith("/one"):
                raise RuntimeError("unexpected transport wreckage")
            return None

        patches: list = []
        _install_stubs(
            monkeypatch, interactions=[_DUE, _DUE2],
            subscriptions=[_SUB, _SUB2],
            patches=patches, webpush_impl=_explodes_for_dev1,
        )
        body = _run().json()
        assert body["row_errors"] == 1
        assert body["sent"] == 1  # dev-2 still got its reminder
        cleared = [p for p in patches if "interactions" in p["url"]]
        assert len(cleared) == 1
        assert cleared[0]["params"]["device_id"] == "eq.dev-2"

    def test_email_fallback_timeout_does_not_abort(self, monkeypatch):
        import httpx

        _set_push_env(monkeypatch)
        monkeypatch.setenv("RESEND_API_KEY", "fake")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")

        async def _timeout_send(**kwargs):
            raise httpx.ReadTimeout("resend hung")

        _install_stubs(
            monkeypatch, interactions=[_DUE], subscriptions=[],
            account_email="user@example.com", send_impl=_timeout_send,
        )
        body = _run().json()
        assert body["status"] == "ok"
        assert body["failed"] == 1
        assert body["emailed"] == 0


# ---------------------------------------------------------------------------
# Digest stamp: retried and loud (nightly-duplicate prevention)
# ---------------------------------------------------------------------------

class TestDigestStampTruth:
    def test_stamp_failure_after_send_is_a_loud_error(self, monkeypatch):
        from tests.test_saved_search_digest import (
            _digest_row,
            _set_digest_env,
        )
        from tests.test_saved_search_digest import (
            _install_stubs as _digest_stubs,
        )

        _set_digest_env(monkeypatch)
        patches: list = []
        _digest_stubs(monkeypatch, rows=[_digest_row()], sends=[], patches=patches)

        # Rig every saved_searches PATCH to fail.
        import httpx
        real_client = httpx.AsyncClient

        class _FailingPatch(real_client):
            async def patch(self, url, **kwargs):
                resp = await super().patch(url, **kwargs)
                resp.status_code = 500
                return resp

        monkeypatch.setattr(httpx, "AsyncClient", _FailingPatch)

        r = client.get("/api/cron/saved-searches/digest",
                       headers={"Authorization": "Bearer cron-ok"})
        body = r.json()
        assert body["sent"] == 1  # provider accepted — send DID happen
        assert any("stamp failed" in e for e in body["errors"])
        # Two attempts = retry occurred.
        assert len([p for p in patches if "saved_searches" in p["url"]]) == 2


# ---------------------------------------------------------------------------
# Cron overlap protection + Flow B orders merge (content tripwires; the live
# behavior is pinned by supabase/tests/flow_b_merge_test.sql s8 in CI)
# ---------------------------------------------------------------------------

class TestStructuralGuards:
    def test_cron_workflows_have_concurrency_groups(self):
        for wf in ("daily-reminders.yml", "saved-searches-refresh.yml"):
            text = (_REPO / ".github/workflows" / wf).read_text()
            assert "concurrency:" in text, f"{wf} lost its concurrency group"
            assert "cancel-in-progress: false" in text, wf

    def test_migration_025_merges_orders_and_widens_ttl(self):
        sql = (_REPO / "supabase/migrations/025_merge_orders_grant_ttl.sql").read_text()
        assert "UPDATE orders SET device_id = v_target" in sql
        assert "jsonb_build_object('orders', n)" in sql
        assert "interval '60 minutes'" in sql
        assert "interval '15 minutes'" not in sql

    def test_flow_b_suite_covers_orders(self):
        sql = (_REPO / "supabase/tests/flow_b_merge_test.sql").read_text()
        assert "PASS scenario 8" in sql
        assert "paid anonymous order lost" in sql
