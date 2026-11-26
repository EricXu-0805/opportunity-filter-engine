import json
from copy import deepcopy

from bs4 import BeautifulSoup

from backend.lib.school_coverage import school_coverage
from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import vanderbilt_faculty
from src.evidence import target_truth

DIRECTORY = "https://as.vanderbilt.edu/chemistry/faculty/"
GROUPS = [
    ("faculty-vanderbilt-chem-b0f20085", "Primary Faculty Directory", "primary-faculty"),
    ("faculty-vanderbilt-chem-6968c3d1", "Teaching Faculty Directory", "teaching-faculty"),
]


def test_group_navigation_is_accounted_for_as_nonfaculty(monkeypatch):
    cards = [
        ("?group=primary-faculty", "Primary Faculty Directory"),
        (DIRECTORY + "?group=teaching-faculty", "Teaching Faculty Directory"),
        ("/chemistry/bio/example-professor?group=primary-faculty", "Example Professor"),
    ]
    html = '<table class="table-striped">' + "".join(
        f'<tr><td><strong><a href="{href}">{name}</a></strong></td></tr>' for href, name in cards
    ) + "</table>"
    chem = next(d["scrape"] for d in vanderbilt_faculty.SCHOOL["departments"] if d["short"] == "CHEM")
    ledger = faculty_graph._new_coverage()
    monkeypatch.setattr(faculty_graph, "_ACTIVE_COVERAGE", ledger)
    people = faculty_graph._parse_cards(
        BeautifulSoup(html, "html.parser"), chem["selectors"], DIRECTORY, link_filter=chem["link_filter"],
    )
    assert [person["name"] for person in people] == ["Example Professor"]
    assert ledger["classified_nonfaculty_rows"] == 2
    assert ledger["parsed_faculty_rows"] == 1 and ledger["unparsed_rows"] == 0


def test_repeated_refresh_recovers_old_directory_ids_and_keeps_individual_contacts(tmp_path, monkeypatch):
    records = []
    for record_id, label, group in GROUPS:
        url = DIRECTORY + "?group=" + group
        records.append({
            "id": record_id, "source": "vanderbilt_faculty", "school": "vanderbilt",
            "source_type": "faculty_research", "opportunity_type": "research", "title": label + " — CHEM", "pi_name": label,
            "source_url": url, "url": url, "description_clean": "Contact this faculty member.",
            "application": {"contact_method": "email", "application_url": url},
            "eligibility": {"eligibility_text_raw": "Contact this faculty member."},
            "metadata": {"is_active": True, "first_seen_at": "2026-07-13", "last_seen_at": "2026-11-19"},
        })
    real = {**deepcopy(records[0]), "id": "original-chemistry-id", "pi_name": "Example Professor",
            "url": DIRECTORY + "individual", "source_url": DIRECTORY + "individual"}
    records.append(real)
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps(records))
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", path)

    for _ in range(2):
        vanderbilt_faculty.merge_into_processed([deepcopy(real)])
        after = json.loads(path.read_text())
        assert [r["id"] for r in after] == [r["id"] for r in records]
        for old, guide in zip(records[:2], after[:2], strict=True):
            assert guide["url"] == old["url"] and guide["title"] == old["pi_name"]
            assert guide["application"]["application_url"] is None and guide["pi_name"] is None
            assert not guide["eligibility"]["eligibility_text_raw"]
            assert guide["metadata"]["first_seen_at"] == old["metadata"]["first_seen_at"]
            assert guide["metadata"]["last_seen_at"] == old["metadata"]["last_seen_at"]
            truth = target_truth(guide)
            assert truth.reference_only and not truth.actionable
        assert after[-1]["pi_name"] == real["pi_name"]
        assert target_truth(after[-1]).actionable
        assert school_coverage(after)["vanderbilt"].faculty_contact_count == 1
