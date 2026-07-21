"""University of California, Davis faculty config (via the faculty_graph engine).

UC Davis runs one shared "SiteFarm" Drupal platform across every department
subdomain (``<dept>.ucdavis.edu``), so a single selector set covers the whole
university. Person cards are ``article.vm-teaser`` (``node--type-sf-person``):

    name/link : h3.vm-teaser__title a           (href /directory/<slug> or
                                                  /people/<slug>)
    title     : ul.vm-teaser__position li.field__item   (first li = rank;
                                                  later li = the person's
                                                  department affiliations)
    email     : ul.vm-teaser__contact a[href^='mailto:']   (inline, ~92%)

Engineering-college subdomains list under ``/directory``; Letters & Science,
the biological-sciences departments, and CA&ES list under ``/people``. The
listing renders all cards on one page (no pager observed on cs.ucdavis.edu's
143-card page). Research areas are not on the teaser (the body field is empty)
— they live on the profile page, recovered by the monthly OFE_ENRICH_PROFILES
pass.

WAF / best-effort caveat (verified live 2026-07-21): every ucdavis.edu
subdomain sits behind a STRICT Cloudflare *managed challenge* that 403s a bare
request and only clears for a real browser with good IP reputation. This means
``render`` (headless Chromium) is mandatory — but unlike the repo's other
render schools (umich/princeton/ucsd, whose lighter bot-fight a plain headless
clears every time), UC Davis hard-challenges datacenter IPs. Weekly CI refresh
is therefore BEST-EFFORT: some runs will collect nothing, and the corpus's
14-day grace + upsert (not deactivation) is what keeps the roster from
churning when a run is blocked. The initial corpus was collected locally
during an unflagged window. Do NOT add stealth/anti-detection tooling to force
the challenge — that circumvents a deliberately-deployed access control (cf.
the UCSD REAL Portal decision).

Deferred (2026-07-21 sitemap recon): math, biology-college department variants
(plb, plantsciences), esp, lawr, and the professional schools (Vet Med, Law,
GSM, Education, Nursing, Medicine) — their subdomains use non-SiteFarm layouts
or different person paths and need their own recon pass.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Shared SiteFarm "vm-teaser" card selectors ----------------------------
_UCD_SELECTORS = {
    "card": "article.vm-teaser",
    "name": "h3.vm-teaser__title a",
    "link": "h3.vm-teaser__title a",
    "title": "ul.vm-teaser__position li.field__item",
    "email": "ul.vm-teaser__contact a[href^='mailto:']",
}

# Directories list faculty alongside emeritus/adjunct/lecturer/researcher ranks
# and (on some depts) affiliated/adjunct sections — gate by the position line.
_UCD_LADDER = {
    "drop": r"emerit|adjunct|visiting|lecturer|\bemerita\b|"
            r"researcher|research scientist|project scientist|"
            r"postdoc|affiliat|by courtesy|\bstaff\b",
}

# Research areas are profile-only; the monthly enrich pass follows each teaser
# link and reads the SiteFarm "Research"/"Research Interests" field block.
_UCD_PROFILE = {
    "research_selector": "div.field--name-field-sf-research-areas, div.field--name-body",
    "throttle": 0.25,
}


def _ucd(short: str, name: str, majors: list[str], sub: str,
         path: str = "/people") -> dict:
    """A department on the shared SiteFarm platform (render-mode)."""
    url = f"https://{sub}.ucdavis.edu{path}"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "render": True,
                       # CF managed challenge needs a longer initial settle than
                       # the 3.5s default before the real DOM replaces the shell.
                       "render_settle": 9000,
                       "selectors": _UCD_SELECTORS,
                       "ladder_filter": _UCD_LADDER,
                       "profile_enrich": _UCD_PROFILE}}


def _eng(short: str, name: str, majors: list[str], sub: str) -> dict:
    return _ucd(short, name, majors, sub, path="/directory")


SCHOOL: dict = {
    "school_slug": "ucd",
    "source": "ucd_faculty",
    "organization": "University of California, Davis",
    "location": "Davis, CA",
    "id_prefix": "ucd",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UC Davis) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering (SiteFarm, /directory) -----------------
        _eng("CS", "Department of Computer Science",
             ["Computer Science", "Data Science"], "cs"),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical and Computer Engineering"], "ece"),
        _eng("MAE", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"], "mae"),
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "bme"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], "cee"),
        _eng("BAE", "Department of Biological and Agricultural Engineering",
             ["Biological Systems Engineering", "Agricultural Engineering"],
             "bae"),
        # ---- College of Letters and Science: Sciences (/people) ------------
        _ucd("PHY", "Department of Physics and Astronomy",
             ["Physics", "Astronomy"], "physics"),
        _ucd("CHE", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _ucd("STA", "Department of Statistics", ["Statistics", "Data Science"],
             "statistics"),
        # ---- College of Letters and Science: Social Sciences ---------------
        _ucd("ECN", "Department of Economics", ["Economics"], "economics"),
        _ucd("PSY", "Department of Psychology", ["Psychology"], "psychology"),
        _ucd("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _ucd("ANT", "Department of Anthropology", ["Anthropology"],
             "anthropology"),
        _ucd("POL", "Department of Political Science", ["Political Science"],
             "ps"),
        _ucd("CMN", "Department of Communication", ["Communication"],
             "communication"),
        # ---- College of Letters and Science: Humanities --------------------
        _ucd("HIS", "Department of History", ["History"], "history"),
        _ucd("ENL", "Department of English", ["English", "Creative Writing"],
             "english"),
        _ucd("PHI", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _ucd("LIN", "Department of Linguistics", ["Linguistics"], "linguistics"),
        # ---- College of Biological Sciences (/people) ----------------------
        _ucd("MCB", "Department of Molecular and Cellular Biology",
             ["Molecular Biology", "Cell Biology", "Biochemistry"], "mcb"),
        _ucd("NPB", "Department of Neurobiology, Physiology and Behavior",
             ["Neurobiology", "Physiology"], "npb"),
        _ucd("EVE", "Department of Evolution and Ecology",
             ["Evolution", "Ecology"], "eve"),
        _ucd("MMG", "Department of Microbiology and Molecular Genetics",
             ["Microbiology", "Genetics"], "mmg"),
        # ---- College of Agricultural and Environmental Sciences (/people) --
        _ucd("ARE", "Department of Agricultural and Resource Economics",
             ["Agricultural Economics", "Resource Economics"], "are"),
        _ucd("ANS", "Department of Animal Science", ["Animal Science"],
             "animalscience"),
        _ucd("FST", "Department of Food Science and Technology",
             ["Food Science"], "foodscience"),
        _ucd("ENT", "Department of Entomology and Nematology",
             ["Entomology", "Nematology"], "entomology"),
        _ucd("VEN", "Department of Viticulture and Enology",
             ["Viticulture", "Enology"], "wineserver"),
        _ucd("HDE", "Department of Human Ecology",
             ["Human Development", "Design", "Textiles"], "humanecology"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
