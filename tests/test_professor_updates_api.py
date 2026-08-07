"""Serving boundary for professor updates (backend/routes/professors.py).

Per-record eligibility contract: a missing/empty artifact is an honest
``available: false`` empty 200 (never an error), each event serves iff its own
evidence validates, and responses never contain contact details.
"""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import opportunities as opportunities_route
from backend.routes import professors
from src.tracking.professor_profiles import (
    canonical_professor_id,
    compute_release_status,
    update_tracking_state,
)

client = TestClient(app)

T0 = "2026-07-01T00:00:00"
T1 = "2026-07-08T00:00:00"


def record(*, record_id="faculty-uiuc-ece-abcd1234", pi_name="Jane Doe",
           last_verified=T0, keywords=("machine learning",)):
    return {
        "id": record_id,
        "source": "uiuc_faculty",
        "source_type": "faculty_research",
        "source_url": "https://ece.illinois.edu/people/jdoe",
        "title": f"Research with Prof. {pi_name} — ECE",
        "organization": "University of Illinois Urbana-Champaign",
        "school": "uiuc",
        "department": "ECE",
        "lab_or_program": "Doe Lab",
        "pi_name": pi_name,
        "contact_email": "jdoe@illinois.edu",
        "keywords": list(keywords),
        "metadata": {
            "last_verified": last_verified,
            "verification_scope": "profile",
            "is_active": True,
        },
    }


def stamp_release(state):
    expected_professors = {
        professor_id: profile["school"]
        for professor_id, profile in state["profiles"].items()
    }
    state["release"] = compute_release_status(
        state["profiles"],
        state["events"],
        refresh_ok=True,
        now=datetime(2026, 7, 20, tzinfo=UTC),
        expected_schools={"uiuc"},
        expected_professors=expected_professors,
    )
    assert state["release"]["release_ready"] is True
    return state


def state_with_event():
    state = update_tracking_state([record()])
    state = update_tracking_state(
        [record(last_verified=T1, keywords=("quantum sensing",))], state
    )
    return stamp_release(state)


@pytest.fixture
def tracking_file(tmp_path, monkeypatch):
    path = tmp_path / "professor_tracking.json"
    monkeypatch.setattr(professors, "TRACKING_PATH", path)
    professors.reset_tracking_cache()
    yield path
    professors.reset_tracking_cache()


def post_updates(ids, **extra):
    return client.post("/api/professors/updates", json={"ids": ids, **extra})


class TestArtifactAvailability:
    def test_absent_file_is_empty_success_not_error(self, tracking_file):
        res = post_updates(["prof:v1:uiuc:" + "a" * 20])
        assert res.status_code == 200
        assert res.json() == {
            "available": False,
            "release_ready": False,
            "events": [],
            "requested": 1,
            "has_more": False,
        }

    def test_corrupt_file_is_unavailable_not_500(self, tracking_file):
        tracking_file.write_text("{broken", encoding="utf-8")
        res = post_updates(["prof:v1:uiuc:" + "a" * 20])
        assert res.status_code == 200
        assert res.json()["available"] is False

    def test_empty_state_without_passing_release_is_unavailable(self, tracking_file):
        tracking_file.write_text(
            json.dumps({"schema_version": 2, "profiles": {}, "events": []}),
            encoding="utf-8",
        )
        res = post_updates(["prof:v1:uiuc:" + "a" * 20])
        assert res.json() == {
            "available": False,
            "release_ready": False,
            "events": [],
            "requested": 1,
            "has_more": False,
        }

    def test_schema_v1_artifact_is_not_served_and_never_release_ready(self, tracking_file):
        """v2-only serving: a leftover v1 artifact is an honest empty response
        (the producer migrates it on its next write) and can never present as
        release-ready."""
        state = state_with_event()
        state["schema_version"] = 1
        tracking_file.write_text(json.dumps(state), encoding="utf-8")
        res = post_updates([state["events"][0]["professor_id"]])
        assert res.status_code == 200
        body = res.json()
        assert body["available"] is False
        assert body["release_ready"] is False
        assert body["events"] == []

    def test_v2_artifact_with_passing_release_block_serves_release_ready(self, tracking_file):
        state = state_with_event()
        state["release"] = compute_release_status(
            state["profiles"], state["events"], refresh_ok=True,
            now=datetime(2026, 7, 20, tzinfo=UTC),
            expected_professors={
                professor_id: profile["school"]
                for professor_id, profile in state["profiles"].items()
            },
        )
        assert state["release"]["release_ready"] is True
        tracking_file.write_text(json.dumps(state), encoding="utf-8")
        res = post_updates([state["events"][0]["professor_id"]])
        body = res.json()
        assert body["available"] is True
        assert body["release_ready"] is True
        assert len(body["events"]) == 1

    def test_once_green_artifact_expires_when_refresh_stops(self, tracking_file):
        state = state_with_event()
        state["release"]["computed_at"] = "2026-01-01T00:00:00+00:00"
        tracking_file.write_text(json.dumps(state), encoding="utf-8")

        body = post_updates([state["events"][0]["professor_id"]]).json()

        assert body["available"] is False
        assert body["release_ready"] is False
        assert body["events"] == []

    def test_cached_artifact_stops_at_exact_profile_freshness_expiry(
        self,
        tracking_file,
        monkeypatch,
    ):
        observed_at = datetime.now(UTC)
        fresh_record = record(last_verified=observed_at.isoformat())
        state = update_tracking_state([fresh_record])
        professor_id = canonical_professor_id(fresh_record)
        state["release"] = compute_release_status(
            state["profiles"],
            state["events"],
            refresh_ok=True,
            now=observed_at,
            expected_schools={"uiuc"},
            expected_professors={professor_id: "uiuc"},
        )
        tracking_file.write_text(json.dumps(state), encoding="utf-8")

        assert post_updates([professor_id]).json()["available"] is True
        expiry = datetime.fromisoformat(
            state["release"]["freshness_valid_until"]
        )

        class AfterExpiry(datetime):
            @classmethod
            def now(cls, tz=None):
                value = expiry.replace(tzinfo=UTC) + professors.timedelta(seconds=1)
                return value if tz is None else value.astimezone(tz)

        monkeypatch.setattr(professors, "datetime", AfterExpiry)
        body = post_updates([professor_id]).json()
        assert body["available"] is False
        assert body["release_ready"] is False


class TestEventServing:
    def test_serves_only_requested_professors_newest_first(self, tracking_file):
        state = state_with_event()
        other = record(record_id="faculty-uiuc-cs-ffff0000", pi_name="John Roe")
        state = update_tracking_state([other], state)
        state = update_tracking_state(
            [record(record_id="faculty-uiuc-cs-ffff0000", pi_name="John Roe",
                    last_verified=T1, keywords=("hci",))],
            state,
        )
        stamp_release(state)
        tracking_file.write_text(json.dumps(state), encoding="utf-8")

        target = canonical_professor_id(record())
        res = post_updates([target])
        body = res.json()
        assert body["available"] is True
        assert len(body["events"]) == 1
        event = body["events"][0]
        assert event["professor_id"] == target
        assert event["professor_name"] == "Jane Doe"
        assert event["change_types"] == ["research_focus"]
        # Serving projection: evidence stays server-side.
        assert "evidence" not in event

    def test_no_contact_details_in_response(self, tracking_file):
        state = state_with_event()
        tracking_file.write_text(json.dumps(state), encoding="utf-8")
        res = post_updates([state["events"][0]["professor_id"]])
        text = res.text
        assert "jdoe@illinois.edu" not in text
        assert "contact_email" not in text

    def test_tampered_event_is_skipped_not_served(self, tracking_file):
        state = state_with_event()
        state["events"][0]["evidence"]["after"]["research_focus"] = ["forged"]
        tracking_file.write_text(json.dumps(state), encoding="utf-8")
        res = post_updates([state["events"][0]["professor_id"]])
        assert res.json() == {
            "available": False,
            "release_ready": False,
            "events": [],
            "requested": 1,
            "has_more": False,
        }

    def test_malformed_ids_are_ignored(self, tracking_file):
        state = state_with_event()
        tracking_file.write_text(json.dumps(state), encoding="utf-8")
        res = post_updates(["faculty-uiuc-x", "PROF:V1:UIUC:" + "a" * 20, ""])
        assert res.json()["events"] == []
        assert res.json()["requested"] == 3

    def test_limit_and_has_more(self, tracking_file):
        state = update_tracking_state([record()])
        for i in range(3):
            state = update_tracking_state(
                [record(last_verified=f"2026-07-{i + 2:02d}T00:00:00", keywords=(f"kw-{i}",))],
                state,
            )
        stamp_release(state)
        tracking_file.write_text(json.dumps(state), encoding="utf-8")
        professor_id = state["events"][0]["professor_id"]

        res = post_updates([professor_id], limit=2)
        body = res.json()
        assert len(body["events"]) == 2
        assert body["has_more"] is True
        assert body["events"][0]["verified_at"] > body["events"][1]["verified_at"]

        res = post_updates([professor_id], limit=200)
        assert res.json()["has_more"] is False

    def test_request_caps_are_enforced(self, tracking_file):
        assert post_updates(["prof:v1:uiuc:" + "a" * 20] * 201).status_code == 422
        assert post_updates(["prof:v1:uiuc:" + "a" * 20], limit=0).status_code == 422
        assert post_updates(["prof:v1:uiuc:" + "a" * 20], limit=201).status_code == 422

    def test_cache_reloads_when_file_changes(self, tracking_file):
        state = state_with_event()
        professor_id = state["events"][0]["professor_id"]
        res = post_updates([professor_id])
        assert res.json()["available"] is False

        tracking_file.write_text(json.dumps(state), encoding="utf-8")
        res = post_updates([professor_id])
        assert res.json()["available"] is True
        assert len(res.json()["events"]) == 1


class TestOpportunityProfessorId:
    def test_detail_payload_carries_derivable_professor_id(self, monkeypatch):
        faculty = record()
        monkeypatch.setattr(
            opportunities_route,
            "load_opportunities_by_id",
            lambda: {faculty["id"]: faculty},
        )
        res = client.get(f"/api/opportunities/{faculty['id']}")
        assert res.status_code == 200
        body = res.json()
        assert body["professor_id"].startswith("prof:v1:uiuc:")
        # Redaction still applies alongside the additive field.
        assert "contact_email" not in body

    def test_non_faculty_detail_has_no_professor_id(self, monkeypatch):
        listing = {"id": "reu-123", "source_type": "research_listing", "title": "REU"}
        monkeypatch.setattr(
            opportunities_route,
            "load_opportunities_by_id",
            lambda: {"reu-123": listing},
        )
        body = client.get("/api/opportunities/reu-123").json()
        assert "professor_id" not in body
