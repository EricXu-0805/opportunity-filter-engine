from copy import deepcopy

import pytest
from bs4 import BeautifulSoup

from backend.lib.opportunity_detail import build_detail_fields
from backend.lib.public_opportunity_detail import project_public_detail
from src.collectors import faculty_graph as fg
from src.collectors import ucb_common
from src.collectors.bu_questrom_research import APPOINTMENTS, CAMPUS_PROFILE, HOME, PERSON
from src.collectors.schools.bu_faculty import SCHOOL
from src.collectors.uiuc_faculty import _carry_forward_enrichment

DEPT = next(d for d in SCHOOL["departments"] if d["short"] == "QST")
DATE = "2026-11-26T13:51:12+00:00"
AREA = "industrial organization and urban economics"


def capture(monkeypatch, *, name=PERSON, href=HOME, heading=PERSON, area=AREA, final=HOME):
    listing = (f'<h2>Charles River Campus Appointments, 2025</h2>'
               f'<h4 class="bu_collapsible">Questrom School of Business</h4>'
               f'<div class="bu_collapsible_section"><ul><li><a href="{href}">{name}</a></li></ul></div>')
    personal = f"<h1>{heading}</h1><p>I'm an assistant professor at Boston University. My research is in {area}.</p>"
    hits = []

    def fetch(url):
        hits.append(url)
        if url == HOME and final is None:
            return None
        text, redirected = (listing, url) if url == APPOINTMENTS else (personal, final)
        page = BeautifulSoup(text, "html.parser")
        return ucb_common._mark_fetched_soup_observation(page, requested_url=url, final_url=redirected, observed_at=DATE)

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    return hits


def refreshed():
    spec = fg.faculty(PERSON, title="Assistant Professor", url=CAMPUS_PROFILE)
    fg._apply_research_join(DEPT, [spec])
    return fg._normalize(SCHOOL, DEPT, spec)


def field(row, name="research_content"):
    return build_detail_fields(project_public_detail(row), row)["fields"][name]


def test_only_the_named_originals_research_cites_its_provost_linked_home(monkeypatch):
    hits = capture(monkeypatch)
    row = refreshed()
    assert hits == [APPOINTMENTS, HOME]
    assert row["id"] == "faculty-bu-qst-3cc6c010"
    assert field(row)["explicit"]["research_areas"] == AREA + "."
    assert field(row)["provenance"] == {"source_url": HOME, "observed_at": DATE}
    assert field(row, "department")["provenance"]["source_url"] == CAMPUS_PROFILE
    for k, wrong in (("id", "other"), ("school", "other"), ("source_url", "https://other.edu/"),
                     ("pi_name", "Another Person")):
        other = deepcopy(row)
        other[k] = wrong
        assert field(other)["provenance"]["source_url"] != HOME
    capture(monkeypatch, final=None)
    failed = refreshed()
    _carry_forward_enrichment(row, failed)
    assert field(failed)["provenance"] == field(row)["provenance"]


@pytest.mark.parametrize("changed", [
    {"name": "Another Person"}, {"href": "https://wrong.github.io/"},
    {"heading": "Another Person"}, {"area": ""},
])
def test_a_confirmed_change_withdraws_the_previously_observed_homepage_facts(monkeypatch, changed):
    capture(monkeypatch)
    original = refreshed()
    hits = capture(monkeypatch, **changed)
    current = refreshed()
    _carry_forward_enrichment(original, current)
    assert not current["metadata"]["research_areas_raw"]
    assert HOME != field(current)["provenance"]["source_url"]
    if "name" in changed or "href" in changed:
        assert hits == [APPOINTMENTS]
