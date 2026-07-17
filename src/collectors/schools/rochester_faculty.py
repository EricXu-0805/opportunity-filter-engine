"""University of Rochester faculty config (via the faculty_graph engine).

Rochester's directories are all server-rendered (no WAF, no JS grids) across
five markup families, verified live 2026-07-17:

* Central-CMS "person-row" theme — ALL Hajim engineering depts, ALL SAS depts,
  CS, and Physics & Astronomy (25 depts). Two markup variants share the same
  classes (``article.person.person-row`` in a grid; Psychology uses
  ``tr.person.person-row`` in a table) so selecting ``.person-row`` covers
  both. Names are "Last, First" (``name_flip``); email AND a clean
  semicolon-separated "Interests:" line are INLINE on ~85-90% of cards, so no
  profile pass is needed. Chemistry's one page mixes five role sections under
  ``h3`` headings — ``section_filter`` keeps only "Chemistry Faculty".

* Political Science legacy PHP directory (the standalone
  www.polisci.rochester.edu host is TLS-dead; sas.rochester.edu/psc serves the
  same roster). Three ``table.people-table`` role tables under ``h3`` headings
  — ``section_filter`` keeps the 24-row "Core Faculty" table. Inline email, no
  titles (engine default "Professor").

* Simon Business School: Drupal, 95 server-rendered ``article`` dm_faculty
  nodes on one page. Listing has name+title+link; the profile keeps a real
  mailto (``field--name-field-dm-email``) and a labeled, comma-separated
  "Research Interests" field — the one Rochester unit whose profile research
  is clean enough to enrich from.

* Warner School of Education: Drupal layout-builder page with no person card
  class — each person is a ``div.layout.row`` holding an ``a.uor-button``
  (name + profile link) and an ``em`` rank line. One non-directory row (a
  visiting professor) rides the selector and is ladder-dropped.

* Eastman School of Music (WordPress + FacetWP, all 174 rows server-rendered)
  and School of Nursing (Bootstrap A-Z directory, 211 cards of faculty AND
  staff interleaved): both need a require-professor gate — Eastman lists
  ensemble instructors/directors, Nursing lists administrative staff. Eastman
  emails live only on profiles (mailto hrefs carry a leading "%20" the
  engine's ``_clean_email`` already strips); Nursing emails are inline.

Single source ("rochester_faculty"); department rides each record, ids
namespaced by department short-code.

Deferred (from the 2026-07-17 recon):
* School of Medicine and Dentistry (URMC) + Eastman Institute for Oral Health
  — separate urmc.rochester.edu people system (listing path 404s), huge
  clinician-heavy corpus; needs its own recon.
* Goergen Institute for Data Science and AI, Audio & Music Engineering,
  Public Health, Susan B. Anthony Institute (GSW), Frederick Douglass
  Institute (Black Studies), Digital Media Studies, Literary Translation
  Studies, Visual & Cultural Studies — all listings work but are
  affiliated/cross-listed rosters duplicating primary-dept faculty (e.g. the
  Goergen page's 119 cards all point at ME/Optics/CS profile URLs).
* Film & Media Studies, Theatre, ASL, ATHS, BSB, Sustainability — people
  paths 404 or redirect to minors pages; not probed this pass.
* Warner staff/emeriti/postdoc pages — non-ladder populations by design.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Central-CMS "person-row" theme (Hajim + SAS + CS + PAS) ---------------
# Email and the semicolon-separated "Interests:" line are inline on the card;
# ``research_re`` bounds just that line in the card markup (the label lives in
# its own <strong>, the areas follow as bare text up to the closing </p>).
_UR_SELECTORS = {
    "card": ".person-row",
    "name": "h4.name a",
    "link": "h4.name a",
    "title": "p.position",
    "email": "dl.contact-information a[href^='mailto:']",
    "research_re": r"<strong>\s*Interests:\s*</strong>(.*?)</p>",
    # Credential tails must go BEFORE the Last,First flip — "Ross, Lainie F.,
    # MD, PhD" has 3 commas, which defeats _flip_name and leaves the comma in
    # pi_name (the engine's _strip_credentials runs after flipping).
    "name_strip": r"(?:,\s*(?:M\.?D|Ph\.?D|J\.?D|Ed\.?D|D\.?N\.?P|R\.?N|M\.?P\.?H|Sc\.?D|D\.?Phil)\.?)+\s*$",
}

# Listings are Faculty pages but still carry emeritus/adjunct/postdoc/visiting
# rows; lecturers are kept (the Statistics program is mostly Senior Lecturers).
_UR_LADDER = {"drop": r"emerit|adjunct|visiting|postdoc|part-\s?time|\binstructor\b"}

# Require-gate for rosters that interleave non-research ranks with a clean
# title on every row (Eastman ensemble instructors, Nursing admin staff).
_PROF_LADDER = {"require": r"\bprofessor\b", "drop": r"emerit|adjunct|visiting"}


def _ur(short: str, name: str, majors: list[str], url: str, *,
        section: dict | None = None, ladder: dict | None = None) -> dict:
    """A department on the central person-row theme."""
    scrape = {"url": url, "selectors": _UR_SELECTORS, "name_flip": True,
              "ladder_filter": ladder or _UR_LADDER}
    if section:
        scrape["section_filter"] = section
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _hajim(short: str, name: str, majors: list[str], slug: str) -> dict:
    return _ur(short, name, majors,
               f"https://www.hajim.rochester.edu/{slug}/people/faculty/index.html")


def _sas(short: str, name: str, majors: list[str], slug: str,
         path: str = "/people/faculty/index.html", *,
         section: dict | None = None, ladder: dict | None = None) -> dict:
    return _ur(short, name, majors,
               f"https://www.sas.rochester.edu/{slug}{path}",
               section=section, ladder=ladder)


SCHOOL: dict = {
    "school_slug": "rochester",
    "source": "rochester_faculty",
    "organization": "University of Rochester",
    "location": "Rochester, NY",
    "id_prefix": "rochester",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Rochester) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Hajim School of Engineering & Applied Sciences ----------------
        {
            "short": "CS", "name": "Department of Computer Science",
            "majors": ["Computer Science", "Data Science"],
            "directory_url": "https://www.cs.rochester.edu/people/faculty/index.html",
            "scrape": {
                "url": "https://www.cs.rochester.edu/people/faculty/index.html",
                "selectors": _UR_SELECTORS, "name_flip": True,
                "ladder_filter": _UR_LADDER,
            },
        },
        _hajim("ECE", "Department of Electrical and Computer Engineering",
               ["Electrical and Computer Engineering", "Audio and Music Engineering"],
               "ece"),
        _hajim("ME", "Department of Mechanical Engineering",
               ["Mechanical Engineering"], "me"),
        _hajim("BME", "Department of Biomedical Engineering",
               ["Biomedical Engineering"], "bme"),
        _hajim("CHE", "Department of Chemical and Sustainability Engineering",
               ["Chemical Engineering"], "che"),
        _hajim("OPT", "The Institute of Optics",
               ["Optical Engineering", "Physics"], "optics"),
        # ---- School of Arts & Sciences: Sciences ---------------------------
        _sas("BIO", "Department of Biology", ["Biology", "Biological Sciences"],
             "bio"),
        # One page, five h3 role sections — keep only "Chemistry Faculty"
        # (others: Cluster Affiliated / Research Professors / Adjunct / Emeritus).
        _sas("CHM", "Department of Chemistry", ["Chemistry"], "chm",
             section={"heading": "h3", "include": r"^chemistry faculty$"}),
        # Before MTH: the Statistics Program's 7 rows are /mth/-hosted profile
        # URLs (the Math dept's statistics faculty) — first-listed dept wins
        # the dedup, so STT must precede MTH to carry Statistics majors.
        _sas("STT", "Statistics Program", ["Statistics", "Data Science"], "stt",
             path="/people/index.html"),
        _sas("MTH", "Department of Mathematics", ["Mathematics"], "mth"),
        _sas("PSY", "Department of Psychology", ["Psychology"], "psy"),
        _sas("BCS", "Department of Brain and Cognitive Sciences",
             ["Brain and Cognitive Sciences", "Neuroscience"], "bcs"),
        # PAS also lists LLE/CIRC staff-scientist ranks — gate them with the
        # professor rows' usual drops.
        _ur("PAS", "Department of Physics and Astronomy", ["Physics", "Astronomy"],
            "https://www.pas.rochester.edu/people/faculty/index.html",
            ladder={"drop": _UR_LADDER["drop"] + r"|\bscientist\b"}),
        _sas("EES", "Department of Earth and Environmental Sciences",
             ["Earth and Environmental Sciences", "Geology"], "ees"),
        # ---- School of Arts & Sciences: Social Sciences --------------------
        _sas("ECO", "Department of Economics", ["Economics"], "eco"),
        _sas("LIN", "Department of Linguistics", ["Linguistics"], "lin"),
        _sas("ANT", "Department of Anthropology", ["Anthropology"], "ant"),
        # ---- School of Arts & Sciences: Humanities -------------------------
        _sas("PHL", "Department of Philosophy", ["Philosophy"], "phl"),
        _sas("ENGL", "Department of English", ["English", "Creative Writing"],
             "eng"),
        _sas("HIS", "Department of History", ["History"], "his"),
        # Language lecturers ride the faculty listing — gate them too.
        _sas("REL", "Department of Religion and Classics", ["Religion", "Classics"],
             "rel",
             ladder={"drop": _UR_LADDER["drop"] + r"|lecturer"}),
        _sas("AAH", "Department of Art and Art History",
             ["Art History", "Studio Art"], "aah"),
        _sas("MLC", "Department of Modern Languages and Cultures",
             ["Modern Languages and Cultures", "Comparative Literature"], "mlc"),
        # Full A-Z directory mixes ensemble directors (one gmail contact) with
        # professors — require a professorial/lecturer rank.
        _sas("MUR", "Arthur Satz Department of Music", ["Music"], "mur",
             path="/people/index.html",
             ladder={"require": r"professor|lecturer", "drop": _UR_LADDER["drop"]}),
        _sas("DAN", "Program of Dance and Movement", ["Dance"], "dan"),
        # ---- Political Science (legacy PHP; www.polisci host is TLS-dead) --
        {
            "short": "PSC", "name": "Department of Political Science",
            "majors": ["Political Science"],
            "directory_url": "https://www.sas.rochester.edu/psc/people/faculty.php",
            "scrape": {
                "url": "https://www.sas.rochester.edu/psc/people/faculty.php",
                # No rank column on the listing — engine default "Professor";
                # the Core Faculty section gate does the ladder work (other
                # tables: "Emeritus & Retired" / "Affiliated").
                "selectors": {"card": "tr.faculty-table-row",
                              "name": "td.faculty-table-row-name a",
                              "link": "td.faculty-table-row-name a",
                              "email": "a[href^='mailto:']"},
                "section_filter": {"heading": "h3", "include": r"^core faculty$"},
            },
        },
        # ---- Simon Business School -----------------------------------------
        {
            "short": "SIMON", "name": "Simon Business School",
            "majors": ["Business", "Economics"],
            "directory_url": "https://simon.rochester.edu/faculty-research/faculty-directory",
            "scrape": {
                "url": "https://simon.rochester.edu/faculty-research/faculty-directory",
                "selectors": {"card": "article.node-type-dm-faculty",
                              "name": "h4 a", "link": "h4 a",
                              "title": ".field--name-field-dm-faculty-title"},
                "ladder_filter": {
                    "drop": r"emerit|adjunct|visiting|postdoctoral"},
                # Profile keeps the mailto and a clean comma-separated
                # "Research Interests" field (the engine strips the label).
                "profile_enrich": {
                    "email_selector": ".field--name-field-dm-email a[href^='mailto:']",
                    "email_drop": r"^[^@]*$",
                    "research_selector": ".field--name-field-dm-research-interests",
                    "throttle": 0.25,
                },
            },
        },
        # ---- Warner School of Education ------------------------------------
        {
            "short": "WARNER",
            "name": "Warner School of Education and Human Development",
            "majors": ["Education"],
            "directory_url": "https://www.warner.rochester.edu/faculty-directory",
            "scrape": {
                "url": "https://www.warner.rochester.edu/faculty-directory",
                # No person-card class: a person row = layout row holding the
                # name button AND a mailto. The rank is the <em> line (one
                # professor's row lacks it → engine default "Professor").
                "selectors": {
                    "card": "div.layout.row:has(a.uor-button):has(a[href^='mailto:'])",
                    "name": "a.uor-button", "link": "a.uor-button",
                    "title": ".text-block em",
                    "email": "a[href^='mailto:']"},
                "ladder_filter": _UR_LADDER,
            },
        },
        # ---- Eastman School of Music ----------------------------------------
        {
            "short": "ESM", "name": "Eastman School of Music",
            "majors": ["Music", "Music Education"],
            "directory_url": "https://www.esm.rochester.edu/faculty/",
            "scrape": {
                "url": "https://www.esm.rochester.edu/faculty/",
                "selectors": {"card": ".fwpl-row",
                              "name": ".fwpl-item.el-75mbc9 a",
                              "link": ".fwpl-item.el-75mbc9 a",
                              "title": ".fwpl-item.el-4pn7g5"},
                "name_flip": True,
                "ladder_filter": _PROF_LADDER,
                # Performance-faculty bios carry no research block; only the
                # email lives on the profile (mailto hrefs lead with "%20",
                # which _clean_email strips).
                "profile_enrich": {
                    "email_selector": "a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|admissions@|info@",
                    "throttle": 0.3,
                },
            },
        },
        # ---- School of Nursing ----------------------------------------------
        {
            "short": "SON", "name": "School of Nursing",
            "majors": ["Nursing", "Public Health"],
            "directory_url": "https://son.rochester.edu/directory/index.html",
            "scrape": {
                "url": "https://son.rochester.edu/directory/index.html",
                # A-Z directory interleaves faculty and staff under the same
                # headings — the require-professor gate is the roster.
                "selectors": {"card": "div.d-flex.flex-row:has(.faculty-photo)",
                              "name": "a strong",
                              "link": "a[href^='/directory/']",
                              "title": "li.directory__font-size",
                              "email": "a[href^='mailto:']"},
                "name_flip": True,
                "ladder_filter": _PROF_LADDER,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
