"""Boston University faculty config (via the faculty_graph engine).

BU is one giant WordPress multisite (www.bu.edu/<unit>/) — no WAF anywhere, a
plain browser-UA GET 200s on every public page. Five markup families, all
selectors live-verified 2026-07-18:

* **BU Profiles plugin** (~23 dept sites: CAS depts, CDS, STH, MET, CGS, SHA,
  KHC, WLL): server-rendered single-page ``li.profile`` cards. CS is the one
  section-headed roster (h3 "Professors" / "Emeriti Professors" / "Adjunct
  Faculty" / "Affiliated Faculty" …) — ``section_filter`` keeps the ladder +
  lecturer sections; flat listings gate by title regex. Profile pages publish a
  clean mailto in ``li.profile-details-email``; Physics profiles additionally
  carry a labeled "Research Interests:" ``h3`` + ``p`` (captured via
  ``research_html_re``; most other units keep research as prose bios — not
  extracted).
* **BU Profiles text-list variant** (CAS Physics): ``li.has-title`` rows; the
  first block is primary faculty, a later h3 "Affiliate Faculty" block (35
  cards) is dropped by ``section_filter`` exclude.
* **Pardee mini-cards**: each ``li.profile-item-mini`` is wrapped INSIDE its
  ``<a>``, so the card selector is ``a:has(> li…)`` with ``link: ":self"``.
  Role taxonomy rides the li class list — ``regions-dis-faculty`` (37 core) is
  the gate; emeriti / visiting-and-language-lecturer classes are excluded by
  the card selector itself.
* **bu-filtering directory** (ENG + Wheelock/SSW/CFA): ``li.bu-filtering-
  result-item`` cards, ``?num=N`` query pagination. ENG's server-side
  ``affiliation=primary-affiliated-faculty`` facet is verified working (BME 94,
  ECE 83); Wheelock's facet params are ignored server-side, so those units
  scrape all pages and gate client-side by title. ENG divisions (MSE, SE)
  overlap the dept lists — the engine's school-wide profile-URL dedupe keeps
  each professor once (departments are ordered so BME/ECE/ME win).
* **One-page mega-directories**: COM custom profile cards (path pagination
  ``/page/N/``; profiles expose NO email — contact form only), SPH (517 cards
  on one page), Sargent (286 cards on one page) — title-regex gated.
* **Questrom WordPress REST** (``wp-json/wp/v2/profiles``): clean JSON roster,
  server-filtered to the research track (``faculty_types=1375``, n=122;
  emeritus=1377 excluded). The feed's ``meta{}`` carries email + real position,
  but the engine's wp source only reads the ``meta_box`` key — so the roster
  comes from the feed and rank/email come from the gated per-profile enrich
  pass (``div.wp-block-amp-profile-position`` + a clean mailto).

Single source ("bu_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred (from the 2026-07-18 recon):
* English (CAS) — /english/people/faculty-profiles/ has zero server-rendered
  profile elements (hub/tile layout only; likely JS).
* Religion (CAS) — /religion/people/faculty/ 302s to shib.bu.edu SSO.
* School of Law — listing is a JS search widget; the wp-json profile feed
  (427 records) exposes no role taxonomy/meta, so gating full-time faculty vs
  staff/adjuncts would need all 427 profile fetches.
* Chobanian & Avedisian School of Medicine + Goldman Dental — separate
  bumc.bu.edu multisite, huge clinical body across ~30 departments (big-med
  defer).
* WLL sibling subpages (Comparative Literature, Cinema & Media Studies, …) —
  same family but only the East Asian Languages subpage was live-verified.
* CAS small programs (American Studies, Romance Studies, Core Curriculum) —
  not probed this pass.
* SSW listing keywords — cards carry ``areas_of_interest-*`` taxonomy CLASSES,
  but the engine has no class-list keyword extraction; SSW lands unkeyworded
  (profile bodies are prose).
"""

from __future__ import annotations

from .. import faculty_graph

# ---- BU Profiles plugin (shared WP multisite theme) ------------------------
_BP_SELECTORS = {
    "card": "li.profile",
    "name": ".profile-name",
    "link": "a",
    "title": ".profile-title",
}

# Profile pages keep a clean personal mailto in the details sidebar
# (li.profile-details-email) on every BU Profiles unit — the footer/dept
# inboxes live elsewhere, and email_drop rejects any shared alias that leaks.
_BP_ENRICH = {
    "email_selector": ".profile-details-email a[href^='mailto:']",
    "email_drop": r"^[^@]*$|^(?:info|admissions|questions|contact|webmaster|psgs|askcs)@",
    # This pass already fetches the page for the email, so research costs nothing
    # extra. There is no container to select — 35 departments, 35 themes, and the
    # commonest shape is a bare <p> — but they all write the same label. Measured
    # over 104 live profiles: 22% land keywords, across 11 departments.
    "research_label_re": faculty_graph.RESEARCH_LABEL_RE,
    "throttle": 0.2,
}

# Flat listings mix ladder faculty with emeriti/adjunct/staff — keep professor
# + lecturer titles, drop the retired/visiting/affiliated ranks. Staff titles
# (deans, advisors, "Research Scientist") fail the require and drop out.
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b",
    "drop": r"emerit|in memoriam|adjunct|visiting|affiliat",
}

# CS's roster is grouped under h3 role headings; Adjunct/Affiliated sections
# carry clean home-dept professor titles, so the section — not the title — is
# the gate there.
_CS_SECTIONS = {
    "heading": "h3",
    "include": (r"^(?:(?:associate|assistant)\s+)?professors(?:\s+of\s+the\s+practice)?$"
                r"|^(?:senior\s+)?lecturers$"),
}

# ---- BU Profiles text-list variant (CAS Physics) ---------------------------
_TL_SELECTORS = {
    "card": "div.profile-listing li.has-title",
    "name": "a > span.profile-name",
    "link": "a",
    "title": "span.profile-title",
}

# First listing block (39 primary faculty) has no preceding h3; the later
# "Affiliate Faculty" block (35 cards) does — exclude it.
_TL_SECTIONS = {"heading": "h3", "exclude": r"affiliate"}

# ---- bu-filtering directory (ENG + Wheelock/SSW/CFA) -----------------------
_BF_SELECTORS = {
    "card": "li.bu-filtering-result-item",
    "name": "h4.bu-filtering-result-item-title a",
    "link": "h4.bu-filtering-result-item-title a",
    "title": "div.bu-filtering-result-item-title",
}


def _bp(short: str, name: str, majors: list[str], path: str, *,
        section_filter: dict | None = None, enrich_extra: dict | None = None) -> dict:
    """A department on the shared BU Profiles plugin theme."""
    url = f"https://www.bu.edu/{path}/"
    scrape: dict = {"url": url, "selectors": _BP_SELECTORS, "ladder_filter": _LADDER,
                    "profile_enrich": {**_BP_ENRICH, **(enrich_extra or {})}}
    if section_filter:
        scrape["section_filter"] = section_filter
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": scrape}


def _eng(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A College of Engineering unit via the server-side-faceted people directory.

    ``affiliation=primary-affiliated-faculty`` filters server-side (verified);
    pages advance with ``?num=N`` until one returns nothing new.
    """
    url = (f"https://www.bu.edu/eng/academics/departments-and-divisions/{slug}/people/"
           f"?department={slug}&affiliation=primary-affiliated-faculty&layout=list")
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _BF_SELECTORS, "ladder_filter": _LADDER,
                       "paginate": {"param": "num", "start": 2, "max": 3},
                       "profile_enrich": _BP_ENRICH}}


def _bf(short: str, name: str, majors: list[str], url: str, max_pages: int) -> dict:
    """A bu-filtering directory WITHOUT working server-side role facets
    (Wheelock/SSW/CFA) — scrape all pages, gate client-side by title."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _BF_SELECTORS, "ladder_filter": _LADDER,
                       "paginate": {"param": "num", "start": 2, "max": max_pages},
                       "profile_enrich": _BP_ENRICH}}


SCHOOL: dict = {
    "school_slug": "bu",
    "source": "bu_faculty",
    "organization": "Boston University",
    "location": "Boston, MA",
    "id_prefix": "bu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Boston University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Arts & Sciences (BU Profiles theme) -----------------
        _bp("CS", "Department of Computer Science", ["Computer Science"],
            "cs/about/people/faculty", section_filter=_CS_SECTIONS),
        _bp("MATH", "Department of Mathematics & Statistics",
            ["Mathematics", "Statistics"], "math/people/faculty"),
        _bp("CHEM", "Department of Chemistry", ["Chemistry"],
            "chemistry/people/faculty"),
        _bp("BIO", "Department of Biology", ["Biology"], "biology/people/faculty"),
        _bp("ECON", "Department of Economics", ["Economics"], "econ/people/faculty"),
        _bp("PSYCH", "Department of Psychological & Brain Sciences",
            ["Psychological & Brain Sciences", "Neuroscience", "Psychology"],
            "psych/people/faculty"),
        _bp("EARTH", "Department of Earth & Environment",
            ["Earth & Environmental Sciences"], "earth/people/faculty"),
        _bp("ASTRO", "Department of Astronomy", ["Astronomy", "Physics"],
            "astronomy/people/faculty"),
        _bp("ANTH", "Department of Anthropology", ["Anthropology"],
            "anthrop/people/faculty"),
        _bp("SOC", "Department of Sociology", ["Sociology"],
            "sociology/people/faculty"),
        _bp("POLS", "Department of Political Science", ["Political Science"],
            "polisci/people/faculty"),
        _bp("HIST", "Department of History", ["History"], "history/people/faculty"),
        _bp("PHIL", "Department of Philosophy", ["Philosophy"],
            "philo/people/faculty"),
        _bp("LING", "Department of Linguistics", ["Linguistics"],
            "linguistics/people/faculty"),
        _bp("ARCH", "Department of Archaeology", ["Archaeology", "Anthropology"],
            "archaeology/people/faculty"),
        _bp("CLAS", "Department of Classical Studies", ["Classical Studies"],
            "classics/people/faculty"),
        _bp("WLL", "World Languages & Literatures (East Asian Languages)",
            ["Chinese", "Japanese", "Comparative Literature"],
            "wll/people/faculty/east-asian-languages-literature"),
        # Physics: text-list variant; profiles have labeled "Research
        # Interests:" — the one CAS unit with an extractable research line.
        {
            "short": "PHYS", "name": "Department of Physics", "majors": ["Physics"],
            "directory_url": "https://www.bu.edu/physics/people/faculty-lecturers/",
            "scrape": {
                "url": "https://www.bu.edu/physics/people/faculty-lecturers/",
                "selectors": _TL_SELECTORS,
                "section_filter": _TL_SECTIONS,
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    **_BP_ENRICH,
                    "research_html_re": r"Research Interests:?\s*</h3>\s*<p>(.*?)</p>",
                },
            },
        },
        # ---- Faculty of Computing & Data Sciences ---------------------------
        _bp("CDS", "Faculty of Computing & Data Sciences",
            ["Data Science", "Computer Science"],
            "cds-faculty/culture-community/faculty"),
        # ---- College of Engineering (server-side primary-faculty facet) -----
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "biomedical-engineering"),
        _eng("ECE", "Department of Electrical & Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "electrical-computer-engineering"),
        _eng("ME", "Department of Mechanical Engineering",
             ["Mechanical Engineering"], "mechanical-engineering"),
        # Interdisciplinary divisions — heavy overlap with the departments
        # above; the school-wide profile-URL dedupe keeps each person once.
        _eng("MSE", "Division of Materials Science & Engineering",
             ["Materials Science & Engineering"], "materials-science-engineering"),
        _eng("SE", "Division of Systems Engineering", ["Systems Engineering"],
             "systems-engineering"),
        # ---- Questrom School of Business (WordPress REST roster) ------------
        {
            "short": "QST", "name": "Questrom School of Business",
            "majors": ["Business Administration", "Finance", "Accounting",
                       "Marketing", "Business Analytics"],
            "directory_url": "https://www.bu.edu/questrom/faculty-research/faculty/",
            # Research track only (faculty_types 1375, n=122; 1376 = teaching
            # track, 1377 = emeritus). The feed's meta{} email/position sit
            # under a key the engine's wp source doesn't read (``meta`` vs
            # ``meta_box``) — the gated enrich below recovers both.
            "api": {
                "type": "wp",
                "base": "https://www.bu.edu/questrom",
                "post_type": "profiles",
                "query": "&faculty_types=1375",
                "category_include": {"faculty_types": [1375]},
                "category_exclude": {"faculty_types": [1377]},
            },
            "profile_enrich": {
                "title_selector": "div.wp-block-amp-profile-position",
                "email_selector": ".profile__contact-cell--email a[href^='mailto:']",
                "email_drop": r"^[^@]*$|^(?:info|questions|questrom)@",
                "throttle": 0.2,
            },
        },
        # ---- College of Communication (custom cards, path pagination) -------
        {
            "short": "COM", "name": "College of Communication",
            "majors": ["Journalism", "Film & Television", "Advertising",
                       "Public Relations", "Media Science"],
            "directory_url": "https://www.bu.edu/com/profiles/faculty/",
            # COM profiles publish NO email (contact form only) — no enrich.
            "scrape": {
                "url": "https://www.bu.edu/com/profiles/faculty/",
                "selectors": {"card": "a.profile-card__link",
                              "name": ".profile-card__name", "link": ":self",
                              "title": ".profile-card__title"},
                "ladder_filter": _LADDER,
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 8},
            },
        },
        # ---- School of Public Health (one page, 517 cards) ------------------
        {
            "short": "SPH", "name": "School of Public Health",
            "majors": ["Public Health", "Epidemiology", "Biostatistics"],
            "directory_url": "https://www.bu.edu/sph/about/directory/",
            "scrape": {
                "url": "https://www.bu.edu/sph/about/directory/",
                "selectors": {"card": "a.sph-profile-basic-card",
                              "name": ".sph-profile-name-full", "link": ":self",
                              "title": "h6.sph-profile-main-position"},
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "email_selector": ".sph-profile-email a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|^(?:info|questions|sph)[a-z]*@",
                    "throttle": 0.2,
                },
            },
        },
        # ---- Sargent College (one page, 286 cards) --------------------------
        {
            "short": "SAR", "name": "Sargent College of Health & Rehabilitation Sciences",
            "majors": ["Health Science", "Human Physiology", "Nutrition",
                       "Speech, Language & Hearing Sciences"],
            "directory_url": "https://www.bu.edu/sargent/directory/",
            "scrape": {
                "url": "https://www.bu.edu/sargent/directory/",
                "selectors": {"card": ".profile-container", "name": ".profile-name",
                              "link": "a", "title": ".profile-title"},
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "email_selector": "li.email a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|^(?:info|questions|sargent)@",
                    "throttle": 0.2,
                },
            },
        },
        # ---- Wheelock / SSW / CFA (bu-filtering, client-side gate) ----------
        _bf("WED", "Wheelock College of Education & Human Development",
            ["Education & Human Development", "Special Education"],
            "https://www.bu.edu/wheelock/about/directory/", 30),
        _bf("SSW", "School of Social Work", ["Social Work"],
            "https://www.bu.edu/ssw/research-faculty/our-faculty/", 3),
        _bf("CFA", "College of Fine Arts",
            ["Music", "Theatre Arts", "Visual Arts", "Art Education"],
            "https://www.bu.edu/cfa/about/contact-directions/directory/", 17),
        # ---- Pardee School of Global Studies (mini-cards, class-gated) ------
        {
            "short": "PARDEE", "name": "Frederick S. Pardee School of Global Studies",
            "majors": ["International Relations", "Asian Studies",
                       "Latin American Studies", "Middle East & North Africa Studies"],
            "directory_url": "https://www.bu.edu/pardeeschool/academics/faculty/",
            # The <a> WRAPS the li, so the card is the anchor itself; the
            # regions-dis-faculty taxonomy class keeps core faculty (37) and
            # drops emeriti + visiting/language lecturers at the selector.
            "scrape": {
                "url": "https://www.bu.edu/pardeeschool/academics/faculty/",
                "selectors": {"card": "a:has(> li.profile-item-mini.regions-dis-faculty)",
                              "name": "h6.profile-name", "link": ":self",
                              "title": "p.pardee-mini-title"},
                "ladder_filter": _LADDER,
                "profile_enrich": _BP_ENRICH,
            },
        },
        # ---- Professional / honors colleges (BU Profiles theme) -------------
        _bp("STH", "School of Theology", ["Religion", "Theology"], "sth/about/faculty"),
        _bp("MET", "Metropolitan College",
            ["Computer Science", "Management", "Criminal Justice"],
            "met/faculty-research/faculty"),
        _bp("CGS", "College of General Studies",
            ["Interdisciplinary Studies"], "cgs/about/directory/department"),
        _bp("SHA", "School of Hospitality Administration",
            ["Hospitality Administration"], "hospitality/about/meet-our-faculty"),
        # KHC lists affiliated faculty from other colleges — once the email
        # enrich pass runs, the school-wide email dedupe collapses them onto
        # their home-department records (KHC is ordered last so home depts win).
        _bp("KHC", "Kilachand Honors College", ["Interdisciplinary Studies"],
            "khc/people/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
