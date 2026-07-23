"""Michigan State University faculty config (via the faculty_graph engine).

MSU standardized on JS-heavy, WAF-fronted web platforms (a Sitecore/Next.js
headless stack, a Drupal college site, WordPress/Elementor college directories),
with Imperva/Incapsula walling most department subdomains. Only a handful of
directories server-render their roster over plain HTTP; the rest expose faculty
either on per-profile pages (reachable) or only through a virtualized/AJAX widget
(not reachable config-only). Coverage below is accuracy-first: every shipped
department is live-verified real faculty AND majority-emailed. Live-verified
2026-07 (Engineering/Chemistry/Physics 07-19; the rest 07-23/24).

* **College of Engineering — one shared server-rendered directory.**
  ``engineering.msu.edu/directory/faculty`` server-renders every engineering
  faculty member (474 ``li.directory-profile-item`` cards, all employment-type
  "Faculty") with the primary department as a plain-text field per card
  (``.primary-dept-info``). The individual dept subdomains (cse/ece/me/…msu.edu)
  302-redirect here, and the ``?departments=<uuid>`` query filters CLIENT-side
  only — so each department is that ONE directory sliced by a ``field_filter`` on
  ``.primary-dept-info`` (``require_present`` so a field-less card can't fall
  through into every dept). Name + rank on the card; email is plain TEXT in
  ``address p.fw-bold`` (not a mailto). No research on the card → topic keywords
  come from downstream OpenAlex enrichment. The directory mixes ladder faculty
  with postdocs/adjuncts/teaching-specialists/scholars/aides — the ladder filter
  keeps professor/endowed-chair ranks. Eight degree-granting departments wired
  (CS/ECE/ME/BME/CEE/CMSE/ChEMS/BAE); Dean's Office, IQHSE, Applied Engineering
  Sciences, and Technology Engineering deliberately not exposed (admin /
  interdisciplinary / small program units).

* **College of Natural Science — Chemistry (dedicated table) + Physics (partial).**
  ``chemistry.msu.edu`` is an old-CMS ASP.NET page: one ``responsiveTable``, 45
  rows, positional ``p:nth-of-type`` selectors, mailto emails, research-focus
  blurb → keywords. Physics ships the verified condensed-matter group table only
  (``pa.msu.edu/condensed-matter-physics/people/faculty.aspx``, name_flip); the
  department-wide directory (pa.msu.edu / directory.natsci.msu.edu) is JS +
  Incapsula. The other Natural Science departments (Math, Statistics, BMB,
  Microbiology-Genetics-Immunology, Integrative Biology, Plant Biology, Earth &
  Environmental Sciences, Physiology, Neuroscience) are all Incapsula-walled
  and/or JS-rendered — see the phase-2 list.

* **College of Communication Arts and Sciences — Drupal college directory pool.**
  ``comartsci.msu.edu/about/directory`` server-renders the WHOLE college roster
  (338 ``div.views-row`` cards: name ``p.h4`` + designation ``p.h6`` + a
  ``/our-people/<slug>`` "Read more" link) but carries NO email on the card and
  NO clean per-card department field. So it ships as ONE college pool (majors =
  the college's four departments' majors), gated by the designation to
  professor/lecturer ranks (107 faculty of 338; drops advisors/staff/deans/grad),
  with the personal mailto recovered by an ``always`` profile-enrich pass off each
  ``/our-people/`` profile (server-rendered ``a[href^=mailto:]``). The per-
  department directory pages (``/departments/<d>/<d>-directory``) are Drupal-Views
  AJAX (zero static rows) — not used; the college page is the complete roster.

* **College of Arts and Letters — WordPress college directory, sitemap pool.**
  The CAL faculty roster lives on one WordPress site, ``directory.cal.msu.edu``
  (the department subdomains embed it via an Elementor-Pro AJAX loop — no static
  cards, no ``person`` CPT, no scrapeable listing). But every person is a
  server-rendered Elementor profile keyed by NetID (``directory.cal.msu.edu/<netid>/``)
  carrying an ``h1`` name, an ``itemprop="jobTitle"`` rank, and a plain mailto —
  and the site's ``sitemap_index.xml`` enumerates all 248 of them. So CAL ships as
  ONE college pool via the engine's ``sitemap`` source: enumerate the profiles,
  fetch each, keep professor/lecturer/chair ranks (drops the
  instructors/specialists/directors/staff the flat sitemap mixes in), take the
  mailto. No per-card department field → college pool (like the CAS pool). No
  research field on the profile → keywords come from downstream OpenAlex.

Single source ("msu_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred to phase-2 (all live-verified unreachable config-only 2026-07-24):
* **Sitecore/Next.js departments** (Social Science: Economics, Criminal Justice,
  HDFS; Arts&Letters-adjacent: History; College of Education; College of Nursing).
  The ``PeopleList`` directory is a client-fetched, VIRTUALIZED widget: it renders
  only the first ~18 of a ~130-person roster (an alphabetical window) and exposes
  no config-drivable pagination/scroll — so a static or headless-render scrape can
  only capture an arbitrary alphabetical slice, not the department. (Profiles ARE
  server-rendered with a mailto + ``span.tag`` expertise chips — so these become
  reachable the day the engine grows a scroll-driver or the Sitecore Experience-
  Edge GraphQL key.) Shipping 18 padded records was rejected.
* **Incapsula/Imperva-walled hosts**: canr.msu.edu (CANR), broad.msu.edu (Broad
  Business), music.msu.edu (Music), and the Natural Science + several Social
  Science department subdomains (psychology, polisci, sociology, geo, socialwork,
  spdc, bmb, mgi, ees, physiology, neuroscience, plantbiology, …). Every plain
  and proxied fetch returns the Incapsula challenge iframe; the per-profile email
  lives behind the same wall, so a headless listing render couldn't be followed by
  a static profile-enrich anyway. Needs a challenge-passing egress.
* **College of Arts and Letters department granularity**: the CAL directory
  exposes no per-profile department field, so the college pool above cannot be
  split into English / History / Philosophy / Linguistics / Art / Religious
  Studies / WGS. (WordPress department sites — english/linglang/art/theatre/
  philosophy/religiousstudies/wrac — are Elementor-AJAX shells with no static
  listing and no ``person`` REST route.)
* **College of Business, College of Education, College of Nursing, CANR** as
  distinct departments — Incapsula (CANR/Broad) or virtualized Sitecore
  (Education/Nursing), per above.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- College of Engineering: one shared server-rendered directory ----------
_ENG_URL = "https://engineering.msu.edu/directory/faculty"
_ENG_SELECTORS = {
    "card": "li.directory-profile-item",
    "name": "h2.profile-title a",
    "link": "h2.profile-title a",
    "title": "p.profile-position",
    # Email is plain text in the address block (fw-bold line), not a mailto.
    "email": "address p.fw-bold",
}
# Keep ladder / endowed-chair professors; drop the postdocs, adjuncts, teaching
# & outreach specialists, scholars, and aides the shared directory mixes in.
_ENG_LADDER = {"require": r"professor|chair",
               "drop": r"adjunct|emerit|visiting|\bpostdoc"}


def _eng(short: str, name: str, majors: list[str], dept_text: str) -> dict:
    """A College of Engineering department = the shared directory sliced by its
    primary-department text via field_filter."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": _ENG_URL,
        "scrape": {
            "url": _ENG_URL,
            "selectors": _ENG_SELECTORS,
            "ladder_filter": _ENG_LADDER,
            "field_filter": {"selector": ".primary-dept-info",
                             "include": dept_text, "require_present": True},
        },
    }


# ---- College directory pools recovered via per-profile email -----------------
# Two MSU colleges expose a complete college-wide roster but keep the personal
# email only on each person's profile page (no per-card email, no per-card
# department field) — so each ships as ONE college pool, gated to professor/
# lecturer ranks, with the mailto recovered per profile.
#
# CAS (Communication Arts & Sciences): a Drupal college directory whose cards
# server-render; the profile-enrich pass follows each ``/our-people/`` link.
_CAS_URL = "https://comartsci.msu.edu/about/directory"


def _cas_pool() -> dict:
    return {
        "short": "CAS",
        "name": "College of Communication Arts and Sciences",
        "majors": ["Communication", "Journalism", "Advertising",
                   "Media and Information", "Communication Sciences and Disorders"],
        "directory_url": _CAS_URL,
        "scrape": {
            "url": _CAS_URL,
            "selectors": {
                "card": "div.views-row",
                "name": "p.h4",
                "title": ".views-field-field-designation p.h6",
                "link": "a.button-3",
            },
            # Designation mixes deans/advisors/coordinators/grad students with
            # faculty; keep professor/lecturer ranks, drop emeriti/adjuncts.
            "ladder_filter": {"require": r"professor|lecturer",
                              "drop": r"emerit|adjunct"},
            # No email on the card — the personal mailto is on each profile page
            # (``always`` because that IS where the email lives, not extra depth).
            "profile_enrich": {
                "always": True,
                "email_selector": "a[href^='mailto:']",
                "email_drop": r"^[^@]*$|comartsci@|info@|advising@",
                "timeout": 6,
                "throttle": 0.05,
            },
        },
    }


# CAL (Arts & Letters): no scrapeable listing anywhere (Elementor-AJAX), but the
# WordPress directory's sitemap enumerates every NetID-keyed profile, and each
# profile is a server-rendered Elementor page with an ``itemprop="jobTitle"`` rank
# and a mailto. The engine's ``sitemap`` source fetches each and gates on rank.
def _cal_pool() -> dict:
    return {
        "short": "CAL",
        "name": "College of Arts and Letters",
        "majors": ["English", "History", "Philosophy", "Linguistics",
                   "Studio Art", "Art History", "Religious Studies",
                   "Women and Gender Studies"],
        "directory_url": "https://directory.cal.msu.edu/",
        "sitemap": {
            "sitemaps": ["https://directory.cal.msu.edu/sitemap_index.xml"],
            # Profiles are ``/<netid>/`` (lowercase+digits); skip the site pages.
            "include": r"directory\.cal\.msu\.edu/[a-z0-9]+/$",
            "exclude": r"/(welcome|feed|category|author)/",
            "selectors": {
                "name": "h1",
                "title": "[itemprop='jobTitle']",
                "email": "a[href^='mailto:']",
            },
            # Flat sitemap mixes ranks: keep professor/lecturer/(endowed-)chair,
            # drop the instructors/teaching-specialists/directors/staff/emeriti.
            "ladder_filter": {"require": r"professor|lecturer|chair",
                              "drop": r"emerit|adjunct|visiting"},
            "throttle": 0.05,
        },
    }


SCHOOL: dict = {
    "school_slug": "msu",
    "source": "msu_faculty",
    "organization": "Michigan State University",
    "location": "East Lansing, MI",
    "id_prefix": "msu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Michigan State University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering (shared directory, dept-text slice) -----
        _eng("CS", "Department of Computer Science and Engineering",
             ["Computer Science", "Data Science"],
             r"^Computer Science and Engineering"),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             r"^Electrical and Computer Engineering"),
        _eng("ME", "Department of Mechanical Engineering",
             ["Mechanical Engineering"],
             r"^Mechanical Engineering"),
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"],
             r"^Biomedical Engineering"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             r"^Civil and Environmental Engineering"),
        _eng("CMSE", "Department of Computational Mathematics, Science and Engineering",
             ["Computational Mathematics", "Data Science", "Computational Science"],
             r"^Computational Mathematics, Science and Engineering"),
        _eng("ChEMS", "Department of Chemical Engineering and Materials Science",
             ["Chemical Engineering", "Materials Science and Engineering"],
             r"^Chemical Engineering and Materials Science"),
        _eng("BAE", "Department of Biosystems and Agricultural Engineering",
             ["Biosystems Engineering", "Agricultural Engineering"],
             r"^Biosystems and Agricultural Engineering"),
        # ---- College of Natural Science: Chemistry --------------------------
        {
            "short": "CHEM", "name": "Department of Chemistry",
            "majors": ["Chemistry"],
            "directory_url": "https://www.chemistry.msu.edu/faculty-research/faculty-members/index.aspx",
            "scrape": {
                "url": "https://www.chemistry.msu.edu/faculty-research/faculty-members/index.aspx",
                # Info cell (td 2) holds four <p>: name link / rank / research
                # focus / mailto. Uniform across all 45 rows.
                "selectors": {
                    "card": "div.component-responsiveTable table tbody tr",
                    "name": "td:nth-of-type(2) p:nth-of-type(1) a",
                    "link": "td:nth-of-type(2) p:nth-of-type(1) a",
                    "title": "td:nth-of-type(2) p:nth-of-type(2)",
                    "research": "td:nth-of-type(2) p:nth-of-type(3)",
                    "email": "td:nth-of-type(2) a[href^='mailto:']",
                },
            },
        },
        # ---- College of Natural Science: Physics (condensed-matter group) ---
        {
            "short": "PHYS", "name": "Department of Physics and Astronomy",
            "majors": ["Physics", "Astrophysics"],
            "directory_url": "https://pa.msu.edu/condensed-matter-physics/people/faculty.aspx",
            "scrape": {
                "url": "https://pa.msu.edu/condensed-matter-physics/people/faculty.aspx",
                # Columns: Name "Last, First" | Title | Phone | Office | Email.
                # Header row is <th>-only (no td name) so it self-skips.
                "selectors": {
                    "card": "div.table-responsive table tr",
                    "name": "td:nth-of-type(1)",
                    "title": "td:nth-of-type(2)",
                    "email": "td:nth-of-type(5) a[href^='mailto:']",
                },
                "name_flip": True,
            },
        },
        # ---- College of Communication Arts and Sciences (college pool) ------
        _cas_pool(),
        # ---- College of Arts and Letters (college pool, sitemap) ------------
        _cal_pool(),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
