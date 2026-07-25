"""Professor tracking derivation (src/tracking/professor_profiles.py).

Covers the W8 contract: content-derived idempotent event ids, events only on
real tracked-field change between profile-verified snapshots, legacy records
(no verification_scope) as silent non-participants, contact-detail exclusion,
and the never-fail refresh wiring.
"""

import json

from src.collectors import refresh_all
from src.tracking.professor_profiles import (
    MAX_EVENTS_PER_PROFESSOR,
    PROFESSOR_ID_PATTERN,
    canonical_professor_id,
    load_tracking_state,
    update_tracking_file,
    update_tracking_state,
    validate_tracking_event_evidence,
)

T0 = "2026-07-01T00:00:00"
T1 = "2026-07-08T00:00:00"
T2 = "2026-07-15T00:00:00"


def record(
    *,
    last_verified=T0,
    scope="profile",
    keywords=("machine learning", "robotics"),
    email="jdoe@illinois.edu",
    department="Electrical and Computer Engineering",
    availability=None,
    record_id="faculty-uiuc-ece-abcd1234",
    pi_name="Jane Doe",
):
    metadata = {"last_verified": last_verified, "is_active": True}
    if scope is not None:
        metadata["verification_scope"] = scope
    if availability is not None:
        metadata["project_availability"] = availability
    return {
        "id": record_id,
        "source": "uiuc_faculty",
        "source_type": "faculty_research",
        "source_url": "https://ece.illinois.edu/people/jdoe",
        "title": f"Research with Prof. {pi_name} — ECE",
        "organization": "University of Illinois Urbana-Champaign",
        "school": "uiuc",
        "department": department,
        "lab_or_program": "Doe Lab",
        "pi_name": pi_name,
        "contact_email": email,
        "pi_email": email,
        "keywords": list(keywords),
        "metadata": metadata,
    }


class TestCanonicalProfessorId:
    def test_stable_and_well_formed(self):
        pid = canonical_professor_id(record())
        assert pid is not None
        assert PROFESSOR_ID_PATTERN.fullmatch(pid)
        assert pid == canonical_professor_id(record(keywords=("different",)))
        assert pid.startswith("prof:v1:uiuc:")

    def test_none_for_non_faculty_or_incomplete(self):
        assert canonical_professor_id({"source_type": "research_listing"}) is None
        assert canonical_professor_id(record(pi_name="")) is None
        no_school = record()
        no_school["school"] = None
        assert canonical_professor_id(no_school) is None
        assert canonical_professor_id("not-a-dict") is None

    def test_enrichment_fields_do_not_change_the_id(self):
        assert canonical_professor_id(record(email=None)) == canonical_professor_id(
            record(email="other@illinois.edu")
        )


class TestEventDerivation:
    def test_first_observation_is_baseline_not_event(self):
        state = update_tracking_state([record()])
        assert len(state["profiles"]) == 1
        assert state["events"] == []

    def test_research_focus_change_emits_verified_event(self):
        state = update_tracking_state([record()])
        state = update_tracking_state(
            [record(last_verified=T1, keywords=("machine learning", "quantum sensing"))],
            state,
        )
        assert len(state["events"]) == 1
        event = state["events"][0]
        assert event["change_types"] == ["research_focus"]
        assert event["verified_at"] == "2026-07-08T00:00:00+00:00"
        assert event["event_id"].startswith("prof-event:v1:")
        assert validate_tracking_event_evidence(event)

    def test_event_id_is_content_derived_and_replay_idempotent(self):
        changed = [record(last_verified=T1, keywords=("new area",))]
        state_a = update_tracking_state(changed, update_tracking_state([record()]))
        state_b = update_tracking_state(changed, update_tracking_state([record()]))
        assert state_a["events"][0]["event_id"] == state_b["events"][0]["event_id"]

        replayed = update_tracking_state(changed, state_a)
        assert len(replayed["events"]) == 1

    def test_department_and_availability_changes(self):
        state = update_tracking_state([record(availability="closed")])
        state = update_tracking_state(
            [record(last_verified=T1, department="Computer Science", availability="closed")],
            state,
        )
        assert state["events"][-1]["change_types"] == ["department_or_lab"]
        assert state["events"][-1]["project_became_available"] is False

        state = update_tracking_state(
            [record(last_verified=T2, department="Computer Science", availability="accepting")],
            state,
        )
        event = state["events"][-1]
        assert event["change_types"] == ["project_availability"]
        assert event["project_became_available"] is True

    def test_legacy_record_without_scope_is_silent(self):
        state = update_tracking_state([record(scope=None)])
        assert state["profiles"] == {}
        assert state["events"] == []
        # A later change on a still-unverified record is also not an event.
        state = update_tracking_state([record(scope=None, last_verified=T1, keywords=("x",))], state)
        assert state["events"] == []

    def test_directory_scope_is_not_a_profile_observation(self):
        state = update_tracking_state([record(scope="directory")])
        assert state["profiles"] == {}

    def test_scope_downgrade_keeps_verified_baseline(self):
        state = update_tracking_state([record()])
        baseline = json.dumps(state["profiles"], sort_keys=True)
        state = update_tracking_state(
            [record(scope="directory", last_verified=T1, keywords=("changed",))], state
        )
        assert json.dumps(state["profiles"], sort_keys=True) == baseline
        assert state["events"] == []

    def test_stale_changed_snapshot_cannot_rewrite_baseline(self):
        state = update_tracking_state([record(last_verified=T1)])
        state = update_tracking_state([record(last_verified=T0, keywords=("older",))], state)
        assert state["events"] == []
        (profile,) = state["profiles"].values()
        assert profile["last_verified"] == "2026-07-08T00:00:00+00:00"

    def test_missing_record_is_retained_not_removed(self):
        state = update_tracking_state([record()])
        state = update_tracking_state([], state)
        assert len(state["profiles"]) == 1

    def test_same_timestamp_rescrape_emits_nothing(self):
        state = update_tracking_state([record()])
        state = update_tracking_state([record(keywords=("changed",))], state)
        assert state["events"] == []

    def test_two_professors_never_merge(self):
        other = record(record_id="faculty-uiuc-cs-ffff0000", pi_name="John Roe")
        state = update_tracking_state([record(), other])
        assert len(state["profiles"]) == 2


class TestPrivacy:
    def test_state_never_contains_contact_details(self):
        state = update_tracking_state([record()])
        state = update_tracking_state([record(last_verified=T1, keywords=("new",))], state)
        serialized = json.dumps(state)
        assert "jdoe@illinois.edu" not in serialized
        assert "contact_email" not in serialized
        assert "pi_email" not in serialized

    def test_email_only_change_is_not_an_event(self):
        state = update_tracking_state([record()])
        state = update_tracking_state(
            [record(last_verified=T1, email="brand-new@illinois.edu")], state
        )
        assert state["events"] == []


class TestPreviousStateSalvage:
    def _state_with_event(self):
        state = update_tracking_state([record()])
        return update_tracking_state([record(last_verified=T1, keywords=("new",))], state)

    def test_wrong_schema_version_starts_fresh(self):
        state = self._state_with_event()
        state["schema_version"] = 99
        assert update_tracking_state([], state) == {
            "schema_version": 1,
            "profiles": {},
            "events": [],
        }

    def test_single_corrupt_event_is_dropped_not_fatal(self):
        state = self._state_with_event()
        tampered = json.loads(json.dumps(state["events"][0]))
        tampered["evidence"]["after"]["research_focus"] = ["forged claim"]
        state["events"].append(tampered)
        salvaged = update_tracking_state([], state)
        assert len(salvaged["events"]) == 1
        assert len(salvaged["profiles"]) == 1

    def test_non_dict_previous_state_starts_fresh(self):
        assert update_tracking_state([], "garbage")["profiles"] == {}


class TestEventCap:
    def test_events_bounded_per_professor(self):
        state = update_tracking_state([record()])
        for i in range(MAX_EVENTS_PER_PROFESSOR + 5):
            state = update_tracking_state(
                [record(last_verified=f"2026-07-{i + 2:02d}T00:00:00", keywords=(f"kw-{i}",))],
                state,
            )
        assert len(state["events"]) == MAX_EVENTS_PER_PROFESSOR
        # Newest survive the cap.
        assert state["events"][-1]["verified_at"].startswith("2026-07-26")


class TestTrackingFile:
    def test_update_writes_compact_valid_artifact(self, tmp_path):
        path = tmp_path / "professor_tracking.json"
        stats = update_tracking_file([record()], path)
        assert stats == {"profiles": 1, "events": 0, "new_events": 0}

        stats = update_tracking_file(
            [record(last_verified=T1, keywords=("new",))], path
        )
        assert stats == {"profiles": 1, "events": 1, "new_events": 1}

        state = load_tracking_state(path)
        assert state["schema_version"] == 1
        assert validate_tracking_event_evidence(state["events"][0])
        # Compact form: machine-read artifact, no pretty-print inflation.
        assert "\n  " not in path.read_text(encoding="utf-8")

    def test_replay_reports_zero_new_events(self, tmp_path):
        path = tmp_path / "professor_tracking.json"
        update_tracking_file([record()], path)
        changed = [record(last_verified=T1, keywords=("new",))]
        update_tracking_file(changed, path)
        stats = update_tracking_file(changed, path)
        assert stats["new_events"] == 0

    def test_corrupt_file_is_recovered_from(self, tmp_path):
        path = tmp_path / "professor_tracking.json"
        path.write_text("{not json", encoding="utf-8")
        stats = update_tracking_file([record()], path)
        assert stats["profiles"] == 1


class TestRefreshWiring:
    def test_tracking_failure_never_raises(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError("tracking exploded")

        monkeypatch.setattr(
            "src.tracking.professor_profiles.update_tracking_file", boom
        )
        summary = {"sources": {}}
        refresh_all._update_professor_tracking([record()], summary)
        assert summary["sources"]["professor_tracking"]["status"] == "error"

    def test_success_path_writes_summary_and_file(self, monkeypatch, tmp_path):
        path = tmp_path / "professor_tracking.json"
        monkeypatch.setattr(refresh_all, "TRACKING_FILE", path)
        summary = {"sources": {}}
        refresh_all._update_professor_tracking([record()], summary)
        assert summary["sources"]["professor_tracking"] == {
            "profiles": 1,
            "events": 0,
            "new_events": 0,
            "status": "ok",
        }
        assert path.exists()
