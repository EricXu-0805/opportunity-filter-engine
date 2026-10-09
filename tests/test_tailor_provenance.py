"""Request-time Tailor rule binding; all provider calls are prohibited or stubbed."""

from collections import defaultdict
from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import tailor

client = TestClient(app)
TARGET = {
    "id": "provenance-target", "title": "Student research", "source_type": "manual",
    "description_clean": "Build sensors", "metadata": {"listing_status": "open"},
}
BULLET = "Built a thermal sensor and wrote a lab report"


@pytest.fixture(autouse=True)
def safe_backend(monkeypatch):
    monkeypatch.setattr(tailor, "load_opportunities_by_id", lambda: {TARGET["id"]: TARGET})
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    monkeypatch.setattr(tailor, "chat_completion", Mock(side_effect=AssertionError("no provider allowed")))


def payload(path, expected=None):
    body = ({"profile": {}, "opportunity_id": TARGET["id"], "original_bullets": [BULLET]}
            if path == "/api/tailor" else {"resume_text": "• " + BULLET})
    if expected is not None:
        body["expected_pipeline_version"] = expected
    return body


def assert_stamp(body, version):
    assert body["pipeline_version"] == version
    assert datetime.fromisoformat(body["generated_at"]).tzinfo is not None


def test_status_exposes_only_authoritative_code_version_and_availability():
    response = client.get("/api/tailor/status")
    assert response.status_code == 200
    assert response.json() == {"ai_available": False, "pipeline_version": tailor.TAILOR_PIPELINE_VERSION}


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/extract-bullets"])
def test_status_then_deploy_refuses_before_loader_or_provider(path, monkeypatch):
    observed = client.get("/api/tailor/status").json().get("pipeline_version", "old-version")
    monkeypatch.setattr(tailor, "TAILOR_PIPELINE_VERSION", "new-version")
    lookup = Mock(return_value={TARGET["id"]: TARGET})
    configured = Mock(return_value=False)
    monkeypatch.setattr(tailor, "load_opportunities_by_id", lookup)
    monkeypatch.setattr(tailor, "is_configured", configured)
    response = client.post(path, json=payload(path, observed))
    assert response.status_code == 409
    assert response.json() == {"detail": {
        "code": "TAILOR_PIPELINE_CHANGED",
        "message": "Tailoring rules changed. Check again before continuing.",
        "retryable": False, "pipeline_version": "new-version",
    }}
    lookup.assert_not_called()
    configured.assert_not_called()
    tailor.chat_completion.assert_not_called()
    # The rate limiter consumes the internal no-work marker rather than publishing it.
    assert "X-Refused-Before-Work" not in response.headers


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/extract-bullets"])
@pytest.mark.parametrize("invalid", ["", " ", "w13.2\n", "版本1", "v\x00", "x" * 81, 1, True, [], {}])
def test_bad_expected_version_is_rejected_without_work(path, invalid, monkeypatch):
    configured = Mock(return_value=False)
    monkeypatch.setattr(tailor, "is_configured", configured)
    response = client.post(path, json=payload(path, invalid))
    assert response.status_code == 422
    configured.assert_not_called()
    tailor.chat_completion.assert_not_called()


@pytest.mark.parametrize("expected", [None, "current-version"])
@pytest.mark.parametrize("branch", ["empty", "no-provider", "invalid-output", "rejected", "ai"])
def test_every_tailor_branch_stamps_actual_rules_and_target(expected, branch, monkeypatch):
    monkeypatch.setattr(tailor, "TAILOR_PIPELINE_VERSION", "current-version")
    body = payload("/api/tailor", expected)
    if branch == "empty":
        body["original_bullets"] = []
    elif branch not in {"no-provider"}:
        monkeypatch.setattr(tailor, "is_configured", lambda: True)
        text = "Implemented PyTorch and Kubernetes" if branch == "rejected" else None
        row = {"unit_id": "b1", "links": [], "decision": "rewrite" if text else "keep",
               "ops": [{"op": "verb_first"}] if text else [], "text": text, "keep_reason": None if text else "no_link"}
        monkeypatch.setattr(tailor, "_ai_tailor_bullets",
                            lambda *a, **kw: None if branch == "invalid-output" else {"b1": row})
    response = client.post("/api/tailor", json=body)
    assert response.status_code == 200
    data = response.json()
    assert_stamp(data, "current-version")
    assert data["opportunity_id"] == TARGET["id"]
    assert data["method"] == ("ai" if branch in {"ai", "rejected"} else "fallback")
    # Every submitted bullet comes back, as written unless a reviewed rewrite replaced it.
    assert [b["text"] for b in data["tailored_bullets"]] == ([] if branch == "empty" else [BULLET])


@pytest.mark.parametrize("expected", [None, "current-version"])
@pytest.mark.parametrize("branch", ["empty", "heuristic", "ai", "mixed"])
def test_extract_stamps_all_processing_paths(expected, branch, monkeypatch):
    monkeypatch.setattr(tailor, "TAILOR_PIPELINE_VERSION", "current-version")
    body = payload("/api/tailor/extract-bullets", expected)
    if branch == "empty":
        body["resume_text"] = "   "
    elif branch in {"ai", "mixed"}:
        monkeypatch.setattr(tailor, "is_configured", lambda: True)
        monkeypatch.setattr(tailor.llm_budget, "exhausted", lambda: False)
        monkeypatch.setattr(tailor, "_ai_extract_bullets", lambda text: [BULLET] if BULLET in text else None)
        if branch == "mixed":
            body["resume_text"] += "\n" + "padding " * 1200
    response = client.post("/api/tailor/extract-bullets", json=body)
    assert response.status_code == 200
    data = response.json()
    assert_stamp(data, "current-version")
    assert data["method"] == ("heuristic" if branch == "empty" else branch)
    assert data["bullets"] == ([] if branch == "empty" else [BULLET])


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/extract-bullets"])
def test_async_processing_cannot_stamp_later_version(path, monkeypatch):
    before = tailor.TAILOR_PIPELINE_VERSION
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor.llm_budget, "exhausted", lambda: False)

    def finish(*args, **kwargs):
        monkeypatch.setattr(tailor, "TAILOR_PIPELINE_VERSION", "changed-during-work")
        return {} if path == "/api/tailor" else [BULLET]

    monkeypatch.setattr(tailor, "_ai_tailor_bullets" if path == "/api/tailor" else "_ai_extract_bullets", finish)
    response = client.post(path, json=payload(path, before))
    assert response.status_code == 200
    assert_stamp(response.json(), before)


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/extract-bullets"])
def test_optional_null_version_preserves_legacy_requests(path):
    body = payload(path)
    body["expected_pipeline_version"] = None
    response = client.post(path, json=body)
    assert response.status_code == 200
    assert_stamp(response.json(), tailor.TAILOR_PIPELINE_VERSION)


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/extract-bullets"])
def test_version_refusal_refunds_global_spend_slot_but_counts_arrival(path, monkeypatch):
    from backend import main

    monkeypatch.setattr(main, "RATE_LIMIT_DISABLED", False)
    monkeypatch.setattr(main, "_rate_buckets", defaultdict(list))
    monkeypatch.setattr(main, "_global_buckets", defaultdict(list))
    monkeypatch.setattr(main, "_last_purge", 0.0)
    monkeypatch.setattr(main, "GLOBAL_LLM_PER_MIN", 1)
    monkeypatch.setattr(main.llm_budget, "exhausted", lambda: False)
    for _ in range(2):
        response = client.post(path, json=payload(path, "old-version"))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "TAILOR_PIPELINE_CHANGED"
        assert main._global_buckets["llm"] == []
    assert sum(len(bucket) for bucket in main._rate_buckets.values()) == 2
    tailor.chat_completion.assert_not_called()
