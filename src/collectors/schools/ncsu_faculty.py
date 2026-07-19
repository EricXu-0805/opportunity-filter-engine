"""North Carolina State University faculty config (via the faculty_graph engine).

NC State is remarkably uniform: nearly the whole campus runs the ncstate-theme
(-v4) WordPress family with a ``person`` custom post type + ``group`` taxonomy
exposed over OPEN wp-json REST — so the PRIMARY path here is the API, not HTML
scraping. All endpoints, group term ids, and selectors live-verified 2026-07-18:

* **v4 person-CPT wp-json** (CS, CCEE, BAE, all six College of Sciences
  depts, Textiles, Poole, all 11 CALS dept subsites, CHASS central pool, CNR
  central pool, Design, Education, all three Vet Med academic depts):
  ``GET <site>/wp-json/wp/v2/person?per_page=100&page=N&group=<faculty-term>``
  (engine paginates until the page runs short; verified CHASS 442 = 5 pages).
  JSON carries name (title.rendered), profile URL (link), and a ``group`` term-id
  array — used for ``category_exclude`` where a roster dual-tags adjuncts
  (CS faculty term 22 also carries adjunct 82 / emeritus 80 / visiting 85
  members). No job title or email in the feed (records default "Professor");
  the gated profile-enrich pass reads the profile card's plain
  ``a.email[mailto]`` + the br-separated "Area(s) of Expertise" block
  (``p.ncst-people-person__research-description``, clean tag phrases on
  csc/textiles; prose profiles are junk-gated downstream).
  Poole has no faculty term — union of rank terms 32,30,29,577,579,581 (=101);
  its profiles usually lack the expertise block, so enrich lands email only.
  Math teaching-faculty (273) verified a SUBSET of faculty (9) — group=9 alone
  is complete (69, not the naive 82).

* **ECE Divi variant**: own listing markup but the SAME person-CPT backend —
  ``group=1439`` (primary-faculty, 80). Profile enrich: ``a#email`` mailto +
  the "Research Focus" ``ul.wpv-loop li a.research-areas`` tag list (clean).

* **wp-theme-hillsborough server-rendered directory** (MAE, MSE, ISE): no
  person REST route (404) — one full-roster page (``div.directory_entry``
  cards) with name + title + plain mailto on every card, staff mixed in, so
  the ladder gate is a title regex (keep Professor|Lecturer, drop emeriti/
  adjunct/visiting: MAE 101→60, MSE 105→50, ISE 133→34). NOTE: ISE/MSE repeat
  each person's card across research-area tabs — the recon's per-card counts
  (ISE "83") double-counted; the engine's in-run URL dedup collapses them
  (ISE truly has 35 unique gate-passing faculty, verified). Profile enrich
  reads the clean "Research Interests" ``<ul>`` via a ``:has()`` items
  selector (email already on the listing).

* **NE + CBE group-page scrape**: both are v4 sites on hosts that
  intermittently exceed the wp-json client's single 20s attempt (verified:
  ne times out most runs, cbe transiently), while the server-rendered
  ``/group/faculty/`` page lists the roster with titles + emails in one
  robust fetch (fetch_soup = 30s x 3 retries) — richer AND sturdier than the
  API there. Title-gated (the group archive includes emeriti/adjunct cards).
  BAE's group page instead OVER-lists (72 professor-titled cards vs the
  27-member faculty term) — BAE stays on the JSON API; its host passed both
  timeout probes but a transient slow read can zero a run (self-heals on the
  next refresh; richer-dedup keeps merged records).

Single source ("ncsu_faculty"); department rides each record, ids namespaced by
department short-code. BME aside, emails/research land via the gated
OFE_ENRICH_PROFILES pass (plain mailtos everywhere — no obfuscation on campus).

Deferred:
* Lampe Joint BME (bme.unc.edu) — the recon's 200s did not reproduce at build
  time: the UNC host now 403s every plain fetch (requests AND curl, any UA);
  needs a headless render pass, and Playwright isn't available in this env.
* Sociology & Anthropology (sasw.chass.ncsu.edu) + World Languages
  (fll.chass.ncsu.edu) — TLS handshake fails outright (dead standalone sites);
  their faculty are already in the CHASS central pool wired here.
* history.chass.ncsu.edu standalone person CPT — contains only grad students;
  history faculty live in the CHASS central pool.
* CVM Veterinary Hospital clinicians / house officers (~900 of the 1036-person
  cvm pool) — clinical staff, not research faculty; only the three academic
  dept groups (docs/mbs/php) are wired.
* CSS usda-faculty term (10 federal USDA scientists) — not NCSU faculty.
* Textiles: the faculty term (391) carries a few adjuncts with no separating
  group term — accepted (the profile-title data to gate them is enrich-only).
* Graduate School / DELTA / University College / Libraries — no research
  faculty relevant to undergrad matching.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- v4 person-CPT wp-json family ------------------------------------------
# Profile pages share the person-card header (plain mailto in ``a.email``) and
# an optional "Area(s) of Expertise" block whose <br>-separated phrases the
# html_re folds to "; " for the derived-keyword split. Prose expertise blocks
# (some physics/CALS profiles) are junk-gated downstream; absent blocks (Poole)
# leave the record email-only. Gated behind OFE_ENRICH_PROFILES.
_V4_ENRICH = {
    "email_selector": "a.email[href^='mailto:']",
    "email_drop": r"^[^@]*$|department@|webmaster@|-info@|help@|admissions@",
    "research_html_re": r"ncst-people-person__research-description[^>]*>\s*(?:<p>)?(.*?)</p>",
    "throttle": 0.2,
}


def _wp(short: str, name: str, majors: list[str], base: str, group: str, *,
        directory: str | None = None, exclude: list[int] | None = None) -> dict:
    """A person-CPT department fetched over wp-json (v4 theme family).

    ``group`` is the faculty term id (comma-list for Poole's rank union);
    ``exclude`` drops members dual-tagged into adjunct/emeritus/visiting terms.
    """
    api: dict = {"type": "wp", "base": base, "post_type": "person",
                 "query": f"&group={group}"}
    if exclude:
        api["category_exclude"] = {"group": exclude}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": directory or f"{base}/people/",
            "api": api, "profile_enrich": _V4_ENRICH}


def _cals(short: str, name: str, majors: list[str], subsite: str, group: int) -> dict:
    """A CALS department on the cals.ncsu.edu multisite (path-based wp-json)."""
    base = f"https://cals.ncsu.edu/{subsite}"
    return _wp(short, name, majors, base, str(group))


def _cnr(short: str, name: str, majors: list[str], group: int) -> dict:
    """A College of Natural Resources department in the cnr.ncsu.edu pool."""
    return _wp(short, name, majors, "https://cnr.ncsu.edu", str(group),
               directory="https://cnr.ncsu.edu/directory/")


def _cvm(short: str, name: str, majors: list[str], group: int) -> dict:
    """A Vet Med academic department in the cvm.ncsu.edu pool (hospital
    clinician groups deliberately not wired)."""
    return _wp(short, name, majors, "https://cvm.ncsu.edu", str(group),
               directory="https://cvm.ncsu.edu/people/")


# ---- wp-theme-hillsborough directory family (MAE, MSE, ISE) ----------------
_HB_SELECTORS = {
    "card": "div.directory_entry",
    "name": ".person_id p.name",
    "link": ".person_id a",
    "title": "p.title",
    "email": "a[href^='mailto:']",
}

# Full-roster directory mixes staff (Coordinator/Advisor/Director/Manager) with
# faculty — require a professorial/lecturer rank, drop the retired/visiting.
_HB_LADDER = {"require": r"\b(?:professor|lecturer)\b",
              "drop": r"emerit|adjunct|visiting|postdoc"}

# Profiles keep a clean "Research Interests" <ul>; the :has() selector pins the
# ul that directly follows that labelled <p> (section optional — no match, no
# keywords). Email is already on the listing card, so enrich adds research only.
_HB_ENRICH = {
    "research_items_selector": "p:has(> strong:-soup-contains('Research Interests')) + ul li",
    "throttle": 0.2,
}


def _hb(short: str, name: str, majors: list[str], url: str) -> dict:
    """A hillsborough-theme department (single-page directory, emails on cards)."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _HB_SELECTORS,
                       "ladder_filter": _HB_LADDER, "profile_enrich": _HB_ENRICH}}


# ---- v4 group-page scrape (NE, CBE — hosts too slow for the 20s API client) --
_GROUP_SELECTORS = {
    "card": "div.person-card",
    "name": "a.name",
    "link": "a.name",
    "title": "p.title",
    "email": "a.email[href^='mailto:']",
}

# Group archive is faculty-scoped but shows real titles: keep rank-shaped and
# head/chair cards, drop the emeritus/adjunct stragglers the archive mixes in.
_GROUP_LADDER = {"require": r"professor|lecturer|head|chair|dean",
                 "drop": r"emerit|adjunct|visiting|postdoc"}


def _v4_group(short: str, name: str, majors: list[str], base: str) -> dict:
    """A v4 department scraped from its /group/faculty/ page (titles + emails
    on every card; sturdier than the site's slow wp-json)."""
    url = f"{base}/group/faculty/"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _GROUP_SELECTORS,
                       "ladder_filter": _GROUP_LADDER, "profile_enrich": _V4_ENRICH}}


SCHOOL: dict = {
    "school_slug": "ncsu",
    "source": "ncsu_faculty",
    "organization": "North Carolina State University",
    "location": "Raleigh, NC",
    "id_prefix": "ncsu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (North Carolina State University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering ----------------------------------------
        _wp("CS", "Department of Computer Science", ["Computer Science"],
            "https://csc.ncsu.edu", "22",
            # faculty term 22 dual-tags adjuncts (82), emeriti (80), and
            # visiting research scholars (85) — exclude wins over include.
            exclude=[82, 80, 85]),
        {
            # ECE: Divi child theme, same person-CPT wp-json backend
            # (group 1439 = primary-faculty; 1440 supporting / 1441 postdocs /
            # 1438 staff deliberately not queried).
            "short": "ECE",
            "name": "Department of Electrical and Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://ece.ncsu.edu/faculty/",
            "api": {"type": "wp", "base": "https://ece.ncsu.edu",
                    "post_type": "person", "query": "&group=1439"},
            "profile_enrich": {
                "email_selector": "a#email[href^='mailto:']",
                "email_drop": r"^[^@]*$|webmaster@|department@",
                "research_items_selector": "ul.wpv-loop li a.research-areas",
                "throttle": 0.2,
            },
        },
        _hb("MAE", "Department of Mechanical and Aerospace Engineering",
            ["Mechanical Engineering", "Aerospace Engineering"],
            "https://mae.ncsu.edu/directory/"),
        _hb("MSE", "Department of Materials Science and Engineering",
            ["Materials Science and Engineering"],
            # /directory/ is 404 on this host — the roster lives here.
            "https://mse.ncsu.edu/faculty-staff/"),
        _v4_group("CBE", "Department of Chemical and Biomolecular Engineering",
                  ["Chemical Engineering"], "https://cbe.ncsu.edu"),
        _wp("CCEE", "Department of Civil, Construction and Environmental Engineering",
            ["Civil Engineering", "Environmental Engineering", "Construction Engineering"],
            "https://ccee.ncsu.edu", "95"),
        _hb("ISE", "Edward P. Fitts Department of Industrial and Systems Engineering",
            ["Industrial and Systems Engineering"],
            "https://ise.ncsu.edu/directory/"),
        _v4_group("NE", "Department of Nuclear Engineering",
                  ["Nuclear Engineering"], "https://ne.ncsu.edu"),
        _wp("BAE", "Department of Biological and Agricultural Engineering",
            ["Biological and Agricultural Engineering"],
            "https://bae.ncsu.edu", "3"),
        # ---- College of Sciences -------------------------------------------
        _wp("PY", "Department of Physics and Astronomy", ["Physics"],
            "https://physics.sciences.ncsu.edu", "3"),
        _wp("MA", "Department of Mathematics", ["Mathematics"],
            # teaching-faculty (273) verified a subset of faculty (9).
            "https://math.sciences.ncsu.edu", "9"),
        _wp("CH", "Department of Chemistry", ["Chemistry"],
            "https://chemistry.sciences.ncsu.edu", "4"),
        _wp("ST", "Department of Statistics", ["Statistics"],
            "https://statistics.sciences.ncsu.edu", "3"),
        _wp("BIO", "Department of Biological Sciences",
            ["Biological Sciences", "Biology"],
            "https://bio.sciences.ncsu.edu", "9"),
        _wp("MEAS", "Department of Marine, Earth and Atmospheric Sciences",
            ["Marine Sciences", "Meteorology", "Geology", "Earth Sciences"],
            "https://meas.sciences.ncsu.edu", "3"),
        # ---- Wilson College of Textiles ------------------------------------
        _wp("TEX", "Wilson College of Textiles",
            ["Textile Engineering", "Polymer and Color Chemistry",
             "Fashion and Textile Management", "Textile Technology"],
            "https://textiles.ncsu.edu", "391"),
        # ---- College of Agriculture and Life Sciences (multisite) ----------
        _cals("PMB", "Department of Plant and Microbial Biology",
              ["Plant Biology", "Microbiology"], "plant-and-microbial-biology", 163),
        _cals("EPP", "Department of Entomology and Plant Pathology",
              ["Entomology", "Plant Pathology"], "entomology-and-plant-pathology", 277),
        _cals("CSS", "Department of Crop and Soil Sciences",
              ["Crop and Soil Sciences", "Agroecology and Sustainable Food Systems"],
              "crop-and-soil-sciences", 522),
        _cals("FBNS", "Department of Food, Bioprocessing and Nutrition Sciences",
              ["Food Science", "Nutrition Science"],
              "food-bioprocessing-and-nutrition-sciences", 149),
        _cals("ANS", "Department of Animal Science", ["Animal Science"],
              "animal-science", 146),
        _cals("AEC", "Department of Applied Ecology",
              ["Applied Ecology", "Biological Sciences"], "applied-ecology", 274),
        _cals("HS", "Department of Horticultural Science", ["Horticultural Science"],
              "horticultural-science", 325),
        _cals("ARE", "Department of Agricultural and Resource Economics",
              ["Agricultural Business Management", "Economics"],
              "agricultural-and-resource-economics", 571),
        _cals("MSB", "Department of Molecular and Structural Biochemistry",
              ["Biochemistry"], "molecular-and-structural-biochemistry", 219),
        _cals("PS", "Prestage Department of Poultry Science", ["Poultry Science"],
              "prestage-department-of-poultry-science", 289),
        _cals("AHS", "Department of Agricultural and Human Sciences",
              ["Agricultural and Human Sciences"], "agricultural-and-human-sciences", 131),
        # ---- College of Humanities and Social Sciences (central pool) ------
        # One college-wide person pool (dead/gradware standalone dept sites are
        # deferred above); dept attribution enrichable later via group slugs.
        _wp("CHASS", "College of Humanities and Social Sciences",
            ["Psychology", "English", "Communication", "History",
             "Political Science", "Sociology", "Anthropology", "Philosophy"],
            "https://chass.ncsu.edu", "11847"),
        # ---- College of Natural Resources (central pool) -------------------
        _cnr("FER", "Department of Forestry and Environmental Resources",
             ["Forest Management", "Environmental Sciences",
              "Fisheries, Wildlife and Conservation Biology"], 18),
        _cnr("FB", "Department of Forest Biomaterials",
             ["Paper Science and Engineering", "Sustainable Materials and Technology"], 38),
        _cnr("PRTM", "Department of Parks, Recreation and Tourism Management",
             ["Parks, Recreation and Tourism Management"], 8),
        # ---- College of Design ---------------------------------------------
        _wp("DES", "College of Design",
            ["Architecture", "Graphic and Experience Design", "Industrial Design",
             "Art and Design", "Landscape Architecture"],
            "https://design.ncsu.edu", "13"),
        # ---- College of Education ------------------------------------------
        _wp("CED", "College of Education",
            ["Elementary Education", "Mathematics Education", "Science Education",
             "Technology, Engineering and Design Education"],
            "https://ced.ncsu.edu", "4"),
        # ---- Poole College of Management -----------------------------------
        # No usable faculty term — union of the rank terms: professor (32) +
        # associate (30) + assistant (29) + professor-of-practice (577) +
        # teaching-assistant-professor (579) + research-associate (581).
        _wp("PCOM", "Poole College of Management",
            ["Business Administration", "Accounting", "Economics"],
            "https://poole.ncsu.edu", "32,30,29,577,579,581"),
        # ---- College of Veterinary Medicine (academic depts only) ----------
        _cvm("DOCS", "Department of Clinical Sciences (Vet Med)",
             ["Veterinary Medicine"], 94),
        _cvm("MBS", "Department of Molecular Biomedical Sciences (Vet Med)",
             ["Veterinary Medicine", "Biological Sciences"], 88),
        _cvm("PHP", "Department of Population Health and Pathobiology (Vet Med)",
             ["Veterinary Medicine", "Public Health"], 151),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
