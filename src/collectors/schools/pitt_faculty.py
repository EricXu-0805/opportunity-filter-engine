"""University of Pittsburgh faculty config (via the faculty_graph engine).

Three markup families, all live-verified 2026-07-19:

* **Drupal 'views-row' (CS, Physics & Astronomy).** ``div.views-row`` cards with
  the name in ``.views-field-title`` and the rank on the listing (CS:
  ``.views-field-field-title``; Physics: a nested ``.field-position``). The email
  is written by an inline ``<script>`` that sets ``innerHTML`` to a mailto whose
  every character is a *decimal HTML entity* (``&#109;&#97;…``) — BeautifulSoup
  keeps that script text raw (the visible field is empty) and the engine's
  text/href email path never html-unescapes it, so there is **no usable listing
  email** for either dept. CS's profile page hides the personal address behind
  the same obfuscation (its only plain mailto is the ``computer.science@pitt.edu``
  dept inbox), so CS ships email-less; its profiles do carry a clean
  ``.field-research-interests`` bullet list, recovered by the gated profile pass.
  Physics profiles DO publish a plain personal mailto (plus the ``dept@phyast``
  inbox, dropped), so the gated pass backfills Physics emails. CS's front rows are
  social-link utility cells (no ``.views-field-title``) — auto-skipped by the name
  guard. Physics' one listing mixes emeritus/adjunct/secondary/research-staff, so
  a title ``ladder_filter`` keeps only ladder + research-professor ranks.

* **engineering.pitt.edu WordPress grids (ECE, MEMS, BME).** One shared card set
  (``.l-grid--faculty-archive .l-grid-item`` → ``h4.h5`` name, ``.bio-info .title``
  rank, card ``a`` → ``/people/faculty/<slug>/`` profile). Each page stacks several
  role grids under sibling ``h2`` headings (Chair / Faculty / Primary Faculty vs
  Secondary Faculty / Research Faculty / Adjunct / Emeritus) — a ``section_filter``
  keeps only the home-department ladder (BME's 174 Secondary cross-listings and the
  adjunct/emeritus grids drop). Headshots are base64-inlined (pages run 5–18 MB) but
  a plain fetch reads them fine. Email + rank live on the profile; research is only
  prose/publication text (no clean tag block), so the gated pass backfills the
  personal mailto only (``mailto://addr`` double-slash form) — topics come from
  OpenAlex.

* **'pitt_25' thin Drupal (Chemistry).** ``div.views-row`` cards carrying only a
  name + ``/people/<slug>`` link (paginated), everything else on the profile. The
  clean 36-name roster is faculty-only; the gated pass reads the personal mailto
  (dropping the ``chemhelp@`` inbox) and, where present, the
  ``field--name-field-research-interests`` bullet list. Records default to
  "Professor" (no listing rank) — acceptable because the listing carries no
  non-faculty.

Single source ("pitt_faculty"); department rides each record, ids namespaced by
department short-code. Emails/research land via the gated OFE_ENRICH_PROFILES pass
(the listings alone give clean name + rank + department for every dept but
Chemistry, which is name + link).

Deferred:
* **Statistics** (stat.pitt.edu/people/faculty, same pitt_25 theme) — the
  "faculty" view is misconfigured to list PhD students and staff alongside the
  real faculty (ID-style ``nis220@pitt.edu`` addresses, no rank), and the
  profiles carry no reliable rank field (most real professors lack the
  "Appointments" section that one or two have), so there is no signal to filter
  the non-faculty out. No cleaner faculty-only URL exists (all probed 404).
  Dropped rather than ship a roster padded with students.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Drupal 'views-row' family (CS, Physics) -------------------------------
_VIEWS_CARD = "div.views-row"
_VIEWS_NAME = ".views-field-title .field-content"
_VIEWS_LINK = ".views-field-field-person-img a[href]"

# Physics ladder: keep tenure/teaching + research-PROFESSOR ranks; drop emeritus,
# adjunct, secondary (cross-listed home elsewhere), part-time, lab instructors,
# and bare research staff (research assistant/associate/scientist NOT "…Professor").
_PHYS_LADDER = {
    "drop": (r"emerit|adjunct|\bsecondary\b|part-?time|lab instructor"
             r"|research (?:associate|assistant|scientist)(?!\s+professor)"),
}
# CS lists full-time faculty only; drop the lone visiting appointment (+ any emeritus).
_CS_LADDER = {"drop": r"visiting|emerit"}

# CS profiles keep a clean "Specific Research Interests" bullet list; the personal
# email stays entity-obfuscated on the profile too, so enrich = research only.
_CS_ENRICH = {
    "research_items_selector": ".field-research-interests ul li",
    "throttle": 0.2,
}
# Physics profiles publish a plain personal mailto (+ the dept inbox, dropped).
_PHYS_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^dept@|@phyast\.pitt\.edu$",
    "throttle": 0.2,
}

# ---- engineering.pitt.edu WordPress grids (ECE, MEMS, BME) -----------------
_ENG_SELECTORS = {
    "card": ".l-grid--faculty-archive .l-grid-item",
    "name": "h4.h5",
    "link": "a",
    "title": ".bio-info .title",
}
# Keep only the home-department ladder grid; the role heading is the sibling h2
# ("Chair" / "Interim Chair" / "Faculty" / "Primary Faculty"). "Secondary Faculty",
# "Research Faculty", "Adjunct …", and any "… Emeritus" grid are excluded.
_ENG_SECTION = {"heading": "h2",
                "include": r"^(?:(?:interim )?chair|(?:primary )?faculty)$"}
# Email on the profile is a personal mailto (double-slash "mailto://addr" form the
# engine's regex still recovers); drop obvious shared inboxes. No clean research block.
_ENG_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^(?:info|webmaster|contact|department|dept|engineering)@",
    "throttle": 0.2,
}

# ---- 'pitt_25' thin Drupal (Chemistry) -------------------------------------
_CHEM_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^chemhelp@|^help@",
    "research_items_selector": ".field--name-field-research-interests .field__item li",
    "throttle": 0.2,
}


SCHOOL: dict = {
    "school_slug": "pitt",
    "source": "pitt_faculty",
    "organization": "University of Pittsburgh",
    "location": "Pittsburgh, PA",
    "id_prefix": "pitt",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Pittsburgh) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Computing and Information ---------------------------
        {
            "short": "CS", "name": "Department of Computer Science",
            "majors": ["Computer Science"],
            "directory_url": "https://www.cs.pitt.edu/people/full-time-faculty",
            "scrape": {
                "url": "https://www.cs.pitt.edu/people/full-time-faculty",
                "selectors": {
                    "card": _VIEWS_CARD,
                    "name": _VIEWS_NAME,
                    "link": _VIEWS_LINK,
                    "title": ".views-field-field-title .field-content",
                },
                "ladder_filter": _CS_LADDER,
                "profile_enrich": _CS_ENRICH,
            },
        },
        # ---- Swanson School of Engineering ---------------------------------
        {
            "short": "ECE",
            "name": "Department of Electrical and Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://www.engineering.pitt.edu/departments/electrical-computer/people/faculty/",
            "scrape": {
                "url": "https://www.engineering.pitt.edu/departments/electrical-computer/people/faculty/",
                "selectors": _ENG_SELECTORS,
                "section_filter": _ENG_SECTION,
                "profile_enrich": _ENG_ENRICH,
            },
        },
        {
            "short": "MEMS",
            "name": "Department of Mechanical Engineering and Materials Science",
            "majors": ["Mechanical Engineering", "Materials Science and Engineering"],
            "directory_url": "https://www.engineering.pitt.edu/departments/mems/People/faculty/",
            "scrape": {
                "url": "https://www.engineering.pitt.edu/departments/mems/People/faculty/",
                "selectors": _ENG_SELECTORS,
                "section_filter": _ENG_SECTION,
                "profile_enrich": _ENG_ENRICH,
            },
        },
        {
            "short": "BME", "name": "Department of Bioengineering",
            "majors": ["Bioengineering", "Biomedical Engineering"],
            "directory_url": "https://www.engineering.pitt.edu/departments/bioengineering/people/faculty/",
            "scrape": {
                "url": "https://www.engineering.pitt.edu/departments/bioengineering/people/faculty/",
                "selectors": _ENG_SELECTORS,
                "section_filter": _ENG_SECTION,
                "profile_enrich": _ENG_ENRICH,
            },
        },
        # ---- Kenneth P. Dietrich School of Arts and Sciences ---------------
        {
            "short": "PHYS", "name": "Department of Physics and Astronomy",
            "majors": ["Physics", "Astronomy"],
            "directory_url": "https://www.physicsandastronomy.pitt.edu/people/faculty",
            "scrape": {
                "url": "https://www.physicsandastronomy.pitt.edu/people/faculty",
                "selectors": {
                    "card": _VIEWS_CARD,
                    "name": _VIEWS_NAME,
                    "link": _VIEWS_LINK,
                    "title": ".field-position",
                },
                "ladder_filter": _PHYS_LADDER,
                "profile_enrich": _PHYS_ENRICH,
            },
        },
        {
            "short": "CHEM", "name": "Department of Chemistry",
            "majors": ["Chemistry"],
            "directory_url": "https://www.chem.pitt.edu/people/faculty",
            "scrape": {
                "url": "https://www.chem.pitt.edu/people/faculty",
                "selectors": {
                    "card": _VIEWS_CARD,
                    "name": ".views-field-title .field-content a",
                    "link": ".views-field-title a[href]",
                },
                "paginate": {"param": "page", "start": 1, "max": 8},
                "profile_enrich": _CHEM_ENRICH,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
