"""Provider-free full-document contract, provenance, budget and failure tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.lib import evidence_map
from backend.lib import target_resume_ai as engine
from backend.lib.evidence_map import target_anchors
from backend.lib.target_resume_ai_schema import MAX_DIRECTION_CHARACTERS, MAX_PROMPT_CHARACTERS, FullTargetRequest
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
    target = route.authoritative_target({
        "id": "target", "title": "Research", "organization": "Example Lab", "source_url": "https://example.edu/lab",
        "description_clean": "Research robots 🧪 with Python.", "eligibility": {"skills_required": ["Python"]},
        "source_type": "campus_program", "opportunity_type": "research", "metadata": {"is_active": True},
    })
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


def row(unit_id, *, priority="high", reason="method_relevance", links=(), text=None, ops=(), keep_reason="no_link"):
    """One v6 evidence-map row: a keep, or with ``text`` a rewrite."""
    return {"unit_id": unit_id, "priority": priority, "reason": reason, "links": list(links),
            "decision": "rewrite" if text else "keep", "ops": list(ops), "text": text,
            "keep_reason": None if text else keep_reason}


# make_doc's target: t1 is the description sentence, t2 the "Python" requirement.
PYTHON = {"id": "L1", "anchor": "t2", "term": "Python", "source": "Python", "relation": "same"}


def output(doc, ids=None):
    """Every requested unit kept, linked to the Python requirement where its original says Python."""
    return {"units": [row(unit["unit_id"], links=[PYTHON] if "Python" in unit["original"] else [],
                          keep_reason="already_aligned" if "Python" in unit["original"] else "no_link")
                      for unit in units_for(doc)[0] if ids is None or unit["unit_id"] in ids]}


def anchors_of(doc):
    return target_anchors(doc["target_snapshot"])


def accept_all(monkeypatch):
    """A reviewer that accepts every pair and every link."""
    def accept(pairs, deadline=None):
        for pair in pairs:
            for link in pair.links:
                link.entailed = True
        return ["accepted"] * len(pairs)

    monkeypatch.setattr(evidence_map, "ai_review", accept)


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
    assert body["pipeline_version"] == "full-target-v6"
    assert [row["status"] for row in body["receipts"]] == ["suggested", "unchanged", "suggested"]
    assert "private" in response.headers["cache-control"] and "no-store" in response.headers["cache-control"]
    prompt = calls[0][0][1]["content"]
    assert "UNCONFIRMED" not in prompt and "Private Student" not in prompt
    assert doc["base_snapshot"]["experience_entries"][0]["text"] in prompt
    # One experience and two fact lines: the output budget is sized to them.
    assert calls[0][1]["max_tokens"] == 350 + 320 + 2 * 120 and calls[0][1]["require_complete"] is True
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


EXPERIENCE = "Built a Python robot with a team of 3. I did not lead the project."
OWN_PART_FIRST = "I did not lead the project. Built a Python robot with a team of 3."


@pytest.mark.parametrize(("kind", "skipped", "unchanged"), [
    ("unknown", {"line-2": "missing_result"}, {"line-3": "already_aligned"}),
    ("duplicate", {"line-2": "missing_result"}, {"line-3": "already_aligned"}),
    ("fact_rewrite", {"line-2": "invalid_model_response"}, {"line-3": "already_aligned"}),
    ("bad_row", {"line-3": "invalid_model_response"}, {}),
    ("borrowed_number", {}, {"line-3": "beyond_allowed_edit"}),
    ("missing", {"line-4": "missing_result"}, {"line-3": "already_aligned"}),
])
def test_model_output_failures_have_exact_receipts(endpoint, monkeypatch, kind, skipped, unchanged):
    client, doc, _, _ = endpoint
    data = output(doc)
    if kind == "unknown":
        data["units"][0]["unit_id"] = "unknown"
    elif kind == "duplicate":
        data["units"].append(data["units"][0])
    elif kind == "fact_rewrite":
        data["units"][0].update(decision="rewrite", text="Invented fact", keep_reason=None, ops=[{"op": "verb_first"}])
    elif kind == "bad_row":
        data["units"][1]["priority"] = "urgent"
    elif kind == "borrowed_number":
        data["units"][1].update(decision="rewrite", keep_reason=None, ops=[{"op": "personal_first"}],
                                text=EXPERIENCE + " The robot weighed 999 kg.")
    else:
        data["units"].pop()
    monkeypatch.setattr(engine, "chat_completion", lambda *args, **kwargs: json.dumps(data))
    response = client.post(PATH, json=payload(doc)).json()
    assert [row["unit_id"] for row in response["receipts"]] == ["line-2", "line-3", "line-4"]
    assert {row["unit_id"]: row["reason_code"] for row in response["receipts"] if row["status"] == "skipped"} == skipped
    assert {row["unit_id"]: row["reason_code"] for row in response["receipts"] if row["status"] == "unchanged"} == unchanged
    assert all(row["suggestion"] is None for row in response["receipts"] if row["status"] == "skipped")
    assert response["method"] == ("partial" if skipped else "ai")


def test_a_reviewed_rewrite_is_suggested_with_its_ops_and_reason(endpoint, monkeypatch):
    client, doc, _, calls = endpoint
    accept_all(monkeypatch)
    data = output(doc)
    data["units"][1].update(decision="rewrite", keep_reason=None, ops=[{"op": "personal_first"}], text=OWN_PART_FIRST)
    monkeypatch.setattr(engine, "chat_completion", lambda *args, **kwargs: json.dumps(data))
    body = client.post(PATH, json=payload(doc)).json()
    receipt = body["receipts"][1]
    assert receipt["status"] == "suggested" and receipt["reason_code"] is None
    suggestion = receipt["suggestion"]
    assert suggestion["proposed_text"] == OWN_PART_FIRST and suggestion["ops"] == ["personal_first"]
    assert suggestion["alternative_text"] is None
    assert "Puts your own part first." in suggestion["reason"]
    # One generation call and one review call, each with its retry bound.
    assert body["logical_calls"] == 2 and body["provider_attempts_upper_bound"] == 4


@pytest.mark.parametrize(("verdict", "status", "code"), [
    ("rejected", "unchanged", "review_rejected"), ("unavailable", "skipped", "rewrite_unchecked"),
])
def test_an_unaccepted_rewrite_keeps_its_advice_or_stays_retryable(endpoint, monkeypatch, verdict, status, code):
    client, doc, _, _ = endpoint
    monkeypatch.setattr(evidence_map, "ai_review", lambda pairs, deadline=None: None if verdict == "unavailable"
                        else ["rejected"] * len(pairs))
    data = output(doc)
    data["units"][1].update(decision="rewrite", keep_reason=None, ops=[{"op": "personal_first"}], text=OWN_PART_FIRST)
    monkeypatch.setattr(engine, "chat_completion", lambda *args, **kwargs: json.dumps(data))
    receipt = client.post(PATH, json=payload(doc)).json()["receipts"][1]
    assert (receipt["status"], receipt["reason_code"]) == (status, code)
    if status == "unchanged":
        assert receipt["suggestion"]["proposed_text"] is None and receipt["suggestion"]["priority"] == "high"
    else:
        assert receipt["suggestion"] is None


def test_high_priority_without_a_verified_link_is_normal(endpoint, monkeypatch):
    client, doc, _, _ = endpoint
    data = output(doc)
    data["units"][2]["links"] = [{**PYTHON, "term": "Pyth"}]
    monkeypatch.setattr(engine, "chat_completion", lambda *args, **kwargs: json.dumps(data))
    receipt = client.post(PATH, json=payload(doc)).json()["receipts"][2]
    assert receipt["suggestion"]["priority"] == "normal" and receipt["suggestion"]["links"] == []
    assert receipt["suggestion"]["target_evidence"] == []


def test_link_quotes_carry_server_offsets(endpoint):
    client, doc, _, _ = endpoint
    receipt = client.post(PATH, json=payload(doc)).json()["receipts"][2]
    [link] = receipt["suggestion"]["links"]
    assert link["target_evidence"] == {"field": "requirement", "requirement_index": 0, "start": 0, "end": 6,
                                       "quote": "Python"}
    assert link["source_evidence"] == {"unit_id": "line-4", "start": 0, "end": 6, "quote": "Python"}
    assert link["entailed"] is False  # advice: never reviewed, shown as the opportunity's own words
    assert receipt["suggestion"]["target_evidence"] == [link["target_evidence"]]


def test_a_target_with_no_quotable_text_costs_no_call(endpoint):
    client, doc, opp, calls = endpoint
    opp["description_clean"] = ("Faculty research profile for Pat Lee in Physics at Example University. Research areas: "
                                "robots, sensors, Python Contact this faculty member to ask whether undergraduate "
                                "research opportunities are currently available.")
    opp["eligibility"]["skills_required"] = []
    doc["target_snapshot"] = route.authoritative_target(opp)
    doc["base"]["target_signature"] = fingerprint(doc["target_snapshot"])
    body = client.post(PATH, json=payload(doc)).json()
    assert {row["reason_code"] for row in body["receipts"]} == {"target_has_no_text"}
    assert body["logical_calls"] == 0 and body["method"] == "unavailable" and not calls
    # The same list is quotable once the record states it as its own research areas.
    opp["metadata"]["research_areas_raw"] = "robots, sensors, Python"
    body = client.post(PATH, json=payload(doc)).json()
    assert body["method"] == "ai" and len(calls) == 1


def test_more_than_eight_experiences_in_one_request_are_refused(endpoint):
    client, doc, _, calls = endpoint
    entries = doc["base_snapshot"]["experience_entries"]
    activity = doc["base_snapshot"]["resume_master"]["activities"][0]
    for index in range(1, 9):
        entries.append({"id": f"exp-{index}", "revision": 1, "status": "confirmed", "text": f"Built robot {index}.",
                        "source": {"kind": "manual"}})
        activity["details"].append({"id": f"exp-{index}", "revision": 1})
    doc["document"] = confirmed_document(doc["base_snapshot"], doc["base"]["source_signature"])
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for line in block["lines"]:
                line.update(text=line["original"], included=True)
    experiences = [unit["unit_id"] for unit in units_for(doc)[0] if unit["evidence"]["kind"] == "experience"]
    assert len(experiences) == 9
    assert client.post(PATH, json=payload(doc, experiences)).status_code == 422 and not calls
    assert client.post(PATH, json=payload(doc, experiences[:8])).status_code == 200


def test_target_quote_offsets_use_codepoints_and_require_literal_match():
    target = {"description": "A🧪中文Z", "requirements": []}
    quote = {"field": "description", "requirement_index": None, "start": 1, "end": 4, "quote": "🧪中文"}
    assert engine.valid_quotes([quote], target) == [quote]
    # A miscounted end is re-anchored to the literal codepoint span, not rejected.
    assert engine.valid_quotes([{**quote, "end": 5}], target) == [quote]
    assert engine.valid_quotes([{**quote, "quote": "🧪中文Y"}], target) is None
    assert engine.valid_quotes([{**quote, "quote": "中文🧪"}], target) is None


KINESIOLOGY = "Department of Health and Kinesiology at University of Illinois"
KINESIOLOGY_DESCRIPTION = ("We study movement science with wearable sensors and field studies. "
                           "The lab is part of the " + KINESIOLOGY + " and welcomes undergraduates.")


def rich_target():
    return {"context_version": 4, "description": "Build 😀中文 sensors; build again.",
            "requirements": ["Python", "MATLAB and Python"],
            "research": {"status": "available", "snapshot": {"works": [
                {"title": "Robot 😀 Grasping", "abstract": "We study grasping.", "abstract_status": "present"},
                {"title": "Soft Sensors", "abstract": "", "abstract_status": "missing"}]}},
            "lab": {"status": "available", "snapshot": {"pages": [{"sections": [
                {"heading": "实验室😀研究", "text": "We study Python sensors."},
                {"heading": "Methods", "text": "Causal inference."}]}]}}}


def test_real_model_quote_with_miscounted_offsets_is_reanchored_to_its_literal_span():
    # Measured shape: literal quote, 62 codepoints, but the model sent start 95, end 154.
    target = {"description": KINESIOLOGY_DESCRIPTION, "requirements": []}
    quote = {"field": "description", "requirement_index": None, "start": 95, "end": 154, "quote": KINESIOLOGY}
    assert len(KINESIOLOGY) == 62 and KINESIOLOGY_DESCRIPTION[95:154] != KINESIOLOGY
    start = KINESIOLOGY_DESCRIPTION.index(KINESIOLOGY)
    assert engine.valid_quotes([quote], target) == [{**quote, "start": start, "end": start + 62}]
    assert quote["start"] == 95  # the model's row is not mutated


@pytest.mark.parametrize("quote", [
    {"field": "description", "requirement_index": None, "start": 0, "end": 5, "quote": "Invented"},
    {"field": "description", "requirement_index": None, "start": 0, "end": 1, "quote": " "},
    {"field": "requirement", "requirement_index": 0, "start": 0, "end": 6, "quote": "MATLAB"},
    {"field": "requirement", "requirement_index": 2, "start": 0, "end": 6, "quote": "Python"},
    {"field": "requirement", "requirement_index": 0, "start": None, "end": 6, "quote": "Python"},
    {"field": "paper_title", "paper_index": 1, "start": 0, "end": 5, "quote": "Robot"},
    {"field": "paper_abstract", "paper_index": 0, "start": 0, "end": 7, "quote": "Robot 😀"},
    {"field": "paper_abstract", "paper_index": 1, "start": 0, "end": 1, "quote": "S"},
    {"field": "lab_text", "page_index": 0, "section_index": 0, "start": 0, "end": 6, "quote": "Causal"},
    {"field": "lab_heading", "page_index": 0, "section_index": 1, "start": 0, "end": 3, "quote": "实验室"},
])
def test_quote_absent_from_its_named_field_is_still_rejected(quote):
    assert engine.valid_quotes([quote], rich_target()) is None


@pytest.mark.parametrize(("quote", "start"), [
    ({"field": "description", "requirement_index": None, "start": 30, "end": 31, "quote": "build"}, 19),
    ({"field": "description", "requirement_index": None, "start": 99, "end": 1, "quote": "中文 sensors"}, 7),
    ({"field": "requirement", "requirement_index": 1, "start": 0, "end": 6, "quote": "Python"}, 11),
    ({"field": "paper_title", "paper_index": 0, "start": 0, "end": 3, "quote": "😀 Grasping"}, 6),
    ({"field": "paper_abstract", "paper_index": 0, "start": 5, "end": 9, "quote": "grasping"}, 9),
    ({"field": "lab_heading", "page_index": 0, "section_index": 0, "start": 0, "end": 2, "quote": "😀研究"}, 3),
    ({"field": "lab_text", "page_index": 0, "section_index": 1, "start": -4, "end": 0, "quote": "inference"}, 7),
])
def test_quote_is_reanchored_by_codepoints_within_its_named_field(quote, start):
    assert engine.valid_quotes([quote], rich_target()) == [{**quote, "start": start, "end": start + len(quote["quote"])}]


@pytest.mark.parametrize(("hint", "expected"), [(0, 0), (-5, 0), (1, 0), (2, 0), (3, 4), (5, 4), (6, 4), (7, 8), (99, 8)])
def test_repeated_quote_anchors_to_nearest_occurrence_and_ties_go_earliest(hint, expected):
    # "ab" starts at codepoints 0, 4 and 8; hints 2 and 6 are exact ties.
    target = {"description": "ab😀😀ab中文ab", "requirements": []}
    quote = {"field": "description", "requirement_index": None, "start": hint, "end": hint + 2, "quote": "ab"}
    assert engine.valid_quotes([quote], target) == [{**quote, "start": expected, "end": expected + 2}]


def test_source_quotes_are_reanchored_inside_the_named_original_only():
    originals = {"a": "Built 😀 robot; built a robot arm.", "b": "Wrote tests."}
    quote = {"unit_id": "a", "start": 50, "end": 60, "quote": "robot arm"}
    assert engine.valid_source_quotes([quote], originals) == [{**quote, "start": 23, "end": 32}]
    assert engine.valid_source_quotes([{**quote, "start": 0, "quote": "robot"}], originals)[0]["start"] == 8
    assert engine.valid_source_quotes([{**quote, "unit_id": "b"}], originals) is None
    assert engine.valid_source_quotes([{**quote, "quote": "robot legs"}], originals) is None
    assert engine.valid_source_quotes([{**quote, "unit_id": "c"}], originals) is None


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
    messages, reason = engine.batch_preflight(checked, processable, "en", anchors_of(checked))
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
    # Fake model returns unsolicited IDs too; they are ignored, never attached elsewhere.
    assert response.status_code == 200 and response.json()["method"] == "ai"
    assert [row["unit_id"] for row in response.json()["receipts"]] == ["line-4"]
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
    by_kind = {unit["unit_id"]: unit["evidence"]["kind"] for unit in units_for(doc)[0]}
    for unit in units_for(doc)[0]:
        original_size = len(unit["original"])
        experience_size = original_size if unit["evidence"]["kind"] == "experience" else 0
        if (len(current) == 20 or size + original_size > 16000 or experiences + experience_size > 6000
                or (experience_size and sum(1 for ident in current if ident.startswith("line-") and
                                            by_kind.get(ident) == "experience") == 8)):
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


def crowd_prompt(doc, opp, title, skill, interests="i" * 8000):
    # Every unit is within the original budgets; only the context repeated in
    # one combined prompt (target, direction, whole-block facts) overflows it.
    opp["eligibility"]["skills_required"] = ["Python", "r" * 11000]
    doc["target_snapshot"] = route.authoritative_target(opp)
    doc["base"]["target_signature"] = fingerprint(doc["target_snapshot"])
    doc["base_snapshot"]["research_interests"] = interests
    doc["base_snapshot"]["resume_master"]["activities"][0]["title"]["value"] = title
    doc["document"]["sections"][1]["blocks"][0]["lines"][0].update(original=title, text=title)
    doc["base_snapshot"]["resume_master"]["skills"][0]["value"] = skill
    doc["document"]["sections"][2]["blocks"][0]["lines"][0].update(original=skill, text=skill)


# v6 sends anchors, not the whole target twice, so its fixed prompt is about
# 28k characters; a lower cap reproduces a crowded request within the unit caps.
CROWDED_PROMPT = 50000


def test_combined_overflow_is_retryable_for_units_that_fit_alone(endpoint, monkeypatch):
    client, doc, opp, calls = endpoint
    monkeypatch.setattr(engine, "MAX_PROMPT_CHARACTERS", CROWDED_PROMPT)
    crowd_prompt(doc, opp, "T" * 8000, "S" * 7000)
    body = client.post(PATH, json=payload(doc)).json()
    assert [row["reason_code"] for row in body["receipts"]] == ["batch_context_too_large"] * 3
    assert body["logical_calls"] == 0 and not calls

    def model(messages, **kwargs):
        requested = [unit["unit_id"] for unit in json.loads(messages[1]["content"])["units"]]
        return json.dumps(output(doc, requested))

    monkeypatch.setattr(engine, "chat_completion", model)
    for ident in ("line-2", "line-3", "line-4"):
        single = client.post(PATH, json=payload(doc, [ident])).json()
        assert single["method"] == "ai" and single["logical_calls"] == 1, (ident, single["receipts"])


def test_only_a_unit_too_large_on_its_own_is_permanently_skipped(endpoint, monkeypatch):
    client, doc, opp, calls = endpoint
    monkeypatch.setattr(engine, "MAX_PROMPT_CHARACTERS", CROWDED_PROMPT)
    crowd_prompt(doc, opp, "T" * 12500, "S" * 3000)
    body = client.post(PATH, json=payload(doc)).json()
    assert {row["unit_id"]: row["reason_code"] for row in body["receipts"]} == {
        "line-2": "context_too_large", "line-3": "batch_context_too_large", "line-4": "batch_context_too_large"}
    assert client.post(PATH, json=payload(doc, ["line-2"])).json()["receipts"][0]["reason_code"] == "context_too_large"
    assert not calls


def test_long_research_interests_are_refused_by_name_and_never_clipped(endpoint):
    client, doc, _, calls = endpoint
    doc["base_snapshot"]["research_interests"] = "interest " * 3888 + "TAIL"
    body = client.post(PATH, json=payload(doc)).json()
    assert [row["reason_code"] for row in body["receipts"]] == ["interests_too_large"] * 3
    assert body["logical_calls"] == 0 and not calls
    doc["base_snapshot"]["research_interests"] = "i" * 7996 + "TAIL"
    assert client.post(PATH, json=payload(doc)).json()["method"] == "ai"
    assert json.loads(calls[0][0][1]["content"])["student_direction"]["research_interests"] == "i" * 7996 + "TAIL"


def test_browser_prompt_estimate_constants_match_the_server():
    protocol = (Path(__file__).parents[1] / "frontend/src/lib/target-resume-ai-protocol.ts").read_text()

    def constant(name):
        return int(re.search(rf"export const {name} = ([0-9_]+);", protocol)[1].replace("_", ""))

    assert constant("FULL_TARGET_AI_SYSTEM_PROMPT_CHARACTERS") == len(engine.SYSTEM_PROMPT)
    assert constant("FULL_TARGET_AI_MAX_INTERESTS_CHARACTERS") == MAX_DIRECTION_CHARACTERS
    assert constant("FULL_TARGET_AI_MAX_PROMPT_CHARACTERS") == MAX_PROMPT_CHARACTERS


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


def test_saturated_worker_pool_is_a_timeout_receipt_not_a_500(endpoint, monkeypatch):
    # The overloaded branch unpacked two values into three names, so a full
    # blocking pool turned into an unhandled ValueError and a 500 for every
    # student asking for suggestions while the pool was busy.
    from backend.lib.blocking import BlockingWorkOverloaded
    client, doc, _, calls = endpoint

    async def overloaded(*args, **kwargs):
        raise BlockingWorkOverloaded()

    monkeypatch.setattr(route, "run_blocking", overloaded)
    response = client.post(PATH, json=payload(doc))
    assert response.status_code == 200
    body = response.json()
    assert all(row["reason_code"] == "timeout" and row["suggestion"] is None for row in body["receipts"])
    assert body["logical_calls"] == 0 and not calls


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


def _parse_one(original, proposed, ops):
    doc = make_doc()
    unit = next(unit for unit in units_for(doc)[0] if unit["evidence"]["kind"] == "experience")
    unit.update(original=original, before_text=original)
    data = {"units": [row(unit["unit_id"], text=proposed, ops=ops)]}
    locale = "zh" if evidence_map.language(proposed) == "zh" else "en"
    return engine.parse_output(json.dumps(data), [unit], anchors_of(doc), locale)


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
    for ops in ([{"op": "personal_first"}], [{"op": "verb_first"}]):
        results, pending = _parse_one(original, proposed, ops)
        assert pending == [] and results[0]["status"] == "unchanged"
        assert results[0]["reason_code"] in ("beyond_allowed_edit", "rewrite_rejected")
        assert results[0]["suggestion"]["proposed_text"] is None


@pytest.mark.parametrize(("original", "proposed", "ops"), [
    ("Our team built a Python parser. I reviewed the documentation.",
     "I reviewed the documentation. Our team built a Python parser.", [{"op": "personal_first"}]),
    ("团队开发了工具。本人负责审阅文档。", "本人负责审阅文档。团队开发了工具。", [{"op": "personal_first"}]),
    ("The project was submitted for review, not accepted.", "The project was submitted for review, not accepted.",
     [{"op": "verb_first"}]),
])
def test_legal_preservation_of_sensitive_claims_still_allows_suggestions(original, proposed, ops):
    results, pending = _parse_one(original, proposed, ops)
    # A faithful reorder goes to the review; the original itself is a cosmetic keep with its advice.
    assert [item.outcome.text for item in pending] == [proposed] or (
        results[0]["status"] == "unchanged" and results[0]["reason_code"] == "cosmetic_only"
        and results[0]["suggestion"] is not None)


def test_whole_block_context_is_sent_once_for_many_selected_lines():
    doc = make_doc()
    title = "T" * 10000
    master = doc["base_snapshot"]["resume_master"]
    master["activities"][0]["title"]["value"] = title
    entries = [{"id": f"short-{i}", "revision": 1, "status": "confirmed", "text": "Built a small Python tool.",
                "source": {"kind": "manual"}} for i in range(8)]
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
    messages, reason = engine.batch_preflight(checked, processable, "en", anchors_of(checked))
    assert reason is None and len(processable) == 9
    model_input = json.loads(messages[1]["content"])
    assert len(model_input["block_contexts"]) == 1
    assert model_input["block_contexts"][0]["fields"][0]["value"] == title
    assert all("block_context" not in unit for unit in model_input["units"])
    assert len(model_input["units"]) == 9
    # Criteria and the opportunity stay context; only the anchors are quotable.
    assert set(model_input) == {"locale", "opportunity", "anchors", "criteria", "block_contexts", "units"}
    assert sum(len(message["content"]) for message in messages) < 60000


def test_source_check_version_is_negotiated_and_server_owned(endpoint, monkeypatch):
    client, doc, _, calls = endpoint
    request = payload(doc)
    legacy = client.post(PATH, json=request)
    assert legacy.status_code == 200
    assert "check_version" not in legacy.json()
    request["include_check_version"] = True
    response = client.post(PATH, json=request)
    assert response.status_code == 200
    assert response.json()["check_version"] == "target-resume-source-checks-v4"
    assert response.json()["pipeline_version"] != response.json()["check_version"]
    # Available rules do not turn skipped/failed work into a checked rewrite.
    monkeypatch.setattr(route, "is_configured", lambda: False)
    failed = client.post(PATH, json=request)
    assert failed.status_code == 200
    assert failed.json()["check_version"] == "target-resume-source-checks-v4"
    assert failed.json()["method"] == "unavailable"
    forged = {**request, "check_version": "target-resume-source-checks-v999"}
    assert client.post(PATH, json=forged).status_code == 422
    for value in ("true", 1, None):
        assert client.post(PATH, json={**request, "include_check_version": value}).status_code == 422
