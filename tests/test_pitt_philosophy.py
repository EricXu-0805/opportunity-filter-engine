import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.pitt_faculty import SCHOOL
from src.normalizers.reviewed_faculty_profiles import REVIEWS, apply_reviewed_faculty_profile


def test_philosophy_personal_links_are_bound_to_names_in_the_primary_faculty_section():
    dept = next(unit for unit in SCHOOL["departments"] if unit["short"] == "PHIL")
    cfg = dept["scrape"]
    html = """
        <h3>Primary Faculty</h3>
        <div class="views-row"><a href="/unrelated">View news</a>
          <a href="/people/kstanton"><img src="/portrait.png" alt="">
            <div class="views-field-title"><span class="field-content">Kate Stanton</span></div>
          </a></div>
        <div class="views-row"><div class="views-field-title"><span class="field-content">
          <a href="/people/rbatterman">Robert Batterman</a></span></div></div>
        <div class="views-row"><a href="/unrelated">Staff contact</a>
          <div class="views-field-title"><span class="field-content">Thomas Berry</span></div></div>
        <h3>Graduate Students</h3>
        <div class="views-row"><a href="/people/graduate">
          <div class="views-field-title"><span class="field-content">Tomas Albergo</span></div>
        </a></div>
    """
    cards = faculty_graph._parse_cards(
        BeautifulSoup(html, "html.parser"), cfg["selectors"], cfg["url"],
        section_filter=cfg["section_filter"],
    )
    rows = [faculty_graph._normalize(SCHOOL, dept, card) for card in cards]
    assert [(row["id"], row["url"], row["source_url"]) for row in rows] == [
        ("faculty-pitt-phil-2930bf5f", cfg["url"] + "/kstanton", cfg["url"] + "/kstanton"),
        ("faculty-pitt-phil-d41160dd", cfg["url"] + "/rbatterman", cfg["url"] + "/rbatterman"),
        ("faculty-pitt-phil-f8df8e27", cfg["url"], cfg["url"]),
    ]


@pytest.mark.parametrize("person_mail", [False, True])
def test_philosophy_enrichment_never_uses_footer_contact(monkeypatch, person_mail):
    dept = next(unit for unit in SCHOOL["departments"] if unit["short"] == "PHIL")
    individual = '<a href="mailto:personal@example.edu">Faculty contact</a>' if person_mail else ""
    page = BeautifulSoup(f"""
        <h1>Kate Stanton</h1>
        <div class="views-field-field-email">{individual}</div>
        <footer><a href="mailto:administrator@example.edu">Undergraduate advising</a></footer>
    """, "html.parser")
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *args, **kwargs: page)
    result = faculty_graph._enrich_profile(
        dept["directory_url"] + "/kstanton", dept["scrape"]["profile_enrich"], expected_name="Kate Stanton",
    )
    assert result[3] == ("personal@example.edu" if person_mail else None)
    assert result[4]


def _kate_appointment(unit, record_id):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == unit)
    review = REVIEWS[record_id]
    row = faculty_graph._normalize(SCHOOL, dept, {
        "name": review.name, "title": review.previous_title, "url": review.profile_url,
    })
    assert row["id"] == record_id
    assert apply_reviewed_faculty_profile(row)
    return row


@pytest.mark.parametrize("reverse", [True, False])
@pytest.mark.parametrize("identical_spelling", [True, False])
def test_published_secondary_points_to_the_reviewed_primary_in_either_order(reverse, identical_spelling):
    primary = _kate_appointment("PHIL", "faculty-pitt-phil-2930bf5f")
    secondary = _kate_appointment("LING", "faculty-pitt-ling-e0bda033")
    if identical_spelling:
        secondary["url"] = primary["url"]
    rows = [primary, secondary] if reverse else [secondary, primary]
    for row in rows:
        row["keywords"] = ["conversational semantics"]
        row["contact_email"] = "verified.person@example.edu"
    for _ in range(2):
        result = faculty_graph.collapse_same_person_faculty(rows, published_ids={row["id"] for row in rows})
        assert {row["id"] for row in result["kept"]} == {primary["id"], secondary["id"]}
        assert primary["metadata"]["is_active"]
        assert not secondary["metadata"]["is_active"]
        assert secondary["metadata"]["duplicate_of"] == primary["id"]
        assert "Secondary appointment in Linguistics" in primary["metadata"]["faculty_title"]


def test_missing_or_changed_appointment_does_not_pin_a_same_name_record():
    from src.normalizers.reviewed_faculty_profiles import reviewed_primary_appointment

    primary = _kate_appointment("PHIL", "faculty-pitt-phil-2930bf5f")
    secondary = _kate_appointment("LING", "faculty-pitt-ling-e0bda033")
    assert reviewed_primary_appointment([primary]) is None
    assert reviewed_primary_appointment([primary, {**secondary, "pi_name": "Another Person"}]) is None
    assert reviewed_primary_appointment([primary, {**secondary, "id": "another-faculty-record"}]) is None
    assert reviewed_primary_appointment([primary, {**secondary, "url": "https://pitt.edu/another-person"}]) is None
    secondary["metadata"]["faculty_title"] = "Professor of Linguistics"
    assert reviewed_primary_appointment([primary, secondary]) is None
