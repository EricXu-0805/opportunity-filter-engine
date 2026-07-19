"""University of Arizona faculty config (via the faculty_graph engine).

All seven departments run the same Arizona Digital "az_quickstart" Drupal
theme: ``article.node--type-az-person`` cards with the name in an ``<h3><a>``,
the rank as the first ``.field--name-field-az-titles .field__item``, and a
plain mailto in ``.field--name-field-az-email``. cs.arizona.edu migrated onto
the same theme, so ONE shared selector block covers every department.
Live-verified 2026-07-19 — every directory is a plain server-rendered 200
(no render mode, no WAF, no Cloudflare anywhere).

Three of the seven listings mix non-faculty into the same card grid:

* CS (``cs.arizona.edu/people/faculty``) — the full ~110-entry people
  directory folds in PhD students and staff (rank item is "PhD Student",
  "Systems Programmer", "Academic Advisor", …).
* Physics (``physics.arizona.edu/people-list``) — a combined ~260-card
  roster where grad students carry NO rank field at all (which the engine
  would otherwise default to "Professor"), so a title regex alone can't gate.
* Statistics (``stat.arizona.edu/people/faculty``) — a Graduate
  Interdisciplinary Program roster mixing M.S./Ph.D. students with
  cross-listed affiliated faculty from ~24 home departments.

The faculty gate is a ``field_filter`` on the rank item: ``require_present``
drops the title-less grad-student cards (the ones the engine would mislabel
"Professor"); ``include`` keeps only professorial ranks; ``exclude`` prunes
adjunct/emeritus (emeriti are also auto-dropped by the engine's retired-title
guard). The same gate runs on the four faculty-only engineering/chemistry
listings (ECE/AME/BME/CBC) — harmless there (nearly every card is
professorial) and it also prunes the handful of admin-title-only cards.

CS is the only listing that carries research interests on the card (an
"Interests: <comma list>" field item); the shared ``research`` selector picks
that up (the engine strips the "Interests:" label and comma-splits it). It
returns nothing on the other six, which ship name+title+email (topics come
from OpenAlex enrichment later).

Statistics/Physics faculty are cross-listed from their home departments
(Math, CS, Chemistry, Optical Sciences, …), so a few people appear under more
than one department short — genuine cross-affiliation, kept as distinct
per-department records (distinct ids).

Deferred: none — no department needed a render pass or had to be dropped.

Single source ("arizona_faculty"); department rides each record, ids
namespaced by department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# Arizona Digital "az_quickstart" person card — identical markup across all
# seven departments (engineering + College of Science + cs.arizona.edu).
_SELECTORS = {
    "card": "article.node--type-az-person",
    "name": "h3 a",
    "link": "h3 a",
    # The first title field item is the rank; Office/Interests/PhD lines are
    # sibling field items, so select_one grabs the clean rank alone.
    "title": ".field--name-field-az-titles .field__item",
    "email": ".field--name-field-az-email a[href^='mailto:']",
    # Only CS lists interests on the card ("Interests: <comma list>"); the
    # engine strips the "Interests:" label and comma-splits into keywords.
    # No such item on the other six → returns nothing (harmless to share).
    "research": '.field--name-field-az-titles .field__item:-soup-contains("Interests:")',
}

# Faculty gate on the rank item. ``require_present`` drops title-less cards
# (the physics grad-student roster the engine would default to "Professor");
# ``include`` keeps professorial ranks; ``exclude`` prunes adjunct/emeritus
# (emeriti are also auto-dropped by the engine's retired-title guard).
_FACULTY_GATE = {
    "selector": ".field--name-field-az-titles .field__item",
    "require_present": True,
    "include": r"\bprofessor\b",
    "exclude": r"emerit|adjunct",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared az_quickstart person-card component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS,
                   "field_filter": _FACULTY_GATE},
    }


SCHOOL: dict = {
    "school_slug": "arizona",
    "source": "arizona_faculty",
    "organization": "University of Arizona",
    "location": "Tucson, AZ",
    "id_prefix": "arizona",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Arizona) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        _dept("CS", "Department of Computer Science", ["Computer Science"],
              "https://cs.arizona.edu/people/faculty"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://ece.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("ME", "Department of Aerospace and Mechanical Engineering",
              ["Mechanical Engineering", "Aerospace Engineering"],
              "https://ame.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              "https://bme.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("PHYS", "Department of Physics", ["Physics", "Astrophysics"],
              "https://physics.arizona.edu/people-list"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"],
              "https://cbc.arizona.edu/directory/faculty"),
        _dept("STAT", "Statistics and Data Science (GIDP)",
              ["Statistics", "Data Science"],
              "https://stat.arizona.edu/people/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
