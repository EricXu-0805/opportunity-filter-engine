"""Lehigh University faculty config (via the faculty_graph engine).

Full university-wide coverage across the catalog's four colleges — Rossin College
of Engineering, the College of Arts & Sciences, the College of Business, and the
College of Health — over five server-rendered markup families (no WAF, no JS
render on any of them). Live-verified 2026-07-24.

* **P.C. Rossin College of Engineering — legacy Drupal "Views" grid (7 depts).**
  CSE, ECE, MechE, BioE, ChBE, CEE and ISE all render each person as a
  ``div.views-row`` with a ``div.views-field-title span.field-content a`` name +
  profile link (``/<dept>/faculty/<numeric-id>``) and a
  ``div.views-field-field-position div.field-content`` rank. No email is on the
  listing (only a generic department address), so these seven land name+title+url
  and a per-profile ``profile_enrich`` pass (``always``) recovers each person's
  address from their profile page (``div.field-name-field-email div.field-item``,
  a plain-text ``field-item`` — the page's only ``mailto`` is the footer's generic
  engineering@lehigh.edu). A ``field_filter`` (not ``ladder_filter``) gates the
  rank: every listing ends with a title-less row whose text is the department name
  itself, and a missing position field would otherwise default to "Professor" and
  leak through, so ``require_present`` drops the position-less row directly, then
  ``include`` keeps only professor/lecturer ranks (dropping ChBE's "University
  President" courtesy row) and ``exclude`` drops adjunct/visiting; emeriti drop via
  the engine's retired-title guard.

* **Materials Science & Engineering — hand-built photo grid (own selector).**
  ``/matsci/faculty`` is NOT the Views template: a flat ``<ul>`` of
  ``li[style*="flex-basis"]`` photo tiles with the name in one of two shapes — an
  ``.overlay`` caption anchor or a bare bold-styled anchor. The tile carries NO
  rank and lists only core faculty (Staff/Emeritus on separate tabs), so no title
  gate; the same engineering profile_enrich pass fills email from each profile.

* **College of Arts & Sciences — "substratum/cas-profile" Drupal (15 depts).**
  Every departmental subdomain (``*.cas.lehigh.edu/faculty-staff`` plus Art,
  Architecture & Design on ``aad.lehigh.edu/faculty-staff``) renders each person
  as an ``article`` whose class is ``cas-profile__card`` (hyphen) on most and
  ``cas_profile__card`` (underscore) on a few — ``article[class*="profile__card"]``
  matches both. Name is ``h1.h1--page-title``; the rank is the FIRST
  ``h2.field--lehigh``; the profile link is ``a.link--arrow[href^='/faculty-
  staff/']``. Email is VISIBLE PLAIN TEXT (no mailto) in ``div.profile__contact``:
  each contact row is an ``icon__field-wrapper`` / ``icon__field_wrapper`` whose
  svg ``aria-labelledby`` names the field, so the email row is selected off
  ``svg[aria-labelledby="email"]``. A ``field_filter`` gates the first h2 (require
  professor/lecturer, drop adjunct/visiting) to drop the postdocs, lab managers,
  coordinators, business/technician staff, artists-in-residence and visiting/
  adjunct rows the pages mix in; emeriti drop via the retired-title guard. Email
  coverage is ~100% on the listing for every ``.cas`` department.

* **College of Business — Drupal directory view, server-side filtered (6 depts).**
  ``business.lehigh.edu/directory?type=1&category=<id>`` returns one department's
  FACULTY only (``type=1`` = faculty, ``category`` = the department taxonomy term).
  Each person is a ``li.az-profile`` with the name in ``span.field--name-title``, a
  ``.az-profile-image a`` profile link, a ``mailto`` email and a ``<p>`` of
  "Rank Department". A ``title_re`` lifts the clean rank from the card text; a
  ``ladder_filter`` drops any adjunct/visiting/emeritus. ~100% emailed.

* **College of Health — Drupal person-grid (1 dept).**
  ``health.lehigh.edu/faculty`` lists each person as a ``div.faculty-row`` with an
  ``h2 a`` name (degree post-nominals stripped by the engine), a ``mailto`` email
  and a ``<p>`` of "Rank, Department". A ``field_filter`` on that ``<p>`` (require
  professor/lecturer, drop adjunct/visiting) keeps ladder + teaching faculty and
  drops the coordinators/managers; a ``title_re`` lifts the clean rank. ~95%
  emailed.

Dropped (recorded for the orchestrator): the Cognitive Science program
(``programs.cas.lehigh.edu/cog-sci``) is an interdisciplinary affiliated-faculty
list — its roster is name-only with a single shared program email (fails the
majority-emailed gate) and every member is a duplicate of a psychology/philosophy/
CS professor already shipped from their home department. The other CAS
interdisciplinary programs (Africana, Asian, Environmental, Film, Global, Health-
Medicine-Society, Latin American, Women's studies, Jewish Studies) are likewise
affiliated-faculty umbrellas, out of the catalog's department scope, and would
only duplicate home-department records — not wired.

Single source ("lehigh_faculty"); department rides each record, ids namespaced by
department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Rossin College of Engineering: shared Drupal "Views" grid -------------
# Each person is a div.views-row; the name link + profile href live in the
# title field, the rank in the position field. No email on the listing — the
# profile_enrich pass recovers it from each person's profile page.
_ENG_SEL = {
    "card": "div.views-row",
    "name": "div.views-field-title span.field-content a",
    "link": "div.views-field-title span.field-content a",
    "title": "div.views-field-field-position div.field-content",
}
# field_filter (not ladder_filter): the position element must exist (drops the
# trailing department-name row, which has none and would otherwise default to
# "Professor" and pass) and must name a professor/lecturer rank (drops the
# "University President" courtesy row on ChBE) and not be adjunct/visiting.
# Emeriti drop via the retired gate.
_ENG_FIELD = {
    "selector": "div.views-field-field-position div.field-content",
    "require_present": True,
    "include": r"professor|lecturer",
    "exclude": r"adjunct|visiting|emerit",
}
# The listing carries no email; every engineering/matsci profile page keeps the
# personal address as plain text in a Drupal email field (the only mailto on the
# page is the footer's generic engineering@lehigh.edu). ``always`` runs it even
# without OFE_ENRICH_PROFILES so the college ships emailed, not name-only.
_ENG_ENRICH = {
    "always": True,
    "email_selector": "div.field-name-field-email div.field-item",
    # ENG + MatSci profiles carry a comma-joined "Areas of Research" field-item;
    # prose path (comma-split downstream). Rides the same always-on email pass.
    "research_selector": "div.field-name-field-areas-of-research div.field-item",
    "timeout": 8,
    "max_retries": 1,
    "throttle": 0.3,
}


def _eng(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Rossin engineering department on the shared Views grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "field_filter": _ENG_FIELD,
                   "profile_enrich": _ENG_ENRICH},
    }


# ---- Materials Science & Engineering: hand-built photo grid -----------------
# li photo tiles; name in an .overlay caption anchor or a bare bold anchor. No
# rank on the tile and the page is core-faculty-only, so no title gate. Email
# comes from the same engineering profile_enrich pass.
_MATSCI_SEL = {
    "card": 'li[style*="flex-basis"]',
    "name": '.overlay a, a[style*="font-weight: bold"]',
    "link": '.overlay a, a[style*="font-weight: bold"]',
}


# ---- College of Arts & Sciences: substratum/cas-profile Drupal --------------
# article[class*="profile__card"] matches both the hyphen and underscore class
# spellings. Rank = first h2.field--lehigh. Email is plain text in the contact
# block's email row, keyed off the svg's aria label.
_CAS_SEL = {
    "card": 'article[class*="profile__card"]',
    "name": "h1.h1--page-title",
    "link": "a.link--arrow[href^='/faculty-staff/']",
    "title": "h2.field--lehigh",
    "email": (
        'div[class*="icon__field"]:has(svg[aria-labelledby="email"]) '
        "div.field--showy"
    ),
}
# Gate the first h2 rank: require professor/lecturer and drop adjunct/visiting,
# dropping postdocs, fellows, lab managers, coordinators, business/technician
# staff, artists-in-residence and visiting/adjunct rows. Emeriti drop via the
# retired-title guard (and the "emerit" exclude, at parse time).
_CAS_FIELD = {
    "selector": "h2.field--lehigh",
    "require_present": True,
    "include": r"professor|lecturer",
    "exclude": r"adjunct|visiting|emerit",
}
# CAS profiles keep research areas as discrete tagged <li> in ul.research-items —
# atomic items path (each <li> survives whole, no comma re-split). Env-gated
# (OFE_ENRICH_PROFILES); _carry_forward_enrichment persists it across refreshes.
_CAS_ENRICH = {
    "research_items_selector": "ul.research-items li",
    "timeout": 8,
    "max_retries": 1,
    "throttle": 0.3,
}


def _cas(short: str, name: str, majors: list[str], url: str) -> dict:
    """A CAS department on the substratum cas-profile component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CAS_SEL, "field_filter": _CAS_FIELD,
                   "profile_enrich": _CAS_ENRICH},
    }


# ---- College of Business: Drupal directory view (server-side filtered) ------
# ?type=1 (faculty) & category=<term> returns one department's faculty. Name in
# span.field--name-title, profile link in .az-profile-image a, mailto email, and
# a <p> of "Rank Department". title_re lifts the clean rank; the ladder drops any
# adjunct/visiting/emeritus.
_BIZ_SEL = {
    "card": "li.az-profile",
    "name": "span.field--name-title",
    "link": ".az-profile-image a",
    "email": "a[href^='mailto:']",
    # The name field appends alumni class-years / degrees to a few faculty
    # ("Mary Kate Dodgson '08", "Dale F. Falcinelli '70 '72 M.A.") — strip from
    # the first apostrophe-year token so pi_name is the clean personal name.
    "name_strip": r"\s+'\d{2}\b.*$",
    "title_re": (
        r"(?i)\b((?:Senior |Associate |Assistant |Teaching |Distinguished |"
        r"Visiting |Adjunct |Clinical |Research )*(?:Full\s+)?"
        r"Professor(?:\s+of\s+Practice)?|Lecturer|Instructor)\b"
    ),
}
_BIZ_LADDER = {"require": r"professor|lecturer", "drop": r"adjunct|visiting|emerit"}
_BIZ_DIR = "https://business.lehigh.edu/directory?type=1&category="
# Business profiles expose research under a "Research Interests" accordion whose
# <ul><li> items are discrete tagged areas (the accordion is hidden="" but
# server-rendered, so BS4 sees it). Env-gated; carry-forward persists it.
_BIZ_ENRICH = {
    "research_items_selector": 'h4:-soup-contains("Research Interests") + ul li',
    "timeout": 8,
    "max_retries": 1,
    "throttle": 0.3,
}


def _biz(short: str, name: str, majors: list[str], category: str) -> dict:
    """A College of Business department (server-side filtered directory view)."""
    url = f"{_BIZ_DIR}{category}"
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _BIZ_SEL, "ladder_filter": _BIZ_LADDER,
                   "profile_enrich": _BIZ_ENRICH},
    }


# ---- College of Health: Drupal person-grid ----------------------------------
# div.faculty-row cards (the plain views-row hero/wrapper rows lack .faculty-row).
# h2 a name (degree post-nominals stripped by the engine), mailto email, and a
# <p> of "Rank, Department". field_filter on the <p> keeps professor/lecturer and
# drops the coordinators/managers/staff; title_re lifts the clean rank.
_HEALTH_SEL = {
    "card": "div.faculty-row",
    "name": "h2 a",
    "link": "h2 a",
    "email": "a[href^='mailto:']",
    # Health names carry degree post-nominals ("Gideon Gogovi, PhD, MS, Mphil.");
    # the engine's credential gate stops on the unrecognized "MPhil", so strip the
    # comma-degree tail here (O'Keeffe / "Jr." are preserved — not degree tokens).
    "name_strip": (
        r"(?i),\s*(?:Ph\.?D|M\.?S(?:c|OR)?|M\.?A|M\.?P\.?H|MHA|M\.?Phil|"
        r"M\.?D|B\.?[AS]|Dr\.?P\.?H|RN|MBA|MSN|DNP|EdD|MSW)\b.*$"
    ),
    "title_re": (
        r"(?i)\b((?:Senior |Associate |Assistant |Teaching |Distinguished |"
        r"Visiting |Adjunct |Clinical |Research )*"
        r"Professor(?:\s+of\s+Practice)?|Lecturer|Instructor)\b"
    ),
}
_HEALTH_FIELD = {
    "selector": "p",
    "require_present": True,
    "include": r"professor|lecturer",
    "exclude": r"adjunct|visiting|emerit",
}


SCHOOL: dict = {
    "school_slug": "lehigh",
    "source": "lehigh_faculty",
    "organization": "Lehigh University",
    "location": "Bethlehem, PA",
    "id_prefix": "lehigh",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Lehigh University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- P.C. Rossin College of Engineering (Views grid) ---------------
        _eng("CSE", "Department of Computer Science and Engineering",
             ["Computer Science", "Computer Engineering", "Data Science"],
             "https://engineering.lehigh.edu/cse/cse-faculty"),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://engineering.lehigh.edu/ece/faculty"),
        _eng("MECHE", "Department of Mechanical Engineering and Mechanics",
             ["Mechanical Engineering", "Engineering Mechanics"],
             "https://engineering.lehigh.edu/meche/faculty"),
        _eng("BIOE", "Department of Bioengineering",
             ["Bioengineering", "Biomedical Engineering"],
             "https://engineering.lehigh.edu/bioe/core-faculty"),
        _eng("CHBE", "Department of Chemical and Biomolecular Engineering",
             ["Chemical Engineering", "Biomolecular Engineering"],
             "https://engineering.lehigh.edu/chbe/faculty"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "https://engineering.lehigh.edu/cee/people"),
        _eng("ISE", "Department of Industrial and Systems Engineering",
             ["Industrial Engineering", "Systems Engineering"],
             "https://engineering.lehigh.edu/ise/faculty"),
        # ---- Materials Science & Engineering (hand-built grid) -------------
        {
            "short": "MATSCI",
            "name": "Department of Materials Science and Engineering",
            "majors": ["Materials Science and Engineering"],
            "directory_url": "https://engineering.lehigh.edu/matsci/faculty",
            "scrape": {
                "url": "https://engineering.lehigh.edu/matsci/faculty",
                "selectors": _MATSCI_SEL,
                "profile_enrich": _ENG_ENRICH,
            },
        },
        # ---- College of Arts & Sciences: sciences (cas-profile) -----------
        _cas("PHYSICS", "Department of Physics", ["Physics", "Astrophysics"],
             "https://physics.cas.lehigh.edu/faculty-staff"),
        _cas("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
             "https://chemistry.cas.lehigh.edu/faculty-staff"),
        _cas("MATH", "Department of Mathematics",
             ["Mathematics", "Applied Mathematics", "Statistics"],
             "https://math.cas.lehigh.edu/faculty-staff"),
        _cas("BIO", "Department of Biological Sciences",
             ["Biological Sciences", "Molecular Biology", "Behavioral Neuroscience"],
             "https://bio.cas.lehigh.edu/faculty-staff"),
        _cas("PSYC", "Department of Psychology",
             ["Psychology", "Behavioral Neuroscience"],
             "https://psychology.cas.lehigh.edu/faculty-staff"),
        _cas("EES", "Department of Earth and Environmental Sciences",
             ["Earth and Environmental Sciences"],
             "https://ees.cas.lehigh.edu/faculty-staff"),
        _cas("ENGL", "Department of English", ["English"],
             "https://english.cas.lehigh.edu/faculty-staff"),
        _cas("HIST", "Department of History", ["History"],
             "https://history.cas.lehigh.edu/faculty-staff"),
        _cas("POLS", "Department of Political Science", ["Political Science"],
             "https://polisci.cas.lehigh.edu/faculty-staff"),
        _cas("IR", "Department of International Relations",
             ["International Relations"],
             "https://ir.cas.lehigh.edu/faculty-staff"),
        _cas("SOCANTH", "Department of Sociology and Anthropology",
             ["Sociology and Anthropology"],
             "https://socanthro.cas.lehigh.edu/faculty-staff"),
        _cas("PHIL", "Department of Philosophy", ["Philosophy"],
             "https://philosophy.cas.lehigh.edu/faculty-staff"),
        _cas("MLL", "Department of Modern Languages and Literatures",
             ["Modern Languages and Literatures"],
             "https://mll.cas.lehigh.edu/faculty-staff"),
        _cas("MUSIC", "Department of Music", ["Music"],
             "https://music.cas.lehigh.edu/faculty-staff"),
        _cas("JOUR", "Department of Journalism and Communication", ["Journalism"],
             "https://journalism.cas.lehigh.edu/faculty-staff"),
        _cas("AAD", "Department of Art, Architecture and Design",
             ["Art, Architecture and Design"],
             "https://aad.lehigh.edu/faculty-staff"),
        _cas("REL", "Department of Religion Studies", ["Religion Studies"],
             "https://religion.cas.lehigh.edu/faculty-staff"),
        _cas("THEA", "Department of Theatre", ["Theatre"],
             "https://theatre.cas.lehigh.edu/faculty-staff"),
        # ---- College of Business (server-side filtered directory) ---------
        _biz("ACCT", "Department of Accounting", ["Accounting"], "147"),
        _biz("DATA", "Department of Decision and Technology Analytics",
             ["Business Analytics", "Business Information Systems",
              "Supply Chain Management"], "148"),
        _biz("ECON", "Department of Economics", ["Economics"], "150"),
        _biz("FIN", "Perella Department of Finance", ["Finance"], "152"),
        _biz("MGT", "Department of Management", ["Management"], "153"),
        _biz("MKT", "Department of Marketing", ["Marketing"], "154"),
        # ---- College of Health (person-grid) ------------------------------
        {
            "short": "COH",
            "name": "College of Health",
            "majors": ["Population Health"],
            "directory_url": "https://health.lehigh.edu/faculty",
            "scrape": {
                "url": "https://health.lehigh.edu/faculty",
                "selectors": _HEALTH_SEL,
                "field_filter": _HEALTH_FIELD,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
