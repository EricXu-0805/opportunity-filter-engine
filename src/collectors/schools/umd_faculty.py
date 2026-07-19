"""University of Maryland, College Park faculty config (via the faculty_graph engine).

All wired directories are server-rendered plain HTML (no WAF challenges at a
0.3-0.5s throttle); eleven markup families, live-verified 2026-07-18:

* CS Drupal 7 media cards: 177 cards on one page, all ranks mixed — the rank is
  a bare TEXT NODE after the name ``h4`` (no element), so ``title_re`` captures
  it from the card text and the ladder gate drops emeriti/affiliate/adjunct.
  Research areas are taxonomy links ON the listing. CS publishes NO emails
  anywhere ("Email: Contact Form") — records land unemailed by policy.
* Clark School shared "facultydir" (Drupal 7, 8 engineering depts on their own
  domains, same /clark/facultydir?page=N&drfilter=-1 pager). Names are
  "Last, First" (``name_flip``); a few rows append "IN MEMORIAM" to the name —
  ``field_filter`` drops those cards. Profiles carry a plain mailto and a
  semicolon-separated ``#faculty_research_interests`` list (enrich pass).
* CMNS "team-block" theme (chem/cbmg/aosc): email is ON the listing. The bare
  /people/faculty pages are empty JS views (chem's /views/ajax 403s), but
  chem's per-letter pages /people/a..z are server-rendered and pre-filtered to
  Faculty — chem is 26 one-letter departments; cbmg/aosc render server-side
  when the people-type taxonomy rides the querystring.
* "person-block" variant (astro/ento), same query-filtered rendering. Astro
  profiles carry clean research-area tags + mailto (enrich).
* Biology "post-block" cards, 12/page: no title and no email on the listing;
  profile carries the mailto (enrich; profile research is prose — NOT used).
* BSOS table rows (geog/psyc/gvpt/anth): "Last, First" name + rank text in one
  cell (``title_re`` extracts; a titleless staff row keeps the raw name cell
  and fails the require-gate), plain-text email in a sibling cell. Cell
  classes vary per site — per-dept title/email selectors.
* Joomla K2 (physics/math): "Last, First"; physics gates on the
  /people/faculty/current/ href and has mailto + a "Title … E-mail" extra-field
  run (``title_re`` bounds it); math's first extra-field value is the rank but
  its email is a CSS attr() cloak (data-ep-*) the engine can't decode — math
  lands unemailed.
* "profile-card" theme (merrill journalism / SPH): whole roster on one page,
  faculty + staff + adjunct mixed — strict require-professor gate (staff carry
  non-academic titles). Merrill's /directory meta-refreshes to
  /about/faculty-and-staff (requests doesn't follow meta refresh — scrape the
  target directly). Profile mailto verified (enrich, email-only: merrill's
  research list has no selectable markup, SPH's is unverified).
* ARHU "silc" contact feed (english/communication): server-side Role filter
  (?name=Faculty), 10/page; name/title/email all on the card.
* iSchool WordPress: HTML directory with server-side job_type facets
  (ttk-faculty + ptk-faculty as two entries), 18/page path pagination; name and
  rank share one ``<p>`` (``title_re``). Profiles carry mailto + clean
  /expertise-areas/ tag links (enrich). (The wp-json feed exists but IGNORES
  its job_type param — role must come from the HTML facet.)
* AGNR hand-maintained tables (ansc/psla/enst): name links to the central AGNR
  profile, rank text in the second cell (enst appends "| Video Intro" —
  ``title_strip_after``; enst also embeds a research-area ``em`` in the name
  cell), mailto in the last cell. PSLA prefixes "Dr." (``name_strip``).

Single source ("umd_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred (recon 2026-07-18, reasons verified live):
* Smith School of Business — Drupal views AJAX directory, results only via
  full AJAX replication or headless.
* Economics / Sociology / Criminology / Hearing & Speech (BSOS) — hosts
  TLS-reset repeat requests from one IP (SSL_ERROR_SYSCALL after 1-2 hits);
  same bsos_table theme, retry from a fresh IP.
* College of Education, School of Public Policy, Architecture, Philosophy,
  Music — JS-rendered directories, no server-side names.
* History / Linguistics (ARHU) — no server-rendered listing found.
* Nutrition and Food Science (AGNR) — paragraph blobs, needs bespoke parsing;
  Agricultural and Resource Economics — 403 on /people; Geology — directory
  URL not found; AGNR central directory — JS-rendered (per-dept tables cover it).
* Remaining ARHU depts (SLLC, Art, Art History, Classics, Theatre/Dance,
  WGSS) — not probed this pass; check the silc family first.
"""

from __future__ import annotations

from string import ascii_lowercase

from .. import faculty_graph

# Rank-capture for directories whose rank is loose text (CS text node after the
# name h4, BSOS name+rank in one cell, iSchool name+rank in one <p>): captures
# the first rank phrase incl. its qualifier prefixes so the ladder gate can
# tell "Affiliate Professor" from "Professor".
_TITLE_RE = (
    r"\b((?:(?:Distinguished|University|Univ\.?|Visiting|Adjunct|Affiliate|"
    r"Assistant|Associate|Research|Senior|Principal|Clinical|Teaching|"
    r"Emeritus|Emerita)\s+)*(?:Professor|Lecturer|Instructor)"
    r"(?:\s+Emerit(?:us|a|i))?)\b"
)

# Rosters that mix every rank (CS, K2, profile-card, iSchool, BSOS, AGNR):
# keep ladder + teaching faculty, drop emeriti/adjunct/affiliate/visiting.
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b",
    "drop": r"emerit|retired|adjunct|affiliate|visiting|in memoriam",
}

# Rosters already faculty-scoped server-side (taxonomy filter / role facet):
# drop-only, so an unusual-but-real title ("Writer-in-Residence") survives.
_LADDER_LIGHT = {"drop": r"emerit|retired|adjunct|affiliate|visiting"}


# ---- Clark School shared "facultydir" (8 engineering depts) ----------------
_CLARK_SELECTORS = {
    "card": "div.faculty_row",
    "name": "div.field-directory-name-title-wrapper > a",
    "link": "div.field-directory-name-title-wrapper > a",
    # First h3 is the rank; later h3s are institute affiliations.
    "title": ".title-wrapper h3",
}

# "IN MEMORIAM" rides the name anchor on deceased-faculty rows — drop the card
# (name_strip would keep the person; these are not contactable records).
_CLARK_MEMORIAM_FILTER = {
    "selector": "div.field-directory-name-title-wrapper > a",
    "exclude": r"IN MEMORIAM",
}

_CLARK_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^[^@]*$|webmaster|communications@|info@",
    # Semicolon-separated interest phrases; _clean_keywords splits downstream.
    "research_selector": "#faculty_research_interests .field-item",
    "throttle": 0.2,
}


def _clark(short: str, name: str, majors: list[str], subdomain: str) -> dict:
    url = f"https://{subdomain}.umd.edu/clark/facultydir?drfilter=-1"
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": f"https://{subdomain}.umd.edu/clark/faculty",
        "scrape": {
            "url": url,
            "selectors": _CLARK_SELECTORS,
            "name_flip": True,
            "ladder_filter": _LADDER,
            "field_filter": _CLARK_MEMORIAM_FILTER,
            "paginate": {"param": "page", "start": 1, "max": 8},
            "profile_enrich": _CLARK_ENRICH,
        },
    }


# ---- CMNS "team-block" theme (chem letter pages, cbmg, aosc) ---------------
_TEAM_SELECTORS = {
    "card": "div.team-block",
    "name": ".team-name a",
    "link": ".team-name a",
    "title": ".team-job .field__item",
    "email": ".field--name-field-team-email a",
}


def _team(short: str, name: str, majors: list[str], url: str) -> dict:
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _TEAM_SELECTORS,
                   "ladder_filter": _LADDER_LIGHT},
    }


def _chem_letter(letter: str) -> dict:
    # chem's /people/faculty is an empty JS view and /views/ajax 403s; the
    # per-letter pages are server-rendered and pre-filtered to Faculty.
    return _team(f"CHEM{letter.upper()}", "Department of Chemistry and Biochemistry",
                 ["Chemistry and Biochemistry", "Chemistry"],
                 f"https://chem.umd.edu/people/{letter}")


# ---- "person-block" variant (astro, ento) ----------------------------------
def _person_block(short: str, name: str, majors: list[str], url: str,
                  title_selector: str, enrich: dict | None = None) -> dict:
    scrape: dict = {
        "url": url,
        "selectors": {"card": "div.person-block-container", "name": "p.person-name a",
                      "link": "p.person-name a", "title": title_selector},
        "ladder_filter": _LADDER_LIGHT,
    }
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": scrape}


# ---- BSOS table theme (geog, psyc, gvpt, anth) ------------------------------
# The name cell holds "Last, First" + rank text; title_re extracts the rank.
# A staff row without a rank keeps the raw cell text as its title and fails
# the require-gate. Cell classes vary per site — per-dept selectors.
def _bsos(short: str, name: str, majors: list[str], url: str,
          title_cell: str, email_cell: str) -> dict:
    # The name anchor must be scoped to the name/title cell: the photo cell
    # holds an EARLIER anchor to the same profile with empty text, which an
    # unscoped "td a" selector would grab (empty name → row dropped).
    name_sel = f"{title_cell} a[href*='/facultyprofile/']"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {"card": "table tr", "name": name_sel, "link": name_sel,
                          "title": title_cell, "title_re": _TITLE_RE,
                          "email": email_cell},
            "name_flip": True,
            "ladder_filter": _LADDER,
        },
    }


# ---- ARHU "silc" contact feed (english, communication) ----------------------
def _silc(short: str, name: str, majors: list[str], url: str) -> dict:
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {"card": "div.contact--feed__result",
                          "name": "a.contact--feed__a h3",
                          "link": "a.contact--feed__a",
                          "title": "p.contact--feed__unit span.functional",
                          "email": "a.contact--feed__email"},
            # ?name=Faculty is a server-side Role facet, but it text-matches
            # "Affiliate Faculty" too, and the functional span flattens ALL of
            # a person's role lines ("Professor, English Affiliate Professor,
            # Film…") — so the drop must anchor to the FIRST role or it would
            # eat English professors holding an affiliate seat elsewhere.
            "ladder_filter": {"drop": r"emerit|retired|^affiliate|^adjunct|^visiting"},
            "paginate": {"param": "page", "start": 1, "max": 8},
        },
    }


# ---- iSchool WordPress (ttk + ptk job_type facets) --------------------------
def _ischool(short: str, job_type: str) -> dict:
    url = f"https://ischool.umd.edu/directory/?job_type={job_type}"
    return {
        "short": short, "name": "College of Information (iSchool)",
        "majors": ["Information Science", "Social Data Science",
                   "Technology and Information Design"],
        "directory_url": url,
        "scrape": {
            "url": url,
            # Name and rank share one <p>; the name is the <a>, title_re pulls
            # the rank from the trailing text.
            "selectors": {"card": "div.col-lg-2", "name": "p a[href*='/directory/']",
                          "link": "p a[href*='/directory/']", "title_re": _TITLE_RE},
            "ladder_filter": _LADDER,
            # WP path pagination /directory/page/N/?job_type=…; page 1 = base.
            "paginate": {"mode": "path", "param": "page", "start": 2, "max": 8},
            "profile_enrich": {
                "email_selector": "a[href^='mailto:']",
                "email_drop": r"^[^@]*$|ischool@|info@",
                "research_items_selector": "a[href*='/expertise-areas/']",
                "throttle": 0.2,
            },
        },
    }


# ---- "profile-card" theme (merrill, sph) ------------------------------------
def _profile_card(short: str, name: str, majors: list[str], url: str,
                  name_selector: str, email_drop: str) -> dict:
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {"card": "div.profile-card", "name": name_selector,
                          "link": "a.card-cta", "title": "div.profile-card-title"},
            # One page mixes Leadership/Faculty/Staff/Adjunct/Emeritus; staff
            # carry non-academic titles, so the strict gate separates them.
            "ladder_filter": _LADDER,
            "profile_enrich": {
                "email_selector": "a[href^='mailto:']",
                "email_drop": email_drop,
                "throttle": 0.2,
            },
        },
    }


# ---- AGNR hand-maintained tables (ansc, psla, enst) -------------------------
def _agnr(short: str, name: str, majors: list[str], url: str,
          title_cell: str = "td:nth-of-type(2)",
          research_items: str | None = None,
          name_strip: str | None = None) -> dict:
    selectors: dict = {
        "card": "table tr",
        "name": "td:nth-of-type(1) a[href*='/about/directory/']",
        "link": "td:nth-of-type(1) a[href*='/about/directory/']",
        "title": title_cell,
        # enst appends "| Video Intro" to the rank cell.
        "title_strip_after": r"\s*\|",
        "email": "td a[href^='mailto:']",
    }
    if research_items:
        selectors["research_items"] = research_items
    if name_strip:
        selectors["name_strip"] = name_strip
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": selectors,
                   # Rows mix staff ("Coordinator Animal Care") and extension
                   # agents — the require-gate keeps professors/lecturers.
                   "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "umd",
    "source": "umd_faculty",
    "organization": "University of Maryland, College Park",
    "location": "College Park, MD",
    "id_prefix": "umd",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Maryland, College Park) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Computer, Mathematical, and Natural Sciences -------
        {
            "short": "CS", "name": "Department of Computer Science",
            "majors": ["Computer Science"],
            "directory_url": "https://www.cs.umd.edu/people/faculty",
            "scrape": {
                "url": "https://www.cs.umd.edu/people/faculty",
                # The rank is a bare text node after the name h4 — title_re
                # over the card text; research areas are taxonomy links.
                "selectors": {"card": "div.views-field-nothing-1.media",
                              "name": "h4.media-heading a",
                              "link": "h4.media-heading a",
                              "title_re": _TITLE_RE,
                              "research_items": ".media-body a[href*='/research-area/']"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "PHYS", "name": "Department of Physics",
            "majors": ["Physics"],
            "directory_url": "https://umdphysics.umd.edu/people/faculty.html",
            "scrape": {
                "url": "https://umdphysics.umd.edu/people/faculty.html",
                # Rank lives in a labeled K2 extra-field run ("Title … E-mail");
                # /adjunct-faculty/ items share the page — the href gates them.
                "selectors": {"card": "div.itemContainer",
                              "name": "h4.catItemTitle a", "link": "h4.catItemTitle a",
                              "title_re": r"\bTitle\s+(.+?)\s+(?:E-mail|Address|Phone)\b",
                              "email": ".catItemExtraFields a[href^='mailto:']"},
                "name_flip": True,
                "link_filter": r"/people/faculty/current/",
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": "https://www-math.umd.edu/people/faculty.html",
            "scrape": {
                "url": "https://www-math.umd.edu/people/faculty.html",
                # First extra-field value is the rank. Emails are a CSS attr()
                # cloak (data-ep-*) with no mailto in the DOM — unemailed.
                "selectors": {"card": "div.catItemView",
                              "name": "h3.catItemTitle a", "link": "h3.catItemTitle a",
                              "title": "span.catItemExtraFieldsValue"},
                "name_flip": True,
                "ladder_filter": _LADDER,
            },
        },
        *[_chem_letter(c) for c in ascii_lowercase],
        # Term 2108 = Tenure/Tenure-Track. (2094 "Instructional" serves the
        # SAME 28 cards live — a duplicate view, not a second roster.)
        _team("CBMG", "Department of Cell Biology and Molecular Genetics",
              ["Biological Sciences"],
              "https://cbmg.umd.edu/people?field_post_category_target_id=2108"),
        _team("AOSC", "Department of Atmospheric and Oceanic Science",
              ["Atmospheric and Oceanic Science"],
              "https://aosc.umd.edu/people?field_post_category_target_id=21"),
        _person_block(
            "ASTR", "Department of Astronomy", ["Astronomy"],
            "https://www.astro.umd.edu/people/?field_astronomy_people_types_target_id=624",
            "p.person-job",
            enrich={"email_selector": "a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|webmaster",
                    "research_items_selector":
                        ".person-bio-description .field--name-name.field--type-string",
                    "throttle": 0.2}),
        {
            "short": "BIOL", "name": "Department of Biology",
            "majors": ["Biological Sciences", "Biology"],
            "directory_url": "https://biology.umd.edu/people/faculty",
            "scrape": {
                "url": "https://biology.umd.edu/people/faculty",
                # No rank and no email on the listing (title defaults to
                # "Professor" on a faculty-scoped roster); profile research is
                # prose — email-only enrich.
                "selectors": {"card": "div.post-block", "name": ".post-title a",
                              "link": ".post-title a"},
                "paginate": {"param": "page", "start": 1, "max": 5},
                "profile_enrich": {
                    "email_selector": "a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|biol-help|help@|webmaster",
                    "throttle": 0.2,
                },
            },
        },
        # ---- A. James Clark School of Engineering --------------------------
        _clark("ECE", "Department of Electrical and Computer Engineering",
               ["Electrical Engineering", "Computer Engineering"], "ece"),
        _clark("ME", "Department of Mechanical Engineering",
               ["Mechanical Engineering"], "enme"),
        _clark("BIOE", "Fischell Department of Bioengineering",
               ["Bioengineering", "Biomedical Engineering"], "bioe"),
        _clark("AE", "Department of Aerospace Engineering",
               ["Aerospace Engineering"], "aero"),
        _clark("CEE", "Department of Civil and Environmental Engineering",
               ["Civil and Environmental Engineering"], "cee"),
        _clark("CHBE", "Department of Chemical and Biomolecular Engineering",
               ["Chemical and Biomolecular Engineering", "Chemical Engineering"],
               "chbe"),
        _clark("MSE", "Department of Materials Science and Engineering",
               ["Materials Science and Engineering"], "mse"),
        _clark("FPE", "Department of Fire Protection Engineering",
               ["Fire Protection Engineering"], "fpe"),
        # ---- College of Behavioral and Social Sciences ----------------------
        _bsos("GEOG", "Department of Geographical Sciences",
              ["Geographical Sciences", "Geography"],
              "https://geog.umd.edu/people/professors",
              "td.views-field-field-position-title", "td.views-field-field-email"),
        _bsos("PSYC", "Department of Psychology", ["Psychology", "Neuroscience"],
              "https://psyc.umd.edu/people/faculty",
              "td.views-field-nothing.views-align-left", "td.views-field-nothing-1"),
        _bsos("GVPT", "Department of Government and Politics",
              ["Government and Politics", "Political Science"],
              "https://gvpt.umd.edu/people/faculty",
              "td.view-title-wrap", "td.views-field-field-email"),
        _bsos("ANTH", "Department of Anthropology", ["Anthropology"],
              "https://anth.umd.edu/people/full-time-faculty",
              "td.views-field-field-position-title", "td.views-field-field-email"),
        # ---- College of Arts and Humanities ---------------------------------
        _silc("ENGL", "Department of English", ["English"],
              "https://english.umd.edu/directory?name=Faculty"),
        _silc("COMM", "Department of Communication", ["Communication"],
              "https://communication.umd.edu/people-directory?name=Faculty"),
        # ---- College of Information ------------------------------------------
        _ischool("INFO", "ttk-faculty"),
        _ischool("INFOP", "ptk-faculty"),
        # ---- Journalism + Public Health --------------------------------------
        _profile_card("JOUR", "Philip Merrill College of Journalism",
                      ["Journalism"],
                      # /directory meta-refreshes here; requests can't follow it.
                      "https://merrill.umd.edu/about/faculty-and-staff",
                      "h2.card-title", r"^[^@]*$|journalism@|merrill@"),
        _profile_card("SPH", "School of Public Health",
                      ["Public Health Science", "Kinesiology", "Family Science",
                       "Behavioral and Community Health"],
                      "https://sph.umd.edu/people/faculty-staff",
                      "h3.card-title", r"^[^@]*$|sph-|info@"),
        # ---- College of Agriculture and Natural Resources --------------------
        _agnr("ANSC", "Department of Animal and Avian Sciences",
              ["Animal Sciences"], "https://ansc.umd.edu/people/faculty"),
        # PSLA keeps name + rank in the FIRST cell (rank in a second <p>) and a
        # clean research-focus <ul> in the third; every name is "Dr."-prefixed.
        _agnr("PSLA", "Department of Plant Science and Landscape Architecture",
              ["Plant Sciences", "Landscape Architecture"],
              "https://psla.umd.edu/people/faculty",
              title_cell="td:nth-of-type(1) p:nth-of-type(2)",
              research_items="td:nth-of-type(3) li",
              name_strip=r"^Dr\.\s+"),
        # ENST double-lists every person (93 rows / 46 unique — engine dedup
        # collapses them). Its in-row research <em>s are NOT harvested: the
        # hand-maintained cell hard-wraps single phrases across multiple <em>s
        # ("Agricultural Nutrient" + "Management") indistinguishably from real
        # multi-area lists, so the chips would ship fragmented.
        _agnr("ENST", "Department of Environmental Science and Technology",
              ["Environmental Science and Technology"],
              "https://enst.umd.edu/people/faculty"),
        # ---- College of Agriculture and Natural Resources (person-block) ----
        _person_block(
            "ENTM", "Department of Entomology", ["Biological Sciences", "Entomology"],
            "https://entomology.umd.edu/people?field_ent_people_types_target_id=335",
            ".person-contact-container .field__item",
            enrich={"email_selector": "a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|webmaster",
                    "throttle": 0.2}),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
