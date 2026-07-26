"""Rutgers University-New Brunswick faculty config (via the faculty_graph engine).

All directories are server-rendered (no WAF anywhere; a desktop UA and polite
throttle suffice), across seven markup families, live-verified 2026-07-18:

* School of Arts & Sciences shared Joomla template (18 dept sites). Cards are
  ``div.news`` with the name/profile link on ``h2.newstitle a`` and the detail
  fields as ``dd.newsextra`` entries inside ``dl.item_details`` (first dd =
  rank; later dds hold research areas / email depending on the dept). Emails,
  where published, sit in a ``span.detail_data`` containing "@" (physics,
  chem, stat, psych, phil, soc, anthro); CS and Econ publish none (Econ's
  profile emails are behind Joomla's spambot JS cloak — undecodable, so those
  two land unemailed). Research areas ride the listing on phil/english/
  history/psych (2nd dd) and anthro (a "Specialization:" labelled span).
  Joomla's ``?limit=0`` collapses pagination to one page (chem 34, math 304),
  so no paginate blocks are needed. Math's directory mixes 84 PhD students +
  staff and History's page embeds a publications sidebar in the same
  ``div.news`` markup — a require-gate and a ``link_filter`` keep them out.

* Shared "rutgers" Drupal 10 person-card install (all 7 SoE depts, 4 SEBS
  Drupal sites, pharmacy): ``section.cc--person-card`` with name on
  ``.f--sub-title``, rank on ``p.title``, plain mailto on ``p.email a``.
  DBM/PLBIO/DEENR group emeriti under an "Emeriti Faculty" ``h2`` (section
  exclude); ANSCI mixes Chair/Faculty/Emeritus/Staff sections (include gate).
  ISE's scoped pages are JS shells — ``/people/all?page=N`` is server-rendered
  (cards carry no profile link → records point at the directory). Pharmacy's
  one-page directory mixes research staff → require-gate (160 cards → ~106).
  Profiles keep clean "Research Interests" text in a ``cc--profile-chapter``
  (enrich pass, gated behind OFE_ENRICH_PROFILES).

* SC&I: the faculty-only pages are JS A-Z shells and the server-rendered
  ``/people/all`` roster spreads ~70 faculty across ~45 pages of doctoral
  students/staff — sparse enough that the scrape paginator's fresh-break
  (which sees only post-ladder keepers) stops after a few pages. Wired via
  the sitemap source's list-pages mode instead: harvest every profile link
  from the 45 listing pages, fetch each profile (name ``h1``, rank
  ``h2.new-person__titles``, mailto), and require-gate on the rank (students
  and emeriti carry their real rank on the profile). ~450 throttled profile
  fetches per refresh — the Medill pattern.

* Legacy SEBS/NJAES Foundation-grid static sites (envsci, nutrition:
  name+title+email+research all on the listing; entomology: no listing
  emails — profile mailtos are HTML-entity-obfuscated, which bs4 decodes for
  free in the gated enrich pass).

* Food Science ``div.box-nav`` one-pager (icon-labelled spans, all fields on
  the listing) and Human Ecology Gutenberg ``wp-block-media-text`` blocks
  (title = first ``p`` after the ``h4`` name, cut at the inline "Research
  Interests:" label; the clean semicolon-separated interests line is captured
  by regex). Human Ecology's 22 blocks include 10 emeriti — the active
  roster is 12.

* Marine & Coastal Sciences WordPress team-showcase: 66 items, mailto inside
  each item's inline popup; no per-person pages (records point at the
  directory); popup research is prose — not scraped.

* Rutgers Business School Drupal teasers (name ``h2 a``, rank ``p.subtitle``,
  one clean academic-area tag in ``div.tags`` — 36/page ``?page=N``, spans
  NB+Newark by design) and SMLR's Drupal 7 ``listing-item.profile-item`` rows
  (mailto on listing, 10/page over ~20 pages, staff mixed in → require-gate).

* School of Nursing: the HTML directory is JS-rendered but WordPress exposes a
  clean JSON feed (``/wp-json/wp/v2/profile``, X-WP-Total 251) whose ``acf``
  object carries position/email/type — mapped via the engine's ``json_dir``
  dotted paths, gated on ``acf.type == "Faculty"`` + a professor require-gate.
  ``json_dir`` fetches one URL, so the 3 pages ride 3 dept entries pinned to
  ``orderby=id&order=asc`` (append-only ordering keeps page membership stable).

* Bloustein's Divi ``/faculty/`` archive is names-only (76 entries; titles
  default to "Professor"); per-person emails are unpublished (profile mailtos
  are the school's shared ejb@ alias) and profile research is prose — no
  enrich, records land as name+link stubs for the OpenAlex pass.

Single source ("rutgers_faculty"); department rides each record, ids
namespaced by department short-code.

Deferred: Mason Gross School of the Arts (per-division WordPress sites; only
Art & Design's listing is mapped so far — needs a per-division pass), SAS
Linguistics (linguistics.rutgers.edu timed out on every recon attempt —
retry later, expected sas_joomla family), the remaining SAS humanities depts
(Classics, Religion, Art History, AMESALL, the language depts, American/
Africana/Latino/Jewish/WGS studies — same expected Joomla family but not
live-verified this pass), Landscape Architecture (page found, not parsed),
Rutgers Biomedical and Health Sciences (huge clinical units on separate
platforms, out of undergrad-research scope), GSE/GSAPP (graduate-only), and
the Newark/Camden campuses (separate school slugs).
"""

from __future__ import annotations

from .. import faculty_graph

_REQ = r"\bprofessor\b|\blecturer\b|\binstructor\b"

# Faculty-scoped listings: keep everyone except emeriti/visiting stragglers.
_LADDER = {"drop": r"emerit|visiting"}
# Mixed directories (math's 304-card department directory, SC&I's all-people
# roster, pharmacy, SMLR, nursing's staff+faculty feed).
_LADDER_MIXED = {"require": _REQ,
                 "drop": r"emerit|visiting|student|postdoc|staff"}
# SEBS/NJAES rosters list research-active Extension Specialists alongside
# ladder faculty — they run labs and take undergrads, so the gate keeps them.
_LADDER_SEBS = {"require": _REQ + r"|extension specialist",
                "drop": r"emerit|visiting"}

# ---- SAS shared Joomla template --------------------------------------------
# The newstitle heading level varies per site (h2 on most, none on philosophy)
# — the class alone is the stable hook.
_SAS_SELECTORS = {
    "card": "div.news",
    "name": ".newstitle a",
    "link": ".newstitle a",
    "title": "dl.item_details dd",
    "email": 'span.detail_data:-soup-contains("@")',
}


def _sas(short: str, name: str, majors: list[str], url: str, *,
         research: str | None = None, ladder: dict = _LADDER,
         link_filter: str | None = None, enrich: dict | None = None) -> dict:
    sel = dict(_SAS_SELECTORS)
    if research:
        sel["research"] = research
    scrape: dict = {"url": url, "selectors": sel, "ladder_filter": ladder}
    if link_filter:
        scrape["link_filter"] = link_filter
    if enrich:
        scrape["profile_enrich"] = {**enrich, "throttle": 0.2}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url.split("?")[0], "scrape": scrape}


# The 2nd dd of the details list is the research line on these depts.
_SAS_RESEARCH_DD2 = "dl.item_details dd:nth-of-type(2)"

# ---- Shared "rutgers" Drupal 10 person-card install -------------------------
_RUD_SELECTORS = {
    "card": "section.cc--component-container.cc--person-card",
    "name": ".f--sub-title",
    "link": "a.image-link",
    "title": "p.title",
    "email": "p.email a[href^='mailto:']",
}

# Profiles keep clean short research text in a titled chapter section
# (ece Bajwa: "High-dimensional inference…, compressed sensing, …";
# dbm Bhattacharya: "algal evolution, endosymbiosis…").
_RUD_ENRICH = {
    "research_selector": 'section.cc--profile-chapter:has(.f--section-title:-soup-contains("Research")) .f--rich-text',
    "email_selector": "p.email a[href^='mailto:']",
    "email_drop": r"^[^@]*$",
    "throttle": 0.3,
    "timeout": 8,
    "max_retries": 1,
}


def _rud(short: str, name: str, majors: list[str], url: str, *,
         ladder: dict = _LADDER, section_filter: dict | None = None,
         paginate: dict | None = None) -> dict:
    scrape: dict = {"url": url, "selectors": _RUD_SELECTORS,
                    "ladder_filter": ladder, "profile_enrich": _RUD_ENRICH}
    if section_filter:
        scrape["section_filter"] = section_filter
    if paginate:
        scrape["paginate"] = paginate
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# DBM/PLBIO/DEENR: the ladder roster has NO heading of its own — only the
# "Emeriti Faculty" h2 marks a section, so the gate is exclude-only.
_SEC_NO_EMERITI = {"heading": "h2", "exclude": r"emerit"}

# ---- Legacy SEBS Foundation-grid static sites -------------------------------
# envsci/nutrition: <p><a><strong>Name</strong></a>, degree<br><strong>Title
# </strong>…<span class="icon i-email"><a mailto></a></span><br> research areas</p>
_SEBS_STATIC_SELECTORS = {
    "card": "div.contact",
    # The name+link is the profile anchor inside <strong>; scope to it so the
    # email mailto is never grabbed as the name. A few instructor cards have
    # their profile <a> commented out (no profile page) — those yield no name
    # element and are dropped rather than surfacing the email as a name.
    "name": "strong a[href$='.html'], strong a[href$='.htm']",
    "link": "strong a[href$='.html'], strong a[href$='.htm']",
    "title": "p > strong",
    "email": "span.i-email a[href^='mailto:']",
    "research_re": r"i-email.*?</span>\s*<br\s*/?>\s*([^<>]{4,300}?)\s*</p>",
}


def _sebs_static(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _SEBS_STATIC_SELECTORS,
                       "ladder_filter": _LADDER_SEBS}}


def _nurs_page(short: str, page: int) -> dict:
    """One page of the School of Nursing WP JSON profile feed (100/page ×3).

    Pinned to ``orderby=id&order=asc`` so the ordering is append-only and a
    person never migrates between the three page-departments across refreshes.
    """
    url = ("https://nursing.rutgers.edu/wp-json/wp/v2/profile"
           f"?per_page=100&page={page}&orderby=id&order=asc")
    return {
        "short": short, "name": "School of Nursing", "majors": ["Nursing"],
        "directory_url": "https://nursing.rutgers.edu/faculty/",
        "json_dir": {
            "url": url,
            "name_fields": ["acf.first_name", "acf.last_name"],
            "title_field": "acf.position",
            "email_field": "acf.email",
            "link_field": "link",
            "status_field": "acf.type", "status_value": "Faculty",
            "ladder_filter": _LADDER_MIXED,
        },
    }


SCHOOL: dict = {
    "school_slug": "rutgers",
    "source": "rutgers_faculty",
    "organization": "Rutgers University-New Brunswick",
    "location": "New Brunswick, NJ",
    "id_prefix": "rutgers",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Rutgers University-New Brunswick) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Arts and Sciences (shared Joomla) --------------------
        _sas("CS", "Department of Computer Science", ["Computer Science"],
             "https://www.cs.rutgers.edu/people/professors",
             # No emails anywhere (listing or profile); profiles expose a clean
             # "Research Group(s)" link list for the gated enrich pass.
             enrich={"research_items_selector": "li.research-group-s a"}),
        _sas("PHYS", "Department of Physics and Astronomy", ["Physics", "Astronomy"],
             "https://physics.rutgers.edu/people/faculty-list"),
        _sas("CHEM", "Department of Chemistry and Chemical Biology", ["Chemistry"],
             "https://chem.rutgers.edu/people/faculty?limit=0"),
        _sas("MATH", "Department of Mathematics", ["Mathematics"],
             "https://math.rutgers.edu/people/department-directory?limit=0",
             ladder=_LADDER_MIXED),
        _sas("STAT", "Department of Statistics", ["Statistics", "Data Science"],
             "https://statistics.rutgers.edu/people-pages/faculty"),
        _sas("ECON", "Department of Economics", ["Economics"],
             # No listing emails; profile emails are spambot-cloaked (JS).
             "https://economics.rutgers.edu/people/faculty"),
        _sas("PSY", "Department of Psychology", ["Psychology", "Neuroscience"],
             "https://psych.rutgers.edu/people/facultyblog",
             research=_SAS_RESEARCH_DD2),
        _sas("MBB", "Department of Molecular Biology and Biochemistry",
             ["Molecular Biology and Biochemistry"],
             "https://mbb.rutgers.edu/people/faculty"),
        _sas("CBN", "Department of Cell Biology and Neuroscience",
             ["Cell Biology and Neuroscience", "Neuroscience"],
             "https://cbn.rutgers.edu/people/faculty"),
        _sas("GEN", "Department of Genetics", ["Genetics"],
             "https://genetics.rutgers.edu/people/faculty"),
        _sas("EPS", "Department of Earth and Planetary Sciences",
             ["Earth and Planetary Sciences", "Geology"],
             "https://eps.rutgers.edu/people/faculty"),
        _sas("POLISCI", "Department of Political Science", ["Political Science"],
             "https://polisci.rutgers.edu/people/faculty", ladder=_LADDER_MIXED),
        _sas("SOC", "Department of Sociology", ["Sociology"],
             "https://sociology.rutgers.edu/people/faculty"),
        _sas("HIST", "Department of History", ["History"],
             "https://history.rutgers.edu/people/faculty",
             research=_SAS_RESEARCH_DD2,
             # The page embeds a publications sidebar in the same div.news
             # markup — keep only real people cards.
             link_filter=r"/people/faculty/details/"),
        _sas("GEOG", "Department of Geography", ["Geography"],
             "https://geography.rutgers.edu/people/faculty"),
        _sas("PHIL", "Department of Philosophy", ["Philosophy"],
             "https://philosophy.rutgers.edu/people/regular-faculty",
             research=_SAS_RESEARCH_DD2),
        _sas("ENGL", "Department of English", ["English"],
             "https://english.rutgers.edu/people/faculty-profiles.html",
             research=_SAS_RESEARCH_DD2),
        _sas("ANTH", "Department of Anthropology", ["Anthropology"],
             "https://anthro.rutgers.edu/people/full-time-faculty",
             research='span.detail_label:-soup-contains("Specialization") + span.detail_data'),
        # ---- School of Engineering (shared Drupal person-cards) -------------
        _rud("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical and Computer Engineering", "Computer Engineering"],
             "https://ece.rutgers.edu/full_time_faculty"),
        _rud("MAE", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"],
             "https://mae.rutgers.edu/people/faculty"),
        _rud("BME", "Department of Biomedical Engineering", ["Biomedical Engineering"],
             "https://bme.rutgers.edu/bme-faculty"),
        _rud("CBE", "Department of Chemical and Biochemical Engineering",
             ["Chemical Engineering"],
             # NOTE: /faculty redirects to an unrelated grad page.
             "https://cbe.rutgers.edu/people/faculty"),
        _rud("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "https://cee.rutgers.edu/civil-and-environmental-engineering-faculty"),
        _rud("MSE", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"],
             "https://mse.rutgers.edu/materials-science-and-engineering-department-faculty"),
        _rud("ISE", "Department of Industrial and Systems Engineering",
             ["Industrial and Systems Engineering"],
             # Scoped pages are JS A-Z shells; /people/all is server-rendered
             # (staff mixed in; cards carry no profile link).
             "https://ise.rutgers.edu/people/all", ladder=_LADDER_MIXED,
             paginate={"param": "page", "start": 1, "max": 3}),
        # ---- SEBS Drupal person-card sites ----------------------------------
        _rud("DEENR", "Department of Ecology, Evolution and Natural Resources",
             ["Ecology, Evolution and Natural Resources", "Environmental Sciences"],
             "https://deenr.rutgers.edu/faculty", section_filter=_SEC_NO_EMERITI),
        _rud("DBM", "Department of Biochemistry and Microbiology",
             ["Biochemistry", "Microbiology"],
             "https://dbm.rutgers.edu/personnel/faculty",
             section_filter=_SEC_NO_EMERITI),
        _rud("PLBIO", "Department of Plant Biology", ["Plant Biology", "Biotechnology"],
             "https://plantbiology.rutgers.edu/personnel/faculty",
             section_filter=_SEC_NO_EMERITI),
        _rud("ANSCI", "Department of Animal Sciences", ["Animal Science"],
             "https://animalsciences.rutgers.edu/personnel",
             section_filter={"heading": "h2",
                             "include": r"^faculty$|department chair",
                             "exclude": r"emerit|staff"}),
        # ---- SEBS legacy static + WordPress sites ---------------------------
        _sebs_static("ENVSCI", "Department of Environmental Sciences",
                     ["Environmental Sciences"],
                     "https://envsci.rutgers.edu/people/faculty/"),
        _sebs_static("NUTR", "Department of Nutritional Sciences",
                     ["Nutritional Sciences"],
                     "https://nutrition.rutgers.edu/faculty/index.html"),
        {
            "short": "ENTO", "name": "Department of Entomology", "majors": ["Entomology"],
            "directory_url": "https://entomology.rutgers.edu/personnel/faculty.html",
            "scrape": {
                "url": "https://entomology.rutgers.edu/personnel/faculty.html",
                "selectors": {
                    "card": "div.contact", "name": "a", "link": "a",
                    # Rank leads the 2nd paragraph ("Professor<br><i>Research:</i> …").
                    "title": "p:nth-of-type(2)",
                    "title_strip_after": r"\bResearch\b",
                    "research_re": r"Research:\s*</i>\s*([^<>]{4,300})",
                },
                "ladder_filter": _LADDER_SEBS,
                # No listing emails; profile mailtos are HTML-entity-obfuscated,
                # which the parser decodes transparently.
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "email_drop": r"^[^@]*$", "throttle": 0.2},
            },
        },
        {
            "short": "FOODSCI", "name": "Department of Food Science", "majors": ["Food Science"],
            "directory_url": "https://foodsci.rutgers.edu/faculty/",
            "scrape": {
                "url": "https://foodsci.rutgers.edu/faculty/",
                "selectors": {
                    "card": "div.box-nav", "name": "strong a", "link": "strong a",
                    "title": "span.i-teacher", "research": "span.i-degree",
                    "email": "span.i-email a[href^='mailto:']",
                },
                "ladder_filter": _LADDER_SEBS,
            },
        },
        {
            "short": "MARINE", "name": "Department of Marine and Coastal Sciences",
            "majors": ["Marine Sciences"],
            "directory_url": "https://marine.rutgers.edu/our-team/faculty/",
            "scrape": {
                "url": "https://marine.rutgers.edu/our-team/faculty/",
                # No per-person pages (inline popups) — records point at the
                # directory; popup research is prose, not scraped.
                "selectors": {
                    "card": "div.team-manager-free-items",
                    "name": ".team-manager-free-items-title",
                    "title": ".team-manager-free-items-designation",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER_SEBS,
            },
        },
        {
            "short": "HUMECO", "name": "Department of Human Ecology",
            "majors": ["Environmental Sciences", "Public Health"],
            "directory_url": "https://humanecology.rutgers.edu/people/faculty/",
            "scrape": {
                "url": "https://humanecology.rutgers.edu/people/faculty/",
                "selectors": {
                    "card": "div.wp-block-media-text",
                    "name": "h4.wp-block-heading", "link": "h4 a",
                    # Some blocks run rank + "Research Interests:" into one
                    # paragraph — keep only the rank.
                    "title": "h4 + p",
                    "title_strip_after": r"\s*Research Interests",
                    # Clean semicolon-separated line after the italic label.
                    "research_re": r"Research Interests:?\s*</em>\s*(?:<br\s*/?>)?\s*(.*?)</p>",
                },
                "ladder_filter": _LADDER_SEBS,
            },
        },
        # ---- Professional schools -------------------------------------------
        {
            "short": "RBS", "name": "Rutgers Business School",
            "majors": ["Finance", "Accounting", "Marketing", "Supply Chain Management",
                       "Business Analytics and Information Technology", "Management"],
            "directory_url": "https://www.business.rutgers.edu/faculty-research/faculty-profiles",
            "scrape": {
                "url": "https://www.business.rutgers.edu/faculty-research/faculty-profiles",
                "selectors": {
                    "card": "div.node--type-faculty", "name": "h2 a", "link": "h2 a",
                    "title": "p.subtitle",
                    # One clean academic-area tag per card.
                    "research_items": "div.tags a",
                },
                "ladder_filter": {"require": _REQ, "drop": r"emerit|visiting"},
                "paginate": {"param": "page", "start": 1, "max": 9},
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "email_drop": r"^[^@]*$", "throttle": 0.2},
            },
        },
        {
            "short": "SMLR", "name": "School of Management and Labor Relations",
            "majors": ["Human Resource Management", "Labor Studies and Employment Relations"],
            "directory_url": "https://smlr.rutgers.edu/faculty-staff",
            "scrape": {
                "url": "https://smlr.rutgers.edu/faculty-staff",
                "selectors": {
                    "card": "div.listing-item.profile-item",
                    "name": ".profile-title a", "link": ".profile-title a",
                    "title": "ul.profile-roles li",
                    "email": ".profile-email a[href^='mailto:']",
                },
                "ladder_filter": _LADDER_MIXED,
                "paginate": {"param": "page", "start": 1, "max": 21},
            },
        },
        {
            "short": "PHARM", "name": "Ernest Mario School of Pharmacy",
            "majors": ["Pharmacy (PharmD)", "Pharmaceutical Sciences"],
            "directory_url": "https://pharmacy.rutgers.edu/directory/",
            "scrape": {
                "url": "https://pharmacy.rutgers.edu/directory/",
                "selectors": _RUD_SELECTORS,
                "ladder_filter": _LADDER_MIXED,
                "profile_enrich": _RUD_ENRICH,
            },
        },
        {
            "short": "BLOUST",
            "name": "Edward J. Bloustein School of Planning and Public Policy",
            "majors": ["Planning and Public Policy", "Public Health", "Health Administration"],
            "directory_url": "https://bloustein.rutgers.edu/faculty/",
            # Names-only archive: titles default to "Professor"; per-person
            # emails are unpublished (profile mailto is the shared ejb@ alias)
            # and profile research is prose — no enrich.
            "scrape": {
                "url": "https://bloustein.rutgers.edu/faculty/",
                "selectors": {"card": "h2.entry-title", "name": "a", "link": "a"},
            },
        },
        {
            "short": "SCI", "name": "School of Communication and Information",
            "majors": ["Communication", "Journalism and Media Studies",
                       "Information Technology and Informatics"],
            "directory_url": "https://sci.rutgers.edu/people/all",
            # The all-people roster mixes ~70 faculty into ~440 doctoral
            # students/staff at 10/page, so most pages hold zero faculty and
            # the scrape paginator's fresh-break would stop after a few pages
            # (ladder-filtering happens per page). The sitemap source's
            # list-pages mode sidesteps that: harvest every profile link from
            # the 45 listing pages, then parse each profile (name h1, rank h2,
            # mailto) behind the professor require-gate. Doctoral students and
            # emeriti carry their real rank on the profile, so the gate holds.
            "sitemap": {
                "list_pages_template": (
                    "https://sci.rutgers.edu/people/all?page={n}", 0, 45),
                "include": r"sci\.rutgers\.edu/[a-z][a-z.]*(?:-[a-z.]+)+$",
                "exclude": (r"about-sci|admissions|continuing-and-professional"
                            r"|staff-directory|student-services|people|media"),
                "selectors": {"name": "h1.new-person__title",
                              "title": "h2.new-person__titles",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": _LADDER_MIXED,
                "throttle": 0.15,
                "cap": 520,
            },
        },
        # ---- School of Nursing (WP JSON feed, 3 pages) ----------------------
        _nurs_page("NURS", 1),
        _nurs_page("NURS2", 2),
        _nurs_page("NURS3", 3),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
