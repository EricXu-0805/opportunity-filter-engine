"""Syracuse University faculty config (via the faculty_graph engine).

Four server-rendered source families, all plain static 200s through the proxy
(no WAF, no JS render needed anywhere). Live-verified 2026-07-24.

* **College of Arts & Sciences — ONE college-wide roster, split by heading.**
  ``artsandsciences.syracuse.edu/people/faculty/`` is the authoritative A&S
  faculty list: a single page of department-grouped ``<table>`` rows under
  ``<h2>`` section headings (18 sections, 400 rows, 99% carrying a plain
  ``mailto``). Each row is ``<td><a href="/people/faculty/<slug>/">Name</a></td>
  <td>Rank</td><td><a mailto></td>``, so ``section_filter`` on the ``h2`` is the
  per-department gate and one fetch serves every department. The page renders
  the same 18 sections TWICE (a ``profileindex__desktop`` block and a
  ``profileindex__mobile`` block); the card selector is scoped to the desktop
  container so every person is parsed once.

  This roster is already ladder-scoped by the college ("full-time assistant,
  associate and full professors, as well as associate and assistant teaching
  professors") — part-time faculty, emeriti and staff live on separate
  ``/people/<role>/`` pages and never appear here. The require-professor gate is
  belt-and-braces on top of that.

  It REPLACES the five per-department Wagtail ``personcontainer`` scrapes this
  config used to run (physics / chemistry / mathematics / biology / earth-
  sciences): the central page yields the same or more people for each of them
  (Biology 40 vs 38, Mathematics 29 vs 28, Physics/Chemistry/Earth identical) at
  100% listing-tier email, from one request instead of five.

* **College of Engineering & Computer Science — one shared WordPress roster.**
  All four ECS departments render from ONE combined ``ecs.syracuse.edu/
  faculty-staff/`` directory, differentiated by a server-side ``?category=<slug>``
  filter. Each person is a ``div.ecs-profile`` card: ``div.profile-name > a``
  (name + profile link) and ``div.profile-title`` (rank). The listing mixes in
  department staff (Budget Manager, Office Coordinator, Academic Operations
  Specialist, Assistant to the Chair) and emeriti; the ladder gate drops the
  staff and the engine's retired-title guard drops the emeriti.

  EMAIL is absent from every ECS listing card (0 mailto) — it lives on each
  person's profile page as PLAIN TEXT inside ``div.entry-content``. The
  ``profile_enrich`` block therefore carries ``always: True``: for a listing with
  no address at all the profile pass isn't optional depth, it's where the
  record's contact value lives, so it must not sit behind the
  ``OFE_ENRICH_PROFILES`` env gate (without it all four ECS departments ship
  name-only and fail the majority-emailed bar).

* **Maxwell School — one directory, filtered by PATH segment.**
  ``www.maxwell.syr.edu/directory`` looks query-filtered but isn't: its
  ``Directory.js`` builds the filtered URL by APPENDING the department slug as a
  path segment (``/directory/<slug>``), which the server renders. ``?department=``
  is inert (it returns the unfiltered first page), and the dropdown's own
  client-side filter never runs headless either — the path form is the only one
  that works. Each department page is a 40-per-page grid of
  ``div.flex-grid-item-md.text-gray-dark`` cards with the rank + a linked
  department name in the first ``<p>`` and a plain ``mailto`` on every card
  (100%). Pagination is ``?page=N`` on top of the path filter, starting at 2
  (``?page=1`` re-serves the base page, whose duplicate rows would abort the walk).

  Only the eight academic DEPARTMENTS are wired. The dropdown's other ~30 entries
  are centers, institutes, offices and undergraduate programs (International
  Relations, Policy Studies, Social Science Ph.D.) whose rosters are cross-listed
  people whose primary appointment is one of the eight — admitting them would
  double-count. Their majors ride the home departments instead.

* **Newhouse School — WordPress REST (``people`` post type).**
  The public directory is a client-side React shell (zero people in the served
  HTML), but ``/wp-json/wp/v2/people`` is open and returns all 374 people in ONE
  response (the endpoint ignores the per-page cap). Contact lives at
  ``meta.person_meta.contact.email`` and the clean display name at
  ``meta.person_meta.name.display_name`` — both plain dict paths the ``json_dir``
  tier reads. Departments come from the ``academic_departments`` taxonomy and the
  ladder gate is the ``faculty_type=Full-Time`` term (1395) plus a
  ``person_type.main_type == "Faculty"`` filter, which together drop the 107
  adjuncts, 6 emeriti, 9 associated and all alumni/staff. 98-100% emailed.

  RANK CAVEAT: Newhouse stores rank inside a LIST
  (``job.program_positions[].academic_program_title``), and the engine's ``_dig``
  walks dicts only — no list indexing — so no per-person rank is reachable and
  these records take the engine's "Professor" default. The taxonomy gate is what
  makes that honest: every record shipped is a full-time Newhouse faculty member.
  A trailing school-wide catch-all (listed last, so the dedup gives the
  departments first claim) picks up the ~50 full-time faculty who carry no
  ``academic_departments`` term.

Single source ("syracuse_faculty"); department rides each record, ids namespaced
by department short-code.

DROPPED / phase-2:
* **Whitman School of Management (all 9 business departments)** — the roster is
  a Sitefinity ``faculty-service`` widget that server-renders NOTHING; headless
  does render it (``li.faculty-item`` cards with rank in
  ``span.faculty-item__value`` and department in ``span.faculty-item__tag``), but
  EVERY address on both the listing AND the profile pages is the literal cloak
  ``<netid>ATsyrDOTedu``, decoded only by an inline ``onclick`` JS string
  replace. ``_clean_email`` returns None for that form (no delimiters and no word
  boundaries around "AT"/"DOT", so neither the bracket nor the bare-prose branch
  fires), so every Whitman record would ship name-only. Needs a one-line engine
  decoder (``ATsyrDOTedu`` → ``@syr.edu``) — deliberately NOT shipped email-less.
* **A&S "Humanities Faculty"** (2 rows) — a catch-all heading on the college
  roster for faculty outside a named department, not a department.
* **Maxwell centers/institutes/offices + the IR, Policy Studies and Social
  Science Ph.D. programs** — cross-listed rosters duplicating the eight
  departments.
* **Maxwell per-department ``/academics/<dept>/people/faculty`` pages** — exist
  for some departments but carry no emails (1 mailto on a 38-card page); the
  central directory is strictly richer.

Live-verified 2026-07-24: 37 departments, 826 records, 99% carrying a real
@-address; every department yields >0 and clears the majority-emailed bar
(lowest is Women's & Gender Studies at 66%, then Philosophy 92% and MAE 96%;
the other 34 are 100%). Per-source: A&S 17 depts / 398 rows, ECS 4 / 117,
Maxwell 8 / 216, Newhouse 8 / 95.

Counts run BELOW the raw listing rows by design — the engine's retired-title
guard drops the emeriti these rosters carry inline (Maxwell Anthropology lists
22 ladder cards, 6 of them "Professor Emeritus/Emerita"), and the cross-listing
dedup gives a jointly-appointed professor to whichever department is declared
first (PAIA loses 14 to Political Science; the Newhouse catch-all is last on
purpose). Both are correctness, not truncation: pagination was verified to walk
past page 1 (Political Science scrapes 59 raw across two pages).
"""

from __future__ import annotations

from .. import faculty_graph

# ---- College of Arts & Sciences: one college-wide, heading-grouped table ----
# Scoped to the desktop block because the page repeats all 18 sections in a
# mobile block; the row layout is name / rank / mailto.
_AS_URL = "https://artsandsciences.syracuse.edu/people/faculty/"
_AS_SEL = {
    "card": "div.profileindex__desktop table tr",
    "name": "td a[href*='/people/faculty/']",
    "link": "td a[href*='/people/faculty/']",
    "title": "td:nth-of-type(2)",
    "email": "a[href^='mailto:']",
}
_LADDER = {"require": r"professor|lecturer|instructor"}


# Research lives on the profile: A&S/most colleges use a
# "<p><strong>Areas of Expertise:</strong></p> <ul><li>" chip list; ECS uses an
# "Areas of Expertise" question-accordion body (comma line). One combined block
# — items win where the <ul> exists, the accordion body is the fallback — rides
# an always-on pass (listings carry no research). Absent → nothing (safe).
_SYR_RESEARCH = {
    "always": True, "throttle": 0.2,
    "research_items_selector": 'p:has(strong:-soup-contains("Areas of Expertise")) + ul li',
    "research_selector": ('div.question-accordion:has(h2:-soup-contains'
                          '("Areas of Expertise")) div.question-accordion-body'),
}


def _as(short: str, name: str, majors: list[str], section: str) -> dict:
    """An A&S department = one ``<h2>`` section of the college-wide roster."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": _AS_URL,
        "scrape": {"url": _AS_URL, "selectors": _AS_SEL,
                   "section_filter": {"heading": "h2", "include": section},
                   "ladder_filter": _LADDER,
                   "profile_enrich": _SYR_RESEARCH},
    }


# ---- College of Engineering & Computer Science: shared ecs-profile card ----
_ECS_SEL = {
    "card": "div.ecs-profile",
    "name": "div.profile-name > a",
    "link": "div.profile-name > a",
    "title": "div.profile-title",
}
# Listing carries no email at all, so the profile pass is mandatory (always),
# not the optional monthly depth pass. The address is bare text in
# div.entry-content (office/department precede it and carry no '@').
_ECS_ENRICH = {"email_selector": "div.entry-content", "always": True,
               "throttle": 0.2,
               # ECS profiles put research in an "Areas of Expertise" accordion
               # body (comma line); rides the mandatory email pass.
               "research_selector": ('div.question-accordion:has(h2:-soup-contains'
                                     '("Areas of Expertise")) div.question-accordion-body'),
               "research_items_selector": 'p:has(strong:-soup-contains("Areas of Expertise")) + ul li'}


def _ecs(short: str, name: str, majors: list[str], category: str) -> dict:
    """An ECS department on the shared combined faculty-staff directory."""
    url = f"https://ecs.syracuse.edu/faculty-staff/?category={category}"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ECS_SEL, "ladder_filter": _LADDER,
                   "profile_enrich": _ECS_ENRICH},
    }


# ---- Maxwell School: /directory/<slug> path filter, 40 per page ------------
_MX_SEL = {
    "card": "div.flex-grid-item-md.text-gray-dark",
    "name": "h2 a",
    "link": "h2 a",
    "title": "p.font-size-10.margin-bottom-0",
    "email": "a[href^='mailto:']",
}


def _mx(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A Maxwell department on the path-filtered central directory."""
    url = f"https://www.maxwell.syr.edu/directory/{slug}"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _MX_SEL, "ladder_filter": _LADDER,
                   # start=2: ?page=1 re-serves the base page, and its duplicate
                   # rows would surface no fresh cards and abort the walk.
                   "paginate": {"param": "page", "start": 2, "max": 5}},
    }


# ---- Newhouse School: open WordPress REST behind a client-side directory ----
_NH_BASE = "https://newhouse.syracuse.edu/wp-json/wp/v2/people?per_page=100"
_NH_FULLTIME = "&faculty_type=1395"  # the Full-Time term; drops adjunct/emeritus
_NH_FIELDS = {
    "name_fields": ["meta.person_meta.name.display_name"],
    "email_field": "meta.person_meta.contact.email",
    "link_field": "link",
    # Belt-and-braces on top of the faculty_type query: keeps only records whose
    # person_type is Faculty (the taxonomy also tags alumni and staff).
    "filter_field": "meta.person_meta.person_type.main_type",
    "filter_value": "Faculty",
}


def _nh(short: str, name: str, majors: list[str], term: int | None) -> dict:
    """A Newhouse department = one ``academic_departments`` term (None = all)."""
    tq = f"&academic_departments={term}" if term else ""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": "https://newhouse.syracuse.edu/about/faculty/",
        "json_dir": {"url": f"{_NH_BASE}{_NH_FULLTIME}{tq}", **_NH_FIELDS},
    }


SCHOOL: dict = {
    "school_slug": "syracuse",
    "source": "syracuse_faculty",
    "organization": "Syracuse University",
    "location": "Syracuse, NY",
    "id_prefix": "syracuse",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Syracuse University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Arts & Sciences (one roster, h2 section per dept) ----
        _as("BIO", "Department of Biology",
            ["Biology", "Biochemistry", "Neuroscience"], r"^Biology$"),
        _as("PHYS", "Department of Physics", ["Physics"], r"^Physics$"),
        _as("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
            r"^Chemistry$"),
        _as("MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"], r"^Mathematics$"),
        _as("EES", "Department of Earth and Environmental Sciences",
            ["Earth Sciences", "Environmental Geoscience"],
            r"^Earth and Environmental Sciences$"),
        _as("PSYC", "Department of Psychology",
            ["Psychology", "Neuroscience"], r"^Psychology$"),
        _as("FSCI", "Forensic and National Security Sciences Institute",
            ["Forensic Science"], r"^Forensic Science$"),
        _as("ENGL", "Department of English",
            ["English", "Creative Writing"], r"^English$"),
        _as("LLL", "Department of Languages, Literatures, and Linguistics",
            ["Linguistics", "Spanish", "French"],
            r"^Languages, Literatures, and Linguistics$"),
        _as("WRT", "Department of Writing Studies, Rhetoric, and Composition",
            ["Writing and Rhetoric"],
            r"^Writing Studies, Rhetoric, and Composition$"),
        _as("CSD", "Department of Communication Sciences and Disorders",
            ["Communication Sciences and Disorders"],
            r"^Communication Sciences and Disorders$"),
        _as("HDFS", "Department of Human Development and Family Science",
            ["Human Development and Family Science"],
            r"^Human Development and Family Science$"),
        _as("PHIL", "Department of Philosophy", ["Philosophy"], r"^Philosophy$"),
        _as("AMH", "Department of Art and Music Histories",
            ["Art History", "Music History"], r"^Art and Music Histories$"),
        _as("RELI", "Department of Religion", ["Religion"], r"^Religion$"),
        _as("AAS", "Department of African American Studies",
            ["African American Studies"], r"^African American Studies$"),
        _as("WGS", "Department of Women's and Gender Studies",
            ["Women's and Gender Studies"], r"^Women.s and Gender Studies$"),
        # ---- College of Engineering & Computer Science (?category= filter) ---
        _ecs("EECS", "Department of Electrical Engineering and Computer Science",
             ["Electrical Engineering", "Computer Engineering", "Computer Science"],
             "electrical-engineering-and-computer-science"),
        _ecs("MAE", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"],
             "mechanical-and-aerospace-engineering"),
        _ecs("BMCE", "Department of Biomedical and Chemical Engineering",
             ["Biomedical Engineering", "Chemical Engineering"],
             "biomedical-and-chemical-engineering"),
        _ecs("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "civil-and-environmental-engineering"),
        # ---- Maxwell School of Citizenship and Public Affairs ----------------
        _mx("PSC", "Department of Political Science",
            ["Political Science", "International Relations", "Policy Studies"],
            "political-science"),
        _mx("PAIA", "Department of Public Administration and International Affairs",
            ["Public Administration", "Public Policy", "International Relations",
             "Policy Studies"], "paia"),
        _mx("ECON", "Department of Economics", ["Economics"],
            "economics-department"),
        _mx("HIST", "Department of History", ["History"], "history"),
        _mx("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _mx("GEO", "Department of Geography and the Environment",
            ["Geography", "Environmental Science"],
            "geography-and-the-environment"),
        _mx("ANTH", "Department of Anthropology", ["Anthropology"],
            "anthropology"),
        _mx("PHP", "Department of Public Health", ["Public Health"],
            "public-health-department"),
        # ---- S.I. Newhouse School of Public Communications -------------------
        _nh("PR", "Department of Public Relations", ["Public Relations"], 1559),
        _nh("MND", "Department of Magazine, News and Digital Journalism",
            ["Magazine, News and Digital Journalism", "Journalism"], 1461),
        _nh("COMM", "Department of Communications",
            ["Communications", "Media Studies"], 1274),
        _nh("ADV", "Department of Advertising", ["Advertising"], 1189),
        _nh("TRF", "Department of Television, Radio and Film",
            ["Television, Radio and Film"], 1622),
        _nh("BDJ", "Department of Broadcast and Digital Journalism",
            ["Broadcast and Digital Journalism", "Journalism"], 1252),
        _nh("VIS", "Department of Visual Communications",
            ["Visual Communications", "Photography"], 1637),
        # Catch-all for the full-time faculty carrying no academic_departments
        # term (deans, endowed chairs, cross-program appointments) — listed last
        # so the departments above win the email/URL dedup.
        _nh("NEWH", "S.I. Newhouse School of Public Communications",
            ["Public Communications", "Journalism"], None),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
