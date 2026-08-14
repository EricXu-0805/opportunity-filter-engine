"""University of Connecticut faculty config (via the faculty_graph engine).

UConn is a WordPress monoculture: nearly every department subdomain renders the
campus-standard "person-card" component, server-side, no WAF, no JS render — a
plain browser-UA GET returns a clean 200. A card is a ``div`` whose class list
carries a ``personcount-N person-<id>`` pair; inside it an ``h4.person-name``
(wrapping the ``a.person-permalink`` profile link and a screen-reader
"(opens in new window)" span the ``name_strip`` regex removes), a
``p.person-title`` holding the rank in a ``<strong>``, an optional
``p.person-keywords`` "Research Interests: …" line, and — where the directory
exposes it — a ``p.person-email`` mailto. One shared selector set + one title
gate (``field_filter``, require ``professor|lecturer``, ``require_present`` so a
title-less staff card can't fall through the engine's default-to-"Professor")
covers the whole family; emeriti drop additionally via the engine's retired gate.

Three wrinkles the campus theme throws:

* **Listing carries no email.** Many departments render the person-card WITHOUT
  the ``p.person-email`` line — the personal address lives only on the
  ``/person/<slug>/`` profile page (still as ``.person-email``, distinct from the
  shared ``dept@uconn.edu`` footer inbox). Those departments carry a
  ``profile_enrich`` pass (``always: True`` — the email isn't optional depth,
  it's the record's contact value) that follows each profile and recovers the
  mailto. Verified 2026-07-24: physics, mathematics, are/kins/plant-landscape/
  hdfs/publicpolicy/art/animalscience come back majority-emailed this way.

* **Table variant (name + email only, no rank).** Philosophy and Natural
  Resources render a ``table.table-striped`` of ``tr.person-<id>`` rows with only
  image / ``td.person-name`` / ``td.person-email`` cells — no rank column. The
  ``data-person-groups`` attribute is the gate (card selector scopes to
  full-time/core "Faculty", dropping Affiliated/Emeritae/Adjunct/Part-Time);
  rank defaults to "Professor" since the row has none.

* **College of Engineering — one college-wide directory.** The engineering
  department subdomains have mostly migrated off the person-card template, but
  the college roster at ``engineering.uconn.edu/people/`` is ONE server-rendered
  person-card page (302 cards) whose ``person-tags`` hidden div names each
  person's school. Each engineering department scopes the shared card via
  ``:-soup-contains(<school>)`` on ``person-tags`` and keeps its ladder faculty
  (all carry a listing mailto). This recovers Electrical & Computer Engineering
  (22 emailed faculty), which the old single-department source could not supply
  cleanly. Computer Science and Mechanical keep their own richer subdomain
  rosters (CS publishes research keywords) and are listed first so the shared
  engineering-directory dedup assigns their people there.

Single source ("uconn_faculty"); department rides each record, ids namespaced by
department short-code.

DROPPED / phase-2 (verified 2026-07-24):
* Psychological Sciences (psychology.uconn.edu) — 103 person-cards but ~half are
  cross-listed AFFILIATED faculty whose home dept is elsewhere (Africana, etc.),
  and the listing carries zero email; a clean core-faculty + profile-email pass
  is a phase-2 job.
* Linguistics — person-card roster is email-less at listing AND the 11 profiles
  are a small, mixed set; phase-2 profile-enrich.
* School of Business, Digital Media & Design, Dramatic Arts, Music — the newer
  UConn "aurora" theme paints the roster client-side (Business embeds an external
  directory iframe), exposes no person-card / table / wp-json REST route, and
  403s the WP API; these need a headless render pass (phase-2).
* Pathobiology, Geosciences, Modern & Classical Languages — no reachable faculty
  directory host (subdomain does not resolve over the egress).
* Nutritional Sciences (nusc) — legacy non-person-card markup; deferred.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Shared campus person-card component ------------------------------------
_SEL = {
    "card": 'div[class*="personcount-"]',
    "name": "h4.person-name",
    "link": "h4.person-name a",
    "name_strip": r"\s*\(opens in new window\)\s*",
    "title": "p.person-title",
    "research": "p.person-keywords",
    "email": 'p.person-email a[href^="mailto:"]',
}

# Keep Professors (ladder + in-residence + distinguished) and Lecturers; drop
# emeriti/adjuncts/instructors/admin-staff. field_filter (not ladder_filter) so a
# title-less staff card can't fall through the engine's default-to-"Professor".
_FIELD = {
    "selector": "p.person-title",
    "require_present": True,
    "include": r"professor|lecturer",
}

# Profile pass for departments whose LISTING omits the mailto: follow each
# /person/<slug>/ and read its own ``.person-email`` (the personal address; the
# shared dept inbox lives in a separate footer widget, not this element). Runs
# unconditionally (``always``) because the email is the record's contact value,
# not optional depth. Only records still missing an email are fetched.
_ENRICH = {
    "always": True,
    "email_selector": '.person-email a[href^="mailto:"]',
    "email_drop": r"^[^@]*$",
    # Free: this pass already has the page open for the email. UConn adds two
    # labels the shared pattern deliberately omits — "Expertise" (Educational
    # Leadership's theme) and "Research Summary" (Molecular & Cell Biology's) —
    # both verified to head real area blocks here. Measured over 98 live
    # profiles: 29% land keywords, across 15 departments.
    "research_label_re": faculty_graph.RESEARCH_LABEL_RE.replace(
        r"|scholarly\s+interests?)", r"|scholarly\s+interests?|expertise"
                                    r"|research\s+summary)"),
    "throttle": 0.15,
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared person-card component, email at listing."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


def _dept_pe(short: str, name: str, majors: list[str], url: str) -> dict:
    """Person-card department whose email lives only on the profile page."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD,
                   "profile_enrich": _ENRICH},
    }


# ---- Table variant (name + email only; data-person-groups gates the roster) --
def _table(short: str, name: str, majors: list[str], url: str,
           group: str) -> dict:
    """A ``table.table-striped`` roster: rows are ``tr[data-person-groups]`` with
    only name/email cells. ``group`` is the CSS attribute match that keeps core
    faculty (e.g. ``[data-person-groups~="Faculty"]`` or ``*="Full-time"``)."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": {
            "card": f"tr{group}",
            "name": "td.person-name a",
            "link": "td.person-name a",
            "email": 'td.person-email a[href^="mailto:"]',
        }},
    }


# ---- College of Engineering: one college-wide person-card directory ----------
# engineering.uconn.edu/people/ renders every school on one page; the person-tags
# hidden div names each person's school. Scope the shared card by that text, then
# the rank gate keeps ladder faculty (all carry a listing mailto).
_ENG_URL = "https://engineering.uconn.edu/people/"


def _eng(short: str, name: str, majors: list[str], tag: str) -> dict:
    card = f'div[class*="personcount-"]:has(.person-tags:-soup-contains(\'{tag}\'))'
    return {
        "short": short, "name": name, "majors": majors, "directory_url": _ENG_URL,
        "scrape": {"url": _ENG_URL,
                   "selectors": {**_SEL, "card": card},
                   "field_filter": _FIELD},
    }


SCHOOL: dict = {
    "school_slug": "uconn",
    "source": "uconn_faculty",
    "organization": "University of Connecticut",
    "location": "Storrs, CT",
    "id_prefix": "uconn",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Connecticut) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Engineering: own subdomain rosters (richer) ----------
        _dept("CSE", "Department of Computer Science and Engineering",
              ["Computer Science", "Computer Engineering", "Data Science"],
              "https://computing.engineering.uconn.edu/people/faculty/"),
        _dept("ME", "School of Mechanical, Aerospace and Manufacturing Engineering",
              ["Mechanical Engineering", "Aerospace Engineering",
               "Manufacturing Engineering"],
              "https://mechanical-aerospace-manufacturing.engineering.uconn.edu/people/faculty/"),
        # ---- School of Engineering: college-wide directory, per-school scope --
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "Biomedical Engineering"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "Civil & Environmental Engineering"),
        _eng("MSE", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"],
             "Materials Science & Engineering"),
        _eng("CHE", "Department of Chemical and Biomolecular Engineering",
             ["Chemical Engineering"], "Chemical & Biomolecular Engineering"),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "Electrical and Computer Engineering"),
        # ---- College of Liberal Arts and Sciences: sciences -----------------
        # Physics and Mathematics render the person-card WITHOUT the email line
        # (mailto lives on the profile only) — profile_enrich recovers it.
        _dept_pe("PHYS", "Department of Physics", ["Physics"],
                 "https://physics.uconn.edu/people/faculty/"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              "https://chemistry.uconn.edu/faculty/"),
        _dept_pe("MATH", "Department of Mathematics",
                 ["Mathematics", "Applied Mathematics", "Actuarial Science"],
                 "https://math.uconn.edu/people/faculty/"),
        _dept("STAT", "Department of Statistics", ["Statistics", "Data Science"],
              "https://statistics.uconn.edu/faculty-directory/"),
        _dept("MCB", "Department of Molecular and Cell Biology",
              ["Molecular and Cell Biology", "Biochemistry", "Genetics"],
              "https://mcb.uconn.edu/people/"),
        _dept("PNB", "Department of Physiology and Neurobiology",
              ["Physiology and Neurobiology", "Neuroscience"],
              "https://pnb.uconn.edu/faculty/"),
        _dept("EEB", "Department of Ecology and Evolutionary Biology",
              ["Ecology and Evolutionary Biology", "Biology"],
              "https://eeb.uconn.edu/graduate-faculty/"),
        # ---- College of Liberal Arts and Sciences: social sciences ----------
        _dept("ECON", "Department of Economics", ["Economics"],
              "https://econ.uconn.edu/faculty/"),
        _dept("POLS", "Department of Political Science",
              ["Political Science"],
              "https://polisci.uconn.edu/faculty-directory/"),
        _dept("SOCI", "Department of Sociology", ["Sociology"],
              "https://sociology.uconn.edu/faculty-directory/"),
        _dept("COMM", "Department of Communication", ["Communication"],
              "https://communication.uconn.edu/faculty/"),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "https://anthropology.uconn.edu/faculty-directory/"),
        _dept("GEOG", "Department of Geography, Sustainability, Community, and Urban Studies",
              ["Geography", "Urban Studies"],
              "https://geography.uconn.edu/faculty-directory/"),
        _dept_pe("HDFS", "Department of Human Development and Family Sciences",
                 ["Human Development and Family Sciences"],
                 "https://hdfs.uconn.edu/faculty/"),
        _dept_pe("DPP", "Department of Public Policy",
                 ["Public Policy", "Public Administration"],
                 "https://publicpolicy.uconn.edu/faculty-staff-directory/"),
        # ---- College of Liberal Arts and Sciences: humanities ---------------
        _dept("ENGL", "Department of English", ["English"],
              "https://english.uconn.edu/faculty-directory/"),
        _dept("HIST", "Department of History", ["History"],
              "https://history.uconn.edu/faculty-directory-2/"),
        _table("PHIL", "Department of Philosophy", ["Philosophy"],
               "https://philosophy.uconn.edu/faculty/",
               '[data-person-groups*="Full-time Faculty"]'),
        # ---- College of Agriculture, Health and Natural Resources -----------
        _dept("AHS", "Department of Allied Health Sciences",
              ["Allied Health Sciences"],
              "https://alliedhealth.uconn.edu/faculty-staff-directory/"),
        _dept_pe("KINS", "Department of Kinesiology",
                 ["Kinesiology", "Exercise Science"],
                 "https://kins.uconn.edu/faculty/"),
        _dept_pe("ARE", "Department of Agricultural and Resource Economics",
                 ["Agricultural and Resource Economics", "Environmental Sciences"],
                 "https://are.uconn.edu/people/"),
        _dept_pe("ANSC", "Department of Animal Science", ["Animal Science"],
                 "https://animalscience.uconn.edu/faculty-staff/"),
        _dept_pe("PLSC", "Department of Plant Science and Landscape Architecture",
                 ["Plant Science", "Landscape Architecture"],
                 "https://plant-landscape.uconn.edu/directory/"),
        _table("NRE", "Department of Natural Resources and the Environment",
               ["Natural Resources", "Environmental Sciences"],
               "https://nre.uconn.edu/faculty-2/",
               '[data-person-groups="Faculty"]'),
        # ---- Neag School of Education ---------------------------------------
        # One college-wide "directory-person" roster (name/title/email inline,
        # all emailed) — not split by department in the markup, so shipped as a
        # single school unit gated to ladder/teaching faculty.
        {
            "short": "NEAG", "name": "Neag School of Education",
            "majors": ["Elementary Education", "Secondary Education",
                       "Educational Psychology", "Sport Management"],
            "directory_url": "https://education.uconn.edu/faculty-staff-directory/",
            "scrape": {
                "url": "https://education.uconn.edu/faculty-staff-directory/",
                "selectors": {
                    "card": "div.directory-person",
                    "name": "div.directory-name a",
                    "link": "div.directory-name a",
                    "title": "div.directory-title",
                    "email": 'div.directory-email a[href^="mailto:"]',
                },
                "field_filter": {
                    "selector": "div.directory-title",
                    "require_present": True,
                    "include": r"professor|lecturer",
                },
            },
        },
        # ---- School of Fine Arts --------------------------------------------
        _dept_pe("ART", "Department of Art and Art History",
                 ["Art", "Art History"],
                 "https://art.uconn.edu/people/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
