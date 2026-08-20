"""Tests for the skill-gap roadmap aggregation (src/recommender/roadmap.py)
and its API accounting (backend/routes/roadmap.py)."""

from fastapi.testclient import TestClient

from backend.lib.blocking import BlockingWorkOverloaded
from backend.main import app
from backend.routes import roadmap as roadmap_route
from src.recommender.roadmap import prepare_roadmap

client = TestClient(app)


def _opp(required=None, preferred=None, *, is_active=True):
    return {
        "source_type": "campus_program",
        "eligibility": {"skills_required": required or [], "skills_preferred": preferred or []},
        "metadata": {"is_active": is_active},
    }


def test_aggregates_needed_by_and_priority():
    profile = {"hard_skills": [], "home_school": "uiuc"}
    opps = [
        _opp(required=["Python", "PyTorch"]),
        _opp(required=["Python"], preferred=["Docker"]),
    ]
    out = prepare_roadmap(profile, opps)
    assert out["total_labs"] == 2
    assert out["targets_with_skill_evidence"] == 2
    assert out["targets_without_skill_evidence"] == 0
    by_skill = {s["skill"]: s for s in out["skills"]}
    assert by_skill["Python"]["needed_by"] == 2
    assert by_skill["Python"]["priority"] == "high"
    assert by_skill["PyTorch"]["needed_by"] == 1
    # Docker is only ever preferred → medium priority
    assert by_skill["Docker"]["priority"] == "medium"
    # courses + time are carried from the taxonomy
    assert by_skill["Python"]["courses"]
    assert by_skill["Python"]["course_catalog"] == "uiuc"
    assert by_skill["Python"]["estimated_time"]


def test_orders_prerequisites_first():
    profile = {"hard_skills": [], "home_school": "uiuc"}
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
    assert out == {
        "skills": [],
        "total_labs": 0,
        "targets_with_skill_evidence": 0,
        "targets_without_skill_evidence": 0,
    }


def test_targets_without_listed_skills_remain_unassessed_not_matched():
    out = prepare_roadmap(
        {"hard_skills": []},
        [
            _opp(),
            {},
            {"eligibility": "invalid"},
            {"eligibility": {"skills_required": ["", "  "]}},
        ],
    )

    assert out == {
        "skills": [],
        "total_labs": 4,
        "targets_with_skill_evidence": 0,
        "targets_without_skill_evidence": 4,
    }


def test_skill_evidence_counts_are_distinct_from_profile_coverage():
    out = prepare_roadmap(
        {"hard_skills": ["Python"]},
        [
            _opp(required=["Python"]),
            _opp(),
        ],
    )

    # One target has evidence and is covered; the other remains unknown.  An
    # empty gaps list must not collapse those two states into a global match.
    assert out["skills"] == []
    assert out["targets_with_skill_evidence"] == 1
    assert out["targets_without_skill_evidence"] == 1


def test_malformed_skill_members_do_not_become_evidence_or_break_valid_skills():
    out = prepare_roadmap(
        {"hard_skills": []},
        [
            {
                "eligibility": {
                    "skills_required": [None, {"name": "invented"}, " Python "],
                    "skills_preferred": "SQL",
                }
            }
        ],
    )

    assert [skill["skill"] for skill in out["skills"]] == ["Python"]
    assert out["targets_with_skill_evidence"] == 1
    assert out["targets_without_skill_evidence"] == 0


def test_needed_by_counts_targets_not_duplicate_skill_labels():
    out = prepare_roadmap(
        {"hard_skills": []},
        [_opp(required=["Python", "python"], preferred=["Python"])],
    )

    assert len(out["skills"]) == 1
    assert out["skills"][0]["needed_by"] == 1
    assert out["skills"][0]["priority"] == "high"


def test_non_uiuc_profile_never_receives_uiuc_course_codes():
    out = prepare_roadmap(
        {"hard_skills": [], "home_school": "ucb"},
        [_opp(required=["Python", "machine learning"])],
    )

    assert out["skills"]
    assert all(skill["courses"] == [] for skill in out["skills"])
    assert all(skill["course_catalog"] is None for skill in out["skills"])


def test_missing_school_fails_closed_instead_of_assuming_uiuc():
    out = prepare_roadmap(
        {"hard_skills": []},
        [_opp(required=["Python"])],
    )

    assert out["skills"][0]["courses"] == []
    assert out["skills"][0]["course_catalog"] is None


def test_roadmap_api_marks_uiuc_course_catalog(monkeypatch):
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {"opp-1": _opp(required=["Python"])},
    )

    response = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "uiuc", "hard_skills": []},
            "opportunity_ids": ["opp-1"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_labs"] == 1
    assert body["requested_targets"] == 1
    assert body["resolved_targets"] == 1
    assert body["unresolved_targets"] == 0
    assert body["targets_with_skill_evidence"] == 1
    assert body["targets_without_skill_evidence"] == 0
    assert body["skills"][0]["course_catalog"] == "uiuc"
    assert body["skills"][0]["courses"]


def test_roadmap_api_reports_stale_target_ids_instead_of_claiming_all_set(monkeypatch):
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {"current": _opp(required=["Python"])},
    )

    response = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "uiuc", "hard_skills": []},
            "opportunity_ids": ["removed-a", "removed-b", "removed-a"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "skills": [],
        "total_labs": 0,
        "requested_targets": 2,
        "resolved_targets": 0,
        "unresolved_targets": 2,
        "inactive_targets": 0,
        "unverified_targets": 0,
        "targets_with_skill_evidence": 0,
        "targets_without_skill_evidence": 0,
    }


def test_roadmap_excludes_inactive_and_unverified_records_from_skill_evidence(monkeypatch):
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {
            "active": _opp(required=["Python"], is_active=True),
            "inactive": _opp(required=["Rust"], is_active=False),
            "unverified": _opp(required=["Kubernetes"], is_active=None),
        },
    )

    response = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "uiuc", "hard_skills": []},
            "opportunity_ids": ["active", "inactive", "unverified", "missing"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_targets"] == 4
    assert body["resolved_targets"] == 1
    assert body["inactive_targets"] == 1
    assert body["unverified_targets"] == 1
    assert body["unresolved_targets"] == 1
    assert [skill["skill"] for skill in body["skills"]] == ["Python"]


def test_roadmap_keeps_its_stricter_activity_policy_for_unknown_records(monkeypatch):
    """Target truth must not promote legacy records into plannable targets.

    General actionability treats an unstamped record as usable — it is the
    unstamped majority of the corpus. Planning is stricter and always has been:
    only an explicit `metadata.is_active is True` is resolved. Folding the two
    together would turn every record that merely fails to say it is inactive
    into a confirmed 30-day plan target.
    """
    absent_key = _opp(required=["Python"])
    absent_key["metadata"].pop("is_active")
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {
            "absent_key": absent_key,
            "explicit_none": _opp(required=["Kubernetes"], is_active=None),
            "explicit_true": _opp(required=["Rust"], is_active=True),
        },
    )

    body = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "uiuc", "hard_skills": []},
            "opportunity_ids": ["absent_key", "explicit_none", "explicit_true"],
        },
    ).json()

    assert body["resolved_targets"] == 1
    assert body["unverified_targets"] == 2
    assert body["inactive_targets"] == 0
    assert [skill["skill"] for skill in body["skills"]] == ["Rust"]


def test_roadmap_blocks_a_closed_listing_that_still_claims_to_be_active(monkeypatch):
    """The live shape of the 861 URAP rows: closed status, is_active True."""
    closed = _opp(required=["Fortran"], is_active=True)
    closed["source"] = "ucb_urap_projects"
    closed["source_type"] = "ucb_program"
    closed["metadata"]["urap_status"] = "closed"
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {
            "closed": closed,
            "open": _opp(required=["Python"], is_active=True),
        },
    )

    body = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "uiuc", "hard_skills": []},
            "opportunity_ids": ["closed", "open"],
        },
    ).json()

    assert body["resolved_targets"] == 1
    assert body["inactive_targets"] == 1
    assert body["unverified_targets"] == 0
    assert [skill["skill"] for skill in body["skills"]] == ["Python"]


def test_roadmap_api_reports_partial_resolution(monkeypatch):
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {"current": _opp(required=["Python"])},
    )

    response = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "ucb", "hard_skills": []},
            "opportunity_ids": ["current", "removed"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_labs"] == 1
    assert body["requested_targets"] == 2
    assert body["resolved_targets"] == 1
    assert body["unresolved_targets"] == 1
    assert body["targets_with_skill_evidence"] == 1
    assert body["targets_without_skill_evidence"] == 0


def test_roadmap_api_reports_resolved_targets_without_skill_evidence(monkeypatch):
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {
            "listed": _opp(required=["Python"]),
            "unknown": _opp(),
        },
    )

    response = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "uiuc", "hard_skills": ["Python"]},
            "opportunity_ids": ["listed", "unknown"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["skills"] == []
    assert body["resolved_targets"] == 2
    assert body["targets_with_skill_evidence"] == 1
    assert body["targets_without_skill_evidence"] == 1


def test_roadmap_api_suppresses_uiuc_courses_for_other_schools(monkeypatch):
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {"opp-1": _opp(required=["Python"])},
    )

    response = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "ucb", "hard_skills": []},
            "opportunity_ids": ["opp-1"],
        },
    )

    assert response.status_code == 200
    assert response.json()["skills"][0] == {
        "skill": "Python",
        "needed_by": 1,
        "priority": "high",
        "estimated_time": "2-4 weeks self-study",
        "courses": [],
        "course_catalog": None,
    }


def test_roadmap_bounded_worker_overload_is_retryable_503(monkeypatch):
    monkeypatch.setattr(
        roadmap_route,
        "load_opportunities_by_id",
        lambda: {"opp-1": _opp(required=["Python"])},
    )

    async def reject(*_args, **_kwargs):
        raise BlockingWorkOverloaded("queue full")

    monkeypatch.setattr(roadmap_route, "run_blocking", reject)
    response = client.post(
        "/api/roadmap",
        json={
            "profile": {"home_school": "uiuc", "hard_skills": []},
            "opportunity_ids": ["opp-1"],
        },
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
