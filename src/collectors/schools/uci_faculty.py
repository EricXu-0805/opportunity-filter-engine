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
  section; Earth System Science is a ``div.views-row`` grid. Physics & Astronomy
  serves its faculty listing under an HTTP 404 status (a Drupal soft-404 that a
  strict GET rejects), so it fetches through the headless browser
  (``scrape.render``), which ignores the status line; the dedicated
  ``/people/faculty`` page is faculty-scoped, with the email in a text field.
- **Computer Science** (WordPress ``person__`` cards on cs.ics.uci.edu): the
  roster is client-rendered, so it too fetches via ``scrape.render``; rank
  (``.person__job-title``) drives the ladder filter and email is a mailto link.
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
Deferred departments (each needs a mechanism this engine can't apply cleanly):
- **ICS — Informatics & Statistics**: informatics.uci.edu and stat.uci.edu serve
  a bot "Access Notice" even to a headless browser (Computer Science, on the
  separate cs.ics.uci.edu host, is collected via render — see above).
- **Humanities** (History/Philosophy/English/Linguistics): the directory loads
  via a Drupal views-AJAX call the static fetch can't reach.
- **Biological Sciences** (Charlie Dunlop School): the ``biosci_people`` WordPress
  REST feed gives clean name+link for ~157 faculty, but the Divi profile pages
  render the personal email/rank client-side — even fully rendered, the page
  exposes only a shared department inbox (never a usable cold-email address), so
  the records would ship without a contact. Deferred until a per-person data
  source surfaces.

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


# School of Humanities — the Drupal "faculty-listing-item" card (T1). Rank +
# email + research on the listing; emeriti/lecturers sit on separate pages, so
# _LADDER is a light safety net. A gated per-profile pass backfills the few
# cards whose email isn't on the listing (e.g. History).
def _hum(short: str, name: str, majors: list[str], url: str) -> dict:
    return _dept(short, name, majors, url, {
        "selectors": {
            "card": "div.paragraph--type--uci-faculty-listing-item",
            "name": ".faculty-listing-title .field--name-field-title .field__item",
            "link": "a[href*='faculty.uci.edu/profile']",
            "title": ".field--name-field-faculty-member-title",
            "email": ".faculty-listing-contact a[href^='mailto:']",
            "research": ".field--name-field-research-interest",
        },
        "ladder_filter": _LADDER,
        "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
    })


# School of Biological Sciences — the central www.bio.uci.edu/academics/faculty/
# <slug>/ pages are server-rendered `bs-staff` cards (T5) with rank + email on
# the listing (the dept SUBDOMAINS are JS-only, so use these). Emeriti/
# in-memoriam are separate slugs, so the roster is clean.
def _bio(short: str, name: str, majors: list[str], slug: str) -> dict:
    url = f"https://www.bio.uci.edu/academics/faculty/{slug}/"
    return _dept(short, name, majors, url, {
        "selectors": {
            "card": "div.entry",
            "name": "h2.text-175",
            "link": "a",
            "title": "h3.text-11",
            "email": ".bs-staff-contact a[href^='mailto:']",
        },
        "ladder_filter": _LADDER,
    })


# Professional schools on the WordPress "cp-dir" directory theme (T6): Public
# Health, Pharmacy, Nursing. Rank in `.cp-dir-field-academic_title`; email is on
# the listing for a subset only, so a gated per-profile pass backfills the rest.
def _cpdir(short: str, name: str, majors: list[str], url: str) -> dict:
    return _dept(short, name, majors, url, {
        "selectors": {
            "card": "div.cp-dir-content-entry.profile-card",
            "name": ".cp-dir-field-post_title",
            "link": "a",
            "title": ".cp-dir-field-academic_title",
            "email": "a[href^='mailto:']",
        },
        "ladder_filter": _LADDER,
        "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
    })


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
                # Research areas live on the dept profile page as a taxonomy
                # field (gated OFE_ENRICH_PROFILES); the stored link is the
                # /people/<slug> profile.
                "profile_enrich": {
                    "research_items_selector":
                        "section.field-name-field-research-interests-to-disp .field-item",
                    "throttle": 1.0,
                },
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
        _dept(
            "PHYS", "Department of Physics & Astronomy",
            ["Physics", "Applied Physics", "Astrophysics"],
            "https://www.physics.uci.edu/people/faculty",
            {
                # The faculty page serves content under an HTTP 404 status (Drupal
                # soft-404) that a strict GET rejects — render bypasses the status
                # line. The /people/faculty page is faculty-scoped (no all-people
                # roster), so no ladder filter; email is a text field, not a link.
                "render": True,
                "selectors": {
                    "card": "div.views-row",
                    "name": "div.views-field-title a",
                    "link": "div.views-field-title a",
                    "email": "div.views-field-field-email",
                },
            },
        ),
        # ---- Bren School of ICS: Computer Science (WordPress, rendered) -----
        _dept(
            "CS", "Department of Computer Science",
            ["Computer Science", "Software Engineering", "Data Science"],
            "https://cs.ics.uci.edu/faculty/",
            {
                # cs.ics.uci.edu renders its roster client-side (person__ BEM
                # cards) from late XHRs, so it needs networkidle — a plain
                # domcontentloaded render comes back empty. Rank is on the card,
                # so ladder-filter the teaching/adjunct/joint entries out of 72.
                "render": True,
                "render_wait": "networkidle",
                "selectors": {
                    "card": "div.person__content",
                    "name": "h3",
                    "title": ".person__job-title",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
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
        # ==== Depth expansion ================================================
        # School of Biological Sciences — via the server-rendered central pages
        # (the dept subdomains' biosci_people feed is JS/profile-gated, per the
        # note that used to sit here). Email + rank on the listing.
        _bio("MBB", "Department of Molecular Biology & Biochemistry",
             ["Biological Sciences", "Biochemistry & Molecular Biology"],
             "molecular-biology-and-biochemistry"),
        _bio("NBB", "Department of Neurobiology & Behavior",
             ["Neurobiology", "Biological Sciences"],
             "neurobiology-and-behavior"),
        _bio("DCB", "Department of Developmental & Cell Biology",
             ["Developmental & Cell Biology", "Biological Sciences"],
             "developmental-and-cell-biology-faculty"),
        _bio("EEB", "Department of Ecology & Evolutionary Biology",
             ["Ecology & Evolutionary Biology", "Biological Sciences"],
             "ecology-and-evolutionary-biology"),
        # School of Humanities (T1 faculty-listing cards).
        _hum("HIST", "Department of History", ["History"],
             "https://www.humanities.uci.edu/history/core-faculty"),
        _hum("PHIL", "Department of Philosophy", ["Philosophy"],
             "https://www.humanities.uci.edu/philosophy/faculty"),
        _hum("ARTH", "Department of Art History", ["Art History"],
             "https://www.humanities.uci.edu/arthistory/core-faculty"),
        _hum("CLAS", "Department of Classics", ["Classics"],
             "https://www.humanities.uci.edu/classics/faculty"),
        _hum("FMS", "Department of Film & Media Studies", ["Film & Media Studies"],
             "https://www.humanities.uci.edu/filmandmediastudies/core-faculty"),
        # Merage School of Business — static faculty table (T8). The rank rides
        # in the row text after the name (no clean field), so title_re captures
        # it and _LADDER drops emeriti/lecturers/joint appointments; the row
        # class encodes the academic area.
        _dept("MERAGE", "Paul Merage School of Business",
              ["Business Administration", "Management"],
              "https://merage.uci.edu/research-faculty/faculty-directory/index.html",
              {"selectors": {"card": "tr.deptRow", "name": "td strong a",
                             "link": "td strong a", "email": "td a[href^='mailto:']",
                             "title_re": r"((?:Assistant |Associate |Distinguished )?"
                                         r"(?:Chancellor's )?Professor(?:\s+Emeritus)?)"},
               "ladder_filter": {"require": r"\bprofessor\b",
                                 "drop": r"emerit|lecturer|joint appointment|adjunct|visiting"}}),
        # Professional schools (cp-dir T6): email backfilled per-profile.
        _cpdir("PUBHLTH", "Program in Public Health",
               ["Public Health", "Public Health Sciences"],
               "https://publichealth.uci.edu/about/our-faculty/"),
        _cpdir("PHARM", "School of Pharmacy & Pharmaceutical Sciences",
               ["Pharmaceutical Sciences", "Pharmacy"],
               "https://pharmsci.uci.edu/about/our-faculty/"),
        _cpdir("NURS", "Sue & Bill Gross School of Nursing", ["Nursing"],
               "https://nursing.uci.edu/faculty-research/our-faculty/"),
        # ==== Depth-2 =========================================================
        # (Psychology & Social Behavior is already covered via the socsci.uci.edu
        # shared table above.) Claire Trevor School of the Arts — the /{dept}/people
        # listings carry
        # name + /faculty/<slug> link but NO rank or email (staff are mixed in),
        # so an always-on per-profile pass reads the rank + personal email off
        # each profile and ladder_recheck drops the staff/lecturers after.
        *[_dept(short, name, majors, url,
                {"selectors": {"card": "div.text-md.font-bold",
                               "name": "a[href^='/faculty/']",
                               "link": "a[href^='/faculty/']"},
                 "profile_enrich": {
                     "always": True, "throttle": 1.0,
                     "title_selector": ".field--name-field-job-title",
                     "email_selector": "a[href^='mailto:']",
                     "ladder_recheck": {"require": r"\bprofessor\b",
                                        "drop": r"emerit|lecturer|adjunct|visiting|of teaching"}}})
          for short, name, majors, url in [
              ("ART", "Department of Art", ["Art", "Studio Art"], "https://www.arts.uci.edu/art/people"),
              ("MUS", "Department of Music", ["Music"], "https://www.arts.uci.edu/music/people"),
              ("DRAMA", "Department of Drama", ["Drama"], "https://www.arts.uci.edu/drama/people"),
              ("DANCE", "Department of Dance", ["Dance"], "https://www.arts.uci.edu/dance/people"),
          ]],
        # ---- Bren School of ICS: Informatics + Statistics -------------------
        # WordPress `item--person` cards (name h3 + job-title + mailto on the
        # listing). The *.ics.uci.edu hosts ship an incomplete TLS chain, but
        # fetch_soup's InCommon-intermediate bundle completes it (no verify=False).
        *[_dept(short, name, majors, url,
                {"selectors": {"card": "article.item--person",
                               "name": ".person__person-title",
                               "link": "a", "title": ".person__job-title",
                               "email": "a[href^='mailto:']"},
                 "ladder_filter": {"require": r"\bprofessor\b",
                                   "drop": r"emerit|lecturer|adjunct|visiting|of teaching|continuing"}})
          for short, name, majors, url in [
              ("INFO", "Department of Informatics", ["Informatics", "Software Engineering"],
               "https://informatics.ics.uci.edu/people/"),
              ("STAT", "Department of Statistics", ["Statistics", "Data Science"],
               "https://www.stat.uci.edu/people/"),
          ]],
        # ---- School of Humanities: WYSIWYG "T2" core-faculty pages ----------
        # Hand-authored pages with no card element: each faculty is a <p> holding
        # <strong>Name</strong> + a mailto + a "View Faculty Profile" link, with
        # the rank in sibling <p><em> blocks. We anchor the card on that name <p>
        # (:has(strong):has(mailto)); these are the ladder-only /core-faculty
        # pages (emeriti/lecturers live on separate pages), so no title filter is
        # needed and none is reachable from the name <p>. (Religious Studies is
        # excluded: its page mixes ~50 affiliated cross-listings that would
        # duplicate their home departments.)
        *[_dept(short, name, majors, url,
                {"selectors": {"card": "p:has(strong):has(a[href^='mailto:'])",
                               "name": "strong",
                               "link": "a[href*='faculty.uci.edu']",
                               "email": "a[href^='mailto:']"}})
          for short, name, majors, url in [
              ("ENGL", "Department of English", ["English"],
               "https://www.humanities.uci.edu/english/core-faculty"),
              ("COMPLIT", "Department of Comparative Literature", ["Comparative Literature"],
               "https://www.humanities.uci.edu/complit/meet-faculty"),
              ("EALC", "Department of East Asian Studies", ["East Asian Studies"],
               "https://www.humanities.uci.edu/eastasian/core-faculty"),
              ("ELS", "Department of European Languages & Studies",
               ["European Languages & Studies", "French", "German", "Spanish"],
               "https://www.humanities.uci.edu/els/faculty"),
          ]],
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
