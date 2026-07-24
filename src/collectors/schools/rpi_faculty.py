"""Rensselaer Polytechnic Institute faculty config (via the faculty_graph engine).

Full-institute coverage: all five schools (Engineering, Science, HASS, Lally
Management, Architecture). Live-verified 2026-07-24.

Every roster is server-rendered — no WAF, no JSON API anywhere on campus. RPI
serves four distinct Drupal markup families plus one hand-built WordPress page:

* **``profile-card`` component (campus Drupal).** People render as
  ``div.profile-card.card`` grouped under sibling ``<h2>`` role headings —
  ``Faculty`` first, then ``Joint Appointment`` / ``Affiliated Faculty`` /
  ``Emeritus`` / ``Research Scientists`` / ``Graduate Students`` / ``Staff``.
  ``_FACULTY_SECTION`` keeps only the home-department ladder block, dropping the
  joint/affiliated cross-listings (home faculty of another dept — they would
  double-count now that every department is covered), the emeriti, the research
  scientists, the students, and the staff. The component has three variants for
  where the rank sits:
  - ``_SEL_SCI`` — rank in ``.profile-card-text`` (CS/PHYS/CHEM/MATH/BIO/EES,
    and Lally, which runs the same component).
  - ``_SEL_ENG`` — rank in ``.profile-card-title``; ``.profile-card-text`` here
    holds link furniture ("Google Scholar"), so it is deliberately NOT read as
    research (BME, ISE).
  - ``_SEL_MANE`` — rank in ``.profile-card-title`` AND research areas in
    ``.profile-card-text``, so MANE lands keyworded in one pass.

* **``personbox`` component (older engineering Drupal).** ECSE/CBE/MSE/CEE serve
  ``div.personbox.views-row``: name in ``.field-title``, rank in ``.position``,
  research in ``.focus-area``. ``_RANKED`` (``field_filter require_present`` on
  ``.position``) drops the rank-less rows — CEE lists five such cards, and
  without the gate the engine's "Professor" default would ship them as
  professors. CEE additionally splits ``CEE Faculty`` / ``CEE Staff`` under h2,
  and is the one department whose LISTING already carries the address
  (``.contact-info`` mailto); CBE/MSE carry none.

* **HASS ``card-title``/``card-subtitle`` variant.** The six HASS departments
  publish at ``hass.rpi.edu/departments-<dept>/<dept>-faculty`` with the name in
  ``.card-title a`` and the rank in ``.card-subtitle``. Their primary faculty
  block sits under NO heading (only the side blocks are headed), so the section
  gate here is an ``exclude`` on the side headings rather than an
  ``include`` on "Faculty".

* **Architecture — hand-built WordPress page, headless.**
  ``www.arch.rpi.edu/faculty/`` is one WP page of ``<p>`` blocks (name in
  ``<strong>`` as "Last, First", rank as the bare text after it — hence
  ``name_flip`` + ``title_html_re``). Every address is JS-cloaked
  (``<a class="mailto-link" data-enc-email="oryyq[at]ecv.rqh">`` — rot13 with a
  literal ``[at]``, which the engine's ``/at/``-keyed rot13 decoder does not
  match), so this department runs ``scrape["render"] = True``: the inline script
  writes the plaintext address into its ``<span>``, and ``.mailto-link span``
  reads it straight off the rendered DOM. 46/46 addresses recovered this way.

**Emails.** Apart from CEE and Architecture, no RPI listing exposes an address —
the cards link out to central ``faculty.rpi.edu`` profiles. Those profiles do
carry a personal ``mailto`` (spot-checked 6/6 on eleven separate departments),
so every faculty.rpi.edu-backed department runs the dept-level ``_ENRICH``
profile pass (``always: True`` — this is where the record's contact value lives,
not optional depth). The same pass lifts the profile's
``field--name-field-focus-area`` block as research areas. Net effect: the school
goes from 0% emailed (listing-only, the previous config) to ~99%.

Title gate (``_LADDER`` require ``prof|lecturer``): keeps ladder + endowed +
practice professors and lecturers; drops admin-only cards whose listing text is
a pure administrative role with no rank ("Associate Dean of Science…", the
university President) and the research-scientist rows that share a section with
faculty. It is intentionally ``prof`` (not ``professor``) so an abbreviated
"Distinguished Prof. of Computer Science" endowed title still qualifies.

Single source ("rpi_faculty"); department rides each record, ids namespaced by
department short-code.

Coverage = all 21 academic departments RPI lists at ``faculty.rpi.edu/
departments`` (7 Engineering, 6 Science, 6 HASS, Lally, Architecture); the rest
of that index is research centers and admin offices, which have no ladder
roster of their own. Live counts 2026-07-24, kept after the gates / % emailed:
MANE 56/100, ARCH 47/97, LALLY 36/100, ECSE 32/96, CS 29/100, PHYS 21/100,
MATH 21/100, BIO 21/100, CEE 20/100, CHEM 19/100, BME 18/100, COGS 18/100,
CBE 17/100, ARTS 16/100, MSE 15/100, STS 15/100, ECON 14/100, ISE 11/100,
COMM 11/100, GXM 8/100, EES 6/100 — 451 records, 99% emailed.

**Dropped / phase-2:** none. Every college in the RPI catalog resolves to a
reachable, majority-emailed roster. The only two unemailed records are one
faculty.rpi.edu profile that 403s under the rate limit of a full run (it
resolves on a retry) and the one Architecture entry whose WP paragraph carries
no cloaked address at all.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- profile-card component, science variant (rank in .profile-card-text) ---
_SEL_SCI = {
    "card": "div.profile-card.card",
    "name": ".profile-card-name a",
    "link": ".profile-card-name a",
    "title": ".profile-card-text",
}
# ---- profile-card, engineering variant (rank in .title; .text is link chrome)-
_SEL_ENG = {
    "card": "div.profile-card.card",
    "name": ".profile-card-name a",
    "link": ".profile-card-name a",
    "title": ".profile-card-title",
}
# ---- profile-card, MANE variant (rank in .title, research in .text) ---------
_SEL_MANE = {**_SEL_ENG, "research": ".profile-card-text"}
# ---- older personbox component (ECSE / CBE / MSE / CEE) ---------------------
_SEL_BOX = {
    "card": "div.personbox.views-row",
    "name": ".field-title",
    "link": "a",
    "title": ".position",
    "research": ".focus-area",
    "title_strip_after": r",\s*$",
}
# ---- CEE alone publishes the address on the listing card --------------------
_SEL_CEE = {**_SEL_BOX, "email": ".contact-info a[href^='mailto']"}
# ---- HASS variant (name in .card-title, rank in .card-subtitle) -------------
_SEL_HASS = {
    "card": "div.profile-card.card",
    "name": ".card-title a",
    "link": ".card-title a",
    "title": ".card-subtitle",
}
# ---- Architecture: WP prose page, "Last, First" in <strong>, rank after it ---
_SEL_ARCH = {
    "card": ".ezcol p",
    "name": "strong",
    "name_strip": r"[.,]\s*$",
    "link": "a",
    # The rank is bare text right after the name, with the sentence period
    # sometimes inside the <strong> and sometimes after it — eat either, then
    # keep only up to the next comma so a trailing admin role ("Professor,
    # Director of …") doesn't ride along with the rank.
    "title_html_re": r"</strong>\s*[.,]*\s*([^<,]{2,80})",
    "email": ".mailto-link span",
}

# Keep professors (ladder / endowed / distinguished / of-practice) and lecturers;
# drop admin-only listing rows (Dean/Director/President) that carry no rank word.
_LADDER = {"require": r"prof|lecturer"}
# Keep only the "Faculty" heading's cards (drops Joint/Affiliated/Emeritus/
# Research Scientists/Graduate Students/Staff on the role-grouped card pages).
_FACULTY_SECTION = {"heading": "h2", "include": r"^faculty$"}
# HASS pages leave the primary block unheaded — gate by excluding the side blocks.
_HASS_SECTION = {"heading": "h2",
                 "exclude": r"emeritus|affiliat|music fellow|staff|student"}
# CEE's own split ("CEE Faculty" vs "CEE Staff").
_CEE_SECTION = {"heading": "h2", "include": r"faculty"}
# A personbox row with an empty .position would inherit the engine's "Professor"
# default — require the rank to actually be there before trusting it.
_RANKED = {"selector": ".position", "require_present": True}

# The listing cards link out to central faculty.rpi.edu profiles, which are the
# only place an address exists (and where the focus-area research block lives).
_ENRICH = {
    "always": True,
    "email_selector": "a[href^='mailto']",
    "email_drop": r"^(admissions|info|inquiry|help|webmaster)@",
    "research_selector": ".field--name-field-focus-area .field__item",
    "timeout": 12,
    "max_retries": 1,
}


def _dept(short: str, name: str, majors: list[str], url: str, selectors: dict,
          *, section: dict | None = _FACULTY_SECTION, field: dict | None = None,
          render: bool = False, name_flip: bool = False,
          enrich: dict | None = _ENRICH) -> dict:
    """One department: a directory scrape plus the central-profile email pass."""
    scrape: dict = {"url": url, "selectors": selectors, "ladder_filter": _LADDER}
    if section:
        scrape["section_filter"] = section
    if field:
        scrape["field_filter"] = field
    if render:
        scrape["render"] = True
    if name_flip:
        scrape["name_flip"] = True
    dept = {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}
    if enrich:
        dept["profile_enrich"] = enrich
    return dept


_HASS = "https://hass.rpi.edu"

SCHOOL: dict = {
    "school_slug": "rpi",
    "source": "rpi_faculty",
    "organization": "Rensselaer Polytechnic Institute",
    "location": "Troy, NY",
    "id_prefix": "rpi",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Rensselaer Polytechnic Institute) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Science ----------------------------------------------
        _dept("CS", "Department of Computer Science",
              ["Computer Science"],
              "https://compsci.rpi.edu/people", _SEL_SCI),
        _dept("PHYS", "Department of Physics, Applied Physics, and Astronomy",
              ["Physics", "Applied Physics", "Astronomy"],
              "https://physics.rpi.edu/people", _SEL_SCI),
        _dept("CHEM", "Department of Chemistry and Chemical Biology",
              ["Chemistry", "Biochemistry and Biophysics"],
              "https://chemistry.rpi.edu/people", _SEL_SCI),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematics", "Applied Mathematics"],
              "https://math.rpi.edu/people", _SEL_SCI),
        _dept("BIO", "Department of Biological Sciences",
              ["Biology", "Biological Neuroscience", "Computational Biology",
               "Biochemistry and Biophysics"],
              "https://biology.rpi.edu/people", _SEL_SCI),
        _dept("EES", "Department of Earth and Environmental Sciences",
              ["Geology", "Environmental Science"],
              "https://earth.rpi.edu/people", _SEL_SCI),
        # ---- School of Engineering ------------------------------------------
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              "https://bme.rpi.edu/people", _SEL_ENG),
        _dept("ISE", "Department of Industrial and Systems Engineering",
              ["Industrial and Management Engineering"],
              "https://ise.rpi.edu/people", _SEL_ENG),
        _dept("MANE", "Department of Mechanical, Aerospace, and Nuclear Engineering",
              ["Mechanical Engineering", "Aeronautical Engineering",
               "Aerospace Engineering", "Nuclear Engineering"],
              "https://mane.rpi.edu/people", _SEL_MANE),
        _dept("ECSE", "Department of Electrical, Computer, and Systems Engineering",
              ["Electrical Engineering", "Computer and Systems Engineering"],
              "https://ecse.rpi.edu/people", _SEL_BOX,
              section=None, field=_RANKED),
        _dept("CBE", "Department of Chemical and Biological Engineering",
              ["Chemical Engineering"],
              "https://cbe.rpi.edu/people", _SEL_BOX,
              section=None, field=_RANKED),
        _dept("MSE", "Department of Materials Science and Engineering",
              ["Materials Engineering"],
              "https://mse.rpi.edu/people", _SEL_BOX,
              section=None, field=_RANKED),
        _dept("CEE", "Department of Civil and Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              "https://cee.rpi.edu/people", _SEL_CEE,
              section=_CEE_SECTION, field=_RANKED),
        # ---- School of Humanities, Arts, and Social Sciences -----------------
        _dept("ARTS", "Department of Arts",
              ["Electronic Arts", "Music", "Games and Simulation Arts and Sciences"],
              f"{_HASS}/departments-arts/arts-faculty", _SEL_HASS,
              section=_HASS_SECTION),
        _dept("COGS", "Department of Cognitive Science",
              ["Cognitive Science", "Psychological Science", "Philosophy"],
              f"{_HASS}/departments-cognitive-science/cognitive-science-faculty",
              _SEL_HASS, section=_HASS_SECTION),
        _dept("COMM", "Department of Communication and Media",
              ["Communication, Media, and Design", "Design, Innovation, and Society"],
              f"{_HASS}/departments-communication-and-media/"
              "communication-and-media-faculty",
              _SEL_HASS, section=_HASS_SECTION),
        _dept("ECON", "Department of Economics",
              ["Economics"],
              f"{_HASS}/departments-economics/economics-faculty", _SEL_HASS,
              section=_HASS_SECTION),
        _dept("GXM", "Department of Games and Experiential Media",
              ["Games and Simulation Arts and Sciences", "Electronic Arts"],
              f"{_HASS}/departments-games-and-experiential-media/faculty",
              _SEL_HASS, section=_HASS_SECTION),
        _dept("STS", "Department of Science and Technology Studies",
              ["Science and Technology Studies", "Sustainability Studies",
               "Design, Innovation, and Society"],
              f"{_HASS}/departments-programs-science-and-technology-studies/"
              "science-and-technology-studies-faculty",
              _SEL_HASS, section=_HASS_SECTION),
        # ---- Lally School of Management --------------------------------------
        _dept("LALLY", "Lally School of Management",
              ["Business and Management", "Business Analytics",
               "Finance, Markets, and Emerging Technologies",
               "Information Technology and Web Science",
               "Marketing and Advanced Computing"],
              "https://lally.rpi.edu/people", _SEL_SCI),
        # ---- School of Architecture ------------------------------------------
        _dept("ARCH", "School of Architecture",
              ["Architecture", "Building Sciences"],
              "https://www.arch.rpi.edu/faculty/", _SEL_ARCH,
              section=None, render=True, name_flip=True, enrich=None),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
