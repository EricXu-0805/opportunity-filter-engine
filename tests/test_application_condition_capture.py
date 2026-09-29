"""Retain full application-condition passages without inventing contact rules."""
from src.contact_instructions import SOURCE_KEY, contact_instructions_for, source_from_html

URL = "https://program.example.edu/apply"
STAMP = "2026-09-28T12:00:00Z"


def capture(body):
    return source_from_html("<html><body><main>" + body + "</main></body></html>",
                            source_url=URL, checked_at=STAMP)


def test_eligibility_heading_keeps_complete_unlabelled_values_and_qualifiers():
    text = "A minimum of 3.0 is required. " + "Additional details. " * 60 + "Exceptions may be considered."
    source = capture("<h2>Eligibility</h2><p>" + text + "</p>")
    assert source is not None
    assert source["sections"] == [{"heading": "Eligibility", "text": text}]
    assert source["checked_at"] == STAMP
    assert source["record_source_url"] == URL


def test_dates_and_materials_under_scoped_headings_are_retained_without_guessing_year():
    source = capture("<h2>Undergraduate program</h2><h3>Deadline</h3><p>February 15, 5 PM.</p>"
                     "<h3>Required materials</h3><ul><li>Two references</li><li>One-page statement</li></ul>")
    assert source is not None
    assert [s["text"] for s in source["sections"]] == ["February 15, 5 PM.", "Two references One-page statement"]
    assert "year" not in source
    assert source["sections"][0]["heading"] == "Undergraduate program > Deadline"


def test_condition_words_in_body_do_not_require_contact_vocabulary():
    source = capture("<p>U.S. citizenship is required.</p><p>Rolling admission.</p>"
                     "<p>Minimum GPA: 3.0.</p><p>Python is preferred, not required.</p>")
    assert source is not None
    assert len(source["sections"]) == 4


def test_chinese_conditions_are_retained_as_source_text_without_translation():
    source = capture("<h2>申请资格</h2><p>限本科三年级学生；不要求美国国籍。</p>"
                     "<h2>截止日期</h2><p>2月15日，时区待确认。</p>")
    assert source is not None
    assert len(source["sections"]) == 2
    assert source["sections"][1]["text"] == "2月15日，时区待确认。"


def test_retention_does_not_promote_conditions_into_contact_permission():
    source = capture("<h2>Undergraduate eligibility</h2><p>Minimum GPA: 3.0.</p>")
    assert source is not None
    assert contact_instructions_for({"url": URL, "metadata": {SOURCE_KEY: [source]}}) == {
        "version": 1, "status": "unknown", "email_policy": "unknown", "rules": []}


def test_navigation_metadata_and_unrelated_research_are_not_captured():
    source = source_from_html('<html><head><meta property="og:description" content="GPA 3.0 required"></head>'
                              '<body><nav><h2>Eligibility</h2><p>GPA 3.0 required</p></nav>'
                              '<main><h2>Research</h2><p>We study robotics.</p></main></body></html>',
                              source_url=URL, checked_at=STAMP)
    assert source is None


def test_oversized_condition_is_refused_without_prefix_capture():
    assert capture("<h2>Eligibility</h2><p>" + "x" * 4001 + "</p>") is None
