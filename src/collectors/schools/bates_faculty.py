"""Bates College faculty config (via the faculty_graph engine).

Bates is a highly ranked US liberal arts college (~1,800 undergraduates, no
graduate school) in Lewiston, Maine. Its public site is a WordPress multisite
where every academic department is its own blog under ``bates.edu/<dept>/``,
but they all share ONE roster component, so a single selector family covers
the whole college — no per-department bespoke markup.

Live-verified 2026-07-23 (~40 clean HTTP 200s via curl + bs4, no WAF, no
Cloudflare interstitial, no render mode anywhere):

* ``bates_dir`` — the shared ``div.faculty-profile.profile-row`` card. Each
  card carries ``h3.profile-name > a`` (name + an ``/<dept>/faculty-profile/<slug>``
  profile link), ``h4.profile-title`` (rank, e.g. "Assistant Professor of
  Physics", named chairs like "Charles A. Dana Professor of Sociology", and the
  occasional abbreviated "Prof of …"), ``div.departmental-associations`` (home
  department), and ``p.contact-meta`` with a plain ``mailto:`` and a ``tel:``.
  Public institutional emails are inline for essentially every professor, so no
  profile-enrichment pass is needed (topics come from OpenAlex; keywords are
  left empty at scrape time).

Most departments expose the roster at ``bates.edu/<dept>/faculty/``; a handful
use a different page slug (Physics & Astronomy, Mathematics, and Digital &
Computational Studies use ``faculty-staff``; Art & Visual Culture uses
``faculty-2``; Music uses ``music-faculty``) — captured per-department below.

The ``ladder_filter`` keeps professorial + lecturer + instructor ranks
(``\\bprof`` also catches the abbreviated "Prof" chair titles) and drops
emeriti, visiting, and adjunct appointments plus the non-teaching staff (lab
"Assistant in Instruction", machinists, technicians) whose titles carry no
professorial rank. The engine additionally drops emeritus/emerita titles
unconditionally.

Bates cross-lists many professors onto interdisciplinary programs
(Environmental Studies, Africana, American/European/Latin American & Latinx
Studies, Gender & Sexuality Studies) whose program pages reuse the same card
markup with a program-namespaced profile URL. Because the shared institutional
email is inline on every card, the engine's per-school contact-email dedup
collapses a cross-listed professor to a single record; the core departments are
therefore listed FIRST so each professor attributes to a home department, and
the interdisciplinary programs are listed AFTER (they still contribute the
professors whose only appointment is the program).

Single source ("bates_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown".

Deferred (2026-07-23 recon): Asian Studies — its ``/asian-studies/faculty/``
page lists cross-appointed faculty as prose without the shared profile-row card
markup; those instructors surface under their home departments (Chinese/
Japanese are taught through cross-listing), so adding it would only yield
email-deduped duplicates with arbitrary attribution.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.bates.edu"

# Person card on the shared Bates WordPress faculty-profile roster component.
_SELECTORS = {
    "card": "div.faculty-profile.profile-row",
    "name": "h3.profile-name",
    "link": "h3.profile-name a",
    "title": "h4.profile-title",
    "email": "p.contact-meta a[href^='mailto:']",
}

# Keep professorial (incl. abbreviated "Prof"), lecturer, and instructor ranks;
# drop emeriti, visiting, and adjunct appointments plus the non-teaching staff
# whose titles carry no professorial rank.
_LADDER = {
    "require": r"\bprof|\blecturer\b|\binstructor\b",
    "drop": r"emerit|\bvisiting\b|\badjunct\b",
}


def _dept(short: str, name: str, majors: list[str], slug: str,
          path: str = "faculty") -> dict:
    """A Bates department on the shared faculty-profile roster template."""
    url = f"{_BASE}/{slug}/{path}/"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "bates",
    "source": "bates_faculty",
    "organization": "Bates College",
    "location": "Lewiston, ME",
    "id_prefix": "bates",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Bates College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Sciences & Mathematics ----------------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"], "chemistry"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics-astronomy", path="faculty-staff"),
        _dept("MATH", "Department of Mathematics", ["Mathematics"],
              "mathematics", path="faculty-staff"),
        _dept("NRSC", "Program in Neuroscience", ["Neuroscience"], "neuroscience"),
        _dept("ECS", "Department of Earth and Climate Sciences",
              ["Earth and Climate Sciences"], "earth-climate-sciences"),
        _dept("DCS", "Program in Digital and Computational Studies",
              ["Digital and Computational Studies"],
              "digital-computational-studies", path="faculty-staff"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        # ---- Social Sciences -----------------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("POLT", "Department of Politics", ["Politics"], "politics"),
        _dept("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "anthropology"),
        _dept("EDUC", "Department of Education", ["Educational Studies"],
              "education"),
        # ---- Humanities ----------------------------------------------------
        _dept("ENG", "Department of English", ["English"], "english"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("REL", "Department of Religious Studies", ["Religious Studies"],
              "religious-studies"),
        _dept("CMS", "Department of Classical and Medieval Studies",
              ["Classical and Medieval Studies"], "classical-medieval-studies"),
        _dept("RFSS", "Department of Rhetoric, Film, and Screen Studies",
              ["Rhetoric, Film, and Screen Studies"], "rhetoric"),
        _dept("FRE", "Department of French and Francophone Studies",
              ["French and Francophone Studies"], "french"),
        _dept("HISP", "Department of Hispanic Studies", ["Hispanic Studies"],
              "hispanic-studies"),
        _dept("GRS", "Department of German and Russian Studies",
              ["German", "Russian"], "german-russian-studies"),
        # ---- Arts ----------------------------------------------------------
        _dept("AVC", "Department of Art and Visual Culture",
              ["Art and Visual Culture", "Studio Art"], "art-visual-culture",
              path="faculty-2"),
        _dept("MUS", "Department of Music", ["Music"], "music",
              path="music-faculty"),
        _dept("THDA", "Department of Theater and Dance", ["Theater", "Dance"],
              "theater-dance"),
        # ---- Interdisciplinary programs (cross-listed; listed after cores) -
        _dept("ENVR", "Program in Environmental Studies",
              ["Environmental Studies"], "environmental-studies"),
        _dept("AFR", "Program in Africana", ["Africana"], "africana"),
        _dept("AMST", "Program in American Studies", ["American Studies"],
              "american-studies"),
        _dept("EUS", "Program in European Studies", ["European Studies"],
              "european-studies"),
        _dept("GSS", "Program in Gender and Sexuality Studies",
              ["Gender and Sexuality Studies"], "gender-sexuality-studies"),
        _dept("LALS", "Program in Latin American and Latinx Studies",
              ["Latin American and Latinx Studies"],
              "latin-american-latinx-studies"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
