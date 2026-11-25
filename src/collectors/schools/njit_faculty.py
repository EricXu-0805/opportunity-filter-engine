"""New Jersey Institute of Technology faculty config (via the faculty_graph engine).

All 17 department rosters publish an inverted display name and rank on an
individual profile link. The newer people-list template puts the link in a
``li.person``. The older faculty-cards template uses an ``a.column`` wrapping
``h1.name`` and two copies of ``p.title``. Both templates use the same
``people.njit.edu/profile/<uid>`` identity for profile enrichment and deduplication.

Each listing mixes professors and university lecturers with other roles such as
chairs, deans, postdocs, adjunct instructors, staff and emeriti. The title field
must contain Professor or Lecturer. A missing title is skipped, and the shared
retired-title guard excludes emeriti.

EMAIL is absent from every listing (no mailto, no obfuscation on the cards).
Each person's own profile page (``people.njit.edu/profile/<uid>``) carries a
single PLAIN ``mailto:`` (``a[href^='mailto:']`` → usually
``first.last@njit.edu``, sometimes a netid alias like ``gor@njit.edu``), so the
scrape block declares a ``profile_enrich`` with that email selector and
``always: True``. The listing has NO email at all, so the profile pass is not
optional depth — it is where the record's only contact field lives, and a
name-only NJIT record has no product value. Live-verified 100% email coverage
across all seventeen departments. The listing carries no research either, but
the profile does: a "Research Interests" block on 40% of a live 30-profile
sample (12/12 distinct, no menu bleed), read by the same pass.

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

# In both Drupal components the anchor wraps the person's name and academic rank.
_SEL = {
    "card": ("a.column[href*='people.njit.edu/profile/'], "
             "li.person > a[href*='people.njit.edu/profile/']"),
    "name": "h1.name, .text-container > div.name",
    "link": ":self",
    "title": "p.title, .text-container > ul.title-container",
}

# The title gate reads the same first matching field that the record stores.
_FIELD = {
    "selector": _SEL["title"],
    "require_present": True,
    "include": r"professor|lecturer",
}

# Each profile page (people.njit.edu/profile/<uid>) exposes exactly one plain
# mailto. always=True because the listing carries no email whatsoever — this
# pass is the record's only contact field, not optional depth.
#
# The same page carries a "Research Interests" block, so the label pass rides
# the fetch this pass already makes: no extra request for any profile. The
# label is spelled out in full on purpose — a bare `^research\b` matches the
# site-wide "Research" nav item on every profile, whose following block is the
# menu word "Academics", and 505 professors would all be tagged with it.
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "research_label_re": r"^research\s+interests?\b",
    "always": True,
    "throttle": 0.05,
}


def _dept(short: str, name: str, majors: list[str], url: str, *,
          id_names: dict[str, str] | None = None) -> dict:
    """A department publishing an NJIT profile-link roster."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "id_names": id_names or {},
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
              "https://chemistry.njit.edu/people",
              id_names={"Farnaz Shakib": "Farnaz Alipour Shakib"}),
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
              "https://hss.njit.edu/people",
              id_names={"Yelda Semizer": "Yelda Semizer Kaplan"}),
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


def fetch_and_normalize(deep: bool = True,
                        unit_ledger: dict | None = None) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep,
                                            unit_ledger=unit_ledger)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
