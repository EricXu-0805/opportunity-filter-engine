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
from tests.test_import_document import _deadline

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
    "Bot Verification | Undergraduate security research", "Checking your browser settings",
    "Checking your browser before proceedings begin",
])
def test_heading_that_only_begins_with_a_bot_check_name_is_still_read(title):
    result = capture("<h1>" + title + "</h1><p>We study robotics.</p>")
    assert result["status"] == "empty"


# The whole stock heading, with the site name some checks print after it and
# the punctuation they end in, is a bot check.
@pytest.mark.parametrize("title", [
    "Checking your browser", "Checking your browser...", "Checking your browser before accessing",
    "Checking your browser before accessing example.edu", "Checking your browser before proceeding.",
    "Checking your browser before continuing to example.edu…!",
    "Human Verification", "Bot verification!", "DDoS-Guard", "Sign in - Example University", "Access denied!!",
    "One moment, please…", "One moment please", "Verify you are a human", "Making sure you’re not a bot",
    "Robot Challenge Screen",
])
def test_whole_bot_check_heading_is_an_access_page(title):
    result = capture("<h1>" + title + "</h1><p>We study robotics.</p>")
    assert (result["status"], result["reason"]) == ("unsupported", "access_page")


# The <title> and the first <h1> are matched whole against the blocked-title
# rule. A run of '.', '!' or '…' after "checking your browser before
# proceeding", then a newline, used to be retried at every split of the run.
@pytest.mark.parametrize("mark", [".", "!", "…"])
@pytest.mark.parametrize("where", ["title", "h1"])
def test_blocked_title_rule_reads_a_long_punctuation_run_in_linear_time(where, mark):
    heading = "Checking your browser before proceeding" + mark * 50_000 + "\nThe lab"
    title, h1 = (heading, "Research") if where == "title" else ("Research", heading)
    html = (f"<html><head><title>{title}</title></head><body><main><h1>{h1}</h1>"
            "<p>We study robotics.</p></main></body></html>")
    with _deadline(2):
        result = capture_from_html(html, source_url=URL, checked_at=STAMP)
    # A heading that long is past the capture's section limit; the title is not a section.
    assert (result["status"], result["reason"]) == (("empty", None) if where == "title" else ("unsupported", "content_limit"))


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


# The capture reads a page in time linear in its size. It used to walk up from
# each heading, paragraph and list through every tag above it, read each nested
# one's text again, and build a reparsed copy of the page whose leftovers it
# removed one by one, each removal searching its parent's children. Each page
# took the seconds shown with the old capture (one run each).
@pytest.mark.parametrize("body", [
    pytest.param("<h2>Lab</h2><p>We study soil.</p>" + "<h1>" * 4000 + "x", id="4000-nested-h1-7.0s"),
    pytest.param("<h2>Lab</h2><p>We study soil.</p>" + "<ul>" * 4000 + "x", id="4000-nested-ul-6.3s"),
    pytest.param("<h2>Lab</h2><p>We study soil.</p><template>" + "<p>" * 4000 + "x", id="4000-nested-p-10.4s"),
    pytest.param("<h2>Lab</h2><p>We study soil.</p>" + "<nav>x</nav><span>y</span>" * 20_000,
                 id="20000-navs-among-text-3.9s"),
    # Every heading inside another holds its text: 1,000 characters each here.
    # The crawlers parse pages without the URL reader's depth limit. The old
    # capture took 7.0 s at 4,000 headings, four times longer per doubling.
    pytest.param("<h2>Lab</h2><p>We study soil.</p>" + "<h2>" * 40_000 + "word " * 199 + "word",
                 id="40000-nested-h2-around-1000-characters"),
])
def test_deep_or_crowded_page_is_captured_in_linear_time(body):
    with _deadline(2):
        result = capture(body)
    assert result["status"] in ("empty", "captured")


def test_page_bs4_could_not_serialize_is_still_captured():
    # The capture used to serialize the page to reparse it. bs4 compares tags
    # whole whenever serialization closes one, recursing through matching
    # children: 250 of these nested blocks raised RecursionError, and
    # /api/import-url answered 500 on a page the reader had read.
    with _deadline(2):
        result = capture("<h2>Lab</h2><p>We study soil.</p>" + "<div><b>x</b>" * 300 + "<i>y</i></div>" * 300)
    assert result["status"] == "empty"


# Text outside every heading, paragraph and list is weighed as it read from a
# reparsed copy of the page: strings with nothing between them run together,
# and only tags inside the captured part decide which strings count.
@pytest.mark.parametrize("html,reason", [
    pytest.param("<main><h2>Lab</h2><p>We study soil.</p>e</x>mail the lab</main>", "unparsed_relevant_content",
                 id="word-split-by-a-stray-end-tag"),
    pytest.param("<main><h2>Lab</h2><p>We study soil.</p>e<!-- -->mail the lab</main>", None,
                 id="word-split-by-a-comment"),
    pytest.param("<template><main><p>We study soil.</p>Contact the lab.</main></template>", "unparsed_relevant_content",
                 id="part-inside-a-template"),
    pytest.param("<main><h2>Lab</h2><p>We study soil.</p><ruby>x<rt>Email us</rt></ruby></main>", None,
                 id="ruby-text"),
])
def test_text_outside_sections_is_weighed_as_before(html, reason):
    result = capture_from_html(html, source_url=URL, checked_at=STAMP)
    assert result.get("reason") == reason
