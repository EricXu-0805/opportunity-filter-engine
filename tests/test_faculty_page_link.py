"""A faculty row's link is published as the person's own page or as a roster."""
import pytest

from backend import data_loader
from backend.lib.public_opportunity_detail import writing_target_version
from backend.lib.public_projection import project_public_opportunity_payload
from backend.routes.matches import _match_card
from backend.routes.opportunities import _redact
from src import faculty_page_link
from src.faculty_page_link import ROSTER_LINKS_MARKER, configured_directory_urls, link_key, mark_roster_links

ROSTER = "https://chem.example.edu/people/faculty/"


def _row(number: int, name: str, url: str, source_url: str | None = None, **overrides) -> dict:
    row = {
        "id": f"faculty-example-chem-{number:08x}", "source": "example_faculty", "source_type": "faculty_research",
        "school": "example", "department": "Department of Chemistry", "pi_name": name, "title": name,
        "organization": "Example University", "url": url, "source_url": source_url or url,
        "eligibility": {}, "application": {}, "metadata": {"is_active": True, "last_verified": "2026-11-20T00:00:00"},
    }
    row.update(overrides)
    return row


def _page(row: dict) -> dict | None:
    return project_public_opportunity_payload(dict(row), row).get("faculty_page")


@pytest.fixture(autouse=True)
def no_configured_directories(monkeypatch):
    monkeypatch.setattr(faculty_page_link, "configured_directory_urls", lambda: {})


@pytest.mark.parametrize(("url", "key"), [
    (" https://chem.example.edu/people/faculty/ ", "https://chem.example.edu/people/faculty"),
    ("https://chem.example.edu/people/faculty#staff", "https://chem.example.edu/people/faculty"),
    ("https://catalog.example.edu/chemistry/#faculty:~:text=Example%2C%20Ada", "https://catalog.example.edu/chemistry"),
    # A query string or a hash route names one person's page.
    ("https://example.edu/profile.html?id=ADA", "https://example.edu/profile.html?id=ADA"),
    ("https://my.example.edu/#/directory/person/ada", "https://my.example.edu/#/directory/person/ada"),
    ("", None), (None, None),
])
def test_a_link_is_compared_as_the_page_it_opens(url, key):
    assert link_key(url) == key


def test_a_link_three_people_share_is_the_directory_and_a_page_of_ones_own_is_a_profile():
    own = "https://chem.example.edu/people/ada-example"
    rows = [_row(1, "Ada Example", own), _row(2, "Ben Sample", ROSTER), _row(3, "Cy Specimen", ROSTER),
            _row(4, "Di Instance", ROSTER + "#staff")]
    mark_roster_links(rows)
    assert _page(rows[0]) == {"kind": "profile", "url": own}
    assert [_page(row) for row in rows[1:]] == [
        {"kind": "directory", "url": ROSTER}, {"kind": "directory", "url": ROSTER},
        {"kind": "directory", "url": ROSTER + "#staff"}]


def test_two_people_on_one_page_or_one_person_in_three_rows_keep_it_as_their_page():
    lab = "https://sites.example.edu/example-sample-lab"
    own = "https://chem.example.edu/people/cy-specimen"
    rows = [_row(1, "Ada Example", lab), _row(2, "Ben Sample", lab),
            _row(3, "Cy Specimen", own), _row(4, "cy  specimen", own, department="Department of Physics"),
            _row(5, "Cy Specimen", own, department="Program in Materials")]
    mark_roster_links(rows)
    assert [_page(row)["kind"] for row in rows] == ["profile"] * 5


def test_the_persons_own_page_is_offered_when_the_cited_page_is_the_roster():
    people = [("Ada Example", "https://chem.example.edu/people/ada-example"),
              ("Ben Sample", "https://chem.example.edu/people/ben-sample"), ("Cy Specimen", ROSTER)]
    rows = [_row(n, name, url, source_url=ROSTER) for n, (name, url) in enumerate(people)]
    mark_roster_links(rows)
    assert _page(rows[0]) == {"kind": "profile", "url": "https://chem.example.edu/people/ada-example"}
    assert _page(rows[1]) == {"kind": "profile", "url": "https://chem.example.edu/people/ben-sample"}
    assert _page(rows[2]) == {"kind": "directory", "url": ROSTER}


def test_text_fragments_into_one_catalog_page_are_one_roster():
    catalog = "https://catalog.example.edu/chemistry/#faculty:~:text="
    rows = [_row(n, name, catalog + name.split()[1]) for n, name in
            enumerate(["Ada Example", "Ben Sample", "Cy Specimen"])]
    mark_roster_links(rows)
    assert [_page(row) for row in rows] == [{"kind": "directory", "url": row["url"]} for row in rows]


def test_a_passage_of_the_roster_a_review_cites_is_the_roster_and_a_passage_of_ones_own_page_is_not():
    catalog = "https://catalog.example.edu/chemistry/#faculty"
    passage = catalog + ":~:text=Example%2C%20Ada"
    own = "https://profiles.example.edu/display/bsample#:~:text=Her%20research%20has%20centered%20on"
    reviewed = {"is_active": True, "faculty_profile_review": {"source_url": catalog, "reviewed_on": "2026-11-26"}}
    rows = [_row(1, "Ada Example", passage, metadata=reviewed), _row(2, "Ben Sample", own),
            _row(3, "Cy Specimen", passage.replace("Example%2C%20Ada", "Specimen%2C%20Cy"))]
    mark_roster_links(rows)
    assert _page(rows[0]) == {"kind": "directory", "url": passage}
    assert _page(rows[1]) == {"kind": "profile", "url": own}
    # No review names the catalog as this row's roster, and two people do not make one.
    assert _page(rows[2])["kind"] == "profile"


def test_sharing_is_counted_among_the_people_of_one_collector():
    rows = [_row(1, "Ada Example", ROSTER), _row(2, "Ben Sample", ROSTER),
            _row(3, "Cy Specimen", ROSTER, source="sample_faculty"),
            _row(4, "Di Instance", ROSTER, source_type="campus_program")]
    mark_roster_links(rows)
    assert [_page(row) and _page(row)["kind"] for row in rows] == ["profile", "profile", "profile", None]
    assert ROSTER_LINKS_MARKER not in rows[3]


def test_a_unit_directory_the_school_config_names_is_a_directory_for_a_single_row(monkeypatch):
    rows = [_row(1, "Ada Example", ROSTER), _row(2, "Ben Sample", "https://chem.example.edu/people/ben-sample")]
    monkeypatch.setattr(faculty_page_link, "configured_directory_urls",
                        lambda: {"example_faculty": frozenset({link_key(ROSTER)})})
    mark_roster_links(rows)
    assert _page(rows[0]) == {"kind": "directory", "url": ROSTER}
    assert _page(rows[1])["kind"] == "profile"


def test_school_configs_name_their_unit_directories(monkeypatch):
    monkeypatch.undo()
    directories = configured_directory_urls()
    assert "https://krieger.jhu.edu/people/faculty-directory" in directories["jhu_faculty"]
    assert all(source.endswith("_faculty") for source in directories)


def test_a_row_the_loader_never_marked_claims_neither():
    row = _row(1, "Ada Example", "https://chem.example.edu/people/ada-example")
    payload = project_public_opportunity_payload(dict(row), row)
    assert "faculty_page" not in payload


def test_the_mark_and_a_stale_answer_never_reach_the_public_payload():
    rows = [_row(n, name, ROSTER) for n, name in enumerate(["Ada Example", "Ben Sample", "Cy Specimen"])]
    mark_roster_links(rows)
    stale = dict(rows[0], faculty_page={"kind": "profile", "url": ROSTER})
    for payload in (project_public_opportunity_payload(stale, rows[0]), _redact(rows[0]), _match_card(rows[0])):
        assert ROSTER_LINKS_MARKER not in payload
        assert payload["faculty_page"] == {"kind": "directory", "url": ROSTER}
    listing = _row(9, "", ROSTER, source_type="campus_program", faculty_page={"kind": "profile", "url": ROSTER})
    assert "faculty_page" not in project_public_opportunity_payload(dict(listing), listing)


def test_the_answer_never_moves_the_version_a_saved_draft_is_bound_to():
    rows = [_row(1, "Ada Example", ROSTER), _row(2, "Ben Sample", ROSTER)]
    unanswered = writing_target_version(_redact(rows[0]))
    mark_roster_links(rows)
    own = _redact(rows[0])
    rows.append(_row(3, "Cy Specimen", ROSTER))
    mark_roster_links(rows)
    listed = _redact(rows[0])
    assert (own["faculty_page"]["kind"], listed["faculty_page"]["kind"]) == ("profile", "directory")
    # Nothing about Ada changed: not when the server began answering, and
    # not when a third colleague's row made her link a roster.
    assert writing_target_version(own) == writing_target_version(listed) == unanswered


def test_an_unsafe_link_is_never_offered_and_a_reassigned_page_offers_none():
    rows = [_row(1, "Ada Example", "javascript:alert(1)", source_url=ROSTER),
            _row(2, "Ben Sample", ROSTER), _row(3, "Cy Specimen", ROSTER),
            _row(4, "Di Instance", "https://chem.example.edu/people/di-instance",
                 metadata={"is_active": False, "deactivation_reason": "profile_identity_mismatch"})]
    mark_roster_links(rows)
    assert _page(rows[0]) == {"kind": "directory", "url": ROSTER}
    assert _page(rows[3]) is None


def test_the_corpus_loader_marks_every_faculty_row():
    rows = [_row(1, "Ada Example", "https://chem.example.edu/people/ada-example", source_url=ROSTER),
            _row(2, "Ben Sample", ROSTER), _row(3, "Cy Specimen", ROSTER)]
    loaded = {row["id"]: row for row in data_loader._canonicalize_corpus(rows)}
    assert [_redact(loaded[row["id"]])["faculty_page"]["kind"] for row in rows] == ["profile", "directory", "directory"]
