"""Provider-free full-document contract, provenance, budget and failure tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.lib import target_resume_ai as engine
from backend.lib.target_resume_ai_schema import FullTargetRequest
from backend.lib.target_resume_ai_validation import (
    confirmed_document,
    fingerprint,
    units_for,
    validate_document,
)
from backend.main import RequestBodyLimitMiddleware, _full_target_body_limit_from_env, _release_feature_for_path, app
from backend.routes import target_resume_ai as route

PATH = "/api/tailor/full-target/suggestions"


def fact(ident, value):
    return {"id": ident, "revision": 1, "status": "confirmed", "value": value, "source": {"kind": "manual"}}


def make_doc():
    raw = "Built a Python robot with a team of 3. I did not lead the project."
    signature = hashlib.sha256(raw.encode()).hexdigest()
    entries = [{"id": "exp", "revision": 1, "status": "confirmed", "text": raw,
                "source": {"kind": "resume", "signature": signature, "quote": raw, "start": 0, "end": len(raw)}}]
    master = {"version": 1, "id": "master", "revision": 1, "source_signature": signature,
              "basics": {"name": fact("name", "Private Student"), "links": []},
              "education": [], "activities": [{"id": "project", "kind": "project", "title": fact("title", "Robot project"),
                                                "details": [{"id": "exp", "revision": 1}]}],
              "publications": [], "skills": [fact("skill", "Python")], "other_sections": [],
              "section_order": ["basics", "education", "activities", "publications", "skills"], "unmapped_ranges": []}
    snapshot = {"resume_text": raw, "experience_entries": entries, "resume_master": master}
    target = {"opportunity_id": "target", "title": "Research", "organization": "Example Lab", "source_url": "https://example.edu/lab",
              "description": "Research robots 🧪 with Python.", "requirements": ["Python"]}
    doc = {"kind": "full_resume", "version": 1, "id": "draft", "opportunity_id": "target",
           "base": {"master_id": "master", "master_revision": 1, "source_signature": signature,
                    "profile_signature": "v1:sha256:" + "a" * 64, "target_signature": fingerprint(target)},
           "base_snapshot": snapshot, "target_snapshot": target,
           "document": confirmed_document(snapshot, signature)}
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for row in block["lines"]:
                row.update(text=row["original"], included=True)
    return doc


def payload(doc=None, ids=None):
    doc = doc or make_doc()
    return {"version": 1, "request_id": "request", "locale": "en", "draft": doc, "document_signature": fingerprint(doc),
            "selected_unit_ids": ids if ids is not None else [unit["unit_id"] for unit in units_for(doc)[0]]}


def output(doc, ids=None):
    units = units_for(doc)[0]
    return {"units": [{"unit_id": unit["unit_id"], "priority": "high", "reason": "Relevant to the stated Python work.",
                       "target_evidence": [{"field": "requirement", "requirement_index": 0, "start": 0, "end": 6, "quote": "Python"}],
                       "proposed_text": None} for unit in units if ids is None or unit["unit_id"] in ids]}


@pytest.fixture
def endpoint(monkeypatch):
    doc = make_doc()
    target = doc["target_snapshot"]
    opp = {"id": "target", "title": target["title"], "organization": target["organization"], "source_url": target["source_url"],
           "description_clean": target["description"], "eligibility": {"skills_required": target["requirements"]},
           "source_type": "campus_program", "opportunity_type": "research", "metadata": {"is_active": True}}
    monkeypatch.setattr(route, "load_opportunities_by_id", lambda: {"target": opp})
    monkeypatch.setattr(route, "is_configured", lambda: True)
    monkeypatch.setattr(engine.llm_budget, "exhausted", lambda: False)
    calls = []

    def model(messages, **kwargs):
        calls.append((messages, kwargs))
        return json.dumps(output(doc))

    monkeypatch.setattr(engine, "chat_completion", model)
    return TestClient(app), doc, opp, calls


def test_golden_cross_language_document_and_manifest():
    golden = json.loads((Path(__file__).parent / "fixtures/target-resume-ai-golden.json").read_text())
    checked = validate_document(golden["draft"])
    assert fingerprint(checked) == golden["document_signature"]
    units, protected = units_for(checked)
    assert units == golden["units"]
    assert {"unit_ids": [unit["unit_id"] for unit in units], "protected_unit_count": protected} == golden["manifest"]


def test_valid_batch_preserves_source_and_excludes_private_and_manual_text(endpoint):
    client, doc, _, calls = endpoint
    doc["document"]["sections"][1]["blocks"][0]["lines"][1]["text"] = "UNCONFIRMED invented achievement 999"
    before = deepcopy(doc)
    response = client.post(PATH, json=payload(doc))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["manifest"] == {"unit_ids": ["line-2", "line-3", "line-4"], "protected_unit_count": 1}
    assert body["logical_calls"] == 1 and body["provider_attempts_upper_bound"] == 2
    assert body["method"] == "ai" and len(body["receipts"]) == 3
    assert "private" in response.headers["cache-control"] and "no-store" in response.headers["cache-control"]
    prompt = calls[0][0][1]["content"]
    assert "UNCONFIRMED" not in prompt and "Private Student" not in prompt
    assert doc["base_snapshot"]["experience_entries"][0]["text"] in prompt
    assert calls[0][1]["max_tokens"] == 12000
    assert doc == before


@pytest.mark.parametrize("mutation", [
    lambda d: d["base_snapshot"]["experience_entries"][0].update(status="withdrawn"),
    lambda d: d["base_snapshot"]["experience_entries"][0]["source"].update(quote="x"),
    lambda d: d["base_snapshot"].update(resume_text="replacement"),
    lambda d: d["base_snapshot"]["resume_master"]["activities"][0]["details"][0].update(revision=2),
    lambda d: d["document"]["sections"][1]["blocks"][0]["lines"][0].update(original="Fake title"),
    lambda d: d["document"]["sections"][1]["blocks"][0]["lines"][0]["evidence"].update(revision=True),
    lambda d: d["document"]["sections"][1]["blocks"][0]["lines"].pop(),
    lambda d: d["base"].update(extra="hidden"),
])
def test_bad_evidence_tree_rejected_without_model(endpoint, mutation):
    client, doc, _, calls = endpoint
    mutation(doc)
    response = client.post(PATH, json=payload(doc))
    assert response.status_code == 422 and not calls
    assert "Private Student" not in response.text


@pytest.mark.parametrize("selection", [["line-1"], ["unknown"], ["line-2", "line-2"], []])
def test_invalid_unit_selection_is_not_silently_repaired(endpoint, selection):
    client, doc, _, calls = endpoint
    assert client.post(PATH, json=payload(doc, selection)).status_code == 422
    assert not calls


@pytest.mark.parametrize("character", ["\ud800", "\udfff", "\x00"])
def test_private_malformed_unicode_returns_safe_422(endpoint, character):
    client, doc, _, calls = endpoint
    body = payload(doc)
    body["draft"]["document"]["sections"][0]["blocks"][0]["lines"][0]["text"] = "PRIVATE" + character
    response = client.post(PATH, content=json.dumps(body, ensure_ascii=True), headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and "PRIVATE" not in response.text and not calls


def test_changed_or_hidden_target_refused_before_model(endpoint):
    client, doc, opp, calls = endpoint
    opp["description_clean"] = "New target"
    assert client.post(PATH, json=payload(doc)).status_code == 409
    opp["metadata"]["is_active"] = False
    assert client.post(PATH, json=payload(doc)).status_code == 409
    assert not calls


@pytest.mark.parametrize("kind", ["unknown", "duplicate", "fact_rewrite", "wrong_quote", "cross_project_number", "missing"])
def test_model_output_failures_have_exact_receipts(endpoint, monkeypatch, kind):
    client, doc, _, _ = endpoint
    data = output(doc)
    if kind == "unknown":
        data["units"][0]["unit_id"] = "unknown"
    elif kind == "duplicate":
        data["units"].append(data["units"][0])
    elif kind == "fact_rewrite":
        data["units"][0]["proposed_text"] = "Invented fact"
    elif kind == "wrong_quote":
        data["units"][0]["target_evidence"][0]["quote"] = "Imagined"
    elif kind == "cross_project_number":
        data["units"][1]["proposed_text"] = "Built 999 Python robots."
    else:
        data["units"].pop()
    monkeypatch.setattr(engine, "chat_completion", lambda *args, **kwargs: json.dumps(data))
    response = client.post(PATH, json=payload(doc)).json()
    assert [row["unit_id"] for row in response["receipts"]] == ["line-2", "line-3", "line-4"]
    assert any(row["status"] == "skipped" for row in response["receipts"])
    assert response["method"] in ("partial", "unavailable")


def test_target_quote_offsets_use_codepoints_and_require_literal_match():
    target = {"description": "A🧪中文Z", "requirements": []}
    quote = {"field": "description", "requirement_index": None, "start": 1, "end": 4, "quote": "🧪中文"}
    assert engine.valid_quotes([quote], target)
    assert not engine.valid_quotes([{**quote, "end": 5}], target)


def test_budget_rechecked_inside_worker_before_provider(endpoint, monkeypatch):
    client, doc, _, calls = endpoint
    monkeypatch.setattr(engine.llm_budget, "exhausted", lambda: True)
    # Bypass only middleware admission to directly test the queued worker seam.
    raw, reason, count = engine.dispatch([])
    assert (raw, reason, count) == (None, "budget_exhausted", 0) and not calls


def test_complete_6000_character_experience_is_not_cut():
    doc = make_doc()
    entry = doc["base_snapshot"]["experience_entries"][0]
    entry.update(text="x" * 5996 + "TAIL", source={"kind": "manual"})
    row = doc["document"]["sections"][1]["blocks"][0]["lines"][1]
    row.update(original=entry["text"], text=entry["text"])
    request = FullTargetRequest(**payload(doc, [row["id"]]))
    checked = validate_document(doc)
    _, _, _, processable = engine.prepare_batch(request, checked)
    messages, reason = engine.batch_preflight(checked, processable, "en")
    assert reason is None and entry["text"] in messages[1]["content"]


def test_large_fact_skipped_without_truncation_and_other_units_survive(endpoint):
    client, doc, _, calls = endpoint
    value = "F" * 16001
    doc["base_snapshot"]["resume_master"]["skills"][0]["value"] = value
    doc["document"]["sections"][2]["blocks"][0]["lines"][0].update(original=value, text=value)
    body = client.post(PATH, json=payload(doc)).json()
    assert body["receipts"][-1]["reason_code"] == "unit_too_large"
    assert body["receipts"][-1]["before_text"] == value
    assert len(body["receipts"]) == 3 and len(calls) == 1


def test_new_route_gate_and_body_limit_are_scoped(monkeypatch):
    assert _release_feature_for_path(PATH) == "resume_renovate"
    monkeypatch.delenv("OFE_MAX_REQUEST_BODY_BYTES", raising=False)
    assert _full_target_body_limit_from_env() == 2 * 1024 * 1024 + 64 * 1024
    monkeypatch.setenv("OFE_MAX_REQUEST_BODY_BYTES", str(1024 * 1024))
    assert _full_target_body_limit_from_env() == 1024 * 1024


def test_unknown_fields_rejected_by_complete_contract(endpoint):
    client, doc, _, calls = endpoint
    body = payload(doc)
    body["secret"] = "DO NOT ECHO"
    response = client.post(PATH, json=body)
    assert response.status_code == 422 and "DO NOT ECHO" not in response.text and not calls


def test_model_receives_only_selected_units_not_every_experience(endpoint):
    client, doc, _, calls = endpoint
    response = client.post(PATH, json=payload(doc, ["line-4"]))
    # Fake model returns unsolicited IDs; reject rather than attach them elsewhere.
    assert response.status_code == 200 and response.json()["method"] == "unavailable"
    prompt = calls[0][0][1]["content"]
    assert doc["base_snapshot"]["experience_entries"][0]["text"] not in prompt


def test_all_batches_cover_more_than_eight_whole_experiences(endpoint, monkeypatch):
    client, doc, _, calls = endpoint
    entries = doc["base_snapshot"]["experience_entries"]
    activity = doc["base_snapshot"]["resume_master"]["activities"][0]
    for index in range(1, 15):
        entries.append({"id": f"exp-{index}", "revision": 1, "status": "confirmed", "text": "Built a Python robot. " * 70,
                        "source": {"kind": "manual"}})
        activity["details"].append({"id": f"exp-{index}", "revision": 1})
    doc["document"] = confirmed_document(doc["base_snapshot"], doc["base"]["source_signature"])
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for row in block["lines"]:
                row.update(text=row["original"], included=True)
    batches, current, size, experiences = [], [], 0, 0
    for unit in units_for(doc)[0]:
        original_size = len(unit["original"])
        experience_size = original_size if unit["evidence"]["kind"] == "experience" else 0
        if len(current) == 24 or size + original_size > 16000 or experiences + experience_size > 6000:
            batches.append(current)
            current, size, experiences = [], 0, 0
        current.append(unit["unit_id"])
        size += original_size
        experiences += experience_size
    if current:
        batches.append(current)
    captured = []

    def model(messages, **kwargs):
        requested = json.loads(messages[1]["content"])["units"]
        captured.extend(unit["unit_id"] for unit in requested)
        return json.dumps(output(doc, [unit["unit_id"] for unit in requested]))

    monkeypatch.setattr(engine, "chat_completion", model)
    received = []
    for batch in batches:
        response = client.post(PATH, json=payload(doc, batch))
        assert response.status_code == 200, response.text
        received.extend(row["unit_id"] for row in response.json()["receipts"])
        assert response.json()["method"] == "ai"
    all_ids = [unit["unit_id"] for unit in units_for(doc)[0]]
    assert len(batches) > 1 and len(all_ids) > 8
    assert received == captured == all_ids


def test_oversized_batch_is_rejected_not_sliced(endpoint):
    client, doc, _, calls = endpoint
    # Two individually legal full experiences together exceed the batch budget.
    entry = doc["base_snapshot"]["experience_entries"][0]
    entry.update(text="a" * 6000, source={"kind": "manual"})
    doc["document"]["sections"][1]["blocks"][0]["lines"][1].update(original=entry["text"], text=entry["text"])
    second = deepcopy(entry)
    second.update(id="another", text="b")
    doc["base_snapshot"]["experience_entries"].append(second)
    doc["base_snapshot"]["resume_master"]["activities"][0]["details"].append({"id": "another", "revision": 1})
    doc["document"] = confirmed_document(doc["base_snapshot"], doc["base"]["source_signature"])
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for row in block["lines"]:
                row.update(text=row["original"], included=True)
    response = client.post(PATH, json=payload(doc))
    assert response.status_code == 422 and not calls


@pytest.mark.parametrize("reason", ["target_too_large", "context_too_large"])
def test_oversize_target_or_context_is_explicit_and_zero_model(endpoint, reason):
    client, doc, opp, calls = endpoint
    if reason == "target_too_large":
        opp["description_clean"] = "t" * 19000
        opp["eligibility"]["skills_required"] = ["Python", "r" * 6000]
        doc["target_snapshot"] = route.authoritative_target(opp)
        doc["base"]["target_signature"] = fingerprint(doc["target_snapshot"])
    else:
        # Complete sibling fact context is legal but cannot be silently trimmed.
        huge = "a" * 59000
        doc["base_snapshot"]["resume_master"]["activities"][0]["title"]["value"] = huge
        doc["document"]["sections"][1]["blocks"][0]["lines"][0].update(original=huge, text=huge)
    response = client.post(PATH, json=payload(doc, ["line-3"]))
    assert response.status_code == 200, response.text
    assert response.json()["receipts"][0]["reason_code"] == reason
    assert response.json()["logical_calls"] == 0 and not calls


def test_no_provider_returns_unavailable_without_claiming_an_attempt(endpoint, monkeypatch):
    client, doc, _, calls = endpoint
    monkeypatch.setattr(route, "is_configured", lambda: False)
    response = client.post(PATH, json=payload(doc)).json()
    assert response["method"] == "unavailable" and response["logical_calls"] == 0
    assert response["provider_attempts_upper_bound"] == 0 and not calls


def test_worker_timeout_preserves_all_receipts(endpoint, monkeypatch):
    from backend.lib.blocking import BlockingWorkTimeout
    client, doc, _, calls = endpoint

    async def timeout(*args, **kwargs):
        raise BlockingWorkTimeout()

    monkeypatch.setattr(route, "run_blocking", timeout)
    response = client.post(PATH, json=payload(doc)).json()
    assert all(row["reason_code"] == "timeout" and row["suggestion"] is None for row in response["receipts"])
    assert response["logical_calls"] == 1 and response["provider_attempts_upper_bound"] == 2
    assert not calls


def test_closed_feature_refuses_new_path_with_no_store(endpoint, monkeypatch):
    import backend.main as main
    client, doc, _, calls = endpoint
    monkeypatch.setattr(main, "feature_enabled", lambda feature: feature != "resume_renovate")
    response = client.post(PATH, json=payload(doc))
    assert response.status_code == 404 and not calls
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(("path", "declared", "sizes", "expected"), [
    (PATH, None, [15, 15], 200),
    (PATH, None, [15, 16], 413),
    (PATH, 31, [1], 413),
    ("/api/tailor/renovate", None, [15, 6], 413),
    ("/api/tailor/renovate", 21, [1], 413),
])
def test_new_body_limit_counts_actual_chunks_without_widening_legacy(path, declared, sizes, expected):
    messages = [{"type": "http.request", "body": b"x" * size, "more_body": i < len(sizes) - 1} for i, size in enumerate(sizes)]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    headers = [] if declared is None else [(b"content-length", str(declared).encode())]
    middleware = RequestBodyLimitMiddleware(downstream, max_bytes=20, full_target_max_bytes=30)
    asyncio.run(middleware({"type": "http", "path": path, "headers": headers}, receive, send))
    assert sent[0]["status"] == expected


def test_complete_document_over_legacy_one_mib_is_admitted_without_truncation(endpoint):
    client, doc, _, calls = endpoint
    manual = "M" * (1024 * 1024 + 10)
    doc["document"]["sections"][1]["blocks"][0]["lines"][1]["text"] = manual
    response = client.post(PATH, json=payload(doc))
    assert response.status_code == 200, response.text[:200]
    receipt = next(row for row in response.json()["receipts"] if row["unit_id"] == "line-3")
    assert receipt["before_text"] == manual and len(calls) == 1
    assert manual not in calls[0][0][1]["content"]


@pytest.mark.parametrize(("original", "proposed"), [
    ("I did not lead the team. I built a Python parser with my teammates.", "I led the team and built a Python parser."),
    ("Our team built a Python parser. I reviewed the documentation.", "I built the Python parser."),
    ("The project was submitted for review, not accepted.", "The project was accepted."),
    ("我没有主导团队。我协助测试。", "我主导团队并完成测试。"),
    ("团队开发了工具。本人负责审阅文档。", "本人开发了工具。"),
    ("论文已投稿，尚未录用。", "论文已录用。"),
    ("论文正在审稿。", "论文已经发表。"),
    ("I did not lead the project.", "I did not lead the project. I led the project."),
])
def test_bounded_claim_locks_reject_negation_role_and_publication_upgrades(original, proposed):
    doc = make_doc()
    unit = next(unit for unit in units_for(doc)[0] if unit["evidence"]["kind"] == "experience")
    unit.update(original=original, before_text=original)
    data = output(doc, [unit["unit_id"]])
    data["units"][0]["proposed_text"] = proposed
    rows = engine.parse_output(json.dumps(data), [unit], doc["target_snapshot"])
    assert rows[0]["status"] == "skipped" and rows[0]["reason_code"] == "ungrounded_rewrite"


@pytest.mark.parametrize(("original", "proposed"), [
    ("I did not lead the project. Reviewed documents.", "Reviewed documents. I did not lead the project."),
    ("Our team built a Python parser. I reviewed the documentation.", "I reviewed the documentation. Our team built a Python parser."),
    ("The project was submitted for review, not accepted.", "The project was submitted for review, not accepted."),
    ("我没有主导团队。本人审阅文档。", "本人审阅文档。我没有主导团队。"),
    ("团队开发了工具。本人负责审阅文档。", "本人负责审阅文档。团队开发了工具。"),
    ("论文已投稿，尚未录用。", "论文已投稿，尚未录用。"),
])
def test_legal_preservation_of_sensitive_claims_still_allows_suggestions(original, proposed):
    doc = make_doc()
    unit = next(unit for unit in units_for(doc)[0] if unit["evidence"]["kind"] == "experience")
    unit.update(original=original, before_text=original)
    data = output(doc, [unit["unit_id"]])
    data["units"][0]["proposed_text"] = proposed
    rows = engine.parse_output(json.dumps(data), [unit], doc["target_snapshot"])
    assert rows[0]["status"] in ("suggested", "unchanged")
    assert rows[0]["suggestion"] is not None


def test_whole_block_context_is_sent_once_for_many_selected_lines():
    doc = make_doc()
    title = "T" * 10000
    master = doc["base_snapshot"]["resume_master"]
    master["activities"][0]["title"]["value"] = title
    entries = [{"id": f"short-{i}", "revision": 1, "status": "confirmed", "text": "Built a small Python tool.",
                "source": {"kind": "manual"}} for i in range(10)]
    doc["base_snapshot"]["experience_entries"] = entries
    master["activities"][0]["details"] = [{"id": item["id"], "revision": 1} for item in entries]
    doc["document"] = confirmed_document(doc["base_snapshot"], doc["base"]["source_signature"])
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for row in block["lines"]:
                row.update(text=row["original"], included=True)
    checked = validate_document(doc)
    selected = [unit["unit_id"] for unit in units_for(checked)[0] if unit["section_id"] == "activities"]
    _, _, _, processable = engine.prepare_batch(FullTargetRequest(**payload(checked, selected)), checked)
    messages, reason = engine.batch_preflight(checked, processable, "en")
    assert reason is None and len(processable) == 11
    model_input = json.loads(messages[1]["content"])
    assert len(model_input["block_contexts"]) == 1
    assert model_input["block_contexts"][0]["fields"][0]["value"] == title
    assert all("block_context" not in unit for unit in model_input["units"])
    assert len(model_input["units"]) == 11
    assert sum(len(message["content"]) for message in messages) < 60000
