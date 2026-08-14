"""University of Arizona faculty config (via the faculty_graph engine).

University-wide coverage. The campus runs the Arizona Digital "az_quickstart"
Drupal theme almost everywhere, so nearly every college/department directory
server-renders a plain 200 with no WAF and no client-side painting. Two markup
families cover it, live-verified 2026-07-24:

* **az_quickstart person card (primary).** ``article.node--type-az-person``:
  name in an ``<h3><a>``, rank as the first
  ``.field--name-field-az-titles .field__item``, plain mailto in
  ``.field--name-field-az-email``. ONE shared selector block covers every
  College of Engineering department subdomain
  (``<dept>.engineering.arizona.edu/faculty-staff/faculty``), the Wyant College
  of Optical Sciences, most of the College of Science, the College of SBS
  schools, English + MENAS in Humanities, Nursing, Public Health, Education, and
  the ACBS / SNRE units in CALES — plus cs.arizona.edu and physics' /people-list.

* **az_quickstart "person card grid" (``div.card`` / ``h3.text-blue``).** A
  handful of CALES/Fine-Arts departments (Biosystems Engineering, Agricultural &
  Resource Economics, School of Plant Sciences, School of Art) render the same
  data through a Views *grid* of Bootstrap cards instead of the person node
  teaser: name in ``h3.h5.text-blue``, the rank as a bare text run between the
  ``</h3>`` and the ``.mt-3`` contact block (no element of its own — pulled with
  ``title_html_re``), mailto in ``.card-body``. Its own helper (``_card``).

The faculty gate is a ``field_filter`` on the rank text: ``require_present``
drops title-less cards (the physics/neuroscience grad-student rosters the engine
would otherwise mislabel "Professor"); ``include`` keeps professorial + lecturer
ranks; ``exclude`` prunes adjunct/emeritus (emeriti are also auto-dropped by the
engine's retired-title guard). Several listings (Optical Sciences, Linguistics,
Public Health, SNRE) fold in students/staff/affiliates into one card grid — the
gate is load-bearing there and harmless on the faculty-only engineering/chemistry
listings. The School of Art runs its own accordion theme (``div.cfa-person``,
handled by ``_cfa``).

CS is the only listing that carries research interests on the card (an
"Interests: <comma list>" field item); the shared ``research`` selector picks
that up. It returns nothing on the others, which ship name+title+email (topics
come from OpenAlex enrichment later).

GIDP / cross-listed faculty (Statistics, Neuroscience, some SNRE) are drawn from
their home departments, so a few people appear under more than one department —
genuine cross-affiliation, kept as distinct per-department records.

Dropped / phase-2 (each attempted; reason recorded):
* **Neuroscience GIDP** (``neuroscience.arizona.edu``) — server-renders az-person
  cards, but it is a graduate interdisciplinary program whose ~270-card roster is
  overwhelmingly affiliated faculty with NO email on the card (only ~9% emailed
  after gating); email-less, needs profile-enrich (phase 2).
* **Mathematics** (``math.arizona.edu/people/faculty``) — a Drupal ``views-row``
  name/office table with NO email on the listing; email-less, needs
  profile-enrich (phase 2).
* **Steward Observatory / Astronomy** (``as.arizona.edu``) — bespoke non-quickstart
  theme, zero az-person cards static; needs headless / a new adapter.
* **Eller College** (Economics, Finance, Accounting, MIS, Marketing, Management)
  — the Eller sites paint their directory client-side (no az-person cards, ~0
  mailto in the static HTML); needs headless.
* **iSchool, CAPLA (Architecture), Music/Theatre/Dance** — JS-rendered or a
  landing page with only a shared inbox; no reachable server-rendered roster.
* **Communication, Entomology, Spanish & Portuguese, East Asian Studies,
  French & Italian, Astronomy** — the subdomain TLS-resets on every proxied
  fetch (host unreachable from this egress); phase 2 from an allowed egress.
* **Philosophy** — the host 403s (WAF) even with a browser UA.

Single source ("arizona_faculty"); department rides each record, ids namespaced
by department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- az_quickstart person card (article.node--type-az-person) ------------------
# Identical markup across every engineering subdomain, Optical Sciences, most of
# the College of Science, the SBS schools, English/MENAS, Nursing, Public Health,
# Education, and ACBS/SNRE. The first title field item is the rank; Office /
# Interests / PhD lines are sibling items, so select_one grabs the clean rank.
_SELECTORS = {
    "card": "article.node--type-az-person",
    "name": "h3 a",
    "link": "h3 a",
    "title": ".field--name-field-az-titles .field__item",
    "email": ".field--name-field-az-email a[href^='mailto:']",
    # Only CS lists interests on the card ("Interests: <comma list>"); the engine
    # strips the label and comma-splits into keywords. No such item elsewhere.
    "research": '.field--name-field-az-titles .field__item:-soup-contains("Interests:")',
}

# Faculty gate on the rank item. ``require_present`` drops the title-less
# grad-student cards (the ones the engine would default to "Professor");
# ``include`` keeps professorial + lecturer ranks; ``exclude`` prunes
# adjunct/emeritus (emeriti also auto-dropped by the engine's retired-title guard).
_FACULTY_GATE = {
    "selector": ".field--name-field-az-titles .field__item",
    "require_present": True,
    "include": r"professor|lecturer",
    "exclude": r"emerit|adjunct",
}


# Arizona's listings already carry the email, so this school had no per-profile
# pass at all — and therefore no research signal outside CS (34 of 1,471 records).
# The profiles do carry it, three different ways, and the engine tries these keys
# in the order they are written: SBS & Humanities publish atomic "research-areas"
# taxonomy chips, the College of Engineering a single comma/semicolon
# "field-research-interests" line, and everything else only a label —
# quickstart writes "Research Interests", SBS "Research Areas", and the Drupal
# faculty-interests field just "Interests", which is why that word is added here
# rather than to the shared pattern.
#
# The chips are the best of the three (already atomic, no sentence-splitting) so
# they go first; the label matcher is last because it is the broadest and would
# otherwise shadow them. Measured separately: chips + line reached 2% -> 13%
# corpus-wide (#698), the label matcher 35% of 93 live profiles (#745). Neither
# subsumes the other, and the fall-through means a profile only pays for the
# next key when the previous one found nothing.
#
# No ``always``, so this runs in the monthly OFE_ENRICH_PROFILES window rather
# than adding 1,471 fetches to every weekly shard run.
_ENRICH = {
    "research_items_selector": "div.field--name-field-sbs-person-research-areas .field__item",
    "research_selector": "div.field-research-interests",
    "research_label_re": faculty_graph.RESEARCH_LABEL_RE.replace(
        r"|scholarly\s+interests?)", r"|scholarly\s+interests?|interests)"),
    "throttle": 0.2,
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared az_quickstart person-card component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS,
                   "field_filter": _FACULTY_GATE, "profile_enrich": _ENRICH},
    }


# ---- az_quickstart "person card grid" (div.card / h3.text-blue) ----------------
# CALES/Fine-Arts departments that render a Views grid of Bootstrap cards instead
# of the person-node teaser. The rank is a bare text run between the name <h3> and
# the ``.mt-3`` contact block (no element of its own), so ``title_html_re`` bounds
# it and strips tags; ``title_strip_after`` trims multi-appointment "A / B / C"
# lists to the first (a chair's leading admin role) so the display title is clean.
_CARD_SEL = {
    "card": "div.card.overflow-hidden",
    "name": "h3.text-blue",
    "email": ".card-body a[href^='mailto:']",
    "title_html_re": r"</h3>(.*?)<div[^>]*class=\"mt-3",
    "title_strip_after": r"\s*/\s*",
}
# The card grid has no per-field rank element, so gate on the whole card-body text
# (which carries the rank inline); require_present is trivially true but keeps the
# include/exclude semantics identical to the person-card gate.
_CARD_GATE = {
    "selector": ".card-body",
    "require_present": True,
    "include": r"professor|lecturer",
    "exclude": r"emerit|adjunct",
}


def _card(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the az_quickstart Views card-grid component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CARD_SEL, "field_filter": _CARD_GATE},
    }


# ---- College of Fine Arts "cfa-member-directory" (div.cfa-person) ---------------
# Fine Arts runs its own accordion directory theme (not az_quickstart): name in
# ``h3.faculty-name``, rank in ``h4.faculty-position``, mailto in
# ``a.faculty-email``. Only the School of Art roster carries per-person emails on
# the listing; gate on the position line.
_CFA_SEL = {
    "card": "div.cfa-person",
    "name": "h3.faculty-name",
    "title": "h4.faculty-position",
    "email": "a.faculty-email[href^='mailto:']",
}
_CFA_GATE = {
    "selector": "h4.faculty-position",
    "require_present": True,
    "include": r"professor|lecturer",
    "exclude": r"emerit|adjunct",
}


def _cfa(short: str, name: str, majors: list[str], url: str) -> dict:
    """A College of Fine Arts school on the cfa-member-directory component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CFA_SEL, "field_filter": _CFA_GATE},
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
        # --- College of Engineering ---
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical and Computer Engineering"],
              "https://ece.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("AME", "Department of Aerospace and Mechanical Engineering",
              ["Mechanical Engineering", "Aerospace Engineering"],
              "https://ame.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              "https://bme.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("CHEE", "Department of Chemical and Environmental Engineering",
              ["Chemical Engineering", "Environmental Engineering"],
              "https://chee.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("CAEM", "Department of Civil and Architectural Engineering and Mechanics",
              ["Civil Engineering", "Architectural Engineering"],
              "https://caem.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("MSE", "Department of Materials Science and Engineering",
              ["Materials Science and Engineering"],
              "https://mse.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("SIE", "Department of Systems and Industrial Engineering",
              ["Systems Engineering", "Industrial Engineering", "Engineering Management"],
              "https://sie.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("MGE", "Department of Mining and Geological Engineering",
              ["Mining Engineering"],
              "https://mge.engineering.arizona.edu/faculty-staff/faculty"),
        _dept("OPTI", "Wyant College of Optical Sciences",
              ["Optical Sciences and Engineering"],
              "https://www.optics.arizona.edu/people/faculty"),
        _card("ABE", "Department of Biosystems Engineering",
              ["Biosystems Engineering"],
              "https://abe.arizona.edu/people/faculty"),
        # --- College of Science ---
        _dept("CS", "Department of Computer Science", ["Computer Science"],
              "https://cs.arizona.edu/people/faculty"),
        _dept("PHYS", "Department of Physics", ["Physics", "Astrophysics"],
              "https://physics.arizona.edu/people-list"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"],
              "https://cbc.arizona.edu/directory/faculty"),
        _dept("STAT", "Statistics and Data Science (GIDP)",
              ["Statistics and Data Science", "Data Science"],
              "https://stat.arizona.edu/people/faculty"),
        _dept("MCB", "Department of Molecular and Cellular Biology",
              ["Molecular and Cellular Biology", "Biochemistry"],
              "https://mcb.arizona.edu/people/faculty"),
        _dept("EEB", "Department of Ecology and Evolutionary Biology",
              ["Ecology and Evolutionary Biology", "Biology"],
              "https://eeb.arizona.edu/people/faculty"),
        _dept("GEOS", "Department of Geosciences", ["Geosciences"],
              "https://www.geo.arizona.edu/people/faculty"),
        _dept("HAS", "Department of Hydrology and Atmospheric Sciences",
              ["Atmospheric Sciences", "Environmental Science"],
              "https://has.arizona.edu/people/faculty"),
        _dept("PSIO", "Department of Physiology", ["Physiology"],
              "https://physiology.arizona.edu/people/faculty"),
        _dept("PSYCH", "Department of Psychology", ["Psychology"],
              "https://psychology.arizona.edu/people/faculty"),
        _dept("SLHS", "Department of Speech, Language, and Hearing Sciences",
              ["Speech, Language, and Hearing Sciences"],
              "https://slhs.arizona.edu/people/faculty"),
        # --- College of Social and Behavioral Sciences ---
        _dept("GEOG", "School of Geography, Development and Environment",
              ["Geography"], "https://geography.arizona.edu/people/faculty"),
        _dept("ANTH", "School of Anthropology", ["Anthropology"],
              "https://anthropology.arizona.edu/people/faculty"),
        _dept("HIST", "Department of History", ["History"],
              "https://history.arizona.edu/people/faculty"),
        _dept("LING", "Department of Linguistics", ["Linguistics"],
              "https://linguistics.arizona.edu/people/faculty"),
        _dept("SGPP", "School of Government and Public Policy",
              ["Political Science"], "https://sgpp.arizona.edu/people/faculty"),
        _dept("SOC", "School of Sociology", ["Sociology"],
              "https://sociology.arizona.edu/people/faculty"),
        # --- College of Humanities ---
        _dept("ENGL", "Department of English", ["English"],
              "https://english.arizona.edu/people/faculty"),
        _dept("MENAS", "School of Middle Eastern and North African Studies",
              ["Middle Eastern and North African Studies"],
              "https://menas.arizona.edu/people/faculty"),
        # --- Health sciences / professional colleges ---
        _dept("NURS", "College of Nursing", ["Nursing"],
              "https://nursing.arizona.edu/people/faculty"),
        _dept("PBHL", "Mel and Enid Zuckerman College of Public Health",
              ["Public Health"], "https://publichealth.arizona.edu/people/faculty"),
        _dept("EDUC", "College of Education", ["Education"],
              "https://coe.arizona.edu/people/faculty"),
        # --- College of Agriculture, Life and Environmental Sciences ---
        _dept("ACBS", "School of Animal and Comparative Biomedical Sciences",
              ["Animal Sciences"], "https://acbs.arizona.edu/people/faculty"),
        _dept("SNRE", "School of Natural Resources and the Environment",
              ["Environmental Science", "Wildlife Conservation"],
              "https://snre.arizona.edu/people/faculty"),
        _card("AREC", "Department of Agricultural and Resource Economics",
              ["Agricultural Economics"],
              "https://arec.arizona.edu/people/faculty"),
        _card("SPLS", "School of Plant Sciences", ["Plant Sciences"],
              "https://spls.arizona.edu/people/faculty"),
        # --- College of Fine Arts ---
        _cfa("ART", "School of Art", ["Studio Art", "Art History"],
             "https://art.arizona.edu/people/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
