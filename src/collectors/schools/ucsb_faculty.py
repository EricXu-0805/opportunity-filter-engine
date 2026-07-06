"""UC Santa Barbara faculty config (via the faculty_graph engine).

Third UC-system rollout school. Every UCSB department runs Drupal (SiteFarm) —
no WordPress, no JSON:API — so the whole school is CSS-scraped, in five Views
card layouts (selectors verified against live HTML, Jul 2026):

- **Family A** — ``div.views-row`` with ``.group-second``/``.group-third``:
  email AND a research-interest line on the listing. ECE, Economics, Geography,
  EEMB, Physics, MCDB. Rank is loose text in ``.group-second`` (an endowed-chair
  line can precede it), so it's pulled with ``title_re``.
- **Family A′** — Bren's clean-field variant (``.views-field-title-1`` +
  ``.views-field-field-title``); email on listing, heavy ladder filter (the page
  bundles affiliated/lecturer/emeritus).
- **Family B** — ``div.views-row`` with an ``h2``/``h3`` heading and stacked
  ``<p>`` lines: Computer Science (email on listing), Communication (email on
  profile), Mechanical Engineering (``/people``).
- **Family B′** — PSTAT's ``article.people-profile`` sub-variant (``h4 a`` +
  ``p.break-words`` email).
- **Family C** — unfiltered all-people pages (``.view-content > div`` cards, no
  ``div.views-row``): Political Science, Sociology, Chemistry & Biochemistry,
  Mathematics. These list grad students / alumni / emeriti / affiliates, so they
  need a strict ladder filter on the title; Math labels ladder faculty with the
  generic "Faculty", handled in its filter. Email is on the profile page.
- **Family D** — ``.view-content li`` item lists: Chemical Engineering (clean),
  Materials (Drupal-7, unfiltered — mostly grad students, heavy ladder filter).
- **Family E** — Psychological & Brain Sciences' ``tr.rev--people--row`` table;
  faculty are the rows whose profile path is ``/people/faculty/`` (section gate),
  with a research-area line on the listing.

Humanities departments (History/Philosophy/English/Linguistics) are deferred:
their rosters load via a Drupal views-AJAX call the static fetch can't reach.

Single source ("ucsb_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

_LADDER = {"require": r"\bprofessor\b",
           "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer|of teaching"
                   r"|teaching professor|\baffiliated|graduate student|\balum"
                   r"|postdoc|\bspecialist"}

# Loose-text rank pattern for the Drupal card families whose title is a bare
# text node (Family A) — capture the ladder/teaching rank; _LADDER drops the
# teaching/affiliated/emeritus ones afterward.
_RANK_RE = (r"((?:Assistant |Associate |Distinguished )?Professor"
            r"(?:\s+of\s+Teaching)?)")


def _dept(short: str, name: str, majors: list[str], url: str, scrape: dict) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": {"url": url, **scrape}}


# Family A: email + research on listing; rank via title_re.
def _famA(short: str, name: str, majors: list[str], url: str) -> dict:
    return _dept(short, name, majors, url, {
        "selectors": {
            "card": "div.views-row",
            "name": ".group-second h3 a",
            "link": ".group-second h3 a",
            "email": ".group-second a[href^='mailto:']",
            "title_re": _RANK_RE,
            "research": ".group-third",
        },
        "ladder_filter": _LADDER,
    })


# Family B: the shared UCSB "people-profiles" Drupal theme across Humanities &
# Fine Arts and the ethnic/area-studies social sciences. Same markup as the
# existing POLSCI/SOC entries — name+link in ``.views-field-nothing h3 a``, rank
# in ``.views-field-field-title``; NO email on the listing (it lives on each
# server-rendered profile page → gated per-profile mailto backfill). Two
# card-container variants: the classic ``div.view-content > div`` and a
# responsive-grid ``div.views-view-responsive-grid__item-inner`` (theater/frit/
# asamst — pass ``card=``). _LADDER drops emeriti/lecturers/affiliated/grad.
def _famB(short: str, name: str, majors: list[str], url: str, *,
          card: str = "div.view-content > div") -> dict:
    return _dept(short, name, majors, url, {
        "selectors": {
            "card": card,
            "name": ".views-field-nothing h3 a",
            "link": ".views-field-nothing h3 a",
            "title": ".views-field-field-title",
        },
        "ladder_filter": _LADDER,
        "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
    })


SCHOOL: dict = {
    "school_slug": "ucsb",
    "source": "ucsb_faculty",
    "organization": "University of California, Santa Barbara",
    "location": "Santa Barbara, CA",
    "id_prefix": "ucsb",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UC Santa Barbara) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Family A (email + research on listing) -------------------------
        _famA("ECE", "Department of Electrical & Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://ece.ucsb.edu/people/faculty"),
        _famA("ECON", "Department of Economics",
              ["Economics", "Financial Mathematics & Statistics"],
              "https://econ.ucsb.edu/people/faculty"),
        _famA("GEOG", "Department of Geography",
              ["Geography"], "https://www.geog.ucsb.edu/people/faculty"),
        _famA("EEMB", "Department of Ecology, Evolution & Marine Biology",
              ["Ecology & Evolution", "Aquatic Biology", "Marine Biology"],
              "https://www.eemb.ucsb.edu/people/faculty"),
        _famA("PHYS", "Department of Physics",
              ["Physics"], "https://www.physics.ucsb.edu/people/faculty"),
        _famA("MCDB", "Department of Molecular, Cellular & Developmental Biology",
              ["Biological Sciences", "Biochemistry", "Cell & Developmental Biology"],
              "https://www.mcdb.ucsb.edu/people/faculty"),
        # ---- Family B / B′ --------------------------------------------------
        _dept(
            "CS", "Department of Computer Science",
            ["Computer Science", "Computer Engineering"],
            "https://cs.ucsb.edu/people/faculty",
            {
                "selectors": {
                    "card": "div.views-row",
                    "name": "h2 a",
                    "link": "h2 a",
                    "title_re": _RANK_RE,
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "COMM", "Department of Communication",
            ["Communication"],
            "https://www.comm.ucsb.edu/people/faculty",
            {
                # Email lives on the profile page here (none on the listing).
                "selectors": {
                    "card": "div.views-row",
                    "name": "h3 a",
                    "link": "h3 a",
                    "title_re": _RANK_RE,
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "email_selector": "a[href^='mailto:']",
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "ME", "Department of Mechanical Engineering",
            ["Mechanical Engineering"],
            "https://me.ucsb.edu/people",
            {
                # ME's card heading is .me-ppl-title (not h2/h3).
                "selectors": {
                    "card": "div.views-row",
                    "name": ".me-ppl-title a",
                    "link": ".me-ppl-title a",
                    "title_re": _RANK_RE,
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "PSTAT", "Department of Statistics & Applied Probability",
            ["Statistics & Data Science", "Actuarial Science", "Financial Mathematics & Statistics"],
            "https://www.pstat.ucsb.edu/people/faculty",
            {
                "selectors": {
                    "card": "div.views-row article",
                    "name": "h4 a",
                    "link": "h4 a",
                    "title": "p:not(.break-words)",
                    "email": "p.break-words a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        # ---- Family C (unfiltered all-people; strict ladder; email on profile)
        _dept(
            "POLSCI", "Department of Political Science",
            ["Political Science"],
            "https://www.polsci.ucsb.edu/people",
            {
                "selectors": {
                    "card": "div.view-content > div",
                    "name": ".views-field-nothing h3 a",
                    "link": ".views-field-nothing h3 a",
                    "title": ".views-field-field-title",
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        _dept(
            "SOC", "Department of Sociology",
            ["Sociology"],
            "https://www.soc.ucsb.edu/people",
            {
                "selectors": {
                    "card": "div.view-content > div",
                    "name": ".views-field-nothing h3 a",
                    "link": ".views-field-nothing h3 a",
                    "title": ".views-field-field-title",
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        _dept(
            "CHEM", "Department of Chemistry & Biochemistry",
            ["Chemistry", "Biochemistry"],
            "https://www.chem.ucsb.edu/people",
            {
                "selectors": {
                    "card": "div.view-content > div",
                    "name": ".views-field-nothing h3 a",
                    "link": ".views-field-nothing h3 a",
                    "title": ".views-field-field-title",
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        _dept(
            "MATH", "Department of Mathematics",
            ["Mathematics", "Financial Mathematics & Statistics"],
            "https://www.math.ucsb.edu/people",
            {
                "selectors": {
                    "card": "div.view-content > div",
                    "name": ".views-field-nothing h3 a",
                    "link": ".views-field-nothing h3 a",
                    "title": ".views-field-field-title",
                },
                # Math labels ladder faculty with the generic "Faculty"; keep that
                # plus explicit professor ranks, drop the rest.
                "ladder_filter": {
                    "require": r"\bprofessor\b|^\s*Faculty\s*$",
                    "drop": r"\bemerit|\bvisiting|\baffiliated|\blecturer|math fellow"
                            r"|graduate student|\bpostdoc"},
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        # ---- Family D (item-list) -------------------------------------------
        _dept(
            "CHEMENGR", "Department of Chemical Engineering",
            ["Chemical Engineering"],
            "https://chemengr.ucsb.edu/people/faculty",
            {
                "selectors": {
                    "card": ".view-content li",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-titles--departments",
                    "email": ".views-field-field-people-email a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "MATSCI", "Department of Materials",
            ["Materials"],
            "https://materials.ucsb.edu/people/faculty",
            {
                # Drupal-7 unfiltered roster (mostly grad students) — strict
                # ladder filter carries the correctness here.
                "selectors": {
                    "card": ".view-content li",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-titles--departments",
                    "email": ".views-field-field-people-email a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        # ---- Family E (psych table; section by URL path) --------------------
        _dept(
            "PSYCH", "Department of Psychological & Brain Sciences",
            ["Psychological & Brain Sciences", "Biopsychology"],
            "https://psych.ucsb.edu/people",
            {
                "selectors": {
                    "card": "tr.rev--people--row",
                    "name": "td h2 a",
                    "link": "td h2 a",
                    "title": "td h2 + p",
                    "research_items": "tr td:last-child a",
                },
                # Faculty are the rows whose profile link is /people/faculty/.
                "link_filter": r"/people/faculty/",
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        # ---- Family A′ (Bren) -----------------------------------------------
        _dept(
            "BREN", "Bren School of Environmental Science & Management",
            ["Environmental Studies"],
            "https://bren.ucsb.edu/people/faculty?person_types=91",
            {
                "selectors": {
                    "card": "div.views-row",
                    "name": ".views-field-title-1 h3 a",
                    "link": ".views-field-title-1 h3 a",
                    "title": ".views-field-field-title .field-content",
                    "email": ".views-field-field-email a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        # ==== Depth expansion: Humanities & Fine Arts + ethnic/area studies ===
        # Family A (email + research on listing): Geological Sciences.
        _famA("GEOL", "Department of Earth Science",
              ["Earth Science", "Geological Sciences", "Geology"],
              "https://www.geol.ucsb.edu/people/faculty"),
        # Family B (people-profiles theme; email via per-profile backfill).
        _famB("PHIL", "Department of Philosophy", ["Philosophy"],
              "https://www.philosophy.ucsb.edu/people"),
        _famB("ARTHI", "Department of History of Art & Architecture",
              ["History of Art & Architecture", "Art History"],
              "https://www.arthistory.ucsb.edu/people"),
        _famB("LING", "Department of Linguistics", ["Linguistics"],
              "https://www.linguistics.ucsb.edu/people"),
        _famB("GLOBAL", "Department of Global Studies", ["Global Studies"],
              "https://www.global.ucsb.edu/people"),
        _famB("CHICST", "Department of Chicana & Chicano Studies",
              ["Chicana & Chicano Studies"], "https://www.chicst.ucsb.edu/people"),
        _famB("BLKST", "Department of Black Studies", ["Black Studies"],
              "https://www.blackstudies.ucsb.edu/people"),
        # Family B, responsive-grid card variant.
        _famB("THDA", "Department of Theater & Dance", ["Theater", "Dance"],
              "https://www.theaterdance.ucsb.edu/people",
              card="div.views-view-responsive-grid__item-inner"),
        _famB("FRIT", "Department of French & Italian", ["French", "Italian"],
              "https://frit.ucsb.edu/people",
              card="div.views-view-responsive-grid__item-inner"),
        _famB("ASAM", "Department of Asian American Studies",
              ["Asian American Studies"], "https://www.asamst.ucsb.edu/people",
              card="div.views-view-responsive-grid__item-inner"),
        # ---- Custom themes, email on the listing ----------------------------
        _dept("ENGL", "Department of English", ["English"],
              "https://www.english.ucsb.edu/people/faculty/",
              {"selectors": {"card": "li.table--list--row", "name": ".table--name a",
                             "link": ".table--name a", "title": ".table--position",
                             "email": ".table--desc a[href^='mailto:']"},
               "ladder_filter": _LADDER}),
        _dept("HIST", "Department of History", ["History"],
              "https://www.history.ucsb.edu/directory/faculty/",
              {"selectors": {"card": ".faculty_card", "name": "a.faculty_name",
                             "link": "a.faculty_name", "title": "label.faculty_title",
                             "email": "a.faculty_email[href^='mailto:']"},
               "ladder_filter": _LADDER}),
        _dept("EALCS", "Department of East Asian Languages & Cultural Studies",
              ["East Asian Languages & Cultural Studies"],
              "https://www.eastasian.ucsb.edu/people/faculty/",
              {"selectors": {"card": "div.card.dir-card",
                             "name": "a.directory-name h5.card-title",
                             "link": "a.directory-name",
                             "email": ".card-details a[href^='mailto:']"},
               "ladder_filter": _LADDER}),
        _dept("TMP", "Technology Management Program", ["Technology Management"],
              "https://tmp.ucsb.edu/faculty",
              {"selectors": {"card": ".views-row", "name": "h2.teaser-title a",
                             "link": "h2.teaser-title a", "title": "p strong",
                             "email": "a[href^='mailto:']"},
               "ladder_filter": _LADDER}),
        # ---- Custom themes, email via per-profile backfill ------------------
        _dept("MUS", "Department of Music", ["Music"],
              "https://music.ucsb.edu/people/faculty",
              {"selectors": {"card": ".node--type-people.node--view-mode-teaser",
                             "name": ".group-right h2", "link": ".node-readmore a",
                             "title": ".field--name-field-position"},
               "ladder_filter": _LADDER,
               "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0}}),
        _dept("FAMST", "Department of Film & Media Studies", ["Film & Media Studies"],
              "https://www.filmandmedia.ucsb.edu/people/faculty/",
              {"selectors": {"card": "div.entity.entity--person",
                             "name": ".entity__meta h3 a", "link": ".entity__meta h3 a",
                             "title": ".entity__meta > p", "research": ".entity__interests li a"},
               "ladder_filter": _LADDER,
               "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0}}),
        _dept("FEMST", "Department of Feminist Studies", ["Feminist Studies"],
              "https://femst.ucsb.edu/people/full-directory",
              {"selectors": {"card": ".views-row",
                             "name": ".views-field-nothing a h2.teaser-title",
                             "link": ".views-field-nothing a", "title": ".person-title"},
               "ladder_filter": _LADDER,
               "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0}}),
    ],
}


# --- Research-interest enrichment (gated OFE_ENRICH_PROFILES) ----------------
# The listings carry no research, but the SiteFarm profile pages do. Each entry
# below is merged into the department's ``profile_enrich`` (a shared per-profile
# fetch also does the email pass where one already exists). Two SiteFarm class
# conventions coexist — double-dash ``.field--name-*``/``.field--item`` (modern)
# and single-dash ``.field-name-*``/``.field-item`` (legacy) — plus a handful of
# departments whose research is prose in the bio (regex over the profile text).
# Verified live Jul 2026. Departments left out keep 0 keywords on purpose:
# Political Science (space-run prose, no clean split), Chemistry (a long research
# *statement*, not areas), Mechanical Engineering (taxonomy block needs a
# soup-contains hop, only 8 faculty) — documented rather than shipped noisy.
_RESEARCH_ENRICH: dict[str, dict] = {
    # Structured taxonomy fields → one clean keyword per element.
    "CS": {"research_items_selector": ".field--name-field-research-areas .field--item"},
    "COMM": {"research_items_selector": ".field--name-field-research-area-s- .field--item"},
    "CHEMENGR": {"research_items_selector": ".field-name-field-people-research-area .field-item"},
    "MATSCI": {"research_items_selector": ".field-name-field-people-research-area .field-item"},
    "BREN": {"research_items_selector": ".field--name-field-department .field--item"},
    # Prose-body departments (Sociology, Mathematics, PSTAT, Political Science)
    # were tried and dropped: their bios have no clean, consistently-labelled
    # research line, so a regex either misses most people or runs past the areas
    # into the address/office block (a "Santa Barbara" leak). Kept at 0 keywords
    # rather than ship location noise — only the structured taxonomy-field
    # departments above are enriched.
}
for _d in SCHOOL["departments"]:
    _re = _RESEARCH_ENRICH.get(_d["short"])
    if not _re:
        continue
    enr = _d["scrape"].setdefault("profile_enrich", {"throttle": 1.0})
    enr.update(_re)


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
