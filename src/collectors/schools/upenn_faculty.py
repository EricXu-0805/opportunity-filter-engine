"""University of Pennsylvania faculty config (via the faculty_graph engine).

Covers every Penn school with a public directory (61 departments):

- **School of Arts & Sciences** (29 depts): all Drupal, no WP API, three shared
  themes — A (D9 people-list ``div.views-row`` + ``summary h3 a`` + mailto),
  B (legacy D7 ``li.views-row`` + ``h2 a``, email only on profiles), C (new
  sas_theme ``article.node--type-profile``) — plus per-dept variants carried
  inline. Most departments publish a pre-filtered "standing-faculty" listing.
  Four hosts (figs/hss/southasia/theatre) 403 a spoofed Chrome UA whose TLS
  fingerprint isn't Chrome's but allow an honest tool UA (``ua`` override).
- **SEAS**: one WordPress directory for all six departments; per-dept card
  classes (``.ft-<dept>``) plus ``.ft-tenure-track`` select ladder faculty
  directly, emails inline.
- **Wharton** (10 depts): shared wharton-department-platform listing; the rank
  is a bare text node after the name anchor, extracted via ``title_re``.
- **Annenberg / GSE**: paginated Drupal card listings, emails inline.
- **Nursing**: LiveWhale — the human page renders 30 cards but the widget
  endpoint ``/live/widget/32?page=6`` is cumulative and returns all ~161 in one
  response; names carry credential suffixes (stripped), titles/emails live on
  profiles so the enrich pass is ``always`` on (it is where core fields live).
- **SP2 / Vet**: WordPress REST people APIs (SP2 standing+research terms; Vet
  per-department taxonomy + tenure/CE/research position types; Vet's Varnish
  403s browser UAs → ``ua`` override).
- **Weitzman Design** (5 depts): Drupal ``?area=<tid>`` listings (adjuncts and
  PhD students mixed in — ladder filter does the cut), emails on profiles.
- **Penn Carey Law**: single directory; ``.standing-faculty`` card class is the
  ladder cut; profile emails are plain text (``.emailadd p``), not mailtos.
- **Dental**: 555-profile sitemap walk (no listing titles anywhere); ladder
  filter keeps the non-clinical professoriate. No public emails exist.
- **Perelman School of Medicine** (10 basic-science/research depts): mixed
  templates behind an Imperva WAF that 403s after ~6 rapid hits — every dept
  carries ``pre_delay`` so a burst never silently drops a department. Genetics
  is Alpine.js (FEDS) and needs render mode. Pathology (JS-truncated listing)
  and the Next.js clinical departments (hashed classnames, __NEXT_DATA__ blob)
  are a documented follow-up.

Single source ("upenn_faculty"); department rides each record's
``department``. Audience "unknown" (per-professor openness).
"""

from __future__ import annotations

from .. import faculty_graph

# Hosts whose WAF (Cloudflare UA/TLS-mismatch heuristic, Vet's Varnish) block a
# spoofed Chrome UA but pass an honest tool UA straight through.
_PLAIN_UA = "curl/8.7.1"

# ---------------------------------------------------------------------------
# School of Arts & Sciences — three shared Drupal themes
# ---------------------------------------------------------------------------
_SAS_A = {"card": "div.views-row", "name": "summary h3 a", "link": "summary h3 a",
          "title": "p.title span.title", "email": "a[href^='mailto:']"}
_SAS_B = {"card": "li.views-row", "name": "h2 a", "link": "h2 a", "title": "h3"}
_SAS_C = {"card": "article.node--type-profile", "name": "h3 a", "link": "h3 a",
          "title": ".field--name-field-official-title",
          "email": "a[href^='mailto:']"}
# Most listings are pre-filtered standing-faculty pages; the require gate keeps
# the professorial ladder AND administratively-titled chairs ("Department
# Chair"), the drop cuts ranks that co-occur with "professor" but aren't ladder.
_SAS_LADDER = {"require": r"\bprofessor\b|\bchair\b",
               "drop": (r"\bemerit|\blecturer|\badjunct|\bvisiting|\bpractice\b"
                        r"|\bpostdoc|\binstructor|\bstaff\b|graduate student")}
_SAS_ENRICH = {"email_selector": "a[href^='mailto:']", "throttle": 0.2,
               # Some profiles lead with the department's shared inbox
               # (info@english, cims-info@) — never take an alias as a
               # personal address.
               "email_drop": r"^(?:[\w-]*info|admin|office|contact|dept\w*)@"}


def _sas(short: str, name: str, majors: list[str], url: str, *,
         theme: dict = _SAS_A, ua: str | None = None,
         enrich: bool = False, selectors: dict | None = None,
         research_items_selector: str | None = None,
         research_selector: str | None = None) -> dict:
    scrape: dict = {"url": url, "selectors": selectors or theme,
                    "ladder_filter": _SAS_LADDER}
    if ua:
        scrape["ua"] = ua
    # A few SAS depts publish a CLEAN taxonomy on the profile (Anthropology's
    # "modes of approach" chips, Art History's "field of study" chips, Psych's
    # semicolon "research interests" field). Those ride the same env-gated pass
    # as the email enrich. The dominant SAS free-text field is a bio narrative
    # and is deliberately NOT wired.
    if research_items_selector or research_selector:
        e = dict(_SAS_ENRICH)
        if research_items_selector:
            e["research_items_selector"] = research_items_selector
        if research_selector:
            e["research_selector"] = research_selector
        scrape["profile_enrich"] = e
    elif enrich:
        scrape["profile_enrich"] = _SAS_ENRICH
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# ---------------------------------------------------------------------------
# SEAS — one WordPress directory, per-dept card classes
# ---------------------------------------------------------------------------
_SEAS_URL = "https://directory.seas.upenn.edu/"
_SEAS_SEL = {"name": ".StaffListName a", "link": ".StaffListName a",
             "title": ".StaffListTitles div:first-child",
             "email": "a[href^='mailto:']"}


def _seas(short: str, name: str, majors: list[str], code: str) -> dict:
    # .ft-tenure-track on the card IS the ladder cut (practice/adjunct/
    # emeritus/research tracks carry their own classes) — no title filter needed.
    sel = {**_SEAS_SEL, "card": f".SingleStaffList.ft-{code}.ft-tenure-track"}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": _SEAS_URL,
            "scrape": {"url": _SEAS_URL, "selectors": sel}}


# ---------------------------------------------------------------------------
# Wharton — shared platform; rank is a bare text node ("Name , Title"),
# captured from the card text after the first comma.
# ---------------------------------------------------------------------------
_WH_SEL = {"card": "li.wdp_listing-row", "name": "strong a", "link": "strong a",
           "title_re": r",\s*(.+)$", "email": "a[href^='mailto:']"}
_WH_LADDER = {"require": r"\bprofessor\b",
              "drop": (r"\bemerit|\badjunct|\blecturer|\bvisiting"
                       r"|\bpractice\b|senior fellow")}
# Listings carry name/title/email but zero research. Each *.wharton profile
# keeps interests in the first <p> of div.wfp-header-research
# ("Research Interests: a, b, c"); the engine strips the label + comma-splits.
_WH_ENRICH = {
    "research_selector": 'div.wfp-header-research p:-soup-contains("Research Interests")',
    "throttle": 0.3,
    "timeout": 8,
    "max_retries": 1,
}


def _wh(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _WH_SEL,
                       "ladder_filter": _WH_LADDER,
                       "profile_enrich": _WH_ENRICH}}


# ---------------------------------------------------------------------------
# Perelman School of Medicine — Imperva WAF rate-limits bursts, so every dept
# spaces its listing hit (pre_delay). Shared SSflex "li.profile" template on
# several basic-science departments.
# ---------------------------------------------------------------------------
_MED_DELAY = 8
_MED_LADDER = {"require": r"\bprofessor\b|\bchair\b|\bchief\b",
               "drop": r"\bemerit|\badjunct|\blecturer|\bvisiting|\binstructor|\bstaff\b"}


SCHOOL: dict = {
    "school_slug": "upenn",
    "source": "upenn_faculty",
    "organization": "University of Pennsylvania",
    "location": "Philadelphia, PA",
    "id_prefix": "upenn",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Pennsylvania) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ================= School of Arts & Sciences (29) =================
        _sas("AFRC", "Department of Africana Studies", ["Africana Studies"],
             "https://africana.sas.upenn.edu/department-africana-studies/standing-faculty",
             selectors={"card": ".views-view-grid .col", "name": "h3 a",
                        "link": "h3 a", "title": "p.title",
                        "email": "a[href^='mailto:']"}),
        _sas("ANTH", "Department of Anthropology", ["Anthropology"],
             "https://anthropology.sas.upenn.edu/people/standing-faculty",
             selectors={**_SAS_B, "name": ".views-field-title-1 h2 a",
                        "link": ".views-field-title-1 h2 a"},
             research_items_selector="div.field-name-field-modes-of-approach a"),
        _sas("BIOL", "Department of Biology", ["Biology"],
             "https://www.bio.upenn.edu/people/standing-faculty"),
        _sas("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
             "https://www.chem.upenn.edu/people/faculty"),
        _sas("CIMS", "Department of Cinema & Media Studies",
             ["Cinema & Media Studies", "Film"],
             "https://cinemastudies.sas.upenn.edu/people/core-faculty",
             selectors={"card": ".view-content > div.row.people-list",
                        "name": "h3 a", "link": "h3 a", "title": "p.title",
                        "email": "a[href^='mailto:']"},
             enrich=True),
        _sas("CLST", "Department of Classical Studies", ["Classical Studies", "Classics"],
             "https://www.classics.upenn.edu/people/standing-faculty"),
        _sas("CRIM", "Department of Criminology", ["Criminology"],
             "https://crim.sas.upenn.edu/people",
             selectors={"card": "li.views-row", "name": ".span6 h2",
                        "link": "a", "title": ".span6 h3",
                        "email": "a[href^='mailto:']"}),
        _sas("EES", "Department of Earth & Environmental Science",
             ["Earth Science", "Environmental Science", "Geology"],
             "https://earth.sas.upenn.edu/people/faculty"),
        _sas("EALC", "Department of East Asian Languages & Civilizations",
             ["East Asian Studies", "Chinese", "Japanese"],
             "https://ealc.sas.upenn.edu/people/faculty"),
        _sas("ECON", "Department of Economics", ["Economics"],
             "https://economics.sas.upenn.edu/people/faculty",
             # No public emails anywhere (profiles show dept aliases only).
             selectors={"card": "ul.people-list > li.row", "name": "h3 a",
                        "link": "h3 a", "title": "h4.col-sm-5"}),
        _sas("ENGL", "Department of English",
             ["English", "Literature", "Creative Writing"],
             "https://www.english.upenn.edu/people/faculty",
             # The page stacks Standing/Affiliated/Non-standing/Emeritus views —
             # scope to the standing-faculty view or 85 lecturers ride along.
             selectors={"card": ".view-display-id-page_1 li.row-fluid",
                        "name": "h3 a", "link": "h3 a",
                        "title": "div.official-title:last-of-type p"},
             enrich=True),
        _sas("FIGS", "Department of Francophone, Italian & Germanic Studies",
             ["French", "Italian", "German"],
             "https://figs.sas.upenn.edu/people/standing-faculty", ua=_PLAIN_UA),
        _sas("HIST", "Department of History", ["History"],
             "https://www.history.upenn.edu/people/standing-faculty"),
        _sas("HSS", "Department of History & Sociology of Science",
             ["History & Sociology of Science", "Science, Technology & Society"],
             "https://hss.sas.upenn.edu/people/standing%20faculty",
             selectors={**_SAS_A, "title": "p.title"}, ua=_PLAIN_UA),
        _sas("ARTH", "Department of the History of Art", ["Art History"],
             "https://arth.sas.upenn.edu/people/standing-faculty",
             selectors={**_SAS_B, "title": ".views-field-views-conditional h3"},
             research_items_selector="div.field-field-of-study a"),
        _sas("LING", "Department of Linguistics", ["Linguistics"],
             "https://www.ling.upenn.edu/people/faculty"),
        _sas("MATH", "Department of Mathematics", ["Mathematics"],
             "https://www.math.upenn.edu/people/standing-faculty",
             selectors={"card": ".people-list li.row-fluid", "name": ".span4 h2",
                        "link": "a", "title": "h3",
                        "email": "a[href^='mailto:']"}),
        _sas("MELC", "Department of Middle Eastern Languages & Cultures",
             ["Middle Eastern Studies", "Near Eastern Languages"],
             "https://melc.sas.upenn.edu/people/standing-faculty"),
        _sas("MUSC", "Department of Music", ["Music"],
             "https://music.sas.upenn.edu/people/standing-faculty"),
        _sas("PHIL", "Department of Philosophy", ["Philosophy"],
             "https://philosophy.sas.upenn.edu/people/department-faculty",
             selectors={**_SAS_B, "title": ".views-field-field-official-title h3"},
             enrich=True),
        _sas("PHYS", "Department of Physics & Astronomy", ["Physics", "Astronomy"],
             "https://www.physics.upenn.edu/people/standing-faculty"),
        _sas("PSCI", "Department of Political Science", ["Political Science"],
             "https://www.polisci.upenn.edu/people/standing-faculty", enrich=True),
        _sas("PSYC", "Department of Psychology", ["Psychology"],
             "https://psychology.sas.upenn.edu/people/standing-faculty",
             theme=_SAS_C,
             research_selector="div.field--name-field-research-interests"),
        _sas("RELS", "Department of Religious Studies", ["Religious Studies"],
             "https://rels.sas.upenn.edu/people/standing-faculty"),
        _sas("REES", "Department of Russian & East European Studies",
             ["Russian", "East European Studies"],
             "https://rees.sas.upenn.edu/people",
             # Masonry grid mixes affiliated/lecturers/staff — ladder cuts.
             selectors={"card": ".view-content .grid-item", "name": "h2 a",
                        "link": "h2 a", "title": "h3",
                        "email": "a[href^='mailto:']"}),
        _sas("SOCI", "Department of Sociology", ["Sociology"],
             "https://sociology.sas.upenn.edu/people/standing-faculty"),
        _sas("SAST", "Department of South Asia Studies", ["South Asia Studies"],
             "https://www.southasia.upenn.edu/people/standing-faculty",
             theme=_SAS_C, ua=_PLAIN_UA),
        _sas("SPAN", "Department of Spanish & Portuguese", ["Spanish", "Portuguese"],
             "https://spanish.sas.upenn.edu/people/standing-faculty",
             theme=_SAS_C),
        _sas("THAR", "Theatre Arts Program", ["Theatre Arts"],
             "https://theatre.sas.upenn.edu/people", ua=_PLAIN_UA),
        # ================= SEAS (6, one directory) =================
        _seas("BE", "Department of Bioengineering",
              ["Bioengineering", "Biomedical Engineering"], "be"),
        _seas("CBE", "Department of Chemical & Biomolecular Engineering",
              ["Chemical Engineering", "Biomolecular Engineering"], "cbe"),
        _seas("CIS", "Department of Computer & Information Science",
              ["Computer Science", "Artificial Intelligence", "Computer Engineering"],
              "cis"),
        _seas("ESE", "Department of Electrical & Systems Engineering",
              ["Electrical Engineering", "Systems Engineering"], "ese"),
        _seas("MEAM", "Department of Mechanical Engineering & Applied Mechanics",
              ["Mechanical Engineering", "Robotics"], "meam"),
        _seas("MSE", "Department of Materials Science & Engineering",
              ["Materials Science", "Nanotechnology"], "mse"),
        # ================= Wharton (10) =================
        _wh("ACCT", "Accounting Department (Wharton)", ["Accounting"],
            "https://accounting.wharton.upenn.edu/faculty/faculty-list/"),
        _wh("BEPP", "Business Economics & Public Policy Department (Wharton)",
            ["Business Economics", "Public Policy"],
            "https://bepp.wharton.upenn.edu/faculty/faculty-list/"),
        _wh("FNCE", "Finance Department (Wharton)", ["Finance"],
            "https://fnce.wharton.upenn.edu/faculty/faculty-list/"),
        _wh("HCMG", "Health Care Management Department (Wharton)",
            ["Health Care Management"],
            "https://hcmg.wharton.upenn.edu/faculty/faculty-list/"),
        _wh("LGST", "Legal Studies & Business Ethics Department (Wharton)",
            ["Legal Studies", "Business Ethics"],
            "https://lgst.wharton.upenn.edu/faculty/faculty-list/"),
        _wh("MGMT", "Management Department (Wharton)",
            ["Management", "Entrepreneurship"],
            "https://mgmt.wharton.upenn.edu/faculty-list/"),
        _wh("MKTG", "Marketing Department (Wharton)", ["Marketing"],
            "https://marketing.wharton.upenn.edu/faculty/faculty-list/"),
        _wh("OIDD", "Operations, Information & Decisions Department (Wharton)",
            ["Operations & Information Management", "Business Analytics"],
            "https://oid.wharton.upenn.edu/faculty/faculty-list/"),
        _wh("REAL", "Real Estate Department (Wharton)", ["Real Estate"],
            "https://real-estate.wharton.upenn.edu/faculty/faculty-list/"),
        _wh("STAT", "Statistics & Data Science Department (Wharton)",
            ["Statistics", "Data Science"],
            "https://statistics.wharton.upenn.edu/faculty/faculty-list/"),
        # ================= Annenberg / GSE =================
        {
            "short": "ASC", "name": "Annenberg School for Communication",
            "majors": ["Communication", "Media Studies"],
            "directory_url": "https://www.asc.upenn.edu/people/faculty",
            "scrape": {
                "url": "https://www.asc.upenn.edu/people/faculty",
                "selectors": {"card": ".card--profile", "name": "h3 a",
                              "link": "h3 a", "title": ".position",
                              "email": "a[href^='mailto:']"},
                # Drupal pager: base page is ?page=0, follow-ups 1..5.
                "paginate": {"param": "page", "start": 1, "max": 5},
                "ladder_filter": _SAS_LADDER,
                # Profile sidebar links each research area to /research/research-
                # areas/… — clean atomic chips; env-gated research-only pass.
                "profile_enrich": {
                    "research_items_selector":
                        ".profile-content__sidebar a[href*='/research/research-areas/']",
                    "throttle": 0.2,
                },
            },
        },
        {
            "short": "GSE", "name": "Graduate School of Education",
            "majors": ["Education", "Education Policy", "Learning Sciences"],
            "directory_url": "https://www.gse.upenn.edu/about-us/faculty",
            "scrape": {
                "url": "https://www.gse.upenn.edu/about-us/faculty",
                "selectors": {"card": ".people_list_item",
                              "name": ".people_list_item_name_link_label",
                              "link": "h2 a",
                              "title": ".people_list_item_job_title",
                              "email": "a[href^='mailto:']"},
                "paginate": {"param": "page", "start": 1, "max": 4},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": (r"\bemerit|\blecturer|\badjunct"
                                           r"|\bvisiting|\bpractice\b|senior fellow")},
            },
        },
        # ================= Nursing (LiveWhale widget) =================
        {
            "short": "NURS", "name": "School of Nursing",
            "majors": ["Nursing"],
            "directory_url": "https://www.nursing.upenn.edu/about/our-faculty/",
            # The widget endpoint's pagination is cumulative: page=6 returns
            # all ~161 faculty in one server-rendered response (the human page
            # renders only the first 30). Listing has neither titles nor
            # emails — the always-on profile pass is where those live, and
            # ladder_recheck re-gates once real ranks exist.
            "scrape": {
                "url": "https://www.nursing.upenn.edu/live/widget/32?page=6",
                "selectors": {"card": ".col-lg-4.col-md-6.mb-5",
                              "name": "h3 a", "link": "h3 a",
                              "name_strip": r",.*$"},
                "profile_enrich": {
                    "always": True,
                    "email_selector": "a[href^='mailto:']",
                    "title_selector": "h1 + p",
                    "use_position_title": True,
                    "throttle": 0.2,
                    "ladder_recheck": {
                        "require": r"\bprofessor\b",
                        "drop": (r"\bemerit|\blecturer|\badjunct|\bvisiting"
                                 r"|\bpractice\b|\binstructor")},
                },
            },
        },
        # ================= SP2 (WordPress REST) =================
        {
            "short": "SP2", "name": "School of Social Policy & Practice",
            "majors": ["Social Work", "Social Policy", "Nonprofit Leadership"],
            "directory_url": "https://sp2.upenn.edu/sp2-directory/",
            # departments taxonomy: 141 = standing faculty, 146 = research
            # faculty (the FacetWP HTML listing is AJAX-only — API preferred).
            "api": {"type": "wp", "base": "https://sp2.upenn.edu",
                    "post_type": "people",
                    "category_include": {"departments": [141, 146]},
                    # WP "research-cat" taxonomy → clean controlled-vocabulary
                    # keywords straight off the feed (no per-profile fetch).
                    "keyword_tax": ["research-cat"],
                    "name_strip": r",\s*(?:Ph\.?D|Ed\.?D|D\.?S\.?W|J\.?D|M\.?D|MSW|LCSW|MPA|MS|MA)\b.*$"},
            "profile_enrich": {"email_selector": "a[href^='mailto:']",
                               "title_selector": "h1 ~ h2",
                               "use_position_title": True, "throttle": 0.2},
        },
        # ================= Weitzman School of Design (5) =================
        *[
            {
                "short": short, "name": name, "majors": majors,
                "directory_url": f"https://www.design.upenn.edu/people?area={tid}",
                "scrape": {
                    "url": f"https://www.design.upenn.edu/people?area={tid}",
                    "selectors": {"card": ".views-row", "name": ".title",
                                  "link": "a.profile-card",
                                  "title": ".meta.titles-inline"},
                    "paginate": {"param": "page", "start": 1, "max": pages},
                    # Area lists mix adjuncts/lecturers/PhD students.
                    "ladder_filter": {
                        "require": r"\bprofessor\b",
                        "drop": (r"\bemerit|\blecturer|\badjunct|\bvisiting"
                                 r"|\bpractice\b|phd (?:candidate|student)"
                                 r"|research associate|\bfellow\b")},
                    "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                       "throttle": 0.2},
                },
            }
            for short, name, majors, tid, pages in [
                ("ARCH", "Department of Architecture (Weitzman)", ["Architecture"], 3, 11),
                ("CPLN", "Department of City & Regional Planning (Weitzman)",
                 ["City & Regional Planning", "Urban Design"], 70, 3),
                ("FNAR", "Department of Fine Arts (Weitzman)", ["Fine Arts"], 8, 6),
                ("HSPV", "Graduate Program in Historic Preservation (Weitzman)",
                 ["Historic Preservation"], 10, 3),
                ("LARP", "Department of Landscape Architecture (Weitzman)",
                 ["Landscape Architecture"], 11, 3),
            ]
        ],
        # ================= Penn Carey Law =================
        {
            "short": "LAW", "name": "Penn Carey Law School",
            "majors": ["Law", "Legal Studies"],
            "directory_url": "https://www.law.upenn.edu/faculty/directory.php",
            "scrape": {
                "url": "https://www.law.upenn.edu/faculty/directory.php",
                # .standing-faculty card class = the 54 standing (ladder +
                # clinical-standing) faculty of the 67 listed.
                "selectors": {"card": ".faculty-post.standing-faculty",
                              "name": "h4",
                              "link": "a[href^='/live/profiles/']",
                              "title": "p"},
                "ladder_filter": {"require": r"\bprofessor",
                                  "drop": r"\bemerit|\blecturer|\badjunct|\bvisiting|senior fellow"},
                # Profile emails are PLAIN TEXT in .emailadd p, not mailtos.
                "profile_enrich": {"email_selector": ".emailadd p",
                                   "throttle": 0.2},
            },
        },
        # ================= Dental (WP archive listing) =================
        {
            "short": "DENT", "name": "School of Dental Medicine",
            "majors": ["Dental Medicine", "Oral Biology"],
            "directory_url": "https://www.dental.upenn.edu/faculty/",
            # The archive pages (28 × 20 cards) carry the rank as a bare text
            # node after the name — a rank-anchored title_re captures it, so
            # the ladder cut happens at listing time. (A per-profile sitemap
            # walk works too but dental.upenn.edu TLS-throttles 556 rapid
            # fetches into a 2-hour crawl — the 28-page archive is the cheap
            # path.) No public emails exist anywhere on this school's site.
            "scrape": {
                "url": "https://www.dental.upenn.edu/faculty/",
                "selectors": {"card": "section.row.pt-3.mb-3",
                              "name": "h2.page-title span",
                              "link": "a.text-decoration-none",
                              "name_strip": r",.*$",
                              "title_re": (r"((?:Clinical\s+|Adjunct\s+|Visiting\s+"
                                           r"|Interim\s+|Assistant\s+|Associate\s+)*"
                                           r"(?:Professor|Instructor|Clinical Associate"
                                           r"|Lecturer|Dean)(?:\s+of\s+.*)?)$")},
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 28},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": (r"\bclinical|\bemerit|\badjunct"
                                           r"|\blecturer|\binstructor|\bvisiting")},
            },
        },
        # ================= Vet (WordPress REST, UA-gated) =================
        *[
            {
                "short": short, "name": name, "majors": majors,
                "directory_url": "https://www.vet.upenn.edu/directory/",
                # position_type: 392 tenure, 393 clinician-educator (a standing
                # track at Penn Vet), 396 research faculty.
                "api": {"type": "wp", "base": "https://www.vet.upenn.edu",
                        "post_type": "people",
                        "query": f"&academic_department={dept_id}",
                        "category_include": {"position_type": [392, 393, 396]},
                        "ua": _PLAIN_UA,
                        "name_strip": r",\s*(?:V\.?M\.?D|D\.?V\.?M|Ph\.?D|M\.?D|DACVIM|DACVS|MS|MSc)\b.*$"},
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "title_selector": ".header__meta--meta",
                                   "use_position_title": True,
                                   "ua": _PLAIN_UA, "throttle": 0.3},
            }
            for short, name, majors, dept_id in [
                ("VET-BIOMED", "Department of Biomedical Sciences (Vet)",
                 ["Veterinary Medicine", "Biomedical Sciences"], 36),
                ("VET-CSAM", "Department of Clinical Sciences & Advanced Medicine (Vet)",
                 ["Veterinary Medicine"], 37),
                ("VET-CSNBC", "Department of Clinical Studies — New Bolton Center (Vet)",
                 ["Veterinary Medicine", "Large Animal Medicine"], 86),
                ("VET-PATHO", "Department of Pathobiology (Vet)",
                 ["Veterinary Medicine", "Pathobiology", "Microbiology"], 103),
            ]
        ],
        # ================= Perelman School of Medicine (10) =================
        {
            "short": "BMB", "name": "Department of Biochemistry & Biophysics (PSOM)",
            "majors": ["Biochemistry", "Biophysics", "Structural Biology"],
            "directory_url": "https://www.med.upenn.edu/biocbiop/primary-faculty.html",
            "scrape": {
                "url": "https://www.med.upenn.edu/biocbiop/primary-faculty.html",
                "pre_delay": _MED_DELAY,
                "selectors": {"card": "li.faculty-profile", "name": "span.name a",
                              "link": "span.name a", "title": "span.position",
                              "email": "a[href^='mailto:']",
                              "name_strip": r",\s*(?:Ph\.?D|M\.?D|D\.? ?Phil|Sc\.?D)\b.*$"},
                "ladder_filter": _MED_LADDER,
            },
        },
        {
            "short": "CBIO", "name": "Department of Cancer Biology (PSOM)",
            "majors": ["Cancer Biology", "Molecular Biology"],
            "directory_url": "https://www.med.upenn.edu/cbio/faculty/",
            "scrape": {
                "url": "https://www.med.upenn.edu/cbio/faculty/",
                "pre_delay": _MED_DELAY,
                "selectors": {"card": "li.profile", "name": "h3",
                              "title": "span.position",
                              "email": "a[href^='mailto:']",
                              "name_strip": r",\s*Ph\.?D\.?.*$"},
                "ladder_filter": _MED_LADDER,
            },
        },
        {
            "short": "CDB", "name": "Department of Cell & Developmental Biology (PSOM)",
            "majors": ["Cell Biology", "Developmental Biology", "Stem Cell Biology"],
            "directory_url": "https://cdb.med.upenn.edu/people/",
            # The .faculty-faculty card class = primary faculty (secondary/
            # adjunct/staff carry their own section classes).
            "scrape": {
                "url": "https://cdb.med.upenn.edu/people/",
                "pre_delay": _MED_DELAY,
                "selectors": {"card": "div.pendari_people_grid_item.faculty-faculty",
                              "name": "h3 a", "link": "h3 a",
                              "name_strip": r",\s*Ph\.?D\.?.*$"},
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "title_selector": "h1 + p",
                                   "use_position_title": True, "throttle": 0.3},
            },
        },
        {
            "short": "GEN", "name": "Department of Genetics (PSOM)",
            "majors": ["Genetics", "Genomics", "Computational Biology"],
            "directory_url": "https://www.med.upenn.edu/genetics/faculty/",
            # Alpine.js FEDS grid: the render lands all 77 names, but titles/
            # emails populate only via lazy in-viewport XHRs (and the JSON
            # endpoint is robots-disallowed; the SPA profile routes 404 when
            # loaded directly). Ship the faculty roster name-first — the
            # OpenAlex/pi-enricher passes attach research + email downstream.
            # The link selector deliberately never matches so records carry
            # the (working) directory URL instead of a broken SPA route.
            "scrape": {
                "url": "https://www.med.upenn.edu/genetics/faculty/",
                "pre_delay": _MED_DELAY,
                "render": True, "render_wait": "networkidle",
                "selectors": {"card": "li.feds-list-item",
                              "name": "a[href^='faculty-profile/']",
                              "link": "a.__no_profile_route__",
                              "name_strip": r",\s*(?:Ph\.?D|M\.?D)\b.*$"},
            },
        },
        {
            "short": "MICRO", "name": "Department of Microbiology (PSOM)",
            "majors": ["Microbiology", "Virology", "Immunology"],
            "directory_url": "https://www.med.upenn.edu/micro/faculty.html",
            "scrape": {
                "url": "https://www.med.upenn.edu/micro/faculty.html",
                "pre_delay": _MED_DELAY,
                "selectors": {"card": "li.profile", "name": "h3.name",
                              "link": "a[href*='apps/faculty']",
                              "title": "span.position",
                              "email": "a[href^='mailto:']",
                              "name_strip": r",\s*(?:Ph\.?D|M\.?D)\b.*$"},
                "ladder_filter": _MED_LADDER,
            },
        },
        {
            "short": "NGG", "name": "Department of Neuroscience (PSOM)",
            "majors": ["Neuroscience"],
            "directory_url": "https://www.med.upenn.edu/neuroscience/",
            # The dept site iframes its FIS group; scrape the FIS primary-
            # faculty category directly (path-based, robots-clean). The FIS
            # roster is a table (tr.member_page_row*) whose rendered rows
            # carry public mailtos; Imperva tarpits repeated plain fetches, so
            # render mode holds a legit browser session.
            "scrape": {
                "url": "https://www.med.upenn.edu/apps/faculty/index.php/g20003260/c2125",
                "pre_delay": _MED_DELAY,
                "render": True,
                "selectors": {"card": "tr[class*='member_page_row']",
                              "name": "td.member_name a",
                              "link": "td.member_name a",
                              "email": "a[href^='mailto:']",
                              "name_strip": r",\s*(?:Ph\.?D|M\.?D|V\.?M\.?D)\b.*$"},
                "link_filter": r"/g20003260/c2125/p\d+",
            },
        },
        {
            "short": "SPTT",
            "name": "Department of Systems Pharmacology & Translational Therapeutics (PSOM)",
            "majors": ["Pharmacology", "Translational Research"],
            "directory_url": "https://www.med.upenn.edu/syspharmatt/faculty/",
            "scrape": {
                "url": "https://www.med.upenn.edu/syspharmatt/faculty/",
                "pre_delay": _MED_DELAY,
                "selectors": {"card": "li.profile", "name": "h3",
                              "title": "span.position",
                              "email": "a[href^='mailto:']",
                              "name_strip": r",\s*(?:Ph\.?D|M\.?D|Pharm\.?D)\b.*$"},
                "ladder_filter": _MED_LADDER,
            },
        },
        {
            "short": "PHGY", "name": "Department of Physiology (PSOM)",
            "majors": ["Physiology", "Metabolism"],
            "directory_url": "https://www.med.upenn.edu/physiol/faculty/",
            # WPBakery grid links to /physiol/people/<slug>/ profiles; harvest
            # them from the listing and read name+email off each profile.
            # Imperva rate-limits ~6 rapid plain hits per burst and its bans
            # outlast polite spacing — render the profile fetches (a real
            # browser session passes clean, as NGG's FIS table shows) and keep
            # the 3s spacing.
            "sitemap": {
                "list_pages": ["https://www.med.upenn.edu/physiol/faculty/"],
                "include": r"/physiol/people/[^/]+",
                "profile_render": True,
                "selectors": {"name": "h1", "email": "a[href^='mailto:']"},
                "cap": 100,
                "throttle": 3.0,
            },
        },
        {
            "short": "DBEI",
            "name": "Department of Biostatistics, Epidemiology & Informatics (PSOM)",
            "majors": ["Biostatistics", "Epidemiology", "Biomedical Informatics"],
            "directory_url": "https://dbei.med.upenn.edu/staff-directory/",
            # staff CPT; staff-category 48 = Core Faculty (124), research-area
            # taxonomy gives clean keywords.
            "api": {"type": "wp", "base": "https://dbei.med.upenn.edu",
                    "post_type": "staff",
                    "category_include": {"staff-category": [48]},
                    "keyword_tax": ["research-area"],
                    "name_strip": r",\s*(?:Ph\.?D|M\.?D|Sc\.?D|Dr\.?P\.?H|M\.?P\.?H|MS|MSCE)\b.*$"},
            "profile_enrich": {"email_selector": "a[href^='mailto:']",
                               "title_selector": "h1 + p",
                               "use_position_title": True, "throttle": 0.3},
        },
        {
            "short": "MEHP", "name": "Department of Medical Ethics & Health Policy (PSOM)",
            "majors": ["Bioethics", "Health Policy"],
            "directory_url": "https://medicalethicshealthpolicy.med.upenn.edu/faculty-all",
            "scrape": {
                "url": "https://medicalethicshealthpolicy.med.upenn.edu/faculty-all",
                "pre_delay": _MED_DELAY,
                "selectors": {"card": "div.c-people-slat",
                              "name": "h3.c-people-slat-name",
                              "link": "a.c-people-slat-thumbnail",
                              "title": "ul.c-people-slat-positions",
                              "email": "a.c-people-slat-email[href^='mailto:']",
                              "name_strip": r",\s*(?:Ph\.?D|M\.?D|J\.?D|M\.?P\.?H|R\.?N|M\.?B\.?E)\b.*$"},
                "ladder_filter": _MED_LADDER,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
