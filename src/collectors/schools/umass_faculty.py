"""UMass Amherst faculty config (via the faculty_graph engine).

Three server-rendered Drupal markup families, live-verified 2026-07-17 (no
WAF; plain requests return full HTML on umass.edu and cics.umass.edu):

* Unified "article.person" college-directory theme — the College of
  Engineering and every college that runs a college-level ``/about/directory``
  (College of Natural Sciences central, Education, Nursing, School of Public
  Health & Health Sciences). Faceted by profile-type (the per-college
  "Faculty" term id) and department via URL query; standard Drupal ``?page=N``
  pager (0-indexed, 10 cards/page — the base faceted URL IS page 0). Emeriti
  ride inside the Faculty facet, so a ladder drop-regex prunes them.
  Engineering profiles carry clean college research-area taxonomy chips
  (``a[href*='/research/research-areas/']``) → profile_enrich; the other
  person-family colleges keep only prose bios on profiles = no enrich.

* Per-department "teaser-item profile" theme — most CNS science departments
  with their own subsite, all SBS and all HFA departments. Faceted by
  profile-type (the "Faculty" term id varies per dept — commonly 1 or 5,
  Chemistry 25; each dept's ids were read off its live filter labels, which
  corrected five recon ids; Political Science, Music & Dance, VASci and SPP
  split faculty across TWO facet ids), same ``?page=N`` pager. Listings carry name/title only; profile emails are rot13
  ``data-mail-to`` and research interests are prose bios — no enrich.

* CICS "person--card-long" (cics.umass.edu) — single page (no pager), the
  only family with plain mailto emails on the listing (``a.person__email``).
  The listing shows one research-area chip + "+N more"; the full clean
  taxonomy list lives on each profile → profile_enrich research_items.
  The Faculty facet includes deans/directors/part-time lecturers, so this
  family gets a require+drop ladder gate.

Emails: umass.edu obfuscates addresses campus-wide — person-theme profiles as
spamspan "[at]/[dot]" text, teaser subsites as rot13 ``data-mail-to``. Both
are deterministic and the engine decodes them (``_decode_rot13email`` + the
written-out at/dot normalization in ``_clean_email``), so every family runs a
``profile_enrich`` email pass.

Single source ("umass_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred (from the 2026-07-17 recon):
* Isenberg School of Management — JS-rendered React app over a Drupal
  JSON:API; the person collection endpoint was not resolvable, needs a
  headless browser or reverse-engineered API path.
* Polymer Science & Engineering — separate host pse.umass.edu unreachable
  (connection code 000) throughout recon; only 4 research-track PSE people on
  the CNS-central directory. Retry the subsite later.
* UMass Chan Medical School — Worcester campus, separate institution
  (umassmed.edu, different OpenAlex org); out of scope for Amherst.
* Geosciences (legacy standalone) — slug 404s; folded into Earth, Geographic
  & Climate Sciences (covered via EGCS, dept facet 231).
* Commonwealth Honors College — no faculty roster (draws faculty from every
  department; runs programs, covered on the campus side).
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Unified college-level Drupal "article.person" theme -------------------
_PERSON_SELECTORS = {
    "card": "div.listing__row.views-row article.person",
    "name": "h2.person__title a",
    "link": "h2.person__title a",
    "title": "div.person__position-role",
}

# ---- Per-department Drupal "teaser-item profile" theme ---------------------
_TEASER_SELECTORS = {
    "card": "div.teaser-item.profile",
    "name": "div.title-wrapper a.title",
    "link": "div.title-wrapper a.title",
    "title": "div.prof-title-role",
}

# The profile-type facets already exclude staff/grad students/postdocs, but
# emeriti (and the odd visiting title) ride inside the Faculty facet on both
# umass.edu families — drop them by title.
_LADDER = {"drop": r"emerit|visiting|postdoc"}

# Drupal pager: base faceted URL is page 0, then &page=1..N (10 cards/page).
# max=16 covers the largest roster (SPHHS ~137); the engine stops at the first
# page that surfaces no new people, so a generous cap costs nothing.
_PAGINATE = {"param": "page", "start": 1, "max": 16}

# Profile emails are obfuscated campus-wide but deterministically decodable:
# person-theme profiles carry spamspan "[at]/[dot]" text, teaser subsites a
# rot13 ``data-mail-to`` — both handled by the engine's email chain.
_EMAIL_ENRICH = {
    "email_selector": "span.spamspan, a[data-mail-to], a[href^='mailto:']",
    "email_drop": r"^[^@]*$|department@|info@",
    # Research lives on the profile in one of three clean atomic-chip shapes,
    # combined so every family gets it: the /research/research-areas/ taxonomy
    # links (Engineering/CICS/person-theme colleges), the teaser subsites'
    # "Research Areas" tag-cloud, and the "RESEARCH INTERESTS/AREAS" list-items.
    # Each yields nothing where absent (safe); the Sociology delimited-<p> line
    # is deliberately NOT included (prose-leak risk on a shared enrich).
    "research_items_selector": (
        "a[href*='/research/research-areas/'], "
        "h2:-soup-contains('Research Areas') + div.link-list div.tag, "
        "h2:-soup-contains('RESEARCH INTERESTS') + ul.list-items li, "
        "h2:-soup-contains('RESEARCH AREAS') + ul.list-items li"),
    "throttle": 0.2,
}

# Back-compat alias — the research chips now live on the shared enrich, so the
# Engineering/CICS "area chip" enrich is just the base enrich.
_AREA_CHIP_ENRICH = _EMAIL_ENRICH


def _person(short: str, name: str, majors: list[str], college: str,
            ptype: int, dept: int | None = None, enrich: dict | None = None) -> dict:
    """A department/college on the unified "article.person" theme."""
    url = (f"https://www.umass.edu/{college}/about/directory"
           f"?s=&field_person__profile_type_ref_target_id%5B{ptype}%5D={ptype}")
    if dept:
        url += f"&field_person__department_target_id%5B{dept}%5D={dept}"
    scrape = {"url": url, "selectors": _PERSON_SELECTORS,
              "ladder_filter": _LADDER, "paginate": _PAGINATE,
              "profile_enrich": enrich or _EMAIL_ENRICH}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _engin(short: str, name: str, majors: list[str], dept: int) -> dict:
    """A College of Engineering department (Faculty facet 411 + dept facet)."""
    return _person(short, name, majors, "engineering", 411, dept,
                   enrich=_AREA_CHIP_ENRICH)


def _teaser(short: str, name: str, majors: list[str], slug: str,
            facets: list[int], path: str = "/about/directory") -> dict:
    """A department subsite on the "teaser-item profile" theme."""
    query = "&".join(f"field_profile_type_target_id%5B{f}%5D={f}" for f in facets)
    url = f"https://www.umass.edu/{slug}{path}?{query}"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _TEASER_SELECTORS,
                       "ladder_filter": _LADDER, "paginate": _PAGINATE,
                       "profile_enrich": _EMAIL_ENRICH}}


_CICS_URL = ("https://www.cics.umass.edu/about/directory"
             "?s=&field_person__profile_type_ref_target_id%5B351%5D=351")

SCHOOL: dict = {
    "school_slug": "umass",
    "source": "umass_faculty",
    "organization": "University of Massachusetts Amherst",
    "location": "Amherst, MA",
    "id_prefix": "umass",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Massachusetts Amherst) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Manning College of Information & Computer Sciences ------------
        {
            "short": "CS",
            "name": "Manning College of Information and Computer Sciences",
            "majors": ["Computer Science", "Informatics", "Data Science"],
            "directory_url": _CICS_URL,
            "scrape": {
                "url": _CICS_URL,
                "selectors": {
                    "card": "div.listing__row.views-row div.person--card-long",
                    "name": "div.person__title",
                    "link": "a[href*='/about/directory/']",
                    "title": "div.person__role",
                    "email": "a.person__email",
                },
                # The Faculty facet also carries deans / program directors /
                # part-time (industry) lecturers — require a professorial rank.
                "ladder_filter": {
                    "require": r"professor|lecturer|teaching faculty",
                    "drop": r"emerit|part-?time lecturer|visiting|postdoc",
                },
                "profile_enrich": _AREA_CHIP_ENRICH,
            },
        },
        # ---- Riccio College of Engineering ---------------------------------
        _engin("BME", "Biomedical Engineering", ["Biomedical Engineering"], 321),
        _engin("ChemE", "Chemical and Biomolecular Engineering",
               ["Chemical Engineering"], 286),
        _engin("CEE", "Civil and Environmental Engineering",
               ["Civil Engineering", "Environmental Engineering"], 291),
        _engin("ECE", "Electrical and Computer Engineering",
               ["Electrical Engineering", "Computer Engineering"], 296),
        _engin("MIE", "Mechanical and Industrial Engineering",
               ["Mechanical Engineering", "Industrial Engineering"], 301),
        # ---- College of Natural Sciences (dept subsites, teaser theme) -----
        _teaser("Physics", "Department of Physics", ["Physics"], "physics", [1]),
        _teaser("Math-Stat", "Department of Mathematics and Statistics",
                ["Mathematics", "Statistics"], "mathematics-statistics", [1]),
        _teaser("Chemistry", "Department of Chemistry", ["Chemistry"],
                "chemistry", [25], path="/people"),
        _teaser("Biology", "Department of Biology", ["Biology"], "biology", [1]),
        _teaser("Microbiology", "Department of Microbiology", ["Microbiology"],
                "microbiology", [1]),
        _teaser("BMB", "Department of Biochemistry and Molecular Biology",
                ["Biochemistry & Molecular Biology"],
                "biochemistry-molecular-biology", [1]),
        _teaser("Astronomy", "Department of Astronomy", ["Astronomy", "Physics"],
                "astronomy", [1]),
        _teaser("Food-Sci", "Department of Food Science", ["Food Science"],
                "food-science", [1]),
        _teaser("EnvCon", "Department of Environmental Conservation",
                ["Environmental Science", "Building & Construction Technology"],
                "environmental-conservation", [1]),
        _teaser("Stockbridge", "Stockbridge School of Agriculture",
                ["Sustainable Food & Farming", "Plant & Soil Sciences",
                 "Horticultural Science"], "stockbridge", [1]),
        # Faculty=1 + Research Faculty=24 (both run labs; Vet Tech=11 excluded).
        _teaser("VASci", "Department of Veterinary and Animal Sciences",
                ["Animal Science"], "veterinary-animal-sciences", [1, 24]),
        # ---- CNS departments with no standalone directory (via CNS central) -
        _person("PBS", "Department of Psychological and Brain Sciences",
                ["Psychology", "Neuroscience"], "natural-sciences", 336, 256),
        _person("EGCS", "Department of Earth, Geographic and Climate Sciences",
                ["Geology", "Geography", "Environmental Science"],
                "natural-sciences", 336, 231),
        _person("SES", "School of Earth and Sustainability",
                ["Environmental Science", "Geology"], "natural-sciences", 336, 261),
        # ---- College of Social & Behavioral Sciences -----------------------
        _teaser("Economics", "Department of Economics", ["Economics"],
                "economics", [1]),
        _teaser("Sociology", "Department of Sociology", ["Sociology"],
                "sociology", [1]),
        # Faculty split across two facets: Graduate=1 + Undergraduate=46.
        _teaser("PoliSci", "Department of Political Science",
                ["Political Science"], "political-science", [1, 46]),
        _teaser("Communication", "Department of Communication", ["Communication"],
                "communication", [1]),
        _teaser("Anthropology", "Department of Anthropology", ["Anthropology"],
                "anthropology", [1]),
        _teaser("Linguistics", "Department of Linguistics", ["Linguistics"],
                "linguistics", [1]),
        _teaser("ResEc", "Department of Resource Economics",
                ["Resource Economics", "Economics"], "resource-economics", [1]),
        _teaser("Journalism", "Department of Journalism", ["Journalism"],
                "journalism", [1]),
        _teaser("LARP", "Department of Landscape Architecture and Regional Planning",
                ["Landscape Architecture"], "landscape-planning", [1]),
        # Public Policy Faculty=1 + Legal Studies Faculty=28 (DACSS=25 skipped:
        # affiliated faculty whose home departments already carry them).
        _teaser("SPP", "School of Public Policy", ["Public Policy", "Legal Studies"],
                "public-policy", [1, 28]),
        # ---- College of Humanities & Fine Arts -----------------------------
        _teaser("AfroAm", "W.E.B. Du Bois Department of Afro-American Studies",
                ["Afro-American Studies"], "afro-am", [5]),
        _teaser("History", "Department of History", ["History"], "history", [5]),
        _teaser("English", "Department of English", ["English"], "english", [5]),
        _teaser("Philosophy", "Department of Philosophy", ["Philosophy"],
                "philosophy", [5]),
        _teaser("Classics", "Department of Classics", ["Classics"],
                "classics", [1]),
        _teaser("LLC", "Department of Languages, Literatures and Cultures",
                ["Spanish & Portuguese Studies", "French & Francophone Studies"],
                "languages-literatures-cultures", [1]),
        _teaser("CompLit", "Program in Comparative Literature",
                ["Comparative Literature"], "comparative-literature", [1]),
        _teaser("Art", "Department of Art", ["Studio Art", "Art History"],
                "art", [1]),
        _teaser("Theater", "Department of Theater", ["Theater"], "theater", [5]),
        _teaser("Architecture", "Department of Architecture", ["Architecture"],
                "architecture", [5]),
        # Faculty split across two facets: Music=1 + Dance=33.
        _teaser("Music-Dance", "Department of Music and Dance",
                ["Music", "Dance"], "music-dance", [1, 33]),
        _teaser("WGSS", "Department of Women, Gender, Sexuality Studies",
                ["Women/Gender/Sexuality Studies"], "women-gender-sexuality", [5]),
        # ---- College-level person directories ------------------------------
        _person("Education", "College of Education", ["Education"],
                "education", 271),
        _person("Nursing", "Elaine Marieb College of Nursing", ["Nursing"],
                "nursing", 281),
        _person("SPHHS", "School of Public Health and Health Sciences",
                ["Public Health Sciences", "Kinesiology", "Nutrition",
                 "Communication Disorders"], "public-health-sciences", 391),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
