"""Stony Brook University faculty config (via the faculty_graph engine).

No WAF anywhere — every directory is server-rendered and fetchable with a
plain request (quirk: some /commcms/ paths 403 when a trailing slash is
APPENDED, so URLs are kept exactly as verified). Nine markup families across
29 departments, all selectors live-verified 2026-07-18:

* New OmniUpdate "dept-faculty-directory" theme (11 CAS/CEAS depts: AMS,
  Physics, Psychology, EcoEvo, Biochem, Neurobiology, Sociology, English,
  History, Philosophy, Anthropology). Cards carry name/profile-link/title AND
  a plain mailto on the listing, so no profile pass is needed. Grids are
  role-grouped: where ``h3.dept-faculty-directory__group-title`` headings
  exist (Physics ranks, Psychology areas, Sociology/History/Philosophy roles)
  a ``section_filter`` keeps the faculty grids; heading-less pages (AMS,
  Neurobiology, Biochem, English, Anthropology) are gated purely by the
  title-regex ladder. The ``__department`` tag is a clean research line on
  Physics (group tags), EcoEvo, English and Anthropology — wired as
  ``research`` there; elsewhere it is the unit name (skipped). Psychology
  cards carry NO title element (records default to "Professor"; its area
  grids are already faculty-only).

* Legacy commcms "person-wrapper" listing (ECE, BME, MatSci, MechEng,
  Linguistics). Name, title (td.item-title) and mailto all on the listing.
  ECE research rides ``td.item-extra``; Linguistics nests rank/degree/
  research inside ``.views-field-value-5`` divs. ECE groups its 6 role tabs
  as ``li.tab`` whose first text node is the label — a ``section_filter`` on
  ``li`` keeps Core + Research Faculty. ECE names are "Last, First"
  (name_flip), ME too, and ME/LIN titles carry a degree tail
  (title_strip_after). ECE "View More" profile links point at a broken
  _old/2024 path (HTTP 500) — listing-only, records keep the directory URL.

* cs.stonybrook.edu Drupal (CS): Bootstrap tab-panes by faculty type — the
  card selector unions ``#nav-core`` + ``#nav-research`` (affiliated/
  emeritus/memoriam panes never parsed). Clean per-field classes incl. a
  comma keyword list on the listing; profile emails are Drupal spamspan
  ("user [at] cs.stonybrook.edu") which the engine's at/dot normalization
  decodes — profile_enrich email pass.

* commcms "bio-list" (EST, Geosciences, Political Science, WGSS):
  ``li.equal-height-col`` cards with ``a.name`` and rank in the first
  ``.bio span.title``/``span.summary-1``. EST/Geo carry a clean
  ``.summary-2`` research line; PolSci's summary-2 is office+mailto (wired
  as the email selector instead); WGSS research is skipped — its first
  letter is wrapped in a display span ("F eminist theory") which would ship
  a corrupt keyword.

* Chemistry section pages (faculty_sections/Core%20Faculty): simple col-3
  cards, name link → faculty_profiles/*.php, rank in a styled span. No
  research on listing and profile research is prose (poison) — mailto-only
  profile_enrich.

* SoMAS "div.person" (Marine Sciences, Atmospheric Sciences, Sustainability
  divisions): name/title/italic research line/mailto all on the listing;
  name links open researchconnect.stonybrook.edu (Elsevier Pure) person
  pages — a future keyword-enrichment path like Illinois Experts.

* Civil Engineering one-off: hand-rolled inline-styled flex cards inside
  ``main.sbu-dept-main``; h3>a name → core-faculty-profiles/*.html, first
  <p> is the rank. Mailto on profiles → profile_enrich.

* Economics faculty.php: one <p> per person holding the _bios/ name link,
  rank, degree and a labelled "Research Interests:" keyword line —
  ``title_re`` + ``research_re_text`` extract from the block text.

* Math's hand-rolled table (math.stonybrook.edu/faculty): one
  paper-noise-styled div per person, name in <big>, everything else one
  text blob in the details td — ``title_strip_after`` cuts the rank ahead
  of the "Ph.D. in YYYY"/"Arrived at"/"Office:" tail, mailto on the
  listing, research via a bounded "Research Interests:" text regex.

* College of Business: one Digital-Measures-generated ``table.tablesaw``
  (First | Last | Title | Department | profile link). NO individual emails
  published anywhere (profiles show only the shared college inbox) and no
  research — name/title records, Title-column ladder gate.

Single source ("sbu_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred (from the 2026-07-18 recon):
* Renaissance School of Medicine + School of Dental Medicine — large
  clinical schools with per-dept subsites, not probed (big med = defer).
* Schools of Nursing / Health Professions / Social Welfare — /commcms slugs
  404; directories live in a separate health-sciences IA, not located.
* Pharmacological Sciences — guessed slugs 404 (likely under RSOM).
* School of Communication and Journalism — fac-staff stub has zero
  server-rendered faculty; /commcms/journalism/people/faculty returns 500.
* Music — bare link list (~137 mixed faculty/staff links, no titles);
  Art — one-off tab markup with name+title+email concatenated; Theatre
  Arts / Africana Studies / Asian & Asian American Studies / Hispanic — no
  parseable directory found (403/404/prose only).
* Chemistry non-core sections — faculty_sections/<Group> URL scheme exists
  but other group names not enumerated; Core Faculty (37) verified.
* Laufer Center — laufercenter.stonybrook.edu 403s curl.
* BME program faculty (program.php, joint appointments) — core.php only.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- New OmniUpdate "dept-faculty-directory" theme -------------------------
_DEPTDIR_SELECTORS = {
    "card": "article.dept-faculty-directory__card",
    "name": "span.dept-faculty-directory__name",
    "link": "a.dept-faculty-directory__profile-link",
    "title": "p.dept-faculty-directory__title",
    "email": "a.dept-faculty-directory__contact-link--email",
}

# Titled ladder gate for role-mixed grids: keep professorial ranks, lecturers
# and chairs; drop emeriti/adjunct/visiting/affiliates/instructional staff.
# Staff and student cards fail the require side (admin/coordinator/PhD titles).
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b|\bchair\b",
    "drop": r"emerit|adjunct|visiting|affiliat|in memoriam|instructional",
}

# Rosters that are already faculty-only (role-scoped page/tab/section): keep
# everyone except emeriti/adjunct stragglers.
_LADDER_LIGHT = {"drop": r"emerit|adjunct|visiting|affiliat|in memoriam"}

# Shared mailto profile pass for families whose listing has no email (a
# handful of profile fetches per dept; OFE_ENRICH_PROFILES-gated).
_MAILTO_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^[^@]*$|info@|department@|admin@|office@|collegeofbusiness@",
    "throttle": 0.2,
}


def _deptdir(short: str, name: str, majors: list[str], url: str, *,
             section: dict | None = None, research: bool = False,
             ladder: dict = _LADDER, enrich: bool = False) -> dict:
    """A department on the new dept-faculty-directory theme.

    ``enrich`` turns on the mailto profile pass for the three depts whose
    LISTING cards omit the contact link (English, Biochem, Neurobiology) —
    their profile pages publish a clean personal mailto (verified live).
    """
    sel = dict(_DEPTDIR_SELECTORS)
    if research:
        # Physics/EcoEvo/English/Anthropology fill the __department tag with a
        # research-group/areas line (elsewhere it's the unit name — skipped).
        sel["research"] = "p.dept-faculty-directory__department"
    scrape: dict = {"url": url, "selectors": sel, "ladder_filter": ladder}
    if section:
        scrape["section_filter"] = {"heading": "h3", **section}
    if enrich:
        scrape["profile_enrich"] = _MAILTO_ENRICH
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# ---- Legacy commcms "person-wrapper" family --------------------------------
_COMMCMS_SELECTORS = {
    "card": "div.person-wrapper",
    "name": ".data p strong",
    "title": "td.item-title",
    "email": ".data a[href^='mailto:']",
}


def _commcms(short: str, name: str, majors: list[str], url: str,
             **scrape_extra) -> dict:
    """A core-faculty page on the legacy commcms person-wrapper markup.

    No link selector: only ECE exposes profile links and they 500 — records
    key on the listing mailto and point at the directory.
    """
    sel = {**_COMMCMS_SELECTORS, **scrape_extra.pop("selectors", {})}
    scrape = {"url": url, "selectors": sel, "ladder_filter": _LADDER_LIGHT,
              **scrape_extra}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# ---- commcms "bio-list" family (est/geosciences/polisci/wgss) --------------
# Rank lives in span.title (geo) or the first span.summary-1 (est/pol/wgss);
# the grouped selector returns whichever comes first in the card.
_BIO_SELECTORS = {
    "card": "li.equal-height-col",
    "name": "a.name",
    "name_strip": r"^\s*Dr\.?\s+",
    "link": "a.name",
    "title": ".bio span.title, .bio span.summary-1",
}


def _bio(short: str, name: str, majors: list[str], url: str, *,
         research: bool = True, listing_email: bool = False) -> dict:
    """A department on the commcms bio-list markup."""
    sel = dict(_BIO_SELECTORS)
    if research:
        sel["research"] = ".bio .summary-2"
    if listing_email:
        # PolSci's summary-2 is office + mailto, not research.
        sel["email"] = ".bio .summary-2 a[href^='mailto:']"
    scrape: dict = {"url": url, "selectors": sel, "ladder_filter": _LADDER_LIGHT}
    if not listing_email:
        scrape["profile_enrich"] = _MAILTO_ENRICH
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# ---- SoMAS "div.person" family ---------------------------------------------
# Marine Sciences wraps the name in .peoplename, Atmospheric Sciences in
# .peoplephoto, and Sustainability in a CLASSLESS div — but the name link is
# always the strong-wrapped researchconnect (Elsevier Pure) anchor.
_SOMAS_SELECTORS = {
    "card": "div.person",
    "name": ".peoplename, .peoplephoto, strong a[href*='researchconnect']",
    "link": ".peoplename a, .peoplephoto a, strong a[href*='researchconnect']",
    "title": ".jobtitle",
    "email": ".peopleemail a[href^='mailto:']",
    "research": ".research em",
}


def _somas(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A SoMAS division people page (profile links = researchconnect Pure)."""
    url = f"https://www.stonybrook.edu/{slug}/people.html"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _SOMAS_SELECTORS,
                       "ladder_filter": {
                           "require": r"\bprofessor\b|\blecturer\b|\bchair\b",
                           "drop": r"emerit|adjunct|visiting|scientist",
                       }}}


_CS_URL = "https://www.cs.stonybrook.edu/people/faculty"
_ECE_URL = "https://www.stonybrook.edu/commcms/electrical/people/faculty"
_CHEM_URL = ("https://www.stonybrook.edu/commcms/chemistry/people/"
             "faculty_sections/Core%20Faculty")
_CIV_URL = "https://www.stonybrook.edu/civileng/faculty/core-faculty.html"
_ECON_URL = "https://www.stonybrook.edu/commcms/economics/people/faculty.php"
_MATH_URL = "https://www.math.stonybrook.edu/faculty"
_BUS_URL = "https://www.stonybrook.edu/commcms/business/about/_faculty/"

SCHOOL: dict = {
    "school_slug": "sbu",
    "source": "sbu_faculty",
    "organization": "Stony Brook University",
    "location": "Stony Brook, NY",
    "id_prefix": "sbu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Stony Brook University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering and Applied Sciences --------------------
        {
            "short": "CS", "name": "Department of Computer Science",
            "majors": ["Computer Science"],
            "directory_url": _CS_URL,
            "scrape": {
                "url": _CS_URL,
                # Tab-panes by faculty type: core + research kept; affiliated/
                # emeritus/memoriam panes are never selected.
                "selectors": {
                    "card": "#nav-core div.card, #nav-research div.card",
                    "name": "p.faculty-name-field a",
                    "link": "p.faculty-name-field a",
                    "title": "p.faculty-jobtitle-field",
                    "research": "p.faculty-interests-field",
                },
                "ladder_filter": _LADDER_LIGHT,
                # Profile emails are Drupal spamspan text ("boyd [at]
                # cs.stonybrook.edu") — _clean_email's at/dot fold decodes.
                "profile_enrich": {**_MAILTO_ENRICH,
                                   "email_selector": "span.spamspan"},
            },
        },
        _commcms("ECE", "Department of Electrical and Computer Engineering",
                 ["Electrical Engineering", "Computer Engineering"], _ECE_URL,
                 selectors={"research": "td.item-extra"},
                 name_flip=True,
                 # Role tabs are li.tab whose first text node is the label —
                 # the nearest previous <li> of every card is its own tab.
                 section_filter={"heading": "li",
                                 "include": r"^(?:core|research)\s+faculty\b"}),
        _deptdir("AMS", "Department of Applied Mathematics and Statistics",
                 ["Applied Mathematics and Statistics", "Mathematics"],
                 "https://www.stonybrook.edu/ams/faculty/index.html",
                 ladder=_LADDER_LIGHT),
        _commcms("BME", "Department of Biomedical Engineering",
                 ["Biomedical Engineering"],
                 "https://www.stonybrook.edu/commcms/bme/people/core.php"),
        _commcms("MSCE", "Department of Materials Science and Chemical Engineering",
                 ["Materials Science", "Chemical and Molecular Engineering"],
                 "https://www.stonybrook.edu/commcms/matscieng/people/core_faculty.php"),
        _commcms("ME", "Department of Mechanical Engineering",
                 ["Mechanical Engineering"],
                 "https://me.stonybrook.edu/people/index.php",
                 selectors={"title_strip_after": r",?\s*Ph\.?\s?\.?\s?D"},
                 name_flip=True),
        {
            "short": "CIV", "name": "Department of Civil Engineering",
            "majors": ["Civil Engineering"],
            "directory_url": _CIV_URL,
            "scrape": {
                "url": _CIV_URL,
                "selectors": {
                    "card": "main.sbu-dept-main div[style*='flex: 1 1 260px']",
                    "name": "h3 a", "link": "h3 a", "title": "p",
                },
                "ladder_filter": _LADDER_LIGHT,
                "profile_enrich": _MAILTO_ENRICH,
            },
        },
        _bio("EST", "Department of Technology and Society",
             ["Technological Systems Management"],
             "https://www.stonybrook.edu/commcms/est/faculty/core-faculty/index.php"),
        # ---- College of Arts and Sciences -----------------------------------
        _deptdir("PHY", "Department of Physics and Astronomy",
                 ["Physics", "Astronomy"],
                 "https://www.stonybrook.edu/physics/people/faculty-and-staff.html",
                 section={"include": (r"^(?:assistant|associate|distinguished)\s+"
                                      r"professors$|^professors$|^lecturers$")},
                 research=True, ladder=_LADDER_LIGHT),
        {
            "short": "CHEM", "name": "Department of Chemistry",
            "majors": ["Chemistry"],
            "directory_url": _CHEM_URL,
            "scrape": {
                "url": _CHEM_URL,
                "selectors": {
                    "card": ".layout-col.col-3",
                    "name": "a[href*='/people/faculty_profiles/']",
                    "link": "a[href*='/people/faculty_profiles/']",
                    "title": "span[style*='font-size']",
                },
                "ladder_filter": _LADDER_LIGHT,
                "profile_enrich": _MAILTO_ENRICH,
            },
        },
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": _MATH_URL,
            "scrape": {
                "url": _MATH_URL,
                "selectors": {
                    "card": "div[style*='paper-noise']",
                    "name": "big",
                    "link": "a[href*='/~']",
                    # The details td is one text blob starting with the rank —
                    # cut it ahead of the degree/arrival/contact tail.
                    "title": "td:nth-of-type(2)",
                    "title_strip_after": (r"\s*(?:(?:Ph|Ed|Sc)\.?\s?\.?\s?D|"
                                          r"D\.?\s?Phil|M\.A\.|B\.S\.|M\.S\.|"
                                          r"Arrived at|Office:|Email:|Phone:|"
                                          r"Mathematics Genealogy|Zoom)"),
                    "email": "a[href^='mailto:']",
                    "research_re_text": (r"Research Interests:\s*(.+?)"
                                         r"(?:\s*(?:PhD Students|Awards|"
                                         r"Address|Website)\s*:|$)"),
                },
                # "Milnor Lecturer, Institute for Mathematical Sciences" =
                # rotating IMS visitor positions, not permanent faculty.
                "ladder_filter": {
                    "require": r"\bprofessor\b|\blecturer\b",
                    "drop": (r"emerit|visiting|adjunct|postdoc|student"
                             r"|institute for mathematical"),
                },
            },
        },
        _deptdir("PSY", "Department of Psychology",
                 ["Psychology"],
                 "https://www.stonybrook.edu/psychology/people/faculty.html",
                 # Area grids (+ Lecturers) are faculty-only; cards carry no
                 # title element, so the section headings do all the gating.
                 section={"include": (r"^(?:clinical|integrative|cognitive|"
                                      r"social|lecturers)\b")},
                 ladder=_LADDER_LIGHT),
        _deptdir("ANTH", "Department of Anthropology", ["Anthropology"],
                 "https://www.stonybrook.edu/anthropology/faculty-and-staff/",
                 research=True),
        _deptdir("EEB", "Department of Ecology and Evolution",
                 ["Biology", "Ecology and Evolution"],
                 "https://www.stonybrook.edu/ecoevo/people/faculty/",
                 section={"exclude": r"emerit|administration|phd|m\.a\.|postdoc"},
                 research=True, ladder=_LADDER_LIGHT),
        _deptdir("BCB", "Department of Biochemistry and Cell Biology",
                 ["Biochemistry", "Biology"],
                 "https://www.stonybrook.edu/biochem/people.html",
                 enrich=True,
                 # Faculty grids are heading-less; the student/postdoc grids
                 # DO carry group-title headings — excluded belt-and-suspenders
                 # on top of the professorial require gate.
                 section={"exclude": r"phd|master|postdoc|student"}),
        _deptdir("NEU", "Department of Neurobiology and Behavior",
                 ["Biology", "Neuroscience"],
                 "https://www.stonybrook.edu/neurobiology/people/faculty-directory.html",
                 enrich=True),
        {
            "short": "ECON", "name": "Department of Economics",
            "majors": ["Economics"],
            "directory_url": _ECON_URL,
            "scrape": {
                "url": _ECON_URL,
                # One <p> per person holding the _bios/ link; rank + labelled
                # research line extracted from the block text.
                "selectors": {
                    "card": "p",
                    "name": "a[href*='/people/_bios/']",
                    "link": "a[href*='/people/_bios/']",
                    "title_re": (r"\b((?:(?:Distinguished|Associate|Assistant|"
                                 r"Visiting|Adjunct|Research|Teaching)\s+)?"
                                 r"(?:Professor|Lecturer))\b"),
                    "research_re_text": r"Research Interests:\s*(.+)$",
                },
                "ladder_filter": _LADDER_LIGHT,
                "profile_enrich": _MAILTO_ENRICH,
            },
        },
        _deptdir("SOC", "Department of Sociology", ["Sociology"],
                 "https://www.stonybrook.edu/sociology/people/",
                 section={"include": r"^department leadership$|^faculty$"}),
        _deptdir("ENGL", "Department of English", ["English"],
                 "https://www.stonybrook.edu/english/people/",
                 research=True, enrich=True),
        _deptdir("HIST", "Department of History", ["History"],
                 "https://www.stonybrook.edu/history/people/",
                 section={"include": r"^department leadership$|^faculty$"}),
        _deptdir("PHIL", "Department of Philosophy", ["Philosophy"],
                 "https://www.stonybrook.edu/philosophy/people/",
                 section={"include": r"^faculty$|^leadership team$"}),
        _commcms("LIN", "Department of Linguistics", ["Linguistics"],
                 "https://linguistics.stonybrook.edu/people/faculty.php",
                 selectors={
                     # Rank/degree/research are nested views-field divs; the
                     # first inner div is the rank. The research line has no
                     # stable element (spans wrap arbitrary lines, incl. role
                     # lines) — not extracted, records land emailed but broad.
                     "title": ("td.item-title div.views-field-value-5 "
                               "div.views-field-value-5"),
                     "link": ".data a[href*='/faculty/']",
                 }),
        _bio("GEO", "Department of Geosciences", ["Geosciences"],
             "https://www.stonybrook.edu/commcms/geosciences/people/geo-faculty.php"),
        _bio("POL", "Department of Political Science", ["Political Science"],
             "https://www.stonybrook.edu/commcms/polisci/people/faculty.php",
             research=False, listing_email=True),
        _bio("WGSS", "Department of Women's, Gender, and Sexuality Studies",
             ["Women's, Gender, and Sexuality Studies"],
             "https://www.stonybrook.edu/commcms/wgss/people/faculty",
             # summary-2 wraps the first letter in a display span ("F eminist
             # theory") — a corrupt keyword, so research is not extracted.
             research=False),
        # ---- School of Marine and Atmospheric Sciences ----------------------
        _somas("MAR", "Marine Sciences Division (SoMAS)",
               ["Marine Sciences", "Marine Vertebrate Biology"],
               "marine-sciences"),
        _somas("ATM", "Atmospheric Sciences Division (SoMAS)",
               ["Atmospheric and Oceanic Sciences"], "atmospheric-sciences"),
        _somas("SUS", "Sustainability Studies Division (SoMAS)",
               ["Sustainability Studies", "Coastal Environmental Studies"],
               "sustainability-studies"),
        # ---- College of Business --------------------------------------------
        {
            "short": "BUS", "name": "College of Business",
            "majors": ["Business Management", "Accounting", "Finance"],
            "directory_url": _BUS_URL,
            "scrape": {
                "url": _BUS_URL,
                # Digital-Measures table; header row has no <td> so it never
                # yields a name. No individual emails exist anywhere.
                "selectors": {
                    "card": "table.tablesaw tr",
                    "name": "td:nth-of-type(1)",
                    "name_last": "td:nth-of-type(2)",
                    "title": "td:nth-of-type(3)",
                    "link": "td a.view-link",
                },
                "ladder_filter": {
                    "require": r"\bprofessor\b",
                    "drop": r"adjunct|emerit|visiting|lecturer|student",
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
