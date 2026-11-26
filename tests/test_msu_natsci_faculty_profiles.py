"""Michigan State publishes a per-person ID separately from the roster citation."""
import json
from pathlib import Path

import pytest

from src.collectors import faculty_graph
from src.collectors.schools import msu_faculty

BMB = next(dept for dept in msu_faculty.SCHOOL["departments"] if dept["short"] == "BMB")
ROSTER = "https://directory.natsci.msu.edu/Directory/Directory/Department/6"
PROFILE = "https://directory.natsci.msu.edu/directory/Profiles/Person/100493"


@pytest.mark.parametrize(("person_id", "destination"), [
    (100493, PROFILE),
    ("100493", PROFILE),
    (None, ROSTER),
    (0, ROSTER),
    ("unassigned", ROSTER),
    ("https://other.example.org/person/100493", ROSTER),
])
def test_directory_id_links_the_person_and_keeps_the_observed_roster(person_id, destination):
    entry = {
        "id": person_id,
        "name": "Claire Vieille",
        "organizationTitles": [
            {"organizationId": 6, "title": "Associate Professor"},
            {"organizationId": 26, "title": "Professor"},
        ],
    }
    [person] = faculty_graph._json_dir_records(BMB, BMB["json_dir"], [entry])
    person["_verification_scope"] = "directory"
    normalized = faculty_graph._normalize(msu_faculty.SCHOOL, BMB, person)
    assert normalized["url"] == destination
    assert normalized["source_url"] == ROSTER
    assert normalized["metadata"]["faculty_title"] == "Associate Professor"


@pytest.mark.parametrize(("title", "accepted"), [
    ("Red Cedar Distinguished Prof", True),
    ("Red Cedar Distinguished Asc Prof", True),
    ("Geological Sciences Endow Prof", True),
    ("Geological Sci Endow Assc Prof", True),
    ("Red Cedar Distinguished Prof Emeritum", False),
    ("Visiting Geological Sciences Endow Prof", False),
    ("Faculty", False),
    ("Assistant to the Prof", False),
])
def test_msu_named_professorship_is_a_substantive_appointment(title, accepted):
    record = {
        "id": 12345,
        "name": "Avery Sample",
        "organizationTitles": [{"organizationId": 6, "title": title}],
    }
    people = faculty_graph._json_dir_records(BMB, BMB["json_dir"], [record])
    assert bool(people) is accepted
    if accepted:
        assert people[0]["title"] == title


def test_stored_msu_faculty_destinations_never_use_a_bare_person_id():
    shard = Path(__file__).resolve().parents[1] / "data" / "processed" / "shards" / "msu.json"
    records = json.loads(shard.read_text(encoding="utf-8"))
    bare = [(row["id"], key) for row in records if row.get("source") == "msu_faculty"
            for key in ("url", "source_url") if str(row.get(key) or "").strip().isdigit()]
    assert not bare, bare


@pytest.mark.parametrize(("short", "title", "accepted"), [
    ("PHYS", "MSU Research FDN DIST. Prof", True),
    ("STAT", "MSU Research FDN DIST. Prof", True),
    ("BMB", "MSU Research FDN DIST. Prof", True),
    ("MGI", "MSU Research FDN DIST. Prof", True),
    ("IBIO", "MSU Research FDN DIST. Prof", True),
    ("BMB", "Assistant to the MSU Research FDN DIST. Prof", False),
    ("BMB", "MSU Research FDN DIST. Prof Emeritus", False),
    ("MATH", "Professor", True),
])
def test_research_foundation_appointments_use_the_official_unit_rank(short, title, accepted):
    dept = next(d for d in msu_faculty.SCHOOL["departments"] if d["short"] == short)
    org = dept["json_dir"]["title_from_list"]["match_value"]
    row = {"id": 12345, "name": "Avery Sample", "organizationTitles": [
        {"organizationId": org, "title": title},
    ]}
    people = faculty_graph._json_dir_records(dept, dept["json_dir"], [row])
    assert bool(people) is accepted
    if accepted:
        assert people[0]["title"] == title


def test_joint_math_appointment_preserves_the_published_cmse_identity():
    dept = next(d for d in msu_faculty.SCHOOL["departments"] if d["short"] == "MATH")
    row = {"id": 101537, "name": "Andrew Jason Christlieb", "organizationTitles": [
        {"organizationId": 3, "title": "MSU Research FDN DIST. Prof"},
    ]}
    assert not faculty_graph._json_dir_records(dept, dept["json_dir"], [row])
    primary = next(d for d in msu_faculty.SCHOOL["departments"] if d["short"] == "CMSE")
    faculty = faculty_graph.faculty("Andrew Christlieb", title="MSU Research Foundation Distinguished Professor")
    assert faculty_graph._normalize(msu_faculty.SCHOOL, primary, faculty)["id"] == "faculty-msu-cmse-5b280249"
