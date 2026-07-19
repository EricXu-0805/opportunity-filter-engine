"""Tufts University faculty config (via the faculty_graph engine).

Every Tufts Arts, Sciences & Engineering (AS&E) department site runs the same
server-rendered Drupal theme (Fastly-fronted, no WAF, no render mode anywhere;
~90 recon fetches all clean 200s, live-verified 2026-07-19). There is exactly
ONE selector family university-wide:

* ``person_card`` — the shared Drupal "person-card" component. Each person is
  an anchor ``a.person-card`` whose ``href`` is the profile node
  (``/<dept>/node/NNNN`` on the hub sites, ``/node/NNNN`` on the subdomain
  sites), so the link selector is ``":self"``. Inside the card: the name in
  ``.person-name`` (an ``<h3>`` wrapping ``.person__name-link``; the text
  carries hard newlines between first/last that the engine whitespace-collapses),
  the rank in ``.person-title``, and a free-text ``.research-interests-text``
  block. The research block is a clean comma-separated topic list on most cards
  (e.g. CS "Programming languages, software engineering, security"); on some it
  is a newline-separated list or a topic list followed by a bio paragraph — the
  engine's ``_clean_keywords`` (3–60 chars, ≤6 words, junk-gated, cap 8) drops
  the prose runs, so only clean topics survive.

The family spans three host layouts, all identical markup:
  1. School of Arts & Sciences hub departments — ``as.tufts.edu/<slug>/people/faculty``
  2. School of Engineering departments — ``engineering.tufts.edu/<slug>/people/faculty``
  3. A&S departments on their own subdomain — ``<host>.tufts.edu/people/faculty``
     (Chemistry, Mathematics, Cognitive Science, Theatre/Dance/Performance).

Listings carry NO email — every profile node exposes a plain ``mailto:`` whose
FIRST occurrence is the person's own address (verified across CS/ME/Biology/
Math: the person's ``first.last@tufts.edu`` precedes any dept inbox like
``biology@tufts.edu`` / ``meinfo@tufts.edu``). The env-gated ``profile_enrich``
pass backfills email from each profile; ``email_drop`` guards the generic
``info@`` / ``dept@`` inboxes. The listing title is authoritative (profile
pages do not repeat ``.person-title``), so enrich recovers email only.

Role gating: ``ladder_filter`` requires a professor/lecturer/instructor rank
(keeps teaching, research, and practice professors plus lecturers) and drops
emeritus, adjunct, affiliate, visiting, and courtesy appointments. The
require gate alone also sheds the "Affiliate", "Senior Scientist", "Visiting
Scholar", "Manager …", and "Vice Provost …" rows the directories interleave.

Interdisciplinary programs (Environmental Studies, Data Analytics, Film &
Media, Race/Colonialism/Diaspora, WGSS, ILCS, Cognitive Science) cross-list
faculty whose primary appointment is a disciplinary department. Because each
Tufts department is a separate Drupal site, a cross-listed person has a
DISTINCT profile URL per site, so the engine's url/id dedup does not collapse
them in the un-enriched pass — the shared ``contact_email`` recovered by the
central enriched run (and ``collapse_same_person_faculty``) merges them,
keeping the keyword-richer record. Per-dept counts below therefore match the
live rosters; the net corpus is smaller after enrichment.

Single source ("tufts_faculty"); department rides each record, ids namespaced
by short-code. Audience "unknown".

Deferred (2026-07-19 recon):
* The professional schools — Fletcher (international affairs), Friedman
  (nutrition), School of Dental Medicine, School of Medicine, and Cummings
  (veterinary) — each run a different Drupal directory (no ``person-card``
  markup; nutrition.tufts.edu/faculty is a bespoke card grid). Clinical/
  professional faculty need their own gate, like other schools' medical tails.
* Judaic Studies — ``/judaic-studies/people/faculty`` 404s (people list under a
  program page, not the standard people path).
* Leadership / Museum Studies / International Relations program pages — tiny,
  entirely-cross-listed administrative rosters; covered via their home depts.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- the single university-wide person-card family -------------------------
_SEL = {
    "card": "a.person-card",
    "name": ".person-name",
    "link": ":self",
    "title": ".person-title",
    # The ``.research-interests-text`` block leads with a clean comma-separated
    # topic list on its FIRST line, then (on many cards) a bio paragraph after a
    # blank line. Capturing only that first line — text after the class-attr
    # open tag up to the first ``<`` or newline — keeps the topic list and drops
    # the prose (a bare ``research`` selector would swallow the paragraph and
    # newline-joined runs into keywords).
    "research_re": r'research-interests-text[^>]*>\s*([^<\n]{3,400})',
}

# Keep the professor/lecturer/instructor ladder (incl. teaching/research/
# practice professors); drop emeriti and secondary appointments that inflate
# cross-listing.
_LADDER = {
    "require": r"professor|lecturer|instructor",
    "drop": r"emerit|adjunct|affiliat|visiting|courtesy",
}

# The person's own first.last@tufts.edu is the first mailto on every profile;
# email_drop only fires on the generic dept inboxes that some profiles append.
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^(?:\w*info|info|contact|office|admin|dept|department|advising)@",
    "throttle": 0.3,
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared Drupal person-card component."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _SEL, "ladder_filter": _LADDER,
                       "profile_enrich": _ENRICH}}


def _as(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A School of Arts & Sciences hub department (as.tufts.edu/<slug>)."""
    return _dept(short, name, majors, f"https://as.tufts.edu/{slug}/people/faculty")


def _eng(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A School of Engineering department (engineering.tufts.edu/<slug>)."""
    return _dept(short, name, majors,
                 f"https://engineering.tufts.edu/{slug}/people/faculty")


def _sub(short: str, name: str, majors: list[str], host: str) -> dict:
    """An A&S department on its own subdomain (<host>.tufts.edu)."""
    return _dept(short, name, majors, f"https://{host}.tufts.edu/people/faculty")


SCHOOL: dict = {
    "school_slug": "tufts",
    "source": "tufts_faculty",
    "organization": "Tufts University",
    "location": "Medford, MA",
    "id_prefix": "tufts",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Tufts University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Engineering -----------------------------------------
        _eng("CS", "Department of Computer Science", ["Computer Science"], "cs"),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], "ece"),
        _eng("ME", "Department of Mechanical Engineering",
             ["Mechanical Engineering"], "me"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], "cee"),
        _eng("CHBE", "Department of Chemical and Biological Engineering",
             ["Chemical Engineering", "Biological Engineering"], "chbe"),
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "bme"),
        # ---- Arts & Sciences: natural sciences & mathematics ---------------
        _as("PHYS", "Department of Physics and Astronomy",
            ["Physics", "Astrophysics"], "physics"),
        _as("BIO", "Department of Biology", ["Biology"], "biology"),
        _sub("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"], "chem"),
        _sub("MATH", "Department of Mathematics", ["Mathematics"], "math"),
        _as("ECS", "Department of Earth and Climate Sciences",
            ["Earth and Climate Sciences", "Geology"], "ecs"),
        _sub("COGS", "Program in Cognitive Science", ["Cognitive Science"], "cogsci"),
        _as("DATA", "Program in Data Analytics",
            ["Data Analytics", "Data Science"], "dataanalytics"),
        _as("ENVS", "Program in Environmental Studies",
            ["Environmental Studies"], "environmentalstudies"),
        # ---- Arts & Sciences: social sciences ------------------------------
        _as("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _as("ECON", "Department of Economics", ["Economics"], "economics"),
        _as("POLS", "Department of Political Science", ["Political Science"],
            "politicalscience"),
        _as("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _as("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _as("UEP", "Department of Urban and Environmental Policy and Planning",
            ["Urban and Environmental Policy and Planning"], "uep"),
        _as("EPCSHD", "Eliot-Pearson Department of Child Study and Human Development",
            ["Child Study and Human Development"], "epcshd"),
        _as("EDUC", "Department of Education", ["Education"], "education"),
        _as("OT", "Department of Occupational Therapy",
            ["Occupational Therapy"], "occupationaltherapy"),
        # ---- Arts & Sciences: humanities & arts ----------------------------
        _as("ENG", "Department of English", ["English", "Creative Writing"], "english"),
        _as("HIST", "Department of History", ["History"], "history"),
        _as("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _as("REL", "Department of Religion", ["Religion"], "religion"),
        _as("CLS", "Department of Classical Studies", ["Classical Studies"],
            "classicalstudies"),
        _as("ILCS", "Department of International Literary and Cultural Studies",
            ["German", "Russian", "Arabic", "Chinese", "Japanese",
             "International Literary and Cultural Studies"], "ilcs"),
        _as("ROM", "Department of Romance Studies",
            ["French", "Spanish", "Italian"], "romancestudies"),
        _as("ARTH", "Department of the History of Art and Architecture",
            ["History of Art and Architecture", "Architectural Studies"],
            "art-architecture"),
        _sub("TDPS", "Department of Theatre, Dance, and Performance Studies",
             ["Theatre", "Dance", "Performance Studies"], "tdps"),
        _as("MUS", "Department of Music", ["Music"], "music"),
        _as("FMS", "Program in Film and Media Studies",
            ["Film and Media Studies"], "fms"),
        _as("WGSS", "Program in Women's, Gender, and Sexuality Studies",
            ["Women's, Gender, and Sexuality Studies"], "wgss"),
        _as("RCD", "Program in Studies in Race, Colonialism, and Diaspora",
            ["Race, Colonialism, and Diaspora"], "rcd"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
