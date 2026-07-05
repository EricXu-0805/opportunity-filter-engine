"""University of Chicago faculty config (via the faculty_graph engine).

Forty-two departments across the College's four collegiate divisions + the
professional schools, verified Jul 2026 (per-department directory probes; raw
HTML/JSON snapshots reviewed by hand before selectors were pinned). The full
Arts & Humanities Division is covered except Germanic Studies (deferred —
unreachable from the collection network, a proxy TLS failure rather than a bot
wall). Art History (photo-tile) and Visual Arts (section-grouped
"academic-profiles") use two further Drupal view templates. Booth (a client-side
Coveo search) is now live via the headless render path with
``render_wait="networkidle"`` (its Coveo grid populates only after late XHRs; a
fixed settle grabbed zero cards).

  * **Live scrape (33 departments), directory families:**
      - *WordPress+FacetWP* -- CS (single-page card grid, per-profile "Focus
        Areas" enrich).
      - *PSD MixItUp* -- Statistics, Mathematics, Physics, Astronomy (one CMS,
        shared selector set; no listing email, so a gated per-profile mailto
        pass backfills it). Geophysical Sciences is a MixItUp *variant* (no
        people_content wrapper, no listing email either).
      - *Drupal Views "bio-*"* -- Economics, Psychology + the five Social
        Sciences Division depts (Sociology, Political Science, History,
        Anthropology, Comparative Human Development). Paginated, emailed,
        interest-tagged; the /people/faculty view is ladder-clean (emeriti on a
        separate page).
      - *Drupal Views "profile-tile"* (Humanities Division) -- Philosophy
        (section-sliced to Core Faculty), English, Linguistics. Single-page,
        emailed; mixes instructional/visiting/teaching-fellow roles, so a
        title/section filter is mandatory.
      - *PME card-spotlight* -- emailed + research topics via taxonomy spans.
      - *Professional-school directories* -- Harris (teaser-table, profile-type
        field filter), Law (profile-list, profile_type=103 view), Crown Family
        School (person-card, capital-T "mailTo:" recovered by _clean_email),
        Divinity (faceted-path faculty view, no listing email -> gated profile
        mailto pass), Booth (client-side Coveo, render_wait="networkidle"). The
        Data Science Institute is skipped (its whole roster is cross-appointed
        CS/Stat/Harris/etc. -- adding it would double-count).
  * **Live json_dir from the sites' own JSON APIs (9 departments).** Chemistry's
    directory page and the eight BSD department sites (Ecology & Evolution,
    Neurobiology, Human Genetics, Molecular Genetics & Cell Biology,
    Biochemistry & Molecular Biology, Organismal Biology & Anatomy, Public
    Health Sciences, Microbiology) are JS-only shells over JSON feeds. Chemistry
    reads its own Pantheon ``faculty_index`` (relative pathAlias joined via
    ``link_base``); the eight BSD depts share ``bsd-data.prod.uchicago.edu``,
    which gates on a same-origin ``Referer`` (``headers``) and lists every joint
    appointment in each record's ``department`` array -- so ``filter_index=0``
    keeps only the PRIMARY appointment, and ``link_list`` pulls the stable
    ``profiles.uchicago.edu`` research-network URL (the per-dept microsite hosts
    aren't all resolvable). ``research_field="interests[]"`` turns each feed's
    interest list into keywords. See the ``_bsd`` helper below.

BSD department chairs carry the literal title "Chair" (Carole Ober, David
Freedman, ...), not "...Professor", so the BSD json_dir uses a drop-only rank
filter -- requiring "professor" would have dropped every chair. Emails are
absent from all nine JSON feeds and from the PSD/geosci MixItUp + Booth
listings; records there ship as linked, keyworded cold-email targets, like the
UW Arts & Sciences departments.

Single source ("uchicago_faculty") across all departments (the UIUC model); the
department rides on each record's ``department`` field, and ids are namespaced
by department short-code so they never collide. Audience "unknown" (per-prof
openness).
"""

from __future__ import annotations

from .. import faculty_graph


# The four PSD departments (Statistics, Mathematics, Physics, Astronomy) share
# one custom-CMS "MixItUp" directory: a single server-rendered <li class="mix
# <role>"> list per site, filtered client-side. The role classes differ per
# site (math isolates ladder faculty as "professors"; the others mix ranks
# inside "faculty"), so the card selector and title filter are parameters.
def _psd(short: str, name: str, majors: list[str], url: str, *,
         card: str = "li.mix.faculty", ladder_filter: dict | None = None) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": card,
                                     "name": ".people_content h3 span",
                                     "link": "a",
                                     "title": ".people_content h3 b"},
                       # The MixItUp listing cards carry no email; each professor's
                       # profile page keeps a personal mailto. Backfill it via the
                       # gated per-profile pass (OFE_ENRICH_PROFILES=1 for the
                       # one-shot generation run; off in weekly CI, where the
                       # already-enriched emails carry forward through the merge).
                       "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                          "throttle": 0.75},
                       **({"ladder_filter": ladder_filter} if ladder_filter else {})}}


# Economics and Psychology share the university's Drupal Views directory theme:
# paginated ?page=N views with emailed, interest-tagged cards. Emeriti mix into
# the Economics view (Psychology keeps them on a separate URL); one drop rule
# covers both.
def _views(short: str, name: str, majors: list[str], url: str, *,
           max_pages: int) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": "div.views-row",
                                     "name": "h2.no-tags > a",
                                     "link": "h2.no-tags > a",
                                     "title": "div.bio-subtitle",
                                     "email": "div.bio-email a",
                                     "research": "div.bio-interest"},
                       "paginate": {"param": "page", "start": 1, "max": max_pages},
                       "ladder_filter": {"drop": r"emerit"}}}


# Humanities/arts teaching-track ranks that a ladder cold-email directory should
# drop. Ladder titles (Assistant/Associate/full/named/endowed Professor) never
# contain these tokens; instructional/teaching-track ones do — so a keyword drop
# separates them cleanly on the Family-B profile-tile pages, which mix roles.
_HUM_DROP = (r"instructional professor|lecturer|teaching fellow|research associate"
             r"|research professor|emerit|postdoctoral|harper-schmidt"
             r"|collegiate assistant professor|of practice|of the practice"
             r"|\binstructor\b|exchange|visiting")


# The Humanities Division uses a SECOND Drupal Views variant ("profile-tile"):
# tiles carry the name in ``h2.info > a > span`` and use ``field--name-field-*``
# divs for title/email, with no research field. These pages are single-page (no
# pagination) and mix ladder with instructional/visiting/teaching-fellow roles,
# so a ladder_filter (or a section slice for the sectioned Philosophy page) is
# mandatory, unlike the ladder-clean Family-A faculty views. A few pages carry no
# listing email (TAPS) -> gated per-profile mailto backfill.
def _tile(short: str, name: str, majors: list[str], url: str, *,
          ladder_filter: dict | None = None, section_filter: dict | None = None,
          profile_enrich: dict | None = None) -> dict:
    scrape = {"url": url,
              "selectors": {"card": "div.views-row",
                            "name": "h2.info > a > span",
                            "link": "h2.info > a",
                            "title": "div.field--name-field-person-faculty-title",
                            "email": "div.field--name-field-person-email > a"}}
    if ladder_filter:
        scrape["ladder_filter"] = ladder_filter
    if section_filter:
        scrape["section_filter"] = section_filter
    if profile_enrich:
        scrape["profile_enrich"] = profile_enrich
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}



# The eight BSD basic-science departments share one roster endpoint
# (bsd-data.prod.uchicago.edu) that gates on a same-origin Referer and lists
# every joint appointment in each record's ``department`` array. Keying on
# department[0] (the PRIMARY appointment) keeps a cross-listed professor in one
# home department; the stable profiles.uchicago.edu "Research Network Profile"
# link is used because the per-dept microsite hosts aren't all resolvable. No
# email in the feed; chairs carry the literal title "Chair" so the rank filter
# is drop-only.
def _bsd(short: str, name: str, majors: list[str], dept_string: str, host: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": host,
            "json_dir": {
                "url": "https://bsd-data.prod.uchicago.edu/api/faculty_index",
                "headers": {"Referer": host.rstrip("/") + "/"},
                "records_key": "data",
                "name_fields": ["firstName", "middleName", "lastName"],
                "title_field": "title",
                "filter_field": "department", "filter_index": 0, "filter_value": dept_string,
                "research_field": "interests[]",
                "link_list": {"field": "websites", "match_key": "name",
                              "match_value": "Research Network Profile", "url_key": "url"},
                "ladder_filter": {"drop": r"emerit|adjunct|research (assist|assoc)|instructor|lecturer"},
            }}

SCHOOL: dict = {
    "school_slug": "uchicago",
    "source": "uchicago_faculty",
    "organization": "University of Chicago",
    "location": "Chicago, IL",
    "id_prefix": "uchicago",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Chicago) -- work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CS",
            "name": "Department of Computer Science",
            "majors": ["Computer Science", "Data Science"],
            "directory_url": "https://cs.uchicago.edu/people/uchicago-faculty/full-time-faculty/",
            "scrape": {
                "url": "https://cs.uchicago.edu/people/uchicago-faculty/full-time-faculty/",
                "selectors": {
                    "card": "div.card.card--person",
                    "name": "h3.card__title",
                    "link": "a.card__url",
                    "title": "div.card__position",
                },
                "ladder_filter": {
                    "require": r"professor",
                    "drop": r"emerit|clinical|instructional|research (assistant|associate) professor|masters",
                },
                # The listing carries name/title only; each profile keeps a
                # "<strong>Focus Areas:</strong> <em>A, B</em>" block (gated
                # per-profile enrich, OFE_ENRICH_PROFILES=1).
                "profile_enrich": {
                    "research_html_re": r"Focus Areas?:\s*</strong>\s*<em>(.*?)</em>",
                    "throttle": 1.0,
                },
            },
        },
        _psd("STAT", "Department of Statistics",
             ["Statistics", "Data Science", "Computational and Applied Mathematics"],
             "https://stat.uchicago.edu/people/",
             ladder_filter={"require": r"professor",
                            "drop": r"emerit|instructional|part-time|visiting|lecturer"}),
        _psd("MATH", "Department of Mathematics",
             ["Mathematics", "Computational and Applied Mathematics"],
             "https://mathematics.uchicago.edu/people/",
             # ladder faculty already isolated by the "professors" role class;
             # instructional/visiting/Dickson instructors carry other classes.
             card="li.mix.professors",
             ladder_filter={"drop": r"emerit"}),
        _psd("PHYS", "Department of Physics",
             ["Physics", "Astrophysics"],
             "https://physics.uchicago.edu/people/",
             ladder_filter={"require": r"professor",
                            "drop": r"emerit|lecturer|instructional|research professor|part-time|scientist|visiting"}),
        _psd("ASTRO", "Department of Astronomy and Astrophysics",
             ["Astrophysics", "Physics"],
             "https://astrophysics.uchicago.edu/people/",
             # the site splits research-faculty/emeriti into their own role
             # classes; within "faculty" the chair/deputy-chair titles carry no
             # "Professor" word, so drop-only.
             ladder_filter={"drop": r"emerit|research professor|lecturer|instructional|part-time|scientist|visiting|postdoc"}),
        _views("ECON", "Kenneth C. Griffin Department of Economics",
               ["Economics"],
               "https://economics.uchicago.edu/people/faculty", max_pages=6),
        _views("PSYCH", "Department of Psychology",
               ["Psychology"],
               "https://psychology.uchicago.edu/people/faculty", max_pages=5),
        # Social Sciences Division — same Family-A bio-* Drupal Views as Econ/
        # Psych. Each dept's /people/faculty view is ladder-clean (emeriti live
        # on a separate page), so the drop-emerit in _views is just a safety net.
        _views("SOC", "Department of Sociology", ["Sociology"],
               "https://sociology.uchicago.edu/people/faculty", max_pages=3),
        _views("POLISCI", "Department of Political Science", ["Political Science"],
               "https://political-science.uchicago.edu/people/faculty", max_pages=4),
        _views("HIST", "Department of History", ["History"],
               "https://history.uchicago.edu/people/faculty", max_pages=5),
        # Anthropology's path is capitalized — the server 403s /people/faculty
        # and redirects /people/faculty -> /People/Faculty.
        _views("ANTHRO", "Department of Anthropology", ["Anthropology"],
               "https://anthropology.uchicago.edu/People/Faculty", max_pages=3),
        _views("HDEV", "Department of Comparative Human Development",
               ["Comparative Human Development"],
               "https://humdev.uchicago.edu/people/faculty", max_pages=3),
        # Humanities Division — Family-B profile-tile. Philosophy is sectioned
        # (slice the Core Faculty group); English + Linguistics are flat lists
        # mixing instructional/visiting/teaching-fellow roles, gated by title.
        _tile("PHIL", "Department of Philosophy", ["Philosophy"],
              "https://philosophy.uchicago.edu/people/profiles",
              section_filter={"heading": "h3", "include": r"core faculty"},
              ladder_filter={"drop": r"emerit|instructional|visiting|lecturer"}),
        _tile("ENGL", "Department of English Language and Literature",
              ["English Language and Literature", "Creative Writing"],
              "https://english.uchicago.edu/people/faculty-and-lecturers",
              # exclude on the literal "Collegiate Assistant Professor" (a
              # Harper-Schmidt fellowship), not bare "Collegiate" — else a real
              # Associate Professor in the Humanities Collegiate Division drops.
              ladder_filter={"require": r"\bprofessor\b",
                             "drop": r"instructional|visiting|collegiate assistant professor"
                                     r"|teaching fellow|harper-schmidt|advisor|postdoc|emerit"}),
        _tile("LING", "Department of Linguistics", ["Linguistics"],
              "https://linguistics.uchicago.edu/people/profiles",
              ladder_filter={"drop": r"instructional|teaching fellow|postdoc|emerit"}),
        # Remaining Arts & Humanities Division — all Family-B profile-tile, all
        # single-page, all mixing instructional/teaching-fellow roles, so the
        # shared _HUM_DROP title filter isolates ladder faculty. Each page's
        # canonical path differs (verified Jul 2026); EALC's ladder roster lives
        # at /people/core-faculty, Slavic's at the combined faculty+instructional
        # page, RLL/Classics/Music/TAPS at /people/faculty(-lecturers). Germanic
        # Studies is deferred (unreachable from the collection network — a proxy
        # TLS failure, not a bot wall; re-probe and add as a sibling _tile).
        _tile("CLAS", "Department of Classics", ["Classical Studies"],
              "https://classics.uchicago.edu/people/faculty",
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        _tile("CMLT", "Department of Comparative Literature", ["Comparative Literature"],
              "https://complit.uchicago.edu/people/profiles",
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        _tile("EALC", "Department of East Asian Languages and Civilizations",
              ["East Asian Languages and Civilizations"],
              "https://ealc.uchicago.edu/people/core-faculty",
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        _tile("RLL", "Department of Romance Languages and Literatures",
              ["Romance Languages and Literatures"],
              "https://rll.uchicago.edu/people/faculty",
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        _tile("SLAV", "Department of Slavic Languages and Literatures",
              ["Russian and East European Studies"],
              "https://slavic.uchicago.edu/people/faculty-instructional-professors",
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        _tile("SALC", "Department of South Asian Languages and Civilizations",
              ["South Asian Languages and Civilizations"],
              "https://salc.uchicago.edu/people/profiles",
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        _tile("CMS", "Department of Cinema and Media Studies",
              ["Cinema and Media Studies", "Media Arts and Design"],
              "https://cms.uchicago.edu/people/profiles",
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        _tile("MUSI", "Department of Music", ["Music"],
              "https://music.uchicago.edu/people/faculty-lecturers",
              # emeriti are mixed into this listing (unlike the other Family-B
              # pages), so the _HUM_DROP emerit token is load-bearing here.
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        _tile("TAPS", "Department of Theater and Performance Studies",
              ["Theater and Performance Studies"],
              "https://taps.uchicago.edu/people/faculty-lecturers",
              # TAPS lists no email (mostly cross-appointed faculty) — ship as
              # linked cold-email targets rather than pay the fragile per-profile
              # backfill (its enrich pass rate-limited the shared uchicago.edu
              # host and corrupted sibling listings in the batch run).
              ladder_filter={"require": r"\bprofessor\b", "drop": _HUM_DROP}),
        # Art History uses a "photo-tile" view: rank isn't on the listing (so no
        # ladder_filter — the page is already the faculty roster, emeriti
        # separate), and the name is a nested field span. Email is only on the
        # profile page; shipped as a linked target (no per-profile backfill).
        {
            "short": "ARTH",
            "name": "Department of Art History",
            "majors": ["Art History", "Visual Arts"],
            "directory_url": "https://arthistory.uchicago.edu/faculty/faculty-profiles",
            "scrape": {
                "url": "https://arthistory.uchicago.edu/faculty/faculty-profiles",
                "selectors": {"card": "article.node--view-mode-photo-tile",
                              "name": "span.person-name a span.field--name-title",
                              "link": "span.person-name a",
                              "research": "span.person-field",
                              "email": "a[href^='mailto:' i]"},
            },
        },
        # Visual Arts (DoVA) uses an "academic-profiles" section-grouped view:
        # name-only rows under <h3> role headings (Faculty / Lecturers /
        # Associate Faculty / Teaching Fellows / Emeritus). section_filter keeps
        # ONLY the exact "Faculty" heading (^faculty$ so "Associate Faculty" and
        # "Visual Arts Teaching Fellows" don't leak in); no listing rank/email,
        # shipped as linked targets.
        {
            "short": "DOVA",
            "name": "Department of Visual Arts",
            "majors": ["Visual Arts", "Media Arts and Design"],
            "directory_url": "https://dova.uchicago.edu/people/faculty",
            "scrape": {
                "url": "https://dova.uchicago.edu/people/faculty",
                "selectors": {"card": "div.views-field-title",
                              "name": "span.field-content a",
                              "link": "span.field-content a"},
                "section_filter": {"heading": "h3", "include": r"^faculty$"},
            },
        },
        # Physical Sciences — Geophysical Sciences is a MixItUp variant with a
        # different inner markup than the Stat/Math/Physics/Astro sites (no
        # people_content wrapper); the listing carries no email.
        {
            "short": "GEOS",
            "name": "Department of the Geophysical Sciences",
            "majors": ["Geophysical Sciences", "Environmental Science", "Climate and Sustainable Growth"],
            "directory_url": "https://geosci.uchicago.edu/people/",
            "scrape": {
                "url": "https://geosci.uchicago.edu/people/",
                "selectors": {"card": "li.mix.academic-faculty",
                              "name": "h2 > a", "link": "h2 > a",
                              "title": "h2 > small",
                              "research": "dl > dd"},
                "ladder_filter": {"drop": r"emerit"},
            },
        },
        # Professional schools. Each has its own directory theme; Booth is
        # deliberately omitted (a JS-only Coveo search with no scrapable feed).
        {
            "short": "HARRIS",
            "name": "Harris School of Public Policy",
            "majors": ["Public Policy Studies", "Economics"],
            "directory_url": "https://harris.uchicago.edu/directory",
            "scrape": {
                "url": "https://harris.uchicago.edu/directory",
                "selectors": {"card": "article.teaser-table--profile",
                              "name": "h2.teaser-table--title a",
                              "link": "h2.teaser-table--title a",
                              "title": "div.teaser-table--job-title .field__item",
                              "email": "div.teaser-table--link a[href^='mailto:' i]"},
                # the directory mixes Faculty / Lecturer / PhD Student / Staff /
                # Visiting Academic as a per-card profile-type; keep Faculty, then
                # require "professor" to drop the Research Associates within it.
                "field_filter": {"selector": "div.teaser-table--profile-type", "include": r"Faculty"},
                "ladder_filter": {"require": r"professor", "drop": r"emerit|visiting|lecturer"},
                "paginate": {"param": "page", "start": 1, "max": 4},
            },
        },
        {
            "short": "LAW",
            "name": "University of Chicago Law School",
            "majors": ["Law, Letters, and Society"],
            # profile_type=103 is the Full-Time Teaching Faculty view; the title
            # filter drops the clinical/practice/visiting ranks mixed into it.
            "directory_url": "https://www.law.uchicago.edu/directory?profile_type=103",
            "scrape": {
                "url": "https://www.law.uchicago.edu/directory?profile_type=103",
                "selectors": {"card": "li.profile-list__item",
                              "name": ".profile-list--item__name a span",
                              "link": ".profile-list--item__name a",
                              "title": ".profile-list--item__job-title",
                              "email": ".profile-list--item__contact a[href^='mailto:' i]"},
                "ladder_filter": {"require": r"professor",
                                  "drop": r"emerit|visiting|lecturer|clinical|from practice|of practice|fellow|director"},
                "paginate": {"param": "page", "start": 1, "max": 5},
            },
        },
        {
            "short": "CROWN",
            "name": "Crown Family School of Social Work, Policy, and Practice",
            "majors": ["Public Policy Studies"],
            # /research-faculty/faculty-directory, NOT /directory (which mixes
            # staff, doctoral students, and centers). Emails use a capital-T
            # "mailTo:" scheme the engine's _clean_email regex still recovers.
            "directory_url": "https://crownschool.uchicago.edu/research-faculty/faculty-directory",
            "scrape": {
                "url": "https://crownschool.uchicago.edu/research-faculty/faculty-directory",
                "selectors": {"card": "article.node--type-person.node--view-mode-card",
                              "name": "h3.person-name a",
                              "link": "h3.person-name a",
                              "title": "span.person-title",
                              "email": ".card-details a[href^='mailto:' i]"},
                "ladder_filter": {"require": r"professor", "drop": r"emerit|lecturer|instructional"},
                "paginate": {"param": "page", "start": 1, "max": 3},
            },
        },
        {
            "short": "DIV",
            "name": "University of Chicago Divinity School",
            "majors": ["Religious Studies"],
            # Faceted PATH URL selects the "faculty" role (emeritus/visiting/
            # associated/teaching-fellows live under sibling path segments). The
            # listing carries no email; the per-profile pass (gated) backfills it.
            "directory_url": "https://divinity.uchicago.edu/directory/all/faculty/all/all",
            "scrape": {
                "url": "https://divinity.uchicago.edu/directory/all/faculty/all/all",
                "selectors": {"card": "div.faculty-detail-section",
                              "name": "h5.name-faculty",
                              "link": "a[href^='/directory/']",
                              "title": "h5.name-faculty + span"},
                "ladder_filter": {"require": r"professor", "drop": r"emerit|visiting|lecturer|instructional|fellow"},
                "paginate": {"param": "page", "start": 1, "max": 5},
                "profile_enrich": {"email_selector": "a[href^='mailto:' i]", "throttle": 0.75},
            },
        },
        {
            "short": "PME",
            "name": "Pritzker School of Molecular Engineering",
            "majors": ["Molecular Engineering"],
            "directory_url": "https://pme.uchicago.edu/faculty-research/faculty-directory",
            "scrape": {
                "url": "https://pme.uchicago.edu/faculty-research/faculty-directory",
                "selectors": {
                    "card": "div.card-spotlight.node--type-faculty",
                    "name": "a.card-spotlight__title",
                    "link": "a.card-spotlight__title",
                    "title": "div.card-spotlight__position",
                    "email": "div.card-spotlight__email a[href^='mailto:']",
                    # scholarly-interest taxonomy spans; the .eyebrow child is
                    # the "Research & Scholarly Interests" label, not a topic.
                    "research_items": "div.card-spotlight__research-scholar-intrest span:not(.eyebrow)",
                },
                "ladder_filter": {"drop": r"emerit"},
            },
        },
        {
            "short": "CHEM",
            "name": "Department of Chemistry",
            "majors": ["Chemistry", "Biological Chemistry"],
            "directory_url": "https://chemistry.uchicago.edu/faculty",
            # Live: the directory page is a JS shell over this Pantheon API
            # (fullName + relative pathAlias + interests[]); no email in the feed.
            "json_dir": {
                "url": "https://live-ucchem.pantheonsite.io/api/faculty_index",
                "name_fields": ["fullName"],
                "title_field": "title",
                "link_field": "pathAlias",
                "link_base": "https://chemistry.uchicago.edu",
                "research_field": "interests[]",
                "ladder_filter": {"drop": r"emerit|adjunct|research (assist|assoc)"},
            },
        },
        _bsd("ECEV", "Department of Ecology and Evolution",
             ["Biological Sciences", "Environmental Science"],
             "Ecology and Evolution", "https://ecologyandevolution.uchicago.edu"),
        _bsd("NEURO", "Department of Neurobiology",
             ["Neuroscience", "Biological Sciences"],
             "Neurobiology", "https://neurobiology.uchicago.edu"),
        _bsd("HG", "Department of Human Genetics", ["Biological Sciences"],
             "Human Genetics", "https://genes.uchicago.edu"),
        _bsd("MGCB", "Department of Molecular Genetics and Cell Biology",
             ["Biological Sciences"],
             "Molecular Genetics and Cell Biology", "https://mgcb.uchicago.edu"),
        _bsd("BMB", "Department of Biochemistry and Molecular Biology",
             ["Biological Chemistry", "Biological Sciences", "Chemistry"],
             "Biochemistry and Molecular Biology", "https://biochem.uchicago.edu"),
        _bsd("OBA", "Department of Organismal Biology and Anatomy",
             ["Biological Sciences", "Neuroscience"],
             "Organismal Biology and Anatomy", "https://biologicalsciences.uchicago.edu"),
        _bsd("PBHS", "Department of Public Health Sciences",
             ["Public Policy Studies", "Data Science", "Statistics"],
             "Public Health Sciences", "https://publichealth.bsd.uchicago.edu"),
        _bsd("MICRO", "Department of Microbiology", ["Biological Sciences"],
             "Microbiology", "https://microbiology.uchicago.edu"),
        {
            "short": "BOOTH",
            "name": "University of Chicago Booth School of Business",
            # Booth is a graduate/MBA school (no College major) but its
            # economics/finance/econometrics faculty are cold-email research
            # targets for Economics / Public Policy / Data Science undergrads.
            "majors": ["Economics", "Public Policy Studies", "Data Science"],
            "directory_url": "https://www.chicagobooth.edu/faculty/directory",
            "scrape": {
                "url": "https://www.chicagobooth.edu/faculty/directory",
                # Client-side Coveo search: no faculty in the server HTML, but a
                # headless browser renders the A-Z roster as folding-child cards.
                # render_wait="networkidle" waits for Coveo's XHRs to finish (a
                # fixed settle grabbed 0 cards on a slow load). No listing email.
                "render": True, "render_wait": "networkidle",
                "selectors": {"card": "article.coveo-normal-child-result",
                              "name": "div.copy h2 a", "link": "div.copy h2 a",
                              "title": "div.swiss-text p", "research_items": "div.details span"},
                # ~272 cards render; keep ladder ranks (drops adjunct/clinical/
                # visiting/emeritus/teaching/lecturer/fellows).
                "ladder_filter": {"require": r"professor",
                                  "drop": r"adjunct|visiting|emerit|clinical|of practice"
                                          r"|from practice|teaching|distinguished fellow|lecturer"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
