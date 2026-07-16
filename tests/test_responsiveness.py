"""Responsiveness signals (红黑榜 v1): aggregation endpoint + ranker bonus.

All Supabase traffic is stubbed at the httpx boundary (digest-test pattern) —
no network. Invariants pinned:

  * a contact counts once per device (status transitions dedup by device_id)
  * replied = reached 'replied' (got-reply) or 'interviewing'
  * aggregates with contacted_n < RESPONSIVENESS_MIN_N never leave the endpoint
  * 'dismissed' transitions are not contacts
  * the map is cached in-process (~1h) — one Supabase fetch per TTL
  * a failed fetch is cached too (short backoff) — no per-request retry storm
  * ranker bonus defaults to 2.0 (OFE_RESPONSIVENESS_BONUS=0 disables), clamped ≤ 3
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
from backend.routes import responsiveness as resp_mod
from src.matcher import ranker
from src.matcher.config import RESPONSIVENESS_MIN_N
from src.matcher.ranker import _responsiveness_bonus, rank_all, rank_opportunity

client = TestClient(app)


def _row(opp, dev, to_status):
    return {"opportunity_id": opp, "device_id": dev, "to_status": to_status}


def _rows_default():
    return [
        # opp-hot: 3 distinct devices contacted, d1 got a reply (2 rows → 1 contact)
        _row("opp-hot", "d1", "applied"),
        _row("opp-hot", "d1", "replied"),
        _row("opp-hot", "d2", "applied"),
        _row("opp-hot", "d3", "rejected"),
        # opp-tiny: only 2 devices → suppressed
        _row("opp-tiny", "d1", "applied"),
        _row("opp-tiny", "d2", "replied"),
        # opp-interview: replied via 'interviewing', 3 devices
        _row("opp-interview", "d4", "applied"),
        _row("opp-interview", "d5", "interviewing"),
        _row("opp-interview", "d6", "applied"),
        # opp-dismissed: dismissals are not contacts
        _row("opp-dismissed", "d1", "dismissed"),
        _row("opp-dismissed", "d2", "dismissed"),
        _row("opp-dismissed", "d3", "dismissed"),
    ]


def _set_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")


def _install_httpx_stub(monkeypatch, rows, calls=None):
    class _Resp:
        status_code = 200

        def __init__(self, data):
            self._data = data

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
            if calls is not None:
                calls.append(url)
            offset = int(kwargs.get("params", {}).get("offset", 0))
            return _Resp(rows[offset:offset + resp_mod._PAGE_SIZE])

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(resp_mod, "_cache", None)
    monkeypatch.setattr(resp_mod, "_cache_time", 0.0)


class TestAggregationEndpoint:
    def test_counts_contacted_and_replied(self, monkeypatch):
        _set_env(monkeypatch)
        _install_httpx_stub(monkeypatch, _rows_default())
        r = client.get("/api/opportunities/responsiveness")
        assert r.status_code == 200
        body = r.json()
        assert body["min_n"] == RESPONSIVENESS_MIN_N
        assert body["signals"]["opp-hot"] == {"contacted_n": 3, "replied_n": 1}

    def test_device_dedup_two_transitions_one_contact(self, monkeypatch):
        _set_env(monkeypatch)
        rows = [
            _row("opp-x", "d1", "applied"),
            _row("opp-x", "d1", "replied"),
            _row("opp-x", "d1", "interviewing"),
            _row("opp-x", "d2", "applied"),
            _row("opp-x", "d3", "applied"),
        ]
        _install_httpx_stub(monkeypatch, rows)
        signals = client.get("/api/opportunities/responsiveness").json()["signals"]
        assert signals["opp-x"] == {"contacted_n": 3, "replied_n": 1}

    def test_small_n_suppressed(self, monkeypatch):
        _set_env(monkeypatch)
        _install_httpx_stub(monkeypatch, _rows_default())
        signals = client.get("/api/opportunities/responsiveness").json()["signals"]
        assert "opp-tiny" not in signals

    def test_interviewing_counts_as_replied(self, monkeypatch):
        _set_env(monkeypatch)
        _install_httpx_stub(monkeypatch, _rows_default())
        signals = client.get("/api/opportunities/responsiveness").json()["signals"]
        assert signals["opp-interview"]["replied_n"] == 1

    def test_dismissed_not_a_contact(self, monkeypatch):
        _set_env(monkeypatch)
        _install_httpx_stub(monkeypatch, _rows_default())
        signals = client.get("/api/opportunities/responsiveness").json()["signals"]
        assert "opp-dismissed" not in signals

    def test_missing_env_returns_empty(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        r = client.get("/api/opportunities/responsiveness")
        assert r.status_code == 200
        assert r.json()["signals"] == {}

    def test_cached_second_request_no_refetch(self, monkeypatch):
        _set_env(monkeypatch)
        calls: list[str] = []
        _install_httpx_stub(monkeypatch, _rows_default(), calls=calls)
        client.get("/api/opportunities/responsiveness")
        first = len(calls)
        assert first >= 1
        client.get("/api/opportunities/responsiveness")
        assert len(calls) == first

    def test_failed_fetch_backs_off_not_per_request(self, monkeypatch):
        _set_env(monkeypatch)
        calls: list[str] = []

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, **kwargs):
                calls.append(url)
                raise RuntimeError("supabase down")

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        first = client.get("/api/opportunities/responsiveness")
        assert first.status_code == 200
        assert first.json()["signals"] == {}
        client.get("/api/opportunities/responsiveness")
        assert len(calls) == 1


_SIGNALS = {"opp-1": {"contacted_n": 3, "replied_n": 2}}


def _opp(opp_id="opp-1"):
    return {
        "id": opp_id,
        "opportunity_type": "research",
        "title": "Vision Lab RA",
        "keywords": ["machine learning"],
        "eligibility": {"majors": [], "international_friendly": "yes"},
        "application": {},
    }


def _profile():
    return {"year": "sophomore", "major": "Computer Science", "hard_skills": []}


class TestRankerBonus:
    def test_on_by_default_at_2(self):
        assert _responsiveness_bonus(_opp(), _SIGNALS) == 2.0
        with_map = rank_opportunity(_profile(), _opp(), responsiveness=_SIGNALS)
        without = rank_opportunity(_profile(), _opp())
        assert with_map.final_score > without.final_score

    def test_env_zero_disables(self, monkeypatch):
        monkeypatch.setattr(ranker, "RESPONSIVENESS_BONUS", 0.0)
        assert _responsiveness_bonus(_opp(), _SIGNALS) == 0.0
        with_map = rank_opportunity(_profile(), _opp(), responsiveness=_SIGNALS)
        without = rank_opportunity(_profile(), _opp())
        assert with_map.final_score == without.final_score

    def test_bonus_when_enabled(self, monkeypatch):
        monkeypatch.setattr(ranker, "RESPONSIVENESS_BONUS", 3.0)
        assert _responsiveness_bonus(_opp(), _SIGNALS) == 3.0
        boosted = rank_opportunity(_profile(), _opp(), responsiveness=_SIGNALS)
        base = rank_opportunity(_profile(), _opp())
        assert boosted.final_score > base.final_score

    def test_bonus_clamped_at_3(self, monkeypatch):
        monkeypatch.setattr(ranker, "RESPONSIVENESS_BONUS", 10.0)
        assert _responsiveness_bonus(_opp(), _SIGNALS) == 3.0

    def test_no_bonus_below_min_n(self, monkeypatch):
        monkeypatch.setattr(ranker, "RESPONSIVENESS_BONUS", 3.0)
        assert _responsiveness_bonus(_opp(), {"opp-1": {"contacted_n": 2, "replied_n": 2}}) == 0.0

    def test_no_bonus_without_replies(self, monkeypatch):
        monkeypatch.setattr(ranker, "RESPONSIVENESS_BONUS", 3.0)
        assert _responsiveness_bonus(_opp(), {"opp-1": {"contacted_n": 5, "replied_n": 0}}) == 0.0

    def test_no_bonus_for_unlisted_opportunity(self, monkeypatch):
        monkeypatch.setattr(ranker, "RESPONSIVENESS_BONUS", 3.0)
        assert _responsiveness_bonus(_opp("opp-other"), _SIGNALS) == 0.0

    def test_none_map_is_noop(self, monkeypatch):
        monkeypatch.setattr(ranker, "RESPONSIVENESS_BONUS", 3.0)
        assert _responsiveness_bonus(_opp(), None) == 0.0

    def test_rank_all_threads_the_map(self, monkeypatch):
        monkeypatch.setattr(ranker, "RESPONSIVENESS_BONUS", 3.0)
        opps = [_opp()]
        boosted = rank_all(_profile(), opps, responsiveness=_SIGNALS)
        base = rank_all(_profile(), opps)
        assert boosted[0].final_score > base[0].final_score
