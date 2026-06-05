"""Tests for the skill-gap roadmap aggregation (src/recommender/roadmap.py)."""

from src.recommender.roadmap import prepare_roadmap


def _opp(required=None, preferred=None):
    return {"eligibility": {"skills_required": required or [], "skills_preferred": preferred or []}}


def test_aggregates_needed_by_and_priority():
    profile = {"hard_skills": []}
    opps = [
        _opp(required=["Python", "PyTorch"]),
        _opp(required=["Python"], preferred=["Docker"]),
    ]
    out = prepare_roadmap(profile, opps)
    assert out["total_labs"] == 2
    by_skill = {s["skill"]: s for s in out["skills"]}
    assert by_skill["Python"]["needed_by"] == 2
    assert by_skill["Python"]["priority"] == "high"
    assert by_skill["PyTorch"]["needed_by"] == 1
    # Docker is only ever preferred → medium priority
    assert by_skill["Docker"]["priority"] == "medium"
    # courses + time are carried from the taxonomy
    assert by_skill["Python"]["courses"]
    assert by_skill["Python"]["estimated_time"]


def test_orders_prerequisites_first():
    profile = {"hard_skills": []}
    out = prepare_roadmap(profile, [_opp(required=["PyTorch", "Python"])])
    order = [s["skill"] for s in out["skills"]]
    assert order.index("Python") < order.index("PyTorch")  # PyTorch implies Python


def test_skips_skills_the_student_has():
    profile = {"hard_skills": ["Python"]}
    out = prepare_roadmap(profile, [_opp(required=["Python", "SQL"])])
    skills = [s["skill"] for s in out["skills"]]
    assert "Python" not in skills
    assert "SQL" in skills


def test_empty_target_set():
    out = prepare_roadmap({"hard_skills": []}, [])
    assert out == {"skills": [], "total_labs": 0}
