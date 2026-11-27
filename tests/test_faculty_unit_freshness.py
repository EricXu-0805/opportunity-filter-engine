import json
from datetime import UTC, datetime

from src.collectors import faculty_graph as fg
from src.collectors import source_health as sh


def test_department_report_counts_only_current_roster_reads(tmp_path, monkeypatch):
    def person(name):
        return fg.faculty(name, title="Professor", url="https://example.edu/" + name.split()[0])

    saved, shared, fresh = map(person, ("Ada Example", "Cora Example", "Bob Example"))
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps([{"name": "Dana Example", "title": "Professor"}]))
    school = {
        "school_slug": "njit", "source": "njit_faculty", "id_prefix": "test",
        "organization": "Example University", "location": "Example",
        "departments": [
            {"short": "mix", "name": "Mixed", "majors": [], "faculty": [saved, shared]},
            {"short": "file", "name": "Frozen", "majors": [], "json_dir": {
                "file": str(path), "harvested_on": "2026-07-10",
                "name_fields": ["name"], "title_field": "title",
            }},
            {"short": "live", "name": "Live", "majors": [], "faculty": [shared]},
        ],
    }
    def directory(dept):
        if dept["short"] == "mix":
            return [dict(shared), dict(fresh)]
        if dept["short"] == "live":
            return [dict(shared)]
        return []

    def enrich(people, config):
        # Reading an individual's biography doesn't read a department listing.
        for spec in people:
            spec["_verification_scope"] = "profile"
        return people

    monkeypatch.setattr(fg, "_scrape_directory", directory)
    monkeypatch.setattr(fg, "_apply_profile_enrich", enrich)
    ledger = {}
    fg.fetch_and_normalize(school, deep=True, unit_ledger=ledger)
    assert {unit: (entry["live_roster_count"], entry["retained_only_count"])
            for unit, entry in ledger.items()} == {"mix": (2, 1), "file": (0, 1), "live": (1, 0)}
    # The last department read Cora too, but the existing cross-unit dedup
    # assigned the emitted row to the first department.
    assert ledger["live"]["observed_count"] == 0


def test_retained_entries_report_a_gap_until_a_real_read_clears_it():
    source, dept = "njit_faculty", "math"
    date = datetime(2026, 11, 25, tzinfo=UTC)
    health = sh.empty_ledger()
    sh.record_attempt(health, source=source, school="njit", outcome=sh.SUCCESS_NONZERO,
                      emitted=5, baseline=5, now=date)
    entry = {"source": source, "unit_id": dept, "baseline_active_count": 5,
             "observed_count": 5, "observed_entity_ids": ["faculty-id"], "fetch_status": "ok",
             "parse_status": "ok", "validation_status": "ok",
             "missed_present_identities": [], "coverage": {"parsed_faculty_rows": 0}}
    report = {source: {"status": "ok", "stale_unit_ledger": {dept: entry}}}

    def status():
        sh.record_faculty_unit_checks(health, report, date)
        return sh.public_school_freshness(health, date, {source})["njit"]["status"]

    entry.update(live_roster_count=4, retained_only_count=1)
    assert status() == sh.PUBLIC_PARTLY_UNCHECKED
    entry.update(live_roster_count=0, retained_only_count=5)
    assert status() == sh.PUBLIC_PARTLY_UNCHECKED
    # Old summaries with only emitted rows have no evidence to clear this.
    del entry["live_roster_count"], entry["retained_only_count"]
    assert status() == sh.PUBLIC_PARTLY_UNCHECKED
    entry.update(live_roster_count=5, retained_only_count=0)
    del entry["missed_present_identities"]
    entry.update(baseline_identity_count=5, matched_identity_count=4)
    assert status() == sh.PUBLIC_PARTLY_UNCHECKED
    entry.update(matched_identity_count=5)
    assert status() == sh.PUBLIC_CURRENT
