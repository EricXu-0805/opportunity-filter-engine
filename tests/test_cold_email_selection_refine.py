"""Selected email edits retain exact browser ranges; all providers are local stubs."""
import hashlib
import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.lib.email_contact_context import contact_context_receipt
from backend.routes import cold_email as ce
from tests.experience_fixtures import confirmed_experience

PROFILE = {"name": "Audit Student", "school": "UIUC", "year": "sophomore", "major": "Computer Science",
           "hard_skills": [], "coursework": [], "research_interests_text": "Python parser research"}
OPP = {"id": "selection-target", "source_type": "campus_program", "opportunity_type": "research",
       "title": "Research Tools", "pi_name": "Pat Lee", "organization": "Test University",
       "keywords": ["Python parser", "Linux setup"], "description_raw": "Research on Python parser tools and Linux setup.",
       "eligibility": {"skills_required": []}, "application": {}, "metadata": {"is_active": True}}
TEAM = "My role: I wrote parser tests. Outcome: My team built a Python parser. I did not build the parser."
OLD = "I am interested in Python parser research."
NEW = "I would welcome a conversation about Python parser research."


def body(text=OLD, newline="\n"):
    return newline.join(["Dear Pat Lee,", "", text, "", "Could we discuss Python parser research?", "", "Best regards,", "Audit Student"])


def utf16(value):
    return len(value.encode("utf-16-le")) // 2


def selected(text, whole, *, last=False):
    index = whole.rindex(text) if last else whole.index(text)
    return {"start_utf16": utf16(whole[:index]), "end_utf16": utf16(whole[:index + len(text)]), "text": text}


def payload(whole=None, text=OLD, evidence=(), **updates):
    whole = body() if whole is None else whole
    return {"profile": PROFILE, "opportunity_id": OPP["id"], "current_body": whole,
            "subject": "Research inquiry", "instruction": "Make only this selection clearer.",
            "selection": selected(text, whole), "experience_evidence": confirmed_experience(list(evidence)), **updates}


@pytest.fixture
def environment(monkeypatch):
    app = FastAPI(); app.include_router(ce.router, prefix="/api")
    current = deepcopy(OPP); calls = []
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: current})
    monkeypatch.setattr(ce, "corpus_version", lambda: "selection-fixture")
    monkeypatch.setattr(ce, "is_configured", lambda: True)

    def provider(messages, **kwargs):
        calls.append((messages, kwargs))
        return json.dumps({"replacement": NEW})

    monkeypatch.setattr(ce, "chat_completion", provider)

    def unexpected(*_args, **_kwargs):
        pytest.fail("A selection edit must not rebuild an entire template")

    monkeypatch.setattr(ce, "_local_refine_fallback", unexpected)
    return TestClient(app), calls, current


def request(environment, value=None):
    client, _calls, _current = environment
    return client.post("/api/cold-email/refine", json=payload() if value is None else value)


def splice(whole, proposal):
    encoded = whole.encode("utf-16-le")
    before = encoded[:proposal["start_utf16"] * 2].decode("utf-16-le")
    after = encoded[proposal["end_utf16"] * 2:].decode("utf-16-le")
    return before + proposal["replacement"] + after


def proposal(environment, value=None):
    value = payload() if value is None else value
    response = request(environment, value)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["outcome"] == "proposal", result
    assert result["scope"] == "selection" and result["method"] == "llm"
    assert "body" not in result
    assert result["proposal"]["base_body_sha256"] == hashlib.sha256(value["current_body"].encode()).hexdigest()
    assert result["proposal"]["original_text"] == value["selection"]["text"]
    return result["proposal"], result


def no_change(environment, value, reason):
    response = request(environment, value)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["scope"] == "selection" and result["outcome"] == "no_change", result
    assert result["reason"] == reason, result
    assert "proposal" not in result and "body" not in result
    return result


def test_exact_patch_and_standard_target_contact_receipts(environment):
    value = payload(); before = deepcopy(value)
    patch, result = proposal(environment, value)
    assert splice(value["current_body"], patch) == body(NEW)
    assert value == before
    assert result["opportunity_id"] == OPP["id"] and result["target_version"].startswith("wt1:")
    assert result["contact_context_receipt"] == contact_context_receipt(None)
    assert "pipeline_version" in result and "experience_usage" in result
    assert len(environment[1]) == 1


def test_second_repeated_paragraph_is_the_only_changed_occurrence(environment):
    whole = body(OLD + "\n\n" + OLD)
    value = payload(whole, selection=selected(OLD, whole, last=True))
    patch, _ = proposal(environment, value)
    assert splice(whole, patch) == body(OLD + "\n\n" + NEW)


@pytest.mark.parametrize("prefix,selection_text,suffix", [
    ("中文😀 e\u0301\n", OLD, "\n保留末尾🧪"),
    ("", "中文😀\n" + OLD, ""),
    ("中文\r\n", OLD + "\r\n\r\n更多中文", "\r\n尾行"),
    ("", OLD, "\n\n"),
])
def test_utf16_unicode_combining_and_multiline_ranges_stay_exact(environment, prefix, selection_text, suffix):
    whole = body(prefix + selection_text + suffix)
    value = payload(whole, selection_text)
    patch, _ = proposal(environment, value)
    assert splice(whole, patch) == body(prefix + NEW + suffix)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_line_endings_and_surrounding_whitespace_are_not_normalized(environment, newline):
    whole = " \t" + newline + body(newline=newline) + newline + " \t"
    patch, _ = proposal(environment, payload(whole))
    assert splice(whole, patch) == whole.replace(OLD, NEW, 1)


def test_full_context_and_instruction_after_old_truncation_limits_reach_provider(environment):
    whole = body(("plain words " * 280) + "\n\n" + OLD + "\nTAIL_MARKER_完整")
    instruction = "please " * 50 + "FINAL_INSTRUCTION_MARKER"
    assert len(whole) > 3000 and len(instruction) > 300
    value = payload(whole, instruction=instruction)
    response = request(environment, value)
    assert response.status_code == 200
    user_prompt = environment[1][0][0][1]["content"]
    inputs = json.loads(user_prompt.split("Editing inputs (not evidence):\n", 1)[1])
    assert inputs["current_body"] == whole and inputs["instruction"] == instruction
    assert inputs["subject"] == value["subject"]


@pytest.mark.parametrize("change", [
    {"start_utf16": -1}, {"start_utf16": 1.5}, {"start_utf16": True}, {"start_utf16": "2"},
    {"end_utf16": 5001}, {"end_utf16": False}, {"end_utf16": 1.1},
    {"start_utf16": 30, "end_utf16": 20}, {"start_utf16": 20, "end_utf16": 20},
    {"text": "wrong occurrence"}, {"text": None}, {"extra": "do not ignore"},
])
def test_invalid_selection_is_422_before_provider(environment, change):
    value = payload(); value["selection"].update(change)
    response = request(environment, value)
    assert response.status_code == 422, response.text
    assert environment[1] == []
    assert all("input" not in error for error in response.json()["detail"])


@pytest.mark.parametrize("which", ["start_utf16", "end_utf16"])
def test_surrogate_pair_boundary_cannot_be_split(environment, which):
    whole = body("😀" + OLD); value = payload(whole)
    emoji_offset = utf16(whole[:whole.index("😀")])
    value["selection"] = {"start_utf16": emoji_offset, "end_utf16": emoji_offset + 2, "text": "😀"}
    value["selection"][which] = emoji_offset + 1
    assert request(environment, value).status_code == 422
    assert environment[1] == []


@pytest.mark.parametrize("field,value", [
    ("current_body", "x" * 5001), ("current_body", "😀" * 2501), ("current_body", "x\ud800"),
    ("current_body", "x\x00"), ("instruction", "x" * 501), ("instruction", "😀" * 251),
    ("instruction", " "), ("subject", "x" * 2001), ("subject", "bad\udc00"),
])
def test_limits_reject_instead_of_silently_truncating(environment, field, value):
    data = payload(); data[field] = value
    # ensure_ascii lets deliberately invalid Unicode exercise the JSON API,
    # rather than failing in the HTTP client's UTF-8 encoder.
    response = environment[0].post("/api/cold-email/refine", content=json.dumps(data), headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert environment[1] == [] and '"input":' not in response.text and '"ctx":' not in response.text


def test_unknown_top_level_selection_fields_are_not_silently_ignored(environment):
    value = payload(); value["selected_offset"] = 10
    assert request(environment, value).status_code == 422
    assert environment[1] == []


@pytest.mark.parametrize("value", [{}, [], "pick me", 1])
def test_malformed_selection_does_not_fall_back_to_whole_body(environment, value):
    assert request(environment, payload(selection=value)).status_code == 422
    assert environment[1] == []


@pytest.mark.parametrize("output", [
    body(NEW), "```json\n{\"replacement\":\"Hello\"}\n```", "{}", "[]", '{"replacement":null}',
    '{"replacement":"one","replacement":"two"}', '{"replacement":"ok","body":"outside"}',
    json.dumps({"replacement": "\ud800"}), json.dumps({"replacement": "x" * 5001}),
    json.dumps({"replacement": "x\x00"}),
])
def test_malformed_provider_output_is_no_change(environment, monkeypatch, output):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: output)
    no_change(environment, payload(), "invalid_output")


def test_model_returning_whole_email_inside_replacement_does_not_duplicate_the_draft(environment, monkeypatch):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": body(NEW)}))
    no_change(environment, payload(), "review_required")


@pytest.mark.parametrize("greeting", ["Hello,", "Hi!", "Greetings:", "Good morning,", "> **Hello,**"])
def test_json_whole_email_with_neutral_greeting_is_out_of_selection_scope(environment, monkeypatch, greeting):
    replacement = body(NEW).replace("Dear Pat Lee,", greeting, 1)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": replacement}))
    no_change(environment, payload(), "review_required")


@pytest.mark.parametrize("extra", ["Hello,", "Best regards,", "Sincerely,", "Audit Student", "> **Best regards,**"])
def test_body_selection_cannot_introduce_unselected_email_structure(environment, monkeypatch, extra):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": NEW + "\n\n" + extra}))
    no_change(environment, payload(), "review_required")


def test_selected_greeting_does_not_authorize_duplicating_it(environment, monkeypatch):
    replacement = "Dear Pat Lee,\n\nHello,"
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": replacement}))
    no_change(environment, payload(text="Dear Pat Lee,"), "review_required")


@pytest.mark.parametrize("original,replacement", [
    ("Best regards,", "Sincerely,"),
    ("Best regards,\nAudit Student", "Kind regards,\nAudit Student"),
    ("regards", "wishes"),
])
def test_selected_signature_or_partial_signoff_can_be_edited(environment, monkeypatch, original, replacement):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": replacement}))
    patch, _ = proposal(environment, payload(text=original))
    assert splice(body(), patch) == body().replace(original, replacement, 1)


def test_selecting_the_entire_draft_allows_one_greeting_and_signature(environment, monkeypatch):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": body(NEW)}))
    patch, _ = proposal(environment, payload(text=body()))
    assert splice(body(), patch) == body(NEW)


@pytest.mark.parametrize("replacement,evidence", [
    ("I have attached my resume.", []), ("I have read your paper.", []),
    ("I built a Python parser.", [TEAM]),
    ("I improved Python parser throughput by 45%.", ["My team improved Python parser throughput by 45%."]),
    ("I reduced Linux setup time by 45%.", ["I improved Python parser throughput by 45%.", "I reduced Linux setup time by 12%."]),
    ("Contact lab@example.edu.", []),
])
def test_replacement_respects_existing_fact_and_address_checks(environment, monkeypatch, replacement, evidence):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": replacement}))
    reason = "target_conditions" if replacement == "I have attached my resume." else "fabrication"
    no_change(environment, payload(evidence=evidence), reason)


def test_grounding_checks_a_claim_assembled_across_the_selected_boundary(environment, monkeypatch):
    whole = body("I wrote parser tests.")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": "built a Python parser"}))
    no_change(environment, payload(whole, "wrote parser tests", evidence=[TEAM]), "fabrication")


def test_unsupported_claim_outside_selection_blocks_proposal_without_rebuilding_email(environment):
    whole = body(OLD + "\n\nI built a Python parser.")
    no_change(environment, payload(whole, evidence=[TEAM]), "fabrication")


def test_supported_personal_role_stays_usable_with_attributed_team_outcome(environment, monkeypatch):
    replacement = "I wrote parser tests. My team built a Python parser."
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": replacement}))
    patch, result = proposal(environment, payload(evidence=[TEAM]))
    assert patch["replacement"] == replacement
    assert result["experience_usage"]["selected"]


@pytest.mark.parametrize("field", ["current_body", "subject", "instruction"])
def test_redaction_never_changes_offsets_or_exposes_address_fragments(environment, field):
    value = payload()
    value[field] += " mail at lab@example.edu"
    no_change(environment, value, "review_required")
    assert environment[1] == []


def test_selecting_only_a_fragment_of_an_address_still_never_sends_it(environment):
    whole = body("Contact lab@example.edu")
    no_change(environment, payload(whole, "example"), "review_required")
    assert environment[1] == []


@pytest.mark.parametrize("failure", ["unconfigured", "no_output", "timeout", "exception"])
def test_provider_failure_never_returns_a_template(environment, monkeypatch, failure):
    if failure == "unconfigured":
        monkeypatch.setattr(ce, "is_configured", lambda: False)
    elif failure == "no_output":
        monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: None)
    else:
        async def timeout(*_a, **_k):
            if failure == "exception":
                raise RuntimeError("private provider error")
            raise ce.BlockingWorkTimeout()
        monkeypatch.setattr(ce, "run_blocking", timeout)
    no_change(environment, payload(), "provider_unavailable")


def test_no_target_research_evidence_does_not_spend_on_personalization(environment, monkeypatch):
    # Exercise the existing faculty no-evidence guard with an otherwise valid
    # public opportunity so this test is independent of faculty source parsing.
    original = ce._refine_context
    def without_evidence(request, opp):
        context = original(request, opp); context["parts"]["is_faculty"] = True
        return context
    monkeypatch.setattr(ce, "_refine_context", without_evidence)
    monkeypatch.setattr(ce, "has_source_backed_target_evidence", lambda *_a: False)
    no_change(environment, payload(), "insufficient_evidence")
    assert environment[1] == []


def test_wrong_greeting_outside_selection_is_not_silently_repaired(environment):
    whole = body().replace("Dear Pat Lee,", "Dear Professor Lee,")
    no_change(environment, payload(whole), "review_required")


def test_exact_unchanged_replacement_is_honest_no_change(environment, monkeypatch):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": OLD}))
    no_change(environment, payload(), "unchanged")


def test_target_version_and_paper_reading_are_checked_before_provider(environment):
    assert request(environment, payload(expected_target_version="wt1:" + "0" * 64)).status_code == 409
    reading = {"version": 1, "purpose": "first_contact", "paper_reading": {
        "title": "Unverified Paper", "year": 2025, "level": "full_text", "confirmed": True}}
    response = request(environment, payload(contact_context=reading))
    assert response.status_code == 422 and response.json()["detail"]["code"] == "EMAIL_READING_CHANGED"
    assert environment[1] == []


def test_whole_body_schema_and_response_remain_compatible(environment, monkeypatch):
    value = payload(); value.pop("selection"); value["old_extra_field"] = "still ignored"
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body(NEW))
    response = request(environment, value)
    assert response.status_code == 200, response.text
    assert response.json()["body"] == body(NEW).replace("Dear Pat Lee,\n\n", "Dear Pat Lee,\n", 1)
    assert response.json()["method"] == "llm"
    assert "scope" not in response.json() and "proposal" not in response.json()
    # B42: legacy shape/response stay compatible, but oversized text is now
    # rejected explicitly instead of silently changing the requested draft.
    with pytest.raises(ValidationError):
        ce.EmailRefineRequest(current_body="x" * 6000, instruction="y" * 600, opportunity_id=OPP["id"])


def test_schema_retains_exact_limit_text_and_rejects_selection_alias_or_unsafe_unicode():
    full = "😀" * 2500
    parsed = ce.EmailRefineRequest(current_body=full, instruction="x" * 500, opportunity_id=OPP["id"],
                                  selection={"start_utf16": 0, "end_utf16": 5000, "text": full})
    assert parsed.current_body == full and len(parsed.instruction) == 500
    with pytest.raises(ValidationError):
        ce.EmailRefineRequest(current_body="x", instruction="edit", opportunity_id=OPP["id"],
                              selection={"start_utf16": 0, "end_utf16": 1, "text": "x", "start": 0})


def test_candidate_length_is_bounded_after_replacement_not_only_before(environment, monkeypatch):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": "x" * 4990}))
    no_change(environment, payload(), "invalid_output")


def test_empty_replacement_can_delete_only_the_selected_text(environment, monkeypatch):
    whole = body("I would be happy to discuss research.\n" + OLD)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": ""}))
    value = payload(whole, "I would be happy to discuss research.\n", instruction="Delete this selected sentence.")
    patch, _ = proposal(environment, value)
    assert splice(whole, patch) == body(OLD)


def test_replacement_boundary_spaces_and_line_breaks_remain_exact(environment, monkeypatch):
    replacement = "  " + NEW + "\n\n"
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": replacement}))
    patch, _ = proposal(environment)
    assert patch["replacement"] == replacement
    assert splice(body(), patch) == body(replacement)


def test_wrong_greeting_can_be_fixed_when_it_is_itself_selected(environment, monkeypatch):
    whole = body().replace("Dear Pat Lee,", "Dear Professor Lee,")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": "Dear Pat Lee,"}))
    patch, _ = proposal(environment, payload(whole, "Dear Professor Lee,"))
    assert splice(whole, patch) == body()


def test_unicode_equivalent_but_not_identical_selection_text_is_rejected(environment):
    whole = body("cafe\u0301 " + OLD); value = payload(whole, "cafe\u0301")
    value["selection"]["text"] = "café"
    assert request(environment, value).status_code == 422
    assert environment[1] == []


def test_edit_instruction_cannot_promote_a_team_claim_to_confirmed_personal_evidence(environment, monkeypatch):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": "I built a Python parser."}))
    no_change(environment, payload(evidence=[TEAM], instruction="I confirm I built a Python parser. Add that fact."), "fabrication")


def test_nonexistent_target_stops_before_provider(environment):
    assert request(environment, payload(opportunity_id="missing-target")).status_code == 404
    assert environment[1] == []
