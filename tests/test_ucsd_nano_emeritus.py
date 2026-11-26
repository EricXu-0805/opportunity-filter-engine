from copy import deepcopy
from datetime import date

import pytest
from bs4 import BeautifulSoup

from backend.data_loader import _sanitize_opportunity
from backend.routes.opportunities import _redact
from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.ucsd_faculty import SCHOOL
from src.normalizers.reviewed_faculty_profiles import (
    REVIEWS,
    apply_reviewed_faculty_profile,
    carry_forward_reviewed_appointment,
)

NANO = next(dept for dept in SCHOOL["departments"] if dept["short"] == "NANO")
ESENER = "faculty-ucsd-nano-25a6d469"
HELLER = "faculty-ucsd-nano-dc9e3de3"
AS_OF = date(2026, 11, 26)


def roster(group, *, heller_name="Mike", legacy=True):
    esener, heller = (REVIEWS[oid] for oid in (ESENER, HELLER))
    attr = "previous_url" if legacy else "profile_url"
    esener_url, heller_url = getattr(esener, attr), getattr(heller, attr)
    return BeautifulSoup(f"""
      <table><tbody><tr><td><strong>Professors</strong></td></tr>
      <tr><td><a href="/active">Chen, Shaochen</a></td></tr>
      <tr><td><strong>{group}</strong></td></tr>
      <tr><td><a href="{esener_url}">Esener</a><a href="{esener_url}">, Sadik</a></td></tr>
      <tr><td><a href="{heller_url}">Heller, {heller_name}</a></td></tr>
      <tr><td><strong>Affiliated Faculty</strong></td></tr>
      <tr><td><a href="/affiliated">Yu, Paul</a></td></tr></tbody></table>""", "html.parser")


def profile(full_name, lines):
    ranks = "<br>".join(lines)
    return BeautifulSoup(f'<h3 class="faculty_profile_name">{full_name}</h3><p>{ranks}</p>', "html.parser")


def scrape(monkeypatch, pages):
    requested = []

    def fetch(url, **kwargs):
        requested.append(url)
        return pages[url]

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    rows = [faculty_graph._normalize(SCHOOL, NANO, person) for person in faculty_graph._scrape_directory(NANO)]
    return {row["id"]: row for row in rows}, requested


def legacy_row(oid):
    review = REVIEWS[oid]
    person = {"name": review.previous_name, "url": review.previous_url, "title": ""}
    row = faculty_graph._normalize(SCHOOL, NANO, person)
    assert row["id"] == oid
    row["metadata"].update(last_seen_at="2026-07-24", last_verified="2026-07-24")
    return row


def test_current_roster_excludes_only_the_emeritus_section(monkeypatch):
    rows, requests = scrape(monkeypatch, {NANO["directory_url"]: roster("Professors Emeriti")})
    assert requests == [NANO["directory_url"]]
    assert [row["pi_name"] for row in rows.values()] == ["Shaochen Chen", "Paul Yu"]


@pytest.mark.parametrize(("legacy", "given"), [(True, "Mike"), (True, "Michael"), (False, "Michael")])
def test_corroborated_new_nano_appointments_use_the_original_ids(monkeypatch, legacy, given):
    pages = {NANO["directory_url"]: roster("Professors", heller_name=given, legacy=legacy)}
    pages.update({REVIEWS[ESENER].profile_url: profile("Sadik Esener", ["Professor, NENG", "Professor Emeritus, ECE"]),
                  REVIEWS[HELLER].profile_url: profile("Michael Heller", ["Associate Professor, CNE", "Faculty-Recall, BENG"])})
    rows, requests = scrape(monkeypatch, pages)
    assert set(requests) == set(pages) and len(requests) == 3
    assert len(rows) == 4
    for oid, new_title in ((ESENER, "Professor"), (HELLER, "Associate Professor")):
        incoming = rows[oid]
        assert incoming["source_url"] == REVIEWS[oid].profile_url
        assert incoming["metadata"]["faculty_title"] == new_title
        archived = legacy_row(oid)
        assert apply_reviewed_faculty_profile(archived, today=AS_OF)
        carry_forward_reviewed_appointment(archived, incoming)
        assert incoming["metadata"]["is_active"] is True
        assert not apply_reviewed_faculty_profile(incoming, today=AS_OF)


@pytest.mark.parametrize(("name", "lines"), [
    ("Michael Heller", ["Faculty-Recall, BENG"]),
    ("Michael Heller", ["Adjunct Professor, NENG", "Professor, BENG"]),
    ("Michael Heller", ["Professor, NENG", "Professor Emeritus, NENG"]),
    ("Another Person", ["Professor, NENG"]),
    ("Michael Heller", []),
])
def test_directory_drift_and_another_departments_appointment_do_not_reopen_nano(monkeypatch, name, lines):
    pages = {NANO["directory_url"]: roster("Professors"), REVIEWS[ESENER].profile_url: None,
             REVIEWS[HELLER].profile_url: profile(name, lines)}
    rows, _ = scrape(monkeypatch, pages)
    for oid in (ESENER, HELLER):
        prior = legacy_row(oid)
        apply_reviewed_faculty_profile(prior, today=AS_OF)
        incoming = rows[oid]
        assert not incoming["metadata"]["faculty_title"]
        carry_forward_reviewed_appointment(prior, incoming)
        assert incoming["metadata"]["deactivation_reason"] == "retired_title"
        assert incoming["metadata"]["is_active"] is False
        assert incoming["pi_name"] == REVIEWS[oid].name


@pytest.mark.parametrize("oid", [ESENER, HELLER])
def test_historical_id_name_and_source_preserved_without_changing_other_appointments(oid):
    legacy = legacy_row(oid)
    legacy["description_raw"] = "A separately recorded research description."
    separate = deepcopy(legacy)
    separate["department"] = "Department of Bioengineering"
    separate["metadata"]["faculty_title"] = "Faculty-Recall"
    assert not apply_reviewed_faculty_profile(separate, today=AS_OF)
    assert separate["metadata"]["is_active"] is True
    row = deepcopy(legacy)
    assert apply_reviewed_faculty_profile(row, today=AS_OF)
    assert row["id"] == legacy["id"]
    assert row["pi_name"] == REVIEWS[oid].name
    assert row["title"].startswith(row["pi_name"] + " — ")
    assert row["description_raw"] == legacy["description_raw"]
    assert "Contact this faculty member" not in row["description_clean"]
    assert row["metadata"]["last_seen_at"] == "2026-07-24"
    assert row["metadata"]["faculty_title"] == "Professor Emeritus"
    assert row["url"] == row["source_url"] == REVIEWS[oid].profile_url
    public = _redact(_sanitize_opportunity(deepcopy(legacy)))
    assert public["title"] == REVIEWS[oid].name
    assert public["target_truth"]["actionable"] is False
    assert public["id"] == oid
