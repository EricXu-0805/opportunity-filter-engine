"""Similar-opportunity scans must leave unrelated HTTP requests responsive."""

from __future__ import annotations

import asyncio
import json
import os
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
    monkeypatch.setattr(opportunities, "load_indexed_opportunities",
                        lambda: (records, opportunities.load_opportunities_by_id()))
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


def test_another_detail_reuses_match_candidates_until_release_changes(monkeypatch, corpus):
    from backend.routes import matches

    monkeypatch.setattr(matches, "_active_corpus_identity", id(corpus))
    monkeypatch.setattr(matches, "_match_universe", None)
    monkeypatch.setattr(matches, "_project_cutoffs", ())
    scanned = []
    original_filter = matches.actionable_opportunities

    def count_scan(records):
        scanned.append(len(records))
        return original_filter(records)

    monkeypatch.setattr(matches, "actionable_opportunities", count_scan)
    client = TestClient(app)
    matches.release_actionable_corpus(corpus)
    _assert_ranked_response(client.get("/api/opportunities/source/similar?limit=3"))
    assert client.get("/api/opportunities/best/similar?limit=3").status_code == 200
    assert len(scanned) == 1

    monkeypatch.setattr(release_scope, "feature_enabled", lambda _feature: True)
    released = client.get("/api/opportunities/source/similar?limit=20").json()
    assert "hidden" in {row["id"] for row in released["opportunities"]}
    assert len(scanned) == 2


def test_similar_keeps_source_and_candidates_together_during_hot_reload(monkeypatch, tmp_path):
    from backend import data_loader

    monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_loader, "_opp_cache", [])
    monkeypatch.setattr(data_loader, "_opp_cache_by_id", {})
    monkeypatch.setattr(data_loader, "_opp_cache_mtime", 0)
    monkeypatch.setattr(data_loader, "_opp_cache_generation", 0)
    # Each file passes the normal canonicalizer and publishes a new list/index.
    # Leave the process-wide matching model used by other tests in place.
    monkeypatch.setattr(data_loader, "_prepare_ranker_corpus", lambda _rows, _mtime: None)
    monkeypatch.setattr(data_loader, "_publish_hooks", [])
    path = tmp_path / "opportunities.json"

    def publish(ids, stamp):
        candidate = tmp_path / "candidate.json"
        candidate.write_text(json.dumps([_record(row_id) for row_id in ids]))
        os.utime(candidate, (stamp, stamp))
        candidate.replace(path)
        return data_loader.load_opportunities()

    publish(["source", "old-peer"], 100)
    original_resolve = opportunities.release_visible_opportunity_by_id

    def resolve_then_reload(lookup, row_id):
        source = original_resolve(lookup, row_id)
        assert source and source["id"] == "source"
        assert [r["id"] for r in publish(["new-peer"], 101)] == ["new-peer"]
        return source

    monkeypatch.setattr(opportunities, "release_visible_opportunity_by_id", resolve_then_reload)
    response = TestClient(app).get("/api/opportunities/source/similar?limit=3")
    assert response.status_code == 200
    assert [r["id"] for r in response.json()["opportunities"]] == ["old-peer"]
    monkeypatch.setattr(opportunities, "release_visible_opportunity_by_id", original_resolve)
    assert TestClient(app).get("/api/opportunities/source/similar?limit=3").status_code == 404


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

    monkeypatch.setattr(opportunities, "load_indexed_opportunities",
                        lambda: (gated_records(), opportunities.load_opportunities_by_id()))

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
    def unexpected_scan(_rows):
        raise AssertionError("refused requests must not scan the corpus")

    monkeypatch.setattr(opportunities, "release_actionable_corpus", unexpected_scan)
    assert TestClient(app).get(path).status_code == status
