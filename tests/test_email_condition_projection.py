"""Public source receipts cannot bypass identity, privacy or target versions."""
from copy import deepcopy
from datetime import UTC, datetime

from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.lib.public_projection import project_public_opportunity_payload

URL = "https://program.example.edu/apply"


def record(*paragraphs):
    stamp = datetime.now(UTC).isoformat()
    return {"id": "b54-projection", "source_type": "summer_program", "title": "Summer research",
            "url": URL, "source_url": URL, "eligibility": {}, "application": {},
            "metadata": {"is_active": True, "last_verified": stamp, "contact_instruction_sources": [
                {"source_url": URL, "record_source_url": URL, "checked_at": stamp,
                 "sections": [{"heading": "Undergraduate applicants", "text": p} for p in paragraphs]}]}}


def rows(public):
    return {row["field"]: row for row in public["target_conditions"]["conditions"]}


def test_detail_retains_usable_terms_but_removes_internal_source_blocks():
    raw = record("Minimum GPA: 3.0.", "Applicants must submit a resume.")
    previous = deepcopy(raw)
    public = project_public_detail(raw)
    assert rows(public)["eligibility.min_gpa"]["usage"] == "usable"
    assert rows(public)["application.requires_resume"]["usage"] == "usable"
    assert "contact_instruction_sources" not in public["metadata"]
    assert raw == previous
    public["target_conditions"]["conditions"][0]["sources"][0]["quote"] = "Mutated"
    assert raw == previous


def test_privacy_changes_retire_only_affected_condition_and_recompute_template():
    public = project_public_detail(record("Minimum GPA: 3.0. Email private.person@example.edu.",
                                         "Applicants must submit a resume."))
    assert rows(public)["eligibility.min_gpa"] == {
        "field": "eligibility.min_gpa", "category": "eligibility", "status": "unknown",
        "value": None, "usage": "excluded", "reason": "source_not_public", "sources": []}
    assert rows(public)["application.requires_resume"]["usage"] == "usable"
    assert "resume" in public["target_conditions"]["template_request"]
    assert "private.person" not in str(public)


def test_cached_public_receipt_is_never_trusted_or_promoted():
    raw = record()
    poison = {"version": 1, "record_kind": "listing", "conditions": [
        {"field": "eligibility.min_gpa", "category": "eligibility", "status": "stated", "usage": "usable",
         "value": 4.0, "reason": "source_stated", "sources": []}], "template_request": "I qualify."}
    raw["target_conditions"] = poison
    public = project_public_detail(raw)
    assert public["target_conditions"]["conditions"] == []
    other = project_public_opportunity_payload({"target_conditions": poison}, raw)
    assert other["target_conditions"] == public["target_conditions"]
    assert raw["target_conditions"] == poison


def test_removed_evidence_changes_version_without_reusing_usable_receipt():
    raw = record("Minimum GPA: 3.0.")
    first = project_public_detail(raw)
    raw["eligibility"]["min_gpa"] = 3.0
    raw["metadata"].pop("contact_instruction_sources")
    raw["target_conditions"] = first["target_conditions"]
    second = project_public_detail(raw)
    assert rows(second)["eligibility.min_gpa"]["status"] == "unverified"
    assert writing_target_version(first) != writing_target_version(second)


def test_compact_list_payload_does_not_gain_the_full_condition_document():
    assert "target_conditions" not in project_public_opportunity_payload({"id": "ignored"}, record("Minimum GPA: 3.0."))
