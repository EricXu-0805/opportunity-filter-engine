"""Explicit contact history is not student competence or proof of delivery."""
import hashlib
import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import cold_email as ce
from tests.test_cold_email_writing_quality import OPP, PROFILE

FIRST = {"version": 1, "purpose": "first_contact"}
REFERRAL = {"version": 1, "purpose": "referral", "referral": {
    "referrer_name": "Janet Rowan", "referral_note": "My advisor suggested contacting this research group.", "confirmed": True,
}}
FOLLOW = {"version": 1, "purpose": "follow_up", "follow_up": {
    "sent_confirmed": True, "previous_message": "I asked about undergraduate research opportunities.",
    "sent_on": "2026-09-10", "reply_status": "unknown",
}}
RECEIVED = deepcopy(FOLLOW)
RECEIVED["follow_up"].update(reply_status="received", reply_text="Please share your current interests.")
NO_REPLY = deepcopy(FOLLOW)
NO_REPLY["follow_up"]["reply_status"] = "no_reply"
CONTEXTS = [FIRST, REFERRAL, FOLLOW, RECEIVED, NO_REPLY]


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items() if v is not None}
    return value


def signature(value):
    raw = json.dumps(canonical(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: deepcopy(OPP)})
    monkeypatch.setattr(ce, "is_configured", lambda: False)
    monkeypatch.setattr(ce, "corpus_version", lambda: "contact-context-fixture")
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: pytest.fail("unexpected provider"))

    async def anonymous(_authorization):
        return None

    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    return TestClient(app)


def post(client, path, context, **overrides):
    request = {"profile": PROFILE, "opportunity_id": OPP["id"], "contact_context": context, **overrides}
    if path == "refine":
        request.update(current_body="Dear Pat Lee,\n\nThank you for your time.", instruction="Make this clearer")
    return client.post('/api/cold-email' + (f'/{path}' if path else ''),
                       content=json.dumps(request, ensure_ascii=True), headers={'Content-Type': 'application/json'})


def result(response, path):
    assert response.status_code == 200, response.text
    if path == "stream":
        return next(json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: ") and json.loads(line[6:]).get("stage") == "done")
    return response.json()


@pytest.mark.parametrize("path", ["", "variants", "stream", "refine"])
@pytest.mark.parametrize("context", CONTEXTS)
def test_all_paths_preserve_confirmed_scenario_without_experience_envelope(client, path, context):
    before = deepcopy(context)
    out = result(post(client, path, context), path)
    receipt = {"version": 1, "purpose": context["purpose"], "context_sig": signature(context)}
    assert out["contact_context_receipt"] == receipt
    variants = out.get("variants", [out])
    for variant in variants:
        assert variant["contact_context_receipt"] == receipt
        body = variant["body"]
        if context["purpose"] == "referral":
            assert "Janet Rowan suggested I contact you." in body
        elif context["purpose"] == "follow_up":
            assert "I am following up on my previous email sent on 2026-09-10." in body
            status = context["follow_up"]["reply_status"]
            assert ("Thank you for your reply." in body) is (status == "received")
            assert ("I have not yet received a reply." in body) is (status == "no_reply")
            assert "My name is" not in body
        else:
            assert "following up" not in body
            assert "suggested I contact" not in body
        assert not variant.get("experience_usage", {}).get("selected")
    assert context == before


@pytest.mark.parametrize("context", [
    {**REFERRAL, "referral": {**REFERRAL["referral"], "confirmed": False}},
    {**REFERRAL, "referral": {**REFERRAL["referral"], "confirmed": 1}},
    {**REFERRAL, "referral": {"referrer_name": "Janet Rowan", "confirmed": True}},
    {**REFERRAL, "referral": {**REFERRAL["referral"], "referrer_name": " Janet Rowan"}},
    {**REFERRAL, "referral": {**REFERRAL["referral"], "referrer_name": "Janet\u2028Rowan"}},
    {**FIRST, "version": True},
    {**FIRST, "follow_up": FOLLOW["follow_up"]},
    {"version": 1, "purpose": "follow_up"},
    {**FOLLOW, "follow_up": {**FOLLOW["follow_up"], "sent_confirmed": False}},
    {**FOLLOW, "follow_up": {**FOLLOW["follow_up"], "sent_on": "2026-02-30"}},
    {**FOLLOW, "follow_up": {**FOLLOW["follow_up"], "previous_message": ""}},
    {**FOLLOW, "follow_up": {**FOLLOW["follow_up"], "reply_text": "Unexpected reply"}},
    {**FOLLOW, "follow_up": {**FOLLOW["follow_up"], "reply_status": "received"}},
    {**FIRST, "availability": {"text": "6 hours per week", "confirmed": False}},
    {**FIRST, "unexpected": "private-marker"},
    {**FIRST, "availability": {"text": "bad\ud800", "confirmed": True}},
])
@pytest.mark.parametrize("path", ["", "variants", "stream", "refine"])
def test_unconfirmed_or_malformed_context_is_rejected_before_generation(client, monkeypatch, context, path):
    monkeypatch.setattr(ce, "_run_engine", lambda *_a, **_k: pytest.fail("invalid context reached generation"))
    response = post(client, path, context)
    assert response.status_code == 422, response.text
    assert "private-marker" not in response.text
    assert all(set(item) <= {"loc", "msg", "type"} for item in response.json()["detail"])


def test_null_and_omitted_context_are_compatible_first_contact(client):
    missing = client.post('/api/cold-email', json={"profile": PROFILE, "opportunity_id": OPP["id"]})
    null = post(client, "", None)
    assert missing.status_code == null.status_code == 200
    assert missing.json()["contact_context_receipt"] == null.json()["contact_context_receipt"] == {
        "version": 1, "purpose": "first_contact", "context_sig": signature(FIRST),
    }


def test_optional_date_and_null_fields_do_not_invent_a_date_or_reply(client):
    context = deepcopy(FOLLOW)
    context["follow_up"]["sent_on"] = None
    context["availability"] = None
    out = result(post(client, "", context), "")
    assert "I am following up on my previous email." in out["body"]
    assert "2026" not in out["body"]
    assert "received a reply" not in out["body"] and "Thank you for your reply" not in out["body"]
    assert out["contact_context_receipt"]["context_sig"] == signature(context)


@pytest.mark.parametrize("context", [REFERRAL, FOLLOW, RECEIVED])
@pytest.mark.parametrize("path", ["", "stream", "refine"])
def test_provider_failure_keeps_contact_purpose(client, monkeypatch, path, context):
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: None)
    out = result(post(client, path, context, engine="ai"), path)
    assert out["contact_context_receipt"]["purpose"] == context["purpose"]
    opening = "Janet Rowan suggested I contact you." if context["purpose"] == "referral" else "I am following up"
    assert opening in out["body"]


@pytest.mark.parametrize("path", ["", "refine"])
def test_previous_email_and_reply_never_authenticate_student_achievements(client, monkeypatch, path):
    context = deepcopy(RECEIVED)
    context["follow_up"].update(previous_message="I trained 99 models with PyTorch.", reply_text="Your 99 models sound impressive.")
    fake = "Dear Pat Lee,\n\nI am following up on my previous email sent on 2026-09-10.\n\nThank you for your reply.\n\nI trained 99 models with PyTorch.\n\nBest regards,\nAudit Student"
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: fake if path else f"Subject: Follow-up\n\n{fake}")
    out = result(post(client, path, context, engine="ai"), path)
    assert "99" not in out["body"] and "trained" not in out["body"]
    assert "I am following up" in out["body"]
    assert out["fallback_reason"] == "fabrication"


def test_confirmed_availability_is_optional_and_never_assumed(client, monkeypatch):
    wet = {**OPP, "keywords": ["wet lab", "cell culture"], "description_raw": "Wet lab cell culture."}
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: wet})
    absent = result(post(client, "", FIRST), "")
    assert "can commit to in-person hours" not in absent["body"]
    context = {**FIRST, "availability": {"text": "I can contribute 6 hours per week during the semester.", "confirmed": True}}
    present = result(post(client, "", context), "")
    assert context["availability"]["text"] in present["body"]
    assert present["contact_context_receipt"]["context_sig"] == signature(context)


@pytest.mark.parametrize("path", ["", "variants", "stream", "refine"])
@pytest.mark.parametrize("claim", ["I won a Nobel Prize.", "I led a team of 12 researchers."])
def test_availability_cannot_launder_awards_or_leadership(client, path, claim):
    context = {**FIRST, "availability": {"text": claim, "confirmed": True}}
    response = post(client, path, context)
    assert response.status_code == 422, response.text
    assert claim not in response.text


@pytest.mark.parametrize("path", ["", "stream", "refine"])
def test_referral_note_is_not_a_new_student_fact_source(client, monkeypatch, path):
    context = deepcopy(REFERRAL)
    context["referral"]["referral_note"] = "I trained 99 models with PyTorch."
    fake = "Dear Pat Lee,\n\nJanet Rowan suggested I contact you.\n\nI trained 99 models with PyTorch.\n\nThank you."
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: fake if path == "refine" else f"Subject: Research inquiry\n\n{fake}")
    out = result(post(client, path, context, engine="ai"), path)
    assert "99" not in out["body"] and "PyTorch" not in out["body"]
    assert "Janet Rowan suggested I contact you." in out["body"]
    assert out["fallback_reason"] == "fabrication"


@pytest.mark.parametrize("context,extra", [
    (FIRST, "Janet Rowan suggested I contact you."),
    (REFERRAL, "Someone Else referred me to you."),
    (FOLLOW, "I have not yet received a reply."),
    (FOLLOW, "Thank you for your reply."),
    (NO_REPLY, "You offered me a position."),
    (FOLLOW, "I am following up on my previous email sent on 2026-09-11."),
])
@pytest.mark.parametrize("path", ["", "refine"])
def test_changed_or_unconfirmed_contact_claims_cannot_survive_generation(client, monkeypatch, path, context, extra):
    # Include a valid prefix as well: merely finding some confirmed words must
    # not license a second, contradictory contact claim elsewhere in the draft.
    from backend.lib.email_contact_context import contact_context_parts
    parts = contact_context_parts(context)
    prefix = "\n\n".join(parts[k] for k in ("contact_opening", "contact_reply_line") if parts[k])
    body = f"Dear Pat Lee,\n\n{prefix}\n\n{extra}\n\nThank you."
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body if path else f"Subject: Research inquiry\n\n{body}")
    out = result(post(client, path, context, engine="ai"), path)
    assert extra not in out["body"]
    assert out["fallback_reason"] == "fabrication"
    assert out["contact_context_receipt"]["context_sig"] == signature(context)


@pytest.mark.parametrize("path", ["", "stream", "refine"])
@pytest.mark.parametrize("context", [REFERRAL, FOLLOW, RECEIVED])
def test_ai_can_use_confirmed_contact_context_without_declaring_a_real_delivery(client, monkeypatch, path, context):
    from backend.lib.email_contact_context import contact_context_parts
    parts = contact_context_parts(context)
    opening = "\n\n".join(parts[k] for k in ("contact_opening", "contact_reply_line") if parts[k])
    body = f"Dear Pat Lee,\n\n{opening}\n\nCould you let me know the best next step?\n\nBest regards,\nAudit Student"
    captured = []

    def provider(messages, **_kwargs):
        captured.append(messages)
        return body if path == "refine" else f"Subject: Research inquiry\n\n{body}"

    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", provider)
    out = result(post(client, path, context, engine="ai"), path)
    assert out["method"] == ("llm" if path == "refine" else "ai"), out
    assert out.get("fallback_reason") is None
    # Existing trusted-greeting normalization uses a single line break.
    assert body.replace("Dear Pat Lee,\n\n", "Dear Pat Lee,\n", 1) == out["body"]
    assert captured
    assert all("CONTACT CONTEXT" in messages[1]["content"] for messages in captured)
    assert all("NOT student competence evidence" in messages[1]["content"] for messages in captured)
    assert out["contact_context_receipt"] == {"version": 1, "purpose": context["purpose"], "context_sig": signature(context)}
    assert "sent" not in out and "delivery_status" not in out


@pytest.mark.parametrize("character,expected_status", [("\ufeff", 422), ("\u0085", 200), ("\u001c", 200)])
def test_backend_trim_boundary_matches_ecmascript_string_trim(client, character, expected_status):
    context = deepcopy(REFERRAL)
    context["referral"]["referral_note"] = f"{character}My advisor suggested contacting this group.{character}"
    response = post(client, "", context)
    assert response.status_code == expected_status, response.text
    if expected_status == 200:
        assert response.json()["contact_context_receipt"]["context_sig"] == signature(context)


def test_unicode_signature_nulls_and_object_order_are_exact(client):
    context = {"availability": None, "referral": {"confirmed": True, "referral_note": "王老师提到这个方向。\n第二行保留 🙂", "referrer_name": "王老师"}, "purpose": "referral", "version": 1}
    response = post(client, "", context)
    assert response.status_code == 200, response.text
    assert response.json()["contact_context_receipt"]["context_sig"] == signature(context)


def test_context_total_budget_counts_the_canonical_wire(client):
    context = deepcopy(RECEIVED)
    context["follow_up"].update(previous_message="\\" * 4000, reply_text="\\" * 2000)
    response = post(client, "", context)
    assert response.status_code == 422


def test_application_instructions_reach_actual_provider_briefs(client, monkeypatch):
    opportunity = {**OPP, "application": {"contact_method": "portal", "application_url": "https://example.edu/apply"}}
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: opportunity})
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    captured = []

    def provider(messages, **_kwargs):
        captured.append(messages)
        return "Subject: Research tools\n\nDear Pat Lee,\n\nI am interested in Python parser tools. Could you clarify the next step?\n\nBest regards,\nAudit Student"

    monkeypatch.setattr(ce, "chat_completion", provider)
    result(post(client, "", FIRST, engine="ai"), "")
    assert captured
    assert all("Recorded application/contact method (may be inferred): portal" in m[1]["content"] for m in captured)
    assert all("https://example.edu/apply" in m[1]["content"] for m in captured)
    assert all("does not replace a form or portal submission" in m[1]["content"] for m in captured)


@pytest.mark.parametrize("name,expected", [
    ("Dr Lee. I won a Nobel Prize", 422), ("Dr Lee. I led a team of 12", 422),
    ("李老师。我获得诺贝尔奖", 422), ("Dr. O'Neil", 200), ("王老师", 200),
])
def test_direct_referrer_name_cannot_smuggle_a_student_work_claim(client, name, expected):
    context = deepcopy(REFERRAL)
    context["referral"]["referrer_name"] = name
    response = post(client, "", context)
    assert response.status_code == expected, response.text
    if expected == 200:
        assert f"{name} suggested I contact you." in response.json()["body"]


def test_all_ai_stages_receive_contact_context_as_separate_evidence(client, monkeypatch):
    calls = []
    body = "Dear Pat Lee,\n\nJanet Rowan suggested I contact you.\n\nI am interested in Python parser tools. Could we discuss the next step?\n\nBest regards,\nAudit Student"

    def provider(messages, **_kwargs):
        system = messages[0]["content"]
        if "You are judging candidate" in system:
            stage, answer = "judge", '{"winner":1}'
        elif "You are a strict reviewer" in system:
            stage, answer = "critique", '{"verdict":"revise","revision_notes":"Keep the confirmed contact opening."}'
        elif "You are revising" in system:
            stage, answer = "revise", f"Subject: Research inquiry\n\n{body}"
        elif "You are an email editor" in system:
            stage, answer = "refine", body
        else:
            stage, answer = "draft", f"Subject: Research inquiry\n\n{body}"
        calls.append((stage, messages))
        return answer

    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", provider)
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "2")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "1")
    initial = result(post(client, "", REFERRAL, engine="ai"), "")
    refined = result(post(client, "refine", REFERRAL), "refine")
    assert initial["method"] == "ai" and refined["method"] == "llm"
    assert {stage for stage, _ in calls} == {"draft", "judge", "critique", "revise", "refine"}
    for stage, messages in calls:
        assert "Use the server's CONTACT CONTEXT purpose" in messages[0]["content"], stage
        assert "NOT student competence evidence" in messages[1]["content"], stage
        assert REFERRAL["referral"]["referral_note"] in messages[1]["content"], stage


@pytest.mark.parametrize("path", ["", "stream", "variants", "refine"])
def test_confirmed_contact_history_never_overrides_closed_target(client, monkeypatch, path):
    opportunity = {**OPP, "metadata": {"is_active": False}}
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: opportunity})
    response = post(client, path, FOLLOW, engine="ai")
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("path", ["", "stream", "variants", "refine"])
def test_confirmed_contact_history_never_overrides_target_version(client, path):
    response = post(client, path, REFERRAL, expected_target_version="wt1:" + "0" * 64, engine="ai")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "WRITING_TARGET_CHANGED"


@pytest.mark.parametrize("context", [FIRST, REFERRAL, FOLLOW])
def test_faculty_contact_context_still_asks_whether_an_opening_exists(client, monkeypatch, context):
    faculty = {**OPP, "source_type": "faculty_research", "record_kind": "faculty_contact",
               "metadata": {"is_active": True, "faculty_title": "Professor", "research_areas_raw": "Python parser tools"}}
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: faculty})
    out = result(post(client, "", context), "")
    assert "current or upcoming research openings" in out["body"]
    assert "your open position" not in out["body"]
    assert out["contact_context_receipt"]["purpose"] == context["purpose"]


def test_shared_browser_backend_contact_golden_contract():
    from pathlib import Path

    from pydantic import ValidationError

    from backend.lib.email_contact_context import contact_context_receipt, normalize_contact_context
    from backend.schemas import EmailContactContext

    fixture = json.loads((Path(__file__).parent / "fixtures/email-contact-context-v1.json").read_text())
    for case in fixture["valid"]:
        context = EmailContactContext.model_validate(case["wire"]).model_dump(exclude_none=True) if case["wire"] is not None else None
        normalized = normalize_contact_context(context)
        assert json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == case["canonical"], case["id"]
        assert contact_context_receipt(context)["context_sig"] == case["context_sig"], case["id"]
    for case in fixture["invalid"]:
        with pytest.raises(ValidationError):
            EmailContactContext.model_validate(case["wire"])


@pytest.mark.parametrize("sentence", [
    "I would appreciate your reply.", "I look forward to your response.",
    "Your reply would help me understand the next step.",
])
def test_future_reply_requests_are_not_a_claim_that_a_reply_already_exists(client, monkeypatch, sentence):
    body = f"Dear Pat Lee,\n\nI am interested in Python parser tools. {sentence}\n\nBest regards,\nAudit Student"
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: f"Subject: Research inquiry\n\n{body}")
    out = result(post(client, "", FIRST, engine="ai"), "")
    assert out["method"] == "ai", out
    assert sentence in out["body"]
    assert out.get("fallback_reason") is None


def test_final_neutral_recovery_keeps_valid_availability_but_no_untrusted_work(client, monkeypatch):
    context = {**REFERRAL, "availability": {"text": "I can contribute 6 hours per week during the semester.", "confirmed": True}}
    monkeypatch.setattr(ce, "generate_cold_email", lambda *_a, **_k: "Subject: Bad\n\nDear Pat Lee,\n\nI have attached my resume.")
    out = result(post(client, "", context), "")
    assert "Janet Rowan suggested I contact you." in out["body"]
    assert context["availability"]["text"] in out["body"]
    assert "attached" not in out["body"]
    assert out["fallback_reason"] == "fabrication"


@pytest.mark.parametrize('path', ['', 'variants', 'stream', 'refine'])
@pytest.mark.parametrize('field', ['referrer_name', 'availability'])
@pytest.mark.parametrize('claim', [
    'I have attached my resume', 'I included my CV as an attachment',
    'I have read your paper', 'Having reviewed your research, I will apply',
])
def test_direct_contact_fields_cannot_reintroduce_unsupported_actions(client, path, field, claim):
    context = deepcopy(REFERRAL)
    if field == 'referrer_name':
        context['referral']['referrer_name'] = 'Dr Lee. ' + claim
    else:
        context['availability'] = {'text': claim, 'confirmed': True}
    response = post(client, path, context)
    assert response.status_code == 422, response.text
    assert claim not in response.text


@pytest.mark.parametrize('availability', [
    'I can send my resume on request.',
    'I will read your paper before we meet.',
    'I will write after having read your paper.',
    'I can contribute 6 hours per week during the semester.',
])
def test_future_offers_in_availability_remain_usable(client, availability):
    context = {**FIRST, 'availability': {'text': availability, 'confirmed': True}}
    out = result(post(client, '', context), '')
    assert availability in out['body']
