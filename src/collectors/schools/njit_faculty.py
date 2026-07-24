"""New Jersey Institute of Technology faculty config (via the faculty_graph engine).

FULL campus coverage — all five colleges, every department NJIT publishes a
faculty roster for (17 departments). Every one of them serves the SAME
campus-standard Drupal "faculty-cards" directory component — server-rendered,
no WAF, no JS render needed (every recon fetch returned a clean static 200
through the proxy). One person is an ``a.column`` profile link
(protocol-relative ``//people.njit.edu/profile/<uid>``, which ``urljoin``
resolves to ``https://people.njit.edu/profile/<uid>``) wrapping a
``div.faculty-staff-profile-card`` that holds:

* an ``h1.name`` with the display name inverted "Last, First" (``name_flip``
  un-inverts it to "First Last");
* a ``p.title`` with the rank — emitted TWICE per card (a duplicate node), so
  ``select_one`` correctly takes the first and both the gate and the record read
  the same rank.

Because the component is uniform campus-wide, ONE shared selector set + one
title gate + one enrichment block covers all seventeen departments. The card
selector keys off the profile-link href so it can never match unrelated
``a.column`` grid furniture elsewhere on a page.

Title gate (``field_filter``, require ``professor|lecturer``): every listing
mixes ladder faculty with adjunct instructors (the single largest bucket on
Chemistry / Civil / Math / HSS), postdocs, lab technicians, program
coordinators, administrative assistants, department chairs/deans, fabrication
staff (Hillier), librarians, and emeriti. A ``field_filter`` (not
``ladder_filter``) is used so a title-less card can't fall through the engine's
default-to-"Professor": ``require_present`` reads the first ``p.title`` directly
and drops the card when it is absent/empty, then ``include`` keeps only
Professor/Lecturer ranks (tenure-track + research + distinguished professors,
and university lecturers). Emeriti are additionally dropped by the engine's own
retired-title guard. A handful of real professors listed only by an
administrative role ("Chair", "Dean") or an abbreviated "Prof" are dropped by
the gate — accuracy over recall, so no adjunct/postdoc/staff rows leak in. The
gate does real work: it drops 86→36 on Hillier (a directory that is mostly
fabrication/marketing/center staff), 111→40 on HSS, and 23→7 on History.

EMAIL is absent from every listing (no mailto, no obfuscation on the cards).
Each person's own profile page (``people.njit.edu/profile/<uid>``) carries a
single PLAIN ``mailto:`` (``a[href^='mailto:']`` → usually
``first.last@njit.edu``, sometimes a netid alias like ``gor@njit.edu``), so the
scrape block declares a ``profile_enrich`` with that email selector and
``always: True``. The listing has NO email at all, so the profile pass is not
optional depth — it is where the record's only contact field lives, and a
name-only NJIT record has no product value. Live-verified 100% email coverage
across all seventeen departments. Research topics come from downstream OpenAlex
enrichment (the listing carries none).

Cross-department overlap (Data Science shares many appointments with Computer
Science; History and Hillier deans appear in several rosters) is collapsed by
the engine's profile-URL de-dup — the same ``/profile/<uid>`` URL is only kept
once, attributed to the first department that lists it. Several rosters also
emit the same card twice; that duplication is collapsed by the same key.

Coverage by college:

* Newark College of Engineering — BME, Chemical & Materials, Civil &
  Environmental, ECE, Mechanical & Industrial, School of Applied Engineering
  and Technology.
* Ying Wu College of Computing — Computer Science, Data Science, Informatics.
* Jordan Hu College of Science and Liberal Arts — Biological Sciences,
  Chemistry & Environmental Science, Humanities & Social Sciences, Federated
  History, Mathematical Sciences, Physics.
* Hillier College of Architecture and Design — one combined roster covering the
  New Jersey School of Architecture and the School of Art + Design.
* Martin Tuchman School of Management.

DROPPED (no roster exists — not a scrape failure):

* Theatre Arts & Technology Program (``theatre.njit.edu/our-people``) — the
  page publishes navigation only; a headless Playwright render returns 0 cards,
  0 ``/profile/`` links and 0 mailtos. It is a program, not a department, and
  its faculty are listed on the HSS roster, which is covered.
* New Jersey School of Architecture (``architecture.njit.edu/faculty``) — no
  standalone roster; headless render likewise returns 0 cards. Its "Our People"
  link resolves to the shared Hillier directory, which is covered as HCAD.
* Aerospace Studies / Air Force ROTC — military instructors, no research
  faculty and no directory.

Single source ("njit_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-24 (cards / kept-after-gate / email%) in the deep run.
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
# fabrication and marketing staff, librarians, program coordinators,
# administrative assistants, chairs/deans-by-role, and emeriti the directories
# mix in. field_filter (not ladder_filter) so a title-less card can't fall
# through the engine's default-to-"Professor": require_present reads the first
# p.title directly and drops the card when it is absent; include then keeps only
# Professor/Lecturer ranks. Emeriti are additionally dropped by the engine's
# retired-title gate.
_FIELD = {
    "selector": "p.title",
    "require_present": True,
    "include": r"professor|lecturer",
}

# Each profile page (people.njit.edu/profile/<uid>) exposes exactly one plain
# mailto. always=True because the listing carries no email whatsoever — this
# pass is the record's only contact field, not optional depth.
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "always": True,
    "throttle": 0.05,
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
        _dept("INFO", "Department of Informatics",
              ["Information Systems", "Information Technology",
               "Business and Information Systems", "Human-Computer Interaction",
               "Web & Information Systems"],
              "https://informatics.njit.edu/people"),
        # ---- Newark College of Engineering --------------------------------
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://ece.njit.edu/our-people"),
        _dept("MIE", "Department of Mechanical and Industrial Engineering",
              ["Mechanical Engineering", "Industrial Engineering"],
              "https://mie.njit.edu/faculty"),
        _dept("CME", "Otto H. York Department of Chemical and Materials Engineering",
              ["Chemical Engineering", "Materials Science and Engineering"],
              "https://cme.njit.edu/people"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              "https://biomedical.njit.edu/people"),
        _dept("CEE", "Department of Civil and Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              "https://civil.njit.edu/people"),
        _dept("SAET", "School of Applied Engineering and Technology",
              ["Construction Engineering Technology",
               "Mechanical Engineering Technology",
               "Concrete Industry Management", "General Engineering"],
              "https://appliedengineering.njit.edu/our-people"),
        # ---- Jordan Hu College of Science and Liberal Arts ------------------
        _dept("PHYS", "Department of Physics",
              ["Physics", "Applied Physics"],
              "https://physics.njit.edu/people"),
        _dept("CHEM", "Department of Chemistry and Environmental Science",
              ["Chemistry", "Environmental Science", "Biochemistry",
               "Forensic Science"],
              "https://chemistry.njit.edu/people"),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematical Sciences", "Applied Mathematics", "Statistics"],
              "https://math.njit.edu/our-people"),
        _dept("BIO", "Federated Department of Biological Sciences",
              ["Biology", "Biochemistry"],
              "https://biology.njit.edu/our-people"),
        _dept("HSS", "Department of Humanities and Social Sciences",
              ["Communication and Media", "Psychology",
               "Science, Technology and Society",
               "Theatre Arts and Technology", "Law, Technology and Culture"],
              "https://hss.njit.edu/people"),
        _dept("HIST", "Federated Department of History",
              ["History", "Science, Technology and Society"],
              "https://history.njit.edu/people"),
        # ---- Hillier College of Architecture and Design ---------------------
        # One combined roster serves both the New Jersey School of Architecture
        # and the School of Art + Design; neither publishes a separate one.
        _dept("HCAD", "Hillier College of Architecture and Design",
              ["Architecture", "Digital Design", "Industrial Design",
               "Interior Design"],
              "https://design.njit.edu/our-people"),
        # ---- Martin Tuchman School of Management ----------------------------
        _dept("MGMT", "Martin Tuchman School of Management",
              ["Business", "Financial Technology"],
              "https://management.njit.edu/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
