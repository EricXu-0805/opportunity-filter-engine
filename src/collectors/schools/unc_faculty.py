"""UNC-Chapel Hill faculty config (via the faculty_graph engine).

University of North Carolina at Chapel Hill. Every department below was
live-verified through the build recon on 2026-07-26 (card selectors run against
the real listing HTML, card counts + sample name/link/email extracted). UNC's
department sites run a wide spread of WordPress/Toolset themes plus the School
of Medicine "directory-gallery" template and the Gillings TablePress rosters, so
several distinct card shapes are covered:

* **CS grid** — ``cs.unc.edu/people/`` renders each person as a ``div.people``
  card (name+profile link in ``h2 a``, rank in ``h3``, a public ``mailto``).
* **Toolset-Views card** — the College of Arts & Sciences workhorse. Political
  Science (``.fac-wrap``), Philosophy / Classics (``div.person``), and the
  modern WP query-loop departments (``li.wp-block-post`` with a
  ``h2.wp-block-post-title a`` name link: Public Policy, Romance Studies, Art,
  History) all sit here. Public Policy carries the rank in an ACF value field;
  History paginates path-style over ``/role/faculty/page/N/``.
* **Hand-built HTML tables** — Sociology / Geography (``table.table tbody tr``),
  American Studies (5-col table, names inverted -> ``name_flip``), and the
  TablePress rosters (Communication, Music, and all five Gillings public-health
  departments) whose ``td:nth-child`` columns carry name / title / mailto.
* **School of Medicine directory-gallery** — the basic-science departments
  (Biochemistry, Genetics, Pharmacology, Cell Biology & Physiology) render
  ``article.row.post.entry`` cards; Microbiology & Immunology uses the newer
  ``li.row.post.entry`` variant.
* **WP REST** — Eshelman Pharmacy and the School of Data, Society & Information
  (which now houses both SILS and the Data Science division) expose a
  ``wp-json/wp/v2`` person feed; the ``api`` block pulls name/title/email from
  the ACF payload and filters to a division / faculty ``class_list`` tag.

Research keywords are NOT captured on this pass: UNC ITS runs an IP-based WAF
that bans request bursts, so the per-profile ``profile_enrich`` follow (thousands
of fetches) is deliberately deferred — the directory-level harvest below is
throttled to stay under the burst threshold. A later research-capture pass can
layer keywords in via ``_carry_forward_enrichment`` without re-fetching listings.

Live-verified card counts (pre-ladder / pre-dedupe, 2026-07-26): CS 126,
Political Science 45, Sociology 26, Geography 25, Anthropology 29, Public Policy
26 (+13 teaching/research), City & Regional Planning 20, American Studies 15,
English 78, History ~51, Philosophy 36, Religious Studies 22, Romance Studies 53,
Germanic & Slavic 23, Asian & Middle Eastern 39, Communication 91, Music 44, Art
32, Classics 31, Gillings Biostatistics 144, Epidemiology 225, Environmental
Sciences 132, Health Behavior 24, Nutrition 71, Eshelman Pharmacy 125, SILS 32,
Data Science 45, Kenan-Flagler Business 149, Education 126, Hussman Journalism
126, SOM Biochemistry 75, Genetics 24 (+siblings), Pharmacology 38, Cell
Biology 48, Microbiology & Immunology 38.

The natural-sciences departments (Physics, Chemistry, Biology, Mathematics,
Statistics & OR, Earth-Marine-Environmental, Psychology & Neuroscience, Applied
Physical Sciences) and Economics were WAF-blocked during recon and are pending
individual DOM verification before wiring.

Single source ("unc_faculty"); department rides each record, ids namespaced by
department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Gillings School of Global Public Health: shared TablePress roster -------
# One TablePress table per department page; the first cell is name+profile link
# (-> /adv_profile/<slug>/), the second the rank, the third a public mailto. The
# rosters mix in staff + emeritus, so a ladder gate keeps professorial ranks.
_GILLINGS_SEL = {
    "card": "table.tablepress tbody tr",
    "name": "td:nth-child(1) a",
    "link": "td:nth-child(1) a",
    "title": "td:nth-child(2)",
    "email": "td:nth-child(3) a[href^='mailto:']",
}
_GILLINGS_LADDER = {"require": r"professor|lecturer", "drop": r"emerit"}


def _gillings_dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Gillings SPH department on the shared TablePress roster theme."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _GILLINGS_SEL,
                   "ladder_filter": _GILLINGS_LADDER},
    }


# ---- School of Medicine basic-science "directory-gallery" card ---------------
# Each faculty is an ``article.row.post.entry``; name+profile link in
# ``h2.entry-title a``, rank in the first ``<strong>`` of the content column,
# email inconsistently on the listing (profile fills the rest — deferred). The
# curated per-rank / faculty galleries already exclude students, but a light
# ladder gate drops any emeritus/adjunct the pages mix in.
_SOM_SEL = {
    "card": "article.row.post.entry",
    "name": "h2.entry-title a",
    "link": "h2.entry-title a",
    "title": ".directory-gallery-content p strong",
    "email": ".directory-gallery-content a[href^='mailto:']",
}
_SOM_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|adjunct"}


def _som_dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A SOM basic-science department on the directory-gallery card."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SOM_SEL,
                   "ladder_filter": _SOM_LADDER},
    }


# ---- Modern WP query-loop card (Toolset / block theme) -----------------------
# ``li.wp-block-post`` with the name+profile link in ``h2.wp-block-post-title a``.
# Shared by Romance Studies, Art (names inverted -> name_flip), and — with an
# extra ACF rank field — Public Policy. History uses the same card on its role
# archive but paginates path-style.
_WPLOOP_SEL = {
    "card": "li.wp-block-post",
    "name": "h2.wp-block-post-title a",
    "link": "h2.wp-block-post-title a",
}


# ============================================================================
SCHOOL: dict = {
    "school_slug": "unc",
    "source": "unc_faculty",
    "organization": "University of North Carolina at Chapel Hill",
    "location": "Chapel Hill, NC",
    "id_prefix": "unc",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of North Carolina at Chapel Hill) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Computer Science ----------------------------------------------
        {
            "short": "CS", "name": "Department of Computer Science",
            "majors": ["Computer Science"],
            "directory_url": "https://cs.unc.edu/people/",
            "scrape": {
                "url": "https://cs.unc.edu/people/",
                "selectors": {
                    "card": "div.people", "name": "h2 a", "link": "h2 a",
                    "title": "h3", "email": "a[href^='mailto:']",
                },
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"emerit"},
            },
        },
        # ---- Arts & Sciences: social sciences ------------------------------
        {
            "short": "POLI", "name": "Department of Political Science",
            "majors": ["Political Science"],
            "directory_url": "https://politicalscience.unc.edu/people/faculty/",
            "scrape": {
                "url": "https://politicalscience.unc.edu/people/faculty/",
                "selectors": {"card": ".fac-wrap", "name": "h2 a",
                              "link": "h2 a", "title": "strong",
                              "email": "a[href^='mailto:']"},
            },
        },
        {
            "short": "SOCI", "name": "Department of Sociology",
            "majors": ["Sociology"],
            "directory_url": "https://sociology.unc.edu/people/faculty/",
            "scrape": {
                "url": "https://sociology.unc.edu/people/faculty/",
                "selectors": {"card": "table.table tbody tr",
                              "name": "strong a", "link": "strong a",
                              "email": "a[href^='mailto:']"},
            },
        },
        {
            "short": "GEOG", "name": "Department of Geography & Environment",
            "majors": ["Geography", "Environmental Studies"],
            "directory_url": "https://geography.unc.edu/people/faculty/",
            "scrape": {
                "url": "https://geography.unc.edu/people/faculty/",
                "selectors": {
                    "card": "table.table tbody tr",
                    "name": "td:nth-of-type(2) > a, td:nth-of-type(2) > strong",
                    "link": "td:nth-of-type(2) > a",
                    "email": "td:nth-of-type(2)"},
            },
        },
        {
            "short": "ANTH", "name": "Department of Anthropology",
            "majors": ["Anthropology", "Archaeology"],
            "directory_url": "https://anthropology.unc.edu/faculty/",
            "scrape": {
                "url": "https://anthropology.unc.edu/faculty/",
                "selectors": {"card": ".col-md-6", "name": "h2 a",
                              "link": "h2 a", "title": "p strong",
                              "email": "a[href^='mailto:']"},
            },
        },
        {
            "short": "PLCY", "name": "Department of Public Policy",
            "majors": ["Public Policy"],
            "directory_url": "https://publicpolicy.unc.edu/people/core-faculty/",
            "scrape": {
                "url": "https://publicpolicy.unc.edu/people/core-faculty/",
                "selectors": {
                    **_WPLOOP_SEL,
                    "title": ".is-acf-field.is-text-field .value",
                    "email": "a[href^='mailto:']"},
            },
        },
        {
            "short": "PLCY", "name": "Department of Public Policy",
            "majors": ["Public Policy"],
            "directory_url": "https://publicpolicy.unc.edu/people/teaching-research-faculty/",
            "scrape": {
                "url": "https://publicpolicy.unc.edu/people/teaching-research-faculty/",
                "selectors": {
                    **_WPLOOP_SEL,
                    "title": ".is-acf-field.is-text-field .value",
                    "email": "a[href^='mailto:']"},
            },
        },
        {
            "short": "PLAN", "name": "Department of City & Regional Planning",
            "majors": ["Urban Planning", "City and Regional Planning"],
            "directory_url": "https://planning.unc.edu/full-time-faculty/",
            "scrape": {
                "url": "https://planning.unc.edu/full-time-faculty/",
                "selectors": {
                    "card": ".wpv-block-loop-item",
                    "name": "h2.wp-block-heading a",
                    "link": "h2.wp-block-heading a",
                    "title": "h2.wp-block-heading + p",
                    "email": "a[href^='mailto:']"},
            },
        },
        {
            "short": "AMST", "name": "Department of American Studies",
            "majors": ["American Studies", "Folklore",
                       "American Indian and Indigenous Studies"],
            "directory_url": "https://americanstudies.unc.edu/faculty/",
            "scrape": {
                "url": "https://americanstudies.unc.edu/faculty/",
                "selectors": {"card": "table tbody tr",
                              "name": "td:nth-of-type(2) a",
                              "link": "td:nth-of-type(2) a",
                              "title": "td:nth-of-type(3)",
                              "email": "a[href^='mailto:']"},
                "name_flip": True,
            },
        },
        # ---- Arts & Sciences: humanities -----------------------------------
        {
            "short": "ENGL",
            "name": "Department of English & Comparative Literature",
            "majors": ["English", "Comparative Literature", "Creative Writing"],
            "directory_url": "https://englishcomplit.unc.edu/people/faculty/",
            "scrape": {
                "url": "https://englishcomplit.unc.edu/people/faculty/",
                "selectors": {"card": "div.faclist", "name": "a", "link": "a"},
            },
        },
        {
            "short": "HIST", "name": "Department of History",
            "majors": ["History"],
            "directory_url": "https://history.unc.edu/role/faculty/",
            "scrape": {
                "url": "https://history.unc.edu/role/faculty/",
                "selectors": {"card": "li.wp-block-post",
                              "name": ".wp-block-post-title a",
                              "link": ".wp-block-post-title a"},
                "paginate": {"mode": "path", "param": "page",
                             "start": 2, "max": 6},
            },
        },
        {
            "short": "PHIL", "name": "Department of Philosophy",
            "majors": ["Philosophy", "PPE"],
            "directory_url": "https://philosophy.unc.edu/people-page/faculty/",
            "scrape": {
                "url": "https://philosophy.unc.edu/people-page/faculty/",
                "selectors": {"card": "div.person",
                              "name": ".personname a, .personname",
                              "link": "a"},
            },
        },
        {
            "short": "RELI", "name": "Department of Religious Studies",
            "majors": ["Religious Studies", "Religion"],
            "directory_url": "https://religion.unc.edu/_people/full-time-faculty/",
            "scrape": {
                "url": "https://religion.unc.edu/_people/full-time-faculty/",
                "selectors": {"card": "td", "name": "a strong, a",
                              "link": "a", "title": "em"},
                "link_filter": r"_people",
            },
        },
        {
            "short": "ROML", "name": "Department of Romance Studies",
            "majors": ["Spanish", "French", "Italian", "Portuguese",
                       "Romance Languages"],
            "directory_url": "https://romancestudies.unc.edu/people/faculty/",
            "scrape": {
                "url": "https://romancestudies.unc.edu/people/faculty/",
                "selectors": {**_WPLOOP_SEL},
            },
        },
        {
            "short": "GSLL",
            "name": "Germanic & Slavic Languages & Literatures",
            "majors": ["German", "Russian", "Slavic Languages",
                       "Central European Studies"],
            "directory_url": "https://gsll.unc.edu/current-faculty/",
            "scrape": {
                "url": "https://gsll.unc.edu/current-faculty/?wpv_view_count=142-TCPID304",
                "selectors": {"card": "div.js-wpv-view-layout > a",
                              "name": "h3", "link": ":self"},
                "paginate": {"param": "wpv_paged", "start": 2, "max": 2},
            },
        },
        {
            "short": "AMES", "name": "Asian & Middle Eastern Studies",
            "majors": ["Asian Studies", "Chinese", "Japanese", "Korean",
                       "Arabic", "Persian", "Hindi-Urdu",
                       "Middle Eastern Studies"],
            "directory_url": "https://asianstudies.unc.edu/people/faculty/",
            "scrape": {
                "url": "https://asianstudies.unc.edu/people/faculty/",
                "selectors": {"card": "h2.faculty-title", "name": "a",
                              "link": "a",
                              "name_strip": r"^(Dr\.|Mr\.|Mrs\.|Ms\.|Prof\.)\s+"},
            },
        },
        {
            "short": "COMM", "name": "Department of Communication",
            "majors": ["Communication", "Media Studies", "Rhetoric",
                       "Performance Studies"],
            "directory_url": "https://comm.unc.edu/people/",
            "scrape": {
                "url": "https://comm.unc.edu/people/",
                "selectors": {"card": "table.tablepress tbody tr",
                              "name": "td.column-2 a", "link": "td.column-2 a",
                              "title": "td.column-3",
                              "email": "td.column-4 a[href^='mailto:']"},
                "link_filter": r"comm\.unc\.edu",
            },
        },
        {
            "short": "MUSC", "name": "Department of Music",
            "majors": ["Music", "Musicology", "Composition", "Performance"],
            "directory_url": "https://music.unc.edu/people/musicfaculty/",
            "scrape": {
                "url": "https://music.unc.edu/people/musicfaculty/",
                "selectors": {
                    "card": "table.tablepress tbody tr",
                    "name": "td a[href*='/people/musicfaculty/']",
                    "link": "td a[href*='/people/musicfaculty/']",
                    "email": "td a[href^='mailto:']"},
            },
        },
        {
            "short": "ART", "name": "Department of Art & Art History",
            "majors": ["Art History", "Studio Art"],
            "directory_url": "https://art.unc.edu/people/art-history-faculty/",
            "scrape": {
                "url": "https://art.unc.edu/people/art-history-faculty/",
                "selectors": {**_WPLOOP_SEL}, "name_flip": True,
            },
        },
        {
            "short": "ART", "name": "Department of Art & Art History",
            "majors": ["Studio Art", "Art History"],
            "directory_url": "https://art.unc.edu/people/studio-art-faculty/",
            "scrape": {
                "url": "https://art.unc.edu/people/studio-art-faculty/",
                "selectors": {**_WPLOOP_SEL}, "name_flip": True,
            },
        },
        {
            "short": "CLAS", "name": "Department of Classics",
            "majors": ["Classics", "Latin", "Greek", "Classical Archaeology"],
            "directory_url": "https://classics.unc.edu/people-3/faculty-2-2/",
            "scrape": {
                "url": "https://classics.unc.edu/people-3/faculty-2-2/",
                "selectors": {"card": "div.person", "name": "a", "link": "a"},
            },
        },
        # ---- Gillings School of Global Public Health -----------------------
        _gillings_dept(
            "BIOS", "Gillings SPH — Biostatistics",
            ["Biostatistics", "Public Health", "Statistics"],
            "https://sph.unc.edu/bios/bios-people/"),
        _gillings_dept(
            "EPID", "Gillings SPH — Epidemiology",
            ["Epidemiology", "Public Health"],
            "https://sph.unc.edu/epid/epid-faculty-and-staff/"),
        _gillings_dept(
            "ENVR", "Gillings SPH — Environmental Sciences & Engineering",
            ["Environmental Sciences", "Environmental Engineering",
             "Environmental Health"],
            "https://sph.unc.edu/envr/envr-our-faculty-and-staff/"),
        _gillings_dept(
            "HB", "Gillings SPH — Health Behavior",
            ["Health Behavior", "Public Health", "Health Education"],
            "https://sph.unc.edu/sph_directory_pt/health-behavior-faculty/"),
        _gillings_dept(
            "NUTR", "Gillings SPH — Nutrition",
            ["Nutrition", "Nutritional Sciences", "Public Health"],
            "https://sph.unc.edu/nutr/unc-nutrition/nutr-our-faculty-and-staff/"),
        # ---- School of Medicine basic-science departments ------------------
        _som_dept(
            "MEDBIOCHEM", "SOM — Biochemistry & Biophysics",
            ["Biochemistry", "Biophysics", "Molecular Biology"],
            "https://www.med.unc.edu/biochem/our-people/faculty/"),
        _som_dept(
            "MEDGEN", "SOM — Genetics",
            ["Genetics", "Genomics", "Molecular Genetics"],
            "https://www.med.unc.edu/genetics/people/professors-and-distinguished-professors/"),
        _som_dept(
            "MEDGEN", "SOM — Genetics",
            ["Genetics", "Genomics", "Molecular Genetics"],
            "https://www.med.unc.edu/genetics/people/associate-professors/"),
        _som_dept(
            "MEDGEN", "SOM — Genetics",
            ["Genetics", "Genomics", "Molecular Genetics"],
            "https://www.med.unc.edu/genetics/people/assistant-professors/"),
        _som_dept(
            "MEDPHARM", "SOM — Pharmacology",
            ["Pharmacology", "Molecular Pharmacology"],
            "https://www.med.unc.edu/pharm/people/primaryfaculty/"),
        _som_dept(
            "MEDCBP", "SOM — Cell Biology & Physiology",
            ["Cell Biology", "Physiology", "Developmental Biology"],
            "https://www.med.unc.edu/cellbiophysio/directory/"),
        {
            "short": "MEDMICRO", "name": "SOM — Microbiology & Immunology",
            "majors": ["Microbiology", "Immunology", "Virology"],
            "directory_url": "https://www.med.unc.edu/microimm/our-faculty-staff/",
            "scrape": {
                "url": "https://www.med.unc.edu/microimm/our-faculty-staff/",
                "selectors": {
                    "card": "li.row.post.entry", "name": "a.post-author",
                    "link": "a.post-author",
                    "title": ".ud-gallery-view__positions__title",
                    "email": ".som-directory-profile-single__contact a[href^='mailto:']"},
                "ladder_filter": _SOM_LADDER,
            },
        },
        # ---- Professional schools ------------------------------------------
        {
            "short": "EDUC", "name": "School of Education",
            "majors": ["Education", "Learning Sciences",
                       "Educational Psychology", "Teacher Education",
                       "School Psychology", "Educational Leadership"],
            "directory_url": "https://ed.unc.edu/people/",
            "scrape": {
                "url": "https://ed.unc.edu/people/",
                "selectors": {
                    "card": "div.person-listing",
                    "name": ".person-listing__content h2 a",
                    "link": ".person-listing__content h2 a",
                    "title": ".headline-group__sub",
                    "email": ".person__detail--email a[href^='mailto:']"},
            },
        },
        {
            "short": "HUSSMAN",
            "name": "Hussman School of Journalism & Media",
            "majors": ["Journalism", "Media", "Advertising",
                       "Public Relations", "Media & Communication"],
            "directory_url": "https://hussman.unc.edu/about/directory",
            "scrape": {
                "url": "https://hussman.unc.edu/about/directory",
                "selectors": {"card": "div.faculty.partial",
                              "name": "h2.title a", "link": "h2.title a",
                              "title": ".meta p"},
                "ladder_filter": {"require": r"professor|lecturer|instructor",
                                  "drop": r"emerit"},
            },
        },
        {
            "short": "KFBS", "name": "Kenan-Flagler Business School",
            "majors": ["Business Administration", "Finance", "Accounting",
                       "Marketing", "Strategy & Entrepreneurship",
                       "Operations", "Organizational Behavior", "Economics"],
            "directory_url": "https://www.kenan-flagler.unc.edu/faculty/",
            "scrape": {
                "url": "https://www.kenan-flagler.unc.edu/faculty/",
                "selectors": {"card": "div.partial-faculty",
                              "name": ".content h3", "link": "a",
                              "title": ".content p"},
                "paginate": {"param": "pg", "start": 2, "max": 6},
            },
        },
        # ---- WP REST feeds -------------------------------------------------
        {
            "short": "PHARM", "name": "Eshelman School of Pharmacy",
            "majors": ["Pharmacy", "Pharmaceutical Sciences", "Pharmacology",
                       "Medicinal Chemistry", "Drug Discovery"],
            "directory_url": "https://pharmacy.unc.edu/directory/",
            "api": {
                "type": "wp", "base": "https://pharmacy.unc.edu",
                "post_type": "faculty",
                "category_include": {"class_list": {"faculty-staff-type-faculty"}},
                "acf_fields": {"title": "acf.title.simple_value_formatted",
                               "email": "acf.email"},
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"emerit"},
            },
        },
        {
            "short": "SILS",
            "name": "School of Information & Library Science",
            "majors": ["Information Science", "Library Science",
                       "Information & Library Science"],
            "directory_url": "https://sdis.unc.edu/people/",
            "api": {
                "type": "wp", "base": "https://sdis.unc.edu",
                "post_type": "person",
                "category_include": {"class_list": {"division-information-library-science"}},
                "acf_fields": {"title": "acf.official_title.simple_value_formatted",
                               "email": "acf.email_address.simple_value_formatted"},
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"emerit"},
            },
        },
        {
            "short": "SDSS", "name": "School of Data Science & Society",
            "majors": ["Data Science", "Statistics", "Machine Learning",
                       "Applied Data Science"],
            "directory_url": "https://sdis.unc.edu/people/",
            "api": {
                "type": "wp", "base": "https://sdis.unc.edu",
                "post_type": "person",
                "category_include": {"class_list": {"division-data-science-society"}},
                "acf_fields": {"title": "acf.official_title.simple_value_formatted",
                               "email": "acf.email_address.simple_value_formatted"},
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"emerit"},
            },
        },
    ],
}


# UNC ITS fronts every ``*.unc.edu`` site with an IP-based, burst-rate WAF that
# returns a "Forbidden - UNC Chapel Hill" 403 after a run of rapid fetches (and
# holds the ban for many minutes). A terminal 403 would silently drop the whole
# department, so every listing hit is spaced with the engine's ``pre_delay`` to
# stay under the threshold — the directory harvest trades wall-clock for not
# tripping the WAF. (WP-REST ``api`` departments page internally and are ordered
# last.)
_WAF_DELAY_S = 9
for _dept in SCHOOL["departments"]:
    _scrape = _dept.get("scrape")
    if _scrape is not None:
        _scrape.setdefault("pre_delay", _WAF_DELAY_S)


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
