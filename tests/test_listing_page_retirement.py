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
that skips a person the page still shows keeps them. The address counts only
in a card that also shows their surname (M178).
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest
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


@pytest.mark.parametrize("address", [
    '<a href="mailto:person9@testu.edu">Email</a>', "<p>person9@testu.edu</p>"],
    ids=["mailto", "text"])
def test_an_address_inside_another_persons_card_keeps_no_one(address):
    # The page still shows the stored address, on a card the selector does not
    # match that names someone else; a namesake's card carries another (M178).
    extra = (f'<div class="card"><h3>Robin Example</h3><p>Lecturer</p>{address}</div>'
             '<div class="card"><h3>Mary Gone</h3>'
             '<a href="mailto:person7@testu.edu">Email</a></div>')
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    out, entry = _retire([gone], extra=extra)
    assert entry["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000aaaa"]
    assert out["records_preserved_still_listed"] == 0
    assert gone["metadata"]["is_active"] is False


def test_the_first_address_on_the_page_is_read_in_its_own_card_too():
    # The other person's row comes first, under a title the unit skips.
    rows = [_tr("Robin Example", "Dean Emeritus", "person9@testu.edu"), *ROWS,
            _tr("Mary Gone", "Dean Emerita", "person7@testu.edu")]
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    out, entry = _retire([gone], rows=rows, ladder={"drop": "emerit"})
    assert entry["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000aaaa"]


def test_an_address_in_a_card_with_the_surname_keeps_the_person():
    # The card writes the stored surname under another first name; a second
    # card carries another address and the stored first name.
    extra = ('<div class="card"><h3>Robin Gone</h3><p>person9@testu.edu</p></div>'
             '<div class="card"><h3>Henry Example</h3>'
             '<a href="mailto:person6@testu.edu">Email</a></div>')
    kept = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    out, entry = _retire([kept], extra=extra)
    assert entry["retirement_authorized"] is True
    assert out["proposals"] == []
    assert out["records_preserved_still_listed"] == 1
    assert kept["metadata"]["is_active"] is True


def test_a_surname_only_inside_the_address_is_not_the_card_showing_it():
    extra = '<div class="card"><h3>Robin Example</h3><p>gone@testu.edu</p></div>'
    gone = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="gone@testu.edu")
    out, _ = _retire([gone], extra=extra)
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000aaaa"]


def test_a_listed_row_is_the_card_for_its_own_address():
    # A feed row has no markup: its name is what its address stands beside.
    def read(listed):
        soup = BeautifulSoup(_page(ROWS), "html.parser")
        fg._ACTIVE_COVERAGE = fg._new_coverage()
        try:
            specs = fg._parse_cards(soup, DEPT["scrape"]["selectors"], LISTING)
            for email, name in listed:
                fg._cover("raw_roster_rows")
                fg._cover("classified_nonfaculty_rows")
                fg._cover_listed(email, None, name)
            coverage = dict(fg._ACTIVE_COVERAGE)
        finally:
            fg._ACTIVE_COVERAGE = None
        return [r for s in specs if (r := fg._normalize(SCHOOL, DEPT, s))], coverage

    produced, coverage = read([("person9@testu.edu", "Example, Robin"),
                               ("person6@testu.edu", "Sample, Kimberly")])
    other = _stored("faculty-testu-anth-0000aaaa", "Henry Gone", email="person9@testu.edu")
    same = _stored("faculty-testu-anth-0000ac02", "Kim Sample", email="person6@testu.edu")
    corpus = [copy.deepcopy(r) for r in produced] + [other, same]
    ledger = {"anth": fg._unit_observation(SCHOOL, DEPT, produced, STARTED, coverage=coverage,
                                           listing_urls=fg._listing_urls(SCHOOL))}
    finalize_unit_ledger(ledger, corpus, "testu_faculty")
    out = deactivate_stale_faculty(corpus, {"testu_faculty": ledger}, today=TODAY)
    assert ledger["anth"]["retirement_authorized"] is True
    assert [p["entity_id"] for p in out["proposals"]] == ["faculty-testu-anth-0000aaaa"]
    assert same["metadata"]["is_active"] is True
    assert "person6@testu.edu" not in str(ledger) and "sample" not in str(ledger)


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


def _unit_tr(name, title="Professor", email=None):
    mail = f'<a href="mailto:{email}">{email}</a>' if email else ""
    return (f'<tr><td class="name">{name}</td><td class="title">{title}</td>'
            f'<td class="email">{mail}</td></tr>')


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


# A list-page row whose own unit, read in full, no longer shows the person
# while another unit of the school reads them is archived under that unit's
# row once the grace window has passed, and keeps its id (M178).
UNIT_C = _unit("CCC", "https://www.testu.edu/ccc/people")
MAIL = "person4@testu.edu"


def _in_unit_a(name, email=None, last_seen=LONG_AGO):
    return {"id": "faculty-testu-aaa-0000aaaa", "source": "testu_faculty",
            "source_type": "faculty_research", "school": "testu",
            "department": UNIT_A["name"], "pi_name": name,
            "url": UNIT_A["scrape"]["url"], "contact_email": email,
            "keywords": ["optics"],
            "metadata": {"is_active": True, "last_seen_at": last_seen}}


def _run_units(reads, stored, *, ladder=None, **options):
    """Read each ``(unit, rows)`` page, store what was read beside ``stored``,
    and run the retirement pass. Returns its counts and the corpus."""
    school = {**TWO_SCHOOL, "departments": [dept for dept, _ in reads]}
    listing = fg._listing_urls(school)
    corpus, ledger = [], {}
    for dept, rows in reads:
        produced, cov = _unit_read(dept, rows, ladder)
        corpus += [copy.deepcopy(r) for r in produced]
        ledger[dept["short"].lower()] = fg._unit_observation(
            school, dept, produced, STARTED, coverage=cov, listing_urls=listing)
    corpus += stored
    finalize_unit_ledger(ledger, corpus, "testu_faculty")
    assert all(entry["retirement_authorized"] is True for entry in ledger.values())
    return deactivate_stale_faculty(
        corpus, {"testu_faculty": ledger}, today=TODAY, **options), corpus


def _kept_as_moved(out, *rows):
    assert out["archived_moved"] == [] and out["records_archived_moved_unit"] == 0
    assert [m["entity_id"] for m in out["moved"]] == [r["id"] for r in rows]
    assert out["newly_deactivated"] == 0 and out["would_deactivate"] == []
    for r in rows:
        assert r["metadata"] == {"is_active": True, "last_seen_at": r["metadata"]["last_seen_at"]}


@pytest.mark.parametrize("email", [None, MAIL], ids=["no address", "address"])
def test_a_person_only_another_unit_lists_is_archived_under_that_units_row(email):
    old = _in_unit_a("Kim Sample", email)
    out, corpus = _run_units(
        [(UNIT_A, [_unit_tr("Robin Example")]),
         (UNIT_B, [_unit_tr("Pat Example"), _unit_tr("Kim Sample", email=email)])], [old])
    new = next(r for r in corpus if r["pi_name"] == "Kim Sample" and r is not old)
    assert new["id"].startswith("faculty-testu-bbb-") and new["department"] == UNIT_B["name"]
    assert out["archived_moved"] == [{
        "entity_id": old["id"], "duplicate_of": new["id"],
        "from_unit": "aaa", "to_unit": "bbb", "school": "testu"}]
    assert out["records_archived_moved_unit"] == 1
    assert out["records_preserved_moved_unit"] == 0 and out["moved"] == []
    assert out["newly_deactivated"] == 0 and out["would_deactivate"] == []
    assert old["metadata"] == {
        "is_active": False, "last_seen_at": LONG_AGO,
        "deactivated_at": TODAY.isoformat(),
        "deactivation_reason": fg.DUPLICATE_REASON, "duplicate_of": new["id"]}
    # The run's collapse then keeps both: the old id for whoever saved it, the
    # person live under the unit that lists them.
    kept = fg.collapse_same_person_faculty(
        corpus, published_ids=frozenset({old["id"]}), today=TODAY)["kept"]
    assert {r["id"]: (r["metadata"]["is_active"], r["metadata"].get("duplicate_of"))
            for r in kept if r["pi_name"] == "Kim Sample"} == {
        old["id"]: (False, new["id"]), new["id"]: (True, None)}


def test_a_moved_person_inside_the_grace_window_is_kept_as_moved():
    recent = (TODAY - timedelta(days=GRACE_DAYS)).isoformat()
    old = _in_unit_a("Kim Sample", MAIL, last_seen=recent)
    out, _ = _run_units(
        [(UNIT_A, [_unit_tr("Robin Example")]),
         (UNIT_B, [_unit_tr("Kim Sample", email=MAIL)])], [old])
    _kept_as_moved(out, old)


@pytest.mark.parametrize("still_shown", [
    _unit_tr("Kim Sample", "Professor Emerita"),
    _unit_tr("Robin Sample", "Professor Emerita", MAIL)],
    ids=["name", "address beside the surname"])
def test_a_moved_person_their_own_page_still_shows_is_kept_as_moved(still_shown):
    # Their own unit's page lists them under a title its gate skips.
    old = _in_unit_a("Kim Sample", MAIL)
    out, _ = _run_units(
        [(UNIT_A, [_unit_tr("Robin Example"), still_shown]),
         (UNIT_B, [_unit_tr("Kim Sample", email=MAIL)])], [old], ladder={"drop": "emerit"})
    _kept_as_moved(out, old)


def test_a_moved_person_two_other_units_list_is_kept_as_moved():
    old = _in_unit_a("Kim Sample")
    out, _ = _run_units(
        [(UNIT_A, [_unit_tr("Robin Example")]), (UNIT_B, [_unit_tr("Kim Sample")]),
         (UNIT_C, [_unit_tr("Kim Sample")])], [old])
    _kept_as_moved(out, old)


def test_a_moved_person_is_archived_only_under_a_row_of_a_unit_that_read_them():
    # The unit that read them left the row to another (read, not emitted). A
    # third unit holds a row for them and no longer lists them either.
    old = _in_unit_a("Kim Sample", MAIL)
    unread = {**_in_unit_a("Kim Sample", MAIL), "id": "faculty-testu-ccc-0000cccc",
              "department": UNIT_C["name"], "url": UNIT_C["scrape"]["url"]}
    school = {**TWO_SCHOOL, "departments": [UNIT_A, UNIT_B, UNIT_C]}
    listing = fg._listing_urls(school)
    a_rows, a_cov = _unit_read(UNIT_A, [_unit_tr("Robin Example")])
    b_rows, b_cov = _unit_read(UNIT_B, [_unit_tr("Pat Example"),
                                        _unit_tr("Kim Sample", email=MAIL)])
    c_rows, c_cov = _unit_read(UNIT_C, [_unit_tr("Lee Example")])
    corpus = [copy.deepcopy(r) for r in a_rows + b_rows[:1] + c_rows] + [old, unread]
    ledger = {"aaa": fg._unit_observation(school, UNIT_A, a_rows, STARTED, coverage=a_cov,
                                          listing_urls=listing),
              "bbb": fg._unit_observation(school, UNIT_B, b_rows[:1], STARTED, coverage=b_cov,
                                          listing_urls=listing, read_not_emitted=b_rows[1:]),
              "ccc": fg._unit_observation(school, UNIT_C, c_rows, STARTED, coverage=c_cov,
                                          listing_urls=listing)}
    finalize_unit_ledger(ledger, corpus, "testu_faculty")
    out = deactivate_stale_faculty(corpus, {"testu_faculty": ledger}, today=TODAY)
    assert all(entry["retirement_authorized"] is True for entry in ledger.values())
    assert identity_key(old, listing) == identity_key(unread, listing)
    _kept_as_moved(out, old, unread)


@pytest.mark.parametrize("options", [{"dry_run": True}, {"held_sources": {"testu_faculty"}}],
                         ids=["dry run", "held source"])
def test_a_dry_run_or_a_held_source_reports_the_archive_and_writes_nothing(options):
    old = _in_unit_a("Kim Sample", MAIL)
    out, corpus = _run_units(
        [(UNIT_A, [_unit_tr("Robin Example")]),
         (UNIT_B, [_unit_tr("Kim Sample", email=MAIL)])], [old], **options)
    new = next(r for r in corpus if r["pi_name"] == "Kim Sample" and r is not old)
    assert [(m["entity_id"], m["duplicate_of"]) for m in out["archived_moved"]] == [
        (old["id"], new["id"])]
    assert out["would_deactivate"] == [old["id"]]
    assert out["records_archived_moved_unit"] == 0 and out["moved"] == []
    assert old["metadata"] == {"is_active": True, "last_seen_at": LONG_AGO}


def test_a_moved_person_with_a_profile_page_is_kept_as_moved():
    # Not a list-page row: the profile link is the identity, and no page check
    # covers it. Another unit holds and read a row on the same profile page.
    profile = "https://www.testu.edu/people/kim-sample"
    old = {**_in_unit_a("Kim Sample"), "url": profile}
    other = {**_in_unit_a("Kim Sample"), "id": "faculty-testu-bbb-0000bbbb",
             "department": UNIT_B["name"], "url": profile,
             "metadata": {"is_active": True, "last_seen_at": TODAY.isoformat()}}
    school = {**TWO_SCHOOL, "departments": [UNIT_A, UNIT_B]}
    listing = fg._listing_urls(school)
    a_rows, a_cov = _unit_read(UNIT_A, [_unit_tr("Robin Example")])
    b_rows, b_cov = _unit_read(UNIT_B, [_unit_tr("Pat Example")])
    corpus = [copy.deepcopy(r) for r in a_rows + b_rows] + [old, other]
    ledger = {"aaa": fg._unit_observation(school, UNIT_A, a_rows, STARTED, coverage=a_cov,
                                          listing_urls=listing),
              "bbb": fg._unit_observation(school, UNIT_B, b_rows, STARTED, coverage=b_cov,
                                          listing_urls=listing)}
    ledger["bbb"]["observed_identities"].append(list(identity_key(other, listing)))
    ledger["bbb"]["observed_entity_ids"].append(other["id"])
    finalize_unit_ledger(ledger, corpus, "testu_faculty")
    out = deactivate_stale_faculty(corpus, {"testu_faculty": ledger}, today=TODAY)
    assert identity_key(old, listing)[0] == "url"
    assert ledger["aaa"]["retirement_authorized"] is True
    _kept_as_moved(out, old)
