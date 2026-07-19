"""Texas A&M University faculty config (via the faculty_graph engine).

TAMU's directories fall into seven markup families, all live-verified
2026-07-18 (no Cloudflare challenges anywhere at a polite throttle; two UA
regimes — see the VMBS note):

* **Cascade profile JSON** (College of Engineering + College of Arts &
  Sciences): ONE college-wide feed at ``/profile-data.json`` — an array of
  ``{name, tag[], link, titles[], email}`` rendered client-side by
  cfprofiles.js, so the engine reads the feed directly (``json_dir``). The
  ``tag`` array mixes role tags (Faculty / Staff / Research Staff / Emeritus
  Faculty / Qatar Faculty / …) with department slugs, so each department entry
  filters on its slug AND requires the exact ``Faculty`` role tag (verified:
  Engineering 1582 people → 754 Faculty / 752 emailed; ArtSci 2989 → 1017 /
  1005 emailed; per-dept slug counts match the config's estimates exactly).
  Titles carry an "… Emeritus" tail on the few Faculty+Emeritus double-tags —
  the ladder drop catches them. Profile pages keep a CLEAN research list
  (Engineering ``#researchinterest li``, ArtSci ``#researchareas li``), wired
  as the gated per-profile enrichment pass.

* **AgriLife WordPress people listing** (14 College of Agriculture & Life
  Sciences dept subdomains): server-rendered ``.people-listing-item`` cards at
  ``/types/faculty/`` (the URL facet already excludes staff/grads/postdocs).
  Emails are Cloudflare-obfuscated cfemail hex on the card — the engine's
  decoder recovers them. ``page/N`` pagination links all render the IDENTICAL
  full list (verified soilcrop p1==p2), so one fetch suffices. Many titles are
  ``Rank<br>specialty-or-admin-role`` — the second line is often an ADMIN role
  ("Associate Department Head…"), so it is NOT harvested as research; a
  boundary split keeps just the rank. biochemistry.tamu.edu 403s the spoofed
  Chrome UA but 200s an honest curl UA (inverted WAF) — per-dept ``ua``.

* **TAMU Health person-wrapper** (Pharmacy all-staff page, Nursing
  faculty-only page): server-rendered ``.person-wrapper`` cards with name,
  multiple ``.title`` divs, plain mailto and a "…'s bio" profile link. Staff
  are dropped by a field filter over the card's full title set (a dean whose
  FIRST title is "Dean" but who is also a Professor stays — verified split:
  Pharmacy 57 keep / 63 staff drop).

* **VMBS directory** (4 School of Veterinary Medicine dept subdomains):
  server-rendered ``a.directory__listing`` cards at ``/people/faculty/``.
  INVERTED WAF: 403 to the spoofed Chrome UA, 200 to a plain curl UA — the
  scrape AND the profile-enrich pass both ride ``ua: curl``. Profile pages
  publish a mailto (@cvm.tamu.edu), wired as the gated email enrich.

* **Bush School staff-list plugin** (INTA / POLS / PSAA): ``.abcfslItemCntrLst``
  cards with name, full title and mailto all on the listing.

* **Education & Human Development custom directory**
  (directory.education.tamu.edu): the ``et=f&number_per_page=all`` facet
  returns all 281 faculty in ONE server-rendered page — but listing names are
  ALL-CAPS ("ACOSTA, SANDRA"), so the config walks the per-person profile
  pages instead (``sitemap`` source with ``list_pages``): profiles carry the
  proper-cased ``.full_name``, the rank, and a plain mailto (verified on
  sacosta + jwahn). ~281 throttled profile fetches per refresh.

* **WordPress REST directory** (Mays Business School, School of Architecture,
  School of Performance/Visualization/Fine Arts): the REST feed carries name +
  profile URL only (no rank/email), so records are completed by an always-on
  per-profile pass (rank selector + mailto) with a ``ladder_recheck`` — the
  api default title is a non-professorial sentinel ("Directory listing") so a
  profile whose rank element is missing or whose fetch failed can never slip
  through as "Professor". Mays mixes 558 faculty/staff/PhD students (title
  gate on ``.bio-title``); Architecture is split into its three departments
  via category terms (architecture-faculty 257 / construction-science-faculty
  260 / laup-faculty 259; rank in the profile callout ``h2`` — emeriti like
  "Professor Emeritus" verified dropped); PVFA faculty are sptp_group 283
  (113 of 169; rank in ``h4.sptp-profession-text``, coordinators recheck-drop).

Single source ("tamu_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred units (and why):

* School of Law — ``law.tamu.edu/profile-data.json`` is MALFORMED (384 lines
  of unrendered ``${str.replaceAll…}`` template literals in sortname/firstname
  break strict JSON parsing; verified 2026-07-18) and the listing page is
  client-rendered from that same feed. Needs a bespoke sanitizer the engine
  doesn't have.
* School of Public Health + College of Dentistry — their
  ``/_json-data/json-profile-data.json`` is a dict KEYED BY PERSON SLUG with
  dict values (no list anywhere); the engine's ``json_dir`` consumes arrays or
  dict-with-list-values only, and the HTML directory pages are client-rendered
  from the same feed (verified: zero ``.person-wrapper`` cards). Engine
  limitation — needs a records-from-dict-values option. (SPH also publishes
  NO email anywhere; Dentistry profiles do carry mailto.)
* College of Medicine — ~9 heterogeneous per-dept layouts off the
  faculty-listings hub; the college JSON feed is a test stub. Needs bespoke
  configs per department.
* VLCS (Large Animal Clinical Sciences) — 403 (Chrome UA) and 404 on
  ``/people/faculty/`` (plain UA); no working listing found.
* TAMU Galveston + TAMU Qatar — separate branch campuses with their own
  OpenAlex IDs; Qatar people in the Engineering feed carry the "Qatar
  Faculty" tag (not "Faculty") and are excluded by the exact-tag gate.
* University Libraries faculty — low research-matching value.
* Mitchell Institute / Cyclotron / Hagler — member faculty already ride the
  college feeds (institute name appears as an extra tag).
* Bush School DC teaching site — small satellite roster.
"""

from __future__ import annotations

from .. import faculty_graph

# Retired / non-home ranks. The Cascade feeds' Faculty tag and the AgriLife /
# VMBS faculty URL facets already exclude staff and students, so the title
# gate's job is the emeritus/visiting/adjunct stragglers.
_DROP_RETIRED = {"drop": r"emerit|visiting|adjunct"}

# Rosters that mix professorial faculty with staff/coordinators and only
# reveal the rank per profile: require a teaching rank outright.
_LADDER_STRICT = {"require": r"professor|lecturer|instructor",
                  "drop": r"emerit|visiting|adjunct"}

# Honest tool UA for the inverted-WAF hosts (vetmed dept subdomains +
# biochemistry.tamu.edu 403 the spoofed Chrome UA but pass curl).
_CURL_UA = "curl/8.7.1"


# ---- Cascade profile JSON (Engineering + Arts & Sciences) ------------------

def _cascade(short: str, name: str, majors: list[str], tag: str, base: str,
             research_items: str) -> dict:
    """One department slice of a college-wide ``/profile-data.json`` feed."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": f"{base}/profile-data.json",
        "json_dir": {
            "url": f"{base}/profile-data.json",
            "name_fields": ["name"],
            # tag[] holds role tags AND dept slugs: membership on the dept slug
            # + exact "Faculty" role (a person tagged only "Emeritus Faculty" /
            # "Qatar Faculty" / "Staff" never matches the exact string).
            "filter_field": "tag", "filter_value": tag,
            "status_field": "tag", "status_value": "Faculty",
            "title_field": "titles",  # list; joined — ladder gate sees all roles
            "email_field": "email",
            "link_field": "link", "link_base": base,
            "ladder_filter": _DROP_RETIRED,
        },
        # Profiles keep a clean bulleted research list; the outer wrapper <li>
        # of the nested list concatenates every item and self-drops on the
        # items-cleaner's length gate, so the bare "li" selector is safe.
        "profile_enrich": {"research_items_selector": research_items,
                           "throttle": 0.2},
    }


def _eng(short: str, name: str, majors: list[str], tag: str) -> dict:
    return _cascade(short, name, majors, tag, "https://engineering.tamu.edu",
                    "#researchinterest li")


def _artsci(short: str, name: str, majors: list[str], tag: str) -> dict:
    return _cascade(short, name, majors, tag, "https://artsci.tamu.edu",
                    "#researchareas li")


# ---- AgriLife WordPress people listing -------------------------------------

# Many titles are "Rank<br>specialty-or-admin-line"; get_text merges the lines,
# so split right after the rank word when the next word is capitalized (the
# merged second line), but never before "Emeritus" — the ladder drop needs it.
_AGRILIFE_SELECTORS = {
    "card": ".people-listing-item",
    "name": ".people-name a",
    "link": ".people-name a",
    "title": ".people-title",
    "title_strip_after": r"(?:(?<=Professor)|(?<=Lecturer)|(?<=Instructor))\s+(?!Emeritus)(?=[A-Z])",
    # cfemail hex on the card anchor's inner span (engine decoder), or a plain
    # mailto on the depts outside the Cloudflare-fronted network (biochemistry).
    "email": ".people-email a",
}


def _agrilife(short: str, name: str, majors: list[str], host: str,
              ua: str | None = None) -> dict:
    url = f"https://{host}/types/faculty/"
    scrape: dict = {"url": url, "selectors": _AGRILIFE_SELECTORS,
                    "ladder_filter": _DROP_RETIRED}
    if ua:
        scrape["ua"] = ua
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# ---- TAMU Health person-wrapper (Pharmacy, Nursing) ------------------------

# A card carries SEVERAL .title divs ("Dean", then "… Professor of
# Pharmaceutical Sciences"): the title selector picks the first professorial
# one, and the field filter over the whole card body drops pure-staff cards
# (directors/coordinators/research scientists) that have none.
_HEALTH_SELECTORS = {
    "card": ".person-wrapper",
    "name": ".font-size-1_75",
    "link": "a.bio",
    "title": (".title:-soup-contains('Professor'), "
              ".title:-soup-contains('Lecturer'), "
              ".title:-soup-contains('Instructor')"),
    "email": ".email a[href^='mailto:']",
}

_HEALTH_FIELD_FILTER = {"selector": ".person-info",
                        "include": r"professor|lecturer|instructor"}


def _health(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _HEALTH_SELECTORS,
                       "field_filter": _HEALTH_FIELD_FILTER,
                       "ladder_filter": _DROP_RETIRED}}


# ---- VMBS directory (vet-school dept subdomains; curl UA required) ---------

_VMBS_SELECTORS = {
    "card": "a.directory__listing",
    "name": ".listing__info .name",
    "link": ":self",
    "title": ".listing__info .title",
}


def _vmbs(short: str, name: str, majors: list[str], host: str) -> dict:
    url = f"https://{host}/people/faculty/"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _VMBS_SELECTORS,
                       "ua": _CURL_UA,
                       "ladder_filter": _LADDER_STRICT,
                       # Profiles publish the @cvm.tamu.edu mailto the listing
                       # omits; same inverted WAF as the listing → curl UA.
                       "profile_enrich": {
                           "email_selector": "a[href^='mailto:']",
                           "email_drop": r"^[^@]*$",
                           "ua": _CURL_UA,
                           "throttle": 0.2,
                       }}}


# ---- Bush School staff-list plugin -----------------------------------------

_BUSH_SELECTORS = {
    "card": ".abcfslItemCntrLst",
    "name": ".MP-F1",
    "link": "a[href^='/faculty/']",
    "title": ".T-F2",
    "email": "a[href^='mailto:']",
}

# Bush lists professors of the practice and senior fellows who teach; keep
# fellow-titled faculty, drop staff/director-only cards.
_BUSH_LADDER = {"require": r"professor|lecturer|\bfellow\b",
                "drop": r"emerit|visiting"}


def _bush(short: str, name: str, majors: list[str], path: str) -> dict:
    url = f"https://bush.tamu.edu/{path}/faculty/"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _BUSH_SELECTORS,
                       "ladder_filter": _BUSH_LADDER}}


# ---- WordPress REST directories (rank + email live on the profile page) ----

def _wp_profiled(short: str, name: str, majors: list[str], *, base: str,
                 post_type: str, directory_url: str, title_selector: str,
                 query: str = "", category_include: dict | None = None) -> dict:
    """A WP-REST roster completed by an always-on per-profile pass.

    The REST feed has no rank/email, so the profile pass is where the record's
    core fields live (the engine's ``always`` idiom). The api default title is
    a NON-professorial sentinel: a missing rank element or a failed profile
    fetch leaves the sentinel in place and the ``ladder_recheck`` drops the
    record — staff/PhD students can never slip through as "Professor".
    """
    api: dict = {"type": "wp", "base": base, "post_type": post_type,
                 "title": "Directory listing"}
    if query:
        api["query"] = query
    if category_include:
        api["category_include"] = category_include
    return {"short": short, "name": name, "majors": majors,
            "directory_url": directory_url,
            "api": api,
            "profile_enrich": {
                "always": True,
                "title_selector": title_selector,
                "email_selector": "a[href^='mailto:']",
                "email_drop": r"^[^@]*$",
                "throttle": 0.2,
                "ladder_recheck": _LADDER_STRICT,
            }}


def _arch(short: str, name: str, majors: list[str], term: int) -> dict:
    """One School of Architecture department (category term = its faculty)."""
    return _wp_profiled(
        short, name, majors,
        base="https://www.arch.tamu.edu", post_type="directory",
        directory_url="https://www.arch.tamu.edu/directory/",
        title_selector=".callout__content .heading-group h2",
        query=f"&categories={term}",
        category_include={"categories": [term]},
    )


SCHOOL: dict = {
    "school_slug": "tamu",
    "source": "tamu_faculty",
    "organization": "Texas A&M University",
    "location": "College Station, TX",
    "id_prefix": "tamu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Texas A&M University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering (Cascade JSON; est 754 Faculty) --------
        _eng("CSCE", "Department of Computer Science and Engineering",
             ["Computer Science", "Computer Engineering"], "csce"),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], "electrical"),
        _eng("ME", "J. Mike Walker '66 Department of Mechanical Engineering",
             ["Mechanical Engineering"], "mechanical"),
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "biomedical"),
        _eng("CHEN", "Artie McFerrin Department of Chemical Engineering",
             ["Chemical Engineering"], "chemical"),
        _eng("CVEN", "Zachry Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], "civil"),
        _eng("AERO", "Department of Aerospace Engineering",
             ["Aerospace Engineering"], "aerospace"),
        _eng("ISEN", "Wm Michael Barnes '64 Department of Industrial and Systems Engineering",
             ["Industrial Engineering"], "industrial"),
        _eng("PETE", "Harold Vance Department of Petroleum Engineering",
             ["Petroleum Engineering"], "petroleum"),
        _eng("MSEN", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"], "materials"),
        _eng("NUEN", "Department of Nuclear Engineering",
             ["Nuclear Engineering"], "nuclear"),
        _eng("OCEN", "Department of Ocean Engineering",
             ["Ocean Engineering"], "ocean"),
        _eng("ETID", "Department of Engineering Technology and Industrial Distribution",
             ["Engineering Technology", "Industrial Distribution"], "etid"),
        _eng("MTDE", "Department of Multidisciplinary Engineering",
             ["Multidisciplinary Engineering"], "mtde"),
        # ---- College of Arts and Sciences (Cascade JSON; est 1017 Faculty) --
        _artsci("MATH", "Department of Mathematics", ["Mathematics"], "mathematics"),
        _artsci("PHYS", "Department of Physics and Astronomy",
                ["Physics", "Astronomy"], "physics-astronomy"),
        _artsci("BIOL", "Department of Biology", ["Biology"], "biology"),
        _artsci("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _artsci("STAT", "Department of Statistics", ["Statistics"], "statistics"),
        _artsci("PSYC", "Department of Psychological and Brain Sciences",
                ["Psychology", "Neuroscience"], "psychological"),
        _artsci("ECON", "Department of Economics", ["Economics"], "economics"),
        _artsci("ENGL", "Department of English", ["English"], "english"),
        _artsci("HIST", "Department of History", ["History"], "history"),
        _artsci("SOCI", "Department of Sociology", ["Sociology"], "sociology"),
        _artsci("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _artsci("COMM", "Department of Communication and Journalism",
                ["Communication", "Journalism"], "comm-journalism"),
        _artsci("OCNG", "Department of Oceanography", ["Oceanography"], "oceanography"),
        _artsci("GEOL", "Department of Geology and Geophysics",
                ["Geology", "Geophysics"], "geology-geophysics"),
        _artsci("ATMO", "Department of Atmospheric Sciences",
                ["Meteorology", "Atmospheric Sciences"], "atmos-science"),
        _artsci("GEOG", "Department of Geography", ["Geography"], "geography"),
        _artsci("GLAC", "Department of Global Languages and Cultures",
                ["Spanish", "French", "German Studies", "Linguistics"],
                "global-lang-cultures"),
        _artsci("PHIL", "Department of Philosophy and Humanities",
                ["Philosophy"], "philosophy-humanities"),
        # ---- College of Agriculture and Life Sciences (AgriLife WP) --------
        _agrilife("ANSC", "Department of Animal Science",
                  ["Animal Science"], "animalscience.tamu.edu"),
        _agrilife("AGEC", "Department of Agricultural Economics",
                  ["Agricultural Economics"], "agecon.tamu.edu"),
        _agrilife("ENTO", "Department of Entomology",
                  ["Entomology"], "entomology.tamu.edu"),
        _agrilife("BCBP", "Department of Biochemistry and Biophysics",
                  ["Biochemistry", "Biophysics"], "biochemistry.tamu.edu",
                  ua=_CURL_UA),
        _agrilife("SCSC", "Department of Soil and Crop Sciences",
                  ["Plant and Environmental Soil Science", "Agronomy"],
                  "soilcrop.tamu.edu"),
        _agrilife("HORT", "Department of Horticultural Sciences",
                  ["Horticulture"], "hortsciences.tamu.edu"),
        _agrilife("POSC", "Department of Poultry Science",
                  ["Poultry Science"], "poultry.tamu.edu"),
        _agrilife("RWFM", "Department of Rangeland, Wildlife and Fisheries Management",
                  ["Rangeland, Wildlife and Fisheries Management", "Ecology"],
                  "rwfm.tamu.edu"),
        _agrilife("NUTR", "Department of Nutrition", ["Nutrition"], "nutrition.tamu.edu"),
        _agrilife("BAEN", "Department of Biological and Agricultural Engineering",
                  ["Biological and Agricultural Engineering"], "baen.tamu.edu"),
        _agrilife("ECCB", "Department of Ecology and Conservation Biology",
                  ["Ecology and Conservation Biology"], "eccb.tamu.edu"),
        _agrilife("ALEC", "Department of Agricultural Leadership, Education and Communications",
                  ["Agricultural Communications"], "alec.tamu.edu"),
        _agrilife("PLPM", "Department of Plant Pathology and Microbiology",
                  ["Plant Pathology", "Microbiology"], "plantpathology.tamu.edu"),
        _agrilife("FSTC", "Department of Food Science and Technology",
                  ["Food Science and Technology"], "foodscience.tamu.edu"),
        # ---- Texas A&M Health (server-rendered person-wrapper pages) -------
        _health("PHAR", "Irma Lerma Rangel College of Pharmacy",
                ["Pharmacy (PharmD track)", "Pharmaceutical Sciences"],
                "https://pharmacy.tamu.edu/directory/index.html"),
        _health("NURS", "College of Nursing", ["Nursing (BSN)"],
                "https://nursing.tamu.edu/faculty-staff/faculty/index.html"),
        # ---- School of Veterinary Medicine and Biomedical Sciences ---------
        _vmbs("VIBS", "Department of Veterinary Integrative Biosciences",
              ["Biomedical Sciences"], "vibs.tamu.edu"),
        _vmbs("VTPP", "Department of Veterinary Physiology and Pharmacology",
              ["Biomedical Sciences"], "vtpp.tamu.edu"),
        _vmbs("VTPB", "Department of Veterinary Pathobiology",
              ["Biomedical Sciences", "Microbiology"], "vtpb.tamu.edu"),
        _vmbs("VSCS", "Department of Small Animal Clinical Sciences",
              ["Biomedical Sciences"], "vscs.tamu.edu"),
        # ---- Bush School of Government and Public Service -------------------
        _bush("INTA", "Department of International Affairs",
              ["International Studies", "Political Science"], "inta"),
        _bush("POLS", "Department of Political Science", ["Political Science"], "pols"),
        _bush("PSAA", "Department of Public Service and Administration",
              ["Political Science", "Public Administration"], "psaa"),
        # ---- School of Education and Human Development ----------------------
        {
            # Listing names are ALL-CAPS; profile pages carry the proper-cased
            # .full_name + rank + mailto, so walk the faculty facet's /view/
            # links (281) through the sitemap source's list_pages harvest.
            "short": "SEHD", "name": "School of Education and Human Development",
            "majors": ["Interdisciplinary Studies (Teaching)", "Kinesiology",
                       "Sport Management", "Human Resource Development",
                       "Educational Psychology"],
            "directory_url": "https://directory.education.tamu.edu/?page=1&number_per_page=all&d=&et=f",
            "sitemap": {
                "list_pages": ["https://directory.education.tamu.edu/?page=1&number_per_page=all&d=&et=f"],
                "include": r"directory\.education\.tamu\.edu/view/",
                "selectors": {
                    "name": ".full_name",
                    "title": "div[style*='font-size: 120%']",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER_STRICT,
                "cap": 400,
                "throttle": 0.2,
            },
        },
        # ---- Mays Business School (WP REST + profile pass) ------------------
        _wp_profiled(
            "MAYS", "Mays Business School",
            ["Accounting", "Finance", "Marketing", "Management",
             "Management Information Systems", "Supply Chain Management"],
            base="https://mays.tamu.edu", post_type="directory",
            directory_url="https://mays.tamu.edu/directory/",
            title_selector=".bio-title",
        ),
        # ---- School of Architecture (WP REST, split by category term) -------
        _arch("ARCH", "Department of Architecture",
              ["Architecture", "Environmental Design"], 257),
        _arch("COSC", "Department of Construction Science",
              ["Construction Science"], 260),
        _arch("LAUP", "Department of Landscape Architecture and Urban Planning",
              ["Landscape Architecture", "Urban and Regional Planning"], 259),
        # ---- School of Performance, Visualization and Fine Arts -------------
        _wp_profiled(
            "PVFA", "School of Performance, Visualization and Fine Arts",
            ["Visualization", "Performance Studies", "Music", "Dance Science"],
            base="https://pvfa.tamu.edu", post_type="sptp_member",
            directory_url="https://pvfa.tamu.edu/about/directory/",
            title_selector="h4.sptp-profession-text",
            query="&sptp_group=283",
            category_include={"sptp_group": [283]},
        ),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
