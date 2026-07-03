"""UC San Diego faculty config (via the faculty_graph engine).

Thirteen departments land in the first pass, in three markup families
(selectors verified against live directory HTML, Jul 2026):

- **Jacobs School / campus Drupal grids** (server-rendered Views): CSE (the
  ``block_1`` Faculty + ``block_9`` Leadership views — the same page's
  Affiliated/Emeritus/Alumni views are skipped by scoping the card selector),
  ECE (emails on the listing), MAE, Bioengineering (ladder filter drops the
  grid's adjunct/affiliated rows), Structural Engineering, and the
  NanoEngineering + Chemical Engineering roster tables (emails on the listing;
  rank section-headers ride the table so titles default to "Professor").
- **Blink "profile-listing-card" template** (shared campus CMS): Cognitive
  Science and Psychology (both with listing emails), Sociology (its active
  Faculty section lists no emails — only the filtered-out emeritus/lecturer
  sections do), Political Science (currently-active subpage), and Economics —
  Econ/Soc list Emeritus/Adjunct/Lecturer sections on the same page, gated out
  via ``section_filter`` on the nearest ``h2``; Econ's "Research Interests:"
  line lands as keywords via ``research_re``.
- **Odd one out**: HDSI's WordPress grid (``vc_grid-term-faculty`` cards,
  ladder-filtered).

Physics rides its public JSON profile API via the engine's ``json_dir`` block
(names/titles/emails in the feed). Deferred departments: Math's
``/export/people/faculty`` feed has no name field and 331/335 records carry an
empty title (no safe ladder gate); Biology's API keeps the rank in a nested
``titleInfo.standardTitle`` the flat ``json_dir`` mapper can't reach; and
Chemistry & Biochemistry's server presents a mismatched TLS intermediate
(an ECC leaf with the RSA intermediate), so strict-verify clients — requests,
curl — can't connect at all (browsers survive via AIA chasing).

Single source ("ucsd_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Ladder faculty only: "professor" matches Assistant/Associate/Distinguished/
# Teaching Professor ranks; drop emeriti, adjuncts, and visitors outright.
_LADDER = {"require": r"\bprofessor\b", "drop": r"\bemerit|\badjunct|\bvisiting"}

# Blink "profile-listing-card" grid shared by the social-science departments.
_BLINK = {
    "card": "li.profile-listing-card",
    "name": "p.h3 > a",
    "link": "p.h3 > a",
    "title": "h4",
    "email": ".profile-listing-data a[href^='mailto:']",
}


def _dept(short: str, name: str, majors: list[str], url: str, scrape: dict) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": {"url": url, **scrape}}


SCHOOL: dict = {
    "school_slug": "ucsd",
    "source": "ucsd_faculty",
    "organization": "University of California, San Diego",
    "location": "La Jolla, CA",
    "id_prefix": "ucsd",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UC San Diego) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Jacobs School of Engineering + campus Drupal grids ------------
        _dept(
            "CSE", "Department of Computer Science & Engineering",
            ["Computer Science", "Computer Engineering", "Data Science"],
            "https://cse.ucsd.edu/people/faculty-profiles",
            {
                # Faculty (block_1) + Department Leadership (block_9) views only;
                # the page's Lecturer/Adjunct/Affiliated/Emeritus/Alumni views
                # are separate blocks and stay out of the card selector.
                "selectors": {
                    "card": (".view-display-id-block_1 .views-field-nothing .field-content, "
                             ".view-display-id-block_9 .views-field-nothing .field-content"),
                    "name": "a[href^='/people/faculty-profiles/'] p strong",
                    "link": "a[href^='/people/faculty-profiles/']",
                },
            },
        ),
        _dept(
            "ECE", "Department of Electrical & Computer Engineering",
            ["Electrical Engineering", "Computer Engineering", "Engineering Physics"],
            "https://ece.ucsd.edu/people/faculty",
            {
                "selectors": {
                    "card": "div.faculty-member",
                    "name": "h2 > a",
                    "link": "h2 > a",
                    # The rank shares one <p> with the email + lab links; cut at
                    # the first email address or "Lab Web" marker.
                    "title": "p",
                    "title_strip_after": r"\s+\S+@|\s+Lab\s+Web\b",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "MAE", "Department of Mechanical & Aerospace Engineering",
            ["Mechanical Engineering", "Aerospace Engineering"],
            "https://mae.ucsd.edu/people/faculty-profiles",
            {
                "selectors": {
                    "card": "div.profile-window",
                    "name": ".profile-info h4 > a",
                    "link": ".profile-info h4 > a",
                    "title": ".profile-info h5",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "BE", "Department of Bioengineering",
            ["Bioengineering", "Bioengineering: Biotechnology",
             "Bioengineering: Bioinformatics", "Bioengineering: BioSystems"],
            "https://be.ucsd.edu/faculty",
            {
                "selectors": {
                    "card": "div.faculty-profile",
                    "name": ".faculty-information h3 > a",
                    "link": ".faculty-information h3 > a",
                    # Malformed <h6>Rank<h6 /> swallows the lab link that follows;
                    # cut the title at the lab/group name.
                    "title": ".faculty-information h6",
                    "title_strip_after": r"\s+(?:\S+\s+)?(?:Research|Lab\b|Laboratory|Group)\b.*",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "NANO", "Department of NanoEngineering",
            ["NanoEngineering"],
            "https://nanoengineering.ucsd.edu/fac/nanoe-faculty",
            {
                # Roster table: rank lives in tr.table-active section headers
                # (those rows carry no <a>, so they're skipped automatically);
                # the name cell links to the professor's lab site.
                "selectors": {
                    "card": "table tbody tr",
                    "name": "td:nth-of-type(1) a",
                    "link": "td:nth-of-type(1) a",
                    "email": "td a[href^='mailto:']",
                },
                "name_flip": True,
            },
        ),
        _dept(
            "CHE", "Chemical Engineering Program",
            ["Chemical Engineering"],
            "https://nanoengineering.ucsd.edu/chemical-engineering-faculty",
            {
                # Same roster-table markup as the NanoE page that hosts it.
                "selectors": {
                    "card": "table tbody tr",
                    "name": "td:nth-of-type(1) a",
                    "link": "td:nth-of-type(1) a",
                    "email": "td a[href^='mailto:']",
                },
                "name_flip": True,
            },
        ),
        _dept(
            "SE", "Department of Structural Engineering",
            ["Structural Engineering", "Civil Engineering"],
            "https://se.ucsd.edu/people/faculty",
            {
                "selectors": {
                    "card": "div[id^='views-bootstrap-faculty-page'] .row > div[class*='col-']",
                    "name": ".views-field-field-last-name .field-content",
                    "link": ".views-field-field-web-page a",
                    "title": ".views-field-field-staff-title em",
                },
                "name_flip": True,
                "ladder_filter": _LADDER,
            },
        ),
        # ---- School of Physical Sciences -----------------------------------
        # (Chemistry & Biochemistry deferred: the server's TLS chain ships the
        # wrong intermediate — see module docstring.)
        {
            "short": "PHYS", "name": "Department of Physics",
            "majors": ["Physics", "General Physics", "Astronomy & Astrophysics"],
            "directory_url": "https://physics.ucsd.edu/people/faculty",
            # The listing page is a JS spinner over this public JSON API.
            "json_dir": {
                "url": "https://physics.ucsd.edu/api/profiles/faculty",
                "name_fields": ["first_name", "last_name"],
                "title_field": "display_title",
                "email_field": "email",
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\badjunct|\bvisiting"},
            },
        },
        # ---- School of Social Sciences --------------------------------------
        _dept(
            "COGSCI", "Department of Cognitive Science",
            ["Cognitive Science", "Cognitive and Behavioral Neuroscience"],
            "https://cogsci.ucsd.edu/people/faculty/",
            {"selectors": dict(_BLINK), "ladder_filter": _LADDER},
        ),
        _dept(
            "PSYCH", "Department of Psychology",
            ["Psychology", "Business Psychology"],
            # Only the flat .html path serves the directory (/people/faculty/ 403s).
            "https://psychology.ucsd.edu/people/faculty.html",
            {"selectors": dict(_BLINK), "ladder_filter": _LADDER},
        ),
        _dept(
            "ECON", "Department of Economics",
            ["Economics", "Business Economics", "Joint Major Mathematics & Economics"],
            "https://economics.ucsd.edu/faculty-and-research/faculty-profiles/index.html",
            {
                # One page, h2-grouped roles (Faculty / Emeritus / Adjunct /
                # Affiliated / Lecturers / Visiting) — keep the Faculty section.
                # No title element (loose text), so rank defaults to Professor;
                # the "Research Interests:" line becomes keywords.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "h3 > a",
                    "link": "h3 > a",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "research_re": r"Research Interests:\s*(.{4,300}?)(?:<|$)",
                },
                "section_filter": {"include": r"^Faculty$", "heading": "h2"},
            },
        ),
        _dept(
            "POLI", "Department of Political Science",
            ["Political Science - General Political Science", "Political Science - International Relations"],
            "https://polisci.ucsd.edu/people/faculty/faculty-directory/currently-active-faculty/index.html",
            {"selectors": dict(_BLINK), "ladder_filter": _LADDER},
        ),
        _dept(
            "SOC", "Department of Sociology",
            ["Sociology"],
            "https://sociology.ucsd.edu/people/faculty/index.html",
            {
                # Same h2-grouped single page as Econ (Faculty / Emeritus /
                # Adjunct / Affiliated / Lecturers / Visiting Scholars); the
                # name rides a bare h3 and the rank is loose text.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "h3 > a",
                    "link": "h3 > a",
                    "email": ".profile-listing-data a[href^='mailto:']",
                },
                "section_filter": {"include": r"^Faculty$", "heading": "h2"},
            },
        ),
        # ---- Halıcıoğlu Data Science Institute ------------------------------
        _dept(
            "HDSI", "Halıcıoğlu Data Science Institute",
            ["Data Science"],
            "https://datascience.ucsd.edu/faculty/",
            {
                # WordPress/WPBakery grid; scope to the "faculty" term cards and
                # ladder-filter out the grid's lecturers/directors/fellows.
                "selectors": {
                    "card": "div.vc_grid-item.vc_grid-term-faculty",
                    "name": ".vc_gitem-post-data-source-post_title h4 > a",
                    "link": ".vc_gitem-post-data-source-post_title h4 > a",
                    "title": ".field.pendari_people_title",
                },
                "ladder_filter": _LADDER,
            },
        ),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
