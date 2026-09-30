"""Similar-opportunity scans must leave unrelated HTTP requests responsive."""

from __future__ import annotations

import asyncio
import threading
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.lib import release_scope
from backend.main import app
from backend.routes import opportunities

RELEASE_CONTRACT_TESTS = True


def _record(opportunity_id: str, **overrides) -> dict:
    return {
        "id": opportunity_id,
        "title": "Synthetic research opportunity",
        "organization": "Example Lab",
        "source_type": "campus_program",
        "opportunity_type": "research",
        "keywords": ["machine learning"],
        "eligibility": {"majors": ["Computer Science"]},
        "application": {},
        "metadata": {"is_active": True},
        **overrides,
    }


@pytest.fixture
def corpus(monkeypatch):
    records = [
        _record("source", keywords=["machine learning", "systems"]),
        _record("z-peer"),
        _record("a-peer", contact_email="hidden@example.edu",
                description="Contact hidden@example.edu",
                application={"url": "mailto:hidden@example.edu"}),
        _record("best", keywords=["MACHINE LEARNING", "systems"],
                organization="Another Lab"),
        _record("type-only", keywords=[], organization="Another Lab", eligibility={}),
        _record("inactive", metadata={"is_active": False}),
        _record("closed", metadata={"is_active": True, "listing_status": "closed"}),
        _record("reference", metadata={"is_active": True, "reference_only": True}),
        _record("hidden", opportunity_type="fellowship"),
        _record("unreviewed", source_type="unknown_source"),
        _record("unrelated", keywords=[], opportunity_type="internship",
                organization="Another Lab", eligibility={}),
    ]
    monkeypatch.setattr(release_scope, "feature_enabled", lambda _feature: False)
    monkeypatch.setattr(opportunities, "load_opportunities", lambda: records)
    monkeypatch.setattr(
        opportunities, "load_opportunities_by_id",
        lambda: {record["id"]: record for record in records},
    )
    return records


def _assert_ranked_response(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_id"] == "source"
    assert body["total"] == 4
    assert [(row["id"], row["_similarity"]) for row in body["opportunities"]] == [
        ("best", 7.5), ("a-peer", 5.0), ("z-peer", 5.0),
    ]
    assert "hidden@example.edu" not in response.text
    assert "contact_email" not in body["opportunities"][1]


def test_similar_scan_keeps_health_and_detail_responsive(monkeypatch, corpus):
    """Hold corpus iteration, then exercise two real sibling HTTP handlers.

    The finite gate also bounds a regression: an event-loop scan times out the
    gate before either sibling can respond, so the ordering assertion fails.
    Filtering, scoring and redaction still use their production implementations.
    """
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original = deepcopy(corpus)

    def gated_records():
        started.set()
        release.wait(3.0)
        try:
            yield from corpus
        finally:
            finished.set()

    monkeypatch.setattr(opportunities, "load_opportunities", gated_records)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            similar = asyncio.create_task(
                client.get("/api/opportunities/source/similar?limit=3"),
            )
            try:
                async def wait_started():
                    while not started.is_set():
                        await asyncio.sleep(0.005)

                await asyncio.wait_for(wait_started(), timeout=5.0)
                health, detail = await asyncio.wait_for(
                    asyncio.gather(
                        client.get("/api/health"),
                        client.get("/api/opportunities/source"),
                    ),
                    timeout=1.0,
                )
                assert health.status_code == 200
                assert health.json()["status"] == "ok"
                assert detail.status_code == 200
                assert detail.json()["id"] == "source"
                assert not finished.is_set(), (
                    "health/detail only responded after the similar scan finished"
                )
                assert not similar.done()
            finally:
                release.set()
                response = await similar
            _assert_ranked_response(response)

    asyncio.run(probe())
    assert finished.is_set()
    assert corpus == original, "public projection must not mutate cached records"


@pytest.mark.parametrize(("path", "status"), [
    ("/api/opportunities/missing/similar", 404),
    ("/api/opportunities/hidden/similar", 404),
    (f"/api/opportunities/{'x' * 101}/similar", 400),
    ("/api/opportunities/source/similar?limit=0", 422),
    ("/api/opportunities/source/similar?limit=-1", 422),
    ("/api/opportunities/source/similar?limit=21", 422),
    ("/api/opportunities/source/similar?limit=invalid", 422),
])
def test_similar_refuses_invalid_requests_before_corpus_scan(monkeypatch, corpus, path, status):
    def unexpected_scan():
        raise AssertionError("refused requests must not scan the corpus")

    monkeypatch.setattr(opportunities, "load_opportunities", unexpected_scan)
    assert TestClient(app).get(path).status_code == status
