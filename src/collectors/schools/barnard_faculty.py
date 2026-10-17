"""Barnard College faculty config (via the faculty_graph engine).

Barnard is a top-tier US women's liberal arts college (~2,700 undergraduates)
in Morningside Heights, New York, academically partnered with — but
institutionally independent of — Columbia University. Its faculty are Barnard's
own (distinct from Columbia's), and every academic department publishes its
roster on a department subdomain (``<dept>.barnard.edu``) built on the same
college-wide Drupal 9 platform.

Live-verified 2026-07-22 (plain HTTP 200s via requests; the barnard.edu TLS
chain trips Python's stdlib ``ssl`` but ``requests``/``fetch_soup`` validate it
fine — no ``insecure`` needed; no Cloudflare wall, no render mode anywhere):

* ``barnard_card`` — the shared Drupal "person card" component. The platform
  ships TWO container variants with IDENTICAL inner markup:
    - ``article.cc--filtered-person-card`` (the faceted "Faculty & Staff"
      directory view — Biology, Chemistry, Anthropology, History, Physics,
      Sociology, Education, Architecture, …), and
    - ``li.cc--featured-person`` (the curated "featured people" grid used by
      the smaller departments — English, Psychology, Neuroscience, Dance,
      Comp Lit, Math, CS, French, Film, amec, …).
  Both wrap a ``.f--cta-title h3 a`` name/profile link (``/profiles/<slug>`` on
  the department subdomain), a ``.f--professional-title`` rank, an optional
  ``.f--specialization .field__item`` list (clean atomic research areas), and a
  decodable ``.f--email a[href^='mailto:']`` mailto. A single selector set with
  the two container classes ORed covers 22 departments. Verified live (fetch +
  bs4 count + sample rows) across all four divisions, e.g. English 54,
  Neuroscience 29, Psychology 28, Dance 28, Architecture 20, Biology 20,
  Chemistry 19, Comparative Literature 18, History 16, Anthropology 15,
  Sociology 15, Environmental Science 12.

Because these are "Faculty & Staff" rosters, each list mixes ladder faculty
with lecturers, lab-instructional staff, department coordinators, emeriti and
the occasional visiting/adjunct appointment. The ``ladder_filter`` keeps
professorial + lecturer ranks and drops emeriti, visiting, and adjunct
appointments; the ``require`` gate also removes non-teaching staff whose titles
carry neither "professor" nor "lecturer". Interdisciplinary programs
(Neuroscience & Behavior, American Studies, Comparative Literature) cross-list
faculty whose home department is also captured; the engine's per-school
email/url dedup collapses those to a single record, so the core disciplinary
departments are listed first.

Emails are inline mailtos on essentially every card, so no profile-enrichment
pass is needed (topics come from the specialization chips + OpenAlex).

Single source ("barnard_faculty"); department rides each record, ids namespaced
by department short-code. Audience "unknown".

Moved 2026-10 (found 2026-10-17): every ``<dept>.barnard.edu`` roster above now
redirects to a department page on the main site (``barnard.edu/<dept>``), and
the person cards are gone. The 2026-10-10 refresh fetched all 22 pages (200,
no fetch error) and parsed 0 rows. The roster is now a "department faculty
grid": ``.paragraph--type--department-faculty`` cards, each an ``h4`` name
(linked to ``/profiles/<slug>`` for faculty, ``/node/<n>`` or nothing for
staff and emeriti), a ``.field--name-field-body`` rank line and, on a few
cards only, a ``.field--name-field-email`` mailto. Specialization chips are no
longer on the listing, so research areas and the email of record come from the
profile page (``.f--email`` mailto, "Academic Focus" accordion), which the
profile pass already fetched for research areas. Ids hash the department short
code and the name, so the moved rows keep their ids.

Deferred (2026-07-22 recon): the ~15 departments that still render their roster
as hand-authored WYSIWYG prose (a ``field--name-field-description`` /
``c--body-wysiwyg`` block with inline mailtos rather than the shared person-card
component) — Classics, Cognitive Science, Economics, Art History, German,
Music, Philosophy, Political Science, Religion, Slavic, Spanish & Latin American
Cultures, Theatre, Urban Studies, Women's/Gender/Sexuality Studies, and the
First-Year Writing program. Each is bespoke prose with no shared selector, so
they are left out rather than mis-scraped; revisit if they migrate onto the
person-card component.
"""

from __future__ import annotations

from .. import faculty_graph

# The main site's department faculty grid (see "Moved 2026-10" above).
_SELECTORS = {
    "card": ".paragraph--type--department-faculty",
    "name": "h4 .field--name-field-title",
    "link": "h4 a",
    "title": ".field--name-field-body",
    "email": ".field--name-field-email a[href^='mailto:']",
}

# Keep professorial + lecturer ranks; drop emeriti, visiting, and adjunct
# appointments as well as the lab-instructional / coordinator / department
# staff whose titles carry neither "professor" nor "lecturer".
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b",
    "drop": r"emerit|\bvisiting\b|\badjunct\b",
}


def _dept(short: str, name: str, majors: list[str], path: str) -> dict:
    """A Barnard department's page on the main site, ``barnard.edu/<path>``.

    ``path`` is where the department's old subdomain roster now redirects.
    """
    url = f"https://barnard.edu/{path}"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER,
                   # Each profile's research areas live in an "Academic Focus"
                   # accordion as a clean <ul><li>, and its email under .f--email
                   # (most grid cards carry none). always:true because the
                   # weekly refresh env-gates enrich off.
                   "profile_enrich": {
                       "always": True,
                       "research_items_selector":
                           '.accordion-item h3:-soup-contains("Academic Focus") + .accordion-panel li',
                       "email_selector": ".f--email a[href^='mailto:']",
                       "throttle": 0.2,
                   }},
    }


SCHOOL: dict = {
    "school_slug": "barnard",
    "source": "barnard_faculty",
    "organization": "Barnard College",
    "location": "New York, NY",
    "id_prefix": "barnard",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Barnard College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Science & Mathematics ---------------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"],
              "biology"),
        _dept("CHEM", "Department of Chemistry",
              ["Chemistry", "Biochemistry"], "chemistry"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics"),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Statistics"], "math"),
        _dept("CS", "Department of Computer Science", ["Computer Science"],
              "computerscience"),
        _dept("ENSC", "Department of Environmental Science",
              ["Environmental Science"], "envsci"),
        _dept("PSYC", "Department of Psychology", ["Psychology"],
              "psychology"),
        _dept("NBB", "Neuroscience and Behavior Program",
              ["Neuroscience and Behavior"], "neuroscience"),
        # ---- Social Sciences ---------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "anthropology"),
        _dept("SOCI", "Department of Sociology", ["Sociology"],
              "sociology"),
        _dept("AMST", "Program in American Studies", ["American Studies"],
              "americanstudies"),
        _dept("EDUC", "Education Program", ["Education"],
              "Education"),
        # ---- Humanities --------------------------------------------------
        _dept("ENGL", "Department of English",
              ["English", "Creative Writing"], "english"),
        _dept("HIST", "Department of History", ["History"],
              "history"),
        _dept("CPLT", "Department of Comparative Literature",
              ["Comparative Literature"], "complit"),
        _dept("FREN", "Department of French", ["French"],
              "french"),
        _dept("ITAL", "Department of Italian", ["Italian"],
              "italian"),
        _dept("AMEC", "Department of Asian and Middle Eastern Cultures",
              ["Asian and Middle Eastern Cultures"], "amec"),
        _dept("AFRS", "Department of Africana Studies", ["Africana Studies"],
              "africana-studies"),
        # ---- Arts --------------------------------------------------------
        _dept("ARCH", "Department of Architecture", ["Architecture"],
              "architecture"),
        _dept("DNCE", "Department of Dance", ["Dance"],
              "dance"),
        _dept("FILM", "Film Studies Program", ["Film Studies"],
              "film"),
    ],
}


def fetch_and_normalize(deep: bool = True,
                        unit_ledger: dict | None = None) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep,
                                            unit_ledger=unit_ledger)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
