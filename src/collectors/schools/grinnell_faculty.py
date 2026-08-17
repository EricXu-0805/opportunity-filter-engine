"""Grinnell College faculty config (via the faculty_graph engine).

Grinnell is a top liberal-arts college (~1,700 undergraduates, no graduate
schools) in Grinnell, Iowa, known for its open curriculum and its flagship
Mentored Advanced Project (MAP) research. The public site is a single Drupal
build: every academic department publishes its roster on one shared
"profile listing" view at ``grinnell.edu/profiles/<dept>/faculty``, so ONE
selector family covers the whole college — no per-department bespoke markup.

Live-verified 2026-07-22 (all plain HTTP 200s via curl, no WAF, no render mode
anywhere):

* ``grinnell_dir`` — the shared Drupal ``.user`` profile-list card. Each person
  is a ``div.user`` block: the name + profile link is ``.user__name a`` (a
  ``/user/<id>`` profile page), the rank is ``.user__position`` ("Professor",
  "Associate Professor", "Assistant Professor", "Senior Lecturer",
  "Instructor", "Professor Emeritus", "Visiting Assistant Professor", …), and
  the public email is a plain ``mailto:`` under ``.user__email``. Emails are
  inline for the large majority of professors. A gated pass follows canonical
  numeric ``/user/<id>`` pages to establish the profile-level tracking baseline;
  current sampling found no structured research signal there.

Sample verified live (``.user`` card counts before ladder gating): Biology 18,
Chemistry 19, Economics 20, Mathematics & Statistics 21, History 16, Physics
12, Psychology 12, Political Science 16, English 17, Computer Science 11.

The correct profiles slug is the department's Drupal machine name (which often
differs from the /academics/majors-concentrations URL slug — e.g. Mathematics
is ``mathematics-statistics``, not ``math``; Gender/Women's/Sexuality Studies
is ``gender-womens-sexuality-studies``, not ``gender``). An unknown/invalid
slug silently falls back to the full 368-person all-college directory, so every
slug below was individually verified to return its own department's roster.

Ladder gate keeps professorial + lecturer + instructor ranks (the
cold-emailable research/teaching faculty, incl. MAP mentors) and drops emeriti
and visiting appointments, plus (via the require gate) the applied-music
associates and departmental staff whose titles carry no professorial rank.

Single source ("grinnell_faculty"); department rides each record, ids
namespaced by department short-code. Grinnell professors are frequently
cross-listed onto an interdisciplinary concentration and their home department
(e.g. a Biology professor also under Biological Chemistry, Neuroscience, or
Environmental Studies); the core departments are listed FIRST and the
concentrations after, and the engine's per-school email/url dedup collapses the
cross-listings to a single record attributed to the home department.

Deferred: General Literary Studies and standalone Arabic (``/profiles`` views
return 0 — their faculty surface under the parent language departments); the
plain ``art``/``math``/``gender`` slugs (they resolve to the 368-person
all-college fallback — the qualified slugs above are used instead).
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.grinnell.edu/profiles"

# Person card on the shared Grinnell Drupal ".user" profile-list view.
_SELECTORS = {
    "card": "div.user",
    "name": ".user__name a",
    "link": ".user__name a",
    "title": ".user__position",
    "email": ".user__email a[href^='mailto:']",
}

# Keep professorial + lecturer + instructor ranks; drop emeriti and visiting
# appointments. The require gate also drops the "Applied Music Associate" and
# "Senior Faculty"/staff rows (no professorial rank) that share the markup.
_LADDER = {
    "require": r"professor|lecturer|instructor",
    "drop": r"emerit|visiting",
}


# The listing carries no research; each person has a /user/<id> profile.
_ENRICH = {
    "research_label_re": faculty_graph.RESEARCH_LABEL_RE,
    "profile_url_re": r"^https://www\.grinnell\.edu/user/\d+/?(?:[?#].*)?$",
    "throttle": 0.15,
}


def _dept(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A Grinnell department on the shared /profiles/<slug>/faculty view."""
    url = f"{_BASE}/{slug}/faculty"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER,
                   "profile_enrich": _ENRICH},
    }


SCHOOL: dict = {
    "school_slug": "grinnell",
    "source": "grinnell_faculty",
    "organization": "Grinnell College",
    "location": "Grinnell, IA",
    "id_prefix": "grinnell",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Grinnell College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Science & Mathematics --------------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("PHYS", "Department of Physics", ["Physics", "Astronomy"],
              "physics"),
        _dept("MATS", "Department of Mathematics and Statistics",
              ["Mathematics", "Statistics"], "mathematics-statistics"),
        _dept("CSC", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("BCHM", "Biological Chemistry Program", ["Biological Chemistry"],
              "biological-chemistry"),
        _dept("NEUR", "Neuroscience Program", ["Neuroscience"], "neuroscience"),
        _dept("ENVS", "Environmental Studies Program", ["Environmental Studies"],
              "environmental-studies"),
        _dept("SMS", "Science, Medicine, and Society Program",
              ["Science, Medicine, and Society"], "science-medicine-society"),
        # ---- Social Sciences --------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "anthropology"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("POL", "Department of Political Science", ["Political Science"],
              "political-science"),
        _dept("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("EDUC", "Department of Education", ["Education"], "education"),
        _dept("GDS", "Global Development Studies Program",
              ["Global Development Studies"], "global-development-studies"),
        _dept("POLS", "Policy Studies Program", ["Policy Studies"],
              "policy-studies"),
        _dept("PCS", "Peace and Conflict Studies Program",
              ["Peace and Conflict Studies"], "peace-conflict-studies"),
        # ---- Humanities --------------------------------------------------
        _dept("ENGL", "Department of English", ["English"], "english"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELS", "Department of Religious Studies", ["Religious Studies"],
              "religious-studies"),
        _dept("CLAS", "Department of Classics", ["Classics"], "classics"),
        _dept("LING", "Linguistics Concentration", ["Linguistics"],
              "linguistics"),
        _dept("SPAN", "Department of Spanish", ["Spanish"], "spanish"),
        _dept("FRAB", "Department of French and Arabic", ["French", "Arabic"],
              "french-arabic"),
        _dept("GERM", "Department of German Studies", ["German Studies"],
              "german-studies"),
        _dept("RCEE",
              "Department of Russian, Central European, and Eurasian Studies",
              ["Russian"], "russian-central-european-eurasian-studies"),
        _dept("EAS", "Department of Chinese and Japanese",
              ["Chinese", "Japanese"], "chinese-japanese"),
        _dept("AMST", "American Studies Concentration", ["American Studies"],
              "american-studies"),
        _dept("ADS", "African Diaspora Studies Concentration",
              ["African Diaspora Studies"], "african-diaspora-studies"),
        _dept("GWSS",
              "Gender, Women's, and Sexuality Studies Concentration",
              ["Gender, Women's, and Sexuality Studies"],
              "gender-womens-sexuality-studies"),
        _dept("EUST", "European Studies Concentration", ["European Studies"],
              "european-studies"),
        _dept("DGST", "Digital Studies Concentration", ["Digital Studies"],
              "digital-studies"),
        # ---- Arts --------------------------------------------------------
        _dept("ART", "Department of Art (Studio Art)", ["Studio Art"],
              "studio-art"),
        _dept("ARTH", "Department of Art History", ["Art History"],
              "art-history"),
        _dept("MUS", "Department of Music", ["Music"], "music"),
        _dept("THDP", "Department of Theatre, Dance, and Performance Studies",
              ["Theatre", "Dance", "Performance Studies"],
              "theatre-dance-performance-studies"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
