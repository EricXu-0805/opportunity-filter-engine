"""University of Florida faculty config (via the faculty_graph engine).

UF's directories are all server-rendered or plain-JSON (no WAF, no JS walls)
across seven markup families, verified live 2026-07-17:

* WordPress "Connections Business Directory" grids on every Wertheim
  College of Engineering department site (CISE, ECE, MAE, BME, MSE, ChE,
  ESSIE). One page, whole roster, ``div.cn-list-item`` cards whose CLASS
  TOKENS carry the role taxonomy — the ladder gate is the card selector
  (keep ``.faculty`` / ``.primary-faculty``, drop emeritus/courtesy/adjunct/
  affiliate classes) plus a title require-gate for the strays (MAE lists
  Research Assistant Scientists under the faculty term). ECE and MSE embed a
  labelled "Research Interests" block in the excerpt (bounded ``research_re``
  so the Honors-and-Awards paragraph never leaks into keywords); BME's
  excerpt is a one-line research summary; CISE/ChE/ESSIE excerpts are bio
  prose — no research selector there (the OpenAlex pass fills topics).
  ESSIE's listing has no emails at all; the Connections profile page
  publishes a mailto (``.cn-entry``), so the env-gated enrich pass fills
  them (and CISE's few email-less cards) one profile at a time.

* Shared ``.faculty-listing-item`` WP theme (ISE, CLAS Chemistry, Law,
  Journalism, HHP). Name = the bio block's first ``<p>``, rank = second.
  Law's ladder gate is the card's ``data-emeritus="false"`` attribute (69 of
  143 cards are emeriti); JOU's is the ``faculty`` class token (78 of 187);
  ISE/Chem/HHP gate on the title (the HHP list mixes staff in).

* CLAS "ufclas-team" blocks (Statistics, Biology, Psychology, Astronomy,
  Geology, Political Science, Geography) — name/position/email all on the
  listing, profile link = first non-mailto anchor (dept /directory/ page or
  personal site). Position require-gate drops the Assistant Scientists the
  Astronomy roster mixes in (14 of 27 cards survive — the rest are
  scientists/postdocs, a legitimate drop). Geology's dept profile pages
  carry a labelled "Areas of Interest:" line → env-gated research enrich.

* Plain HTML tables with per-dept column maps (Physics, Math, Anthropology,
  and IFAS Animal Sciences' emeritus tables). Physics: name|title|phone|
  office|email columns, 95 rows of which 52 are ladder faculty (the rest are
  emeriti/scientists/affiliates — verified against the title histogram).
  NOTE: Physics prints surnames in caps ("Jeff ANDREWS") and the engine has
  no case transform — names ship as published. Math merges name+rank+
  (school, year)+areas into one cell: the name is the cell's anchor text,
  the rank comes from ``title_re``, the areas from a bounded ``research_re``
  after the credential parenthetical. Animal Sciences' ACTIVE faculty are
  NOT in its tables (those hold emeriti + staff) — they are h2-name cards
  (``div.inner-right-top``); the ``:has(h3, h4)`` card gate drops the
  Sustaining Courtesy Faculty blocks, which have no title element and would
  otherwise default to "Professor" and slip the ladder.

* Bespoke card grids: Economics ("mercury" team grid, plain-text email
  divs), English (``.card.news-card``, specialty area in ``.card-text`` used
  as the research tag — the rank isn't published, and emeriti live on a
  separate, unfetched page), DCP (MixItUp filter grid, ~89 of 104 cards
  survive the title gate), College of the Arts (profile cards, 10/page).
  The Arts college-wide /directory/ CANNOT be paginated: ``/page/N/``
  re-serves page 2 for every N≥3 and ``?paged=N`` 301s into the School of
  Art + Art History's own directory (the recon's "20 pages" was this
  misdirect). The real rosters are the three school directories
  (art-art-history 4 pages / music 5 / theatre-dance 4), each of whose
  ``?paged=N`` works — and because the engine's query paginator stops at
  the first page whose cards ALL fail the ladder gate (staff-heavy pages
  occur mid-run), each school is wired as one scrape entry per page (+1
  empty headroom page; an overshoot page has zero cards, which is safe).

* Warrington College of Business: one admin-ajax JSON call returns all 441
  records with ``isFaculty``/``emeritus`` flags, title, business email
  (194/195 faculty) and ``researchTags``. The feed has NO absolute profile
  URL (``linkName`` is a bare slug and json_dir has no URL template), so
  records fall back to the human directory page.

* UF Health "Apollo" colleges (Pharmacy, Nursing, PHHP, Vet Med): the
  ``/wp-json/ufhealth/directory/v1/profiles/search`` API pages at a hard
  per_page=100 cap, and the engine's json_dir source is single-call — so
  each college is wired as one json_dir entry PER PAGE (+1 empty headroom
  page each; overshoot returns ``profiles: []``, which is safe). The feeds
  include staff and grad assistants ("GRADUATE AST-R") — strict title gate.
  The feeds' ``link`` field points at internal staging hosts
  (cop-main-a2-new.sites.medinfo.ufl.edu …), so it is NOT used; records
  fall back to each college's public directory page. Cross-page duplicates
  collapse via the engine's school-wide email dedupe.
  College of Education is the same shape: its own /faculty/query endpoint
  returns ``posts: null`` past the last page (an uncaught TypeError in
  json_dir), so COE is wired to the subsite's standard wp/v2/posts route
  instead (134 posts, all faculty profiles; ACF fields carry display_name/
  titles/email; overshoot pages 400 and are caught) — 2 live pages + 1
  headroom.

Single source ("uf_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred (from the recon pass, with reasons):
* College of Medicine — the Apollo search API on med.ufl.edu returns no
  profiles; ~25 clinical dept subsites would each need probing.
* College of Dentistry — no Apollo API (non-JSON response); the rendered
  faculty table (246 rows) has no titles, so no ladder gate is possible
  without per-profile fetches to directory.ufhealth.org.
* Engineering Education (EED) — not probed by the recon (small dept; likely
  the Connections family — verify live before wiring).
* IFAS/CALS remaining depts (Entomology & Nematology, Horticultural
  Sciences, FSHN, Microbiology & Cell Science, Soil & Water, Wildlife
  Ecology, Agronomy, Food & Resource Economics, …) — per-dept TerminalFour
  sites with non-uniform URL schemes (guessed paths 404); each needs
  individual URL discovery like ABE/Animal Sciences.
* CLAS History and Sociology & Criminology — recon's guessed directory
  URLs 404; real paths still to be found.
* CLAS remaining humanities (Philosophy, Religion, Classics, Linguistics,
  LLC, Spanish & Portuguese, African American Studies, Women's Studies) —
  not probed; likely the ufclas-team family, verify each live.
* School of Natural Resources and Environment; Hamilton School — not probed.
* College of the Arts satellite units (Digital Worlds Institute, Center for
  Arts in Medicine) — outside the recon's scope (Music / Art + Art History /
  Theatre & Dance); wire their /directory/ pages after a live probe.
* Fisher School of Accounting — already covered inside the Warrington JSON
  (FSOA dept code); listed to avoid a double-count, not a gap.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Wertheim Engineering: Connections Business Directory grids ------------
# Role taxonomy rides the card CLASS tokens; gate there first, then by title
# (MAE files Research Assistant Scientists under the faculty term).
_CONN_CARD = ("div.cn-list-item.faculty"
              ":not(.emeritus):not(.courtesy):not(.adjunct):not(.affiliate)")
# BME and ChE tag ladder faculty "primary-faculty" instead of "faculty".
_CONN_PRIMARY_CARD = "div.cn-list-item.primary-faculty:not(.emeritus-faculty)"

_CONN_SEL = {
    "card": _CONN_CARD,
    # .fn text concatenates given+family with no space — take the two spans.
    "name": ".fn .given-name",
    "name_last": ".fn .family-name",
    "link": ".cn-gridder-detail-link a",
    "title": "span.title",
    # Titles run on ("…Professor\nDirector, …" / "…Professor; Director…") —
    # keep only the rank segment.
    "title_strip_after": r"[;\n]",
    "email": ".cn-email-address a[href^='mailto:']",
}

_CONN_LADDER = {"require": r"\bprofessor\b|\blecturer\b",
                "drop": r"emerit|courtesy|adjunct|visiting"}

# ECE/MSE excerpts label the interests; bound the capture at the paragraph end
# OR the "Honors and Awards" heading (some excerpts run both in one <p>) so
# award lines never leak into keywords ("2024 IEEE Fellow").
_CONN_RI_RE = (r"Research\s+Interests\s*:?\s*(?:</p>\s*<p[^>]*>)?"
               r"(.*?)(?:</p>|Honors\s+and\s+Awards)")

# Connections profile pages publish a mailto the ESSIE listing (and a few CISE
# cards) omit; env-gated, and only email-less records are fetched.
_CONN_ENRICH = {
    "email_selector": ".cn-entry a[href^='mailto:']",
    "email_drop": r"^[^@]*$",
    # Research lives under an h3/h4/h5 heading inside the cn-list-item card;
    # heading-level scoping excludes the nav dropdown "Faculty Research Areas"
    # links (those are <a>, not headings). Plural blocks are comma lists.
    "research_selector": (
        'div.cn-list-item :is(h3, h4, h5):-soup-contains("Research Areas") + p, '
        'div.cn-list-item :is(h3, h4, h5):-soup-contains("Research Interests") + p'
    ),
    # ESSIE profiles whose only research label is the singular "Primary Research
    # Area"; fires only when the CSS selector above yields nothing.
    "research_re": (
        r"Primary Research Area\s+([A-Z][^.]{2,60}?)\s+"
        r"(?:Research (?:Topic|Areas|Interests)|Other Research|Education|"
        r"Awards|Honors|Courses|Teaching|Publications)"
    ),
    "throttle": 0.3,
    "timeout": 8,
    "max_retries": 1,
}


def _conn(short: str, name: str, majors: list[str], url: str, *,
          card: str = _CONN_CARD, research: str | None = None,
          research_re: str | None = None) -> dict:
    """A Wertheim Engineering department on the Connections grid."""
    sel = dict(_CONN_SEL, card=card)
    if research:
        sel["research"] = research
    if research_re:
        sel["research_re"] = research_re
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _CONN_LADDER,
                       "profile_enrich": _CONN_ENRICH}}


# ---- Shared ".faculty-listing-item" theme (ISE, Chem, Law, JOU, HHP) -------
_FL_SEL = {
    "card": ".faculty-listing-item",
    "name": ".faculty-listing-bio p:first-child",
    # These rosters list "First Last, <credentials>" (Ph.D., M.B.A, P.E., APR,
    # CSCS*D…) — the engine only strips KNOWN degree suffixes, so cut the whole
    # comma tail (names here are never "Last, First").
    "name_strip": r"\s*,.*$",
    "link": "a.faculty-listing-img",
    "title": ".faculty-listing-bio p:nth-of-type(2)",
    "email": "a.faculty-email[href^='mailto:']",
}

_LADDER = {"require": r"\bprofessor\b|\blecturer\b",
           "drop": r"emerit|adjunct|visiting|courtesy"}
# Law/JOU rosters are pre-gated by card attribute/class, but still mix in a
# few pure-staff roles (law-library heads, newsroom producers), and their
# endowed-chair titles ("Gerald A. Rosenthal Chair in Labor & Employment Law")
# carry no "professor" — so the require set adds chair/dean/scholar.
_LADDER_WIDE = {
    "require": r"\bprofessor\b|\blecturer\b|\bchair\b|\bdean\b|\bscholar\b",
    "drop": r"emerit|adjunct|visiting|courtesy",
}


def _fl(short: str, name: str, majors: list[str], url: str, *,
        card: str = ".faculty-listing-item", ladder: dict = _LADDER) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": dict(_FL_SEL, card=card),
                       "ladder_filter": ladder}}


# ---- CLAS "ufclas-team" blocks (list + cards variants, same field names) ---
_CLAS_SEL = {
    "card": ".ufclas-team-list__item, .ufclas-team-cards__item",
    "name": "[class$='__name']",
    # Geology/Geography/Psychology prefix names with "Dr." — strip it so
    # pi_name (and the cold-email greeting) stays a bare person name.
    "name_strip": r"^Dr\.\s+",
    "link": "a:not([href^='mailto:'])",
    "title": "[class$='__position']",
    "email": "[class$='__email'] a[href^='mailto:']",
}

_CLAS_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b",
    "drop": r"emerit|scientist|postdoc|coordinator|advis[oe]r|manager"
            r"|visiting|adjunct|courtesy",
}


def _clas(short: str, name: str, majors: list[str], url: str,
          enrich: dict | None = None, *,
          research: str | None = None, research_items: str | None = None,
          research_re: str | None = None) -> dict:
    """A CLAS ufclas-team department. Most list-variant rosters publish the
    person's areas on the listing itself (zero extra fetch): STA/GLY carry a
    comma/semicolon ``.ufclas-team-list__summary`` (``research``), POS wraps each
    area in a ``<strong>`` inside that summary (``research_items`` chips, so the
    ``>`` breadcrumb separators never leak), and the cards-variant BIO roster
    labels a "Research Interests:" line inside each card (``research_re``)."""
    sel = _CLAS_SEL
    if research or research_items or research_re:
        sel = dict(_CLAS_SEL)
        if research:
            sel["research"] = research
        if research_items:
            sel["research_items"] = research_items
        if research_re:
            sel["research_re"] = research_re
    d = {"short": short, "name": name, "majors": majors, "directory_url": url,
         "scrape": {"url": url, "selectors": sel,
                    "ladder_filter": _CLAS_LADDER}}
    if enrich:
        d["scrape"]["profile_enrich"] = enrich
    return d


# Geology dept /directory/ profiles carry a labelled "Areas of Interest:" line
# (verified); bound the capture at the first period so the following "Professor
# and Chair Contact Information…" boilerplate never rides in.
_GLY_ENRICH = {"research_re": r"Areas of Interest:?\s*([^.]{4,220})",
               "throttle": 0.2}


# ---- UF Health Apollo colleges + Warrington/COE JSON feeds -----------------
def _apollo(short: str, college: str, majors: list[str], host: str,
            pages: int, directory_url: str) -> list[dict]:
    """One json_dir entry per API page (the feed caps per_page at 100 and
    json_dir is single-call). Last page is empty headroom — overshoot returns
    ``profiles: []``, which parses to zero records safely. The feed's ``link``
    field points at internal staging hosts, so no link_field: records fall
    back to the college's public directory page."""
    return [
        {"short": short if n == 1 else f"{short}{n}", "name": college,
         "majors": majors, "directory_url": directory_url,
         "json_dir": {
             "url": (f"https://{host}/wp-json/ufhealth/directory/v1/profiles/"
                     f"search?q=&page={n}&per_page=100"),
             "records_key": "profiles",
             "name_fields": ["full_name"],
             "title_field": "title",
             "email_field": "email",
             "link_field": "__no_public_url_in_feed__",
             "ladder_filter": _LADDER,
         }}
        for n in range(1, pages + 1)
    ]


def _arts(short: str, name: str, majors: list[str], slug: str,
          pages: int) -> list[dict]:
    """A College of the Arts school directory, one scrape entry per page.

    The engine's query paginator breaks at the first page whose cards all
    fail the ladder gate (these rosters interleave staff), so each ``?paged=N``
    page is its own entry. Last page is empty headroom — an overshoot page
    renders zero cards, which parses to zero records safely."""
    base = f"https://arts.ufl.edu/programs-schools/{slug}/directory/"
    entries = []
    for n in range(1, pages + 1):
        url = base if n == 1 else f"{base}?paged={n}"
        entries.append({
            "short": short if n == 1 else f"{short}{n}", "name": name,
            "majors": majors, "directory_url": base,
            "scrape": {
                "url": url,
                "selectors": {
                    "card": "article.card-with-image",
                    "name": ".linked-title__link",
                    "link": ".linked-title__link",
                    "title": ".profile-card__titles",
                    "email": ".profile-card__contact-email a[href^='mailto:']",
                    # First unit-list item is the person's area/program
                    # ("Composition, Theory & Technology"); the second is the
                    # school name, which is furniture. A single-item list IS
                    # the bare school name — skip those cards entirely.
                    "research_items":
                        "li.unit-list__unit:first-of-type:not(:only-of-type)",
                },
                "ladder_filter": _LADDER,
            },
        })
    return entries


def _coe_page(n: int) -> dict:
    """College of Education via the /faculty/ subsite's standard wp/v2 route
    (the college's own /faculty/query endpoint returns ``posts: null`` past
    the last page, which json_dir cannot survive). ACF fields carry the
    person's display name, rank, and email; ``link`` is the public profile.
    Page 3 is headroom — wp/v2 400s past the last page, which is caught."""
    return {
        "short": "COE" if n == 1 else f"COE{n}",
        "name": "College of Education",
        "majors": ["Education Sciences", "Early Childhood Education"],
        "directory_url": "https://education.ufl.edu/faculty/",
        "json_dir": {
            "url": ("https://education.ufl.edu/faculty/wp-json/wp/v2/posts"
                    f"?per_page=100&page={n}"),
            "name_fields": ["acf.display_name"],
            "title_field": "acf.titles",
            "email_field": "acf.email",
            "link_field": "link",
            "ladder_filter": _LADDER,
        },
    }


SCHOOL: dict = {
    "school_slug": "uf",
    "source": "uf_faculty",
    "organization": "University of Florida",
    "location": "Gainesville, FL",
    "id_prefix": "uf",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Florida) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Herbert Wertheim College of Engineering ----------------------
        _conn("CISE", "Computer & Information Science & Engineering",
              ["Computer Science"], "https://www.cise.ufl.edu/people/faculty/"),
        _conn("ECE", "Electrical & Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://www.ece.ufl.edu/people/faculty/",
              research_re=_CONN_RI_RE),
        _conn("MAE", "Mechanical & Aerospace Engineering",
              ["Mechanical Engineering", "Aerospace Engineering"],
              "https://mae.ufl.edu/people/faculty/"),
        _conn("BME", "J. Crayton Pruitt Family Biomedical Engineering",
              ["Biomedical Engineering"],
              "https://www.bme.ufl.edu/people/faculty/",
              card=_CONN_PRIMARY_CARD, research=".cn-excerpt"),
        _conn("MSE", "Materials Science & Engineering",
              ["Materials Science and Engineering", "Nuclear Engineering"],
              "https://mse.ufl.edu/faculty/", research_re=_CONN_RI_RE),
        _conn("CHE", "Chemical Engineering", ["Chemical Engineering"],
              "https://www.che.ufl.edu/people/faculty/",
              card=_CONN_PRIMARY_CARD),
        _conn("ESSIE", "Engineering School of Sustainable Infrastructure & Environment",
              ["Civil Engineering", "Environmental Engineering"],
              "https://www.essie.ufl.edu/people/faculty/"),
        _fl("ISE", "Industrial & Systems Engineering",
            ["Industrial and Systems Engineering"],
            "https://www.ise.ufl.edu/people/faculty/"),
        # ABE (IFAS TerminalFour): /people/faculty/ 403s — only /people/ works
        # (staff mixed in, title-gated). Cards carry no profile links, only
        # mailto — records point at the roster page.
        {
            "short": "ABE", "name": "Agricultural & Biological Engineering",
            "majors": ["Agricultural and Biological Engineering",
                       "Biological Engineering"],
            "directory_url": "https://abe.ufl.edu/people/",
            "scrape": {
                "url": "https://abe.ufl.edu/people/",
                "selectors": {"card": ".card-skinny", "name": "h3.card-title",
                              # Some names carry ", P.E." (First Last format).
                              "name_strip": r"\s*,.*$",
                              "title": "p.card-text strong",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Liberal Arts and Sciences -------------------------
        # Physics table: 95 rows, 52 ladder (emeriti/scientists/affiliates/
        # research-professors gated out — verified against title histogram).
        {
            "short": "PHY", "name": "Department of Physics", "majors": ["Physics"],
            "directory_url": "https://www.phys.ufl.edu/wp/index.php/people/faculty/",
            "scrape": {
                "url": "https://www.phys.ufl.edu/wp/index.php/people/faculty/",
                "selectors": {"card": "table tr", "name": "td:nth-of-type(1)",
                              "link": "td a[href*='people']",
                              "title": "td:nth-of-type(2)",
                              "email": "td:nth-of-type(5)"},
                "name_flip": True,
                "ladder_filter": {
                    "require": r"\bprofessor\b|\blecturer\b",
                    "drop": r"emerit|scientist|affiliate|research professor",
                },
            },
        },
        _fl("CHM", "Department of Chemistry", ["Chemistry"],
            "https://www.chem.ufl.edu/people/faculty/"),
        # Math table merges name+rank+(school, year)+areas into one cell: the
        # name is the cell's anchor, the rank comes from title_re, the areas
        # from the line after the credential parenthetical.
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": "https://math.ufl.edu/people/faculty/",
            "scrape": {
                "url": "https://math.ufl.edu/people/faculty/",
                "selectors": {
                    "card": "table tr",
                    "name": "td.column-2 a",
                    "link": "td.column-2 a",
                    "title_re": (r"\b((?:(?:Assistant|Associate|Distinguished|"
                                 r"Graduate|Visiting|Emeritus|Instructional|"
                                 r"Research)\s+)*(?:Professor|Lecturer|"
                                 r"Instructor)(?:\s+Emeritus)?)"),
                    "research_re": r"\([^()]*\d{4}\)\s*<br/?>\s*([^<]{3,150})",
                    "email": "td.column-3",
                },
                "name_flip": True,
                "ladder_filter": {"require": r"\bprofessor\b|\blecturer\b",
                                  "drop": r"emerit"},
            },
        },
        _clas("STA", "Department of Statistics", ["Statistics"],
              "https://stat.ufl.edu/people/faculty/",
              research=".ufclas-team-list__summary"),
        # Biology is the cards variant: each card labels a "Research Interests:"
        # line (comma list) — bounded so the trailing "Pronouns:/Profile:" spans
        # never ride in.
        _clas("BIO", "Department of Biology", ["Biology"],
              "https://biology.ufl.edu/people/faculty/",
              research_re=r"Research Interests:\s*</strong>\s*([^<]+)"),
        _clas("PSY", "Department of Psychology", ["Psychology"],
              "https://psych.ufl.edu/people/faculty/"),
        _clas("AST", "Department of Astronomy", ["Astronomy", "Physics"],
              "https://astro.ufl.edu/people/faculty/"),
        # Geology's list summary ("Areas of Interest: …") is cleaner and cheaper
        # than the per-profile pass; keep the enrich as a fallback for the ~11
        # cards with no summary.
        _clas("GLY", "Department of Geological Sciences",
              ["Geology", "Environmental Science"],
              "https://geology.ufl.edu/people/faculty/", enrich=_GLY_ENRICH,
              research=".ufclas-team-list__summary"),
        # Political Science wraps each area in a <strong> (with a ">" breadcrumb
        # span between) — take the strongs as atomic chips.
        _clas("POS", "Department of Political Science", ["Political Science"],
              "https://polisci.ufl.edu/people/faculty/",
              research_items=".ufclas-team-list__summary strong"),
        _clas("GEO", "Department of Geography", ["Geography"],
              "https://geog.ufl.edu/people/faculty/"),
        # Economics "mercury" team grid; email is a plain-text div.
        {
            "short": "ECO", "name": "Department of Economics", "majors": ["Economics"],
            "directory_url": "https://economics.clas.ufl.edu/people/faculty/",
            "scrape": {
                "url": "https://economics.clas.ufl.edu/people/faculty/",
                "selectors": {"card": ".individual-team-member-container",
                              "name": ".archive-team-member-name",
                              "link": ".team-member-image a",
                              "title": ".archive-team-member-position",
                              "email": ".archive-team-member-email"},
                "ladder_filter": _CLAS_LADDER,
            },
        },
        # Anthropology table: the subfield column is a usable research tag.
        {
            "short": "ANT", "name": "Department of Anthropology",
            "majors": ["Anthropology"],
            "directory_url": "https://anthro.ufl.edu/people/faculty/",
            "scrape": {
                "url": "https://anthro.ufl.edu/people/faculty/",
                "selectors": {"card": "table tr", "name": "td:nth-of-type(1)",
                              "link": "td a[href*='people']",
                              "title": "td:nth-of-type(2)",
                              "research": "td:nth-of-type(3)",
                              "email": "td:nth-of-type(4)"},
                "name_flip": True,
                "ladder_filter": {"require": r"\bprofessor\b|\blecturer\b",
                                  "drop": r"emerit"},
            },
        },
        # English: the rank isn't published (card-text is the specialty area,
        # kept as the research tag); emeriti live on a separate, unfetched page.
        {
            "short": "ENG", "name": "Department of English",
            "majors": ["English", "Creative Writing"],
            "directory_url": "https://english.ufl.edu/faculty-listing/",
            "scrape": {
                "url": "https://english.ufl.edu/faculty-listing/",
                "selectors": {"card": ".card.news-card", "name": "h3.card-title",
                              "link": "a.news-card-link",
                              "research": ".card-text"},
            },
        },
        # ---- Professional colleges ----------------------------------------
        _fl("LAW", "Levin College of Law", ["Political Science", "Criminology"],
            "https://www.law.ufl.edu/faculty/",
            card=".faculty-listing-item[data-emeritus='false']",
            ladder=_LADDER_WIDE),
        _fl("JOU", "College of Journalism and Communications",
            ["Journalism", "Advertising", "Public Relations",
             "Media Production, Management, and Technology"],
            "https://www.jou.ufl.edu/directory/",
            card=".faculty-listing-item.faculty", ladder=_LADDER_WIDE),
        # DCP MixItUp grid (all depts incl. Rinker Construction).
        {
            "short": "DCP", "name": "College of Design, Construction and Planning",
            "majors": ["Architecture", "Interior Design", "Landscape Architecture",
                       "Sustainability and the Built Environment",
                       "Construction Management", "Urban and Regional Planning"],
            "directory_url": "https://dcp.ufl.edu/faculty/",
            "scrape": {
                "url": "https://dcp.ufl.edu/faculty/",
                "selectors": {"card": "div.mix", "name": ".name-header",
                              "link": "a[href*='/faculties/']",
                              "title": ".fc-title",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": _LADDER,
            },
        },
        _fl("HHP", "College of Health & Human Performance",
            ["Applied Physiology and Kinesiology", "Health Education and Behavior",
             "Sport Management", "Tourism, Hospitality and Event Management"],
            "https://hhp.ufl.edu/directory/"),
        # Warrington: one JSON call, whole college (FSOA/FIRE/ISOM/MKG/MGT…).
        {
            "short": "WCB", "name": "Warrington College of Business",
            "majors": ["Finance", "Marketing", "Management",
                       "Information Systems", "Accounting"],
            "directory_url": "https://warrington.ufl.edu/directory/",
            "json_dir": {
                "url": ("https://warrington.ufl.edu/wp-admin/admin-ajax.php"
                        "?action=wcb_directory_list_profiles"),
                "name_fields": ["FIRST_NAME_DISPLAY", "LAST_NAME_DISPLAY"],
                "title_field": "title",
                "email_field": "ufBusinessEmail",
                # linkName is a bare slug and the feed has no absolute URL
                # field — fall back to the directory page.
                "link_field": "__no_public_url_in_feed__",
                "research_field": "researchTags",
                "field_filters": [
                    {"field": "isFaculty", "include": r"^1$"},
                    {"field": "emeritus", "exclude": r"^1$"},
                ],
                "ladder_filter": _LADDER,
            },
        },
        _coe_page(1), _coe_page(2), _coe_page(3),
        *_apollo("COP", "College of Pharmacy",
                 ["Pharmaceutical Sciences", "Chemistry", "Biology"],
                 "pharmacy.ufl.edu", 5,
                 "https://pharmacy.ufl.edu/the-college/faculty-staff/faculty-directory/"),
        *_apollo("NUR", "College of Nursing", ["Nursing"],
                 "nursing.ufl.edu", 3,
                 "https://nursing.ufl.edu/faculty/faculty-directory/"),
        *_apollo("PHHP", "College of Public Health & Health Professions",
                 ["Health Science", "Public Health",
                  "Communication Sciences and Disorders"],
                 "phhp.ufl.edu", 4,
                 "https://phhp.ufl.edu/about/phhp-faculty-and-staff/"),
        *_apollo("CVM", "College of Veterinary Medicine",
                 ["Animal Sciences", "Biology", "Microbiology and Cell Science"],
                 "vetmed.ufl.edu", 4,
                 "https://www.vetmed.ufl.edu/about-the-college/directory/"),
        # ---- College of the Arts (three school directories; the college-wide
        # /directory/ can't be paginated — see module docstring).
        *_arts("ART", "School of Art + Art History",
               ["Art", "Art History", "Graphic Design"],
               "school-of-art-art-history", 5),
        *_arts("MUS", "School of Music", ["Music"], "school-of-music", 6),
        *_arts("THD", "School of Theatre + Dance", ["Theatre", "Dance"],
               "school-of-theatre-dance", 5),
        # ---- IFAS Animal Sciences: active faculty are h2-name cards; the
        # tables on the same page hold ONLY emeriti/staff/students and are
        # never selected. :has(h3, h4) drops the Sustaining Courtesy Faculty
        # cards (no title element → would default to "Professor").
        {
            "short": "ANS", "name": "Department of Animal Sciences",
            "majors": ["Animal Sciences"],
            "directory_url": "https://animal.ifas.ufl.edu/people/",
            "scrape": {
                "url": "https://animal.ifas.ufl.edu/people/",
                "selectors": {"card": "div.inner-right-top:has(h3, h4)",
                              "name": "h2", "title": "h3, h4",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": {"require": r"\bprofessor\b|\blecturer\b",
                                  "drop": r"emerit|courtesy|scientist"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
