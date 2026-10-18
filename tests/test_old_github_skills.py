"""A GitHub skill imported before M12 is not named in the student's voice (checklist M108).

Before M12 (cc0c684a) the GitHub import stored ``{name, level: "beginner",
source: "github"}`` with no evidence, and its topic map turned the topics
machine-learning and deep-learning into PyTorch and data-science into pandas:
a library no repository names. Since M12 every GitHub skill carries the repo
field that named it. One that carries none, and that the student has not
confirmed, may still be ranked on but is never named in the template email,
the AI brief, Tailor's student context or the résumé suggestions.
"""

from backend.routes import cold_email as ce_route
from backend.routes import tailor
from backend.schemas import ProfileRequest
from src.recommender.cold_email import _common_parts, generate_cold_email, generate_variants
from src.recommender.resume_advisor import analyze_gaps
from src.student_evidence import claimable_skill_levels, skill_may_be_named

OLD = {"name": "PyTorch", "level": "beginner", "source": "github"}
CONFIRMED_OLD = {**OLD, "confirmed": True}
# As the profile stores it, and as the browser sends it.
M12_STORED = {**OLD, "evidence": "repo engine: topic pytorch"}
M12_SENT = {**OLD, "evidenced": True}
TYPED = {"name": "Python", "level": "beginner"}

OPP = {
    "id": "m108-opp", "source": "manual",
    "opportunity_type": "research", "pi_name": "Jane Doe",
    "lab_or_program": "Prof. Jane Doe's Research Group",
    "department": "Computer Science", "keywords": ["computer vision"],
    "description_raw": "Computer vision research on image segmentation.",
    "eligibility": {"skills_required": ["Python", "PyTorch"]},
}


def profile(*skills: dict) -> dict:
    return {
        "name": "Eric", "year": "sophomore", "major": "Computer Science",
        "school": "UIUC", "hard_skills": list(skills),
        "research_interests_text": "computer vision",
    }


def writings(*skills: dict) -> dict[str, str]:
    """Every student-voice writing that reads the skill list, by name."""
    p = profile(*skills)
    tips = analyze_gaps(p, OPP)["resume_tips"]
    return {
        "template": generate_cold_email(p, OPP),
        "variants": "\n".join(v["text"] for v in generate_variants(p, OPP)),
        "ai brief": ce_route._render_student_brief(_common_parts(p, OPP)),
        "tailor": tailor._student_context(p),
        "resume tips": "\n".join(tip for tip in tips if tip.startswith("Highlight your experience")),
    }


def test_an_old_github_skill_is_named_nowhere():
    for where, text in writings(TYPED, OLD).items():
        assert "PyTorch" not in text, where
        assert "Python" in text, where


def test_the_old_shape_is_the_only_one_held_back():
    assert not skill_may_be_named(OLD)
    for skill in (CONFIRMED_OLD, M12_STORED, M12_SENT, TYPED, "PyTorch",
                  {"name": "PyTorch", "source": "resume"}, {**OLD, "evidence": "  "} | {"confirmed": True}):
        assert skill_may_be_named(skill), skill
    assert not skill_may_be_named({**OLD, "evidence": "  "})
    assert claimable_skill_levels([TYPED, OLD]) == {"Python": "beginner"}


def test_a_confirmed_or_evidenced_github_skill_is_named_as_before():
    for skill in (CONFIRMED_OLD, M12_STORED, M12_SENT):
        for where, text in writings(TYPED, skill).items():
            assert "PyTorch" in text, (where, skill)
    # Still only at the level it may be spoken at.
    template = writings(M12_SENT)["template"]
    assert "foundational exposure to PyTorch" in template


def test_a_typed_skill_is_unchanged():
    texts = writings({"name": "PyTorch", "level": "expert"})
    assert "I have experience with PyTorch." in texts["template"]
    assert "- PyTorch (expert)" in texts["tailor"]


def test_the_request_keeps_whether_a_skill_has_evidence():
    """The browser sends the flag and pydantic must not drop it, or every
    M12 skill reads as the old shape on the server."""
    parsed = ProfileRequest(hard_skills=[M12_SENT, OLD, TYPED]).model_dump()["hard_skills"]
    assert [s["evidenced"] for s in parsed] == [True, False, False]
    assert "PyTorch" in generate_cold_email(profile(parsed[0]), OPP)
    assert "PyTorch" not in generate_cold_email(profile(parsed[1]), OPP)


def test_ranking_still_reads_an_old_github_skill():
    """Scoring is not a claim made to a person: the skill still counts as had."""
    gaps = analyze_gaps(profile(TYPED, OLD), OPP)
    assert "PyTorch" not in gaps["missing_skills"]
