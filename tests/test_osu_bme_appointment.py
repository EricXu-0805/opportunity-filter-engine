"""A saved OSU appointment can reopen for the same person's return to the BME ladder."""
import json

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import osu_faculty


def test_returning_osu_bme_member_and_independent_namesake(tmp_path, monkeypatch):
    dept = next(d for d in osu_faculty.SCHOOL["departments"] if d["short"] == "BME")
    owner = dept["reserved_profile_identity"]
    profile = "https://" + owner["profile"]
    original_id = "faculty-osu-bme-5874478d"
    name = owner["name"]
    moved = profile + "-new"
    other = profile + "-namesake"

    def appointment(url, email):
        person = faculty_graph.faculty(name, title="Professor, Biomedical Engineering", url=url, email=email)
        return faculty_graph._normalize(osu_faculty.SCHOOL, dept, person)

    # A name or department-wide link cannot identify the returning member.
    assert appointment(None, None) is None
    assert appointment(dept["directory_url"], "other@example.edu") is None
    historical = appointment(profile, owner["email"])
    historical["metadata"].update(is_active=False, first_seen_at="2025-01-01", faculty_title="Adjunct Professor")
    storage = tmp_path / "opportunities.json"
    storage.write_text(json.dumps([historical]))
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", storage)

    def saved():
        return {r["id"]: r for r in json.loads(storage.read_text())}

    namesake = appointment(other, "other@example.edu")
    assert namesake["id"] != original_id
    assert osu_faculty.merge_into_processed([namesake]) == (1, 0)
    assert saved()[original_id] == historical

    assert appointment(profile, None)["id"] == original_id
    assert osu_faculty.merge_into_processed([appointment(moved, owner["email"])]) == (0, 1)
    # If only the identified member's link then vanishes, retain the latest personal page.
    assert osu_faculty.merge_into_processed([appointment(None, owner["email"])]) == (0, 1)
    stored = saved()[original_id]
    assert stored["metadata"]["is_active"] and stored["metadata"]["first_seen_at"] == "2025-01-01"
    assert stored["metadata"]["faculty_title"] == "Professor, Biomedical Engineering"
    assert stored["url"] == stored["source_url"] == moved
    assert saved()[namesake["id"]] == namesake
