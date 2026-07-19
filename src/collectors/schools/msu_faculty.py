"""Michigan State University faculty config (via the faculty_graph engine).

All three markup families are plain server-rendered HTML (no render mode, no WAF;
every recon fetch a clean static 200). Live-verified 2026-07-19:

* **College of Engineering — one shared directory.**
  ``engineering.msu.edu/directory/faculty`` server-renders every engineering
  faculty member (474 ``li.directory-profile-item`` cards, all employment-type
  "Faculty") with the primary department as a plain-text field per card
  (``.primary-dept-info``). The individual dept subdomains (cse/ece/me/…msu.edu)
  302-redirect here, and the ``?departments=<uuid>`` query filters CLIENT-side
  only (a static fetch of it still returns every department) — so each department
  is that ONE directory sliced by a ``field_filter`` on ``.primary-dept-info``
  (``require_present`` so a field-less card can't fall through into every dept).
  Name + rank sit on the card; the email is plain TEXT in ``address p.fw-bold``
  (not a mailto — ``_clean_email`` extracts the address). No research interests
  on the card (profile-only), so topic keywords come from downstream OpenAlex
  enrichment, not here. The directory mixes ladder faculty with postdocs,
  adjuncts, teaching/outreach specialists, scholars, and aides — the ladder
  filter keeps professor/endowed-chair ranks and drops the rest. The four recon
  departments (CS/ECE/ME/BME) plus four more degree-granting engineering
  departments verified live in the same directory (CEE/CMSE/ChEMS/BAE) are all
  wired here; the Dean's Office, IQHSE institute, Applied Engineering Sciences,
  and Technology Engineering buckets are deliberately not exposed (admin /
  interdisciplinary institute / small program units, not research departments).

* **Chemistry — dedicated faculty table.**
  ``chemistry.msu.edu/faculty-research/faculty-members/`` is an old-CMS ASP.NET
  page: one ``div.component-responsiveTable`` table, 45 rows, each row's info
  cell holding four ``<p>`` blocks (name link, rank, a short research-focus
  blurb, mailto email). Uniform across all 45 rows, so positional ``p:nth-of-type``
  selectors are safe. It is the dedicated faculty page (no staff/students), and
  the lone emeritus is dropped by the engine's retired-title gate — no ladder
  filter needed. The research-focus blurb lands as keywords.

* **Physics & Astronomy — condensed-matter research group (PARTIAL).**
  The department-wide directory (pa.msu.edu/directory + directory.natsci.msu.edu)
  is JS-rendered (no names in static HTML). The server-rendered path is a
  per-research-group table at ``pa.msu.edu/<group>/people/faculty.aspx``; only
  the condensed-matter table is verified live (22 rows: Name "Last, First" |
  Title | Phone | Office | mailto Email — name_flip un-inverts, emeriti dropped
  by the retired-title gate). The sibling group pages the recon HYPOTHESIZED
  (astro / high-energy / nuclear-FRIB / biophysics) all 404 on this host, so
  Physics ships the verified condensed-matter roster only — the rest of the
  department is deferred to a headless render of the JS directory.

Single source ("msu_faculty"); department rides each record, ids namespaced by
department short-code.
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
# (require=professor|chair already excludes the specialist/scholar/aide/postdoc
# ranks that carry neither word; drop= removes the adjunct/emeritus/visiting
# titles that DO contain "professor".)
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
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
