"""UC Irvine faculty config (via the faculty_graph engine).

Second UC-system rollout school after UCSD. Directory markup by family
(selectors verified against live HTML, Jul 2026):

- **Samueli School of Engineering** (Drupal 7 "Mothership"): one shared selector
  set across all six departments — EECS, Mechanical & Aerospace, Biomedical,
  Chemical & Biomolecular, Civil & Environmental, and Materials — each on its own
  ``/dept/<short>/faculty-staff/faculty`` page (emeritus/affiliated/staff live on
  separate sibling URLs, so the ladder page is already role-scoped). Emails and a
  "Research Interests:" line are on the listing card.
- **Physical Sciences** (Drupal Views, but a different field schema per dept):
  Chemistry and Mathematics are ``tr``-row tables gated to the "Faculty" position
  section; Physics & Astronomy and Earth System Science are ``div.views-row``
  grids. Physics carries no rank on the listing, so its ladder gate runs on the
  profile page (``profile_enrich`` + ``ladder_recheck``).
- **Economics** (custom PHP): ``div.faculty-info`` cards on ``faculty.php`` (the
  core-ladder page; other ranks are separate PHP pages), research on the listing.
- **School of Social Sciences** (one campus-wide DataTable): a single
  server-rendered table at ``socsci.uci.edu/faculty-directory.php`` lists every
  social-science department. One ``field_filter`` on the department column slices
  each department out of the shared table (Anthropology, Cognitive Sciences,
  Political Science, Sociology, Language Science, Logic & Philosophy of Science).
- **Social Ecology** (Drupal 10 Bootstrap cards): one school directory covering
  Psychological Science, Criminology/Law & Society, and Urban Planning & Public
  Policy, sliced by the department-link ``field_filter``; rank is on the profile.
Deferred departments (each needs a mechanism the static engine doesn't have):
- **ICS** (Computer Science / Informatics / Statistics): ics/stat serve a bot
  "Access Notice" even to a headless browser; cs/informatics render their
  roster from an internal API not present in the served HTML.
- **Humanities** (History/Philosophy/English/Linguistics): the directory loads
  via a Drupal views-AJAX call the static fetch can't reach.
- **Physics & Astronomy**: its faculty listing serves content under an HTTP 404
  status (a Drupal soft-404) and carries no rank on the listing.
- **Biological Sciences** (Charlie Dunlop School): the ``biosci_people`` WordPress
  REST feed gives clean name+link for ~157 faculty, but the Divi profile pages
  render email/rank/research client-side (static HTML exposes only a shared dept
  inbox). Recovering ICS/Physics/Bio all want a per-profile headless pass — a
  follow-up once the render path is wired for this school.

Single source ("uci_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Ladder faculty only: "professor" matches Assistant/Associate/Distinguished ranks;
# drop emeriti, adjuncts, visitors, and teaching-track professors of practice.
_LADDER = {"require": r"\bprofessor\b",
           "drop": r"\bemerit|\badjunct|\bvisiting|of teaching|professor of teaching"}

# Samueli Engineering — Drupal 7 bean cards, one selector set for all six depts.
# Rank shares the body <p> with endowed-chair/center text; the "Research
# Interests:" label follows it on the same card.
_ENG = {
    "card": "div.bean-call-to-action-block",
    "name": ".field_body h4 a",
    "link": ".field_body h4 a",
    "title": ".field_body p",
    "title_strip_after": r"\s+Research Interests:|\s+\S+@",
    "email": ".field_body a[href^='mailto:']",
    "research_re": r"Research Interests:\s*(?:</strong>)?\s*([^<]{4,400})",
}


def _dept(short: str, name: str, majors: list[str], url: str, scrape: dict) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": {"url": url, **scrape}}


def _eng(short: str, name: str, majors: list[str], dept_slug: str) -> dict:
    url = f"https://engineering.uci.edu/dept/{dept_slug}/faculty-staff/faculty"
    return _dept(short, name, majors, url,
                 {"selectors": dict(_ENG), "ladder_filter": _LADDER})


# School of Social Sciences — one shared DataTable; positional <td> columns
# (name "Last, First" | title | department | room/phone | email). Each dept is
# the same table sliced by a field_filter on the department column. The dept
# cell concatenates the primary "Department of X" with the person's research
# CENTER names (some of which contain other departments' words — e.g. a center
# with "Political Science" in its title), so the filter anchors on the leading
# "Department of <name>" to key off the PRIMARY appointment only.
def _socsci(short: str, name: str, majors: list[str], dept_name: str) -> dict:
    url = "https://www.socsci.uci.edu/faculty-directory.php"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {
                "card": "table#profiles tbody tr",
                "name": "td:nth-of-type(1)",
                "title": "td:nth-of-type(2)",
                "email": "td:nth-of-type(5) a[href^='mailto:']",
            },
            "name_flip": True,
            "field_filter": {"selector": "td:nth-of-type(3)",
                             "include": rf"^\s*Department of {dept_name}"},
            "ladder_filter": _LADDER,
        },
    }


SCHOOL: dict = {
    "school_slug": "uci",
    "source": "uci_faculty",
    "organization": "University of California, Irvine",
    "location": "Irvine, CA",
    "id_prefix": "uci",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UC Irvine) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Samueli School of Engineering (shared Drupal-7 selectors) ------
        _eng("EECS", "Department of Electrical Engineering & Computer Science",
             ["Electrical Engineering", "Computer Engineering", "Computer Science & Engineering"],
             "eecs"),
        _eng("MAE", "Department of Mechanical & Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"], "mae"),
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "bme"),
        _eng("CBE", "Department of Chemical & Biomolecular Engineering",
             ["Chemical Engineering"], "cbe"),
        _eng("CEE", "Department of Civil & Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], "cee"),
        _eng("MSE", "Department of Materials Science & Engineering",
             ["Materials Science & Engineering"], "mse"),
        # ---- Physical Sciences (Drupal Views, per-dept field schema) --------
        _dept(
            "CHEM", "Department of Chemistry",
            ["Chemistry", "Chemistry (BS)", "Pharmaceutical Sciences"],
            "https://www.chem.uci.edu/people/faculty",
            {
                # tr-row table; keep the "Faculty" position section, then
                # ladder-filter the job-title column.
                "selectors": {
                    "card": "tr.odd, tr.even",
                    "name": "td.views-field-field-name-first",
                    "name_last": "td.views-field-field-name-last",
                    "title": "td.views-field-field-job-title",
                    "email": "td.views-field-field-email",
                    "link": "td.views-field-field--thumbnail a",
                },
                "field_filter": {"selector": "td.views-field-field-position",
                                 "include": r"^\s*Faculty\s*$"},
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics", "Data Science"],
            "https://www.math.uci.edu/people",
            {
                "selectors": {
                    "card": "tr.odd, tr.even",
                    "name": "td.views-field-field-name a",
                    "title": "td.views-field-field-job-title",
                    "email": "td.views-field-field-email",
                    "link": "td.views-field-field-name a",
                    "research_re": r"views-field-field-research-area[^>]*>\s*(?:<[^>]+>\s*)*([^<]{3,200})",
                },
                "field_filter": {"selector": "td.views-field-field-position",
                                 "include": r"^\s*Faculty\s*$"},
                "ladder_filter": _LADDER,
            },
        ),
        # (Physics & Astronomy deferred: its faculty listing serves content under
        # an HTTP 404 status — a Drupal soft-404 the strict fetch can't accept —
        # and carries no rank on the listing, so the ladder gate would need a
        # per-profile pass against JS-rendered profile pages. See module docstring.)
        _dept(
            "ESS", "Department of Earth System Science",
            ["Earth System Science", "Environmental Science"],
            "https://www.ess.uci.edu/faculty_profiles",
            {
                "selectors": {
                    "card": "div.views-row",
                    "name": ".views-field-field-fprofile-ldap-full-name",
                    "title": ".views-field-field-fprofile-ldap-title",
                    "email": ".views-field-field-fprofile-ldap-email",
                    "link": ".views-field-field-fprofile-ldap-url a",
                },
                "ladder_filter": _LADDER,
            },
        ),
        # ---- Economics (custom PHP) -----------------------------------------
        _dept(
            "ECON", "Department of Economics",
            ["Economics", "Business Economics", "Quantitative Economics"],
            "https://www.economics.uci.edu/people/faculty.php",
            {
                "selectors": {
                    "card": "div.faculty-info",
                    "name": ".permalink a",
                    "link": ".permalink a",
                    "title": "ul.post-meta li:first-of-type",
                    "email": "ul.post-meta a[href^='mailto:']",
                    "research": "ul.post-meta li:nth-of-type(2)",
                },
                "ladder_filter": _LADDER,
            },
        ),
        # ---- School of Social Sciences (one shared DataTable) ---------------
        _socsci("ANTHRO", "Department of Anthropology",
                ["Anthropology"], r"Anthropology"),
        _socsci("COGSCI", "Department of Cognitive Sciences",
                ["Cognitive Sciences", "Psychology"], r"Cognitive Sciences"),
        _socsci("POLISCI", "Department of Political Science",
                ["Political Science", "Public Policy"], r"Political Science"),
        _socsci("SOC", "Department of Sociology",
                ["Sociology"], r"Sociology"),
        _socsci("LANGSCI", "Department of Language Science",
                ["Language Science"], r"Language Science"),
        _socsci("LPS", "Department of Logic & Philosophy of Science",
                ["Philosophy", "Logic & Philosophy of Science"], r"Logic and Philosophy of Science"),
        # ---- School of Social Ecology (Drupal 10 cards) ---------------------
        _dept(
            "PSB", "Department of Psychological Science",
            ["Psychological Science", "Psychology"],
            "https://socialecology.uci.edu/faculty",
            {
                "selectors": {
                    "card": "div.card.h-100",
                    "name": "div.fs-4.fw-bold",
                    "email": "p a[href^='mailto:']",
                },
                "field_filter": {"selector": "p.fst-italic.text-muted a",
                                 "include": r"Psycholog"},
                "profile_enrich": {
                    "title_selector": "h1 ~ p, .field-name-field-title, p.subhead",
                    "ladder_recheck": _LADDER,
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "CLS", "Department of Criminology, Law & Society",
            ["Criminology, Law & Society"],
            "https://socialecology.uci.edu/faculty",
            {
                "selectors": {
                    "card": "div.card.h-100",
                    "name": "div.fs-4.fw-bold",
                    "email": "p a[href^='mailto:']",
                },
                "field_filter": {"selector": "p.fst-italic.text-muted a",
                                 "include": r"Criminology"},
                "profile_enrich": {
                    "title_selector": "h1 ~ p, .field-name-field-title, p.subhead",
                    "ladder_recheck": _LADDER,
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "UPPP", "Department of Urban Planning & Public Policy",
            ["Urban Studies", "Public Policy"],
            "https://socialecology.uci.edu/faculty",
            {
                "selectors": {
                    "card": "div.card.h-100",
                    "name": "div.fs-4.fw-bold",
                    "email": "p a[href^='mailto:']",
                },
                "field_filter": {"selector": "p.fst-italic.text-muted a",
                                 "include": r"Urban Planning"},
                "profile_enrich": {
                    "title_selector": "h1 ~ p, .field-name-field-title, p.subhead",
                    "ladder_recheck": _LADDER,
                    "throttle": 1.0,
                },
            },
        ),
        # (Charlie Dunlop School of Biological Sciences deferred: its WordPress
        # biosci_people REST feed gives clean name+link for all 157 faculty, but
        # the Divi profile pages render email/rank/research client-side — the
        # static HTML exposes only a shared dept inbox (never a usable
        # cold-email address). Recovering it needs a per-profile headless pass.
        # See module docstring.)
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
