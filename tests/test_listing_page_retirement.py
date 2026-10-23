"""A professor row whose url is the department's list page is judged by the
person, not by the page (M141).

Linkless directory rows (UCI's social-sciences table, ELS, the cp-dir schools)
store the list page itself as their url. The retirement check compared the
list page's raw config URL with the row's reduced URL, so the page was never
recognised as a list page: every such row in a unit had one identity, and as
long as anyone on the page was read, nobody on it could be retired. Such a row
is now the person on the page: their name together with their address. It is
retired only when the full read shows neither their address nor their name
(unless a row read this run is that person): a title gate or a card selector
that skips a person the page still shows keeps them.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

from bs4 import BeautifulSoup

from src.collectors import faculty_graph as fg
from src.normalizers.deactivate_stale_faculty import (
    GRACE_DAYS,
    deactivate_stale_faculty,
    finalize_unit_ledger,
    identity_key,
    listed_name_key,
)

TODAY = date.today()
LONG_AGO = (TODAY - timedelta(days=GRACE_DAYS + 30)).isoformat()
STARTED = f"{TODAY.isoformat()}T00:00:00+00:00"
LISTING = "https://www.testu.edu/faculty-directory.php"
DEPT = {
    "short": "ANTH",
    "name": "Department of Anthropology",
    "majors": ["Anthropology"],
    "directory_url": LISTING,
    "scrape": {
        "url": LISTING,
        "selectors": {
            "card": "table#profiles tbody tr",
            "name": "td.name",
            "title": "td.title",
            "email": "td.email a[href^='mailto:']",
        },
    },
}
SCHOOL = {
    "school_slug": "testu", "organization": "Test University",
    "id_prefix": "testu", "source": "testu_faculty",
    "location": "Testville", "audience": "external", "departments": [DEPT],
}


def _tr(name, title="Professor", email=None):
    mail = f'<a href="mailto:{email}">{email}</a>' if email else ""
    return (f'<tr><td class="name">{name}</td><td class="title">{title}</td>'
            f'<td class="email">{mail}</td></tr>')


ROWS = [_tr("Ada Lovelace", email="person1@testu.edu"),
        _tr("Grace Hopper", "Associate Professor"),
        _tr("Jane Doe", email="person3@testu.edu")]


def _page(rows, extra=""):
    return ('<html><body><table id="profiles"><tbody>'
            + "".join(rows) + "</tbody></table>" + extra + "</body></html>")


def _stored(rid, name, *, email=None, url="https://testu.edu/Faculty-Directory.php/"):
    # The url as stored rows carry it: the list page, written another way.
    return {
        "id": rid, "source": "testu_faculty", "source_type": "faculty_research",
        "school": "testu", "department": DEPT["name"], "pi_name": name,
        "url": url, "contact_email": email,
        "metadata": {"is_active": True, "last_seen_at": LONG_AGO},
    }


def _read(rows, extra="", ladder=None):
    soup = BeautifulSoup(_page(rows, extra), "html.parser")
    fg._ACTIVE_COVERAGE = fg._new_coverage()
    try:
        specs = fg._parse_cards(soup, DEPT["scrape"]["selectors"], LISTING, ladder)
        coverage = dict(fg._ACTIVE_COVERAGE)
    finally:
        fg._ACTIVE_COVERAGE = None
    return [r for s in specs if (r := fg._normalize(SCHOOL, DEPT, s))], coverage


def _retire(stored, rows=ROWS, extra="", ladder=None, **observation):
    produced, coverage = _read(rows, extra, ladder)
    corpus = [copy.deepcopy(r) for r in produced] + stored
    if observation:
        produced = []
    ledger = {"anth": fg._unit_observation(
        SCHOOL, DEPT, produced, STARTED, coverage=coverage,
        listing_urls=fg._listing_urls(SCHOOL), **observation)}
    finalize_unit_ledger(ledger, corpus, "testu_faculty")
    out = deactivate_stale_faculty(corpus, {"testu_faculty": ledger}, today=TODAY)
    return out, ledger["anth"]


def test_the_page_reads_three_people_on_the_list_page_url():
    produced, _ = _read(ROWS)
    assert [r["pi_name"] for r in produced] == ["Ada Lovelace", "Grace Hopper", "Jane Doe"]
    assert {r["url"] for r in produced} == {LISTING}


def test_rows_on_a_list_page_are_three_people_not_one_page():
    produced, coverage = _read(ROWS)
    entry = fg._unit_observation(SCHOOL, DEPT, produced, STARTED,
                                 coverage=coverage, listing_urls=fg._listing_urls(SCHOOL))
    kinds = [kind for kind, _ in entry["observed_identities"]]
    assert kinds == ["person", "person", "person"]
    assert entry["coverage"]["duplicate_rows"] == 0


def test_raw_and_reduced_list_page_urls_compare_alike():
    a = _stored("a", "Ada Lovelace", email="person1@testu.edu")
    b = _stored("b", "Grace Hopper")
    assert identity_key(a, {LISTING})[0] == "person"
    assert identity_key(a, {LISTING}) != identity_key(b, {LISTING})


def test_a_person_the_full_read_no_longer_lists_is_retired():
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    gone_no_mail = _stored("faculty-testu-anth-0000bbbb", "Ida Absent")
    out, entry = _retire([gone, gone_no_mail])
    assert entry["retirement_authorized"] is True
    assert sorted(p["entity_id"] for p in out["proposals"]) == [
        "faculty-testu-anth-0000aaaa", "faculty-testu-anth-0000bbbb"]
    assert out["newly_deactivated"] == 2
    assert gone["metadata"]["is_active"] is False
    assert gone_no_mail["metadata"]["is_active"] is False


def test_a_person_the_page_still_lists_under_another_spelling_is_kept():
    # Stored as "Jane Q. Doe"; the page now writes "Jane Doe" (a new id).
    still = _stored("faculty-testu-anth-0000cccc", "Jane Q. Doe", email="person3@testu.edu")
    out, entry = _retire([still])
    assert entry["retirement_authorized"] is True
    assert out["newly_deactivated"] == 0
    assert still["metadata"]["is_active"] is True


def test_a_partial_read_retires_nobody():
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    unreadable = '<tr><td class="title">Professor</td><td class="email"></td></tr>'
    out, entry = _retire([gone], rows=ROWS + [unreadable])
    assert entry["coverage"]["unparsed_rows"] == 1
    assert entry["retirement_authorized"] is False
    assert out["newly_deactivated"] == 0
    assert gone["metadata"]["is_active"] is True


def test_a_failed_read_retires_nobody():
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    out, entry = _retire([gone], fetch_status="http_403", parse_status="error")
    assert entry["retirement_authorized"] is False
    assert out["newly_deactivated"] == 0
    assert gone["metadata"]["is_active"] is True


def test_a_namesake_with_another_initial_keeps_no_one_gone():
    # Jane Doe is still listed; Mary Doe is not.
    gone = _stored("faculty-testu-anth-0000dddd", "Mary Doe")
    out, entry = _retire([gone])
    assert entry["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000dddd"]
    assert gone["metadata"]["is_active"] is False


def test_a_namesake_without_an_address_keeps_no_one_gone():
    # Grace Hopper is still listed, with no address; Mary Hopper is not.
    gone = _stored("faculty-testu-anth-0000ffff", "Mary Hopper")
    out, entry = _retire([gone])
    assert entry["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000ffff"]
    assert gone["metadata"]["is_active"] is False


def test_two_people_of_one_name_are_told_apart_by_address():
    listed = _stored("faculty-testu-anth-0000ee01", "Jane Doe", email="person3@testu.edu")
    gone = _stored("faculty-testu-anth-0000ee02", "Jane Doe", email="person7@testu.edu")
    out, entry = _retire([listed, gone])
    assert entry["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000ee02"]
    assert listed["metadata"]["is_active"] is True
    assert gone["metadata"]["is_active"] is False


def test_a_professor_the_page_lists_under_a_title_the_unit_skips_is_kept():
    # The unit keeps professors only; the page still shows these two people.
    director = _stored("faculty-testu-anth-0000ab01", "Pat Example",
                       email="person5@testu.edu")
    emeritus = _stored("faculty-testu-anth-0000ab02", "Lee Q. Sample")
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    namesake_gone = _stored("faculty-testu-anth-0000ab03", "Mary Sample")
    rows = ROWS + [_tr("Pat Example", "Director of Graduate Studies", "person5@testu.edu"),
                   _tr("Lee Sample", "Dean Emeritus")]
    out, entry = _retire([director, emeritus, gone, namesake_gone], rows=rows,
                         ladder={"drop": "director|emerit"})
    assert entry["coverage"]["classified_nonfaculty_rows"] == 2
    assert entry["retirement_authorized"] is True
    # Kept, and the ones the page no longer shows are still retired.
    assert sorted(p["entity_id"] for p in out["proposals"]) == [
        "faculty-testu-anth-0000aaaa", "faculty-testu-anth-0000ab03"]
    assert director["metadata"]["is_active"] is True
    assert emeritus["metadata"]["is_active"] is True
    # What the page showed travels as run-keyed digests only.
    assert "person5@testu.edu" not in str(entry) and "sample" not in str(entry)


def test_a_person_on_a_card_the_selector_does_not_match_is_kept():
    # Two cards outside the table the selector reads: one with an address, one
    # with a name split over two spans and no address.
    extra = ('<div class="card"><h3>Robin Example</h3><p>Assistant Professor</p>'
             '<a href="mailto:person6@testu.edu">Email</a></div>'
             '<div class="card"><h3><span>Kim</span> <span>Sample</span></h3>'
             '<p>Professor</p></div>')
    # Stored under a first name the page no longer writes: kept by the address.
    by_mail = _stored("faculty-testu-anth-0000ac01", "Bobbie Example",
                      email="person6@testu.edu")
    by_name = _stored("faculty-testu-anth-0000ac02", "Kim Sample")
    out, entry = _retire([by_mail, by_name], extra=extra)
    assert entry["retirement_authorized"] is True
    assert out["proposals"] == []
    assert by_mail["metadata"]["is_active"] is True
    assert by_name["metadata"]["is_active"] is True


def test_a_name_over_a_line_break_or_with_a_nickname_is_still_shown():
    # Both under a title the unit skips. The markup breaks the line inside one
    # name, and puts a nickname in brackets inside the other.
    rows = ROWS + [_tr("Kim\n        Sample", "Dean Emeritus"),
                   _tr("Alex (Lex) Example", "Professor Emerita")]
    by_line = _stored("faculty-testu-anth-0000ae01", "Kim Sample")
    by_nickname = _stored("faculty-testu-anth-0000ae02", "Alex Example")
    out, entry = _retire([by_line, by_nickname], rows=rows, ladder={"drop": "emerit"})
    assert entry["coverage"]["classified_nonfaculty_rows"] == 2
    assert entry["retirement_authorized"] is True
    assert out["proposals"] == []
    assert by_line["metadata"]["is_active"] is True
    assert by_nickname["metadata"]["is_active"] is True


def test_a_person_the_page_lists_is_kept_though_a_namesake_was_read():
    # Lee Sample is listed as Dean Emeritus, a title the unit skips. Lisa
    # Sample, read this run, shares the surname and initial, not the person.
    emeritus = _stored("faculty-testu-anth-0000ad01", "Lee Q. Sample")
    rows = ROWS + [_tr("Lisa Sample", email="person8@testu.edu"),
                   _tr("Lee Sample", "Dean Emeritus")]
    out, entry = _retire([emeritus], rows=rows, ladder={"drop": "emerit"})
    assert entry["coverage"]["classified_nonfaculty_rows"] == 1
    assert entry["retirement_authorized"] is True
    assert out["proposals"] == []
    assert emeritus["metadata"]["is_active"] is True


def test_a_name_the_page_writes_inside_a_headline_keeps_the_person():
    # Not a card: a news item whose headline runs the name into other words.
    extra = ('<div class="news"><h3><a href="/news/1">Kim Sample Headlines the '
             'Spring Lecture Series</a></h3></div>')
    named = _stored("faculty-testu-anth-0000ad02", "Kim Sample")
    out, entry = _retire([named], extra=extra)
    assert entry["retirement_authorized"] is True
    assert out["proposals"] == []
    assert named["metadata"]["is_active"] is True


def test_a_person_the_page_has_commented_out_is_retired():
    # The markup still carries the old card inside a comment; no one sees it.
    extra = "<!-- Henry Gone, Professor, person9@testu.edu -->"
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    out, entry = _retire([gone], extra=extra)
    assert entry["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000aaaa"]
    assert gone["metadata"]["is_active"] is False


def test_the_same_address_read_under_another_first_name_stays_listed():
    # The page writes "Countess Lovelace" with the stored row's address, and
    # the run reads her under that name: she stays listed in the row read; the
    # stored copy is retired for the tombstone pass to fold away. One whose
    # address the page shows on a row no one read is kept (as above).
    old = _stored("faculty-testu-anth-0000abab", "Ada Lovelace", email="person1@testu.edu")
    rows = [_tr("Countess Lovelace", email="person1@testu.edu"), ROWS[1], ROWS[2]]
    out, entry = _retire([old], rows=rows)
    assert entry["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000abab"]
    produced, _ = _read(rows)
    assert [(r["pi_name"], r["contact_email"]) for r in produced][0] == (
        "Countess Lovelace", "person1@testu.edu")


def test_a_page_the_run_did_not_record_retires_no_list_page_row():
    # A ledger written before pages were recorded: absence is not shown.
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    produced, coverage = _read(ROWS)
    corpus = [copy.deepcopy(r) for r in produced] + [gone]
    entry = fg._unit_observation(SCHOOL, DEPT, produced, STARTED, coverage=coverage,
                                 listing_urls=fg._listing_urls(SCHOOL))
    entry.pop("page_people", None)
    ledger = {"anth": entry}
    finalize_unit_ledger(ledger, corpus, "testu_faculty")
    out = deactivate_stale_faculty(corpus, {"testu_faculty": ledger}, today=TODAY)
    assert entry["retirement_authorized"] is True
    assert out["proposals"] == []
    assert gone["metadata"]["is_active"] is True


def test_a_label_before_a_colon_is_not_the_name():
    assert listed_name_key("Associated appointment, by courtesy: Jane Doe") == "doe j"
    assert listed_name_key("Jane Doe, PhD: Director") == "doe j"
    assert listed_name_key("Thomas A Pearson, MD") == "pearson t"
    assert listed_name_key("Pearson, Thomas") is None


# The page check reads only the row's own unit's page: a namesake another
# department of the school lists keeps no one gone (review of round 2).
TWO_SEL = {"card": "table#profiles tbody tr", "name": "td.name", "title": "td.title",
           "email": "td.email a[href^='mailto:']"}


def _unit(short, url):
    return {"short": short, "name": f"Department {short}", "majors": [short],
            "directory_url": url, "scrape": {"url": url, "selectors": TWO_SEL}}


UNIT_A = _unit("AAA", "https://www.testu.edu/aaa/people")
UNIT_B = _unit("BBB", "https://www.testu.edu/bbb/people")
TWO_SCHOOL = {"school_slug": "testu", "organization": "Test University", "id_prefix": "testu",
              "source": "testu_faculty", "location": "Testville", "audience": "external",
              "departments": [UNIT_A, UNIT_B]}


def _unit_tr(name, title="Professor"):
    return (f'<tr><td class="name">{name}</td><td class="title">{title}</td>'
            '<td class="email"></td></tr>')


def _unit_read(dept, rows, ladder=None):
    soup = BeautifulSoup('<table id="profiles"><tbody>' + "".join(rows)
                         + "</tbody></table>", "html.parser")
    fg._ACTIVE_COVERAGE = fg._new_coverage()
    try:
        specs = fg._parse_cards(soup, TWO_SEL, dept["scrape"]["url"], ladder)
        cov = dict(fg._ACTIVE_COVERAGE)
    finally:
        fg._ACTIVE_COVERAGE = None
    return [r for s in specs if (r := fg._normalize(TWO_SCHOOL, dept, s))], cov


def test_a_namesake_on_another_units_page_keeps_no_one_gone():
    # Mary Doe left AAA; BBB lists Mark Doe under a title BBB's gate skips.
    gone = {"id": "faculty-testu-aaa-0000aaaa", "source": "testu_faculty",
            "source_type": "faculty_research", "school": "testu",
            "department": UNIT_A["name"], "pi_name": "Mary Doe",
            "url": UNIT_A["scrape"]["url"], "contact_email": None,
            "metadata": {"is_active": True, "last_seen_at": LONG_AGO}}
    a_rows, a_cov = _unit_read(UNIT_A, [_unit_tr("Ada Lovelace")])
    b_rows, b_cov = _unit_read(UNIT_B, [_unit_tr("Grace Hopper"),
                                        _unit_tr("Mark Doe", "Professor Emeritus")],
                               ladder={"drop": "emerit"})
    corpus = [copy.deepcopy(r) for r in a_rows + b_rows] + [gone]
    listing = fg._listing_urls(TWO_SCHOOL)
    ledger = {"aaa": fg._unit_observation(TWO_SCHOOL, UNIT_A, a_rows, STARTED, coverage=a_cov,
                                          listing_urls=listing),
              "bbb": fg._unit_observation(TWO_SCHOOL, UNIT_B, b_rows, STARTED, coverage=b_cov,
                                          listing_urls=listing)}
    finalize_unit_ledger(ledger, corpus, "testu_faculty")
    out = deactivate_stale_faculty(corpus, {"testu_faculty": ledger}, today=TODAY)
    assert ledger["aaa"]["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-aaa-0000aaaa"]
    assert gone["metadata"]["is_active"] is False
