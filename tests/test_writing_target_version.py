"""Tailor consumes exactly the anonymous public snapshot whose version it echoes."""
import hashlib
import json
import re
from collections import defaultdict
from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import opportunities, tailor

client = TestClient(app)
BULLET = "Built a thermal sensor and wrote a lab report"
TOKEN = re.compile(r"wt1:[0-9a-f]{64}\Z")


@pytest.fixture(autouse=True)
def corpus(monkeypatch):
    record = {
        "id": "writing-target", "title": "Sensor research", "organization": "Example University",
        "source_type": "manual", "opportunity_type": "research", "description_clean": "Build sensors",
        "eligibility": {"skills_required": ["Python"], "preferred_year": ["Junior", "Senior"], "min_gpa": 3.2},
        "application": {"requires_resume": "yes", "contact_method": "email"},
        "metadata": {"listing_status": "open", "confidence_score": 0.8},
        "contact_email": "private@example.edu", "pi_email": "hidden@example.edu",
    }
    rows = {record["id"]: record}
    monkeypatch.setattr(opportunities, "load_opportunities_by_id", lambda: rows)
    monkeypatch.setattr(tailor, "load_opportunities_by_id", lambda: rows)
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    monkeypatch.setattr(tailor, "chat_completion", Mock(side_effect=AssertionError("provider forbidden")))
    async def no_auth(_value):
        return None
    monkeypatch.setattr(opportunities, "authenticated_uid", no_auth)
    return rows, record


def detail():
    response = client.get("/api/opportunities/writing-target", params={"_release_scope": opportunities.CURRENT_TRUTH_AWARE_SCOPE})
    assert response.status_code == 200
    return response.json()


def body(version=None):
    result = {"profile": {}, "opportunity_id": "writing-target", "original_bullets": [BULLET]}
    if version is not None:
        result["expected_target_version"] = version
    return result


def canonical_token(public):
    fields = {key: value for key, value in public.items()
              if key not in {"writing_target_version", "contact_email_status", "detail_fields", "contact_email", "pi_email", "professor_id"}}
    encoded = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "wt1:" + hashlib.sha256(encoded).hexdigest()


def test_anonymous_detail_token_matches_exact_public_json_and_tailor_receipt(corpus):
    public = detail()
    assert TOKEN.fullmatch(public.get("writing_target_version", ""))
    assert public["writing_target_version"] == canonical_token(public)
    assert "private@example.edu" not in json.dumps(public)
    response = client.post("/api/tailor", json=body(public["writing_target_version"]))
    assert response.status_code == 200
    assert response.json()["target_version"] == public["writing_target_version"]


@pytest.mark.parametrize("value", [None, "omitted"])
def test_legacy_requests_are_explicitly_compatible_and_still_stamped(value):
    request = body()
    if value is None:
        request["expected_target_version"] = None
    response = client.post("/api/tailor", json=request)
    assert response.status_code == 200
    assert response.json()["target_version"] == detail()["writing_target_version"]


@pytest.mark.parametrize("invalid", ["", "wt1:" + "A" * 64, "wt1:" + "a" * 63, "wt2:" + "a" * 64,
                                     "wt1:" + "a" * 64 + "\n", "版本", 3, True, [], {}])
def test_malformed_expected_token_is_rejected_before_work(invalid, monkeypatch):
    lookup = Mock(side_effect=AssertionError("lookup must not happen"))
    monkeypatch.setattr(tailor, "load_opportunities_by_id", lookup)
    response = client.post("/api/tailor", json=body(invalid))
    assert response.status_code == 422
    lookup.assert_not_called()
    tailor.chat_completion.assert_not_called()


@pytest.mark.parametrize("change", ["description", "nested", "deadline", "new-field", "array-order", "null"])
def test_same_id_public_changes_refuse_before_generation(change, corpus, monkeypatch):
    old = detail()["writing_target_version"]
    _rows, record = corpus
    if change == "description": record["description_clean"] = "A changed focus"
    elif change == "nested": record["eligibility"]["skills_required"].append("R")
    elif change == "deadline": record["deadline"] = "2027-04-01"
    elif change == "new-field": record["new_public_terms"] = {"中文": ["尾项 🧪", None]}
    elif change == "array-order": record["eligibility"]["preferred_year"].reverse()
    else: record["remote_option"] = None
    configured = Mock(side_effect=AssertionError("no generation work"))
    monkeypatch.setattr(tailor, "is_configured", configured)
    response = client.post("/api/tailor", json=body(old))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "WRITING_TARGET_CHANGED",
        "message": "This opportunity changed. Check it again before continuing.", "retryable": False}
    assert "X-Refused-Before-Work" not in response.headers
    configured.assert_not_called()
    assert detail()["writing_target_version"] != old


def test_object_key_order_changes_do_not_change_the_version(corpus):
    old = detail()["writing_target_version"]
    rows, record = corpus
    reordered = {key: ({k: value[k] for k in reversed(value)} if isinstance(value, dict) else value)
                 for key, value in reversed(list(record.items()))}
    rows[record["id"]] = reordered
    assert detail()["writing_target_version"] == old
    assert client.post("/api/tailor", json=body(old)).status_code == 200


def test_private_contact_and_auth_reveal_metadata_never_enter_token(corpus, monkeypatch):
    old = detail()["writing_target_version"]
    _rows, record = corpus
    record.update(contact_email="different-private@example.edu", pi_email="another-private@example.edu",
                  contact_email_status="revealed", writing_target_version="poisoned", professor_id="internal-tracking")
    assert detail()["writing_target_version"] == old
    async def signed_in(_value): return "signed-in-owner"
    monkeypatch.setattr(opportunities, "authenticated_uid", signed_in)
    monkeypatch.setattr(opportunities, "contact_email_status", lambda *args, **kwargs: ("revealed", "different-private@example.edu"))
    revealed = client.get("/api/opportunities/writing-target", headers={"Authorization": "Bearer fake"}).json()
    assert revealed["contact_email"] == "different-private@example.edu"
    assert revealed["writing_target_version"] == old


def test_recursive_redaction_precedes_hash_and_does_not_reveal_a_changed_private_address(corpus):
    _rows, record = corpus
    record["description_clean"] = "Build sensors; email first-private@example.edu"
    record["metadata"]["nested"] = {"note": "Contact first-private@example.edu"}
    old = detail()["writing_target_version"]
    record["description_clean"] = "Build sensors; email second-private@example.edu"
    record["metadata"]["nested"]["note"] = "Contact second-private@example.edu"
    updated = detail()
    assert updated["writing_target_version"] == old
    assert "first-private" not in json.dumps(updated)
    assert "second-private" not in json.dumps(updated)


@pytest.mark.parametrize("branch", ["empty", "no-provider", "invalid-output", "rejected", "ai"])
def test_all_accepted_branches_stamp_actual_detached_target(branch, monkeypatch):
    observed = detail()["writing_target_version"]
    request = body(observed)
    if branch == "empty": request["original_bullets"] = []
    elif branch != "no-provider":
        monkeypatch.setattr(tailor, "is_configured", lambda: True)
        text = "Implemented PyTorch and Kubernetes" if branch == "rejected" else None
        row = {"unit_id": "b1", "links": [], "decision": "rewrite" if text else "keep",
               "ops": [{"op": "verb_first"}] if text else [], "text": text, "keep_reason": None if text else "no_link"}
        monkeypatch.setattr(tailor, "_ai_tailor_bullets",
                            lambda *args, **kwargs: None if branch == "invalid-output" else {"b1": row})
    response = client.post("/api/tailor", json=request)
    assert response.status_code == 200
    assert response.json()["target_version"] == observed
    assert response.json()["opportunity_id"] == "writing-target"
    assert response.json()["pipeline_version"] == tailor.TAILOR_PIPELINE_VERSION
    assert response.json()["method"] == ("ai" if branch in {"ai", "rejected"} else "fallback")


def test_snapshot_is_public_and_fully_detached_before_the_first_await(corpus, monkeypatch):
    public = detail()
    _rows, record = corpus
    original = deepcopy(record)
    seen = []
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    async def held_work(_fn, _profile, used_target, _bullets, **_kwargs):
        record["description_clean"] = "Changed while request is in flight"
        record["eligibility"]["skills_required"].append("Rust")
        record["metadata"]["confidence_score"] = 0.1
        seen.append(deepcopy(used_target))
        return {}
    monkeypatch.setattr(tailor, "run_blocking", held_work)
    response = client.post("/api/tailor", json=body(public["writing_target_version"]))
    assert response.status_code == 200
    assert response.json()["target_version"] == public["writing_target_version"]
    assert seen == [{key: value for key, value in public.items()
                     if key not in {"writing_target_version", "contact_email_status", "detail_fields"}}]
    assert seen[0]["eligibility"] == original["eligibility"]
    assert "private@example.edu" not in json.dumps(seen)
    assert detail()["writing_target_version"] != public["writing_target_version"]


@pytest.mark.parametrize("event", ["deleted", "closed", "hidden"])
def test_visibility_and_actionability_are_not_bypassed_by_a_valid_old_token(event, corpus, monkeypatch):
    token = detail()["writing_target_version"]
    rows, record = corpus
    if event == "deleted": rows.clear()
    elif event == "closed": record["metadata"]["listing_status"] = "closed"
    else: monkeypatch.setattr(tailor, "release_visible_opportunity_by_id", lambda *args: None)
    configured = Mock(side_effect=AssertionError("no work allowed"))
    monkeypatch.setattr(tailor, "is_configured", configured)
    response = client.post("/api/tailor", json=body(token))
    assert response.status_code == (409 if event == "closed" else 404)
    if event == "closed": assert response.json()["detail"]["code"] == "TARGET_NOT_ACTIONABLE"
    configured.assert_not_called()


def test_target_refusal_refunds_only_global_spend(monkeypatch):
    from backend import main
    monkeypatch.setattr(main, "RATE_LIMIT_DISABLED", False)
    monkeypatch.setattr(main, "_rate_buckets", defaultdict(list))
    monkeypatch.setattr(main, "_global_buckets", defaultdict(list))
    monkeypatch.setattr(main, "_last_purge", 0.0)
    monkeypatch.setattr(main, "GLOBAL_LLM_PER_MIN", 1)
    monkeypatch.setattr(main.llm_budget, "exhausted", lambda: False)
    for _ in range(2):
        response = client.post("/api/tailor", json=body("wt1:" + "0" * 64))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "WRITING_TARGET_CHANGED"
        assert main._global_buckets["llm"] == []
    assert sum(len(bucket) for bucket in main._rate_buckets.values()) == 2
    tailor.chat_completion.assert_not_called()
