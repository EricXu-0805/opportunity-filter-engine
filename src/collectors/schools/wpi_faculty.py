"""Worcester Polytechnic Institute faculty config (via the faculty_graph engine).

All departments share ONE component: WPI's campus Drupal "directory widget".
Every ``/academics/departments/<slug>/faculty-staff`` page renders each person as
an ``article.dw_wrapper`` — a single selector set covers the whole school. Every
page is plain server-rendered HTML through the proxy (no WAF, no JS render);
live-verified 2026-07-24.

Coverage is UIUC-parity: the full four-college catalog (School of Engineering,
The Business School, School of Arts & Sciences, The Global School) — 19 wired
departments (up from the original 10 STEM cores). Every real department that
publishes a faculty roster is wired; catalog majors whose faculty live in an
interdisciplinary overlay are mapped onto the home department (see below).

Two non-obvious URL facts, both live-verified 2026-07-24:

* **Mechanical & Materials Engineering** keeps the legacy slug
  ``mechanical-engineering`` — the current catalog slug
  ``mechanical-materials-engineering`` has NO working ``/faculty-staff`` page
  (returns 0 cards). The legacy slug serves the full 35-card roster.
* **The Business School** sits OFF the ``/academics/departments/`` tree at
  ``/academics/business/`` and serves its roster (same widget) at
  ``/academics/business/leadership-faculty-and-staff`` — the
  ``/academics/departments/business`` path 404s. Its 45 cards include deans and
  associate deans, but every one carries a "…Professor of …" title, so the gate
  keeps 31 rank-bearing faculty and drops the title-less administrators.

Cross-listing is handled by the engine, not by pruning departments: ``deep``
``fetch_and_normalize`` dedups every record by ``contact_email`` and profile URL
across departments, first-listed wins. So departments are ordered home-first and
the two interdisciplinary overlays kept (Data Science, IMGD) are listed LAST —
their shared people attribute to the home department and only their genuinely
distinct faculty add. Overlays that netted ZERO distinct faculty after the
email-dedup are NOT wired (they would fetch a page and contribute nothing); their
catalog majors ride the home department's ``majors`` list instead:

* Industrial Engineering → folded into The Business School (all 9 IE faculty —
  Sarkis, Konrad, Saberi, Trapp, Towner, Zhu, … — appear on the Business roster).
* Bioinformatics & Computational Biology → Biology & Biotechnology + CS + Chem +
  Math already carry all 28; 0 net.
* International & Global Studies → overlay of Humanities & Arts + Social Science &
  Policy Studies + Integrative & Global Studies; ~0 net.
* Environmental Engineering → within Civil, Environmental & Architectural Eng.
* Professional Writing → within Humanities & Arts (9/10 shared).
* Psychological & Cognitive Sciences → within Social Science & Policy Studies
  (7/9 shared).
* AI / Cybersecurity / Systems Eng / Manufacturing Eng / Learning Sciences —
  cross-listing overlays of CS/ECE/Business, not catalog majors; captured via
  those home departments.
* Neuroscience — no reachable faculty-staff roster (0 cards).

Per card:

* ``a.dw__name_link`` — the display name (clean "First Last") wrapping the profile
  link (faculty → ``/people/faculty/<slug>``, staff → ``/people/staff/<slug>``,
  relative to www.wpi.edu);
* ``div.dw__title`` — the rank as leading text followed by a
  ``a.dw__title_link`` that repeats the home department (so ``get_text`` yields
  "rank + department", exactly like Case Western's ``p.media-title``); the gate
  reads this directly;
* ``a.dw__email_link[href^='mailto:']`` — a PLAIN mailto on every card
  (~100% coverage on the listing; no per-profile crawl needed).

Note the WPI edge emits UNQUOTED href attributes (``href=/people/faculty/x``,
``href=mailto:x``) — bs4/lxml parse these fine. A short/stripped ~115KB response
is an intermittent light-cache variant; a re-fetch returns the full page (every
recon fetch here landed the full page, 250-450KB).

Title gate (``field_filter``, require ``professor|lecturer|instructor``): the
faculty-staff pages mix in department staff (administrative associates, lab
managers, operations/grant/program managers, technicians) and title-less
administrators (interim deans, a president, a vice provost) — the require gate
drops every one because none carry a rank word, while keeping ladder /
teaching / research / affiliate / adjunct professors, lecturers, and WPI's
full-time Instructors and Senior Instructors. ``field_filter`` (not
``ladder_filter``) with ``require_present`` reads ``div.dw__title`` directly so a
title-less staff card can't fall through the engine's default-to-"Professor".
The ``exclude`` drops Mathematical Sciences' two "Instructor's Associate" support
roles that would otherwise ride the ``instructor`` alternation on a substring
match. Emeriti (none currently listed on these pages) would drop via the
engine's own retired-title guard.

Single source ("wpi_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-24 (kept-after-gate & email% AFTER cross-department
email/URL dedup, home-first ordering): CS 44, ECE 25, ME 35, BME 32, Physics 20,
Chemistry 23, ChemE 15, Robotics 15, DataSci 8, Math 43, Aerospace 13,
Civil/Env/Arch 15, Fire Protection 5, Biology 21, Humanities & Arts 62,
Social Science & Policy 22, Integrative & Global 26, Business 31, IMGD 6 →
461 faculty, 100% email (plain mailto on every card). A per-run ±few variance on
a couple of departments (BME/Physics) is the intermittent light-cache stub noted
above; a re-fetch returns the full page and richer-dedup keeps prior records.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared WPI campus Drupal "directory widget" — identical markup on every
# department's /faculty-staff page. Card is ``article.dw_wrapper``; the name link
# doubles as the profile link; ``div.dw__title`` holds the rank followed by a
# department link (so its text is "rank + department", read directly by the gate);
# the email is a plain mailto on every card.
_SEL = {
    "card": "article.dw_wrapper",
    "name": "a.dw__name_link",
    "link": "a.dw__name_link",
    "title": "div.dw__title",
    "email": "a.dw__email_link[href^='mailto:']",
}

# Keep professors (ladder + teaching + research + affiliate + adjunct), lecturers,
# and WPI's full-time Instructors / Senior Instructors; drop the admin/lab/ops
# staff and title-less administrators the faculty-staff pages mix in. field_filter
# (not ladder_filter) so a title-less staff card can't default to "Professor":
# require_present reads div.dw__title directly and drops the card when absent,
# include then keeps only rank-bearing titles. exclude removes Math's two
# "Instructor's Associate" support roles caught by the ``instructor`` substring.
_FIELD = {
    "selector": "div.dw__title",
    "require_present": True,
    "include": r"professor|lecturer|instructor",
    "exclude": r"instructor.s\s+associate",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A WPI department on the shared directory-widget template."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


_BASE = "https://www.wpi.edu/academics/departments"

SCHOOL: dict = {
    "school_slug": "wpi",
    "source": "wpi_faculty",
    "organization": "Worcester Polytechnic Institute",
    "location": "Worcester, MA",
    "id_prefix": "wpi",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Worcester Polytechnic Institute) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Engineering ----
        _dept("CS", "Department of Computer Science",
              ["Computer Science"],
              f"{_BASE}/computer-science/faculty-staff"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical and Computer Engineering", "Electrical Engineering",
               "Computer Engineering"],
              f"{_BASE}/electrical-computer-engineering/faculty-staff"),
        _dept("ME", "Department of Mechanical and Materials Engineering",
              ["Mechanical Engineering", "Materials Science and Engineering"],
              # legacy slug — the catalog slug mechanical-materials-engineering
              # has no working /faculty-staff page (0 cards).
              f"{_BASE}/mechanical-engineering/faculty-staff"),
        _dept("AERO", "Aerospace Engineering Department",
              ["Aerospace Engineering"],
              f"{_BASE}/aerospace-engineering/faculty-staff"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              f"{_BASE}/biomedical-engineering/faculty-staff"),
        _dept("CHE", "Department of Chemical Engineering",
              ["Chemical Engineering"],
              f"{_BASE}/chemical-engineering/faculty-staff"),
        _dept("CEE", "Department of Civil, Environmental, and Architectural Engineering",
              ["Civil Engineering", "Environmental Engineering",
               "Architectural Engineering"],
              # legacy slug — omits "architectural" from the catalog slug.
              f"{_BASE}/civil-environmental-engineering/faculty-staff"),
        _dept("RBE", "Robotics Engineering Department",
              ["Robotics Engineering"],
              f"{_BASE}/robotics-engineering/faculty-staff"),
        _dept("FPE", "Department of Fire Protection Engineering",
              ["Fire Protection Engineering"],
              f"{_BASE}/fire-protection-engineering/faculty-staff"),
        # ---- School of Arts & Sciences ----
        _dept("PHYS", "Department of Physics",
              ["Physics", "Applied Physics"],
              f"{_BASE}/physics/faculty-staff"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"],
              f"{_BASE}/chemistry-biochemistry/faculty-staff"),
        _dept("BIO", "Department of Biology and Biotechnology",
              ["Biology and Biotechnology",
               "Bioinformatics and Computational Biology"],
              f"{_BASE}/biology-biotechnology/faculty-staff"),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematical Sciences", "Actuarial Mathematics",
               "Applied Mathematics", "Statistics"],
              f"{_BASE}/mathematical-sciences/faculty-staff"),
        _dept("HUA", "Department of Humanities and Arts",
              ["Humanities and Arts", "Professional Writing"],
              f"{_BASE}/humanities-arts/faculty-staff"),
        _dept("DS", "Data Science Program",
              ["Data Science"],
              f"{_BASE}/data-science/faculty-staff"),
        # ---- The Business School (off the /departments/ tree) ----
        _dept("BUS", "The Business School",
              ["Business", "Financial Technology",
               "Information Systems and Technologies", "Management Engineering",
               "Industrial Engineering"],
              "https://www.wpi.edu/academics/business/leadership-faculty-and-staff"),
        # ---- The Global School ----
        _dept("SSPS", "Department of Social Science and Policy Studies",
              ["Economic Science", "Policy Studies", "Psychological Science",
               "Social Science"],
              f"{_BASE}/social-science-policy-studies/faculty-staff"),
        _dept("IGSD", "Department of Integrative and Global Studies",
              ["International and Global Studies",
               "Environmental and Sustainability Studies",
               "Liberal Arts and Engineering",
               "Interdisciplinary (Individually Designed)"],
              f"{_BASE}/integrative-global-studies/faculty-staff"),
        # ---- Interdisciplinary overlay, listed LAST so its shared faculty
        # attribute to their home department (CS / Humanities & Arts) and only
        # its distinct game/art faculty add net via the engine's email dedup. ----
        _dept("IMGD", "Interactive Media and Game Development Program",
              ["Interactive Media & Game Development",
               "Interactive Media & Game Development Technology"],
              f"{_BASE}/interactive-media-game-development/faculty-staff"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
