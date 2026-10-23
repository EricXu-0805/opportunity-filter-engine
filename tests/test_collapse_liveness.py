"""A same-person collapse keeps the richer row, and that row takes the newest
sighting when the sighting is its own (M140).

Every pass that folds one person's rows into one picks the survivor for its
research keywords, then its longer name. A row stored under a spelling the
page no longer writes ("Ana Belmonte, Ph.D., P.E.") wins that contest against
the row this run read ("Ana Belmonte"), so the person kept the old row's
``last_seen_at`` after every refresh and read as stale. The uiuc dedups
already carry the newest sighting onto the survivor (#815); these pin the same
rule on every other path, without changing which row survives.

Only a sighting of the survivor's own listing moves: a row of its own scrape
unit under the same person's name, or a row on a profile page the refresh
observed as one person's identity. deactivate_stale_faculty runs before the
collapse, so a sighting carried every week from another department, through a
school directory page, or from a colleague on a shared inbox would keep a row
its own department dropped inside the grace window for ever.

A test whose docstring starts with "Guard" holds on every version of this
code; every other test fails without the rule it names.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from src.collectors import faculty_graph as fg
from src.collectors.ucb_common import (
    collapse_ucb_joint_appointments,
    drop_joint_appointment_duplicates,
)
from src.normalizers.deactivate_stale_faculty import (
    canonical_profile_url,
    deactivate_stale_faculty,
    identity_key,
    observed_profile_pages,
)

OLD = "2026-07-18T07:02:23.799409"
MID = "2026-09-12T08:15:00.000000"
NEW = "2026-10-17T11:30:39.500947"
RETIRED = {"is_active": False, "deactivated_at": "2026-08-10",
           "deactivation_reason": "absent_from_directory_rescrape"}


def _row(rid, name, *, school="testu", dept="Department of Testing", url="",
         email=None, keywords=(), seen=NEW, source=None, **meta):
    return {
        "id": rid, "source": source or f"{school}_faculty",
        "source_type": "faculty_research", "school": school,
        "department": dept, "pi_name": name, "url": url,
        "contact_email": email, "keywords": list(keywords),
        "metadata": {"is_active": True, "last_seen_at": seen, **meta},
    }


def _pairs():
    """(pass, stored stale row that wins on richness, fresh row it absorbs,
    profile pages the refresh observed, whether the fresh row's sighting is
    the stale row's own)."""
    for label, pages, own in (
            ("url_and_name", frozenset({"testu.edu/users/ana-belmonte"}), True),
            ("url_and_name_unobserved", frozenset(), False)):
        # One profile page linked from two departments' directories, one of
        # them writing it in capitals with a trailing slash. It is the
        # person's page across units only when the refresh observed it so.
        yield (label,
               _row("faculty-testu-cee-0000aaaa", "Ana Belmonte, Ph.D., P.E.",
                    dept="Department of Civil Engineering",
                    url="https://www.testu.edu/users/Ana-Belmonte/",
                    keywords=["hydrology", "climate extremes"], seen=OLD),
               _row("faculty-testu-ess-0000bbbb", "Ana Belmonte",
                    dept="Department of Earth System Science",
                    url="https://www.testu.edu/users/ana-belmonte", seen=NEW),
               pages, own)
    # One unit whose page moved the profile link to another host.
    yield ("syndicated_slug",
           _row("faculty-testu-ee-0000aaaa", "Jo Smith", url="https://cms.testu.edu/people/jsmith",
                keywords=["optics", "lasers"], seen=OLD),
           _row("faculty-testu-ee-0000bbbb", "Jo Smith", url="https://ee.testu.edu/people/jsmith",
                keywords=["optics"], seen=NEW),
           frozenset(), True)
    # One unit's rows on its own directory page, the stored name in HTML entities.
    listing = "https://www.testu.edu/faculty-directory.php"
    yield ("same_email",
           _row("faculty-testu-chem-0000aaaa", "Jos&eacute; Ib&aacute;&ntilde;ez", url=listing,
                email="person1@testu.edu", seen=OLD),
           _row("faculty-testu-chem-0000bbbb", "José Ibáñez", url=listing,
                email="person1@testu.edu", seen=NEW),
           frozenset(), True)
    # One unit whose page now adds a degree the stored name lacks.
    yield ("degree_suffix",
           _row("faculty-testu-nurs-0000aaaa", "Dana Ellis", email="person5@testu.edu",
                url="https://nurs.testu.edu/people/dana-ellis", keywords=["palliative care"],
                seen=OLD),
           _row("faculty-testu-nurs-0000bbbb", "Dana Ellis DNP", email="person5@testu.edu",
                url="https://nurs.testu.edu/people/dana-ellis-dnp", seen=NEW),
           frozenset(), True)
    # Another department's listing, on another page.
    yield ("cross_unit_email",
           _row("faculty-testu-math-0000aaaa", "Pat Q. Smith", dept="Department of Mathematics",
                url="https://math.testu.edu/people/psmith", email="person4@testu.edu",
                keywords=["topology", "geometry"], seen=OLD),
           _row("faculty-testu-stat-0000bbbb", "Pat Smith", dept="Department of Statistics",
                url="https://stat.testu.edu/people/pat-smith", email="person4@testu.edu",
                seen=NEW),
           frozenset(), False)
    # One collector's two units that print one department name.
    yield ("same_label_other_unit",
           _row("faculty-testu-cs-0000aaaa", "Pat Q. Smith", dept="Computer Science",
                url="https://cs.testu.edu/people/psmith", email="person4@testu.edu",
                keywords=["compilers", "verification"], seen=OLD),
           _row("faculty-testu-csaff-0000bbbb", "Pat Smith", dept="Computer Science",
                url="https://affiliates.testu.edu/people/pat-smith", email="person4@testu.edu",
                seen=NEW),
           frozenset(), False)
    yield ("medical_seed",
           _row("faculty-jhu-bme-0000aaaa", "Pat Lee", school="jhu",
                dept="Department of Biomedical Engineering",
                url="https://bme.testu.edu/pat-lee", seen=OLD),
           _row("faculty-jhu-som-bme-0000bbbb", "Pat Lee", school="jhu",
                dept="School of Medicine — Biomedical Engineering",
                url="https://som.testu.edu/pat-lee", seen=NEW),
           frozenset(), False)
    yield ("umbrella",
           _row("faculty-gatech-ic-0000aaaa", "Kim Park", school="gatech",
                dept="School of Interactive Computing",
                url="https://ic.testu.edu/kim-park", seen=OLD),
           _row("faculty-gatech-coc-0000bbbb", "Kim Park", school="gatech",
                dept="College of Computing", url="https://cc.testu.edu/kim-park", seen=NEW),
           frozenset(), False)
    # One unit's office inbox on two colleagues who share a first name: the
    # email pass folds them, but one person's listing is not the other's.
    yield ("shared_inbox_first_name",
           _row("faculty-testu-math-0000aaaa", "John Smith", dept="Department of Mathematics",
                url="https://math.testu.edu/people/jsmith", email="office@math.testu.edu",
                keywords=["topology", "geometry"], seen=OLD),
           _row("faculty-testu-math-0000bbbb", "John Doe", dept="Department of Mathematics",
                url="https://math.testu.edu/people/jdoe", email="office@math.testu.edu",
                seen=NEW),
           frozenset(), False)


@pytest.mark.parametrize("label,stale,fresh,pages,own", list(_pairs()),
                         ids=[p[0] for p in _pairs()])
def test_the_kept_row_takes_only_its_own_fresher_sighting(label, stale, fresh, pages, own):
    sid, name = stale["id"], stale["pi_name"]
    out = fg.collapse_same_person_faculty([stale, fresh], person_pages=pages)
    # Which row survives, its id and its name are unchanged.
    assert [o["id"] for o in out["kept"]] == [sid]
    kept = out["kept"][0]
    assert kept["pi_name"] == name
    assert kept["metadata"]["last_seen_at"] == (NEW if own else OLD)
    assert kept["metadata"]["is_active"] is True


def test_the_kept_row_is_never_backdated():
    """Guard: an older dropped row leaves the kept row's date alone."""
    profile = "https://www.testu.edu/users/ana-belmonte"
    kept = _row("faculty-testu-cee-0000aaaa", "Ana Belmonte, Ph.D., P.E.", url=profile,
                keywords=["hydrology", "climate extremes"], seen=NEW)
    older = _row("faculty-testu-cee-0000bbbb", "Ana Belmonte", url=profile, seen=OLD)
    out = fg.collapse_same_person_faculty([kept, older])
    assert [o["id"] for o in out["kept"]] == ["faculty-testu-cee-0000aaaa"]
    assert kept["metadata"]["last_seen_at"] == NEW


def test_a_retired_row_listed_again_in_its_unit_comes_back():
    """The #815 rule in full: a row of the kept row's own unit listed after
    the kept row was retired disproves the retirement. No collapse pass keeps
    a retired row beside a listed one today, so this pins the merge itself."""
    profile = "https://www.testu.edu/users/lee-chen"
    survivor = _row("faculty-testu-test-0000aaaa", "Lee Chen", url=profile, seen=OLD, **RETIRED)
    listed = _row("faculty-testu-test-0000bbbb", "Lee Chen", url=profile, seen=NEW)
    fg._merge_faculty_fields(survivor, listed)
    meta = survivor["metadata"]
    assert (meta["last_seen_at"], meta["is_active"]) == (NEW, True)
    assert "deactivated_at" not in meta and "deactivation_reason" not in meta


_COVERAGE = {"raw_roster_rows": 2, "parsed_faculty_rows": 2, "classified_nonfaculty_rows": 0,
             "unparsed_rows": 0, "ambiguous_rows": 0, "parser_errors": 0,
             "partial_render_rows": 0, "duplicate_rows": 0, "identity_match_failures": 0}


def _read(unit, rows, day, directory=None):
    """An authorised, complete read of one unit that listed ``rows``. A row
    whose link is the unit's directory page is recorded by its address, as an
    identity a directory page cannot be."""
    unit_url = directory or f"https://{unit}.testu.edu/people/"
    listing = {canonical_profile_url(unit_url)}
    return {"unit_id": unit, "fetch_status": "ok", "parse_status": "ok",
            "validation_status": "ok", "roster_source_confirmed": True,
            "coverage": dict(_COVERAGE), "retirement_authorized": True,
            "observed_entity_ids": [r["id"] for r in rows],
            "observed_identities": [list(identity_key(r, listing)) for r in rows],
            "school": "testu", "source": "testu_faculty",
            "started_at": f"{day.isoformat()}T09:00:00+00:00", "unit_url": unit_url}


def _at(day):
    return f"{day.isoformat()}T10:00:00"


def _upsert(corpus, emitted):
    """The id-keyed merge: a stored id takes the fresh row's metadata."""
    by_id = {o["id"]: o for o in corpus}
    for row in emitted:
        if row["id"] in by_id:
            by_id[row["id"]]["metadata"] = copy.deepcopy(row["metadata"])
        else:
            corpus.append(copy.deepcopy(row))


def _refresh(corpus, ledger, day):
    """One weekly refresh after the merge, in the refresh_all order: retire,
    then collapse with the profile pages the run observed."""
    fetched = {"testu_faculty": ledger}
    deactivate_stale_faculty(corpus, fetched, today=day)
    return fg.collapse_same_person_faculty(
        corpus, person_pages=observed_profile_pages(fetched))["kept"]


@pytest.mark.parametrize("shared", [False, True], ids=["own_pages", "school_directory_page"])
def test_a_row_its_own_department_dropped_still_retires(shared):
    """Mathematics stops listing a cross-listed professor after the first week;
    Statistics keeps listing them under the same address, on its own page or
    on the school directory page both departments' rows link. The Mathematics
    row wins the collapse on richness, so if it took the Statistics sighting it
    would never leave the grace window, showing a department no page states any
    more. It retires after the grace and the Statistics row is shown."""
    start = date(2026, 9, 1)
    directory = "https://www.testu.edu/people/faculty-directory/" if shared else None
    math = _row("faculty-testu-math-0000aaaa", "Pat Q. Smith", dept="Department of Mathematics",
                url=directory or "https://math.testu.edu/people/psmith",
                email="person4@testu.edu", keywords=["topology", "geometry"], seen=_at(start))
    stat = _row("faculty-testu-stat-0000bbbb", "Pat Smith", dept="Department of Statistics",
                url=directory or "https://stat.testu.edu/people/pat-smith",
                email="person4@testu.edu")
    other = _row("faculty-testu-math-0000cccc", "Lee Chen", dept="Department of Mathematics",
                 url="https://math.testu.edu/people/lchen", email="person3@testu.edu")
    corpus = [math, other]
    for week in range(5):
        day = start + timedelta(days=7 * week)
        listed_math = [other] + ([math] if week == 0 else [])
        for row in listed_math:
            row["metadata"]["last_seen_at"] = _at(day)
        emitted = copy.deepcopy(stat)
        emitted["metadata"]["last_seen_at"] = _at(day)
        _upsert(corpus, [emitted])
        corpus = _refresh(corpus, {"math": _read("math", listed_math, day, directory),
                                   "stat": _read("stat", [emitted], day, directory)}, day)
        shown = [(o["id"], o["metadata"]["last_seen_at"], o["metadata"]["is_active"])
                 for o in corpus if o["contact_email"] == "person4@testu.edu"]
        if week < 3:
            # Inside the grace: the richer row survives, with its own date.
            assert shown == [(math["id"], _at(start), True)]
    assert shown == [(stat["id"], _at(day), True)]


@pytest.mark.parametrize("left_name,listed_name", [
    ("John Smith", "John Doe"),            # a shared first name
    ("Mei Tanaka", "Ren Tanaka"),          # a shared surname
    ("R. Tanaka", "Mei Tanaka"),           # an initial and a shared surname
    ("Ana Ruiz Vega", "Ana Ruiz Soto"),    # two shared words, neither name inside the other
], ids=["first_name", "surname", "initial_and_surname", "two_shared_words"])
def test_a_colleague_on_a_shared_inbox_does_not_keep_a_departed_row(left_name, listed_name):
    """One department's office inbox sits on two colleagues who share a name
    word, so the collapse folds the listed one into the departed, richer one.
    The listed colleague's sighting is not the departed one's: the departed row
    retires after the grace and the listed colleague is shown."""
    start = date(2026, 9, 1)
    inbox = "office@math.testu.edu"
    left = _row("faculty-testu-math-0000aaaa", left_name, dept="Department of Mathematics",
                url="https://math.testu.edu/people/jsmith", email=inbox,
                keywords=["topology", "geometry"], seen=_at(start))
    listed = _row("faculty-testu-math-0000bbbb", listed_name, dept="Department of Mathematics",
                  url="https://math.testu.edu/people/jdoe", email=inbox)
    corpus = [left]
    for week in range(5):
        day = start + timedelta(days=7 * week)
        if week == 0:
            left["metadata"]["last_seen_at"] = _at(day)
        emitted = copy.deepcopy(listed)
        emitted["metadata"]["last_seen_at"] = _at(day)
        _upsert(corpus, [emitted])
        read = [emitted] + ([left] if week == 0 else [])
        corpus = _refresh(corpus, {"math": _read("math", read, day)}, day)
        shown = [(o["pi_name"], o["metadata"]["last_seen_at"], o["metadata"]["is_active"])
                 for o in corpus if o["contact_email"] == inbox]
        if week < 3:
            assert shown == [(left_name, _at(start), True)]
    assert shown == [(listed_name, _at(day), True)]


def test_a_unit_directory_page_is_nobodys_profile_page():
    """A linkless card links its unit's directory page, and a refresh can
    record that page among the unit's identities. Two departments sharing one
    school directory page then give one person two rows on it; the page does
    not say which department lists them, so no date crosses between them."""
    directory = "https://www.testu.edu/people/faculty-directory/"
    day = date(2026, 10, 17)
    math = _row("faculty-testu-math-0000aaaa", "Pat Q. Smith", dept="Department of Mathematics",
                url=directory, email="person4@testu.edu", keywords=["topology", "geometry"],
                seen=OLD)
    stat = _row("faculty-testu-stat-0000bbbb", "Pat Smith", dept="Department of Statistics",
                url=directory, email="person4@testu.edu", seen=NEW)
    recorded = {}
    for unit, row in (("math", math), ("stat", stat)):
        recorded[unit] = _read(unit, [row], day, directory)
        recorded[unit]["observed_identities"] = [list(identity_key(row))]
    assert ["url", "testu.edu/people/faculty-directory"] in recorded["stat"]["observed_identities"]
    pages = observed_profile_pages({"testu_faculty": recorded})
    out = fg.collapse_same_person_faculty([math, stat], person_pages=pages)
    assert [o["id"] for o in out["kept"]] == [math["id"]]
    assert math["metadata"]["last_seen_at"] == OLD


def test_a_page_several_people_link_is_nobodys_profile_page():
    """A profile script that keeps the person in its query reduces to one page
    for every person it serves, and the refresh observes that page. Rows of
    several people on it make it no one's profile, so the date stays put."""
    script = "https://www.testu.edu/people/profile.html?id="
    math = _row("faculty-testu-math-0000aaaa", "Pat Q. Smith", dept="Department of Mathematics",
                url=script + "17", keywords=["topology", "geometry"], seen=OLD)
    stat = _row("faculty-testu-stat-0000bbbb", "Pat Smith", dept="Department of Statistics",
                url=script + "17", seen=NEW)
    others = [_row("faculty-testu-math-0000cccc", "Lee Chen", dept="Department of Mathematics",
                   url=script + "18", seen=NEW),
              _row("faculty-testu-stat-0000dddd", "Kim Park", dept="Department of Statistics",
                   url=script + "19", seen=NEW)]
    page = canonical_profile_url(script + "17")
    out = fg.collapse_same_person_faculty([math, stat, *others],
                                          person_pages=frozenset({page}))
    assert math["id"] in [o["id"] for o in out["kept"]]
    assert stat["id"] not in [o["id"] for o in out["kept"]]
    assert math["metadata"]["last_seen_at"] == OLD


def test_ucb_collapse_keeps_the_listed_row_over_a_retired_richer_one():
    """collapse_ucb_joint_appointments also folds retired rows. The richer row
    retired from its own department used to win, so the person was not shown
    although another department's page listed them this run."""
    retired = _row("faculty-ucb-me-0000aaaa", "Toni M. Varga", school="ucb",
                   source="ucb_me_faculty", dept="Mechanical Engineering",
                   keywords=["biomechanics", "bone"], seen=OLD, **RETIRED)
    listed = _row("faculty-ucb-bioe-0000bbbb", "Toni Varga", school="ucb",
                  source="ucb_bioe_faculty", dept="Bioengineering", seen=NEW)
    out = collapse_ucb_joint_appointments([retired, listed])
    assert [o["id"] for o in out["kept"]] == ["faculty-ucb-bioe-0000bbbb"]
    assert listed["pi_name"] == "Toni Varga"
    assert listed["metadata"]["is_active"] is True
    assert listed["metadata"]["last_seen_at"] == NEW
    # The retired row is not brought back by the fold either.
    assert retired["metadata"]["is_active"] is False


def test_ucb_collapse_of_retired_rows_takes_only_its_own_departments_sighting():
    """With no listed row the richer retired row survives the fold, still
    retired. It takes the sighting of its own department's row under another
    spelling, not another department's, even when all three link one profile
    page: a Berkeley department retires a row by its date alone."""
    page = "https://research.testu.edu/faculty/toni-varga"
    survivor = _row("faculty-ucb-me-0000aaaa", "Toni M. Varga", school="ucb",
                    source="ucb_me_faculty", dept="Mechanical Engineering", url=page,
                    keywords=["biomechanics", "bone"], seen=OLD, **RETIRED)
    renamed = _row("faculty-ucb-me-0000bbbb", "Toni Varga", school="ucb", url=page,
                   source="ucb_me_faculty", dept="Mechanical Engineering", seen=MID, **RETIRED)
    other = _row("faculty-ucb-bioe-0000cccc", "Toni Varga", school="ucb", url=page,
                 source="ucb_bioe_faculty", dept="Bioengineering", seen=NEW, **RETIRED)
    out = collapse_ucb_joint_appointments([survivor, renamed, other])
    assert [o["id"] for o in out["kept"]] == ["faculty-ucb-me-0000aaaa"]
    meta = survivor["metadata"]
    assert meta["last_seen_at"] == MID
    assert meta["is_active"] is False
    assert meta["deactivated_at"] == RETIRED["deactivated_at"]


def test_ucb_merge_keeps_a_department_that_lists_the_person():
    """drop_joint_appointment_duplicates kept this run's row out whenever
    another ucb source had stored the person, even as a retired row: the
    person then disappeared for good."""
    stored = _row("faculty-ucb-eecs-0000aaaa", "Robin Hale", school="ucb",
                  source="ucb_eecs_faculty", email="person2@testu.edu",
                  seen=OLD, **RETIRED)
    incoming = _row("faculty-ucb-stat-0000bbbb", "Robin Hale", school="ucb",
                    source="ucb_stat_faculty", email="person2@testu.edu", seen=NEW)
    kept, dropped = drop_joint_appointment_duplicates([incoming], [stored])
    assert (kept, dropped) == ([incoming], 0)
    assert stored["metadata"]["is_active"] is False
    assert stored["metadata"]["last_seen_at"] == OLD


@pytest.mark.parametrize("stat_url", [
    "https://www.testu.edu/people/robin-hale",
    "https://statistics.testu.edu/people/robin-hale",
], ids=["same_profile_page", "own_department_page"])
def test_ucb_merge_leaves_the_stored_row_its_own_date(stat_url):
    """The stored row of another ucb source stays and this run's row is
    dropped. The stored row keeps its own date, even on the same profile page:
    its department retires it by that date alone."""
    stored = _row("faculty-ucb-eecs-0000aaaa", "Robin Hale", school="ucb",
                  source="ucb_eecs_faculty", email="person2@testu.edu",
                  url="https://www.testu.edu/people/robin-hale", seen=OLD)
    incoming = _row("faculty-ucb-stat-0000bbbb", "Robin Hale", school="ucb",
                    source="ucb_stat_faculty", email="person2@testu.edu",
                    url=stat_url, seen=NEW)
    kept, dropped = drop_joint_appointment_duplicates([incoming], [stored])
    assert (kept, dropped) == ([], 1)
    assert stored["metadata"]["last_seen_at"] == OLD
    assert stored["metadata"]["is_active"] is True


def test_a_berkeley_row_its_department_dropped_gives_way_to_the_listing_one():
    """EECS stops listing a jointly appointed professor after the first week;
    Statistics keeps listing them on the same profile page. Each weekly refresh
    merges EECS, then Statistics (another department's stored row wins), then
    retires each department's rows by count and date and folds the rest. The
    EECS row retires after the grace and the Statistics row is shown."""
    start = date(2026, 9, 1)
    profile = "https://www.testu.edu/people/robin-hale"
    eecs_dept = "Electrical Engineering and Computer Sciences"

    def ucb_row(rid, name, source, dept, day):
        return _row(rid, name, school="ucb", source=source, dept=dept, url=profile,
                    email="person2@testu.edu", seen=_at(day))

    staff = [_row(f"faculty-ucb-eecs-{i:08x}", f"Eecs Member {chr(97 + i)}{chr(97 + i)}",
                  school="ucb", source="ucb_eecs_faculty", dept=eecs_dept,
                  url=f"https://www.testu.edu/people/member-{i}") for i in range(19)]
    person = ucb_row("faculty-ucb-eecs-0000aaaa", "Robin Hale", "ucb_eecs_faculty",
                     eecs_dept, start)
    person["keywords"] = ["statistical learning", "causal inference"]
    corpus = [*staff, person]
    for week in range(5):
        day = start + timedelta(days=7 * week)
        eecs = copy.deepcopy(staff + ([person] if week == 0 else []))
        for row in eecs:
            row["metadata"]["last_seen_at"] = _at(day)
        _upsert(corpus, eecs)
        stat = [ucb_row("faculty-ucb-stat-0000bbbb", "Robin Hale", "ucb_stat_faculty",
                        "Statistics", day)]
        stat, _ = drop_joint_appointment_duplicates(stat, corpus)
        _upsert(corpus, stat)
        deactivate_stale_faculty(corpus, {"ucb_eecs_faculty": len(eecs),
                                          "ucb_stat_faculty": 1}, today=day)
        corpus = collapse_ucb_joint_appointments(corpus)["kept"]
        shown = [(o["id"], o["metadata"]["last_seen_at"]) for o in corpus
                 if o["pi_name"] == "Robin Hale" and o["metadata"]["is_active"]]
        if week < 3:
            assert shown == [(person["id"], _at(start))]
    assert shown == [("faculty-ucb-stat-0000bbbb", _at(day))]


def test_a_dropped_tombstone_leaves_its_sighting_but_not_its_retirement():
    live = _row("faculty-testu-test-0000aaaa", "Lee Chen", email="person3@testu.edu", seen=OLD)
    tomb = _row("faculty-testu-test-0000bbbb", "Lee Chen", email="person3@testu.edu",
                seen=NEW, **RETIRED)
    out = fg.collapse_same_person_faculty([live, tomb])
    assert [o["id"] for o in out["kept"]] == ["faculty-testu-test-0000aaaa"]
    assert live["metadata"]["last_seen_at"] == NEW
    assert live["metadata"]["is_active"] is True
    assert "deactivated_at" not in live["metadata"]


@pytest.mark.parametrize("other", ["Sam Ortiz", "Lee Ortiz"],
                         ids=["other_name", "shared_first_name"])
def test_a_tombstone_on_a_shared_inbox_leaves_another_person_alone(other):
    live = _row("faculty-testu-test-0000aaaa", "Lee Chen", email="person3@testu.edu", seen=OLD)
    tomb = _row("faculty-testu-test-0000bbbb", other, email="person3@testu.edu",
                seen=NEW, **RETIRED)
    out = fg.collapse_same_person_faculty([live, tomb])
    # The tombstone still goes (the gate counts it on the address); its date stays.
    assert [o["id"] for o in out["kept"]] == ["faculty-testu-test-0000aaaa"]
    assert live["metadata"]["last_seen_at"] == OLD


def test_a_berkeley_name_variant_its_richer_department_dropped_gives_way():
    """BioE writes "Toni Varga", ME "Toni M. Varga", one profile page and no
    address at merge time, so ME's row is merged every week and the Berkeley
    collapse folds the two. BioE stops listing the person after week 0: its
    row retires after the grace and ME's row is shown."""
    start = date(2026, 9, 1)
    page = "https://research.testu.edu/faculty/toni-varga"

    def ucb(rid, name, source, dept, day, url, keywords=()):
        return _row(rid, name, school="ucb", source=source, dept=dept, url=url,
                    keywords=keywords, seen=_at(day))

    staff = [ucb(f"faculty-ucb-bioe-{i:08x}", f"Bioe Member {chr(97 + i)}{chr(97 + i)}",
                 "ucb_bioe_faculty", "Bioengineering", start,
                 f"https://bioe.testu.edu/people/member-{i}") for i in range(19)]
    person = ucb("faculty-ucb-bioe-0000aaaa", "Toni Varga", "ucb_bioe_faculty", "Bioengineering",
                 start, page, ["biomechanics", "bone"])
    corpus = copy.deepcopy(staff) + [copy.deepcopy(person)]
    for week in range(5):
        day = start + timedelta(days=7 * week)
        bioe = copy.deepcopy(staff + ([person] if week == 0 else []))
        for r in bioe:
            r["metadata"]["last_seen_at"] = _at(day)
        _upsert(corpus, bioe)
        me, _ = drop_joint_appointment_duplicates(
            [ucb("faculty-ucb-me-0000bbbb", "Toni M. Varga", "ucb_me_faculty",
                 "Mechanical Engineering", day, page)], corpus)
        _upsert(corpus, me)
        deactivate_stale_faculty(corpus, {"ucb_bioe_faculty": len(bioe), "ucb_me_faculty": 1},
                                 today=day)
        corpus = collapse_ucb_joint_appointments(corpus)["kept"]
        shown = [(o["id"], o["metadata"]["last_seen_at"]) for o in corpus
                 if "Varga" in o["pi_name"] and o["metadata"]["is_active"]]
        if week < 3:
            assert shown == [(person["id"], _at(start))]
    assert shown == [("faculty-ucb-me-0000bbbb", _at(day))]
