from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend import main as main_module
from backend.lib.release_scope import (
    RELEASE_SCOPE,
    feature_enabled,
    opportunity_visible_in_release,
)
from backend.main import app
from backend.routes import cold_email as cold_email_module
from backend.routes import matches as matches_module
from backend.routes import opportunities as opportunities_module
from backend.routes import push as push_module
from backend.routes import roadmap as roadmap_module
from backend.routes import saved_searches as saved_searches_module
from backend.routes import tailor as tailor_module
from backend.schemas import ProfileRequest
from src.matcher.ranker import MatchResult

RELEASE_CONTRACT_TESTS = True

client = TestClient(app)


def test_unaccepted_server_features_fail_closed(monkeypatch):
    monkeypatch.setenv("OFE_PAYMENTS_ENABLED", "true")

    assert all(value is False for value in RELEASE_SCOPE.values())
    assert feature_enabled("payments") is False


def test_unaccepted_routes_return_404_before_any_handler():
    requests = [
        ("POST", "/api/roadmap"),
        ("POST", "/api/matches/opp-1/gaps"),
        ("POST", "/api/matches/opp-1/explain"),
        ("POST", "/api/tailor/structure"),
        ("POST", "/api/tailor/renovate"),
        ("POST", "/api/tailor/bullet"),
        ("POST", "/api/opportunities/opp-1/chat"),
        ("GET", "/api/chat/models"),
        ("GET", "/api/opportunities/responsiveness"),
        ("POST", "/api/professors/updates"),
        ("POST", "/api/orders/not-an-order/mark-paid-claimed"),
        ("GET", "/api/admin/orders"),
    ]

    for method, path in requests:
        response = client.request(method, path)
        assert response.status_code == 404, (method, path, response.text)
        assert response.json() == {"detail": "Not found"}

    trailing_slash = client.post("/api/tailor/renovate/", follow_redirects=False)
    assert trailing_slash.status_code == 404
    assert trailing_slash.json() == {"detail": "Not found"}


def test_frozen_routes_bypass_rate_buckets_but_keep_security_headers(monkeypatch):
    monkeypatch.setattr(main_module, "RATE_LIMIT_DISABLED", False)
    main_module._rate_buckets.clear()
    main_module._global_buckets.clear()
    try:
        response = client.post("/api/tailor/renovate", json={})
        assert response.status_code == 404
        assert not main_module._rate_buckets
        assert not main_module._global_buckets
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
    finally:
        main_module._rate_buckets.clear()
        main_module._global_buckets.clear()


def test_match_ai_query_is_not_billable_while_refine_is_unaccepted():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": b"llm=true",
        }
    )
    assert main_module._billable_class(request, "/api/matches") is None


def test_hidden_professor_signals_never_reach_match_ranking(monkeypatch):
    async def forbidden_signals_map():
        raise AssertionError("hidden professor signals were fetched")

    monkeypatch.setattr(matches_module, "signals_map", forbidden_signals_map)
    assert asyncio.run(matches_module._responsiveness_for_matching()) is None


def test_hidden_fellowship_preference_is_removed_server_side():
    profile = ProfileRequest(seeking_type=["fellowship"])
    normalized = matches_module._normalized_profile(profile)
    assert normalized["seeking_type"] == ["research", "summer_program"]


def _fellowship_release_corpus() -> list[dict]:
    deadline = (date.today() + timedelta(days=5)).isoformat()
    common = {
        "organization": "Example University",
        "deadline": deadline,
        "keywords": ["machine learning", "vision"],
        "metadata": {"is_active": True},
        "source": "uiuc_release_contract",
    }
    return [
        {
            **common,
            "id": "regular-research",
            "title": "Visible research",
            "opportunity_type": "research",
            "eligibility": {"majors": ["Computer Science"]},
        },
        {
            **common,
            "id": "regular-research-peer",
            "title": "Visible research peer",
            "opportunity_type": "research",
            "eligibility": {"majors": []},
        },
        {
            **common,
            "id": "fellowship-major-match",
            "title": "Hidden fellowship with matching major",
            "opportunity_type": "fellowship",
            "eligibility": {"majors": ["Computer Science"]},
        },
        {
            **common,
            "id": "fellowship-no-majors",
            "title": "Hidden legacy fellowship without majors",
            "type": " Fellowship ",
            "eligibility": {"majors": []},
        },
    ]


def test_hidden_fellowship_records_never_enter_match_ranking(monkeypatch):
    corpus = _fellowship_release_corpus()
    lookup = {opportunity["id"]: opportunity for opportunity in corpus}
    ranked_ids: list[str] = []

    def rank_every_received_record(_profile, opportunities, **_kwargs):
        ranked_ids.extend(opportunity["id"] for opportunity in opportunities)
        return [
            MatchResult(
                opportunity_id=opportunity["id"],
                eligibility_score=80,
                readiness_score=80,
                upside_score=80,
                final_score=80,
                bucket="good_match",
                reasons_fit=[],
                reasons_gap=[],
                next_steps=[],
            )
            for opportunity in opportunities
        ]

    monkeypatch.setattr(matches_module, "load_opportunities", lambda: corpus)
    monkeypatch.setattr(matches_module, "load_opportunities_by_id", lambda: lookup)
    monkeypatch.setattr(matches_module, "rank_all", rank_every_received_record)
    matches_module._match_snapshots.clear()
    try:
        response = client.post(
            "/api/matches",
            json={
                "major": "Computer Science",
                "seeking_type": ["research", "fellowship"],
            },
        )
    finally:
        matches_module._match_snapshots.clear()

    assert response.status_code == 200
    returned_ids = {
        result["opportunity_id"] for result in response.json()["results"]
    }
    assert ranked_ids == ["regular-research", "regular-research-peer"]
    assert returned_ids == {"regular-research", "regular-research-peer"}


def test_hidden_fellowship_records_never_leave_discovery_apis(monkeypatch):
    corpus = _fellowship_release_corpus()
    lookup = {opportunity["id"]: opportunity for opportunity in corpus}
    monkeypatch.setattr(opportunities_module, "load_opportunities", lambda: corpus)
    monkeypatch.setattr(
        opportunities_module,
        "load_opportunities_by_id",
        lambda: lookup,
    )
    monkeypatch.setattr(opportunities_module, "_stats_cache", None)

    listed = client.get("/api/opportunities?limit=20").json()
    assert [item["id"] for item in listed["opportunities"]] == [
        "regular-research",
        "regular-research-peer",
    ]
    assert listed["total"] == 2
    assert client.get(
        "/api/opportunities?opportunity_type=fellowship"
    ).json()["total"] == 0

    for hidden_id in ("fellowship-major-match", "fellowship-no-majors"):
        assert client.get(f"/api/opportunities/{hidden_id}").status_code == 404
        assert client.get(
            f"/api/opportunities/{hidden_id}/similar"
        ).status_code == 404

    batch = client.post(
        "/api/opportunities/batch",
        json={"ids": list(lookup)},
    ).json()
    assert batch["requested"] == 4
    assert batch["found"] == 2
    assert {
        item["id"] for item in batch["opportunities"]
    } == {"regular-research", "regular-research-peer"}

    upcoming = client.get("/api/opportunities/upcoming?days=30").json()
    assert upcoming["total"] == 2
    assert {
        item["id"] for item in upcoming["opportunities"]
    } == {"regular-research", "regular-research-peer"}

    similar = client.get(
        "/api/opportunities/regular-research/similar?limit=20"
    ).json()
    assert {
        item["id"] for item in similar["opportunities"]
    } == {"regular-research-peer"}

    stats = client.get("/api/opportunities/stats/summary").json()
    assert stats["total"] == 2
    assert "fellowship" not in stats["by_type"]

    coverage = client.get("/api/opportunities/coverage").json()
    assert coverage["counts"]["uiuc"] == 2


def test_release_record_gate_checks_canonical_and_legacy_type_fields():
    assert opportunity_visible_in_release({"opportunity_type": "research"})
    assert not opportunity_visible_in_release({"opportunity_type": "fellowship"})
    assert not opportunity_visible_in_release({"type": " Fellowship "})


def test_hidden_fellowship_id_is_rejected_by_tailor_and_all_cold_email_paths(
    monkeypatch,
):
    hidden = next(
        opportunity
        for opportunity in _fellowship_release_corpus()
        if opportunity["id"] == "fellowship-major-match"
    )
    lookup = {hidden["id"]: hidden}
    monkeypatch.setattr(tailor_module, "load_opportunities_by_id", lambda: lookup)
    monkeypatch.setattr(
        cold_email_module,
        "load_opportunities_by_id",
        lambda: lookup,
    )
    monkeypatch.setattr(cold_email_module, "is_configured", lambda: False)

    profile = {"name": "Release Contract Student", "major": "Computer Science"}
    tailor_response = client.post(
        "/api/tailor",
        json={
            "profile": profile,
            "opportunity_id": hidden["id"],
            "original_bullets": ["Built a machine learning classifier"],
        },
    )
    assert tailor_response.status_code == 404

    generation_payload = {
        "profile": profile,
        "opportunity_id": hidden["id"],
    }
    for path in (
        "/api/cold-email",
        "/api/cold-email/stream",
        "/api/cold-email/variants",
    ):
        response = client.post(path, json=generation_payload)
        assert response.status_code == 404, (path, response.text)

    refine_response = client.post(
        "/api/cold-email/refine",
        json={
            "current_body": "Dear Professor,",
            "instruction": "make it warmer",
            "profile": profile,
            "opportunity_id": hidden["id"],
        },
    )
    assert refine_response.status_code == 404


def test_hidden_fellowship_id_is_rejected_by_dormant_target_consumers(
    monkeypatch,
):
    hidden = next(
        opportunity
        for opportunity in _fellowship_release_corpus()
        if opportunity["id"] == "fellowship-major-match"
    )
    lookup = {hidden["id"]: hidden}
    monkeypatch.setattr(matches_module, "load_opportunities_by_id", lambda: lookup)
    monkeypatch.setattr(roadmap_module, "load_opportunities_by_id", lambda: lookup)

    with pytest.raises(HTTPException) as gaps_error:
        asyncio.run(
            matches_module.get_gap_analysis(hidden["id"], ProfileRequest())
        )
    assert gaps_error.value.status_code == 404

    with pytest.raises(HTTPException) as explain_error:
        asyncio.run(
            matches_module.get_match_explanation(
                hidden["id"],
                ProfileRequest(),
                llm=False,
            )
        )
    assert explain_error.value.status_code == 404

    roadmap = roadmap_module._prepare_roadmap_request({}, [hidden["id"]])
    assert roadmap["resolved_targets"] == 0
    assert roadmap["unresolved_targets"] == 1


def test_hidden_fellowship_id_is_rejected_if_ask_ai_is_later_enabled(
    monkeypatch,
):
    hidden = next(
        opportunity
        for opportunity in _fellowship_release_corpus()
        if opportunity["id"] == "fellowship-major-match"
    )
    monkeypatch.setattr(
        opportunities_module,
        "load_opportunities_by_id",
        lambda: {hidden["id"]: hidden},
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": b"",
        }
    )

    with pytest.raises(HTTPException) as chat_error:
        asyncio.run(
            opportunities_module.chat_with_opportunity(
                hidden["id"],
                opportunities_module.ChatRequest(message="Is this a fit?"),
                request,
            )
        )
    assert chat_error.value.status_code == 404


def _install_saved_search_release_stubs(monkeypatch, *, rows, patches, sends):
    class Response:
        status_code = 200
        text = ""

        def __init__(self, payload=None):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, _url, **_kwargs):
            return Response(rows)

        async def patch(self, url, **kwargs):
            patches.append({"url": url, **kwargs})
            return Response()

    async def record_send(**kwargs):
        sends.append(kwargs)

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(saved_searches_module, "_send_via_resend", record_send)
    for name, value in {
        "CRON_SECRET": "release-contract-cron",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-key",
        "RESEND_API_KEY": "resend-key",
        "RESEND_FROM_EMAIL": "from@example.com",
        "RESTORE_LINK_SECRET": "signing-key",
    }.items():
        monkeypatch.setenv(name, value)


def test_saved_search_refresh_never_writes_hidden_fellowship_ids(monkeypatch):
    corpus = _fellowship_release_corpus()
    hidden_id = "fellowship-major-match"
    stale_visible_id = "regular-record-temporarily-missing"
    row = {
        "id": "saved-search-release-contract",
        "filters_json": {},
        "query": "",
        "last_result_ids": [],
        "new_match_ids": [stale_visible_id, hidden_id],
    }
    patches: list[dict] = []
    sends: list[dict] = []
    _install_saved_search_release_stubs(
        monkeypatch,
        rows=[row],
        patches=patches,
        sends=sends,
    )
    monkeypatch.setattr(
        saved_searches_module,
        "load_opportunities",
        lambda: corpus,
    )

    response = client.get(
        "/api/cron/saved-searches/refresh",
        headers={"Authorization": "Bearer release-contract-cron"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert len(patches) == 1
    body = patches[0]["json"]
    assert hidden_id not in body["last_result_ids"]
    assert hidden_id not in body["new_match_ids"]
    assert stale_visible_id in body["new_match_ids"]
    assert set(body["last_result_ids"]) == {
        "regular-research",
        "regular-research-peer",
    }
    assert sends == []


def test_saved_search_digest_cleans_hidden_pending_id_without_sending(
    monkeypatch,
):
    corpus = _fellowship_release_corpus()
    hidden = next(
        opportunity
        for opportunity in corpus
        if opportunity["id"] == "fellowship-major-match"
    )
    row = {
        "id": "saved-search-release-contract",
        "name": "Hidden fellowship",
        "digest_email": "student@example.com",
        "new_match_ids": [hidden["id"]],
        "last_digest_sent_at": None,
    }
    patches: list[dict] = []
    sends: list[dict] = []
    _install_saved_search_release_stubs(
        monkeypatch,
        rows=[row],
        patches=patches,
        sends=sends,
    )
    monkeypatch.setattr(
        saved_searches_module,
        "load_opportunities",
        lambda: corpus,
    )

    response = client.get(
        "/api/cron/saved-searches/digest",
        headers={"Authorization": "Bearer release-contract-cron"},
    )

    assert response.status_code == 200
    assert response.json()["sent"] == 0
    assert response.json()["skipped"] == 1
    assert sends == []
    assert len(patches) == 1
    assert patches[0]["json"] == {"new_match_ids": []}


def test_hidden_fellowship_reminder_is_kept_but_never_sent(monkeypatch):
    hidden = next(
        opportunity
        for opportunity in _fellowship_release_corpus()
        if opportunity["id"] == "fellowship-major-match"
    )
    due = [{
        "device_id": "release-contract-device",
        "opportunity_id": hidden["id"],
        "remind_at": "2020-01-01",
        "interaction_type": "applied",
        "notes": "",
    }]
    requests: list[str] = []
    patches: list[dict] = []
    sends: list[dict] = []

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return due

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, url, **_kwargs):
            requests.append(url)
            return Response()

        async def patch(self, url, **kwargs):
            patches.append({"url": url, **kwargs})
            return Response()

    async def forbidden_send(*_args, **_kwargs):
        sends.append(_kwargs)
        raise AssertionError("hidden reminder must not be sent")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        push_module,
        "load_opportunities_by_id",
        lambda: {hidden["id"]: hidden},
    )
    monkeypatch.setattr(push_module, "send_webpush_safely", forbidden_send)
    monkeypatch.setattr(push_module, "_send_via_resend", forbidden_send)
    for name, value in {
        "CRON_SECRET": "release-contract-cron",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-key",
        "VAPID_PRIVATE_KEY": "private-key",
        "VAPID_PUBLIC_KEY": "public-key",
        "VAPID_SUBJECT": "mailto:ops@example.com",
        "RESEND_API_KEY": "resend-key",
        "RESEND_FROM_EMAIL": "from@example.com",
    }.items():
        monkeypatch.setenv(name, value)

    response = client.get(
        "/api/cron/reminders",
        headers={"Authorization": "Bearer release-contract-cron"},
    )

    assert response.status_code == 200
    assert response.json()["due"] == 1
    assert response.json()["skipped"] == 1
    assert response.json()["sent"] == 0
    assert response.json()["emailed"] == 0
    assert len(requests) == 1
    assert patches == []
    assert sends == []


def test_pre_llc_migration_revokes_direct_order_inserts():
    migration = (
        Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "024_disable_pre_llc_orders.sql"
    ).read_text()
    assert 'DROP POLICY IF EXISTS "orders_insert_own_pending"' in migration
    assert 'DROP POLICY IF EXISTS "orders_select_own"' in migration
    assert (
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE public.orders "
        "FROM anon, authenticated"
    ) in migration
    assert "public.waitlist" not in migration.lower()
