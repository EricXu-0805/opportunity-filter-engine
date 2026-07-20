"""Lehigh University faculty config (via the faculty_graph engine).

Three server-rendered markup families, all plain static 200s through the proxy
(no WAF, no JS render). Live-verified 2026-07-20.

* **P.C. Rossin College of Engineering — legacy Drupal "Views" grid (7 depts).**
  CSE, ECE, MechE, BioE, ChBE, CEE and ISE all render each person as a
  ``div.views-row`` with a ``div.views-field-title span.field-content a`` name +
  profile link (``/<dept>/faculty/<numeric-id>``) and a
  ``div.views-field-field-position div.field-content`` rank. No email is exposed
  on the listing (only a generic department address), so these seven land
  name+title+url and the per-profile enrich pass recovers the address later.
  A ``field_filter`` (not ``ladder_filter``) gates the rank: every listing ends
  with a title-less row whose text is the department name itself
  ("Computer Science & Engineering", "Bioengineering") — the person-name guard is
  too lenient to reject those, and a missing position field would otherwise
  default to "Professor" and leak through, so ``require_present`` drops the
  position-less row directly, then ``include`` keeps only professor/lecturer
  ranks (which also drops ChBE's "University President" courtesy row). Emeriti are
  dropped by the engine's own retired-title guard.

* **Materials Science & Engineering — hand-built photo grid (own selector).**
  ``/matsci/faculty`` is NOT the Views template: it is a flat ``<ul>`` of
  ``li[style*="flex-basis"]`` photo tiles with the name in one of two shapes — an
  ``.overlay`` caption anchor (13 of 15) or a bare bold-styled anchor (Helen M.
  Chan) — so the name selector matches either. The tile carries NO rank text at
  all, and the page lists only core faculty (Staff and Emeritus live on separate
  tabs), so no title gate is applied; the enrich pass fills email + rank from each
  profile. Two links use the campus ``/faculty/<slug>`` form instead of
  ``/matsci/faculty/<id>`` (shared/joint appointments) — both resolve fine.

* **College of Arts & Sciences science — "substratum/cas-profile" Drupal (3 depts).**
  physics/chemistry/math on ``*.cas.lehigh.edu`` render each person as an
  ``article`` whose class is ``cas-profile__card`` on physics/chemistry but
  ``cas_profile__card`` (underscore) on math — ``article[class*="profile__card"]``
  matches both. Name is ``h1.h1--page-title``; the rank is the FIRST of several
  repeated ``h2.field--lehigh`` headings; the profile link is
  ``a.link--arrow[href^='/faculty-staff/']``. Email is VISIBLE PLAIN TEXT (no
  mailto) inside ``div.profile__contact``: each contact row is an
  ``icon__field-wrapper`` (physics/chem) / ``icon__field_wrapper`` (math, again
  underscore) whose svg ``aria-labelledby`` names the field, so
  ``div[class*="icon__field"]:has(svg[aria-labelledby="email"]) div.field--showy``
  targets exactly the address cell (not the phone/office cells) — the engine's
  ``_clean_email`` lifts the address from its text. A ``field_filter`` gates the
  first h2 (require professor/lecturer) to drop the postdocs, lab managers,
  coordinators, business/technician staff and the visiting-faculty rows the pages
  mix in; emeriti drop via the retired-title guard. Email coverage is ~100% on all
  three.

Single source ("lehigh_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-20 (cards -> kept-after-gate): CSE 32/31, ECE 23/22,
MechE 31/30, BioE 19/18, ChBE 18/16, CEE 24/23, ISE 21/20, MatSci 15/15,
Physics 36/20, Chemistry 33/16, Math 43/25 -> 236 total. Emails land on the three
CAS departments (61/61) on the listing; the eight engineering departments land
via the per-profile enrich pass.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Rossin College of Engineering: shared Drupal "Views" grid -------------
# Each person is a div.views-row; the name link + profile href live in the
# title field, the rank in the position field. No email on the listing.
_ENG_SEL = {
    "card": "div.views-row",
    "name": "div.views-field-title span.field-content a",
    "link": "div.views-field-title span.field-content a",
    "title": "div.views-field-field-position div.field-content",
}
# field_filter (not ladder_filter): the position element must exist (drops the
# trailing department-name row, which has none and would otherwise default to
# "Professor" and pass) and must name a professor/lecturer rank (drops the
# "University President" courtesy row on ChBE). Emeriti drop via the retired gate.
_ENG_FIELD = {
    "selector": "div.views-field-field-position div.field-content",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _eng(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Rossin engineering department on the shared Views grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "field_filter": _ENG_FIELD},
    }


# ---- Materials Science & Engineering: hand-built photo grid -----------------
# li photo tiles; name in an .overlay caption anchor or a bare bold anchor. No
# rank on the tile and the page is core-faculty-only, so no title gate.
_MATSCI_SEL = {
    "card": 'li[style*="flex-basis"]',
    "name": '.overlay a, a[style*="font-weight: bold"]',
    "link": '.overlay a, a[style*="font-weight: bold"]',
}


# ---- College of Arts & Sciences: substratum/cas-profile Drupal --------------
# article[class*="profile__card"] matches both the hyphen (physics/chem) and
# underscore (math) class spellings. Rank = first h2.field--lehigh. Email is
# plain text in the contact block's email row, keyed off the svg's aria label
# (class*="icon__field" covers both spellings too).
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
# Gate the first h2 rank: require it be present and name a professor/lecturer,
# dropping postdocs, fellows, lab managers, coordinators, business/technician
# staff and visiting-faculty rows. Emeriti drop via the retired-title guard.
_CAS_FIELD = {
    "selector": "h2.field--lehigh",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _cas(short: str, name: str, majors: list[str], url: str) -> dict:
    """A CAS science department on the substratum cas-profile component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CAS_SEL, "field_filter": _CAS_FIELD},
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
            },
        },
        # ---- College of Arts & Sciences: science (cas-profile) ------------
        _cas("PHYSICS", "Department of Physics", ["Physics", "Astrophysics"],
             "https://physics.cas.lehigh.edu/faculty-staff"),
        _cas("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
             "https://chemistry.cas.lehigh.edu/faculty-staff"),
        _cas("MATH", "Department of Mathematics",
             ["Mathematics", "Applied Mathematics", "Statistics"],
             "https://math.cas.lehigh.edu/faculty-staff"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
