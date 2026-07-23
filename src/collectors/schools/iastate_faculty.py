"""Iowa State University faculty config (via the faculty_graph engine).

University-wide coverage across the colleges whose department directories
server-render their roster over plain HTTP (the engine already sends a browser
User-Agent, so Iowa State's F5 BIG-IP ASM front does not gate it). Three markup
families, all clean static 200s, live-verified 2026-07-23:

* **Drupal "isu-people-directory" — /people/faculty.** One
  ``article.node--type-people.isu-horizontal-card`` per person: the name is a
  profile-linked ``h3.people-teaser-name a`` (absolute <dept>.iastate.edu URL),
  the rank is the first ``<li>`` of ``ul.isu-people_position-list`` (later
  ``<li>``s are committee/leadership roles), and a plain ``mailto`` sits in
  ``.isu-people_email``. Covers Computer Science, Physics & Astronomy,
  Statistics, Economics, Genetics/Development/Cell Biology, Biochemistry, Animal
  Science, Natural Resource Ecology & Management, Agricultural Education &
  Studies, Plant Pathology/Entomology/Microbiology, and Integrated Health
  Sciences.

* **WordPress iastate22 "faculty-staff-card" (``__content-name``) — paginated.**
  Mathematics lists its WHOLE department at ``math.iastate.edu/profiles/``; the
  LAS social-science / humanities departments expose the same card under
  ``<dept>.iastate.edu/profiles/?post_type=profiles&department=faculty`` (the
  ``department=faculty`` filter is loose — grad students, advisers and staff ride
  alongside real faculty, so the title gate is load-bearing). Name in
  ``h3.faculty-staff-card__content-name`` (the profile link is a separate
  ``a.iastate22-link-secondary``), rank in
  ``div.faculty-staff-feed-item__content-body``, mailto in
  ``.faculty-staff-card__content-contact``. Path pagination ``/profiles/page/N/``
  (page 1 = base), ~20 cards/page. Covers Psychology, Political Science, English
  and Earth/Atmosphere/Climate (Environmental Science).

* **College of Design "faculty-staff-card" (``__content-title``).** One WordPress
  install (``design.iastate.edu/profiles/``) hosts all seven design departments;
  ``?department=<Name>`` server-renders that department's whole roster on a single
  page (no pagination). A different card body than the LAS variant: name in
  ``p.faculty-staff-card__content-title a``, rank in
  ``p.faculty-staff-card__content-body`` (multi-line — chair/director lead,
  "Professor" lands lower), mailto in ``ul.faculty-staff-card__content-contact``.
  Covers Architecture, Graphic Design, Industrial Design, Interior Design,
  Landscape Architecture and Urban Planning & Development (Community & Regional
  Planning).

Title gate: a ``field_filter`` (not ``ladder_filter``) reading the WHOLE rank
element and requiring ``professor|lecturer`` — because a department chair's card
leads with "Department Chair" and carries "Professor" only on a later line, which
a first-line ladder read would wrongly drop. ``require_present`` also drops the
handful of blank/absent rank fields (staff/grad) before the engine's "Professor"
default could wave them through; emeriti/retired drop by the engine's own
retired-title guard.

Recovered from the JS-rendered tier via their backing WordPress-REST feeds
(deep mode ``api`` blocks, coexisting additively with the static scrape family):

* **CALS Agronomy — ``people`` CPT.** ``agron.iastate.edu`` renders its roster
  through JetEngine (a static scrape lands zero cards), but the ``people`` custom
  post type is open at ``/wp-json/wp/v2/people``. The ``people-category`` taxonomy
  is the gate — term 227 (faculty), excluding 250 (emeritus); ``area-of-expertise``
  supplies clean keyword chips (``interests`` is numeric-id junk, not wired). No
  rank/email in the feed (records default "Professor"); the personal address is a
  plaintext jet-listing field on the profile (``strong:Email:`` sibling text, not a
  mailto — the shared ``agron@`` inbox is the only mailto, dropped) recovered by
  the profile-enrich pass. Names carry a "Dr." honorific → ``name_strip``.

Still not covered (needs a headless render pass, a new engine adapter, or — for
the email-less HHS feed — a real email source; all phase 2):
* **College of Health & Human Sciences (+ CALS Food Science)** — the shared
  ``fhsd_staff`` feed on ``hs.iastate.edu`` is category-gateable to faculty but
  carries no email (it lives in array-wrapped ``meta_fields`` the engine can't
  read, painted client-side) and the host now Cloudflare-403s the wp-json route.
  Dropped rather than ship ~54 email-less name-only records.
* **College of Engineering** — the college directory is a FacetWP client app
  (``facetwp-facet-faculty_a_z``) painting a Twig template off ``admin-ajax.php``;
  the eight department subdomains register NO faculty/person/profile CPT over
  wp-json, so there is no REST route to hit config-only. Needs headless.
* **Ivy College of Business** — its ``cob-directory/v1/profile`` route IS a clean
  faculty feed (``phd_fac`` flag, ``title`` rank, ``exp0..10`` research), but it's
  a bespoke namespace, not ``wp/v2/<post_type>``, so it needs a new engine fetch
  adapter (out of scope for a config-only pass).
* **Chemistry, Ecology-Evolution-Organismal-Biology** — the F5 front resets the
  TLS handshake on every proxied fetch (host unreachable); AJAX-Drupal directories
  with zero static rows. Needs headless from an allowed egress.
* **Horticulture, Global Resource Systems** — no reachable ``people`` CPT
  (Horticulture registers only news/video types; GRS host TLS-resets). Needs
  headless.

Single source ("iastate_faculty"); department rides each record, ids namespaced
by department short-code.
"""

from __future__ import annotations

from urllib.parse import quote

from .. import faculty_graph

# ---- Drupal "isu-people-directory" (/people/faculty) ---------------------------
# The name anchor already carries the absolute profile URL, so link == name. The
# title selector lands the FIRST position <li> (the rank) for the record's
# display title; the gate below reads the whole list so a chair whose rank sits
# on a later line is still kept.
_ISU_SEL = {
    "card": "article.node--type-people.isu-horizontal-card",
    "name": "h3.people-teaser-name a",
    "link": "h3.people-teaser-name a",
    "title": "ul.isu-people_position-list li",
    "email": ".isu-people_email a",
}
# Gate on the ENTIRE position list (not just the first <li>): a department chair
# card leads with "Department Chair" and only names "Professor" further down, so a
# first-line read would drop a real full professor. require_present drops the
# rare rank-less card before the engine's default title kicks in.
_ISU_FIELD = {
    "selector": "ul.isu-people_position-list",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _isu(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared Drupal isu-people-directory component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ISU_SEL, "field_filter": _ISU_FIELD},
    }


# ---- WordPress iastate22 "faculty-staff-card" (__content-name), paginated -------
_PROFILE_SEL = {
    "card": "div.faculty-staff-card",
    "name": "h3.faculty-staff-card__content-name",
    "link": "a.iastate22-link-secondary",
    "title": "div.faculty-staff-feed-item__content-body",
    "email": ".faculty-staff-card__content-contact a[href^='mailto:']",
}
_PROFILE_FIELD = {
    "selector": "div.faculty-staff-feed-item__content-body",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _profiles(short: str, name: str, majors: list[str], url: str) -> dict:
    """A WordPress "profiles" roster; path pagination /profiles/page/N/."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url, "selectors": _PROFILE_SEL, "field_filter": _PROFILE_FIELD,
            "paginate": {"mode": "path", "param": "page", "start": 2, "max": 20},
        },
    }


def _las(short: str, name: str, majors: list[str], host: str) -> dict:
    """An LAS department on the /profiles/?department=faculty view."""
    url = f"https://{host}.iastate.edu/profiles/?post_type=profiles&department=faculty"
    return _profiles(short, name, majors, url)


# ---- College of Design "faculty-staff-card" (__content-title) ------------------
# One WordPress install serves all seven departments; ?department=<Name> renders
# that department's whole roster on a single page. Name + rank live on <p> tags
# (not the <h3>/feed-item body the LAS variant uses), so this needs its own family.
_DESIGN_SEL = {
    "card": "div.faculty-staff-card",
    "name": "p.faculty-staff-card__content-title a",
    "link": "p.faculty-staff-card__content-title a",
    "title": "p.faculty-staff-card__content-body",
    "email": "ul.faculty-staff-card__content-contact a[href^='mailto:']",
}
_DESIGN_FIELD = {
    "selector": "p.faculty-staff-card__content-body",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _design(short: str, name: str, majors: list[str], department: str) -> dict:
    """A College of Design department, filtered by its ?department= term."""
    url = ("https://www.design.iastate.edu/profiles/?post_type=profiles"
           f"&department={quote(department)}")
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _DESIGN_SEL, "field_filter": _DESIGN_FIELD},
    }


# ---- CALS Agronomy: JetEngine "people" CPT over wp-json --------------------
# The roster is JS-painted, but the ``people`` post type is open. Gate on the
# people-category taxonomy (227 = faculty; 250 = emeritus dropped); pull keyword
# chips from area-of-expertise. The personal email is a plaintext jet-listing
# field on the profile (the only mailto is the shared agron@ inbox — dropped).
_AGRON_ENRICH = {
    "email_selector": "div.jet-listing-dynamic-field__content:-soup-contains('Email')",
    "email_drop": r"^[^@]*$|^agron@|webmaster@|-info@",
    "throttle": 0.2,
}


SCHOOL: dict = {
    "school_slug": "iastate",
    "source": "iastate_faculty",
    "organization": "Iowa State University",
    "location": "Ames, IA",
    "id_prefix": "iastate",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Iowa State University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # --- College of Liberal Arts and Sciences ---
        _isu("CS", "Department of Computer Science",
             ["Computer Science", "Software Engineering", "Data Science"],
             "https://www.cs.iastate.edu/people/faculty"),
        _isu("PHYS", "Department of Physics and Astronomy",
             ["Physics", "Astronomy"],
             "https://www.physastro.iastate.edu/people/faculty"),
        _profiles("MATH", "Department of Mathematics",
                  ["Mathematics"],
                  "https://math.iastate.edu/profiles/"),
        _isu("STAT", "Department of Statistics",
             ["Statistics", "Data Science"],
             "https://www.stat.iastate.edu/people/faculty"),
        _isu("ECON", "Department of Economics",
             ["Economics", "Agricultural Business"],
             "https://www.econ.iastate.edu/people/faculty"),
        _isu("GDCB", "Department of Genetics, Development and Cell Biology",
             ["Genetics", "Biology"],
             "https://www.gdcb.iastate.edu/people/faculty"),
        _isu("BBMB", "Department of Biochemistry, Biophysics and Molecular Biology",
             ["Biochemistry"],
             "https://www.bb.iastate.edu/people/faculty"),
        _las("PSYCH", "Department of Psychology", ["Psychology"], "psychology"),
        _las("POLS", "Department of Political Science", ["Political Science"], "pols"),
        _las("ENGL", "Department of English", ["English"], "engl"),
        _las("EAC", "Department of the Earth, Atmosphere, and Climate",
             ["Environmental Science"], "earth-atmosphere-climate"),
        # --- College of Agriculture and Life Sciences ---
        _isu("ANS", "Department of Animal Science",
             ["Animal Science"],
             "https://www.ans.iastate.edu/people/faculty"),
        _isu("NREM", "Department of Natural Resource Ecology and Management",
             ["Forestry", "Environmental Science"],
             "https://www.nrem.iastate.edu/people/faculty"),
        _isu("AGEDS", "Department of Agricultural Education and Studies",
             ["Agricultural and Life Sciences Education"],
             "https://www.ageds.iastate.edu/people/faculty"),
        _isu("PPEM", "Department of Plant Pathology, Entomology and Microbiology",
             ["Biology"],
             "https://www.plantpath.iastate.edu/people/faculty"),
        # Agronomy is JetEngine-rendered — recovered via its open ``people`` CPT.
        {
            "short": "AGRON", "name": "Department of Agronomy",
            "majors": ["Agronomy", "Crop Science", "Soil Science"],
            "directory_url": "https://www.agron.iastate.edu/people/",
            "api": {
                "type": "wp", "base": "https://www.agron.iastate.edu",
                "post_type": "people",
                "category_include": {"people-category": [227]},
                "category_exclude": {"people-category": [250]},
                "keyword_tax": ["area-of-expertise"],
                "name_strip": r"^(?:Dr|Prof)\.\s+",
                "name_flip": True,
            },
            "profile_enrich": _AGRON_ENRICH,
        },
        # --- Health sciences (LAS-hosted, health majors) ---
        _isu("IHS", "Department of Integrated Health Sciences",
             ["Kinesiology and Health", "Nutritional Science"],
             "https://integratedhealthsciences.iastate.edu/people/faculty"),
        # --- College of Design ---
        _design("ARCH", "Department of Architecture",
                ["Architecture"], "Architecture"),
        _design("GRDES", "Department of Graphic Design",
                ["Graphic Design"], "Graphic Design"),
        _design("INDD", "Department of Industrial Design",
                ["Industrial Design"], "Industrial Design"),
        _design("INTD", "Department of Interior Design",
                ["Interior Design"], "Interior Design"),
        _design("LARCH", "Department of Landscape Architecture",
                ["Landscape Architecture"], "Landscape Architecture"),
        _design("UPD", "Department of Urban Planning and Development",
                ["Community and Regional Planning"], "Urban Planning and Development"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
