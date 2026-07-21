"""New Jersey Institute of Technology faculty config (via the faculty_graph engine).

All nine departments share ONE campus-standard Drupal "faculty-cards" directory
component — server-rendered, no WAF, no JS render needed (every recon fetch
returned a clean static 200 through the proxy). One person is an
``a.column`` profile link (protocol-relative ``//people.njit.edu/profile/<uid>``,
which ``urljoin`` resolves to ``https://people.njit.edu/profile/<uid>``) wrapping
a ``div.faculty-staff-profile-card`` that holds:

* an ``h1.name`` with the display name inverted "Last, First" (``name_flip``
  un-inverts it to "First Last");
* a ``p.title`` with the rank — emitted TWICE per card (a duplicate node), so
  ``select_one`` correctly takes the first and both the gate and the record read
  the same rank.

Because the component is uniform, one shared selector set + one title gate covers
all nine departments. The card selector keys off the profile-link href so it can
never match unrelated ``a.column`` grid furniture elsewhere on a page.

Title gate (``field_filter``, require ``professor|lecturer``): every listing
mixes ladder faculty with adjunct instructors (the single largest bucket on
Chemistry / Civil / Math), postdocs, lab technicians, program coordinators,
administrative assistants, department chairs/deans, and emeriti. A
``field_filter`` (not ``ladder_filter``) is used so a title-less card can't fall
through the engine's default-to-"Professor": ``require_present`` reads the first
``p.title`` directly and drops the card when it is absent/empty, then ``include``
keeps only Professor/Lecturer ranks (tenure-track + research + distinguished
professors, and university lecturers). Emeriti are additionally dropped by the
engine's own retired-title guard. A handful of real professors listed only by an
administrative role ("Chair", "Dean") or an abbreviated "Prof" are dropped by the
gate — accuracy over recall, so no adjunct/postdoc/staff rows leak in.

EMAIL is absent from every listing (no mailto, no obfuscation on the cards). Each
person's own profile page (``people.njit.edu/profile/<uid>``) carries a single
PLAIN ``mailto:`` (``a[href^='mailto:']`` → ``first.last@njit.edu``), so the
scrape block declares a ``profile_enrich`` with that email selector. It is gated
behind ``OFE_ENRICH_PROFILES`` (no ``always``), so the fast ``deep=True`` listing
pass lands name+title+profile-URL records and the deliberate per-profile
enrichment run recovers the addresses; research topics come from downstream
OpenAlex enrichment (the listing carries none).

Cross-department overlap (Data Science shares many appointments with Computer
Science and other units) is collapsed by the engine's profile-URL de-dup — the
same ``/profile/<uid>`` URL is only kept once, attributed to the first department
that lists it.

Single source ("njit_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-20 (cards / kept-after-gate) recorded in the onboarding run.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared NJIT Drupal "faculty-cards" component — identical markup on every
# department host. The card IS the profile anchor (a.column), scoped to the
# people.njit.edu/profile/ href so no unrelated grid column can match; the name
# h1 is "Last, First" (flipped); p.title is emitted twice so select_one takes the
# first. No email element exists on the listing — it is recovered per-profile.
_SEL = {
    "card": "a.column[href*='people.njit.edu/profile/']",
    "name": "h1.name",
    "link": ":self",
    "title": "p.title",
}

# Keep Professors (tenure-track + research + distinguished) and University
# Lecturers; drop the adjunct instructors, postdocs, lab/technical staff,
# program coordinators, administrative assistants, chairs/deans-by-role, and
# emeriti the directories mix in. field_filter (not ladder_filter) so a
# title-less card can't fall through the engine's default-to-"Professor":
# require_present reads the first p.title directly and drops the card when it is
# absent; include then keeps only Professor/Lecturer ranks. Emeriti are
# additionally dropped by the engine's retired-title gate.
_FIELD = {
    "selector": "p.title",
    "require_present": True,
    "include": r"professor|lecturer",
}

# Each profile page (people.njit.edu/profile/<uid>) exposes exactly one plain
# mailto (first.last@njit.edu). Gated behind OFE_ENRICH_PROFILES (no `always`),
# so deep=True lands name+title only and the one-shot enrichment run fills email.
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "throttle": 0.15,
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared NJIT faculty-cards component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": _SEL,
            "field_filter": _FIELD,
            "name_flip": True,
            "profile_enrich": _ENRICH,
        },
    }


SCHOOL: dict = {
    "school_slug": "njit",
    "source": "njit_faculty",
    "organization": "New Jersey Institute of Technology",
    "location": "Newark, NJ",
    "id_prefix": "njit",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (New Jersey Institute of Technology) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Ying Wu College of Computing ---------------------------------
        _dept("CS", "Department of Computer Science",
              ["Computer Science", "Data Science"],
              "https://cs.njit.edu/faculty"),
        _dept("DS", "Department of Data Science",
              ["Data Science", "Computer Science"],
              "https://datascience.njit.edu/our-people"),
        # ---- Newark College of Engineering --------------------------------
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://ece.njit.edu/our-people"),
        _dept("MIE", "Department of Mechanical and Industrial Engineering",
              ["Mechanical Engineering", "Industrial Engineering"],
              "https://mie.njit.edu/faculty"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              "https://biomedical.njit.edu/people"),
        _dept("CEE", "Department of Civil and Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              "https://civil.njit.edu/people"),
        # ---- College of Science and Liberal Arts --------------------------
        _dept("PHYS", "Department of Physics",
              ["Physics", "Applied Physics"],
              "https://physics.njit.edu/people"),
        _dept("CHEM", "Department of Chemistry and Environmental Science",
              ["Chemistry", "Environmental Science"],
              "https://chemistry.njit.edu/people"),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematical Sciences", "Applied Mathematics", "Statistics"],
              "https://math.njit.edu/our-people"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
