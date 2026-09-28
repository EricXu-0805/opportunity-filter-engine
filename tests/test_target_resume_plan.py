"""Whole-document API checks using only an in-process synthetic provider."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.lib import target_resume_ai as ai
from backend.lib import target_resume_plan as plan
from backend.lib.blocking import BlockingWorkOverloaded, BlockingWorkTimeout
from backend.lib.target_resume_ai_validation import confirmed_document, fingerprint, validate_document
from backend.lib.target_resume_plan_schema import MAX_BODY_BYTES, FullTargetPlanRequest
from backend.routes import target_resume_ai as route
from tests.test_full_target_resume_attribution import _document, _fact

PATH = "/api/tailor/full-target/selection-plan"
ORIGINAL = "I wrote parser tests using Python."


def payload(doc, pages=1):
    return {"version": 1, "request_id": "plan-fixture", "locale": "en", "draft": doc,
            "document_signature": fingerprint(doc), "options": {"target_pages": pages}}


@dataclass
class Endpoint:
    client: TestClient
    opportunity: dict
    calls: list = field(default_factory=list)
    rewrites: dict = field(default_factory=dict)
    mutate: object = None

    def model(self, messages, **kwargs):
        self.calls.append((deepcopy(messages), deepcopy(kwargs)))
        data = json.loads(messages[1]["content"])
        items = []
        target_quote = data["target"]["requirements"][0]
        for block in data["blocks"]:
            first = block["lines"][0]
            rewrites = [{"unit_id": line["unit_id"], "proposed_text": self.rewrites[line["evidence"]["id"]]}
                        for line in block["lines"] if line["evidence"]["id"] in self.rewrites]
            items.append({"section_id": block["section_id"], "block_id": block["block_id"],
                          "action": "compress" if rewrites else "keep", "reason": f"Relevant to the published {target_quote} requirement.",
                          "target_evidence": [{"field": "requirement", "requirement_index": 0,
                                               "start": 0, "end": len(target_quote), "quote": target_quote}],
                          "source_evidence": [{"unit_id": first["unit_id"], "start": 0,
                                               "end": len(first["original"]), "quote": first["original"]}],
                          "rewrites": rewrites})
        result = {"items": items}
        if self.mutate:
            self.mutate(result, data)
        return json.dumps(result, ensure_ascii=False)

    def doc(self, originals=None):
        return _document(originals or [ORIGINAL, "I built a Python parser using NumPy."], self.opportunity)

    def submit(self, doc, pages=1):
        before = deepcopy(doc)
        result = self.client.post(PATH, json=payload(doc, pages))
        assert doc == before  # Advice cannot apply changes or mutate source snapshots.
        return result


@pytest.fixture
def endpoint(monkeypatch):
    opp = {"id": "plan-target", "title": "Research Tools", "organization": "Example Lab",
           "source_url": "https://example.edu/lab", "description_clean": "Research Python parsers 🧪 中文.",
           "eligibility": {"skills_required": ["Python"]}, "source_type": "campus_program",
           "opportunity_type": "research", "metadata": {"is_active": True}}
    result = Endpoint(TestClient(main.app), opp)
    monkeypatch.setattr(route, "load_opportunities_by_id", lambda: {opp["id"]: opp})
    monkeypatch.setattr(route, "is_configured", lambda: True)
    monkeypatch.setattr(ai.llm_budget, "exhausted", lambda: False)
    monkeypatch.setattr(ai, "chat_completion", result.model)
    return result


def completed(endpoint, response, doc):
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["pipeline_version"] == "full-target-plan-v4"
    assert result["complete"] is True and result["method"] == "ai" and result["reason_code"] is None
    assert result["logical_calls"] == 1 and result["provider_attempts_upper_bound"] == 2
    assert result["document_signature"] == fingerprint(doc) and result["base"] == doc["base"]
    assert len(endpoint.calls) == 1
    expected = [{"section_id": section["id"], "block_id": block["id"], "line_ids": [row["id"] for row in block["lines"]]}
                for section in doc["document"]["sections"] if section["kind"] != "basics" for block in section["blocks"]]
    assert result["manifest"] == expected
    assert [(row["section_id"], row["block_id"]) for row in result["items"]] == [(row["section_id"], row["block_id"]) for row in expected]
    assert "private" in response.headers["cache-control"] and "no-store" in response.headers["cache-control"]
    return result


def unavailable(response, reason, *, calls=1):
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["method"] == "unavailable" and result["complete"] is False
    assert result["items"] == [] and result["reason_code"] == reason
    assert result["logical_calls"] == calls and result["provider_attempts_upper_bound"] == (2 if calls else 0)
    return result


def test_all_thirty_blocks_hidden_content_and_last_item_reach_one_model_call(endpoint):
    originals = [f"I wrote parser tests for dataset {i}." for i in range(29)] + ["I wrote the FINAL_ENTRY_SENTINEL parser tests."]
    doc = endpoint.doc(originals)
    section = doc["document"]["sections"][1]
    section["included"] = False
    section["blocks"][0]["included"] = False
    section["blocks"][0]["lines"][-1].update(included=False, text="MY_CURRENT_UNVERIFIED_LAYOUT_TEXT")
    def last_matters(result, data):
        assert len(data["blocks"]) == 30 and "FINAL_ENTRY_SENTINEL" in data["blocks"][-1]["lines"][-1]["original"]
        result["items"][-1]["action"] = "omit"
    endpoint.mutate = last_matters
    result = completed(endpoint, endpoint.submit(doc, 2), doc)
    assert len(result["items"]) == 30 and result["items"][-1]["action"] == "omit"
    prompt = json.loads(endpoint.calls[0][0][1]["content"])
    assert prompt["options"] == {"target_pages": 2}
    assert [line["original"] for block in prompt["blocks"] for line in block["lines"] if line["evidence"]["kind"] == "experience"] == originals
    assert prompt["blocks"][0]["section_included"] is False and prompt["blocks"][0]["included"] is False
    assert prompt["blocks"][0]["lines"][-1]["included"] is False
    assert prompt["blocks"][0]["lines"][-1]["text"] == "MY_CURRENT_UNVERIFIED_LAYOUT_TEXT"
    assert "Fixture Student" not in endpoint.calls[0][0][1]["content"]


def test_full_long_originals_beyond_old_batch_limit_are_not_cut(endpoint):
    originals = ["A" * 5995 + "TAIL1", "B" * 5995 + "TAIL2"]
    doc = endpoint.doc(originals)
    completed(endpoint, endpoint.submit(doc), doc)
    prompt = json.loads(endpoint.calls[0][0][1]["content"])
    actual = [line["original"] for block in prompt["blocks"] for line in block["lines"] if line["evidence"]["kind"] == "experience"]
    assert actual == originals and sum(map(len, actual)) == 12000


def test_scope_discloses_unreferenced_pending_stale_and_unmapped_without_sending_their_text(endpoint):
    doc = endpoint.doc()
    snap = doc["base_snapshot"]
    base = {"revision": 1, "text": "DO_NOT_SEND_OUTSIDE_CURRENT_DOCUMENT", "source": {"kind": "manual"}}
    for ident, status in [("pending", "candidate"), ("unreferenced", "confirmed"), ("withdrawn", "withdrawn"), ("rejected", "rejected")]:
        snap["experience_entries"].append({**deepcopy(base), "id": ident, "status": status})
    snap["experience_entries"].append({**deepcopy(base), "id": "stale", "status": "confirmed",
                                      "source": {"kind": "resume", "signature": "0" * 64, "quote": "OLD", "start": 0, "end": 3}})
    snap["resume_master"]["unmapped_ranges"] = [{"start": 0, "end": 3}]
    result = completed(endpoint, endpoint.submit(doc), doc)
    assert result["scope"] == {"pending_experience_ids": ["pending"], "unreferenced_experience_ids": ["unreferenced"],
                               "stale_experience_ids": ["stale"], "unmapped_range_count": 1}
    assert "DO_NOT_SEND_OUTSIDE_CURRENT_DOCUMENT" not in endpoint.calls[0][0][1]["content"]


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown", "wrong_section", "extra_field", "bad_action", "blank_reason",
                                   "bad_target", "bad_source", "cross_block_source", "editable_source", "fact_rewrite",
                                   "cross_block_rewrite", "duplicate_rewrite", "keep_rewrite", "omit_rewrite", "blank_rewrite", "extra_rewrite_field"])
def test_any_invalid_structure_or_quote_invalidates_the_whole_plan(endpoint, kind):
    doc = endpoint.doc()
    def mutate(result, data):
        rows = result["items"]
        item, block = rows[0], data["blocks"][0]
        experience = block["lines"][-1]
        if kind == "missing": rows.pop()
        elif kind == "duplicate": rows[-1] = deepcopy(item)
        elif kind == "unknown": item["block_id"] = "unknown"
        elif kind == "wrong_section": item["section_id"] = "education"
        elif kind == "extra_field": item["hidden_instruction"] = "secret"
        elif kind == "bad_action": item["action"] = "delete"
        elif kind == "blank_reason": item["reason"] = " "
        elif kind == "bad_target": item["target_evidence"][0]["quote"] = "Invented"
        elif kind == "bad_source": item["source_evidence"][0]["end"] += 1
        elif kind == "cross_block_source": item["source_evidence"] = deepcopy(rows[1]["source_evidence"])
        elif kind == "editable_source": item["source_evidence"] = [{"unit_id": experience["unit_id"], "start": 0, "end": 4, "quote": "FAKE"}]
        else:
            item["action"] = "compress"
            item["rewrites"] = [{"unit_id": experience["unit_id"], "proposed_text": "I wrote parser tests."}]
            if kind == "fact_rewrite": item["rewrites"][0]["unit_id"] = block["lines"][0]["unit_id"]
            elif kind == "cross_block_rewrite": item["rewrites"][0]["unit_id"] = data["blocks"][1]["lines"][-1]["unit_id"]
            elif kind == "duplicate_rewrite": item["rewrites"].append(deepcopy(item["rewrites"][0]))
            elif kind == "keep_rewrite": item["action"] = "keep"
            elif kind == "omit_rewrite": item["action"] = "omit"
            elif kind == "blank_rewrite": item["rewrites"][0]["proposed_text"] = " "
            elif kind == "extra_rewrite_field": item["rewrites"][0]["status"] = "suggested"
    endpoint.mutate = mutate
    doc["document"]["sections"][1]["blocks"][0]["lines"][-1]["text"] = "FAKE manual text"
    reason = "no_target_evidence" if kind == "bad_target" else "no_source_evidence" if kind in {"bad_source", "cross_block_source", "editable_source"} else "invalid_model_response"
    body = unavailable(endpoint.submit(doc), reason)
    assert len(endpoint.calls) == 1 and len(body["manifest"]) == 2


@pytest.mark.parametrize("original,proposed", [
    ("My team built a parser. I wrote parser tests. Additional context for length.", "Built a parser. My team built a parser. I wrote parser tests."),
    ("I improved throughput by 45% and reduced latency by 12%. Additional context for length.", "Improved throughput by 12% and reduced latency by 45%."),
    ("I built a parser. I did not build a compiler. Additional context for length.", "Built a compiler. I did not build a compiler."),
    ("My team implemented Python ML projects for CS 225. I wrote tests. Additional context for length.",
     "Implemented Python ML projects in CS 225. My team implemented Python ML projects for CS 225."),
    ("I analyzed measurement uncertainty, never carefully. Additional context for length.",
     "Analyzed measurement uncertainty carefully."),
])
def test_compression_reuses_b43_attribution_guard_without_discarding_valid_plan(endpoint, original, proposed):
    assert len(proposed) < len(original)
    doc = endpoint.doc([original])
    endpoint.rewrites = {"exp-0": proposed}
    result = completed(endpoint, endpoint.submit(doc), doc)
    assert result["items"][0]["rewrites"] == [{"unit_id": doc["document"]["sections"][1]["blocks"][0]["lines"][-1]["id"],
        "status": "skipped", "reason_code": "ungrounded_rewrite", "proposed_text": None}]
    assert result["items"][0]["reason"] and result["items"][0]["action"] == "compress"


def test_same_block_other_line_and_manual_wording_cannot_supply_missing_claim(endpoint):
    doc = endpoint.doc(["I wrote parser tests using Python.", "I built a Python parser using NumPy."])
    master = doc["base_snapshot"]["resume_master"]
    master["activities"][0]["details"].extend(master["activities"].pop()["details"])
    doc["document"] = confirmed_document(doc["base_snapshot"], doc["base"]["source_signature"])
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for line in block["lines"]:
                line.update(text=line["original"], included=True)
    line = doc["document"]["sections"][1]["blocks"][0]["lines"][1]
    line["text"] = "I built a Python parser using NumPy with my own manual additions."
    endpoint.rewrites = {"exp-0": "I built a Python parser.", "exp-1": "Built a Python parser."}
    result = completed(endpoint, endpoint.submit(doc), doc)
    assert [row["status"] for row in result["items"][0]["rewrites"]] == ["skipped", "suggested"]
    assert result["items"][0]["rewrites"][0]["reason_code"] == "ungrounded_rewrite"


@pytest.mark.parametrize("original,current,proposed,reason", [
    (ORIGINAL, ORIGINAL, "I wrote parser tests.", None),
    (ORIGINAL, "Tests.", "I wrote parser tests.", "not_shorter"),
    (ORIGINAL, ORIGINAL, ORIGINAL, "not_shorter"),
    ("I wrote tests🧪", "I wrote tests🧪", "I wrote tests.", "not_shorter"),
    ("My team built a parser. I wrote tests. Additional context for length.",
     "My team built a parser. I wrote tests. Additional context for length.",
     "My team built a parser. I wrote tests.", None),
    (ORIGINAL, ORIGINAL + " Extra manual text.", ORIGINAL + " More.", "not_shorter"),
    ("Built Python ML models during coursework.", "Built Python ML models during coursework.", "Built ML models during coursework.", None),
])
def test_rewrite_requires_strictly_less_than_original_and_current_codepoints(endpoint, original, current, proposed, reason):
    doc = endpoint.doc([original])
    doc["document"]["sections"][1]["blocks"][0]["lines"][-1]["text"] = current
    endpoint.rewrites = {"exp-0": proposed}
    body = completed(endpoint, endpoint.submit(doc), doc)
    row = body["items"][0]["rewrites"][0]
    assert row["reason_code"] == reason
    assert row["status"] == ("skipped" if reason else "suggested")
    assert row["proposed_text"] == (None if reason else proposed)


@pytest.mark.parametrize("kind", ["context_too_large", "target_too_large", "no_plan_items", "model_unavailable"])
def test_explicit_unavailability_makes_no_provider_call(endpoint, monkeypatch, kind):
    doc = endpoint.doc()
    if kind == "context_too_large":
        # Editable text has no line cap but the complete prompt is bounded; no slicing.
        doc["document"]["sections"][1]["blocks"][0]["lines"][-1]["text"] = "L" * 120000
    elif kind == "target_too_large":
        endpoint.opportunity["description_clean"] = "T" * 19000
        endpoint.opportunity["eligibility"]["skills_required"] = ["Python", "R" * 6000]
        doc["target_snapshot"] = route.authoritative_target(endpoint.opportunity)
        doc["base"]["target_signature"] = fingerprint(doc["target_snapshot"])
    elif kind == "no_plan_items":
        doc["base_snapshot"]["resume_master"]["activities"] = []
        doc["document"] = {"sections": [doc["document"]["sections"][0]]}
    else:
        monkeypatch.setattr(route, "is_configured", lambda: False)
    unavailable(endpoint.submit(doc), kind, calls=0)
    assert endpoint.calls == []


def test_prompt_cap_boundary_counts_the_complete_unicode_prompt(endpoint, monkeypatch):
    doc = endpoint.doc(["I wrote tests 中文 🧪."])
    request = FullTargetPlanRequest(**payload(doc))
    blocks, _, scope = plan.prepare_plan(request, validate_document(doc))
    messages, reason = plan.plan_preflight(doc, blocks, scope, {"target_pages": 1}, "zh")
    assert reason is None
    count = sum(len(message["content"]) for message in messages)
    monkeypatch.setattr(plan, "MAX_PROMPT_CHARACTERS", count)
    assert plan.plan_preflight(doc, blocks, scope, {"target_pages": 1}, "zh")[1] is None
    monkeypatch.setattr(plan, "MAX_PROMPT_CHARACTERS", count - 1)
    unavailable(endpoint.submit(doc), "context_too_large", calls=0)
    assert not endpoint.calls


@pytest.mark.parametrize("changes", [
    {"version": True}, {"options": {"target_pages": True}}, {"options": {"target_pages": 3}},
    {"options": {"target_pages": "1"}}, {"options": {"target_pages": 1, "hidden": "PRIVATE"}},
    {"selected_unit_ids": ["line-3"]}, {"document_signature": "v1:sha256:" + "0" * 64},
])
def test_invalid_request_fails_without_provider_or_private_echo(endpoint, changes):
    doc = endpoint.doc()
    data = {**payload(doc), **changes}
    response = endpoint.client.post(PATH, json=data)
    assert response.status_code == 422 and not endpoint.calls and "PRIVATE" not in response.text
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("change", ["target_changed", "not_found", "not_actionable", "source_changed", "legacy"])
def test_source_and_authoritative_target_preflight_precedes_provider(endpoint, change):
    doc = endpoint.doc()
    if change == "target_changed": endpoint.opportunity["description_clean"] = "Different target"
    elif change == "not_found": doc["opportunity_id"] = doc["target_snapshot"]["opportunity_id"] = "missing"; doc["base"]["target_signature"] = fingerprint(doc["target_snapshot"])
    elif change == "not_actionable": endpoint.opportunity["metadata"]["is_active"] = False
    elif change == "source_changed": doc["base_snapshot"]["resume_text"] += "forged"
    else:
        target = doc["target_snapshot"]
        doc["target_snapshot"] = {key: target[key] for key in ("opportunity_id", "title", "organization", "source_url", "description", "requirements")}
        doc["base"]["target_signature"] = fingerprint(doc["target_snapshot"])
    response = endpoint.submit(doc)
    assert response.status_code == (422 if change == "source_changed" else 404 if change == "not_found" else 409)
    assert not endpoint.calls and "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("error,calls", [(BlockingWorkOverloaded, 0), (BlockingWorkTimeout, 1), (RuntimeError, 1)])
def test_worker_failures_keep_complete_manifest_but_no_plan(endpoint, monkeypatch, caplog, error, calls):
    async def fail_worker(*args, **kwargs):
        raise error("PRIVATE provider exception")
    monkeypatch.setattr(route, "run_blocking", fail_worker)
    result = unavailable(endpoint.submit(endpoint.doc()), "invalid_model_response" if error is RuntimeError else "timeout", calls=calls)
    assert len(result["manifest"]) == 2 and not endpoint.calls and "PRIVATE" not in caplog.text


def test_spend_budget_is_checked_inside_the_actual_worker(endpoint, monkeypatch):
    monkeypatch.setattr(ai.llm_budget, "exhausted", lambda: True)
    unavailable(endpoint.submit(endpoint.doc()), "budget_exhausted", calls=0)
    assert not endpoint.calls


def test_quote_offsets_are_exact_unicode_codepoints(endpoint):
    doc = endpoint.doc(["I wrote tests 🧪 中文 using Python."])
    def quote(result, data):
        line = data["blocks"][0]["lines"][-1]
        original = line["original"]
        start = original.index("🧪")
        result["items"][0]["source_evidence"] = [{"unit_id": line["unit_id"], "start": start, "end": start + 4, "quote": "🧪 中文"}]
    endpoint.mutate = quote
    completed(endpoint, endpoint.submit(doc), doc)


def test_new_path_feature_private_and_body_cap_are_registered(endpoint):
    assert main._release_feature_for_path(PATH) == "resume_renovate"
    assert MAX_BODY_BYTES == 2 * 1024 * 1024 + 64 * 1024
    async def exercise(path, size):
        calls, events = [], []
        async def application(scope, receive, send):
            calls.append(scope["path"])
        async def receive():
            return {"type": "http.request", "body": b""}
        async def send(event):
            events.append(event)
        middleware = main.RequestBodyLimitMiddleware(application, max_bytes=10, full_target_max_bytes=20)
        await middleware({"type": "http", "path": path, "headers": [(b"content-length", str(size).encode())]}, receive, send)
        return calls, events
    assert asyncio.run(exercise(PATH, 15))[0] == [PATH]
    calls, events = asyncio.run(exercise(PATH, 21))
    assert not calls and events[0]["status"] == 413
    assert not asyncio.run(exercise("/api/other", 15))[0]


@pytest.mark.parametrize("kind,skill,locale", [("research", "Python", "en"), ("internship", "MATLAB", "zh")])
def test_two_authoritative_contexts_and_locales_reach_the_model_in_full(endpoint, kind, skill, locale):
    endpoint.opportunity.update(opportunity_type=kind, title=f"{skill} {kind}", organization=f"{skill} Laboratory",
                                description_clean=f"研究 {skill} 工具与数据 🧪.")
    endpoint.opportunity["eligibility"]["skills_required"] = [skill]
    doc = endpoint.doc([f"I wrote tests using {skill}."])
    data = payload(doc, 2)
    data["locale"] = locale
    result = completed(endpoint, endpoint.client.post(PATH, json=data), doc)
    prompt = json.loads(endpoint.calls[0][0][1]["content"])
    assert prompt["locale"] == locale and prompt["target"] == doc["target_snapshot"]
    assert result["items"][0]["target_evidence"][0]["quote"] == skill


def test_whole_plan_covers_education_publications_skills_and_other_blocks(endpoint):
    doc = endpoint.doc([ORIGINAL])
    master = doc["base_snapshot"]["resume_master"]
    master["education"] = [{"id": "education-1", "school": _fact("school-1", "Example University"), "details": []}]
    master["publications"] = [{"id": "publication-1", "title": _fact("paper-title", "Submitted parser paper"), "details": []}]
    master["skills"] = [_fact("skill-1", "Python")]
    master["other_sections"] = [{"id": "other-1", "heading": "Other", "items": [_fact("other-item", "Additional confirmed text")]}]
    master["section_order"].append("other-1")
    doc["document"] = confirmed_document(doc["base_snapshot"], doc["base"]["source_signature"])
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for line in block["lines"]:
                line.update(text=line["original"], included=True)
    result = completed(endpoint, endpoint.submit(doc), doc)
    assert [row["section_id"] for row in result["manifest"]] == ["education", "activities", "publications", "skills", "other-1"]


@pytest.mark.parametrize("raw", [None, "", "{}", '{"items":null}', '{"items":[]}'])
def test_provider_empty_or_malformed_output_is_not_a_complete_plan(endpoint, monkeypatch, raw):
    def model(*args, **kwargs):
        endpoint.calls.append(1)
        return raw
    monkeypatch.setattr(ai, "chat_completion", model)
    unavailable(endpoint.submit(endpoint.doc()), "model_unavailable" if not raw else "invalid_model_response")
    assert len(endpoint.calls) == 1


def test_source_check_version_is_negotiated_and_server_owned(endpoint, monkeypatch):
    doc = endpoint.doc()
    request = payload(doc)
    legacy = endpoint.client.post(PATH, json=request)
    assert legacy.status_code == 200
    assert "check_version" not in legacy.json()
    request["include_check_version"] = True
    response = endpoint.client.post(PATH, json=request)
    assert response.status_code == 200
    assert response.json()["check_version"] == "target-resume-source-checks-v3"
    assert response.json()["pipeline_version"] != response.json()["check_version"]
    # Available rules do not turn skipped/failed work into a checked rewrite.
    monkeypatch.setattr(route, "is_configured", lambda: False)
    failed = endpoint.client.post(PATH, json=request)
    assert failed.status_code == 200
    assert failed.json()["check_version"] == "target-resume-source-checks-v3"
    assert failed.json()["method"] == "unavailable"
    forged = {**request, "check_version": "target-resume-source-checks-v999"}
    assert endpoint.client.post(PATH, json=forged).status_code == 422
    for value in ("true", 1, None):
        assert endpoint.client.post(PATH, json={**request, "include_check_version": value}).status_code == 422
