"""University of Delaware faculty config (via the faculty_graph engine).

Full UIUC-parity coverage across all six colleges. Every roster is a plain-HTTP
200 (no WAF, no JS render needed except where noted), gated to real ladder /
teaching faculty, and majority-emailed. Live-verified 2026-07-24.

Six server-rendered markup families:

* **CIS — Divi column grid** (``www.cis.udel.edu/people/faculty/``). Each
  professor is a ``div.et_pb_column`` card with an ``a.entry-featured-image-url``
  profile link, an ``h2`` name, and ``<p>`` lines (rank / office / phone /
  mailto). Card scoped to columns that hold a faculty link; ladder gate keeps
  professor/endowed-chair ranks.

* **ECE — Divi table, role-sectioned** (``www.ece.udel.edu/people/faculty/``).
  Five ``<table>``s under sibling ``h2`` headings (Primary / Emeritus / Joint /
  Affiliated / Secondary); a ``section_filter`` scopes to the Primary table and
  the ladder gate drops the lone Instructor.

* **Central AEM "Our People"** — the shared ``matrixResultLink`` template on
  ``www.udel.edu/academics/colleges/cas/units/departments/<slug>/our-people/``.
  Serves EVERY College of Arts & Sciences department. Each person is a
  ``div.col-sm-12.col-md-8`` info column with an ``h1`` name and a
  ``.matrixResultTextContent`` block. A ``field_filter`` keeps cards mentioning a
  professor/lecturer/instructor/chair rank anywhere (dropping pure-staff rows even
  when the first line is an administrative role); a ``link_filter`` drops the
  affiliated faculty these pages cross-list from other departments.

* **AEM department "media" cards** — the College of Health Sciences and College
  of Earth, Ocean & Environment department directories at
  ``.../colleges/<chs|ceoe>/departments/<slug>/faculty/``. Each person is a
  ``div.media`` (``h4.media-heading`` name / ``span.media-title`` rank /
  ``div.media-email`` mailto). These pages list faculty AND staff, so a ladder
  gate on the title keeps only professor/instructor/lecturer/chair rows.

* **AEM "callout" cards** — the College of Agriculture & Natural Resources
  department directories at ``.../canr/departments/<slug>/faculty-staff/``. Each
  person is a ``div.callout-carousel-text-image`` (``div.title p`` name /
  ``div.content p`` rank + mailto / ``a.link`` profile). Also mixed faculty+staff,
  same ladder gate.

* **Engineering Divi variants** — each College of Engineering department subdomain
  renders faculty in its own Divi module family: ME (``faculty-grid-item``), CBE
  (``et_pb_team_member`` Team Member module), CCEE (``dmach-grid-item`` Divi
  Machine faculty grid), MSEG / BME (``et_pb_text`` name+mailto grids). CCEE
  (Civil, Construction & Environmental) covers both the Civil and Environmental
  Engineering majors.

Single source ("udel_faculty"); department rides each record, ids namespaced by
department short-code. Joint/cross-listed duplicates collapse on the engine's
email/URL de-dup.

Coverage (2026-07-24): CAS 19 depts · Engineering 7 depts (CIS/ECE/ME/CBE/CCEE/
MSEG/BME) · Health Sciences 7 depts · Earth-Ocean-Environment 3 depts ·
Agriculture & Natural Resources 4 depts.

Dropped / phase-2:
* **Alfred Lerner College of Business & Economics** — the unified
  ``lerner.udel.edu/faculty-and-research/faculty-and-staff-directory/`` is a
  Divi Machine grid loaded entirely via ``admin-ajax.php``; the static HTML
  carries ZERO mailto addresses and no reachable per-department JSON. Needs a
  bespoke admin-ajax action probe or headless render — deferred to phase-2.
* Departments whose ``our-people`` roster is systematically email-light (e.g.
  CAS Theatre & Dance) are dropped by the majority-email gate at runtime.
"""

from __future__ import annotations

from .. import faculty_graph

# Keep ladder + endowed-chair professors; drop the Instructors, Associate
# Instructors, Senior Researchers, and any adjunct/emeritus/visiting the
# directories mix in.
_LADDER = {"require": r"professor|chair", "drop": r"emerit|adjunct|visiting"}

# The AEM "media"/"callout" department directories (CHS/CEOE/CANR) list faculty
# AND staff on one page. Keep any teaching/ladder rank — Professor of every
# grade, plus the Instructor / Associate Instructor / Clinical Instructor and
# Lecturer ranks these applied colleges use — and drop pure staff (Coordinator,
# Administrator, Manager, Specialist) whose title carries none of those words.
_TEACHING = {"require": r"Prof|Instructor|Lecturer|Chair", "drop": r"emerit|adjunct|visiting"}


# --- CIS: Divi column cards -------------------------------------------------
_CIS_SEL = {
    "card": "div.et_pb_column:has(a.entry-featured-image-url)",
    "name": "h2",
    "link": "a.entry-featured-image-url",
    "title": "p",
    "email": "a[href^='mailto:']",
}

# --- ECE: Divi table sliced to the Primary section --------------------------
_ECE_SEL = {
    "card": "table tr",
    "name": "td.column-1 a",
    "link": "td.column-1 a",
    "title": "td.column-2",
    "email": "td.column-4 a[href^='mailto:']",
}

# --- ME: WordPress grid items (primary faculty only) ------------------------
_ME_SEL = {
    "card": "div.faculty-grid-item",
    "name": "span:nth-of-type(1)",
    "link": "a[href*='/faculty/']",
    "title": "span:nth-of-type(2)",
    "title_strip_after": r"\s+\d|\s+\w+\s+(?:Lab|Hall)\b",
    "email": "a[href^='mailto:']",
}

# --- CBE: Divi Team Member module -------------------------------------------
_CBE_SEL = {
    "card": "div.et_pb_team_member",
    "name": "h2.et_pb_module_header",
    "title": "p.et_pb_member_position",
    "email": "a[href^='mailto:']",
}

# --- CCEE: Divi Machine faculty grid ----------------------------------------
_CCEE_SEL = {
    "card": "div.grid-col.dmach-grid-item",
    "name": "h4.entry-title a",
    "link": "h4.entry-title a",
    "title": "p.dmach-acf-value",
    "email": "a.dmach-acf-value[href^='mailto:']",
}

# --- MSEG / BME: Divi text grid (name link + mailto, no rank line) -----------
_ENGR_TEXT_SEL = {
    "card": "div.et_pb_text_inner:has(h4 a)",
    "name": "h4 a",
    "link": "h4 a",
    "email": "a[href^='mailto:']",
}

# --- Central AEM "Our People" (CAS) -----------------------------------------
_AEM_SEL = {
    "card": "div.col-sm-12.col-md-8",
    "name": "h1",
    "link": "a.matrixResultLink",
    "title": ".matrixResultTextContent p:nth-of-type(1) b",
    # Some departments render the address as a mailto anchor, others as plain
    # "Email: name@udel.edu" text; selecting the whole block lets the engine's
    # address-shape regex recover both (a mailto-only selector missed the
    # plain-text departments, e.g. Biological Sciences at 4/37).
    "email": ".matrixResultTextContent",
}

# --- AEM department "media" cards (CHS / CEOE) ------------------------------
_MEDIA_SEL = {
    "card": "div.media",
    "name": "h4.media-heading",
    "title": "span.media-title",
    "email": "div.media-email a[href^='mailto:']",
}

# --- AEM "callout" cards (CANR) ---------------------------------------------
_CALLOUT_SEL = {
    "card": "div.callout-carousel-text-image",
    "name": "div.title p",
    "link": "a.link",
    "title": "div.content p:nth-of-type(1)",
    # Same plain-text-vs-anchor split as the AEM cards: only the chair's address
    # is a mailto, the rest are "Email: name@udel.edu" text — select the block
    # and let the engine's address regex pull it out.
    "email": "div.content",
}


# UDel publishes research under a "Research Areas" / "Research Interests"
# heading on the engineering subdomain profiles (CIS, ME, CCEE, MSEG, BME all
# hit); the central AEM pages carry the same words only in their left-nav rail,
# which the engine's menu guard now refuses. Measured on the real production
# path, four profiles per department: CIS 4/4, ME 4/4, CCEE 4/4, BME 4/4,
# MSEG 2/4, and 0/4 for ECE, CBE, PHYS, CHEM.
#
# Attached to every helper rather than only the ones that hit. Four samples
# cannot tell 0% from 15%, and the visit earns a professor-tracking baseline
# (metadata.verification_scope == "profile") whether or not research comes
# back — udel had 999 faculty and zero of both. No ``always``, so it runs in
# the monthly OFE_ENRICH_PROFILES window.
_ENRICH = {
    "research_label_re": faculty_graph.RESEARCH_LABEL_RE,
    "throttle": 0.15,
}


def _aem(short: str, name: str, majors: list[str], dept_path: str) -> dict:
    """A CAS department on the shared central-udel.edu AEM "Our People" page."""
    url = (f"https://www.udel.edu/academics/colleges/cas/units/departments/"
           f"{dept_path}/our-people/")
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": _AEM_SEL,
            "link_filter": rf"{dept_path}/our-people/",
            "field_filter": {
                "selector": ".matrixResultTextContent",
                "require_present": True,
                "include": r"Prof|Lecturer|Instructor|Chair",
            },
            "profile_enrich": _ENRICH,
        },
    }


def _media(short: str, name: str, majors: list[str], college: str,
           slug: str) -> dict:
    """A CHS/CEOE department directory of AEM ``div.media`` faculty cards."""
    url = (f"https://www.udel.edu/academics/colleges/{college}/departments/"
           f"{slug}/faculty/")
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _MEDIA_SEL,
                   "ladder_filter": _TEACHING, "profile_enrich": _ENRICH},
    }


def _callout(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A CANR department directory of AEM ``callout`` faculty cards."""
    url = (f"https://www.udel.edu/academics/colleges/canr/departments/"
           f"{slug}/faculty-staff/")
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CALLOUT_SEL,
                   "ladder_filter": _TEACHING, "profile_enrich": _ENRICH},
    }


def _scrape(short: str, name: str, majors: list[str], url: str, selectors: dict,
            ladder: dict | None = None) -> dict:
    """A single-page Divi/WordPress engineering directory (subdomain sites)."""
    cfg = {"url": url, "selectors": selectors, "profile_enrich": _ENRICH}
    if ladder:
        cfg["ladder_filter"] = ladder
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": cfg}


SCHOOL: dict = {
    "school_slug": "udel",
    "source": "udel_faculty",
    "organization": "University of Delaware",
    "location": "Newark, DE",
    "id_prefix": "udel",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Delaware) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ==== College of Engineering ========================================
        {
            "short": "CIS", "name": "Department of Computer and Information Sciences",
            "majors": ["Computer Science", "Information Systems", "Data Science"],
            "directory_url": "https://www.cis.udel.edu/people/faculty/",
            "scrape": {
                "url": "https://www.cis.udel.edu/people/faculty/",
                "selectors": _CIS_SEL,
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "ECE", "name": "Department of Electrical and Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://www.ece.udel.edu/people/faculty/",
            "scrape": {
                "url": "https://www.ece.udel.edu/people/faculty/",
                "selectors": _ECE_SEL,
                "section_filter": {"heading": "h2", "include": r"^Primary$"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "ME", "name": "Department of Mechanical Engineering",
            "majors": ["Mechanical Engineering"],
            "directory_url": "https://me.udel.edu/people/faculty/",
            "scrape": {
                "url": "https://me.udel.edu/people/faculty/",
                "selectors": _ME_SEL,
                "ladder_filter": _LADDER,
            },
        },
        _scrape("CBE", "Department of Chemical and Biomolecular Engineering",
                ["Chemical Engineering"],
                "https://cbe.udel.edu/people/faculty/", _CBE_SEL, _LADDER),
        _scrape("CCEE", "Department of Civil, Construction and Environmental Engineering",
                ["Civil Engineering", "Environmental Engineering"],
                "https://ccee.udel.edu/people/faculty/", _CCEE_SEL),
        _scrape("MSEG", "Department of Materials Science and Engineering",
                ["Materials Science and Engineering"],
                "https://mseg.udel.edu/people/faculty/", _ENGR_TEXT_SEL),
        _scrape("BME", "Department of Biomedical Engineering",
                ["Biomedical Engineering"],
                "https://bme.udel.edu/people/", _ENGR_TEXT_SEL),

        # ==== College of Arts & Sciences (central AEM "Our People") =========
        _aem("PHYS", "Department of Physics and Astronomy",
             ["Physics", "Astronomy", "Astrophysics"], "physics-astronomy"),
        _aem("CHEM", "Department of Chemistry and Biochemistry",
             ["Chemistry", "Biochemistry"], "chem-biochem"),
        _aem("MATH", "Department of Mathematical Sciences",
             ["Mathematics", "Applied Mathematics", "Statistics"],
             "mathematical-sciences"),
        _aem("BISC", "Department of Biological Sciences",
             ["Biological Sciences", "Neuroscience"], "biological-sciences"),
        _aem("PBS", "Department of Psychological and Brain Sciences",
             ["Psychology", "Neuroscience", "Cognitive Science"],
             "psychological-and-brain-sciences"),
        _aem("POSC", "Department of Political Science and International Relations",
             ["Political Science"], "political-science-international-relations"),
        _aem("ENGL", "Department of English", ["English"], "english"),
        _aem("HIST", "Department of History", ["History"], "history"),
        _aem("LING", "Department of Linguistics and Cognitive Science",
             ["Cognitive Science", "Linguistics"], "linguistics-cognitive-science"),
        _aem("SOCI", "Department of Sociology and Criminal Justice",
             ["Criminal Justice", "Sociology"], "sociology-and-criminal-justice"),
        _aem("COMM", "Department of Communication", ["Communication"], "communication"),
        _aem("ARTC", "Department of Art Conservation", ["Art Conservation"],
             "art-conservation"),
        _aem("MUSC", "School of Music", ["Music"], "school-of-music"),
        _aem("AFRA", "Department of Africana Studies", ["Africana Studies"],
             "africana-studies"),
        _aem("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _aem("ARTD", "Department of Art and Design", ["Art", "Design"], "art-design"),
        _aem("ARTH", "Department of Art History", ["Art History"], "art-history"),
        _aem("FASH", "Department of Fashion and Apparel Studies",
             ["Fashion and Apparel Studies"], "fashion-apparel-studies"),
        _aem("LLC", "Department of Languages, Literatures and Cultures",
             ["Languages, Literatures and Cultures"], "languages-literatures-cultures"),
        _aem("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _aem("WOMS", "Department of Women and Gender Studies",
             ["Women and Gender Studies"], "women-gender-studies"),

        # ==== College of Health Sciences (AEM "media" cards) ================
        _media("SON", "School of Nursing", ["Nursing"], "chs", "son"),
        _media("KAAP", "Department of Kinesiology and Applied Physiology",
               ["Exercise Science", "Applied Physiology"], "chs", "kaap"),
        _media("HBNS", "Department of Health Behavior and Nutrition Sciences",
               ["Health Behavior Science", "Applied Nutrition"], "chs", "hbns"),
        _media("CSCD", "Department of Communication Sciences and Disorders",
               ["Communication Sciences and Disorders"], "chs", "cscd"),
        _media("MMS", "Department of Medical and Molecular Sciences",
               ["Medical Diagnostics"], "chs", "mms"),
        _media("PT", "Department of Physical Therapy",
               ["Physical Therapy", "Integrated Health Sciences"], "chs", "pt"),
        _media("EPID", "Department of Epidemiology", ["Epidemiology"], "chs",
               "epidemiology"),

        # ==== College of Earth, Ocean and Environment (AEM "media" cards) ===
        _media("ENVS", "Department of Environmental Science",
               ["Environmental Science"], "ceoe", "es"),
        _media("GEOL", "Department of Geological Sciences",
               ["Geological Sciences", "Earth Science"], "ceoe", "gss"),
        _media("SMSP", "School of Marine Science and Policy",
               ["Marine Science"], "ceoe", "smsp"),

        # ==== College of Agriculture & Natural Resources (AEM "callout") ====
        _callout("ANFS", "Department of Animal and Food Sciences",
                 ["Animal Science", "Food and Agribusiness Marketing"],
                 "animal-and-food-sciences"),
        _callout("APEC", "Department of Applied Economics and Statistics",
                 ["Environmental and Resource Economics", "Agriculture and Natural Resources"],
                 "applied-economics-and-statistics"),
        _callout("ENWC", "Department of Entomology and Wildlife Ecology",
                 ["Wildlife Ecology and Conservation"],
                 "entomology-and-wildlife-ecology"),
        _callout("PLSC", "Department of Plant and Soil Sciences",
                 ["Plant Science", "Sustainable Food Systems"],
                 "plant-and-soil-sciences"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
