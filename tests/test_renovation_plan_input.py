"""Legacy planning must read the accepted material or refuse before model work.

Synthetic HTTP requests; no model or metering service is contacted.
"""
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import tailor

client = TestClient(app)


@pytest.fixture
def target(monkeypatch):
    record = {
        "id": "complete-plan-target", "source": "manual", "source_type": "manual",
        "opportunity_type": "research", "title": "Sensor research",
        "organization": "Example University", "pi_name": "Example Professor",
        "description_clean": "Build sensors", "eligibility": {"skills_required": ["Python"]},
        "keywords": ["sensors"], "metadata": {"listing_status": "open"},
    }
    monkeypatch.setattr(tailor, "load_opportunities_by_id", lambda: {record["id"]: record})
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "_schedule_usage", Mock())
    monkeypatch.setattr(tailor, "chat_completion", Mock(return_value=None))
    return record


def payload():
    return {
        "profile": {"name": "Test Student", "research_interests_text": "Sensor calibration"},
        "opportunity_id": "complete-plan-target",
        "sections": [{"id": "s1", "heading": "Projects", "kind": "projects",
                      "bullets": [{"id": "b1", "text": "Built a thermal sensor"}]}],
    }


def test_plan_reads_complete_experiences_and_target(target):
    body = payload()
    heading = "Research " * 10 + "HEADING-END"
    text = "Recorded sensor readings. " * 30 + "I only organized the data; I did not design the sensor."
    body["sections"][0].update(heading=heading, bullets=[{"id": "b1", "text": text}])
    target.update(
        title="Long research title " * 15 + "TITLE-END",
        organization="Example University " * 15 + "ORGANIZATION-END",
        pi_name="Professor Name " * 10 + "PROFESSOR-END",
        description_clean="The laboratory studies calibration. " * 40 + "DESCRIPTION-END",
        keywords=[f"Topic {i} with complete details" for i in range(13)],
        eligibility={"skills_required": [f"Method {i} with complete details" for i in range(12)]},
    )
    response = client.post("/api/tailor/renovate", json=body)
    assert response.status_code == 200, response.text
    prompt = tailor.chat_completion.call_args.args[0][1]["content"]
    for value in [heading, text, target["title"], target["organization"], target["pi_name"],
                  target["description_clean"], *target["keywords"], *target["eligibility"]["skills_required"]]:
        assert value in prompt
    # The description is whole now, so the prompt no longer calls it an excerpt.
    assert f"- Organization: {target['organization']}\n" in prompt
    assert f"- Description: {target['description_clean']}\n" in prompt and "excerpt" not in prompt
    # A failed plan leaves the rollback floor intact, including the tail's limitation.
    assert response.json()["sections"][0]["bullets"][0]["base_text"] == text
    assert response.json()["pipeline_version"] == "w14.4"


def test_all_hundred_bullets_reach_the_plan_with_their_tails(target):
    body = payload()
    body["sections"] = []
    originals = []
    for section, count in enumerate([35, 35, 30]):
        bullets = []
        for i in range(count):
            text = "Recorded a measurement. " * 12 + f"END-{section}-{i}"
            bullets.append({"id": f"b{section}-{i}", "text": text})
            originals.append(text)
        body["sections"].append({"id": f"s{section}", "bullets": bullets})
    response = client.post("/api/tailor/renovate", json=body)
    assert response.status_code == 200, response.text
    prompt = tailor.chat_completion.call_args.args[0][1]["content"]
    assert all(text in prompt for text in originals)
    assert [b["base_text"] for s in response.json()["sections"] for b in s["bullets"]] == originals


@pytest.mark.parametrize("oversize", ["resume", "target", "combined", "escaping"])
def test_oversize_plan_is_refused_before_provider_and_usage(target, oversize):
    body = payload()
    if oversize == "resume":
        body["sections"][0]["bullets"][0]["text"] = "PRIVATE-RESUME " + "r" * 120_000
    elif oversize == "target":
        # Each field passes the public projection; their combined size exceeds
        # the plan budget. A single huge field is withheld by contact redaction.
        target["keywords"] = [f"PRIVATE-TARGET-{i} " + "t" * 1000 for i in range(120)]
    elif oversize == "combined":
        body["sections"][0]["bullets"][0]["text"] = "PRIVATE-RESUME " + "r" * 65_000
        target["keywords"] = [f"PRIVATE-TARGET-{i} " + "t" * 1000 for i in range(60)]
    else:
        # Fits as raw text; JSON escaping pushes the actual prompt over its limit.
        body["sections"][0]["bullets"][0]["text"] = 'PRIVATE-RESUME ' + '"\\' * 30_000
    response = client.post("/api/tailor/renovate", json=body)
    assert response.status_code == 413, response.text[:1000]
    assert response.json()["detail"] == {
        "code": "TAILOR_INPUT_TOO_LARGE",
        "message": "The combined resume input is too long. Reduce the selected material and try again.",
        "max_characters": 120_000, "retryable": False,
    }
    assert "PRIVATE-" not in response.text
    tailor.chat_completion.assert_not_called()
    tailor._schedule_usage.assert_not_called()


def _serialized(messages):
    return len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))


def test_plan_limit_counts_the_system_prompt_and_allows_exactly_the_limit(target):
    def send(length):
        body = payload()
        body["sections"][0]["bullets"][0]["text"] = "x" * length
        return client.post("/api/tailor/renovate", json=body)

    assert send(1).status_code == 200
    base = _serialized(tailor.chat_completion.call_args.args[0])
    fits = 1 + tailor.TAILOR_PROMPT_MAX_CHARACTERS - base
    assert send(fits).status_code == 200
    messages = tailor.chat_completion.call_args.args[0]
    assert _serialized(messages) == tailor.TAILOR_PROMPT_MAX_CHARACTERS
    # One character more is refused, though the messages without the system prompt would still fit.
    assert _serialized(messages[1:]) + 1 <= tailor.TAILOR_PROMPT_MAX_CHARACTERS
    tailor.chat_completion.reset_mock()
    tailor._schedule_usage.reset_mock()
    assert send(fits + 1).status_code == 413
    tailor.chat_completion.assert_not_called()
    tailor._schedule_usage.assert_not_called()


def test_oversize_plan_without_a_provider_still_returns_the_unchanged_document(target, monkeypatch):
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    body = payload()
    body["sections"][0]["bullets"][0]["text"] = "PRIVATE-RESUME " + "r" * 120_000
    response = client.post("/api/tailor/renovate", json=body)
    assert response.status_code == 200, response.text[:1000]
    assert response.json()["warnings"] == ["llm_not_configured"]
    assert response.json()["sections"][0]["bullets"][0]["base_text"] == body["sections"][0]["bullets"][0]["text"]
    tailor.chat_completion.assert_not_called()
    tailor._schedule_usage.assert_not_called()


def test_plan_uses_public_snapshot_without_reintroducing_withheld_source(target):
    target["description_clean"] = "PRIVATE-TARGET " + "t" * 20_000
    target["contact_email"] = "private@example.edu"
    response = client.post("/api/tailor/renovate", json=payload())
    assert response.status_code == 200, response.text
    prompt = tailor.chat_completion.call_args.args[0][1]["content"]
    assert "[email redacted]" in prompt
    assert "PRIVATE-TARGET" not in prompt and "private@example.edu" not in prompt

