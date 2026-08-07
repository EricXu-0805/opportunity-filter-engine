"""Public response and generation contexts must not carry hidden contacts."""

from __future__ import annotations

from copy import deepcopy

import pytest

from backend.lib.public_projection import (
    contains_embedded_email,
    redact_embedded_emails,
    safe_public_http_url,
    sanitize_public_urls,
)
from backend.routes import cold_email as cold_email_route
from backend.routes.cold_email import _contact_safe_opportunity, _run_engine
from backend.routes.matches import _match_card, _match_result_response
from backend.routes.opportunities import (
    _build_chat_system_prompt,
    _list_card,
    _local_chat_fallback,
    _redact,
)
from backend.schemas import ColdEmailRequest, ProfileRequest
from src.matcher.ranker import MatchResult

CONTACT_VARIANTS = [
    "jane@example.edu",
    "jane at example.edu",
    "jane at cs.example.edu",
    "jane at example dot edu",
    "jane at example dot health",
    "jane at example dot college",
    "jane at example dot institute",
    "jane at example point health",
    "jane at example point college",
    "contact student at example.com",
    "email student at example.com",
    "jane[at]example[dot]edu",
    "jane{at}example{dot}edu",
    "jane(at)example(dot)edu",
    "jane/at/example/dot/edu",
    "jane%40example%2Eedu",
    "jane%2540example%252Eedu",
    "jane%252540example%25252Eedu",
    "jane%20at%20example%2Eedu",
    "jane&#64;example&#46;edu",
    "jane&amp;#64;example&amp;#46;edu",
    "jane at example&amp;#46;edu",
    "jane+at+example+dot+edu",
    "jane+at+example%2Eedu",
    "jane [at] example . edu",
    "jane @ example . edu",
    "jane@\u200bexample.edu",
    "jane\u200b@example.edu",
    "jane\u2060at\u2060example\u2060dot\u2060edu",
    "jane%u0040example%u002Eedu",
    "jane@[192.0.2.1]",
    "jane<span>@</span>example<span>.</span>edu",
    'jane<span title=">">@</span>example<span>.</span>edu',
    "jane<span title=&quot;&gt;&quot;>@</span>example<span>.</span>edu",
    "jane<!-- directory guard -->@example.edu",
    "jane<!-- directory guard --!>@example.edu",
    "jane<!directory-guard>@example.edu",
    "jane <span>a</span><span>t</span> example "
    "<span>d</span><span>o</span><span>t</span> edu",
    "jane a<!-- split -->t example d<!-- split -->o<!-- split -->t edu",
    "jane at example．edu",
    "jane at example。edu",
    "jane at example﹒edu",
    "jane艾特example点edu",
    "ｊａｎｅ＠ｅｘａｍｐｌｅ．ｅｄｕ",
    "用户@例子.公司",
    "用户[at]例子[dot]公司",
]


def _opportunity() -> dict:
    return {
        "id": "contact-bearing",
        "title": "Email jane@example.edu about the ML lab",
        "organization": "Example University",
        "department": "Computer Science",
        "opportunity_type": "research",
        "source": "example_faculty",
        "source_type": "faculty",
        "pi_name": "Jane Doe",
        "lab_or_program": "ML Lab",
        "contact_email": "jane@example.edu",
        "pi_email": "admin@example.edu",
        "url": "https://example.edu/people/jane@example.edu",
        "source_url": "javascript:alert(1)",
        "paid": "unknown",
        "keywords": ["machine learning", "coordinator@example.edu"],
        "eligibility": {
            "majors": ["Computer Science"],
            "skills_required": ["Python", "staff at example dot edu"],
            "international_friendly": "yes",
        },
        "application": {
            "application_url": "mailto:apply@example.edu",
            "contact_method": "email",
        },
        "description_clean": (
            "Machine-learning research. Questions to jane at example.edu."
        ),
        "metadata": {"is_active": True},
    }


def _profile() -> ProfileRequest:
    return ProfileRequest(
        name="Test Student",
        school="Example University",
        year="sophomore",
        major="Computer Science",
        international_student=True,
        seeking_type=["research"],
        hard_skills=[{"name": "Python", "level": "experienced"}],
        coursework=["CS 101"],
        experience_level="beginner",
        resume_ready=True,
        can_cold_email=True,
        research_interests_text="machine learning",
    )


@pytest.mark.parametrize("contact", CONTACT_VARIANTS)
def test_contact_detection_fails_closed_for_visible_encoded_and_obfuscated_forms(
    contact: str,
):
    value = f"Public description; contact {contact} for details"

    assert contains_embedded_email(value)
    assert redact_embedded_emails(value) == "[email redacted]"


@pytest.mark.parametrize(
    "value",
    [
        "Research at Stanford University",
        "Look at example.com",
        "Research at stanford dot edu",
        "Meet at Stanford Point Lab",
        "Data points at scale",
        "5 point scale",
        "point-of-care methods",
        "Enhancing Infrastructure at the Point Reyes Field Station",
        "Infrastructure at the Point Cloud Lab",
        "Fellowships at the dot institute open now",
        "React.js and C++",
    ],
)
def test_contact_detection_preserves_common_non_contact_phrases(value: str):
    assert not contains_embedded_email(value)
    assert redact_embedded_emails(value) == value


def test_oversized_text_has_an_explicit_fail_closed_policy():
    assert redact_embedded_emails("x" * 20_000) == "x" * 20_000
    assert redact_embedded_emails("x" * 20_001) == "[email redacted]"


def test_point_reyes_corpus_title_is_not_a_contact_false_positive():
    title = "Enhancing Infrastructure at the Point Reyes Field Station"
    projected = _redact({
        "id": "nsf-reu-2556052",
        "title": title,
        "lab_or_program": title,
    })

    assert projected["title"] == title
    assert projected["lab_or_program"] == title


def test_detail_projection_redacts_addresses_split_across_html_markup():
    projected = _redact({
        "id": "html-split-contact",
        "description_raw": (
            'Questions: jane<span title=">">@</span>'
            "example<span>.</span>health"
        ),
        "metadata": {
            "notes": "Write jane<!-- hidden -->@example.edu",
        },
    })

    assert projected["description_raw"] == "[email redacted]"
    assert projected["metadata"]["notes"] == "[email redacted]"


def test_recursive_projection_redacts_values_and_contact_shaped_keys_without_mutation():
    original = {
        "plain": "Contact jane@example.edu",
        "nested": [
            "safe",
            {
                "jane[at]example[dot]edu": "secret",
                "ordinary": "staff at example dot edu",
            },
        ],
    }
    before = deepcopy(original)

    projected = redact_embedded_emails(original)

    assert original == before
    assert projected == {
        "plain": "[email redacted]",
        "nested": ["safe", {"ordinary": "[email redacted]"}],
    }


def test_public_url_projection_allows_only_absolute_contact_free_http_links():
    assert safe_public_http_url("https://example.edu/apply?id=42#form") == (
        "https://example.edu/apply?id=42#form"
    )
    for value in (
        "javascript:alert(1)",
        "data:text/html,boom",
        "mailto:jane@example.edu",
        "/relative/path",
        "https://user:secret@example.edu/apply",
        "https://example.edu/people/jane@example.edu",
        " https://example.edu/apply",
    ):
        assert safe_public_http_url(value) is None


def test_recursive_url_projection_covers_nested_application_and_publication_links():
    original = {
        "url": "javascript:alert(1)",
        "application": {"application_url": "https://example.edu/apply?job=7"},
        "metadata": {"contact_source_url": "javascript:alert(2)"},
        "recent_works": [{"url": "data:text/html,boom"}],
    }
    before = deepcopy(original)

    projected = sanitize_public_urls(original)

    assert original == before
    assert projected == {
        "application": {"application_url": "https://example.edu/apply?job=7"},
        "metadata": {},
        "recent_works": [{}],
    }


@pytest.mark.parametrize("projector", [_redact, _list_card, _match_card])
def test_all_opportunity_projection_shapes_remove_embedded_contacts_and_unsafe_urls(
    projector,
):
    opportunity = _opportunity()
    before = deepcopy(opportunity)

    projected = projector(opportunity)

    assert opportunity == before
    assert not contains_embedded_email(str(projected))
    assert projected.get("url") is None
    if "application" in projected:
        assert "application_url" not in projected["application"]


def test_match_result_projection_covers_reasons_next_steps_unknowns_and_ai_reason():
    result = MatchResult(
        opportunity_id="contact-bearing",
        eligibility_score=70,
        readiness_score=60,
        upside_score=50,
        final_score=65,
        bucket="good_match",
        reasons_fit=["Write jane@example.edu"],
        reasons_gap=["Ask jane at example dot edu"],
        next_steps=["Open https://example.edu/people/jane@example.edu"],
        ai_reason="The contact is jane%40example%2Eedu",
        unknowns=["owner@example.edu"],
    )

    response = _match_result_response(
        result,
        {"contact-bearing": _match_card(_opportunity())},
    ).model_dump()

    assert not contains_embedded_email(str(response))
    assert response["reasons_fit"] == ["[email redacted]"]
    assert response["reasons_gap"] == ["[email redacted]"]
    assert response["next_steps"] == ["[email redacted]"]
    assert response["ai_reason"] == "[email redacted]"
    assert response["unknowns"] == ["[email redacted]"]


def test_ask_ai_prompt_and_local_fallback_only_receive_public_projection():
    public = _redact(_opportunity())

    prompt = _build_chat_system_prompt(public, _profile())
    fallback = _local_chat_fallback(public, "How should I apply?")

    assert not contains_embedded_email(prompt)
    assert not contains_embedded_email(fallback)
    assert "jane@example.edu" not in prompt
    assert "admin@example.edu" not in prompt


def test_cold_email_context_and_output_cannot_reintroduce_hidden_address(monkeypatch):
    opportunity = _opportunity()
    captured: dict = {}

    def fake_generate(profile: dict, safe_opp: dict) -> str:
        captured["profile"] = profile
        captured["opportunity"] = safe_opp
        return (
            "Subject: Questions for jane@example.edu\n\n"
            "Dear Professor Doe,\nPlease write jane at example dot edu.\n"
            "Best regards,\nTest Student"
        )

    monkeypatch.setattr(cold_email_route, "generate_cold_email", fake_generate)
    request = ColdEmailRequest(
        profile=_profile(),
        opportunity_id="contact-bearing",
        engine="template",
    )

    response = _run_engine(
        request,
        opportunity,
        request.profile.model_dump(),
        authenticated=False,
    ).model_dump()

    assert captured["opportunity"] == _contact_safe_opportunity(opportunity)
    assert not contains_embedded_email(str(captured["opportunity"]))
    assert response["subject"] == "[email redacted]"
    assert response["body"] == "[email redacted]"
    assert response["recipient_email"] == ""
    # W7a reconciliation: this legacy-shaped record now HAS a verified send
    # target, so an anonymous caller gets the honest sign-in gate — never the
    # address itself (asserted above), and never a false "unavailable".
    assert response["recipient_status"] == "sign_in_required"
    assert "example.edu" not in response["mailto_link"]
