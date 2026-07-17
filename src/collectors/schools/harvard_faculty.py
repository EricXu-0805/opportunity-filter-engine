"""Harvard University faculty config (via the faculty_graph engine).

Harvard FAS migrated its department sites onto the shared "HWP" Drupal 10
platform — ONE selector set (``article.page-card--hwp-person``) covers ~28
departments; the stragglers are five WordPress one-offs (math, EPS, gov, MCB,
SCRB), Comp Lit's hand-built Elementor page, and SEAS's own Drupal. All
live-verified 2026-07-15. Akamai fronts the FAS sites: it 403s header-less
clients AND flags IPs that hammer it (a scrape burst re-arms the wall for
hours) — the weekly shard is the steady-state fill path when that happens.

HWP notes: listings paginate ``?page=N`` (0-indexed, 12/page — the base page
is page 0, the engine follows 1..max); role facets ride the URL as
``?f[0]=<field>:<tid>`` and where a clean ladder facet exists the config URL
uses it (anthropology "Ladder Faculty", history "Core Faculty", OEB
"Department Faculty", …). Tabbed/sectioned pages (economics, statistics,
astronomy, philosophy, AAAS) ship all cards statically — a ``section_filter``
on the nearest preceding ``h2`` scopes to the ladder tab/section. English
alone caps its static HTML at 12 cards; its Drupal "show more" AJAX endpoint
returns the full 47 in one call (engine ``ajax_html``; needs XHR + Referer
headers or Akamai 403s). Most HWP listings carry the person's REAL email on
the card; the exceptions (history, histsci, physics, TDM, AFVS) recover it
from profiles via the gated enrich pass. Research interests ride the card
description behind a "Research Interests:" label — captured by regex so bio
prose never leaks into keywords (the Dartmouth lesson).

Quirks: anthropology's faculty page slug is academic-year-stamped
("faculty25-26") and WILL rotate annually — expect a red collector then;
celtic's tiny roster has a site data bug (one mailto points at a colleague);
``math.harvard.edu`` apex and several ``<dept>.fas`` DNS aliases are dead —
canonical ``www.<dept>.harvard.edu`` hosts are used throughout. SEAS
paginates ``?page=%2CN`` (comma-prefixed — the faculty view is the page's
second view; engine ``value_prefix``).

Single source ("harvard_faculty"); department rides each record, ids
namespaced by department short-code.

Deferred (documented): pure cross-appointment committees (Folklore &
Mythology, Social Studies, WGS, Study of Religion — their members are
covered via home departments and would only feed the joint-appointment
collapse), the CfA (Harvard-Smithsonian astrophysics — Smithsonian joint
institution beyond the FAS Astronomy roster), HBS (AWS-WAF JS challenge),
HKS (Akamai 403), HMS (host timeout), SPH (post-rebrand IA unknown), GSD
(JS-only listing).
"""

from __future__ import annotations

from .. import faculty_graph

# Ladder faculty: professor-titled ranks (named chairs, "of the Practice",
# "in Residence" included); drop emeriti/visiting/lecturers/preceptors/
# fellows/instructors and research staff.
_LADDER = {
    "require": r"\bprofessor\b",
    "drop": (r"emerit|visiting|adjunct|\blecturer\b|preceptor|instructor"
             r"|\bfellow\b|research scientist|research associate|in memoriam"),
}

# Faculty-scoped facet URLs / categories: keep everyone except stragglers.
_LADDER_LIGHT = {"drop": r"emerit|visiting|in memoriam|preceptor|\blecturer\b"}

# ---- HWP Drupal 10 shared theme (FAS) ---------------------------------------
_HWP_SELECTORS = {
    "card": "article.page-card--hwp-person",
    "name": "h3.page-card__heading",
    "name_strip": r"(?i)\s*\((?:on leave|on sabbatical|emerit)[^)]*\)$",
    "link": "a.page-card__link",
    "title": ".field--name-field-hwp-person-prof-title",
    "email": "a.page-card__email[href^='mailto:']",
    # Only the labelled research line — HWP descriptions are otherwise bio
    # prose, which must not become keywords.
    "research_re_text": r"Research Interests?:\s*(.{4,300})",
}

# Gated profile pass for the HWP depts whose listings omit emails; the first
# mailto in the page body is the person (later ones are the dept office).
_HWP_ENRICH = {
    "email_selector": "main a[href^='mailto:']",
    "email_drop": (r"^[^@]*$|(?:info|admin|office|contact|department|inquiries"
                   r"|undergrad\w*|events|webmaster)@"),
    "throttle": 0.2,
}


def _hwp(short: str, name: str, majors: list[str], url: str, *,
         pages: int = 0, section: str | None = None, ladder: dict | None = _LADDER,
         enrich: bool = False, **extra) -> dict:
    scrape: dict = {"url": url, "selectors": _HWP_SELECTORS}
    if ladder:
        scrape["ladder_filter"] = ladder
    if pages:
        scrape["paginate"] = {"param": "page", "start": 1, "max": pages}
    if section:
        scrape["section_filter"] = {"heading": "h2", "include": section}
    if enrich:
        scrape["profile_enrich"] = _HWP_ENRICH
    scrape.update(extra)
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url.split("?")[0], "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "harvard",
    "source": "harvard_faculty",
    "organization": "Harvard University",
    "location": "Cambridge, MA",
    "id_prefix": "harvard",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Harvard University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- FAS: HWP Drupal theme -----------------------------------------
        _hwp("AAAS", "Department of African and African American Studies",
             ["African and African American Studies"],
             "https://aaas.fas.harvard.edu/aaas-people",
             section=r"^faculty$"),
        _hwp("AFVS", "Department of Art, Film, and Visual Studies",
             ["Art, Film, and Visual Studies"],
             "https://afvs.fas.harvard.edu/faculty", pages=1, enrich=True),
        _hwp("ANTH", "Department of Anthropology", ["Anthropology"],
             # The slug is academic-year-stamped and rotates each fall.
             "https://anthropology.fas.harvard.edu/faculty25-26?f[0]=hwp_c_facultyrole:132806",
             pages=2, ladder=_LADDER_LIGHT),
        _hwp("ASTRO", "Department of Astronomy", ["Astronomy"],
             "https://astronomy.fas.harvard.edu/people",
             section=r"^faculty$"),
        _hwp("CCB", "Department of Chemistry and Chemical Biology",
             ["Chemistry and Chemical Biology"],
             "https://www.chemistry.harvard.edu/people?f[0]=hwp_c_affiliateslecturersp:159841",
             pages=2, ladder=_LADDER_LIGHT),
        {
            # Celtic's tiny roster uses the vertical-card variant (no
            # hwp-person cards, no profile pages); rank lives in prose, so
            # emeriti are excluded by description text instead.
            "short": "CELTIC", "name": "Department of Celtic Languages and Literatures",
            "majors": ["Celtic Languages and Literatures"],
            "directory_url": "https://celtic.fas.harvard.edu/people-0",
            "scrape": {
                "url": "https://celtic.fas.harvard.edu/people-0",
                "selectors": {"card": "article.page-card--hwp-vertical-card-item",
                              "name": "h3.page-card__heading",
                              "email": "a[href^='mailto:']"},
                "field_filter": {"selector": ".page-card__description",
                                 "exclude": r"emerit"},
            },
        },
        _hwp("CLASSICS", "Department of the Classics", ["Classics"],
             "https://classics.fas.harvard.edu/classics-faculty-0"),
        _hwp("EALC", "Department of East Asian Languages and Civilizations",
             ["East Asian Languages and Civilizations"],
             "https://ealc.fas.harvard.edu/faculty-0?f[0]=hwp_c_people1234:6536",
             pages=6),
        _hwp("ECON", "Department of Economics", ["Economics"],
             "https://www.economics.harvard.edu/faculty",
             section=r"^faculty\b"),
        {
            "short": "ENGL", "name": "Department of English", "majors": ["English"],
            "directory_url": "https://english.fas.harvard.edu/our-people",
            "scrape": {
                # Static HTML caps at 12 cards; the tab's show-more AJAX
                # endpoint returns all 47 in one call.
                "url": ("https://english.fas.harvard.edu/ajax/show-more?data-config="
                        "%7B%22additional_filters%22%3A%5B%5D%2C%22card_background%22%3A%22%22%2C"
                        "%22columns%22%3A%22%22%2C%22content_type%22%3A%22hwp_person%22%2C"
                        "%22display_style%22%3A%22grid%22%2C%22filter_type%22%3A%22taxonomy_and_others%22%2C"
                        "%22group_background%22%3A%22transparent%22%2C%22heading_level%22%3A%22%22%2C"
                        "%22no_results_behavior%22%3A%22hide%22%2C%22no_results_message%22%3Anull%2C"
                        "%22number_of_items%22%3A%22100%22%2C%22pager_style%22%3A%22show_more%22%2C"
                        "%22service%22%3A%22hwp_dstan_core.node_list%22%2C"
                        "%22sort_field%22%3A%22field_hwp_person_name.family--asc%22%2C"
                        "%22wrapper_id%22%3A%22hwp-node-list-results--2%22%2C"
                        "%22field_display%22%3A%7B%22prof_title%22%3A%22prof_title%22%2C"
                        "%22email%22%3A%22email%22%2C%22image%22%3A%22image%22%2C"
                        "%22excerpt%22%3A%22excerpt%22%2C%22name%22%3A%22name%22%7D%2C"
                        "%22parent%22%3A%22846%22%2C%22featured_item_id%22%3Anull%2C"
                        "%22taxonomy_filters%22%3A%7B%22field_hwp_c_coursetopic%22%3Anull%2C"
                        "%22field_hwp_c_role1234567891011121%22%3A%5B%7B%22target_id%22%3A%22164602%22%7D%5D%2C"
                        "%22field_hwp_c_undergraduateadminis%22%3Anull%2C"
                        "%22field_hwp_person_categories%22%3Anull%7D%2C%22content_filter%22%3A%5B%5D%2C"
                        "%22current_node_id%22%3A%221136254%22%2C%22total%22%3A12%2C%22page%22%3A0%7D"),
                "ajax_html": True,
                "ajax_headers": {"Referer": "https://english.fas.harvard.edu/our-people"},
                "selectors": _HWP_SELECTORS,
                "ladder_filter": _LADDER,
            },
        },
        _hwp("GERM", "Department of Germanic Languages and Literatures",
             ["Germanic Languages and Literatures"],
             "https://german.fas.harvard.edu/our-people?f[0]=hwp_c_facultyrole:173004",
             ladder=_LADDER_LIGHT),
        _hwp("HAA", "Department of History of Art and Architecture",
             ["History of Art and Architecture"],
             "https://haa.fas.harvard.edu/faculty"),
        _hwp("HEB", "Department of Human Evolutionary Biology",
             ["Human Evolutionary Biology"],
             "https://heb.fas.harvard.edu/people?f[0]=hwp_c_people12345678910111:18181",
             pages=2, ladder=_LADDER_LIGHT),
        _hwp("HIST", "Department of History", ["History"],
             "https://history.fas.harvard.edu/faculty?f[0]=faculty:130601",
             pages=4, ladder=_LADDER_LIGHT, enrich=True),
        _hwp("HISTSCI", "Department of the History of Science", ["History of Science"],
             "https://histsci.fas.harvard.edu/faculty-0?f[0]=hwp_c_currentpeople:133321",
             pages=1, ladder=_LADDER_LIGHT, enrich=True),
        _hwp("LING", "Department of Linguistics", ["Linguistics"],
             "https://linguistics.fas.harvard.edu/people/faculty"),
        _hwp("MUSIC", "Department of Music", ["Music"],
             "https://music.fas.harvard.edu/people/faculty"),
        _hwp("NELC", "Department of Near Eastern Languages and Civilizations",
             ["Near Eastern Languages and Civilizations"],
             "https://nelc.fas.harvard.edu/people/core-faculty"),
        _hwp("OEB", "Department of Organismic and Evolutionary Biology",
             ["Organismic and Evolutionary Biology"],
             "https://www.oeb.harvard.edu/people?f[0]=hwp_c_people12345678910111:48886",
             pages=2, ladder=_LADDER_LIGHT),
        _hwp("PHIL", "Department of Philosophy", ["Philosophy"],
             "https://philosophy.fas.harvard.edu/faculty-1",
             section=r"^regular faculty$", ladder=_LADDER_LIGHT),
        _hwp("PHYS", "Department of Physics", ["Physics"],
             "https://www.physics.harvard.edu/people/faculty", enrich=True),
        _hwp("PSYCH", "Department of Psychology", ["Psychology"],
             "https://psychology.fas.harvard.edu/faculty"),
        _hwp("RLL", "Department of Romance Languages and Literatures",
             ["Romance Languages and Literatures"],
             "https://rll.fas.harvard.edu/people?f[0]=department_role:266",
             pages=1, ladder=_LADDER_LIGHT),
        _hwp("SLAVIC", "Department of Slavic Languages and Literatures",
             ["Slavic Languages and Literatures"],
             "https://slavic.fas.harvard.edu/faculty"),
        _hwp("SOC", "Department of Sociology", ["Sociology"],
             "https://sociology.fas.harvard.edu/people/faculty", pages=1),
        _hwp("STAT", "Department of Statistics", ["Statistics"],
             "https://statistics.fas.harvard.edu/faculty",
             section=r"^department faculty$", ladder=_LADDER_LIGHT),
        _hwp("TDM", "Committee on Theater, Dance, and Media",
             ["Theater, Dance, and Media"],
             "https://tdm.fas.harvard.edu/people?f[0]=hwp_c_people12345678910111:98071",
             pages=2, ladder=_LADDER_LIGHT, enrich=True),
        # ---- FAS: WordPress one-offs -----------------------------------------
        {
            "short": "MATH", "name": "Department of Mathematics", "majors": ["Mathematics"],
            "directory_url": "https://www.math.harvard.edu/people/",
            "scrape": {
                # Professors + senior faculty category; the rank rides a
                # <span class="deg"> INSIDE the name anchor — strip its text.
                "url": "https://www.math.harvard.edu/peoples-categories/professors-senior-faculty/",
                "selectors": {"card": "div.item", "name": "li.name a",
                              "link": "li.name a",
                              "name_strip": r"\s*(?:University\s+)?(?:Senior\s+)?(?:Professor|Lecturer|Preceptor|Emeritus|Benjamin Peirce Fellow|Fellow)(?:\s+of.*)?$",
                              "email": "li.icon-email a"},
                "name_flip": True,
                "ladder_filter": _LADDER_LIGHT,
            },
        },
        {
            "short": "EPS", "name": "Department of Earth and Planetary Sciences",
            "majors": ["Earth and Planetary Sciences"],
            "directory_url": "https://eps.harvard.edu/people/",
            "scrape": {
                "url": "https://eps.harvard.edu/people/",
                "selectors": {"card": "a.people-tease", "name": "h3.people-tease__heading",
                              "link": ":self", "title": ".people-tease__title"},
                "field_filter": {"selector": ".people-tease__roles",
                                 "include": r"^faculty$"},
                "profile_enrich": {"email_selector": "article a[href^='mailto:']",
                                   "email_drop": r"^[^@]*$", "throttle": 0.2},
            },
        },
        {
            "short": "GOV", "name": "Department of Government",
            "majors": ["Government", "Political Science"],
            "directory_url": "https://www.gov.harvard.edu/people/faculty/",
            "scrape": {
                "url": "https://www.gov.harvard.edu/people/faculty/",
                "selectors": {"card": "div.cp-dir-content-grid-item",
                              "name": "h3.cp-dir-field-post_title a",
                              "link": "h3.cp-dir-field-post_title a",
                              "title": "span.cp-dir-field-title_1"},
                "ladder_filter": _LADDER,
                # Profile mailtos are frequently the faculty ASSISTANT's — the
                # school-wide collapse pass nulls any address shared across
                # people, so a stray assistant inbox can't misroute cold email.
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "email_drop": r"^[^@]*$", "throttle": 0.2},
            },
        },
        {
            "short": "MCB", "name": "Department of Molecular and Cellular Biology",
            "majors": ["Molecular and Cellular Biology"],
            "directory_url": "https://www.mcb.harvard.edu/faculty/faculty-profiles/",
            "scrape": {
                "url": "https://www.mcb.harvard.edu/faculty/faculty-profiles/",
                "selectors": {"card": "div.profile", "name": "h3.title--alternate",
                              "link": "a",
                              "research_items": "a.profile__icon span.profile__tooltip"},
                "ladder_filter": {"drop": r"emerit"},
                "profile_enrich": {
                    "email_selector": "li.contact__item.icon--email a, li.contact__item.icon--email",
                    "email_drop": r"^[^@]*$",
                    "title_selector": "p.title--section.subtitle",
                    "ladder_recheck": {"drop": r"emerit|visiting|\blecturer\b|preceptor"},
                    "throttle": 0.2,
                },
            },
        },
        {
            "short": "SCRB", "name": "Department of Stem Cell and Regenerative Biology",
            "majors": ["Stem Cell and Regenerative Biology"],
            "directory_url": "https://hscrb.harvard.edu/faculty/",
            "scrape": {
                "url": "https://hscrb.harvard.edu/faculty/",
                "selectors": {"card": "div.bc-c-person-preview", "name": "h4 a",
                              "link": "h4 a"},
                "ladder_filter": {"drop": r"emerit"},
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "email_drop": r"^[^@]*$",
                                   "title_selector": "ul.bc-c-professional-title-list",
                                   "throttle": 0.2},
            },
        },
        {
            "short": "COMPLIT", "name": "Department of Comparative Literature",
            "majors": ["Comparative Literature"],
            "directory_url": "https://complit.fas.harvard.edu/faculty/",
            "scrape": {
                # Hand-built Elementor page: each faculty is an h2 anchor; no
                # structured title element — profiles carry the rank/email.
                "url": "https://complit.fas.harvard.edu/faculty/",
                "selectors": {"card": "h2 a[href*='complit.fas.harvard.edu/people/']",
                              "name": ":self", "link": ":self"},
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "email_drop": r"^[^@]*$", "throttle": 0.2},
            },
        },
        # ---- Professional schools with scrapeable directories ---------------
        {
            "short": "HLS", "name": "Harvard Law School", "majors": ["Government"],
            "directory_url": "https://hls.harvard.edu/faculty/",
            "scrape": {
                "url": "https://hls.harvard.edu/faculty/",
                # The job line is often an administrative role ("Director, ...")
                # on people who ARE professors — the /faculty/ page is already
                # faculty-scoped, so only stragglers are dropped.
                "selectors": {"card": "li.faculty-feed__item",
                              "name": "h3.faculty-feed__item-title",
                              "link": "a.faculty-feed__item-link",
                              "title": "span.faculty-feed__item-job"},
                "ladder_filter": {"drop": r"emerit|visiting|\blecturer\b|climenko|fellow"},
                "paginate": {"param": "page", "start": 2, "max": 5},
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "email_drop": r"^[^@]*$", "throttle": 0.2},
            },
        },
        {
            "short": "GSE", "name": "Harvard Graduate School of Education",
            "majors": ["Education"],
            "directory_url": "https://www.gse.harvard.edu/directory/faculty",
            "scrape": {
                "url": "https://www.gse.harvard.edu/directory/faculty",
                # One page, 244 cards, most with emails (some are lab-admin
                # inboxes — the school-wide collapse pass nulls shared ones).
                "selectors": {"card": "li.o-summary-directory",
                              "name": ".o-summary-directory__heading a",
                              "link": ".o-summary-directory__heading a",
                              "title": ".o-summary-directory__position",
                              "email": ".o-summary-directory__email a[href^='mailto:']"},
                "ladder_filter": _LADDER,
            },
        },
        # ---- SEAS -------------------------------------------------------------
        {
            "short": "SEAS", "name": "John A. Paulson School of Engineering and Applied Sciences",
            "majors": ["Computer Science", "Electrical Engineering", "Bioengineering",
                       "Applied Mathematics", "Applied Physics",
                       "Environmental Science and Engineering",
                       "Materials Science and Mechanical Engineering"],
            "directory_url": "https://seas.harvard.edu/faculty",
            "scrape": {
                "url": "https://seas.harvard.edu/faculty",
                "selectors": {"card": "article.person-directory",
                              "name": "h2.node-title",
                              "link": "h2.node-title a",
                              "title": ".person__primary-title",
                              "email": ".person__email a[href^='mailto:']"},
                "ladder_filter": _LADDER,
                # The faculty view is the page's second view — its pager values
                # are comma-prefixed ("?page=%2C3").
                "paginate": {"param": "page", "start": 1, "max": 8,
                             "value_prefix": "%2C"},
                "profile_enrich": {
                    "email_selector": ".person__email a[href^='mailto:']",
                    "email_drop": r"^[^@]*$",
                    "research_items_selector": ".person__research-interests a",
                    "throttle": 0.2,
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
