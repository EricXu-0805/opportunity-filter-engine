"""Arizona State University faculty config (via the faculty_graph engine).

ASU runs its whole people layer off ONE authoritative backend — the ASU iSearch
directory API (``https://search.asu.edu/api/v1/webdir-profiles/faculty-staff/
filtered``, no auth). Every campus directory (the WordPress "pitchfork-people"
plugin on the engineering sites, the Drupal "clas-isearch" React widget on the
CLAS sites, the "webdir-container" widget on the professional colleges) paints
its roster client-side from that API keyed on a numeric iSearch **department
node id** (``dept_ids``), so the reliable path is the JSON API, not CSS
scraping. Each department was located by resolving one of its faculty members'
``primary_deptid`` (or by reading the ``depts`` / ``depList`` / ``dept-ids`` id
embedded in its directory page) and then live-verified 2026-07-24 against the
API: roster size, the ``primary_empl_class == "Faculty"`` count, and a
majority-emailed check (every wired unit below came back 98–100% emailed).

One shared ``json_dir`` field mapping serves every API department — only the
``dept_ids`` node id changes. Record shape: each field is a ``{"raw": …}`` box,
so dotted paths (``display_name.raw``, ``primary_title.raw``,
``email_address.raw``) read the value; ``size=1000`` returns the whole roster in
one page (the largest unit, SoMSS, is 276 rows → still one page).

Faculty filter (two gates, high precision):
* ``primary_empl_class.raw == "Faculty"`` — the authoritative faculty flag that
  drops the University Staff, Graduate Assistant/Associate, Post-Doctoral
  Scholars, and Academic-Professional rows the same feed carries (e.g. the CS
  unit's 235 records → 113 faculty).
* a title ``ladder_filter`` — keep professor/instructor/lecturer ranks (incl.
  the research-track Research/Regents/President's/Teaching professors, who run
  labs), drop Emeritus / Adjunct / Visiting and the part-time "Faculty
  Associate" instructional rows.

Keywords: ``expertise_areas.raw`` is a clean controlled-vocabulary LIST when
present (~40–65% of faculty) — folded straight into keyword chips via the ``[]``
fan-out. ``research_interests.raw`` is HTML prose (not clean keywords), so it is
deliberately NOT used. Faculty without an expertise list ship
name+title+email+department (OpenAlex/LLM enrichment backfills topics later).
Link: ``website.raw`` (a per-person homepage/lab site where the profile declares
one — always an absolute http(s) URL); absent, the record falls back to its
department directory URL.

Several "departments" here are ASU *schools* that house multiple degree
programs under one iSearch unit id, and the API exposes no clean sub-filter to
split them (the human pages filter client-side by a hard-coded asurite
exclude-list we can't reconstruct). Rather than ship a mis-scoped slice, each is
modeled as its whole school with a multi-program ``majors`` list (SCAI = CS +
Software + Industrial + Computer Eng; SEMTE = Aero/Mech + Chemical + Materials;
SMS = Chemistry + Biochemistry; SoMSS = Mathematics + Statistics; SoLS = Biology
+ Microbiology + Neuroscience + Molecular Biosciences; SHPRS = History +
Philosophy + Religious Studies; and so on).

Coverage (2026-07-24): the full Ira A. Fulton Schools of Engineering (7 schools),
The College of Liberal Arts and Sciences (16 departments/schools across natural,
social, and humanities divisions), the Herberger Institute (Design, Art, Music/
Dance/Theatre), the Watts College (Social Work, Public Affairs, Criminology,
Community Resources), the College of Global Futures (Sustainability, Future of
Innovation), the College of Health Solutions, and Edson College of Nursing — all
via the iSearch API. The Walter Cronkite School of Journalism does not paint from
the client-side iSearch API (its people page is a server-rendered UDS React
grid), so it is wired as a headless ``render`` scrape of that grid (name / rank /
mailto), still gated to ladder + teaching faculty.

Dropped / phase-2 (no clean, majority-emailed source reachable 2026-07-24):
* **W. P. Carey School of Business** — the ``/people/faculty`` UDS grid renders
  cards with an EMPTY rank ``<h4>`` (rank lives only in prose) and paginates 20
  at a time; nothing to gate ladder rank on. Needs a per-department iSearch node
  (the college exposes none) or a paginated-render pass — phase-2.
* **Mary Lou Fulton Teachers College** — the ``/directory`` page renders zero
  person cards (roster injected elsewhere); no iSearch node surfaced.
* **Herberger — Sidney Poitier New American Film School & School of Arts, Media
  and Engineering** — both hosts sit behind Cloudflare (HTTP 522 to proxy +
  headless); node not resolvable.
* **Global Futures — School of Complex Adaptive Systems & School of Ocean
  Futures** — pure client-side shells, no iSearch call and no server-rendered
  roster to scrape.

Single source ("asu_faculty"); department rides each record, ids namespaced by
department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# ---- shared ASU iSearch directory API mapping ------------------------------
_ISEARCH = ("https://search.asu.edu/api/v1/webdir-profiles/faculty-staff/"
            "filtered?dept_ids={ids}&size=1000&page=1")

# Keep ladder + teaching + research-track + instructor/lecturer ranks; drop the
# retired/visiting/adjunct rows. The empl_class gate already removes staff/
# students/postdocs, so this only prunes the non-PI faculty ranks the feed still
# tags "Faculty".
_LADDER = {"require": r"professor|instructor|lecturer",
           "drop": r"emerit|adjunct|visiting"}


def _dept(short: str, name: str, majors: list[str], dept_ids: str,
          directory_url: str) -> dict:
    """One ASU unit fetched from the shared iSearch API (``dept_ids`` — the
    numeric iSearch node — is the only per-department variable)."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": directory_url,
        "json_dir": {
            "url": _ISEARCH.format(ids=dept_ids),
            "records_key": "results",
            "name_fields": ["display_name.raw"],
            "title_field": "primary_title.raw",
            "email_field": "email_address.raw",
            "link_field": "website.raw",
            "status_field": "primary_empl_class.raw",
            "status_value": "Faculty",
            "research_field": ["expertise_areas.raw[]"],
            "ladder_filter": _LADDER,
        },
    }


# ---- Cronkite: server-rendered UDS person-profile grid (headless render) ----
# ``cronkite.asu.edu/people/faculty`` is NOT painted from the client-side iSearch
# API — it is a server-fed Unity Design System React grid of
# ``div.uds-person-profile`` cards. ``render: True`` runs the JS; each card
# carries the name (``.person-name`` anchor → search.asu.edu/profile/<id>), the
# rank (``.person-profession h4``), and a plain ``mailto:`` email. The ladder
# gate drops the staff / adjunct / emeriti the grid mixes in.
_CRONKITE_URL = "https://cronkite.asu.edu/people/faculty"
_CRONKITE_SEL = {
    "card": "div.uds-person-profile",
    "name": "a.person-name",
    "link": "a.person-name",
    "title": ".person-profession h4",
    "email": "ul.person-contact-info a[href^='mailto:']",
}


SCHOOL: dict = {
    "school_slug": "asu",
    "source": "asu_faculty",
    "organization": "Arizona State University",
    "location": "Tempe, AZ",
    "id_prefix": "asu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Arizona State University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Ira A. Fulton Schools of Engineering --------------------------
        _dept("CS", "School of Computing and Augmented Intelligence",
              ["Computer Science", "Software Engineering",
               "Industrial Engineering", "Computer Engineering", "Informatics"],
              "1661",
              "https://faculty.engineering.asu.edu/directory/scai/computer-science-and-engineering/"),
        _dept("ECE", "School of Electrical, Computer and Energy Engineering",
              ["Electrical Engineering", "Computer Engineering",
               "Electrical Systems Engineering"],
              "1663",
              "https://faculty.engineering.asu.edu/directory/ecee/"),
        _dept("SEMTE", "School for Engineering of Matter, Transport and Energy",
              ["Mechanical Engineering", "Aerospace Engineering",
               "Chemical Engineering", "Materials Science and Engineering"],
              "1662",
              "https://faculty.engineering.asu.edu/directory/semte/aerospace-and-mechanical-engineering/"),
        _dept("BME", "School of Biological and Health Systems Engineering",
              ["Biomedical Engineering"],
              "1659",
              "https://faculty.engineering.asu.edu/directory/sbhse/"),
        _dept("SSEBE",
              "School of Sustainable Engineering and the Built Environment",
              ["Civil Engineering", "Environmental Engineering",
               "Construction Engineering", "Construction Management",
               "Sustainable Engineering"],
              "1660",
              "https://ssebe.engineering.asu.edu/"),
        _dept("MSN", "School of Manufacturing Systems and Networks",
              ["Manufacturing Engineering"],
              "N1659649552",
              "https://faculty.engineering.asu.edu/directory/msn/"),
        _dept("TPS", "The Polytechnic School",
              ["Robotics", "Engineering Management",
               "Human Systems Engineering"],
              "35490",
              "https://faculty.engineering.asu.edu/directory/tps/"),
        # ---- The College of Liberal Arts and Sciences: natural sciences ----
        _dept("PHYS", "Department of Physics", ["Physics", "Astrophysics"],
              "1735",
              "https://physics.asu.edu/directory/faculty"),
        _dept("CHEM", "School of Molecular Sciences",
              ["Chemistry", "Biochemistry"],
              "1734",
              "https://sms.asu.edu/People/Faculty"),
        _dept("MATH", "School of Mathematical and Statistical Sciences",
              ["Mathematics", "Statistics", "Applied Mathematics",
               "Actuarial Science", "Data Science"],
              "2243",
              "https://math.asu.edu/faculty/all"),
        _dept("SESE", "School of Earth and Space Exploration",
              ["Geology", "Astrophysics", "Environmental Science",
               "Earth Science"],
              "1726",
              "https://sese.asu.edu/people/faculty"),
        _dept("SOLS", "School of Life Sciences",
              ["Biological Sciences", "Microbiology", "Neuroscience",
               "Molecular Biosciences and Biotechnology"],
              "1755",
              "https://sols.asu.edu/people/faculty"),
        _dept("PSY", "Department of Psychology",
              ["Psychology", "Neuroscience"],
              "1743",
              "https://psychology.asu.edu/faculty"),
        # ---- The College: social sciences ----------------------------------
        _dept("SHESC", "School of Human Evolution and Social Change",
              ["Anthropology", "Global Health"],
              "1739",
              "https://shesc.asu.edu/people/faculty"),
        _dept("SPGS", "School of Politics and Global Studies",
              ["Political Science", "Global Studies"],
              "1742",
              "https://spgs.asu.edu/people/faculty"),
        _dept("SGSUP",
              "School of Geographical Sciences and Urban Planning",
              ["Geography", "Urban and Regional Planning"],
              "1730",
              "https://sgsup.asu.edu/about/people/faculty"),
        _dept("SSFD",
              "T. Denny Sanford School of Social and Family Dynamics",
              ["Sociology", "Family and Human Development"],
              "1747",
              "https://thesanfordschool.asu.edu/"),
        _dept("HDSHC", "Hugh Downs School of Human Communication",
              ["Communication", "Communication Studies"],
              "1758",
              "https://humancommunication.asu.edu/"),
        _dept("SST", "School of Social Transformation",
              ["Justice Studies", "Women and Gender Studies",
               "African and African American Studies"],
              "1773",
              "https://sst.asu.edu/"),
        _dept("STS", "School of Transborder Studies",
              ["Transborder Studies"],
              "1750",
              "https://sts.asu.edu/"),
        # ---- The College: humanities ---------------------------------------
        _dept("SHPRS",
              "School of Historical, Philosophical and Religious Studies",
              ["History", "Philosophy", "Religious Studies"],
              "1740",
              "https://shprs.asu.edu/people"),
        _dept("ENGL", "Department of English", ["English"],
              "1728",
              "https://english.asu.edu/"),
        _dept("SILC", "School of International Letters and Cultures",
              ["Languages", "Linguistics", "Cultural Studies"],
              "1729",
              "https://silc.asu.edu/"),
        # ---- Herberger Institute for Design and the Arts -------------------
        _dept("DESIGN", "The Design School",
              ["Architecture", "Industrial Design", "Graphic Design",
               "Interior Design", "Landscape Architecture"],
              "1626",
              "https://design.asu.edu/"),
        _dept("ART", "School of Art", ["Art"],
              "1622",
              "https://art.asu.edu/"),
        _dept("SOMDT", "School of Music, Dance and Theatre",
              ["Music", "Dance", "Theatre"],
              "392823",
              "https://musicdancetheatre.asu.edu/"),
        # ---- Watts College of Public Service and Community Solutions -------
        _dept("SSW", "School of Social Work", ["Social Work"],
              "2126",
              "https://socialwork.asu.edu/people/faculty-rank"),
        _dept("SPA", "School of Public Affairs",
              ["Public Policy", "Public Administration",
               "Emergency Management and Homeland Security"],
              "2125",
              "https://spa.asu.edu/content/school-directory"),
        _dept("SCCJ", "School of Criminology and Criminal Justice",
              ["Criminology and Criminal Justice"],
              "2128",
              "https://ccj.asu.edu/people/faculty-rank"),
        _dept("SCRD", "School of Community Resources and Development",
              ["Nonprofit Leadership and Management", "Tourism Development",
               "Community Resources"],
              "2124",
              "https://scrd.asu.edu/content/school-directory"),
        # ---- College of Global Futures -------------------------------------
        _dept("SOS", "School of Sustainability",
              ["Sustainability", "Sustainable Food Systems",
               "Environmental and Resource Management"],
              "1413",
              "https://schoolofsustainability.asu.edu/people/faculty"),
        _dept("SFIS", "School for the Future of Innovation in Society",
              ["Innovation in Society", "Science and Technology Policy"],
              "35574",
              "https://sfis.asu.edu/people/faculty"),
        # ---- College of Health Solutions -----------------------------------
        _dept("CHS", "College of Health Solutions",
              ["Health Sciences", "Nutrition", "Kinesiology", "Public Health",
               "Speech and Hearing Sciences"],
              "1534",
              "https://chs.asu.edu/about/faculty"),
        # ---- Edson College of Nursing and Health Innovation ----------------
        _dept("NURS", "Edson College of Nursing and Health Innovation",
              ["Nursing", "Integrative Health"],
              "96401",
              "https://nursing.asu.edu/about/directory"),
        # ---- Walter Cronkite School of Journalism (render scrape) ----------
        {
            "short": "CRONKITE",
            "name": "Walter Cronkite School of Journalism and Mass Communication",
            "majors": ["Journalism", "Sports Journalism", "Media Studies",
                       "Mass Communication"],
            "directory_url": _CRONKITE_URL,
            "scrape": {
                "url": _CRONKITE_URL,
                "selectors": _CRONKITE_SEL,
                "ladder_filter": _LADDER,
                "render": True,
                "render_settle": 4500,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
