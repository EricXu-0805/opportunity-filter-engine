from copy import deepcopy
from datetime import date

import pytest

from backend.data_loader import _sanitize_opportunity
from src.normalizers.deactivate_stale_faculty import deactivate_retired_title_faculty, deactivate_trainee_faculty
from src.normalizers.reviewed_faculty_profiles import (
    REVIEWS,
    apply_reviewed_faculty_profiles,
    carry_forward_reviewed_appointment,
)

AS_OF = date(2026, 11, 26)
BEISE = "faculty-umd-phys-5e8e0edd"
HERSHATTER = "faculty-ucsc-hist-d64a8110"
VT_APPOINTMENTS = {
    "faculty-vt-che-be391032": ("Professor Emeritus", "retired_title"),
    "faculty-vt-che-762a80d6": ("Professor Emeritus", "retired_title"),
    "faculty-vt-che-8d99f667": ("Professor Emeritus", "retired_title"),
    "faculty-vt-che-23e0354e": ("Joseph H. Collie Professor Emeritus", "retired_title"),
    "faculty-vt-che-2b84e643": ("Postdoctoral researchers", "trainee_title"),
    "faculty-vt-che-b0225752": ("Postdoctoral researcher", "trainee_title"),
}
PREVIOUS_TITLES = {
    "faculty-gatech-itm-21b8dd50": "Steven A. Denning Professor in Technology & Management",
    **dict.fromkeys(VT_APPOINTMENTS, ""),
    "faculty-ucsc-envs-c7e85a3f": "Distinguished Professor",
    HERSHATTER: "Research Professor and Distinguished Professor of History Emer.",
    "faculty-ucsc-lit-f8043691": "Professor of Literature",
}
ARCHIVED = {
    "faculty-gatech-itm-21b8dd50": ("Professor Emeritus", "retired_title"),
    **VT_APPOINTMENTS,
    "faculty-ucsc-envs-c7e85a3f": ("Distinguished Professor Emeritus; Director of UCSC Forest Ecology Research Plot", "retired_title"),
    "faculty-ucsc-lit-f8043691": ("Professor Emeritx of Literature; Founding Director, Teaching and Learning Center", "retired_title"),
    HERSHATTER: ("Research Professor and Distinguished Professor of History Emerita", "retired_title"),
    BEISE: ("Professor Emerita", "retired_title"),
    "faculty-sbu-geo-d49b7576": ("Distinguished Professor Emeritus", "retired_title"),
    "faculty-sbu-geo-07129e92": ("In Memoriam — Distinguished Professor Emeritus", "listed_as_deceased"),
}


def _old(oid):
    review = REVIEWS[oid]
    return {
        "id": oid, "pi_name": review.name, "department": review.department, "school": review.school,
        "source_type": "faculty_research", "source": f"{review.school}_faculty",
        "url": review.previous_url, "source_url": review.previous_url,
        "application": {"application_url": review.previous_url},
        "metadata": {"faculty_title": PREVIOUS_TITLES.get(oid, "Professor"), "last_verified": "2026-07-25",
                     "last_seen_at": "2026-07-25", "is_active": True},
    }


def test_reviewed_urls_and_title_replay_once_without_freshening_other_evidence():
    rows = [_old(oid) for oid in REVIEWS]
    assert apply_reviewed_faculty_profiles(rows, today=AS_OF) == len(rows)
    assert sum(row["metadata"]["is_active"] is False for row in rows) == len(ARCHIVED)
    for row in rows:
        review = REVIEWS[row["id"]]
        md = row["metadata"]
        assert row["url"] == row["source_url"] == row["application"]["application_url"] == review.profile_url
        assert md["last_seen_at"] == md["last_verified"] == "2026-07-25"
        assert md["faculty_profile_review"]["source_url"] == review.roster_url
        if row["id"] in ARCHIVED:
            title, reason = ARCHIVED[row["id"]]
            assert md["faculty_title"] == title
            assert md["faculty_profile_review"]["previous_title"] == PREVIOUS_TITLES.get(row["id"], "Professor")
            assert md["is_active"] is False and md["deactivation_reason"] == reason
            assert md["deactivated_at"] == review.reviewed_on.isoformat()
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


@pytest.mark.parametrize(("seen", "verified"), [
    (None, None), ("unknown", None), ("2026-11-25T12:20:00", "2026-11-25T12:20:00"),
    ("2026-11-26", "2026-11-26"),
])
def test_directory_timestamps_cannot_restore_old_urls_or_appointments(seen, verified):
    rows = [_old(oid) for oid in REVIEWS]
    for row in rows:
        row["metadata"].update(last_seen_at=seen, last_verified=verified, verification_scope="directory")
    assert apply_reviewed_faculty_profiles(rows, today=AS_OF) == len(rows)
    assert all(row["url"] == REVIEWS[row["id"]].profile_url for row in rows)
    retired = next(row for row in rows if row["id"] == BEISE)
    assert retired["metadata"]["is_active"] is False
    assert retired["metadata"]["faculty_title"] == "Professor Emerita"


def test_emeritus_profile_updates_generated_invitation_but_keeps_independent_source_text():
    row = _old("faculty-gatech-itm-21b8dd50")
    row["organization"] = "Georgia Institute of Technology"
    old = (f"Research opportunity with {row['metadata']['faculty_title']} Han Zhang in the {row['department']} "
           "at Georgia Institute of Technology. Contact the professor directly to inquire about "
           "undergraduate research positions in their lab.")
    row.update(description_clean=old, description_raw="A separately sourced research statement.",
               eligibility={"eligibility_text_raw": old})
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 1
    assert row["description_raw"] == "A separately sourced research statement."
    assert row["description_clean"] == row["eligibility"]["eligibility_text_raw"]
    assert "Professor Emeritus" in row["description_clean"] and "Contact" not in row["description_clean"]
    assert row["metadata"]["is_active"] is False

    updated = _old("faculty-gatech-itm-21b8dd50")
    updated["metadata"]["faculty_title"] = "Visiting Professor"
    before = deepcopy(updated)
    assert apply_reviewed_faculty_profiles([updated], today=AS_OF) == 0 and updated == before


def test_a_changed_ucsc_appointment_is_outside_the_review():
    row = _old(HERSHATTER)
    row["metadata"]["faculty_title"] = "Research Professor of History"
    before = deepcopy(row)
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 0
    assert row == before


def test_unrelated_archive_is_preserved():
    row = _old(BEISE)
    row["metadata"].update(is_active=False, deactivation_reason="duplicate_of")
    before = deepcopy(row)
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 0 and row == before


def _successful_profile_read(row, attempted="2026-11-25T12:03:00+00:00", **changes):
    row["metadata"]["contact_instruction_capture"] = {
        "version": 1, "status": "empty", "reason": None, "attempted_at": attempted,
        "source_url": row["url"], "record_source_url": row["url"], "requested_source_url": row["url"],
        "identity_name": row["pi_name"], **changes,
    }


def test_observed_math_roster_keeps_individual_profile_and_accepts_new_personal_site():
    oid = "faculty-umd-math-0f940cb3"
    row = _old(oid)
    _successful_profile_read(row, attempted="2026-11-26T13:00:00+00:00")
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 1
    assert row["url"] == REVIEWS[oid].profile_url
    row["url"] = row["source_url"] = "https://example.edu/new-faculty-profile"
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 0
    assert row["url"] == "https://example.edu/new-faculty-profile"


def test_restored_link_requires_a_newer_success_for_the_same_person_and_page():
    oid = "faculty-tamu-inta-c32e8252"
    for changes in ({"status": "failed"}, {"identity_name": "Another Person"},
                    {"source_url": "https://bush.tamu.edu/"}, {"requested_source_url": "https://bush.tamu.edu/"},
                    {"attempted": "2026-11-25T11:59:00+00:00"}):
        row = _old(oid)
        _successful_profile_read(row, **changes)
        assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 1
        assert row["url"] == REVIEWS[oid].profile_url
    restored = _old(oid)
    _successful_profile_read(restored)
    assert apply_reviewed_faculty_profiles([restored], today=AS_OF) == 0
    assert restored["url"] == REVIEWS[oid].previous_url


@pytest.mark.parametrize("restored_url", [False, True])
def test_reappearing_umd_roster_keeps_verified_retirement(restored_url):
    row = _old(BEISE)
    if restored_url:
        _successful_profile_read(row)
    else:
        row["url"] = REVIEWS[BEISE].profile_url
    url = row["url"]
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 1
    assert row["url"] == url
    assert row["metadata"]["is_active"] is False
    assert row["metadata"]["deactivation_reason"] == "retired_title"


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


def test_refresh_of_old_umd_directory_without_a_live_personal_page(tmp_path, monkeypatch):
    import json

    from bs4 import BeautifulSoup

    from src.collectors import faculty_graph, ucb_common
    from src.collectors.schools.umd_faculty import SCHOOL

    review = REVIEWS[BEISE]
    dept = next(dept for dept in SCHOOL["departments"] if dept["short"] == "PHYS")
    soup = BeautifulSoup(
        f'<div class="itemContainer"><h4 class="catItemTitle"><a href="{review.previous_url}">'
        'Beise, Elizabeth</a></h4><div class="catItemExtraFields">Title Professor E-mail</div></div>',
        "html.parser",
    )

    def fetch(url, **kwargs):
        assert url == dept["directory_url"]
        return soup

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    path = tmp_path / "opportunities.json"
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", path)
    old = _old(BEISE)
    apply_reviewed_faculty_profiles([old], today=AS_OF)
    path.write_text(json.dumps([old]))
    for _ in range(2):
        [incoming] = faculty_graph.fetch_and_normalize({**SCHOOL, "departments": [dept]}, deep=True)
        assert incoming["id"] == BEISE and incoming["metadata"]["verification_scope"] == "directory"
        assert incoming["url"] == review.previous_url and incoming["metadata"]["faculty_title"] == "Professor"
        faculty_graph.merge_into_processed([incoming])
        merged = json.loads(path.read_text())
        apply_reviewed_faculty_profiles(merged, lambda school: school == "umd", today=AS_OF)
        deactivate_retired_title_faculty(merged, today=AS_OF)
        assert merged[0]["metadata"]["is_active"] is False
        assert merged[0]["metadata"]["faculty_title"] == "Professor Emerita"
        assert merged[0]["url"] == review.profile_url
        path.write_text(json.dumps(merged))


@pytest.mark.parametrize(("raw", "expected"), [("Neuroscience", ""), ("Sensory systems", "Sensory systems")])
def test_texas_profile_labels_department_and_preserves_other_readings(raw, expected):
    oid = "faculty-utexas-neuro-ed6d4734"
    row = _old(oid)
    row["metadata"].update(research_areas_raw=raw, research_areas_verified_at="2026-08-06")
    row["keywords"] = ["Neuroscience"]
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 1
    assert row["url"] == "https://research.utexas.edu/profiles/harold-zakon"
    assert row["metadata"]["research_areas_raw"] == expected
    assert ("research_areas_verified_at" in row["metadata"]) == bool(expected)
    public = _sanitize_opportunity(deepcopy(row))
    assert ("Research areas:" in public["description_clean"]) == bool(expected)
    assert row["metadata"]["last_seen_at"] == "2026-07-25"
    assert apply_reviewed_faculty_profiles([row], today=AS_OF) == 0


def test_vt_chemical_review_only_retires_the_same_unranked_appointment(monkeypatch):
    class ReviewDate(date):
        @classmethod
        def today(cls):
            return AS_OF

    monkeypatch.setattr("src.normalizers.reviewed_faculty_profiles.date", ReviewDate)
    for oid, (_, reason) in VT_APPOINTMENTS.items():
        old = _old(oid)
        served = _sanitize_opportunity(deepcopy(old))
        assert served["metadata"]["deactivation_reason"] == reason
        assert served["metadata"]["faculty_profile_review"]["source_url"] == old["url"]
        assert served["id"] == old["id"]
        assert served["metadata"]["last_seen_at"] == old["metadata"]["last_seen_at"]
        for field, new_value in (("pi_name", "Different Person"), ("url", "https://che.vt.edu/People/other.html")):
            changed = {**old, field: new_value}
            assert apply_reviewed_faculty_profiles([changed], today=AS_OF) == 0
        old["metadata"]["faculty_title"] = "Assistant Professor"
        assert apply_reviewed_faculty_profiles([old], today=AS_OF) == 0
        assert old["metadata"]["is_active"] is True


def test_vt_chemical_refresh_counts_reviewed_appointments_before_comparing_the_roster():
    rows = [_old(oid) for oid in VT_APPOINTMENTS]
    assert apply_reviewed_faculty_profiles(rows, today=AS_OF, classify_title=False) == 6
    assert deactivate_retired_title_faculty(rows, today=AS_OF)["by_school"] == {"vt": 4}
    assert deactivate_trainee_faculty(rows, today=AS_OF)["by_school"] == {"vt": 2}
    assert apply_reviewed_faculty_profiles(rows, today=AS_OF, classify_title=False) == 0


def test_an_unranked_refresh_preserves_a_review_until_the_source_reports_a_new_appointment():
    oid = "faculty-vt-che-2b84e643"
    archived = _old(oid)
    assert apply_reviewed_faculty_profiles([archived], today=AS_OF) == 1
    archived["metadata"]["deactivated_at"] = "2026-11-27"
    repeat = _old(oid)
    carry_forward_reviewed_appointment(archived, repeat)
    assert repeat["metadata"]["is_active"] is False
    assert repeat["metadata"]["deactivated_at"] == "2026-11-27"
    assert deactivate_trainee_faculty([repeat], today=date(2026, 12, 3))["deactivated"] == 0

    confirmed = _old(oid)
    confirmed["metadata"]["faculty_title"] = archived["metadata"]["faculty_title"]
    carry_forward_reviewed_appointment(archived, confirmed)
    assert confirmed["metadata"]["is_active"] is False
    assert confirmed["metadata"]["deactivated_at"] == "2026-11-27"

    promoted = _old(oid)
    promoted["metadata"].update(faculty_title="Assistant Professor", last_seen_at="2026-12-03")
    carry_forward_reviewed_appointment(repeat, promoted)
    assert promoted["metadata"]["is_active"] is True
    assert apply_reviewed_faculty_profiles([promoted], today=date(2026, 12, 3)) == 0
    later = _old(oid)
    carry_forward_reviewed_appointment(promoted, later)
    assert later["metadata"]["faculty_title"] == "Assistant Professor"
    assert later["metadata"]["is_active"] is True
    assert apply_reviewed_faculty_profiles([later], today=date(2026, 12, 10)) == 0

    for changed in ({"pi_name": "Another Person"}, {"url": "https://che.vt.edu/People/new"}):
        other = {**_old(oid), **changed}
        carry_forward_reviewed_appointment(archived, other)
        assert other["metadata"]["is_active"] is True
