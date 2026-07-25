"""Stevens Institute of Technology faculty config (via the faculty_graph engine).

Twelve departments across all four colleges share ONE campus Next.js
"faculty-card" component — every page is server-rendered raw HTML behind
Cloudflare but not challenge-walled, so a plain proxied request returns a clean
static 200 (no ``render`` needed). Live-verified 2026-07-20 (engineering) and
2026-07-24 (business + arts-and-letters).

The Schaefer School of Engineering & Science exposes one roster per department
under ``/school-engineering-science/departments/<slug>/faculty``; the two
non-engineering colleges — the School of Business and the College of Arts and
Letters (served under ``/hass/``) — each publish a single combined faculty
roster (no per-program sub-pages: ``/school-business/<area>/faculty`` 404s), so
each is wired as one department carrying all of that college's majors. The
School of Systems and Enterprises is its own catalog college but lives on the
engineering base path. That is the full four-college catalog — Schaefer
SES's "Biology" major has no standalone department (it rides Chemistry &
Chemical Biology), and Software Engineering / AI / Cybersecurity are CS majors.

The component's CSS-module class names carry a per-build hash suffix
(``faculty-card_cc--faculty-card__j3sBO``, ``faculty-card_name-title__WxAmJ``)
that changes whenever the site is rebuilt, so every selector matches on a
``class*=`` PREFIX (the stable module-name part) and never the full hashed class.
One person is a ``div[class*="faculty-card_cc--faculty-card"]`` holding:

* a ``div[class*="faculty-card_name-title"]`` with an ``h3 > a`` (display name +
  ``/profile/<netid>`` link) and an ``h4`` (rank);
* a ``div[class*="faculty-card_contact-email"]`` whose ``<a>`` is a Cloudflare
  email-protection anchor wrapping ``<span class="__cf_email__" data-cfemail=…>``
  — the engine's ``_email_from_el`` XOR-decodes it, so pointing the email selector
  at that anchor yields the real address with no bespoke decoder. Email coverage
  is 100% on every department's listing (netid == email local part @stevens.edu).

Two card shapes ride the same grid: the ~44 named faculty above, and a tail of
"Adjunct" cards that carry only a rank ``h4`` and NO name link (no ``/profile/``
anchor) — those fall out on the engine's absent-name guard. Each page also mixes
in a few university officers listed with an administrative title instead of a
rank (a President, Deans, Vice Provosts, a Provost) and named adjuncts titled
plain "Adjunct" / "Adjunct – WebCampus".

Title gate (``field_filter``, require ``professor|lecturer``): ``require_present``
reads the rank ``h4`` directly and drops a card when it is absent (so a nameless
or title-less card can't fall through the engine's default-to-"Professor"), then
``include`` keeps only Professor / Lecturer ranks — dropping the officers
(President / Dean / Provost / Director) and the plain-"Adjunct" cards while
keeping every ladder / teaching / research / visiting professor and lecturer.
Emeriti (e.g. ChemE's "…& Emeritus Professor", CEOE's "Emeritus – Faculty") are
additionally dropped by the engine's own retired-title guard.

Single source ("stevens_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-20 (cards → kept-after-gate, email coverage):
CS 54→44 (44/44 email), ECE 37→20, ME 46→31, BME 16→14, Physics 23→18,
Chemistry 26→18, ChemE 12→11 (one emeritus dropped by the retired guard),
CEOE 44→23, Math 23→21, Systems 57→24 — every kept card carries a decoded
@stevens.edu address (100% listing email).
Live-verified 2026-07-24 (business + arts-and-letters):
Business 178→70, Arts-and-Letters 94→45 — both 100% @stevens.edu email.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared Stevens Next.js "faculty-card" component. Every class carries a
# per-build hash suffix, so match on the stable ``class*=`` module-name prefix.
# The email anchor is a Cloudflare email-protection link wrapping a
# ``span.__cf_email__[data-cfemail]`` the engine decodes via _email_from_el.
_SEL = {
    "card": 'div[class*="faculty-card_cc--faculty-card"]',
    "name": 'div[class*="faculty-card_name-title"] h3 a',
    "link": 'div[class*="faculty-card_name-title"] h3 a',
    "title": 'div[class*="faculty-card_name-title"] h4',
    "email": 'div[class*="faculty-card_contact-email"] a',
}

# Keep Professors (ladder + teaching + research + visiting + endowed-chair) and
# Lecturers; drop the university officers (President / Dean / Provost / Vice
# Provost / Director) and plain-"Adjunct" cards the pages mix in. field_filter
# (not ladder_filter) so a nameless/title-less card can't default to "Professor":
# require_present reads the rank h4 directly and drops the card when absent, then
# include keeps only Professor/Lecturer ranks. Emeriti drop via the retired gate.
_FIELD = {
    "selector": 'div[class*="faculty-card_name-title"] h4',
    "require_present": True,
    "include": r"professor|lecturer",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared Stevens faculty-card component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


_BASE = "https://www.stevens.edu/school-engineering-science/departments"

SCHOOL: dict = {
    "school_slug": "stevens",
    "source": "stevens_faculty",
    "organization": "Stevens Institute of Technology",
    "location": "Hoboken, NJ",
    "id_prefix": "stevens",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Stevens Institute of Technology) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        _dept("CS", "Department of Computer Science",
              ["Computer Science", "Cybersecurity"],
              f"{_BASE}/computer-science/faculty"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              f"{_BASE}/electrical-computer-engineering/faculty"),
        _dept("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"],
              f"{_BASE}/mechanical-engineering/faculty"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              f"{_BASE}/biomedical-engineering/faculty"),
        _dept("PHYS", "Department of Physics",
              ["Physics", "Applied Physics"],
              f"{_BASE}/physics/faculty"),
        _dept("CHEM", "Department of Chemistry and Chemical Biology",
              ["Chemistry", "Chemical Biology"],
              f"{_BASE}/chemistry-chemical-biology/faculty"),
        _dept("CHEME", "Department of Chemical Engineering and Materials Science",
              ["Chemical Engineering", "Materials Science and Engineering"],
              f"{_BASE}/chemical-engineering-materials-science/faculty"),
        _dept("CEOE", "Department of Civil, Environmental and Ocean Engineering",
              ["Civil Engineering", "Environmental Engineering", "Ocean Engineering"],
              f"{_BASE}/civil-environmental-ocean-engineering/faculty"),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematics", "Applied Mathematics"],
              f"{_BASE}/mathematical-sciences/faculty"),
        _dept("SSE", "School of Systems and Enterprises",
              ["Systems Engineering", "Engineering Management",
               "Industrial and Systems Engineering"],
              f"{_BASE}/systems-engineering/faculty"),
        # School of Business — one combined roster (no per-area sub-pages);
        # carries every business major. Same shared faculty-card component +
        # Cloudflare email decoder. field_filter drops the ~90 Adjunct /
        # WebCampus-adjunct / staff / dean / emeritus cards, keeping ladder,
        # teaching, research, and industry (professor-of-practice) professors +
        # lecturers. Live-verified 2026-07-24: 70 kept, 100% @stevens.edu email.
        _dept("BUS", "School of Business",
              ["Business & Technology", "Finance", "Quantitative Finance",
               "Accounting & Analytics", "Information Systems", "Economics",
               "Management", "Marketing Innovation & Analytics"],
              "https://www.stevens.edu/school-business/faculty"),
        # College of Arts and Letters — served under /hass/, one combined roster
        # (no per-program sub-pages); carries every arts-and-letters major. Same
        # component + gate; drops Adjunct / music-instructor / writing-consultant
        # / TA / dean / emeritus cards. Live-verified 2026-07-24: 45 kept,
        # 100% @stevens.edu email.
        _dept("CAL", "College of Arts and Letters",
              ["Literature", "Philosophy", "Social Sciences",
               "Quantitative Social Science", "Science Communication",
               "Music and Technology", "Visual Arts and Technology",
               "Science, Technology, and Society"],
              "https://www.stevens.edu/hass/hass-faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
