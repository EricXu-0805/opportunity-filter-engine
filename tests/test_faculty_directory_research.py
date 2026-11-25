from copy import deepcopy

import pytest

from backend.data_loader import _sanitize_opportunity
from backend.lib.opportunity_detail import build_detail_fields
from src.collectors import faculty_graph as fg
from src.collectors.schools.lsu_faculty import SCHOOL
from src.collectors.uiuc_faculty import _carry_forward_enrichment
from src.evidence import DEPARTMENT_FIELD_METHOD, inferred_method, stamp_inferred
from src.recommender.cold_email import generate_cold_email, generate_variants


def _row(source, department, raw, keywords):
    return {
        "id": "faculty-test", "source_type": "faculty_research", "source": source,
        "title": "Prof. Alex Smith", "pi_name": "Alex Smith", "department": department,
        "organization": "Example University", "url": "https://example.edu/smith",
        "keywords": keywords, "eligibility": {}, "application": {},
        "metadata": {"faculty_title": "Professor", "research_areas_raw": raw,
                     "is_active": True, "last_verified": "2026-11-20",
                     "research_areas_verified_at": "2026-11-18"},
    }


def _emails(record):
    student = {"name": "Jamie", "major": "Biology", "year": "sophomore", "hard_skills": []}
    return [generate_cold_email(student, record),
            *(draft["text"] for draft in generate_variants(student, record))]


def test_school_label_keeps_only_inferred_search_keywords_in_the_detail_and_mail():
    record = _sanitize_opportunity(_row("lsu_faculty", "School of Architecture",
                                        "Architecture", ["Architecture"]))
    field = build_detail_fields(record, record)["fields"]["research_content"]
    assert not field["explicit"]
    assert field["inferred"]["research_areas"]["value"] == ["Architecture"]
    assert field["provenance"]["observed_at"] is None
    assert "research_areas_verified_at" not in record["metadata"]
    assert all(mail.splitlines()[0] == "Subject: Research inquiry" for mail in _emails(record))
    assert all("your work on architecture" not in mail.lower() for mail in _emails(record))
    again = _sanitize_opportunity(deepcopy(record))
    assert again["metadata"] == record["metadata"]


@pytest.mark.parametrize(("source", "dept", "raw"), [
    ("lsu_faculty", "School of Animal Sciences", "School of Animal Science"),
    ("lsu_faculty", "School of Interior Design", "Architecture/Interior Design"),
    ("lsu_faculty", "Robert Reich School of Landscape Architecture", "Landscape Architecture"),
    ("macalester_faculty", "Department of Mathematics, Statistics, and Computer Science", "Mathematics"),
])
def test_fallback_cannot_return_through_enrichment_carry(source, dept, raw):
    old = _row(source, dept, raw, [])
    fresh = _row(source, dept, "", [])
    fresh["metadata"].pop("research_areas_verified_at")
    _carry_forward_enrichment(old, fresh)
    assert not fresh["metadata"].get("research_areas_raw")
    assert "research_areas_verified_at" not in fresh["metadata"]


def test_cleanup_keeps_independent_enrichment_and_its_attribution():
    record = _row("lsu_faculty", "School of Architecture", "Architecture", ["coastal planning"])
    stamp_inferred(record["metadata"], "keywords", "derived:openalex_topics")
    served = _sanitize_opportunity(record)
    assert not served["metadata"]["research_areas_raw"]
    assert served["keywords"] == ["coastal planning"]
    assert inferred_method(served, "keywords") == "derived:openalex_topics"


@pytest.mark.parametrize(("source", "dept", "raw"), [
    ("utexas_faculty", "Department of Mathematics", "Mathematics"),
    ("utexas_faculty", "Department of Neuroscience", "Neuroscience"),
    ("vassar_faculty", "Department of Hispanic Studies", "Hispanic Studies"),
    ("uconn_faculty", "Department of Agricultural and Resource Economics", "Agricultural and Resource economics"),
    ("lsu_faculty", "School of Animal Sciences", "Veterinary Parasitology"),
    ("lsu_faculty", "School of Art", "Art/Printmaking"),
    ("macalester_faculty", "Department of Mathematics, Statistics, and Computer Science", "Mathematics, Harmonic Analysis"),
])
def test_source_stated_fields_and_specialties_keep_their_evidence(source, dept, raw):
    record = _sanitize_opportunity(_row(source, dept, raw, [raw]))
    field = build_detail_fields(record, record)["fields"]["research_content"]
    assert field["explicit"]["research_areas"] == raw
    assert field["provenance"]["observed_at"] == "2026-11-18"


def test_new_lsu_harvest_keeps_directory_label_out_of_source_text():
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "ARCH")
    person = fg.faculty("Alex Smith", title="Professor", research_areas="Architecture")
    out = fg._normalize(SCHOOL, dept, person)
    assert out["keywords"] == ["Architecture"]
    assert out["metadata"]["research_areas_raw"] == ""
    assert inferred_method(out, "keywords") == DEPARTMENT_FIELD_METHOD
    assert "Research areas:" not in out["description_raw"]


def test_clause_fragments_never_become_email_subjects_and_leave_the_statement_intact():
    raw = ("The synthesis of elements and the generation of energy in stars is strongly "
           "influenced by the properties of nuclei and the speed with which reactions take place.")
    fragments = ["which", "takes place in novae and supernovae"]
    record = _sanitize_opportunity(_row("nd_faculty", "Department of Physics and Astronomy", raw, fragments))
    assert record["metadata"]["research_areas_raw"] == raw
    assert record["keywords"] == []
    assert all("which" not in mail.splitlines()[0].lower() for mail in _emails(record))
    good = ["which-path interferometry", "which way information", "nuclear astrophysics"]
    assert fg._clean_keywords({"keywords": [*fragments, *good]}) == good


@pytest.mark.parametrize(("source", "department", "raw", "keywords"), [
    ("lsu_faculty", "School of Architecture", "Architecture", ["Architecture"]),
    ("nd_faculty", "Department of Physics and Astronomy", "", ["which", "takes place in novae and supernovae"]),
])
def test_drafts_accepting_a_raw_shard_use_the_same_evidence_without_mutation(source, department, raw, keywords):
    record = _row(source, department, raw, keywords)
    before = deepcopy(record)
    assert all(mail.splitlines()[0] == "Subject: Research inquiry" for mail in _emails(record))
    assert record == before
