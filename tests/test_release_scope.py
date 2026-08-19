from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend import main as main_module
from backend.lib import release_scope as release_scope_module
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
from src.matcher.ranker import MatchResult, RankedMatchUniverse

RELEASE_CONTRACT_TESTS = True

client = TestClient(app)

@pytest.fixture
def scope_closed(monkeypatch):
    """Drive the gate from an explicitly closed feature.

    Every assertion below is about what the release gate DOES to a feature that
    has not been accepted — routes 404 before the handler, hidden records never
    reach ranking, discovery, cold email, saved searches or reminders. That is a
    property of the gate, not of which features happen to be closed this week,
    and reading the live table made all of it evaporate the moment a feature
    shipped. (Same defect as the release-gate test in #736: a test pinning a
    state instead of a behaviour.)

    `payments` is closed today and these paths still guard it, but the point is
    that the next feature to ship closed inherits the identical protection
    without anyone rewriting this file.
    """
    monkeypatch.setattr(main_module, "feature_enabled", lambda _feature: False)
    monkeypatch.setattr(matches_module, "feature_enabled", lambda _feature: False)
    monkeypatch.setattr(
        release_scope_module, "feature_enabled", lambda _feature: False,
    )




ACCEPTED_FEATURES = frozenset({
    "cross_school_matching",
})
UNACCEPTED_FEATURES = frozenset({
    "match_ai_refine",
    "compare",
    "fellowships",
    "resume_renovate",
    "roadmap",
    "ask_ai",
    "professor_signals",
    "payments",
    "microsoft_school_auth",
    "concierge_pay_qr",
})


def test_the_release_table_is_exactly_what_was_accepted():
    """The table itself, stated once, so a flip is never a silent side effect.

    Every other test in this file asks what the gate DOES; this one is the only
    place that records WHICH features are through it. Flipping a switch without
    editing this list fails here, which is the review the module docstring in
    backend/lib/release_scope.py asks for.
    """
    assert set(RELEASE_SCOPE) == ACCEPTED_FEATURES | UNACCEPTED_FEATURES
    assert {f for f, v in RELEASE_SCOPE.items() if v} == ACCEPTED_FEATURES
    assert {f for f, v in RELEASE_SCOPE.items() if not v} == UNACCEPTED_FEATURES


def test_unaccepted_server_features_fail_closed(monkeypatch):
    """A runtime variable can disable an accepted feature, never promote one."""
    monkeypatch.setenv("OFE_PAYMENTS_ENABLED", "true")

    for feature in UNACCEPTED_FEATURES:
        assert RELEASE_SCOPE[feature] is False
        assert feature_enabled(feature) is False


def test_an_accepted_feature_still_has_its_runtime_kill_switch(monkeypatch):
    """Acceptance is not the same as "always on".

    payments carries OFE_PAYMENTS_ENABLED so an incident can turn it off
    without a deploy. Proven against a feature that IS accepted, so the
    mechanism is exercised rather than short-circuited by the source flag.
    """
    from types import MappingProxyType

    from backend.lib import release_scope as rs

    monkeypatch.setattr(
        rs, "RELEASE_SCOPE", MappingProxyType({**rs.RELEASE_SCOPE, "payments": True}),
    )
    monkeypatch.setenv("OFE_PAYMENTS_ENABLED", "")
    assert rs.feature_enabled("payments") is False
    monkeypatch.setenv("OFE_PAYMENTS_ENABLED", "1")
    assert rs.feature_enabled("payments") is True


class TestUnacceptedSignInDoorsAreRefusedServerSide:
    """Hiding the Microsoft button never closed the Microsoft door.

    The azure provider is enabled on the Supabase project and reachable at
    /auth/v1/authorize?provider=azure without touching this app's UI — one real
    third-party account was created that way. So the flag has to be enforced
    where the session is spent, not only where the button is drawn.
    """

    def test_a_session_minted_through_an_unaccepted_provider_is_refused(self):
        from backend.lib.release_scope import session_provider_accepted

        assert session_provider_accepted(
            {"id": "u1", "app_metadata": {"provider": "azure"}}
        ) is False

    def test_accepted_providers_and_shapes_without_one_still_pass(self):
        from backend.lib.release_scope import session_provider_accepted

        for user in (
            {"id": "u1", "app_metadata": {"provider": "google"}},
            {"id": "u1", "app_metadata": {"provider": "email"}},
            {"id": "u1", "app_metadata": {}},
            {"id": "u1"},
        ):
            assert session_provider_accepted(user) is True

    def test_the_refusal_follows_the_flag_rather_than_the_provider_name(
        self, monkeypatch,
    ):
        """Accepting microsoft_school_auth is the only thing that opens it."""
        from types import MappingProxyType

        from backend.lib import release_scope as rs

        monkeypatch.setattr(
            rs, "RELEASE_SCOPE",
            MappingProxyType({**rs.RELEASE_SCOPE, "microsoft_school_auth": True}),
        )
        assert rs.session_provider_accepted(
            {"id": "u1", "app_metadata": {"provider": "azure"}}
        ) is True


class TestTheQrChannelIsGatedWhereOrdersAreMinted:
    """concierge_pay_qr has its own prerequisite: a confirmed receiving account.

    Switching `payments` on first must not start minting manual orders against
    an account nobody has confirmed, so the gate lives on the channel and not
    only on the route.
    """

    def test_manual_orders_are_refused_while_the_qr_is_unaccepted(self):
        import pytest as _pytest

        from backend.lib import payments

        with _pytest.raises(NotImplementedError, match="concierge_pay_qr"):
            payments.create_order(
                "manual", device_id="d", package="single_email", amount_cents=990,
            )

    def test_accepting_the_qr_lets_the_manual_channel_work(self, monkeypatch):
        from types import MappingProxyType

        from backend.lib import payments
        from backend.lib import release_scope as rs

        monkeypatch.setattr(
            rs, "RELEASE_SCOPE",
            MappingProxyType({**rs.RELEASE_SCOPE, "concierge_pay_qr": True}),
        )
        row = payments.create_order(
            "manual", device_id="d", package="single_email", amount_cents=990,
        )
        assert row["status"] == "pending"
        assert row["channel"] == "manual"


def test_cross_school_profile_flag_fails_closed_at_match_boundary(scope_closed):
    profile = ProfileRequest(
        home_school="uiuc",
        include_cross_school=True,
    )

    normalized = matches_module._normalized_profile(profile)

    # The boundary strips the preference rather than trusting the UI to hide the
    # selector: a profile saved while the feature was open still arrives with
    # the flag set after it closes again.
    assert normalized["include_cross_school"] is False


def test_unaccepted_routes_return_404_before_any_handler(scope_closed):
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


def test_frozen_routes_bypass_rate_buckets_but_keep_security_headers(scope_closed, monkeypatch):
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


def test_match_ai_query_is_not_billable_while_refine_is_unaccepted(scope_closed):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": b"llm=true",
        }
    )
    assert main_module._billable_class(request, "/api/matches") is None


def _release_contract_snapshot(
    *,
    opportunity: dict | None = None,
) -> matches_module._MatchSnapshot:
    visible: list[MatchResult] = []
    opportunities_by_id: dict[str, dict] = {}
    if opportunity is not None:
        visible = [
            MatchResult(
                opportunity_id=opportunity["id"],
                eligibility_score=70,
                readiness_score=70,
                upside_score=70,
                final_score=70,
                bucket="good_match",
                reasons_fit=["Research interests align"],
                reasons_gap=["Verify details"],
                next_steps=["Review details"],
            )
        ]
        opportunities_by_id = {opportunity["id"]: opportunity}
    return matches_module._MatchSnapshot(
        created_at=0,
        corpus_identity=1,
        result_set_id="release-contract-snapshot",
        visible=visible,
        by_id={result.opportunity_id: result for result in visible},
        opportunities_by_id=opportunities_by_id,
        buckets={
            "high_priority": 0,
            "good_match": len(visible),
            "reach": 0,
            "low_fit": 0,
        },
        field_relevant_count=len(visible),
    )


def test_match_ai_query_reaches_only_the_deterministic_snapshot(monkeypatch):
    seen_modes: list[bool] = []

    async def snapshot(_profile, llm):
        seen_modes.append(llm)
        return _release_contract_snapshot()

    monkeypatch.setattr(matches_module, "_get_or_compute_snapshot", snapshot)
    monkeypatch.setattr(
        matches_module,
        "llm_rerank",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("AI rerank must stay unreachable")
        ),
    )

    response = client.post("/api/matches?llm=true", json={})
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert seen_modes == [False]


def test_hidden_compare_explain_route_never_reaches_snapshot_or_ai(monkeypatch):
    opportunity = {
        "id": "release-contract-opp",
        "title": "Confirmed program listing",
        "organization": "Test University",
        "source_type": "campus_program",
        "opportunity_type": "research",
        "paid": "unknown",
        "on_campus": None,
        "location": "Test City",
        "keywords": ["robotics"],
        "eligibility": {},
        "application": {},
        "metadata": {"is_active": True},
    }
    seen_modes: list[bool] = []

    async def snapshot(_profile, llm):
        seen_modes.append(llm)
        return _release_contract_snapshot(opportunity=opportunity)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("closed AI explain path was reached")

    monkeypatch.setattr(matches_module, "load_opportunities_by_id", lambda: {
        opportunity["id"]: opportunity,
    })
    monkeypatch.setattr(matches_module, "_get_or_compute_snapshot", snapshot)
    monkeypatch.setattr(matches_module, "_explain_cache_get", forbidden)
    monkeypatch.setattr(matches_module, "_llm_explanation", forbidden)

    response = client.post(
        f"/api/matches/{opportunity['id']}/explain?llm=true",
        json={},
    )
    assert response.status_code == 404
    assert seen_modes == []


def test_hidden_professor_signals_never_reach_match_ranking(scope_closed, monkeypatch):
    async def forbidden_signals_map():
        raise AssertionError("hidden professor signals were fetched")

    monkeypatch.setattr(matches_module, "signals_map", forbidden_signals_map)
    assert asyncio.run(matches_module._responsiveness_for_matching()) is None


def test_hidden_professor_signals_never_leave_public_opportunity_surfaces(monkeypatch):
    opportunity = {
        "id": "faculty-release-contract",
        "title": "Faculty contact profile",
        "organization": "Example University",
        "source_type": "faculty_research",
        "opportunity_type": "research",
        "pi_name": "Jane Doe",
        "professor_id": "poisoned-stale-professor-id",
        "description": "Faculty research profile.",
        "keywords": ["robotics"],
        "eligibility": {},
        "application": {},
        "metadata": {"is_active": True, "school": "uiuc"},
    }
    peer = {
        **opportunity,
        "id": "faculty-release-contract-peer",
        "pi_name": "Alex Doe",
        "professor_id": "second-poisoned-stale-professor-id",
    }
    derived_id = "prof:v1:uiuc:0123456789abcdef0123"
    corpus = [opportunity, peer]
    monkeypatch.setattr(
        opportunities_module,
        "load_opportunities_by_id",
        lambda: {item["id"]: item for item in corpus},
    )
    monkeypatch.setattr(
        opportunities_module,
        "load_opportunities",
        lambda: corpus,
    )
    monkeypatch.setattr(
        opportunities_module,
        "canonical_professor_id",
        lambda _opportunity: derived_id,
    )

    monkeypatch.setattr(
        opportunities_module,
        "feature_enabled",
        lambda _feature: False,
    )
    hidden = client.get(f"/api/opportunities/{opportunity['id']}")
    assert hidden.status_code == 200
    assert "professor_id" not in hidden.json()

    listed = client.get("/api/opportunities?limit=10")
    assert listed.status_code == 200
    assert all(
        "professor_id" not in item
        for item in listed.json()["opportunities"]
    )

    batched = client.post(
        "/api/opportunities/batch",
        json={"ids": [opportunity["id"], peer["id"]]},
    )
    assert batched.status_code == 200
    assert all(
        "professor_id" not in item
        for item in batched.json()["opportunities"]
    )

    similar = client.get(f"/api/opportunities/{opportunity['id']}/similar")
    assert similar.status_code == 200
    assert similar.json()["opportunities"]
    assert all(
        "professor_id" not in item
        for item in similar.json()["opportunities"]
    )

    monkeypatch.setattr(
        opportunities_module,
        "feature_enabled",
        lambda feature: feature == "professor_signals",
    )
    accepted = client.get(f"/api/opportunities/{opportunity['id']}")
    assert accepted.status_code == 200
    assert accepted.json()["professor_id"] == derived_id


def test_hidden_fellowship_preference_is_removed_server_side(scope_closed):
    profile = ProfileRequest(
        seeking_type=["fellowship", " Fellowship ", "FELLOWSHIP"],
    )
    normalized = matches_module._normalized_profile(profile)
    assert normalized["seeking_type"] == ["research", "summer_program"]

    mixed = ProfileRequest(
        seeking_type=["research", " Fellowship ", "summer_program"],
    )
    assert matches_module._normalized_profile(mixed)["seeking_type"] == [
        "research",
        "summer_program",
    ]


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


def test_hidden_fellowship_records_never_enter_match_ranking(scope_closed, monkeypatch):
    corpus = _fellowship_release_corpus()
    lookup = {opportunity["id"]: opportunity for opportunity in corpus}
    ranked_ids: list[str] = []

    def rank_every_received_record(_profile, opportunities, **_kwargs):
        ranked_ids.extend(opportunity["id"] for opportunity in opportunities)
        visible = [
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
        return RankedMatchUniverse(
            visible=visible,
            buckets={
                "high_priority": 0,
                "good_match": len(visible),
                "reach": 0,
                "low_fit": 0,
            },
            field_relevant_count=0,
        )

    monkeypatch.setattr(
        matches_module,
        "load_opportunities_generation",
        lambda: (corpus, "release-scope-fixture"),
    )
    monkeypatch.setattr(
        matches_module,
        "registered_corpus_identity_nowait",
        lambda: id(corpus),
    )
    monkeypatch.setattr(
        matches_module,
        "registered_corpus_identity",
        lambda: id(corpus),
    )
    monkeypatch.setattr(matches_module, "load_opportunities_by_id", lambda: lookup)
    monkeypatch.setattr(
        matches_module,
        "rank_visible_universe",
        rank_every_received_record,
    )
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


def test_hidden_fellowship_records_never_leave_discovery_apis(scope_closed, monkeypatch):
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


def test_release_record_gate_checks_canonical_and_legacy_type_fields(scope_closed):
    assert opportunity_visible_in_release({"opportunity_type": "research"})
    assert not opportunity_visible_in_release({"opportunity_type": "fellowship"})
    assert not opportunity_visible_in_release({"type": " Fellowship "})


def test_hidden_fellowship_id_is_rejected_by_tailor_and_all_cold_email_paths(scope_closed, monkeypatch,):
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


def test_hidden_fellowship_id_is_rejected_by_dormant_target_consumers(scope_closed, monkeypatch,):
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
                Request({"type": "http", "method": "POST", "headers": []}),
                hidden["id"],
                ProfileRequest(),
                llm=False,
            )
        )
    assert explain_error.value.status_code == 404

    roadmap = roadmap_module._prepare_roadmap_request({}, [hidden["id"]])
    assert roadmap["resolved_targets"] == 0
    assert roadmap["unresolved_targets"] == 1


def test_hidden_fellowship_id_is_rejected_if_ask_ai_is_later_enabled(scope_closed, monkeypatch,):
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


def test_saved_search_refresh_never_writes_hidden_fellowship_ids(scope_closed, monkeypatch):
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


def test_saved_search_digest_cleans_hidden_pending_id_without_sending(scope_closed, monkeypatch,):
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


@pytest.mark.parametrize("target_state", ["known_hidden", "unknown"])
def test_unprovable_reminder_is_kept_but_never_sent(
    scope_closed,
    monkeypatch,
    target_state,
):
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
        lambda: (
            {hidden["id"]: hidden}
            if target_state == "known_hidden"
            else {}
        ),
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
        / "026_disable_pre_llc_orders.sql"
    ).read_text()
    assert 'DROP POLICY IF EXISTS "orders_insert_own_pending"' in migration
    assert 'DROP POLICY IF EXISTS "orders_select_own"' in migration
    assert (
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE public.orders "
        "FROM anon, authenticated"
    ) in migration
    assert "public.waitlist" not in migration.lower()


def test_hidden_mtp_migration_closes_browser_data_api_and_preserves_server():
    migration = (
        Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "20260819164641_disable_unaccepted_mtp_data_api.sql"
    ).read_text()
    normalized = " ".join(migration.split())
    policies = {
        "resume_renovations": (
            "resume_renovations_select_own",
            "resume_renovations_insert_own",
            "resume_renovations_update_own",
            "resume_renovations_delete_own",
        ),
        "resume_renovation_versions": (
            "resume_renovation_versions_select_own",
            "resume_renovation_versions_insert_own",
        ),
        "professor_follows": (
            "professor_follows_select_own",
            "professor_follows_insert_own",
            "professor_follows_delete_own",
        ),
        "professor_update_reads": (
            "professor_update_reads_select_own",
            "professor_update_reads_insert_own",
            "professor_update_reads_update_own",
        ),
    }
    for table, names in policies.items():
        for name in names:
            assert (
                f'DROP POLICY IF EXISTS "{name}" ON public.{table}'
                in normalized
            )

    tables = (
        "public.resume_renovations, public.resume_renovation_versions, "
        "public.professor_follows, public.professor_update_reads"
    )
    assert (
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {tables} "
        "FROM PUBLIC, anon, authenticated"
    ) in normalized
    assert (
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tables} "
        "TO service_role"
    ) in normalized
    assert "DROP TABLE" not in normalized.upper()
