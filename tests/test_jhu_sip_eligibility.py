"""Current School of Medicine SIP admissions rules survive a campus refresh."""
from src.collectors.campus_graph import fetch_and_normalize
from src.collectors.schools.jhu import SCHOOL


def test_sip_preserves_its_original_id_and_citizenship_requirement():
    sip, = (row for row in fetch_and_normalize(SCHOOL)
            if row["metadata"].get("collector_key") == "som_summer_internship_program")
    assert sip["id"] == "jhu-d72ba740f62d"
    assert sip["eligibility"]["international_friendly"] == "no"
    assert sip["eligibility"]["citizenship_required"] is True
    assert "or permanent residents" in sip["description"]
