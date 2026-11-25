from copy import deepcopy
from datetime import date

import pytest

from backend.data_loader import _sanitize_opportunity
from src.normalizers.deactivate_stale_faculty import deactivate_retired_title_faculty
from src.normalizers.reviewed_faculty_profiles import REVIEWS, apply_reviewed_faculty_profiles

AS_OF = date(2026, 11, 25)
BEISE = "faculty-umd-phys-5e8e0edd"


def _old(oid):
    review = REVIEWS[oid]
    return {
        "id": oid, "pi_name": review.name, "department": review.department, "school": review.school,
        "source_type": "faculty_research", "source": f"{review.school}_faculty",
        "url": review.previous_url, "source_url": review.previous_url,
        "application": {"application_url": review.previous_url},
        "metadata": {"faculty_title": "Professor", "last_verified": "2026-07-25",
                     "last_seen_at": "2026-07-25", "is_active": True},
    }


def test_reviewed_urls_and_title_replay_once_without_freshening_other_evidence():
    rows = [_old(oid) for oid in REVIEWS]
    assert apply_reviewed_faculty_profiles(rows, today=AS_OF) == len(rows)
    assert sum(row["metadata"]["is_active"] is False for row in rows) == 1
    for row in rows:
        review = REVIEWS[row["id"]]
        md = row["metadata"]
        assert row["url"] == row["source_url"] == row["application"]["application_url"] == review.profile_url
        assert md["last_seen_at"] == md["last_verified"] == "2026-07-25"
        assert md["faculty_profile_review"]["source_url"] == review.roster_url
        if row["id"] == BEISE:
            assert md["faculty_title"] == "Professor Emerita"
            assert md["faculty_profile_review"]["previous_title"] == "Professor"
            assert md["is_active"] is False and md["deactivation_reason"] == "retired_title"
            assert md["deactivated_at"] == AS_OF.isoformat()
        else:
            assert md["is_active"] is True
    before = deepcopy(rows)
    assert apply_reviewed_faculty_profiles(rows, today=AS_OF) == 0
    assert deactivate_retired_title_faculty(rows, today=AS_OF)["deactivated"] == 0
    assert rows == before


@pytest.mark.parametrize(("key", "value"), [
    ("id", "another-row"), ("pi_name", "A different person"), ("school", "another-school"),
    ("source", "manual"), ("source_type", "internship"), ("department", "Department of Astronomy"),
    ("url", "https://umd.edu/a-new-appointment"),
])
def test_review_matches_the_same_person_and_original_unit_only(key, value):
    row = _old(BEISE)
    row[key] = value
    before = deepcopy(row)
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 0
    assert row == before


@pytest.mark.parametrize(("key", "value"), [
    ("last_seen_at", None), ("last_seen_at", "unknown"), ("last_seen_at", "2026-11-25T23:00:00"),
    ("last_verified", "2026-11-26"), ("is_active", False),
])
def test_missing_dates_newer_evidence_and_retained_archives_are_preserved(key, value):
    row = _old(BEISE)
    row["metadata"][key] = value
    before = deepcopy(row)
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 0
    assert row == before


def test_selection_review_date_and_independent_destinations_are_respected():
    row = _old(BEISE)
    row["application"]["application_url"] = "https://umd.edu/another-destination"
    row["source_url"] = "https://umd.edu/another-source"
    assert apply_reviewed_faculty_profiles([row], lambda school: school == "sbu", today=AS_OF) == 0
    assert apply_reviewed_faculty_profiles([row], today=date(2026, 11, 24)) == 0
    assert apply_reviewed_faculty_profiles([row], lambda school: school == "umd", today=AS_OF) == 1
    assert row["application"]["application_url"] == "https://umd.edu/another-destination"
    assert row["source_url"] == "https://umd.edu/another-source"


def test_serving_legacy_shards_applies_the_same_retirement_and_profile_evidence(monkeypatch):
    class ReviewDate(date):
        @classmethod
        def today(cls):
            return AS_OF
    monkeypatch.setattr("src.normalizers.reviewed_faculty_profiles.date", ReviewDate)
    retired = _sanitize_opportunity(_old(BEISE))
    assert retired["metadata"]["deactivation_reason"] == "retired_title"
    assert retired["metadata"]["is_active"] is False
    active = _sanitize_opportunity(_old("faculty-sbu-cs-890dcd54"))
    assert active["url"] == "https://alps-lab.github.io/"
    assert active["metadata"]["is_active"] is True
    assert active["metadata"]["last_seen_at"] == "2026-07-25"
