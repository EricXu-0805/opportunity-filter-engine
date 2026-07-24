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
faculty) and drop adjunct / visiting. Emeriti usually go with the engine's own
retired-title guard, but the NSM department pages list theirs under a heading
with an ordinary "Professor - <dept>" title, so those pages also gate on the
roster grid they sit in (``_ACTIVE_SECTION``).

Single source ("utdallas_faculty"); department rides each record, ids namespaced
by department short-code. Live-verified 2026-07-25.

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
# The name cell is hand-edited and splits a name across two or three anchors
# ("Alagar, " + "Sridhar"), so ``name_last`` re-joins the second one. One row
# also hyperlinks the person's endowed chair from the same cell
# (chairs.utdallas.edu, "Research Initiation Chair") — counting that as the
# surname produced the corrupted "Sanda Research Initiation Chair Harabagiu",
# so the name anchors exclude the endowed-chair microsite. Email hrefs are
# inconsistently written: most are ``mailto:``, a few are the bare address
# (``href="sruthi.chappidi@utdallas.edu"``), so match on the "@" instead.
_CS_SEL = {
    "card": "figure.wp-block-table table tbody tr",
    "name": "td:first-child a:not([href*='chairs.utdallas.edu'])",
    "name_last": "td:first-child a:not([href*='chairs.utdallas.edu']):nth-of-type(2)",
    # Seven faculty with no profile page yet are linked to the placeholder
    # ``profiles.utdallas.edu/#``; taking it as their profile URL made them one
    # duplicated person, so six real professors never shipped. Skip it and let
    # them fall back to the department directory.
    "link": "td:first-child a:not([href$='#'])",
    "title_html_re": r"<td>.*?<br\s*/?>(.*?)</td>",
    "email": "td a[href*='@']",
}

# ---- Decoder B: ECE wp-block-columns ----------------------------------------
# Several rows keep an EMPTY leftover anchor from the row they were copied from
# (``<a href="mailto:poras@utdallas.edu"></a><a href="mailto:sxa176730@…">…</a>``)
# — taking the first mailto there hands a student a different professor's
# address, so only anchors that actually render an address qualify.
_ECE_SEL = {
    "card": 'div.wp-block-column:has(> ul.wp-block-list a[href^="mailto:"])',
    "name": "ul.wp-block-list > li:first-child",
    "link": "ul.wp-block-list > li:first-child a",
    "title": "ul.wp-block-list > li:nth-of-type(2)",
    "email": "a[href^='mailto:']:not(:empty)",
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
# The rank is normally the second line, but the department head's card puts
# "Department Head" there and her rank on the line below — reading only line 2
# gave her a rank-less title that the ladder gate then dropped, so the whole
# department's head was missing from the corpus. Fall through to line 3 when
# line 2 is the administrative role (selector lists resolve in document order,
# so ordinary cards still take line 2).
_BE_SEL = {
    "card": "div.wp-block-column.faculty-contact",
    "name": "ul.wp-block-list:first-of-type > li:first-child strong",
    "link": "ul.wp-block-list:first-of-type > li:first-child a",
    "title": ('ul.wp-block-list:first-of-type > li:nth-of-type(2)'
              ':not(:-soup-contains("Department Head")), '
              'ul.wp-block-list:first-of-type > li:nth-of-type(3)'),
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
    # The central Profiles system stores the rank with the person's department
    # appended ("Professor - Physics", "Assist. Prof. of Instruction — Biological
    # Sciences"), which the record's prose splices in front of the name:
    # "Research opportunity with Professor - Physics Yuri Gartstein in the
    # Department of Physics…". Cut the suffix at the separator. A dash followed
    # by another RANK is part of a real compound title ("Bert Moore Chair in
    # BrainHealth - Professor - Department of Psychology") and must survive, or
    # the ladder gate would drop the person entirely; an unspaced hyphen is left
    # alone so hyphenated words ("Cross-Cultural") stay intact.
    "title_strip_after": (r"(?:\s*[–—]\s*|\s+-\s*|-\s+)"
                          r"(?!\s*(?:Prof\.|Professor|Assoc|Assist|Clinical|"
                          r"Research|Lect|Instruct))"),
}
# Keep professor (incl. "Prof."-abbreviated and "of Instruction" teaching ranks),
# lecturer, and instructor; drop adjunct / visiting. Emeriti drop via the engine.
_PROF_LADDER = {"require": r"profe?ss?or|prof\.|lecturer|instruct",
                "drop": r"emerit|adjunct|visiting"}


# A hire announced before they arrive is listed with the start date inside the
# name ("Ioulia Kovelman (Starts Fall 2026)") — not yet a contactable UT Dallas
# lab, and the parenthetical would ride into pi_name.
_NOT_ARRIVED = ':not(:has(.profile-name a:-soup-contains("(Starts")))'

# The NSM department pages stack several rosters on one URL, each an h2/h3
# heading followed by its own ``.profiles-container`` grid — active ranks first,
# then "Emeritus Professors" / "Emeritus Faculty" / "Retired Faculty" /
# "In Memoriam". Those trailing groups carry ordinary "Professor - <dept>"
# titles (no "emeritus" token for the engine's retired-title guard to catch), so
# only the grid's position tells them apart: keep every container EXCEPT one
# introduced by a retired-group heading. Affiliated/cross-listed groups stay —
# they are the only listing for a few active faculty.
_ACTIVE_SECTION = (
    "div.profiles-plugin.profiles-container:not("
    ":is(h2,h3,h4):-soup-contains('Emeritus') + div, "
    ":is(h2,h3,h4):-soup-contains('Retired') + div, "
    ":is(h2,h3,h4):-soup-contains('Memoriam') + div) "
)

# Physics lists a professor who left for another university but still appears on
# the roster with his new address (chuanwei.zhang@wustl.edu). An address outside
# utdallas.edu is the tell that the listing is stale; a card with no address at
# all is unaffected (``field_filter`` passes an empty field).
_UTD_EMAIL_ONLY = {
    "selector": "li:not(.item-template) [data-item-text='email']",
    "exclude": r"@(?!(?:[\w-]+\.)*utdallas\.edu\b)",
}


def _prof_card(tag_slugs: list[str] | None) -> str:
    """Card selector: the whole roster, or the union of a department's tag-classes."""
    if not tag_slugs:
        return ".profiles-plugin.profile[id]"
    return ", ".join(f".profiles-plugin.profile[id].{s}" for s in tag_slugs)


def _gated(card: str, section_gate: bool) -> str:
    """Apply the active-roster gates to every branch of a card selector union."""
    prefix = _ACTIVE_SECTION if section_gate else ""
    return ", ".join(f"{prefix}{part.strip()}{_NOT_ARRIVED}"
                     for part in card.split(","))


def _prof(short: str, name: str, majors: list[str], url: str,
          tag_slugs: list[str] | None = None, card: str | None = None,
          directory_url: str | None = None, section_gate: bool = False,
          field_filter: dict | None = None) -> dict:
    """A profiles-plugin department (headless render). ``tag_slugs`` scopes a
    combined school page to one department; ``card`` overrides the selector for
    a per-department roster page (e.g. Math's id-less plugin variant);
    ``section_gate`` drops the emeritus / retired / in-memoriam grids on the
    per-department NSM pages."""
    sel = dict(_PROF_SEL)
    sel["card"] = _gated(card or _prof_card(tag_slugs), section_gate)
    scrape = {"url": url, "selectors": sel, "ladder_filter": _PROF_LADDER,
              "render": True, "render_settle": 6000}
    if field_filter:
        scrape["field_filter"] = field_filter
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": directory_url or url,
        "scrape": scrape,
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
        # ECE splits its roster across two pages; the instructional faculty live
        # on their own URL and are absent from the tenure-system list entirely.
        _eng("ECE2", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://ece.utdallas.edu/instructional-faculty/", _ECE_SEL),
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
              "https://physics.utdallas.edu/faculty/",
              section_gate=True, field_filter=_UTD_EMAIL_ONLY),
        _prof("BIO", "Department of Biological Sciences",
              ["Biology", "Molecular Biology"],
              "https://biology.utdallas.edu/faculty/", section_gate=True),
        _prof("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"],
              "https://chemistry.utdallas.edu/research-faculty/",
              section_gate=True),
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
