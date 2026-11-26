"""Michigan State publishes a per-person ID separately from the roster citation."""
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
