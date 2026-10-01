"""Source receipt outcomes survive storage without claiming unsupported pages are empty."""
from copy import deepcopy

import pytest

from backend.lib.public_opportunity_detail import project_public_detail
from src.contact_instructions import (
    CAPTURE_KEY,
    SOURCE_KEY,
    capture_failure,
    capture_from_html,
    capture_from_sections,
    capture_metadata,
    same_source_page,
    source_from_html,
)

URL = "https://program.example.edu/research"
STAMP = "2026-09-28T12:00:00Z"


def capture(body):
    return capture_from_html("<html><body><main>" + body + "</main></body></html>",
                             source_url=URL, checked_at=STAMP)


def test_empty_is_explicit_but_unknown_dom_is_not_empty():
    checked = capture("<h1>Research</h1><p>We study robotics.</p>")
    assert checked["status"] == "empty"
    assert capture_metadata(checked)[SOURCE_KEY] == []
    unsupported = capture("<h1>Research</h1><div>We study robotics.</div>")
    assert unsupported["status"] == "unsupported"
    assert SOURCE_KEY not in capture_metadata(unsupported)


def test_capture_keeps_full_quote_and_source_time_independent_of_attempt_metadata():
    paragraph = "Undergraduates should apply with a CV. " + "Additional detail. " * 80
    result = capture("<h2>Undergraduate applicants</h2><p>" + paragraph + "</p>")
    before = deepcopy(result)
    meta = capture_metadata(result)
    assert meta[CAPTURE_KEY]["status"] == "captured"
    assert meta[CAPTURE_KEY]["attempted_at"] == STAMP
    assert meta[SOURCE_KEY][0]["checked_at"] == STAMP
    assert meta[SOURCE_KEY][0]["sections"][0]["text"] == paragraph.strip()
    meta[SOURCE_KEY][0]["sections"][0]["text"] = "Changed"
    assert result == before


@pytest.mark.parametrize("title", [
    "Sign in", "Log In", "Access denied", "Attention required",
    "Just a moment...", "Page not found", "404", "Service unavailable",
    "One moment, please...", "Making sure you're not a bot!", "Pardon Our Interruption",
])
def test_access_and_error_pages_are_not_a_successful_empty_check(title):
    result = capture("<h1>" + title + "</h1><p>Please contact the administrator.</p>")
    assert result["status"] == "unsupported"
    assert SOURCE_KEY not in capture_metadata(result)


# Bot-check names count only as a whole heading; a research page can open with them.
@pytest.mark.parametrize("title", [
    "Human verification: a psychology study", "Security Checkpoint - Airport Screening Research",
    "Bot Verification | Undergraduate security research",
])
def test_heading_that_only_begins_with_a_bot_check_name_is_still_read(title):
    result = capture("<h1>" + title + "</h1><p>We study robotics.</p>")
    assert result["status"] == "empty"


def test_password_form_is_not_a_successful_source_page():
    result = capture('<h1>University SSO</h1><p>Apply now.</p><input type="password">')
    assert result["status"] == "unsupported"


def test_unparsed_relevant_field_prevents_partial_source_and_false_empty():
    result = capture("<p>Our research focuses on water.</p><div>Minimum GPA: 3.0.</div>")
    assert (result["status"], result["reason"]) == ("unsupported", "unparsed_relevant_content")
    assert SOURCE_KEY not in capture_metadata(result)


def test_raw_section_adapter_uses_real_label_and_does_not_invent_a_label():
    result = capture_from_sections([{"heading": "Eligibility", "text": "Sophomores only."}],
                                   source_url=URL, checked_at=STAMP)
    assert result["status"] == "captured"
    assert result["sources"][0]["sections"] == [{"heading": "Eligibility", "text": "Sophomores only."}]
    # An unlabeled value cannot acquire a generated eligibility heading.
    unlabeled = capture_from_sections([{"heading": "", "text": "Sophomores only."}], source_url=URL)
    assert unlabeled["status"] == "empty"


@pytest.mark.parametrize("sections", [
    [], None, "Minimum GPA: 3.0.", [{}], [{"heading": "Eligibility", "text": ""}],
    [{"heading": ["Eligibility"], "text": "Minimum GPA 3.0."}],
    [{"heading": "Eligibility", "text": "x" * 4001}],
    [{"heading": "x" * 1001, "text": "Minimum GPA 3.0."}],
    [{"heading": "Eligibility", "text": "GPA 3.0."}] * 161,
])
def test_unsupported_sections_cannot_clear_previous_success(sections):
    result = capture_from_sections(sections, source_url=URL)
    assert result["status"] == "unsupported"
    assert SOURCE_KEY not in capture_metadata(result)


def test_navigation_and_metadata_do_not_manufacture_relevant_sections():
    result = capture('<nav><p>Submit an application.</p></nav><p>We study robotics.</p>')
    assert result["status"] == "empty"


def test_failed_attempt_has_no_sources_or_success_time():
    result = capture_failure(source_url=URL, identity_name="Jane Scientist",
                             checked_at=STAMP, reason="fetch_timeout")
    assert result["status"] == "failed"
    assert result["attempted_at"] == STAMP
    assert "checked_at" not in result
    assert result["identity_name"] == "Jane Scientist"
    assert SOURCE_KEY not in capture_metadata(result)


@pytest.mark.parametrize("url", ["", "file:///tmp/page", "https://user:pass@example.edu"])
def test_invalid_source_binding_cannot_be_successful(url):
    result = capture_from_html("<body><p>Apply with a CV.</p></body>", source_url=url)
    assert result["status"] == "unsupported"


def test_compatibility_reader_keeps_adjacent_list_whole():
    source = source_from_html("<body><h2>Undergraduate applicants</h2>"
                              "<p>Email us and include:</p><ul><li>CV</li><li>Transcript</li></ul></body>",
                              source_url=URL)
    assert source["sections"][0]["text"] == "Email us and include:\nCV Transcript"


def test_public_projection_uses_sources_without_exposing_internal_attempt_receipt():
    result = capture("<h2>Eligibility</h2><p>Minimum GPA: 3.0.</p>")
    raw = {"id": "capture-receipt-test", "title": "Summer program", "source_type": "summer_program",
           "url": URL, "source_url": URL, "metadata": capture_metadata(result)}
    original = deepcopy(raw)
    public = project_public_detail(raw)
    assert CAPTURE_KEY not in public["metadata"]
    assert SOURCE_KEY not in public["metadata"]
    assert next(row for row in public["target_conditions"]["conditions"]
                if row["field"] == "eligibility.min_gpa")["usage"] == "usable"
    assert raw == original



@pytest.mark.parametrize("requested,final,expected", [
    ("https://example.edu/apply", "https://example.edu/apply/", True),
    ("http://example.edu/apply", "https://example.edu/apply", True),
    ("http://example.edu:80/apply", "https://example.edu:443/apply/", True),
    ("https://example.edu/apply#details", "https://example.edu/apply", True),
    ("https://example.edu/apply", "http://example.edu/apply", False),
    ("https://example.edu/apply", "https://example.edu/", False),
    ("https://example.edu/apply?a=1", "https://example.edu/apply?a=2", False),
    ("https://example.edu/apply", "https://other.edu/apply", False),
    ("https://example.edu:8443/apply", "https://example.edu/apply", False),
    ("https://example.edu/apply", "https://example.edu:bad/apply", False),
    ("https://example.edu/apply", "https://user:password@example.edu/apply", False),
])
def test_redirect_equivalence_keeps_resource_identity(requested, final, expected):
    assert same_source_page(requested, final) is expected


def test_unparsed_value_inherits_relevant_heading_in_incomplete_capture_check():
    result = capture("<p>Our lab studies sensors.</p><h2>Minimum GPA</h2><div>3.0</div>")
    assert (result["status"], result["reason"]) == ("unsupported", "unparsed_relevant_content")
    assert SOURCE_KEY not in capture_metadata(result)


def test_unparsed_qualifier_cannot_be_dropped_after_a_supported_requirement():
    result = capture("<h2>Eligibility</h2><p>Minimum GPA: 3.0.</p><div>Exceptions may be considered.</div>")
    assert result["status"] == "unsupported"
    assert SOURCE_KEY not in capture_metadata(result)
