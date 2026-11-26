"""IU directories keep personal identity in a query parameter on one shared path."""
import json

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import indiana_faculty
from src.normalizers.deactivate_stale_faculty import canonical_profile_url, unit_identity_completeness

KELLEY = next(d for d in indiana_faculty.SCHOOL["departments"] if d["short"] == "KELLEY")
MEDIA = next(d for d in indiana_faculty.SCHOOL["departments"] if d["short"] == "MSCH")
KELLEY_PROFILE = "https://kelley.iu.edu/faculty-research/faculty-directory/profile.html"
MEDIA_PROFILE = "https://mediaschool.indiana.edu/people/profile.html"


@pytest.mark.parametrize(("endpoint", "parameter"), [(KELLEY_PROFILE, "id"), (MEDIA_PROFILE, "p")])
def test_query_profile_requires_one_safe_person_key(endpoint, parameter):
    path = endpoint.removeprefix("https://")
    a = f"{endpoint}?utm_medium=directory&{parameter}=One123#contact"
    assert canonical_profile_url(a) == f"{path}?{parameter}=one123"
    assert canonical_profile_url(f"{endpoint}?{parameter}=one123&ref=footer") == canonical_profile_url(a)
    assert canonical_profile_url(f"{endpoint}?{parameter}=Two456") != canonical_profile_url(a)
    for query in ("", "?utm_medium=faculty", f"?{parameter}=", f"?{parameter}=a&{parameter}=b",
                  f"?{parameter}=not%2Fa%2Fperson"):
        assert canonical_profile_url(endpoint + query) is None
    assert canonical_profile_url("https://other.edu/people/profile.html?id=someone") == "other.edu/people/profile.html"


@pytest.mark.parametrize(("endpoint", "reason"), [
    (KELLEY_PROFILE, "ambiguous_kelley_directory_identity"),
    (MEDIA_PROFILE, "ambiguous_media_school_directory_identity"),
])
def test_an_old_query_stripped_ledger_cannot_authorize_absence(endpoint, reason):
    entry = {"roster_source_confirmed": True, "unit_url": endpoint, "observed_identities": [
        ["url", endpoint.removeprefix("https://")]], "coverage": faculty_graph._new_coverage()}
    assert unit_identity_completeness(entry) == (False, reason)


def test_current_and_earlier_cards_read_ranks_from_their_own_contact_area(monkeypatch):
    markup = """
      <article class="faculty-card"><h2 class="faculty-card__name"><a href="profile.html?id=ONE">One Example</a></h2>
        <div class="faculty-card__contact"><a href="mailto:one@example.edu">one@example.edu</a>
          <span>Bloomington</span><span>Senior Lecturer</span></div>
        <p class="faculty-card__interests">Economics of higher education</p></article>
      <div class="faculty-directory grid"><div class="grid-item"></div><div class="grid-item">
        <h3><a href="profile.html?id=TWO">Two Example</a></h3><div class="text">
        <p>Clinical Professor<br/><a href="mailto:two@example.edu">two@example.edu</a></p></div></div>
        <div class="grid-item"><div class="text"><p>Market design</p></div></div></div>
      <article class="faculty-card"><h2 class="faculty-card__name"><a href="profile.html?id=THREE">Three Example</a></h2>
        <div class="faculty-card__contact"><span>Visiting Assistant Professor</span></div></article>
      <article class="faculty-card"><h2><a href="other.html">Directory help</a></h2></article>
      <article class="faculty-card"><h2 class="faculty-card__name"><a href="profile.html?id=FOUR">Four Example</a></h2>
        <div class="faculty-card__contact"><span>Senior Lecturer (retired)</span></div></article>
    """
    coverage = faculty_graph._new_coverage()
    monkeypatch.setattr(faculty_graph, "_ACTIVE_COVERAGE", coverage)
    config = KELLEY["scrape"]
    specs = faculty_graph._parse_cards(BeautifulSoup(markup, "html.parser"), config["selectors"],
                                       KELLEY["directory_url"], config["ladder_filter"])
    assert [(p["name"], p["title"]) for p in specs] == [
        ("One Example", "Senior Lecturer"), ("Two Example", "Clinical Professor"),
        ("Four Example", "Senior Lecturer (retired)")]
    assert specs[0]["research_areas"] == "Economics of higher education"
    assert specs[1]["research_areas"] == "Market design"
    assert specs[0]["url"] == KELLEY_PROFILE + "?id=ONE"
    assert specs[1]["url"] == KELLEY_PROFILE + "?id=TWO"
    assert faculty_graph._normalize(indiana_faculty.SCHOOL, KELLEY, specs[2]) is None
    assert coverage["raw_roster_rows"] == 5 and coverage["unparsed_rows"] == 1


@pytest.mark.parametrize(("dept", "endpoint", "key", "current", "historical"), [
    (KELLEY, KELLEY_PROFILE, "id=KNUSSBAU", "Kathie Nussbaum", "Kathleen Nussbaum"),
    (MEDIA, MEDIA_PROFILE, "p=krrudd", "Kamady Rudd", "Kamady Lewis"),
])
def test_renamed_profile_updates_original_id_and_another_person_keeps_their_own(dept, endpoint, key,
                                                                                current, historical, tmp_path, monkeypatch):
    def entry(name, query):
        return faculty_graph._normalize(indiana_faculty.SCHOOL, dept,
                                        {"name": name, "url": endpoint + "?" + query, "title": "Professor"})

    original = entry(historical, key)
    original["metadata"]["first_seen_at"] = "2026-07-23T12:00:00"
    updated = entry(current, key + "&utm_source=directory")
    other = entry(current, key.split("=")[0] + "=DIFFERENT")
    assert updated["id"] == original["id"] != other["id"]
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps([original]))
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", path)
    assert indiana_faculty.merge_into_processed([updated, other]) == (1, 1)
    stored = json.loads(path.read_text())
    assert [r["id"] for r in stored] == [original["id"], other["id"]]
    assert stored[0]["metadata"]["first_seen_at"] == "2026-07-23T12:00:00"
    assert stored[0]["pi_name"] == current and stored[0]["url"] == updated["url"]


def test_kelley_only_binds_an_address_to_one_named_card_from_its_observed_page():
    def card(person, key, emails):
        contacts = "".join(f'<a href="mailto:{address}">{address}</a>' for address in emails)
        return (f'<article class="faculty-card"><h2 class="faculty-card__name">'
                f'<a href="profile.html?id={key}">{person}</a></h2>'
                f'<div class="faculty-card__contact">{contacts}<span>Professor</span></div></article>')

    config = KELLEY["scrape"]
    markup = "".join([
        card("Ada Roe", "AROE", ["aroe@iu.edu"]),
        card("Ben Fox", "BFOX", ["bfox@iu.edu", "other@iu.edu"]),
        card("Cal Lee", "CLEE", ["lee@example.org"]),
    ])
    soup = BeautifulSoup(markup, "html.parser")
    soup._ofe_requested_url = soup._ofe_final_url = config["url"]
    soup._ofe_observed_at = "2026-11-26T15:00:00+00:00"
    specs = faculty_graph._parse_cards(soup, config["selectors"], config["url"], config["ladder_filter"])
    records = [faculty_graph._normalize(indiana_faculty.SCHOOL, KELLEY, spec) for spec in specs]
    assert records[0]["metadata"]["identity_bound"] is True
    assert records[0]["metadata"]["contact_source_url"] == config["url"]
    assert [row["contact_email"] for row in records] == ["aroe@iu.edu", None, None]
