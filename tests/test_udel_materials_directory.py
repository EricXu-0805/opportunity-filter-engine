from datetime import date

from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.udel_faculty import SCHOOL
from src.normalizers.reviewed_faculty_profiles import apply_reviewed_faculty_profile


def test_materials_reads_named_links_only_in_full_time_section(monkeypatch):
    unit = next(d for d in SCHOOL["departments"] if d["short"] == "MSEG")
    cfg = unit["scrape"]
    url = unit["directory_url"]
    html = """
        <div id="faculty">
          <div class="et_pb_text_inner"><h4><a href="people/doty/"><img alt="Portrait"></a>
            <a href="/people/doty/">Matthew Doty</a></h4><a href="mailto:doty@udel.edu">Email</a></div>
          <div class="et_pb_text_inner"><h4><a href="/people/korley/">LaShanda Korley</a></h4></div>
          <div class="et_pb_text_inner"><h4><a href="/people/different/">LaShanda Korley</a></h4></div>
          <div class="et_pb_text_inner"><h4><a href="/people/no-name/"><img></a></h4></div>
        </div>
        <div id="emeritus"><div class="et_pb_text_inner"><h4><a href="/retired/">Retired Person</a></h4></div></div>
        <div id="joint"><div class="et_pb_text_inner"><h4><a href="/affiliated/">Affiliated Person</a></h4></div></div>
    """
    coverage = faculty_graph._new_coverage()
    monkeypatch.setattr(faculty_graph, "_ACTIVE_COVERAGE", coverage)
    people = faculty_graph._parse_cards(BeautifulSoup(html, "html.parser"), cfg["selectors"], url,
                                        field_filter=cfg["field_filter"])
    assert [(p["name"], p["url"]) for p in people] == [
        ("Matthew Doty", "https://mseg.udel.edu/people/doty/"),
        ("LaShanda Korley", "https://mseg.udel.edu/people/different/"),
    ]
    assert (coverage["raw_roster_rows"], coverage["parsed_faculty_rows"],
            coverage["classified_nonfaculty_rows"], coverage["unparsed_rows"]) == (4, 2, 1, 1)


def test_gillespie_appointment_correction_matches_original_person_and_old_rank():
    url = "https://me.udel.edu/faculty/john-w-gillespie-jr/"
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "ME")
    row = faculty_graph._normalize(SCHOOL, dept, {"name": "John Gillespie Jr.", "title": "Professor", "url": url})
    assert row["id"] == "faculty-udel-me-4b7217c7"
    reviewed_on = date(2026, 11, 26)
    for different in (dict(row, url="https://example.edu/another-person"),
                      dict(row, metadata=dict(row["metadata"], faculty_title="Research Professor"))):
        assert not apply_reviewed_faculty_profile(different, today=reviewed_on)

    assert apply_reviewed_faculty_profile(row, today=reviewed_on)
    assert row["metadata"]["is_active"] is False
    assert row["metadata"]["deactivation_reason"] == "retired_title"
    assert row["metadata"]["faculty_title"] == "Professor Emeritus"
    assert row["metadata"]["faculty_profile_review"]["source_url"].endswith("3-5-2026_Current-JWG-CV.pdf")
    assert row["url"] == url
