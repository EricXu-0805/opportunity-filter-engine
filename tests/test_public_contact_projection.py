"""Public response and generation contexts must not carry hidden contacts."""

from __future__ import annotations

from copy import deepcopy

import pytest

from backend.lib.public_projection import (
    _EVIDENCE_ONLY_METADATA_KEYS,
    contains_embedded_email,
    neutralize_lifecycle_title,
    project_public_opportunity_payload,
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
        # A reviewed listing source type. Unreviewed would have the whole
        # description neutralized, and `faculty_research` would have it
        # rewritten by the faculty-safe projection — either way the redaction
        # under test would never run.
        "source_type": "campus_program",
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


def test_a_nested_absolute_url_is_still_one_destination():
    """A wrapper URL is a link to the wrapper, not to what it wraps.

    `faculty-ucsd-hwsph-8fd2db9c` in the served corpus has exactly one link,
    and it is a URLDefense rewrite: a single absolute URL to urldefense.com
    whose path contains the real profile URL. A rule that refused a second
    bare `http(s)://` would delete that record's only source link — and every
    other mail-gateway rewrite and `?next=` return address with it.

    `urlsplit` already answers the question that matters: which host a click
    reaches. Two destinations in one field is a data-integrity problem, not a
    link-safety one.
    """
    for value in (
        "https://urldefense.com/v3/__https://profiles.ucsd.edu/pooyan.kazemian__;!!x$",
        "https://example.edu/apply?next=https://example.edu/done",
        "https://example.edu/apply?next=https%3A%2F%2Fexample.edu%2Fdone",
        "https://example.edu/apply?id=42#form",
        "https://example.edu/a;b;c",
    ):
        assert safe_public_http_url(value) == value, value


def test_the_real_urldefense_record_keeps_its_only_link():
    from backend.data_loader import load_opportunities_by_id

    record = load_opportunities_by_id().get("faculty-ucsd-hwsph-8fd2db9c")
    if record is None:
        pytest.skip("record not present in this corpus generation")
    wrapped = record.get("source_url") or record.get("url")
    assert wrapped and wrapped.startswith("https://urldefense.com/")
    # The contract keeps it byte-for-byte: this is the profile page, and
    # dropping it would leave the record with no way to read the source at all.
    assert safe_public_http_url(wrapped) == wrapped


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

    # Mirrors the real signature rather than accepting **kwargs: a double
    # that swallows anything stops noticing when the contract it stands in
    # for changes.
    def fake_generate(profile: dict, safe_opp: dict,
                      resume_bullets: list[str] | None = None) -> str:
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


# ---------------------------------------------------------------------------
# The one central projector.
# ---------------------------------------------------------------------------

_SEVEN_TRUTH_KEYS = {
    "listing_state", "reference_only", "actionable",
    "accepting_state", "reason_code", "verified_at", "expires_at",
}

# Written out, not imported. These are the ten internal paths that must never
# reach a browser; the test below asserts production still equals this set, so
# a key added or removed there is a deliberate edit here rather than a silent
# narrowing of what is being checked.
_EXPECTED_EVIDENCE_KEYS = frozenset({
    "is_active",
    "listing_status",
    "urap_status",
    "reference_only",
    "last_verified",
    "expires_at",
    "faculty_availability_status",
    "faculty_availability_scan_version",
    "faculty_not_accepting_undergraduates_stated",
    "faculty_research_inactive_stated",
})

_LIVE_LISTING = {
    "id": "listing-1",
    "source_type": "campus_program",
    "title": "Vision Lab RA (applications open)",
    "deadline": "2099-09-01",
    "paid": "stipend",
    "opportunity_type": "research",
    "description_clean": "We are recruiting two students.",
    "eligibility": {"international_friendly": "yes"},
    "application": {"application_url": "https://example.edu/apply"},
    "metadata": {"is_active": True, "notes": "keep me"},
}

_FACULTY = {
    "id": "faculty-1",
    "source_type": "faculty_research",
    "title": "Dr Rivera — Systems Lab",
    "url": "https://example.edu/people/rivera",
    "metadata": {"notes": "keep me"},
}

_UNKNOWN = {
    "id": "unknown-1",
    "title": "URSA — Undergraduate Research (applications open)",
    "source_url": "https://example.edu/ursa",
    "metadata": {"is_active": True, "deadline_note": "rolling", "notes": "keep me"},
}


class TestTheCentralProjector:
    """One function shapes every public opportunity payload.

    Before this, the truth envelope, the record kind, evidence-only metadata
    and unverified-kind neutralization were applied by a helper that MUTATED
    the dict handed to it, and was correct only because all three of its
    callers happened to build a fresh one first. Nothing stated that
    precondition and nothing tested it, so a fourth caller passing a corpus
    record would have rewritten the in-process corpus.
    """

    def test_a_live_listing_keeps_everything_it_has_earned(self):
        # The positive control the redaction tests below are measured against.
        # Over-redaction is its own failure: a real opening that loses its
        # deadline and apply link is as broken as a dead one that keeps them.
        out = project_public_opportunity_payload(dict(_LIVE_LISTING), _LIVE_LISTING)
        assert out["record_kind"] == "listing"
        assert out["target_truth"]["actionable"] is True
        assert out["deadline"] == "2099-09-01"
        assert out["paid"] == "stipend"
        assert out["description_clean"] == "We are recruiting two students."
        assert out["eligibility"] == {"international_friendly": "yes"}
        assert out["application"]["application_url"] == "https://example.edu/apply"
        # An open listing may say it is open. This is the only case that keeps
        # the suffix, and stripping every suffix everywhere must fail here.
        assert out["title"] == "Vision Lab RA (applications open)"
        # Evidence in, decision out — for every kind, not only unknown ones.
        assert "is_active" not in out["metadata"]
        assert out["metadata"]["notes"] == "keep me"

    def test_a_faculty_contact_keeps_its_identity_facts(self):
        out = project_public_opportunity_payload(dict(_FACULTY), _FACULTY)
        assert out["record_kind"] == "faculty_contact"
        assert out["title"] == "Dr Rivera — Systems Lab"
        assert out["url"] == "https://example.edu/people/rivera"
        assert out["metadata"]["notes"] == "keep me"

    def test_the_envelope_is_exactly_seven_public_keys(self):
        out = project_public_opportunity_payload(dict(_FACULTY), _FACULTY)
        # Exact, both directions. A missing key silently disables a client
        # gate; an extra one leaks which internal field decided the answer.
        assert set(out["target_truth"]) == _SEVEN_TRUTH_KEYS
        for internal in ("evidence_source", "evidence_key", "evidence_value"):
            assert internal not in out["target_truth"]

    TRUTH_POISON = [
        ("absent", {}),
        ("null", {"target_truth": None}),
        ("scalar", {"target_truth": "actionable"}),
        ("list", {"target_truth": [1, 2]}),
        ("partial", {"target_truth": {"actionable": True}}),
        ("extra key", {"target_truth": {"actionable": True, "evidence_key": "urap_status"}}),
        ("internal fields", {"target_truth": {"evidence_value": "closed"}}),
        ("complete opposite", {"target_truth": {
            "listing_state": "open", "reference_only": False, "actionable": True,
            "accepting_state": "accepting", "reason_code": None,
            "verified_at": None, "expires_at": None,
        }}),
    ]

    @pytest.mark.parametrize("label,poison", TRUTH_POISON, ids=[p[0] for p in TRUTH_POISON])
    def test_a_payload_never_supplies_its_own_truth(self, label, poison):
        # The envelope is derived, never forwarded. A payload that arrives
        # carrying one is either stale or hostile, and the "complete opposite"
        # row is the one that matters: a well-formed, entirely plausible
        # actionable envelope on a record the contract refuses.
        out = project_public_opportunity_payload({**_UNKNOWN, **poison}, _UNKNOWN)
        assert set(out["target_truth"]) == _SEVEN_TRUTH_KEYS
        assert out["target_truth"]["actionable"] is False
        assert out["target_truth"]["reason_code"] == "record_kind_unverified"
        assert out["record_kind"] == "unknown"

    KIND_POISON = [
        ("absent", {}),
        ("null", {"record_kind": None}),
        ("number", {"record_kind": 7}),
        ("list", {"record_kind": ["listing"]}),
        ("object", {"record_kind": {"kind": "listing"}}),
        ("invalid", {"record_kind": "definitely_a_listing"}),
        ("opposite valid", {"record_kind": "listing"}),
    ]

    @pytest.mark.parametrize("label,poison", KIND_POISON, ids=[p[0] for p in KIND_POISON])
    def test_a_payload_never_supplies_its_own_kind(self, label, poison):
        out = project_public_opportunity_payload({**_UNKNOWN, **poison}, _UNKNOWN)
        assert out["record_kind"] == "unknown"

    def test_identity_binds_to_the_canonical_record(self):
        # A payload id that disagrees with the record is how one target's
        # terms get served under another target's name.
        out = project_public_opportunity_payload(
            {**_LIVE_LISTING, "id": "some-other-record", "source_type": "faculty_research"},
            _LIVE_LISTING,
        )
        assert out["id"] == "listing-1"
        assert out["source_type"] == "campus_program"
        assert out["record_kind"] == "listing"

    def test_an_absent_canonical_source_type_is_removed_not_preserved(self):
        # The 26 real rows carry no source_type at all. Keeping a payload's
        # invented one would manufacture the exact evidence the truth
        # contract has just finished saying we do not have.
        out = project_public_opportunity_payload(
            {**_UNKNOWN, "source_type": "campus_program"}, _UNKNOWN,
        )
        assert "source_type" not in out
        assert out["record_kind"] == "unknown"

    def test_canonical_identity_passes_through_the_contact_boundary(self):
        # Canonical means authoritative about identity, NOT clean. Binding it
        # after the projection would carry it past the very boundary this
        # function claims to apply — and a real record's TITLE is an address.
        poisoned_record = {**_LIVE_LISTING, "id": "person@example.edu"}
        out = project_public_opportunity_payload(dict(_LIVE_LISTING), poisoned_record)
        assert out["id"] == "[email redacted]"
        assert "person@example.edu" not in repr(out)

    def test_a_closed_reference_listing_reports_every_field_exactly(self):
        # Values, not just key names. Without a case carrying a non-null
        # `last_verified`/`expires_at` and a decided listing_state, a mutant
        # that hardcoded `listing_state`, dropped `reference_only`, or
        # returned `expires_at: None` would pass every other test here.
        closed = {
            "id": "closed-1",
            "source_type": "ucb_program",
            "title": "URAP Project",
            "metadata": {
                "urap_status": "closed",
                "reference_only": True,
                "is_active": True,
                "last_verified": "2026-07-21T08:18:35",
                "expires_at": "2026-12-31T00:00:00",
            },
        }
        out = project_public_opportunity_payload(dict(closed), closed)
        assert out["target_truth"] == {
            "listing_state": "closed",
            "reference_only": True,
            "actionable": False,
            "accepting_state": "not_accepting",
            "reason_code": "listing_closed",
            "verified_at": "2026-07-21T08:18:35",
            "expires_at": "2026-12-31T00:00:00",
        }
        assert out["record_kind"] == "listing"

    def test_the_title_helper_keys_on_actionable_not_only_on_kind(self):
        # A reviewed LISTING that is no longer live. Kind alone would keep the
        # suffix; the permission requires listing AND actionable, and this is
        # the only case that separates the two.
        closed_listing = {
            "id": "closed-2",
            "source_type": "campus_program",
            "title": "X (applications open)",
            "metadata": {"is_active": False},
        }
        out = project_public_opportunity_payload(dict(closed_listing), closed_listing)
        assert out["record_kind"] == "listing"
        assert out["target_truth"]["actionable"] is False
        assert out["title"] == "X"

    def test_an_unknown_kind_loses_every_offer_term(self):
        payload = {
            **_UNKNOWN,
            "deadline": "2099-09-01", "deadline_is_estimate": False, "is_rolling": True,
            "posted_date": "2026-08-01", "start_date": "2026-09-01",
            "paid": "stipend", "compensation_details": "$20/hr", "duration": "10 weeks",
            "opportunity_type": "research", "on_campus": True, "remote_option": "hybrid",
            "location": "Urbana", "audience": "undergraduate",
            "description_clean": "Apply by March 1.", "description_raw": "<p>Apply</p>",
            "description": "Open to all majors", "status": "open", "semester": "Fall 2026",
        }
        out = project_public_opportunity_payload(payload, _UNKNOWN)
        for field in (
            "deadline", "deadline_is_estimate", "is_rolling", "posted_date", "start_date",
            "paid", "compensation_details", "duration", "opportunity_type", "on_campus",
            "remote_option", "location", "audience", "description_clean",
            "description_raw", "description", "status", "semester",
        ):
            assert field not in out, field
        # Still a page worth opening: identity and the source link survive.
        assert out["id"] == "unknown-1"
        assert out["source_url"] == "https://example.edu/ursa"

    @pytest.mark.parametrize("application,eligibility", [
        # Well-formed — the shape an isinstance guard already caught.
        ({"application_url": "https://evil.example.com/steal"}, {"international_friendly": "yes"}),
        # A list, and a bare string. Keyed on the KEY being present, not on
        # the value being a dict: a string `application` renders as an
        # instruction, and a type-specific guard waves exactly those through
        # while catching only the tidy case.
        (["apply now: https://evil.example.com/steal"], ["all students welcome"]),
        ("apply now: https://evil.example.com/steal", "all students welcome"),
    ], ids=["dict", "list", "string"])
    def test_unknown_kind_normalizes_every_shape_of_offer_object(
        self, application, eligibility,
    ):
        out = project_public_opportunity_payload(
            {**_UNKNOWN, "application": application, "eligibility": eligibility},
            _UNKNOWN,
        )
        assert out["application"] == {}
        assert out["eligibility"] == {}
        assert "all students welcome" not in repr(out)
        assert "evil.example.com" not in repr(out)

    def test_metadata_keeps_what_is_unrelated_and_loses_what_is_evidence(self):
        out = project_public_opportunity_payload(dict(_UNKNOWN), _UNKNOWN)
        assert out["metadata"] == {"notes": "keep me"}

    def test_the_evidence_key_set_is_exactly_what_this_test_covers(self):
        # Drift detection, kept SEPARATE from the poison below. Generating
        # both the poison and the expected-absence from the production set
        # would shrink this test in lockstep with production: delete a key
        # there and the test stops poisoning it, then passes.
        assert _EVIDENCE_ONLY_METADATA_KEYS == _EXPECTED_EVIDENCE_KEYS

    def test_every_evidence_only_metadata_key_is_stripped(self):
        # Poison and assertion both built from the FROZEN set above, so
        # removing any one key from production fails here.
        poisoned = dict.fromkeys(_EXPECTED_EVIDENCE_KEYS, "leaked")
        # A separate, unknown-only metadata key — not part of the evidence set.
        poisoned["deadline_note"] = "rolling"
        poisoned["notes"] = "keep"
        out = project_public_opportunity_payload(
            {**_UNKNOWN, "metadata": poisoned}, _UNKNOWN,
        )
        # Exact, not "some removed": every internal path is gone and the one
        # unrelated key survives untouched.
        assert out["metadata"] == {"notes": "keep"}

    def test_only_metadata_is_stripped_not_public_faculty_fields(self):
        # `metadata.faculty_availability_status` is the scan's own bookkeeping
        # and goes. The TOP-LEVEL field of the same name is a deliberate part
        # of the payload and must survive — same name, opposite decision.
        faculty = {
            **_FACULTY,
            "faculty_availability_status": "research_inactive",
            "faculty_title": "Associate Professor",
            "metadata": {"faculty_availability_status": "research_inactive", "notes": "n"},
        }
        out = project_public_opportunity_payload(dict(faculty), faculty)
        assert out["faculty_availability_status"] == "research_inactive"
        assert out["faculty_title"] == "Associate Professor"
        assert out["metadata"] == {"notes": "n"}

    def test_an_unknown_row_that_also_states_a_closure_still_loses_everything(self):
        # Kind drives neutralization, reason drives copy. The closure is the
        # more specific fact so it wins the reason — and reading eligibility
        # off the reason would let exactly these rows keep their offer terms.
        record = {**_UNKNOWN, "metadata": {**_UNKNOWN["metadata"], "urap_status": "closed"}}
        out = project_public_opportunity_payload(
            {**_UNKNOWN, "deadline": "2099-09-01", "paid": "stipend"}, record,
        )
        assert out["record_kind"] == "unknown"
        assert out["target_truth"]["reason_code"] == "listing_closed"
        assert "deadline" not in out
        assert "paid" not in out

    def test_a_non_actionable_listing_loses_its_application_url_but_keeps_its_links(self):
        closed = {**_LIVE_LISTING, "metadata": {"is_active": False}}
        out = project_public_opportunity_payload(
            {**_LIVE_LISTING, "url": "https://example.edu/read", "metadata": {}}, closed,
        )
        assert out["target_truth"]["actionable"] is False
        assert out["record_kind"] == "listing"
        assert out["application"]["application_url"] is None
        # Readable, always. A saved link has to keep working.
        assert out["url"] == "https://example.edu/read"

    def test_nested_hostile_values_are_projected_not_forwarded(self):
        payload = {
            **_LIVE_LISTING,
            "application": {
                "application_url": "javascript:alert(1)",
                "contact_source_url": "https://user:pw@example.edu/x",
            },
            "notes": ["reach jane@example.edu", {"deep": ({"href": "data:text/html,x"}, "bob@x.edu")}],
        }
        out = project_public_opportunity_payload(payload, _LIVE_LISTING)
        rendered = repr(out)
        assert "javascript:" not in rendered
        # Inside a tuple inside a dict inside a list: the URL contract is
        # keyed on the FIELD NAME, so the scheme check has to reach a nested
        # `href` the recursion could easily have stopped short of.
        assert "data:text/html" not in rendered
        assert "user:pw@example.edu" not in rendered
        assert "jane@example.edu" not in rendered
        assert "bob@x.edu" not in rendered

    def test_neither_input_is_mutated_and_no_mutable_descendant_is_shared(self):
        # Copy-on-write as a property of the function, not a habit of its
        # callers. The predecessor mutated its argument in place.
        payload = deepcopy(_LIVE_LISTING)
        payload["nested"] = {"list": [1, {"deep": "x"}], "tuple": ({"t": 1},)}
        record = deepcopy(_LIVE_LISTING)
        payload_before, record_before = deepcopy(payload), deepcopy(record)

        out = project_public_opportunity_payload(payload, record)
        out["nested"]["list"][1]["deep"] = "MUTATED"
        out["nested"]["list"].append("MUTATED")
        out["nested"]["tuple"][0]["t"] = 999
        out["eligibility"]["international_friendly"] = "MUTATED"
        out["metadata"]["notes"] = "MUTATED"
        out["application"]["application_url"] = "MUTATED"

        assert payload == payload_before
        assert record == record_before


class TestTheLifecycleTitleNeutralizer:
    """One shared helper, because the digest reads the raw corpus record.

    Two real rows (`b27723bb1ca91202`, `a22e863a3bd7ce87`) carry no
    `source_type`, so the truth contract answers `record_kind_unverified` —
    and their titles said "(applications open)" in the same payload.
    """

    def test_a_live_listing_keeps_its_suffix(self):
        assert neutralize_lifecycle_title(
            "Vision Lab RA (applications open)", _LIVE_LISTING,
        ) == "Vision Lab RA (applications open)"

    @pytest.mark.parametrize("title,expected", [
        # The two real shapes, including the one with a SECOND parenthetical
        # that must survive — an unanchored rule would eat both.
        (
            "URSA — Undergraduate Research in Scientific Advancement (applications open)",
            "URSA — Undergraduate Research in Scientific Advancement",
        ),
        (
            "CS DRP — Directed Reading Program (Computer Science, Winter Break) "
            "(applications open)",
            "CS DRP — Directed Reading Program (Computer Science, Winter Break)",
        ),
        ("Lab Assistant ( Applications  Open )", "Lab Assistant"),
        ("Lab Assistant (APPLICATION OPEN)", "Lab Assistant"),
    ])
    def test_an_unconfirmed_record_loses_the_opening_claim(self, title, expected):
        assert neutralize_lifecycle_title(title, _UNKNOWN) == expected

    @pytest.mark.parametrize("title", [
        # Not proven false by this incident, so not touched. "closed" is the
        # record AGREEING with the envelope; erasing it deletes a true
        # statement. The rest are ordinary English.
        "Summer Program (applications closed)",
        "Fall Recruiting (now open)",
        "Open House",
        "Directed Reading Program (Computer Science, Winter Break)",
        "Research Assistant (Physics)",
        # Non-terminal, so not a suffix at all. Dropping the `$` anchor would
        # cut this title in half and lose the part that says it is archived —
        # turning a truthful title into a misleading fragment.
        "X (applications open) — archived",
        "(applications open) programme retrospective",
    ])
    def test_it_removes_nothing_else(self, title):
        assert neutralize_lifecycle_title(title, _UNKNOWN) == title

    @pytest.mark.parametrize("title", [
        "  Open House  ",
        "\tResearch Assistant (Physics)\n",
        " Summer Program (applications closed) ",
    ])
    def test_a_non_matching_title_is_returned_byte_for_byte(self, title):
        # Including surrounding whitespace. An unconditional strip() would
        # rewrite titles this helper never matched, which is exactly the
        # generic normalization this fix is scoped not to be.
        assert neutralize_lifecycle_title(title, _UNKNOWN) == title

    def test_a_title_that_is_only_the_false_claim_does_not_survive(self):
        # The one shape where falling back to the original would hand back
        # exactly the claim this helper exists to remove. No corpus row is
        # this shape; if one appears it arrives nameless rather than lying.
        assert neutralize_lifecycle_title("(applications open)", _UNKNOWN) == ""


class TestKeywordProvenanceReachesTheClient:
    """A topic we inferred must not render identically to one they stated.

    5% of faculty rows carry keywords derived from a matched OpenAlex author
    record. An audit of 14 such rows found 4 attached to the wrong person — a
    UTK geographer working on GeoAI and remote sensing was showing a petroleum
    geophysicist's topics. The stamp recording that derivation has existed in
    `metadata.inferred_fields` since the enrichment was written and no route
    ever served it, so every surface presented an inference as a stated fact.

    This is the same contract `publication_attribution_status` already has, for
    the same reason: the client cannot re-derive it, and absent must keep
    meaning "stated" for every record that never went through enrichment.
    """

    @staticmethod
    def _record(inferred: bool) -> dict:
        record = {
            "id": "faculty-utk-geog-x", "title": "Bing Zhou",
            "source_type": "faculty_research", "pi_name": "Bing Zhou",
            "keywords": ["hydrocarbon exploration and reservoir analysis"],
            "metadata": {},
        }
        if inferred:
            record["metadata"] = {
                "inferred_fields": {"keywords": "derived:openalex_topics"}
            }
        return record

    def test_a_derived_keyword_is_labelled_on_the_wire(self):
        record = self._record(inferred=True)
        out = project_public_opportunity_payload(dict(record), record)
        assert out["keywords_attribution"] == "inferred"

    def test_a_stated_keyword_carries_no_label(self):
        """Absent means stated. Labelling everything would make the label
        meaningless and quietly downgrade the 41% who published their own."""
        record = self._record(inferred=False)
        out = project_public_opportunity_payload(dict(record), record)
        assert "keywords_attribution" not in out

    def test_a_record_with_no_keywords_is_not_labelled(self):
        record = self._record(inferred=True)
        record["keywords"] = []
        out = project_public_opportunity_payload(dict(record), record)
        assert "keywords_attribution" not in out

    def test_the_label_follows_the_canonical_record_not_the_payload(self):
        """Same rule identity already follows: a payload that arrived without
        metadata — every card, since _CARD_OPP_FIELDS excludes it — must still
        be labelled from the record the projection was given."""
        record = self._record(inferred=True)
        card = {"id": record["id"], "title": record["title"],
                "keywords": record["keywords"]}
        out = project_public_opportunity_payload(card, record)
        assert out["keywords_attribution"] == "inferred"


class TestInventedSkillsAreLabelledOnTheWire:
    """The detail page printed "REQUIRED SKILLS / Python / MATLAB" for a
    wet-lab biology REU whose own page lists only timing and a deadline.
    The stamp existed in the data (#826); nothing put it on the wire."""

    @staticmethod
    def _program(inferred: bool) -> dict:
        record = {
            "id": "sro-3c378261", "title": "Cellular and Molecular Biology of Stress Summer Research Program",
            "source_type": "summer_program", "organization": "University of Wisconsin-Madison",
            "eligibility": {"skills_required": ["Python", "MATLAB"]},
            "metadata": {},
        }
        if inferred:
            record["metadata"] = {"inferred_fields": {"eligibility.skills_required": "rule:llm_tagger"}}
        return record

    def test_a_tagger_written_requirement_is_labelled(self):
        record = self._program(inferred=True)
        out = project_public_opportunity_payload(dict(record), record)
        assert out["skills_attribution"] == "inferred"

    def test_a_stated_requirement_carries_no_label(self):
        record = self._program(inferred=False)
        out = project_public_opportunity_payload(dict(record), record)
        assert "skills_attribution" not in out

    def test_an_empty_list_is_not_labelled(self):
        record = self._program(inferred=True)
        record["eligibility"]["skills_required"] = []
        out = project_public_opportunity_payload(dict(record), record)
        assert "skills_attribution" not in out

    def test_the_card_is_labelled_from_the_canonical_record(self):
        record = self._program(inferred=True)
        card = {"id": record["id"], "title": record["title"], "eligibility": dict(record["eligibility"])}
        out = project_public_opportunity_payload(card, record)
        assert out["skills_attribution"] == "inferred"


class TestApproximateMajorsAreLabelledOnTheWire:
    """#862 stamped the SRO major lists as ours and stopped the matcher calling
    them a stated preference. The detail page still printed them under
    "MAJORS", so the student read our keyword-bank guess as the program's own
    eligibility terms. 433 live records carry such a list."""

    @staticmethod
    def _program(inferred: bool) -> dict:
        record = {
            "id": "sro-majors", "title": "Summer Research Opportunities Program",
            "source_type": "summer_program", "organization": "Test University",
            "eligibility": {"majors": ["Biology", "Chemistry"]},
            "metadata": {},
        }
        if inferred:
            record["metadata"] = {
                "inferred_fields": {"eligibility.majors": "rule:research_area_bank"}
            }
        return record

    def test_a_bank_written_major_list_is_labelled(self):
        record = self._program(inferred=True)
        out = project_public_opportunity_payload(dict(record), record)
        assert out["majors_attribution"] == "inferred"

    def test_a_stated_major_list_carries_no_label(self):
        record = self._program(inferred=False)
        out = project_public_opportunity_payload(dict(record), record)
        assert "majors_attribution" not in out

    def test_an_empty_list_is_not_labelled(self):
        record = self._program(inferred=True)
        record["eligibility"]["majors"] = []
        out = project_public_opportunity_payload(dict(record), record)
        assert "majors_attribution" not in out

class TestGuessedPayIsLabelledButAPublishedRequirementIsNot:
    """A green "Paid" badge on "in many cases, funding or a stipend" is a
    student planning a summer around money we guessed at. 220 records carry a
    pay value the tagger read off prose.

    NSF REU Sites are the deliberate exception: the solicitation requires a
    stipend, so `policy:nsf_reu_solicitation` is a published requirement of the
    funding program rather than a reading of the page. Hedging those 154 would
    hide real money from a student who cannot take an unpaid summer.
    """

    @staticmethod
    def _program(method: str | None) -> dict:
        record = {
            "id": "prog-pay", "title": "Undergraduate Research Program",
            "source_type": "summer_program", "organization": "Test University",
            "paid": "yes", "eligibility": {}, "metadata": {},
        }
        if method:
            record["metadata"] = {"inferred_fields": {"paid": method}}
        return record

    def test_a_pay_value_read_off_prose_is_labelled(self):
        record = self._program("rule:llm_tagger")
        out = project_public_opportunity_payload(dict(record), record)
        assert out["paid_attribution"] == "inferred"

    def test_a_published_funder_requirement_is_not_labelled(self):
        record = self._program("policy:nsf_reu_solicitation")
        out = project_public_opportunity_payload(dict(record), record)
        assert "paid_attribution" not in out

    def test_a_stated_pay_value_carries_no_label(self):
        record = self._program(None)
        out = project_public_opportunity_payload(dict(record), record)
        assert "paid_attribution" not in out

    def test_an_unknown_pay_value_is_not_labelled(self):
        record = self._program("rule:llm_tagger")
        record["paid"] = "unknown"
        out = project_public_opportunity_payload(dict(record), record)
        assert "paid_attribution" not in out


class TestAGuessedEligibilityRestrictionIsLabelled:
    """186 live listings say international_friendly='no' and
    citizenship_required=True. 154 are NSF REU Sites, where the solicitation
    really does restrict eligibility to US citizens and permanent residents.
    The other 32 are the LLM tagger reading a federal-organisation or title
    substring, and an international student who believes one self-selects out
    of a program that would have taken them. 70 more carry a class-year list
    the tagger read out of prose.

    Same predicate as the pay badge: `policy:` is a published requirement of
    the funding program; everything else is a reading of the page.
    """

    @staticmethod
    def _program(method: str | None) -> dict:
        record = {
            "id": "prog-intl", "title": "Summer Research Program",
            "source_type": "summer_program", "organization": "Test University",
            "eligibility": {
                "international_friendly": "no", "citizenship_required": True,
                "preferred_year": ["senior"],
            },
            "metadata": {},
        }
        if method:
            record["metadata"] = {"inferred_fields": {
                "eligibility.international_friendly": method,
                "eligibility.citizenship_required": method,
                "eligibility.preferred_year": method,
            }}
        return record

    def test_a_tagger_read_restriction_is_labelled(self):
        record = self._program("rule:llm_tagger")
        out = project_public_opportunity_payload(dict(record), record)
        assert out["international_attribution"] == "inferred"
        assert out["citizenship_attribution"] == "inferred"
        assert out["preferred_year_attribution"] == "inferred"

    def test_the_nsf_solicitation_is_not_a_guess(self):
        record = self._program("policy:nsf_reu_solicitation")
        out = project_public_opportunity_payload(dict(record), record)
        assert "international_attribution" not in out
        assert "citizenship_attribution" not in out

    def test_a_stated_restriction_carries_no_label(self):
        record = self._program(None)
        out = project_public_opportunity_payload(dict(record), record)
        for key in ("international_attribution", "citizenship_attribution",
                    "preferred_year_attribution"):
            assert key not in out

    def test_an_absent_value_is_not_labelled(self):
        record = self._program("rule:llm_tagger")
        record["eligibility"] = {}
        out = project_public_opportunity_payload(dict(record), record)
        for key in ("international_attribution", "citizenship_attribution",
                    "preferred_year_attribution"):
            assert key not in out


class TestADerivedPiNameIsNotServed:
    """pi_name is derived by taking the word before "Laboratory" or "Group" in
    the program title. On the served corpus all 36 distinct derived names are
    institutions or plain nouns — Volkswagen, Cigna, Expedia, Jackson, Spring
    Harbor, Analysis, Market — so the detail page was printing "Faculty member:
    Spring Harbor" as fact."""

    @staticmethod
    def _program(inferred: bool) -> dict:
        opp = {
            "id": "sro-cshl", "title": "Cold Spring Harbor Laboratory Program",
            "source_type": "program", "opportunity_type": "summer_program",
            "organization": "Cold Spring Harbor Laboratory",
            "lab_or_program": "Cold Spring Harbor Laboratory Undergraduate Program",
            "pi_name": "Spring Harbor", "eligibility": {}, "metadata": {},
        }
        if inferred:
            opp["metadata"] = {
                "inferred_fields": {"pi_name": "rule:lab_title_surname"}
            }
        return opp

    def test_a_derived_name_never_reaches_the_page(self):
        record = self._program(inferred=True)
        served = project_public_opportunity_payload(dict(record), record)
        assert "pi_name" not in served

    def test_a_real_name_is_untouched(self):
        record = self._program(inferred=False)
        served = project_public_opportunity_payload(dict(record), record)
        assert served["pi_name"] == "Spring Harbor"
