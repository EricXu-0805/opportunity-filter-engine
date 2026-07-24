"""University of Texas at Dallas faculty config (via the faculty_graph engine).

Full university-wide coverage across all six schools. Three markup families,
one per delivery mechanism the campus uses:

* **Erik Jonsson School of Engineering & Computer Science — static WordPress.**
  Each engineering department runs its own server-rendered WordPress site
  (``cs``/``ece``/``me``/``be``/``mse``.utdallas.edu) with plain ``mailto:``
  emails (high yield). Names are comma-inverted ("Last, First"), so ``name_flip``
  un-inverts every department. Five distinct Gutenberg-block decoders (A–D)
  handle the per-site markup; see each ``_*_SEL`` below.

* **Naveen Jindal School of Management — static "area" HTML fragments.**
  ``jsom.utdallas.edu/faculty/api.php?area=<code>`` returns a server-rendered
  ``div.stat-box`` card per person (name link, ``p.sub-heading`` rank, plain
  ``mailto:``) for each of the six academic areas. Plain HTTP 200, 100% emailed;
  no render needed.

* **Natural Sciences & Mathematics, Behavioral & Brain Sciences, Economic /
  Political / Policy Sciences, and the Bass School — the central UT Dallas
  Profiles system (headless render).** These schools' department pages ship an
  empty shell plus a jQuery plugin (``profiles-wordpress-plugin``) that carries
  the roster as a ``data-person`` username list and paints ``.profile`` cards
  client-side from ``profiles.utdallas.edu/api/v1`` (name / title / email /
  research tags). A plain GET yields no people, so these pages render HEADLESS
  (cron-safe: refresh-data.yml installs Playwright). Every card lands
  100%-emailed, and the plugin stamps each person's research-tag *slugs* as CSS
  classes on the card — so a single combined school roster splits into
  departments by scoping the card selector to a department's tag-class(es).

Shared ladder gates keep professor / lecturer / instruction ranks (incl. teaching
"of Instruction", clinical, and endowed-chair titles — all real, contactable
faculty) and drop adjunct / visiting; emeriti are dropped by the engine's own
retired-title guard.

Single source ("utdallas_faculty"); department rides each record, ids namespaced
by department short-code. Live-verified 2026-07-24.

Departments DROPPED (recorded honestly rather than shipped email-less):

* **NSM Geosciences / Sustainable Earth Systems Sciences** — its site
  (``geoscience.utdallas.edu`` / ``sustainableearth.utdallas.edu``) fails the
  TLS handshake from this environment (``SSL: UNEXPECTED_EOF_WHILE_READING``) on
  every attempt, so its roster cannot be reached or verified here. Left unwired.
* **Four Bass "Lecturer I" entries** carry no research tags at all, so the
  tag-class department split can't place them; they are the only Bass faculty the
  render misses (200 of 204 land).
"""

from __future__ import annotations

from .. import faculty_graph


# =============================================================================
# Erik Jonsson School of Engineering & Computer Science — static WordPress
# =============================================================================

# Shared ladder gate: keep every professor / lecturer / instructor rank (incl.
# teaching "of Instruction" faculty); drop research scientists, deans, and
# title-less admin/staff. "profesor" catches a typo'd rank on the CS roster.
_LADDER = {"require": r"profe?ss?or|lecturer|instructor"}


# ---- Decoder D: Computer Science wp-block-table -----------------------------
_CS_SEL = {
    "card": "figure.wp-block-table table tbody tr",
    "name": "td:first-child a",
    "name_last": "td:first-child a:nth-of-type(2)",
    "link": "td:first-child a",
    "title_html_re": r"<td>.*?<br\s*/?>(.*?)</td>",
    "email": "td a[href^='mailto:']",
}

# ---- Decoder B: ECE wp-block-columns ----------------------------------------
_ECE_SEL = {
    "card": 'div.wp-block-column:has(> ul.wp-block-list a[href^="mailto:"])',
    "name": "ul.wp-block-list > li:first-child",
    "link": "ul.wp-block-list > li:first-child a",
    "title": "ul.wp-block-list > li:nth-of-type(2)",
    "email": "a[href^='mailto:']",
    "research_re_text": r"Research Interests:\s*(.+)",
}

# ---- Decoder A (ul variant): Mechanical Engineering -------------------------
_ME_SEL = {
    "card": "ul.wp-block-list.faculty-contact",
    "name": "li:first-child strong",
    "link": "li:first-child strong a",
    "title": "li:nth-of-type(2)",
    "email": "a[href^='mailto:']",
    "research": "li.focus em",
}

# ---- Decoder A (div variant): Bioengineering --------------------------------
_BE_SEL = {
    "card": "div.wp-block-column.faculty-contact",
    "name": "ul.wp-block-list:first-of-type > li:first-child strong",
    "link": "ul.wp-block-list:first-of-type > li:first-child a",
    "title": "ul.wp-block-list:first-of-type > li:nth-of-type(2)",
    "email": "a[href^='mailto:']",
    "research": "ul.wp-block-list:nth-of-type(2)",
}

# ---- Decoder C: Materials Science centered paragraph ------------------------
_MSE_SEL = {
    "card": 'p.has-text-align-center:has(a[href^="mailto:"])',
    "name": "strong",
    "link": "a",
    "title_html_re": r"<br\s*/?>(.*?)<br\s*/?>",
    "email": "a[href^='mailto:']",
}


def _eng(short: str, name: str, majors: list[str], url: str, sel: dict) -> dict:
    """A Jonsson engineering department on one of the static block decoders."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER,
                   "name_flip": True},
    }


# =============================================================================
# Naveen Jindal School of Management — static "area" HTML fragments
# =============================================================================

_JSOM_SEL = {
    "card": "div.stat-box",
    "name": "h3.top-header a",
    "link": "h3.top-header a",
    "title": "p.sub-heading",
    "email": "a[href^='mailto:']",
}
# JSOM titles are almost all professorial ranks (incl. endowed chairs like
# "Ashbel Smith Professor" / "O.P. Jindal Distinguished Chair", "of Practice",
# "of Instruction", and "Clinical Professor"); require any of those, drop the
# lone emeritus and any adjunct/visiting.
_JSOM_LADDER = {"require": r"profess|chair|lecturer|instruct",
                "drop": r"emerit|adjunct|visiting"}


def _jsom(short: str, name: str, majors: list[str], area: str) -> dict:
    """A Jindal academic area served by the shared api.php?area=<code> fragment."""
    url = f"https://jsom.utdallas.edu/faculty/api.php?area={area}"
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": "https://jindal.utdallas.edu/faculty/",
        "scrape": {"url": url, "selectors": _JSOM_SEL, "ladder_filter": _JSOM_LADDER},
    }


# =============================================================================
# UT Dallas Profiles plugin (headless render) — NSM / BBS / EPPS / Bass
# =============================================================================
# Each card is a jQuery-cloned .profile populated from the central API. Name in
# .profile-name a; the current rank + email live in the FILLED contact-info li
# (li:not(.item-template), so the empty hidden template span is skipped); research
# tags in .profile-tags .profile-tag. On a combined school page the plugin stamps
# each person's tag-slugs as CSS classes on the card, so a department is scoped by
# its slug class(es).

_PROF_SEL = {
    "name": ".profile-name a",
    "link": ".profile-name a",
    # Element-agnostic: the combined-page plugin renders the email as a <span>
    # (EPPS/Bass) on some sites and as an <a href="mailto:…"> (BBS) on others.
    "title": "li:not(.item-template) [data-item-text='title']",
    "email": "li:not(.item-template) [data-item-text='email']",
    "research_items": ".profile-tags .profile-tag",
}
# Keep professor (incl. "Prof."-abbreviated and "of Instruction" teaching ranks),
# lecturer, and instructor; drop adjunct / visiting. Emeriti drop via the engine.
_PROF_LADDER = {"require": r"profe?ss?or|prof\.|lecturer|instruct",
                "drop": r"emerit|adjunct|visiting"}


def _prof_card(tag_slugs: list[str] | None) -> str:
    """Card selector: the whole roster, or the union of a department's tag-classes."""
    if not tag_slugs:
        return ".profiles-plugin.profile[id]"
    return ", ".join(f".profiles-plugin.profile[id].{s}" for s in tag_slugs)


def _prof(short: str, name: str, majors: list[str], url: str,
          tag_slugs: list[str] | None = None, card: str | None = None,
          directory_url: str | None = None) -> dict:
    """A profiles-plugin department (headless render). ``tag_slugs`` scopes a
    combined school page to one department; ``card`` overrides the selector for
    a per-department roster page (e.g. Math's id-less plugin variant)."""
    sel = dict(_PROF_SEL)
    sel["card"] = card or _prof_card(tag_slugs)
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": directory_url or url,
        "scrape": {"url": url, "selectors": sel, "ladder_filter": _PROF_LADDER,
                   "render": True, "render_settle": 6000},
    }


_EPPS = "https://epps.utdallas.edu/faculty/"
_BBS = "https://bbs.utdallas.edu/faculty/"
_BASS = "https://bass.utdallas.edu/people/faculty/"


SCHOOL: dict = {
    "school_slug": "utdallas",
    "source": "utdallas_faculty",
    "organization": "The University of Texas at Dallas",
    "location": "Richardson, TX",
    "id_prefix": "utdallas",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (The University of Texas at Dallas) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Erik Jonsson School of Engineering & Computer Science ----------
        _eng("CS", "Department of Computer Science",
             ["Computer Science", "Software Engineering", "Data Science"],
             "https://cs.utdallas.edu/people/faculty/", _CS_SEL),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://ece.utdallas.edu/people/tenure-system-faculty/", _ECE_SEL),
        _eng("ME", "Department of Mechanical Engineering",
             ["Mechanical Engineering"],
             "https://me.utdallas.edu/faculty/", _ME_SEL),
        _eng("BE", "Department of Bioengineering",
             ["Bioengineering", "Biomedical Engineering"],
             "https://be.utdallas.edu/people/faculty/", _BE_SEL),
        _eng("MSE", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"],
             "https://mse.utdallas.edu/ourteam/faculty/", _MSE_SEL),

        # ---- Naveen Jindal School of Management (static area fragments) -----
        _jsom("ACCT", "Accounting", ["Accounting"], "accounting"),
        _jsom("FIN", "Finance and Managerial Economics", ["Finance"], "finance"),
        _jsom("IS", "Information Systems",
              ["Information Technology and Systems"], "is"),
        _jsom("MKT", "Marketing", ["Marketing"], "marketing"),
        _jsom("OM", "Operations Management",
              ["Supply Chain Management"], "om"),
        _jsom("OSIM", "Organizations, Strategy and International Management",
              ["Business Administration", "Global Business", "Healthcare Management"],
              "osim"),

        # ---- School of Natural Sciences and Mathematics (render) -----------
        _prof("PHYS", "Department of Physics", ["Physics"],
              "https://physics.utdallas.edu/faculty/"),
        _prof("BIO", "Department of Biological Sciences",
              ["Biology", "Molecular Biology"],
              "https://biology.utdallas.edu/faculty/"),
        _prof("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"],
              "https://chemistry.utdallas.edu/research-faculty/"),
        _prof("MATH", "Department of Mathematical Sciences",
              ["Mathematics", "Actuarial Science"],
              "https://math.utdallas.edu/people/faculty/",
              card=".faculty.profiles-plugin.profile"),

        # ---- School of Behavioral and Brain Sciences (render, tag-scoped) --
        _prof("PSY", "Department of Psychology", ["Psychology"], _BBS,
              tag_slugs=["psychology-faculty", "psychological-sciences"]),
        _prof("NSCI", "Department of Neuroscience", ["Neuroscience"], _BBS,
              tag_slugs=["neuroscience-faculty"]),
        _prof("SLH", "Department of Speech, Language, and Hearing",
              ["Speech, Language, and Hearing Sciences", "Cognitive Science",
               "Child Learning and Development"], _BBS,
              tag_slugs=["slh-faculty", "communication-sciences-and-disorders",
                         "callier-faculty"]),
        # The Cognition-and-Neuroscience and Child-Learning-and-Development
        # programs are interdisciplinary: every one of their faculty is also
        # tagged psychology-faculty / neuroscience-faculty / slh-faculty and is
        # already shipped under one of the three departments above (they yield 0
        # unique records after the profile-URL de-dup), so they are not wired as
        # separate — empty — departments.

        # ---- School of Economic, Political and Policy Sciences (render) ----
        _prof("ECON", "Program in Economics", ["Economics"], _EPPS,
              tag_slugs=["economics"]),
        _prof("POLS", "Program in Political Science", ["Political Science"], _EPPS,
              tag_slugs=["political-science"]),
        _prof("SOC", "Program in Sociology", ["Sociology"], _EPPS,
              tag_slugs=["sociology"]),
        _prof("CRIM", "Program in Criminology and Criminal Justice",
              ["Criminology"], _EPPS,
              tag_slugs=["criminology-criminal-justice"]),
        _prof("GIS", "Program in Geospatial Information Sciences",
              ["Geospatial Information Sciences"], _EPPS,
              tag_slugs=["geospatial-information-science", "gis"]),
        _prof("PA", "Program in Public and Nonprofit Management",
              ["Public Affairs"], _EPPS,
              tag_slugs=["public-and-nonprofit-management", "public-policy",
                         "public-health"]),

        # ---- Harry W. Bass Jr. School of Arts, Humanities, and Technology --
        _prof("ATEC", "Arts, Technology, and Emerging Communication",
              ["Arts, Technology, and Emerging Communication"], _BASS,
              tag_slugs=["atcm", "atecphd", "emerging-media-art", "animation-games",
                         "design-creative-practice", "design-technology", "comm",
                         "communication", "communication-studies", "communication-culture",
                         "film", "art-science", "critical-media-studies", "ecs", "idea",
                         "game-studies", "games-development", "new-media", "media-studies",
                         "media-arts-and-design", "journalism", "technical-communication",
                         "professional-communication"]),
        _prof("HIST", "Historical Studies", ["Historical Studies"], _BASS,
              tag_slugs=["hist", "ahst", "religious-history", "rels"]),
        _prof("PHIL", "Philosophy and the History of Ideas", ["Philosophy"], _BASS,
              tag_slugs=["phil", "huma", "humanities", "rhet", "rhetoric", "ethics",
                         "aesthetics", "continental-philosophy", "public-speaking",
                         "interpersonal-communication"]),
        _prof("LIT", "Literature", ["Literature"], _BASS,
              tag_slugs=["lit", "litandlang", "crwt", "lang", "lats", "span", "kore",
                         "chin", "arab", "screenwriting", "minor-in-asian-studies",
                         "gender-studies"]),
        _prof("VPA", "Visual and Performing Arts",
              ["Visual and Performing Arts"], _BASS,
              tag_slugs=["vpas", "musi", "danc", "thea", "arts", "art-history",
                         "art-and-performance", "contemporary-art", "artist",
                         "painting", "visual-art", "drawing", "art-and-technology",
                         "arhm", "design", "music-performance", "directing",
                         "interdisciplinary-art"]),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
