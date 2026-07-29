"""Colorado State University faculty config (via the faculty_graph engine).

Colorado State runs a different directory widget per college / department family;
this config wires one selector (or headless-render) set per family and rides the
department on each record. Live-verified 2026-07-24. Coverage now spans four
colleges by six markup families:

* **"sg-directory" list rows — ``directory-default-row`` (Natural Sciences:
  Computer Science, Physics, Mathematics).** One ``div.directory-default-row`` per
  person: a photo ``a.team-member-name``, a text ``a.team-member-name`` wrapping
  ``span.team-member-name``, a ``span.directory-list-title`` rank (stray "/ "
  prefix), a clean ``mailto`` in ``.directory-list-contact-info``. These are FULL
  people directories (Physics alone lists 22 grad research assistants, 12 grad
  teaching assistants, emeriti, postdocs, staff around ~20 ladder faculty), so the
  ``field_filter`` on ``span.directory-list-title`` (``require_present`` so a
  title-less card can't fall through to the "Professor" default, keep
  professor/lecturer/instructor, drop ``emerit``) is the load-bearing gate.

* **"mk-employee-item" cards (Natural Sciences: Chemistry, Statistics, Biology,
  Biochemistry & Molecular Biology).** Jupiter "employees" widget: one
  ``li.mk-employee-item`` per person, name in ``span.team-member-name``, rank in
  ``span.team-member-position``, per-card ``mailto`` (100% email). ``.team-member-desc``
  is Office/Phone text, NOT research. Same title gate drops the dozens of ARC-facility
  scientists, IT/accounting staff and emeriti these full rosters carry (Biology's
  raw page is 269 people, Chemistry mixes in facility managers, etc.).

* **"cns-directory-grid" cards (Natural Sciences: Psychology).** The College of
  Natural Sciences shared directory (backed by ``cnsdrake.natsci.colostate.edu``):
  one ``div.cns-directory-grid-item`` per person, name in ``h3.cns-directory-name``,
  rank in ``p.cns-directory-title``, ``mailto`` inside ``div.cns-directory-contact``.
  Full roster (admin coordinators, office managers, research scientists) → same gate.

* **engineering "person_row" (Walter Scott College of Engineering: ECE,
  Mechanical, Civil & Environmental, Chemical & Biological, Biomedical).** Each
  ``engr.colostate.edu/<dept>/people/`` paints its roster CLIENT-SIDE from the shared
  ``/libs/directory/`` widget (``div#dir_list``), so a bare GET yields ~zero cards and
  ``wp-json`` is 403-blocked — these need ``scrape["render"]=True`` (headless
  Playwright). Rendered card = ``div.person_row`` with ``div.person-name`` (link +
  name), ``div.person-appointment`` (rank), and a ``mailto`` in ``div.person-contact``
  (100% emailed). Rosters carry research associates, postdocs, lab engineers and
  advising staff → gated to professor/lecturer/instructor ranks.

* **"memberSmall" cards (College of Business — one college-wide directory).**
  ``biz.colostate.edu/directory/`` server-renders every business person as
  ``div.memberSmall`` with a schema.org ``a.user-listing-name`` ("Last, First" →
  ``name_flip``), ``span.user-listing-position`` rank, and a ``mailto`` in
  ``span.user-listing-email`` (297/298 emailed). No per-department split is exposed,
  so it ships as one "College of Business" department. The gate drops the ~40
  Instructional Coordinators, advisors and 12 emeriti (note "Instructor" does not
  substring-match "Instructional", so those coordinators are correctly excluded).

DROPPED / phase-2 (no reachable contact email — shipping them would pad the count
with worthless name-only records):
  * **College of Liberal Arts** (Anthropology, Economics, English, History, …):
    the shared ``cla-people-list-item`` widget lists name + title + profile link
    but NO email — and the individual profile pages carry no ``mailto`` even after a
    headless render. Email-less; needs profile-enrich/phase-2.
  * **Warner College of Natural Resources** (Ecosystem Science, Fish/Wildlife,
    Forest & Rangeland, Geosciences, Human Dimensions): the college directory is a
    client-side jQuery-UI accordion (``warnercnr.colostate.edu/directory/``) that
    lazy-loads only the first expanded section (~10 emails) headless and never
    hydrates the rest; no reachable per-department roster.
  * **College of Agricultural Sciences** (Soil & Crop, Animal Sciences, Horticulture
    & Landscape Architecture, Ag & Resource Economics, Ag Biology): the
    ``agsci.colostate.edu/directory/`` app renders its people only via an
    ``admin-ajax.php`` POST (nonce-gated) — no static, headless or REST roster carries
    emails.
  * **Biomedical Engineering** (``engr.colostate.edu/sbme/people/``): the School of
    Biomedical Engineering's people page lists only administrative/advising staff —
    its faculty are cross-appointed from ME/ECE/Chem etc., so the ladder-rank gate
    leaves 0 standalone records.
  * **Systems Engineering** (``engr.colostate.edu/se/people/`` → 404) and
    **Neuroscience** (graduate program, faculty drawn from other departments): no
    standalone faculty directory.

Single source ("colostate_faculty"); department rides each record, ids namespaced
by department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# Shared rank extractor: trim a matched title back to a clean ladder/teaching rank
# (drops the stray "/ " prefix and trailing " - FC" / director / chair suffixes).
_RANK_RE = (
    r"((?:University\s+)?(?:Distinguished\s+)?"
    r"(?:Assistant\s+|Associate\s+|Adjunct\s+|Research\s+|Visiting\s+"
    r"|Teaching\s+|Senior\s+|Clinical\s+|Master\s+)*"
    r"(?:Professor|Lecturer|Instructor))"
)


def _field(selector: str) -> dict:
    """Load-bearing gate: require the rank element (so a title-less staff row can't
    default to "Professor"), keep only ladder/teaching ranks, drop emeriti."""
    return {
        "selector": selector,
        "require_present": True,
        "include": r"professor|lecturer|instructor",
        "exclude": r"emerit",
    }


# ---- "sg-directory" list rows: Computer Science / Physics / Mathematics -----
# Card = the per-person row wrapper (never ``.team-member-name``, which repeats
# 3x/person). Name is the inner span; the profile link is the photo/text anchor
# to ``/person/?id=…`` (its ?id query IS the identity, so it is NOT stripped).
_DIR_SEL = {
    "card": "div.directory-default-row",
    "name": "span.team-member-name",
    "link": "a.team-member-name[href*='/person/']",
    "title": "span.directory-list-title",
    "title_re": _RANK_RE,
    "email": "div.directory-list-contact-info a[href^='mailto:']",
}
_DIR_FIELD = _field("span.directory-list-title")

# ---- "mk-employee-item" cards: Chemistry / Statistics / Biology / Biochem ----
# ``.team-member-desc`` is Office/Phone contact text, NOT research — no research
# selector; topics come from downstream OpenAlex enrichment.
_EMP_SEL = {
    "card": "li.mk-employee-item",
    "name": "span.team-member-name",
    "link": "a.team-member-name[href*='/person/']",
    "title": "span.team-member-position",
    "title_re": _RANK_RE,
    "email": "a[href^='mailto:']",
}
_EMP_FIELD = _field("span.team-member-position")

# ---- "cns-directory-grid" cards: Psychology (CNS shared directory) ----------
_CNS_SEL = {
    "card": "div.cns-directory-grid-item",
    "name": "h3.cns-directory-name a",
    "link": "h3.cns-directory-name a[href*='/person/']",
    "title": "p.cns-directory-title",
    "title_re": _RANK_RE,
    "email": "div.cns-directory-contact a[href^='mailto:']",
}
_CNS_FIELD = _field("p.cns-directory-title")

# ---- engineering "person_row" (headless render): Walter Scott College --------
# Client-rendered from the shared ``/libs/directory/`` widget; wp-json is 403, so
# the roster exists only after JS runs → ``render: True`` (Playwright).
_ENGR_SEL = {
    "card": "div.person_row",
    "name": "div.person-name a",
    "link": "div.person-name a",
    "title": "div.person-appointment",
    "title_re": _RANK_RE,
    "email": "div.person-contact a[href^='mailto:']",
}
_ENGR_FIELD = _field("div.person-appointment")

# ---- "memberSmall" cards: College of Business (one college-wide directory) ---
# schema.org markup; name is "Last, First" → name_flip un-inverts it.
_BIZ_SEL = {
    "card": "div.memberSmall",
    "name": "a.user-listing-name",
    "link": "a.user-listing-name",
    "title": "span.user-listing-position",
    "title_re": _RANK_RE,
    "email": "span.user-listing-email a[href^='mailto:']",
}
_BIZ_FIELD = _field("span.user-listing-position")


def _dept(short, name, majors, url, sel, field, **scrape):
    scrape = {"url": url, "selectors": sel, "field_filter": field, **scrape}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _dir_dept(short, name, majors, url):
    return _dept(short, name, majors, url, _DIR_SEL, _DIR_FIELD)


def _emp_dept(short, name, majors, url):
    return _dept(short, name, majors, url, _EMP_SEL, _EMP_FIELD)


def _cns_dept(short, name, majors, url):
    return _dept(short, name, majors, url, _CNS_SEL, _CNS_FIELD)


# Each engineering profile is also client-rendered; its "Research Interests"
# (or "Research Focus Areas"/"Academic Areas") Elementor heading is followed by a
# <li> chip list. The profile pass renders too (env-gated; CI does not render
# colostate, so the local seed persists via keyword carry-forward).
_ENGR_RESEARCH_ENRICH = {
    "render": True, "render_settle": 4000, "throttle": 0.2,
    "research_items_selector": (
        'div.elementor-widget-heading:has(h2.elementor-heading-title'
        ':-soup-contains("Research Interests")) + div.elementor-widget-text-editor li, '
        'div.elementor-widget-heading:has(h2.elementor-heading-title'
        ':-soup-contains("Research Focus Areas")) + div.elementor-widget-text-editor li, '
        'div.elementor-widget-heading:has(h2.elementor-heading-title'
        ':-soup-contains("Academic Areas")) + div.elementor-widget-text-editor li'),
}


def _engr_dept(short, name, majors, url):
    return _dept(short, name, majors, url, _ENGR_SEL, _ENGR_FIELD,
                 render=True, render_settle=5000,
                 profile_enrich=_ENGR_RESEARCH_ENRICH)


def _biz_dept(short, name, majors, url):
    return _dept(short, name, majors, url, _BIZ_SEL, _BIZ_FIELD, name_flip=True)


# ---- College of Health & Human Sciences: one shared JSON directory API -------
# The CHHS directory pages are a List.js widget that server-renders only 10 cards
# but hydrates from a public JSON REST endpoint. Each department = the feed sliced
# by its ``<CODE> - Faculty and Staff`` group; keep roles=Faculty (drops the
# staff-only rows) and drop emeriti. Email is inline in the feed.
_CHHS_API = "https://apps.chhs.colostate.edu/directory/api/users"


def _chhs(short, name, majors, code):
    url = f"https://www.chhs.colostate.edu/{code.lower()}/faculty/"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "json_dir": {"url": _CHHS_API,
                         "name_fields": ["name.display"],
                         "title_field": "title", "email_field": "email",
                         "filter_field": "groups",
                         "filter_value": f"{code} - Faculty and Staff",
                         "status_field": "roles", "status_value": "Faculty",
                         "ladder_filter": {"drop": r"emerit"}}}


# ---- College of Liberal Arts shared "cla-people" widget (static HTML) --------
# TABLE flavor (Music/Theatre/Dance): inline mailto per row; title-gated
# (professor/lecturer/instructor, drop emeriti). CARD flavor (English): each
# person is an li with data-position — gate on data-position=faculty, email in
# the card's mailto.
_CLA_TABLE_SEL = {
    "card": "tr.cla-people-list-item",
    "name": "td.cla-people-list-item-name a",
    "link": "td.cla-people-list-item-name a",
    "title": "td.cla-people-list-item-title",
    "email": "td.cla-people-list-item-email a[href^='mailto:']",
    # Expertise/concentration ("Piano", "Voice", …) rides the listing card —
    # comma/semicolon-split into keywords downstream.
    "research": "td.cla-people-list-item-concentration",
}
_CLA_CARD_SEL = {
    "card": "li.cla-people-list-item[data-position='faculty']",
    "name": "h3.cla-people-name",
    "link": "a.cla-people-name-link",
    "title": "ul.cla-people-position-title li",
    "email": "p.cla-people-email a.cla-people-email-link[href^='mailto:']",
    # English lists expertise as the card's data-concentration attribute
    # ("Creative Writing, Contemporary Literature") — no text element holds it.
    "research_re": r'data-concentration="([^"]+)"',
}
_CLA_LADDER = {"require": r"professor|lecturer|instructor", "drop": r"emerit"}


def _cla_table(short, name, majors, url):
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CLA_TABLE_SEL,
                       "ladder_filter": _CLA_LADDER}}


def _cla_card(short, name, majors, url):
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CLA_CARD_SEL,
                       "ladder_filter": {"drop": r"emerit"}}}


SCHOOL: dict = {
    "school_slug": "colostate",
    "source": "colostate_faculty",
    "organization": "Colorado State University",
    "location": "Fort Collins, CO",
    "id_prefix": "colostate",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Colorado State University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Natural Sciences ------------------------------------
        _dir_dept("CS", "Department of Computer Science",
                  ["Computer Science", "Data Science"],
                  "https://compsci.colostate.edu/people/"),
        _dir_dept("PHYS", "Department of Physics",
                  ["Physics", "Astrophysics"],
                  "https://www.physics.colostate.edu/about/people/"),
        _dir_dept("MATH", "Department of Mathematics",
                  ["Mathematics", "Applied Mathematics"],
                  "https://mathematics.colostate.edu/people/faculty/"),
        _emp_dept("CHEM", "Department of Chemistry",
                  ["Chemistry", "Biochemistry"],
                  "https://www.chem.colostate.edu/people/"),
        _emp_dept("STAT", "Department of Statistics",
                  ["Statistics", "Data Science"],
                  "https://statistics.colostate.edu/faculty-staff/"),
        _emp_dept("BIOL", "Department of Biology",
                  ["Biology", "Neuroscience"],
                  "https://www.biology.colostate.edu/directory/"),
        _emp_dept("BMB", "Department of Biochemistry and Molecular Biology",
                  ["Biochemistry", "Biology"],
                  "https://www.bmb.colostate.edu/about/people/"),
        _cns_dept("PSY", "Department of Psychology",
                  ["Psychology", "Neuroscience"],
                  "https://psychology.colostate.edu/people/"),
        # ---- Walter Scott, Jr. College of Engineering (headless render) -----
        _engr_dept("ECE", "Department of Electrical and Computer Engineering",
                   ["Electrical Engineering", "Computer Engineering"],
                   "https://www.engr.colostate.edu/ece/people/"),
        _engr_dept("ME", "Department of Mechanical Engineering",
                   ["Mechanical Engineering"],
                   "https://www.engr.colostate.edu/me/people/"),
        _engr_dept("CE", "Department of Civil and Environmental Engineering",
                   ["Civil Engineering", "Environmental Engineering"],
                   "https://www.engr.colostate.edu/ce/people/"),
        _engr_dept("BCE", "Department of Chemical and Biological Engineering",
                   ["Chemical and Biological Engineering"],
                   "https://www.engr.colostate.edu/bce/people/"),
        # ---- College of Business (one college-wide directory) ---------------
        _biz_dept("BUS", "College of Business",
                  ["Accounting", "Finance", "Real Estate", "Management",
                   "Marketing", "Computer Information Systems",
                   "Human Resource Management", "Business Administration"],
                  "https://biz.colostate.edu/directory/"),
        # ---- College of Health & Human Sciences (shared JSON directory API) -
        _chhs("FSHN", "Department of Food Science and Human Nutrition",
              ["Food Science", "Human Nutrition", "Nutrition and Food Science"], "FSHN"),
        _chhs("HDFS", "Department of Human Development and Family Studies",
              ["Human Development and Family Studies"], "HDFS"),
        _chhs("HES", "Department of Health and Exercise Science",
              ["Health and Exercise Science", "Kinesiology"], "HES"),
        _chhs("OT", "Department of Occupational Therapy",
              ["Occupational Therapy"], "OT"),
        _chhs("CM", "Department of Construction Management",
              ["Construction Management"], "CM"),
        _chhs("DM", "Department of Design and Merchandising",
              ["Interior Architecture and Design", "Apparel and Merchandising"], "DM"),
        _chhs("SOE", "School of Education", ["Education"], "SOE"),
        _chhs("SSW", "School of Social Work", ["Social Work"], "SSW"),
        # ---- College of Liberal Arts: School of Music, Theatre & Dance ------
        _cla_table("MUS", "School of Music, Theatre and Dance — Music",
                   ["Music", "Music Education", "Music Performance"],
                   "https://music.colostate.edu/people/"),
        _cla_table("THTR", "School of Music, Theatre and Dance — Theatre",
                   ["Theatre"], "https://theatre.colostate.edu/people/"),
        _cla_table("DANC", "School of Music, Theatre and Dance — Dance",
                   ["Dance"], "https://dance.colostate.edu/people/"),
        # ---- College of Liberal Arts: English (card flavor, inline email) ---
        _cla_card("ENGL", "Department of English",
                  ["English", "Creative Writing", "Literature"],
                  "https://english.colostate.edu/faculty-staff/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
