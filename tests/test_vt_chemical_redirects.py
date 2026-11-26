from datetime import date

from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools import vt_faculty
from src.normalizers.reviewed_faculty_profiles import apply_reviewed_faculty_profile


def test_chemical_engineering_reads_core_redirects_and_preserves_affiliate_home_departments():
    dept = next(unit for unit in vt_faculty.SCHOOL["departments"] if unit["short"] == "ChE")
    cards = [
        ("bio", "Chang Lu", "/People/faculty/Lu.html"),
        ("redirect", "Julia Ross", "/People/faculty/Ross.html"),
        ("redirect", "Guoliang Liu", "/People/affiliated-faculty/guoliang-liu.html"),
        ("news", "College News", "/People/faculty/latest-news.html"),
    ]
    markup = "".join(
        f'<div class="vt-list-item-wrapper"><span class="vt-list-item-heading" data-itemtype="{kind}"></span>'
        f'<a class="vt-list-item-title-link" href="{url}">{name}<span>, {kind}</span></a></div>'
        for kind, name, url in cards
    )
    people = faculty_graph._parse_cards(
        BeautifulSoup(markup, "html.parser"), dept["scrape"]["selectors"], dept["directory_url"]
    )
    assert [person["name"] for person in people] == ["Chang Lu", "Julia Ross"]
    record = faculty_graph._normalize(vt_faculty.SCHOOL, dept, people[1])
    assert record["id"] == "faculty-vt-che-e1d3b3cb"
    assert apply_reviewed_faculty_profile(record, today=date(2026, 11, 26))
    assert record["url"] == record["source_url"] == "https://www.provost.vt.edu/who_we_are/julie-ross-bio.html"
    assert record["metadata"]["faculty_profile_review"]["source_url"] == dept["directory_url"]
    assert not apply_reviewed_faculty_profile(record, today=date(2026, 12, 1))
    new_profile = "https://che.vt.edu/People/faculty/julie-ross.html"
    changed = faculty_graph._normalize(vt_faculty.SCHOOL, dept, {**people[1], "url": new_profile})
    assert changed["id"] == record["id"]
    assert not apply_reviewed_faculty_profile(changed, today=date(2026, 12, 1))
    assert changed["url"] == new_profile
