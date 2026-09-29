"""Independent held-out checks across real lexical writers and consumers."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from backend.lib.public_projection import project_public_opportunity_payload
from src.collectors.base import RawOpportunity
from src.collectors.url_parser import _merge_llm_into_base
from src.matcher.ranker import score_eligibility
from src.normalizers.enricher import enrich_opportunity
from src.normalizers.normalizer import normalize
from src.parsers.llm_tagger import apply_updates, rule_based_tag
from src.recommender.cold_email import _stated_required_skills


def pipeline(text):
    row = normalize(
        {
            "id": "held-out",
            "title": "Summer project",
            "source": "manual",
            "source_type": "manual",
            "description_raw": text,
        }
    )
    enrich_opportunity(row)
    apply_updates(row, rule_based_tag(row))
    return row


@pytest.mark.parametrize(
    "text,forbidden",
    [
        ("Application materials A CV is required.", {"R", "Go", "Git", "IS"}),
        ("Applicants must have JavaScript programming experience.", {"Java", "R"}),
        ("Please go to the program website. Digital materials are available.", {"Go", "Git", "R"}),
        ("No Python experience is required. Training will be provided.", {"Python"}),
        ("We study vitamin C and nutrition. Read the project before applying.", {"C", "R"}),
    ],
)
def test_false_lexical_labels_cannot_reappear_in_later_writers(text, forbidden):
    row = pipeline(text)
    labels = set(
        row["eligibility"]["skills_required"]
        + row["eligibility"]["skills_preferred"]
        + row["eligibility"]["majors"]
        + row["metadata"].get("skill_mentions", [])
    )
    assert not labels & forbidden


def test_meaningful_r_survives_research_word_and_stays_separate_from_optional_sql():
    row = pipeline(
        "Research assistant: R programming is required. SQL is preferred. Review the project before applying."
    )
    assert set(row["eligibility"]["skills_required"]) == {"R"}
    assert set(row["eligibility"]["skills_preferred"]) == {"SQL"}
    assert "eligibility.skills_required" in row["metadata"]["inferred_fields"]
    assert _stated_required_skills(row) == []


def test_generated_title_and_summary_cannot_reenter_as_source_labels():
    raw = RawOpportunity(
        source="text_parser",
        source_url="",
        url="",
        title="Untitled Opportunity",
        description_raw="We study bird migration in field surveys.",
        extra_fields={},
    )
    merged = _merge_llm_into_base(
        raw,
        {
            "title": "Information science Python developer in machine learning and robotics",
            "description": "Java programming is required.",
            "skills_required": ["Java"],
        },
    )
    row = normalize(asdict(merged))
    enrich_opportunity(row)
    apply_updates(row, rule_based_tag(row))
    assert not row["eligibility"]["majors"]
    assert not row["eligibility"]["skills_required"]
    assert not row["eligibility"]["skills_preferred"]
    assert not row["metadata"].get("skill_mentions", [])
    assert not row["keywords"]


def listing():
    return {
        "id": "heldout",
        "title": "Student project",
        "source_type": "campus_program",
        "opportunity_type": "research",
        "eligibility": {
            "majors": [],
            "skills_required": [],
            "skills_preferred": [],
            "preferred_year": [],
            "international_friendly": "unknown",
        },
        "metadata": {"is_active": True},
    }


def profile():
    return {
        "year": "sophomore",
        "major": "History",
        "seeking_type": ["research"],
        "hard_skills": [{"name": "Python", "level": "experienced"}],
    }


def test_missing_inferred_labels_cannot_reduce_score_and_do_not_claim_requirements():
    base = listing()
    derived = deepcopy(base)
    derived["eligibility"].update(majors=["IS"], skills_required=["Java"])
    derived["metadata"]["inferred_fields"] = {
        "eligibility.majors": "rule:enricher",
        "eligibility.skills_required": "llm:llm_tagger",
    }
    normal = score_eligibility(profile(), base)
    actual = score_eligibility(profile(), derived)
    assert actual[0] >= normal[0]
    assert not any("Missing skills" in line or "Prefers IS" in line for line in actual[2])


def test_optional_match_cannot_mask_explicit_hard_requirement():
    base = listing()
    base["eligibility"]["skills_required"] = ["SQL"]
    optional = deepcopy(base)
    optional["eligibility"]["skills_preferred"] = ["Python"]
    optional["metadata"].update(
        skill_mentions=["Python"], inferred_fields={"metadata.skill_mentions": "rule:opportunity_terms"}
    )
    assert score_eligibility(profile(), optional) == score_eligibility(profile(), base)
    assert _stated_required_skills(optional) == ["SQL"]


@pytest.mark.parametrize("signal", ["Python", {"name": "Python"}, [None], [""], ["Python"] * 513])
def test_malformed_mention_shapes_never_change_score_or_reasons(signal):
    base = listing()
    malformed = deepcopy(base)
    malformed["metadata"].update(
        skill_mentions=signal, inferred_fields={"metadata.skill_mentions": "rule:opportunity_terms"}
    )
    assert score_eligibility(profile(), malformed) == score_eligibility(profile(), base)


def test_positive_mention_is_soft_and_not_public_raw_metadata_or_email_requirement():
    base = listing()
    enriched = deepcopy(base)
    enriched["metadata"].update(
        skill_mentions=["Python"], inferred_fields={"metadata.skill_mentions": "rule:opportunity_terms"}
    )
    result = score_eligibility(profile(), enriched)
    assert result[0] > score_eligibility(profile(), base)[0]
    assert any("Python" in line and "mentioned" in line for line in result[1])
    assert _stated_required_skills(enriched) == []
    public = project_public_opportunity_payload(deepcopy(enriched), enriched)
    assert "skill_mentions" not in public.get("metadata", {})
    assert enriched["metadata"]["skill_mentions"] == ["Python"]
