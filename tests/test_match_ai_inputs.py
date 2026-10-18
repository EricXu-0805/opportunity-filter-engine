"""M22: the optional AI rerank and AI explanation read the student's accepted
interests, skills and courses in full, and refuse an over-limit input
explicitly instead of cutting it. Offline: every provider is a local mock."""
import json
import socket

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.lib.prompt_budget import PromptInputTooLarge
from backend.routes import matches
from src.matcher.ranker import MatchResult, _profile_query_text
from tests.test_match_consistency import snapshot_env  # noqa: F401

REAL_EXPLANATION = matches._llm_explanation
REAL_RERANK = matches._llm_score_candidates

INTERESTS = "robot learning for surgical tools\nand tactile sensing"
PROFILE = {
    "year": "junior",
    "major": "Computer Science",
    "research_interests_text": INTERESTS,
    "secondary_interests": ["Mathematics minor"],
    "hard_skills": [
        # Typed (no source), confirmed import, bare string: the student's own.
        {"name": "ROS", "level": "beginner"},
        {"name": "PyTorch", "level": "experienced", "source": "resume", "confirmed": True},
        "C++",
        # An unconfirmed résumé hit and a skill inferred from a GitHub repo.
        {"name": "Verilog", "level": "beginner", "source": "resume"},
        {"name": "Jupyter Notebook", "level": "beginner", "source": "github"},
    ],
    "courses": [
        {"name": "CS 225", "status": "completed", "source": "manual"},
        {"name": "CS 444", "status": "in_progress", "source": "manual"},
        {"name": "CS 446", "status": "planned", "source": "manual"},
    ],
    # A legacy coursework string: the student never gave its status.
    "coursework": ["ECE 470"],
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("No external service is permitted")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(main, "RATE_LIMIT_DISABLED", True)
    monkeypatch.setattr(main, "feature_enabled", lambda _name: True)
    monkeypatch.setattr(matches, "feature_enabled", lambda _name: True)
    matches._llm_rerank_cache.clear()
    yield
    matches._llm_rerank_cache.clear()


def _results(ids):
    return [MatchResult(opportunity_id=i, eligibility_score=50, readiness_score=50, upside_score=50,
                        final_score=50.0, bucket="good_match", reasons_fit=[], reasons_gap=[], next_steps=[])
            for i in ids]


def _lookup(ids):
    return {i: {"id": i, "title": f"Lab {i}", "keywords": ["robotics"]} for i in ids}


def _student(user: str) -> dict:
    line = next(line for line in user.splitlines() if "(JSON data" in line)
    return json.loads(line.split("): ", 1)[1])


def _rerank_user(monkeypatch, profile) -> str:
    calls = []

    def provider(messages, **_kwargs):
        calls.append(messages)
        return '{"0": {"s": 80, "r": "Their tactile sensing work matches your interest."}}'

    monkeypatch.setattr(matches, "_resolve", lambda *_a, **_k: object())
    monkeypatch.setattr(matches, "chat_completion", provider)
    outcome = matches.llm_rerank(profile, _results(["a"]), _lookup(["a"]))
    assert outcome.applied and len(calls) == 1
    return calls[0][1]["content"]


def _explain_user(monkeypatch, profile) -> str:
    calls = []

    def provider(messages, **_kwargs):
        calls.append(messages)
        return "A controlled fit summary."

    monkeypatch.setattr(matches, "chat_completion", provider)
    assert matches._llm_explanation(profile, {"title": "Lab a"}, ["fit"], ["gap"]) == "A controlled fit summary."
    return calls[0][1]["content"]


def _courses_by_status(student: dict) -> dict[str, list[str]]:
    """``{"completed": [...], "in progress": [...], ...}`` from the labelled groups."""
    out: dict[str, list[str]] = {}
    for label, names in student["courses"].items():
        status = next(s for s in ("completed", "in progress", "planned", "status not given") if label.startswith(s))
        out[status] = names
    return out


@pytest.mark.parametrize("build", [_rerank_user, _explain_user], ids=["rerank", "explain"])
def test_prompt_carries_accepted_skills_and_courses_with_status(monkeypatch, build):
    user = build(monkeypatch, PROFILE)
    student = _student(user)
    assert student["research_interests_text"] == INTERESTS
    # Student text stays JSON data: its newline cannot start a prompt line.
    assert "\nand tactile sensing" not in user
    assert student["major"] == "Computer Science"
    assert student["secondary_interests"] == ["Mathematics minor"]
    # Each skill at the level the writers may claim it at.
    assert student["skills"] == [{"name": "ROS", "level": "beginner"},
                                 {"name": "PyTorch", "level": "experienced"},
                                 {"name": "C++", "level": "beginner"}]
    assert "Verilog" not in user
    assert "Jupyter Notebook" not in user
    assert _courses_by_status(student) == {"completed": ["CS 225"], "in progress": ["CS 444"],
                                           "planned": ["CS 446"], "status not given": ["ECE 470"]}
    # Each group says how its courses may be stated: planned is never taken.
    planned = next(label for label in student["courses"] if label.startswith("planned"))
    assert "never as taken" in planned


LEGACY_SKILLS = [
    # No source and a level above beginner: the old importers stamped exactly
    # this, and the form asks the student to confirm it (skillNeedsConfirming).
    {"name": "LabVIEW", "level": "experienced"},
    {"name": "Simulink", "level": "intermediate"},
    # No source at beginner, or with no level, claims nothing: settled.
    {"name": "ROS", "level": "beginner"},
    {"name": "Git"},
    # Settled above beginner: the legacy "expert" only the badge writes, and
    # a level the student confirmed with or without a source.
    {"name": "OpenCV", "level": "expert"},
    {"name": "CUDA", "level": "intermediate", "confirmed": True},
    {"name": "PyTorch", "level": "experienced", "source": "resume", "confirmed": True},
]


@pytest.mark.parametrize("build", [_rerank_user, _explain_user], ids=["rerank", "explain"])
def test_legacy_skill_the_form_asks_to_confirm_is_left_out(monkeypatch, build):
    user = build(monkeypatch, {**PROFILE, "hard_skills": LEGACY_SKILLS})
    assert _student(user)["skills"] == [{"name": "ROS", "level": "beginner"},
                                        {"name": "Git", "level": "beginner"},
                                        {"name": "OpenCV", "level": "expert"},
                                        {"name": "CUDA", "level": "intermediate"},
                                        {"name": "PyTorch", "level": "experienced"}]
    assert "LabVIEW" not in user
    assert "Simulink" not in user


def test_semantic_rerank_query_is_unchanged():
    # The embedding rerank keeps reading every skill name; only the model
    # prompts read the accepted set.
    assert _profile_query_text(PROFILE) == (
        f"{INTERESTS} major: Computer Science ROS PyTorch C++ Verilog Jupyter Notebook Mathematics minor"
    )


def _course_profile(count: int) -> dict:
    return {**PROFILE, "coursework": [],
            "courses": [{"name": f"Course {i:03d} " + "x" * 985, "status": "planned", "source": "manual"}
                        for i in range(count)]}


@pytest.mark.parametrize("build", [_rerank_user, _explain_user], ids=["rerank", "explain"])
def test_long_course_list_reaches_the_model_whole(monkeypatch, build):
    profile = _course_profile(100)
    student = _student(build(monkeypatch, profile))
    assert _courses_by_status(student)["planned"] == [course["name"] for course in profile["courses"]]


def test_over_limit_rerank_is_refused_not_cut(monkeypatch):
    monkeypatch.setattr(matches, "_resolve", lambda *_a, **_k: object())
    monkeypatch.setattr(matches, "chat_completion", lambda *_a, **_k: pytest.fail("over-limit input reached the model"))
    with pytest.raises(PromptInputTooLarge) as error:
        matches.llm_rerank(_course_profile(125), _results(["a"]), _lookup(["a"]))
    assert error.value.detail["code"] == "MATCH_RERANK_INPUT_TOO_LARGE"


def test_over_limit_explanation_is_refused_not_cut(monkeypatch):
    monkeypatch.setattr(matches, "chat_completion", lambda *_a, **_k: pytest.fail("over-limit input reached the model"))
    with pytest.raises(PromptInputTooLarge) as error:
        matches._llm_explanation(_course_profile(125), {"title": "Lab a"}, ["fit"], ["gap"])
    assert error.value.detail["code"] == "MATCH_EXPLANATION_INPUT_TOO_LARGE"


def test_over_limit_routes_refuse_explicitly(monkeypatch, snapshot_env):  # noqa: F811
    client = TestClient(main.app)
    profile = _course_profile(125)
    monkeypatch.setattr(matches, "chat_completion", lambda *_a, **_k: pytest.fail("over-limit input reached the model"))
    monkeypatch.setattr(matches, "_llm_explanation", REAL_EXPLANATION)
    response = client.post("/api/matches/opp-00/explain?llm=true", json=profile)
    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "MATCH_EXPLANATION_INPUT_TOO_LARGE"
    # The explain request ranked with the fixture's scorer; drop what it cached.
    monkeypatch.setattr(matches, "_llm_score_candidates", REAL_RERANK)
    matches._match_snapshots.clear()
    matches._llm_rerank_cache.clear()
    assert client.post("/api/matches?llm=false", json=profile).status_code == 200
    response = client.post("/api/matches?llm=true", json=profile)
    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "MATCH_RERANK_INPUT_TOO_LARGE"
