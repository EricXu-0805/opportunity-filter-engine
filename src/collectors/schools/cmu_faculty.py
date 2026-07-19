"""Carnegie Mellon University faculty config (via the faculty_graph engine).

CMU's colleges run a handful of shared templates on the central www.cmu.edu
CMS plus a few departmental Drupal sites — all server-rendered, no WAF
(live-verified 2026-07-18):

  * **filterable cards** (central CMS "filterable directory"):
    ``div.filterable`` with ``h2 a`` name/profile link and the role taxonomy
    in a ``data-categories`` attribute. Statistics & Data Science, Philosophy,
    Social & Decision Sciences, Psychology (core-training-faculty via
    ``link_filter``), LTI, and BME (whose first ``<p>`` carries a real rank).
  * **MCS profile blocks** (math/chem/physics/bio): per-person ``div[id]``
    blocks — ``h2`` name, rank as loose text (``title_re``), inline
    ``mailto:`` Email button, relative ``.html`` profile link, and a
    "Research Areas:" line the keyword cleaner strips the label from.
  * **ECE bios grid**: ``div > h2 a[href*='bios/']`` cards with an ``h3``
    role line (administrative roles kept; special/adjunct/courtesy dropped).
  * **Engineering "bio" cards** (schema.org/Person markup): ``div.bio`` with
    ``p.bioname`` and the rank as the first ``ul.biometa li`` — MechE, ChemE,
    CEE, MSE, and EPP share it.
  * **SCS Drupal**: CSD's ``views-table`` rows ("Last, First" + rank text +
    inline ``mailto:``) and HCII's ``person-teaser`` cards (rank + email).

Single source ("cmu_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown".

Deferred (tracked for a later pass): MLD + Robotics Institute + S3D
(client-rendered SCS directories), History/English (contact-block template
without profile links), Economics + Modern Languages (no static faculty
listing found), Heinz College and Tepper (JS directories), CFA schools
(Drama/Music/Art/Design/Architecture — nav-page or JS listings), INI.
"""

from __future__ import annotations

from .. import faculty_graph

_DROP = r"emerit"
# Loose-text rank recovery for blocks whose rank is not in its own element.
_TITLE_RE = (
    r"\b((?:University |Associate |Assistant |Visiting |Teaching |Special "
    r"|Adjunct |Research )*(?:Professor|Lecturer|Instructor)"
    r"(?:\s+(?:of|in)\s+[A-Za-z,&\- ]{3,50})?)"
)

# Central-CMS filterable directory cards (rank lives in data-categories only,
# so records default to "Professor" and the gated profile pass refines).
_FILTERABLE = {"card": "div.filterable", "name": "h2 a", "link": "h2 a"}


def _filt(short: str, name: str, majors: list[str], url: str, **extra) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _FILTERABLE, **extra}}


# MCS per-person profile blocks (math/chem/physics/bio). Math wraps each
# person in a div[id]; the other three use anonymous divs. Both legs require
# an inline mailto: so the site-header block (div#sitename, whose h2 is the
# college name) can never land as a phantom "Mellon College of Science" card.
_MCS_SELECTORS = {
    "card": ("div[id]:has(> h2):has(a[href^='mailto:']), "
             "div:has(> h2):has(> p a[href^='mailto:'])"),
    "name": "h2",
    "link": "a[href$='.html']",
    "email": "a[href^='mailto:']",
    "research": "p:-soup-contains('Research Areas')",
    "title_re": _TITLE_RE,
}


def _mcs(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _MCS_SELECTORS,
                       "ladder_filter": {"require": r"professor|lecturer|instructor",
                                         "drop": _DROP}}}


# College of Engineering shared "bio" card grid (schema.org/Person).
_ENG_SELECTORS = {
    "card": "div.bio",
    "name": "p.bioname",
    "link": "a[href*='bios/']",
    "title": "ul.biometa li",
}


def _eng(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _ENG_SELECTORS,
                       "ladder_filter": {"require": r"professor|lecturer|instructor",
                                         "drop": _DROP}}}


SCHOOL: dict = {
    "school_slug": "cmu",
    "source": "cmu_faculty",
    "organization": "Carnegie Mellon University",
    "location": "Pittsburgh, PA",
    "id_prefix": "cmu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Carnegie Mellon University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Computer Science ------------------------------------
        {"short": "CSD", "name": "Computer Science Department",
         "majors": ["Computer Science"],
         "directory_url": "https://csd.cmu.edu/people/faculty",
         "scrape": {"url": "https://csd.cmu.edu/people/faculty",
                    "selectors": {"card": "table tr",
                                  "name": "td.views-field-field-first-name a",
                                  "link": "td.views-field-field-first-name a",
                                  "email": "a[href^='mailto:']",
                                  "title_re": _TITLE_RE},
                    "name_flip": True,
                    "paginate": {"param": "page", "start": 1, "max": 8}}},
        {"short": "HCII", "name": "Human-Computer Interaction Institute",
         "majors": ["Human-Computer Interaction", "Computer Science"],
         "directory_url": "https://hcii.cmu.edu/people/faculty",
         "scrape": {"url": "https://hcii.cmu.edu/people/faculty",
                    "selectors": {"card": ".person-teaser",
                                  "name": ".faculty-content-heading h2 a",
                                  "link": ".faculty-content-heading h2 a",
                                  "title": "h3.faculty-content-heading-position",
                                  "email": "a[href^='mailto:']"}}},
        _filt("LTI", "Language Technologies Institute",
              ["Language Technologies", "Computer Science",
               "Natural Language Processing"],
              "https://lti.cs.cmu.edu/people/faculty/index.html"),
        # ---- College of Engineering ----------------------------------------
        {"short": "ECE", "name": "Department of Electrical & Computer Engineering",
         "majors": ["Electrical Engineering", "Computer Engineering"],
         "directory_url": "https://www.ece.cmu.edu/directory/faculty.html",
         "scrape": {"url": "https://www.ece.cmu.edu/directory/faculty.html",
                    "selectors": {"card": "div:has(> h2 a[href*='bios/'])",
                                  "name": "h2 a", "link": "h2 a",
                                  "title": "h3"},
                    "ladder_filter": {"drop": r"emerit|adjunct|courtesy|special faculty"}}},
        _eng("MECHE", "Department of Mechanical Engineering",
             ["Mechanical Engineering"],
             "https://www.meche.engineering.cmu.edu/directory/index.html"),
        _eng("CHEME", "Department of Chemical Engineering",
             ["Chemical Engineering"],
             "https://www.cheme.engineering.cmu.edu/directory/index.html"),
        _eng("CEE", "Department of Civil & Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "https://www.cee.engineering.cmu.edu/directory/index.html"),
        _eng("MSE", "Department of Materials Science & Engineering",
             ["Materials Science & Engineering"],
             "https://www.materials.cmu.edu/directory/index.html"),
        _eng("EPP", "Department of Engineering & Public Policy",
             ["Engineering & Public Policy"],
             "https://www.cmu.edu/epp/people/faculty/index.html"),
        _filt("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              "https://www.cmu.edu/bme/People/Faculty/index.html",
              # BME prints names as "Dr.  First Last" — strip the honorific so
              # pi_name stays a clean person name (same fix as OSU/UF configs).
              selectors={**_FILTERABLE, "title": "p",
                         "name_strip": r"^Dr\.?\s+"},
              ladder_filter={"require": r"professor|lecturer|instructor",
                             "drop": _DROP}),
        # ---- Mellon College of Science --------------------------------------
        _mcs("MATH", "Department of Mathematical Sciences", ["Mathematics"],
             "https://www.cmu.edu/math/people/faculty/index.html"),
        _mcs("CHEM", "Department of Chemistry", ["Chemistry"],
             "https://www.cmu.edu/chemistry/people/faculty/index.html"),
        _mcs("PHYS", "Department of Physics", ["Physics"],
             "https://www.cmu.edu/physics/people/faculty/index.html"),
        _mcs("BIO", "Department of Biological Sciences", ["Biological Sciences"],
             "https://www.cmu.edu/bio/people/faculty/index.html"),
        # ---- Dietrich College ------------------------------------------------
        _filt("SDS", "Department of Statistics & Data Science",
              ["Statistics & Data Science", "Data Science"],
              "https://www.cmu.edu/dietrich/statistics-datascience/people/faculty/index.html"),
        _filt("PSY", "Department of Psychology", ["Psychology", "Neuroscience"],
              "https://www.cmu.edu/dietrich/psychology/directory/index.html",
              link_filter=r"core-training-faculty/"),
        _filt("PHIL", "Department of Philosophy", ["Philosophy", "Logic"],
              "https://www.cmu.edu/dietrich/philosophy/people/faculty/index.html"),
        _filt("SDSC", "Department of Social & Decision Sciences",
              ["Social & Decision Sciences", "Behavioral Economics"],
              "https://www.cmu.edu/dietrich/sds/people/faculty/index.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
