"""University of Minnesota Twin Cities faculty config (via the faculty_graph engine).

UMN's directories are Cloudflare-fronted but fully server-rendered (no JS
challenge for a desktop UA); the only Cloudflare artifact is email obfuscation
(``span.__cf_email__`` / ``data-cfemail`` hex), which the engine's
``_decode_cfemail`` handles. Rate limiting is real (bursts of ~8-10 requests
draw HTTP 429 on cse/cla.umn.edu and connection resets on CFANS subdomains),
so every department carries a ``pre_delay``. Five markup families, verified
live 2026-07-17:

* College of Science & Engineering (cse.umn.edu) Drupal "Folwell" people-list:
  ``div.views-row`` cards with the name link on ``.pl-item.people-title a``,
  the rank on ``.pl-item.people-jobroles``, and a Cloudflare-shielded email on
  the listing itself. Dept ``/faculty`` pages are faculty-only; the ``/people``
  pages (CEMS, AEM) and ISyE append Emeritus/Affiliated/Adjunct sections under
  their own ``h2`` headings ("Adjuct Faculty" [sic] on ISyE — the exclude
  matches the ``adju`` stem), gated out by an exclude ``section_filter``.
  Profile bios are prose (POISON as tags) — no research enrich here; topics
  come from the OpenAlex pass.

* College of Liberal Arts modern "teaser-grid" (9 depts): faculty-only
  ``/people/faculty`` pages of ``article.user--view-mode-teaser-grid`` cards
  (name on ``h3.user--display-name a``, rank on ``.field--name-field-role-
  title``); no email or research at listing tier. Profiles (shared
  ``/about/directory/profile/<uid>``) carry a CLEAN specialties tag list and a
  shielded email — recovered by the gated per-profile pass.

* College of Liberal Arts legacy directory-table (6 depts): ``main table tr``
  rows (Name+rank cell | contact | specialty). The core-faculty table's nearest
  preceding ``h2`` is sidebar nav ("In This Section"), while Affiliate /
  Adjunct & Visiting / Emeritus tables sit under their own ``h2`` headings —
  so the gate is exclude-based. The rank follows the name behind a ``<br>``
  (no element of its own) → ``title_re`` over the row text. The Specialty
  column is clean comma-split tags, kept at listing tier.

* Hubbard School (HSJMC) variant of the same profiles: ``div.views-row
  .table-cell`` blocks, "Last, First" names (``name_flip``), rank inside the
  first ``<p>`` ahead of endowed-fellow lines → ``title_re``; a require-gate
  drops the one "Senior Fellow".

* College of Biological Sciences: ONE college-wide paginated directory
  (``/directory/faculty?page=N``, 0-indexed, 50/page) covering all five CBS
  departments; each card carries a department label (``.cbs-list--
  department``) so the five dept entries partition the shared roster via
  ``field_filter`` (which also drops the lone "Dean's Office" card). Email is
  on the listing; profile bios are prose — no enrich.

* CFANS dept subdomains (10 depts; bbe/ansci/agronomy.cfans/…): shared Drupal
  "unit" theme, faculty-only 3-column table (Name+rank | Areas of Interest |
  Email). The Areas-of-Interest column is CLEAN comma-split tags and the email
  is on the listing, so this family lands fully-keyworded + emailed in one
  pass.

Single source ("umn_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred (from the recon pass, reasons verbatim-condensed):

* Carlson School of Management — single faculty+PhD directory with name-only
  listing cards; role/dept facet params don't filter server-side, so a clean
  faculty-only ladder gate isn't URL-addressable (role would need per-profile
  fetches). Accuracy-risky; needs a dedicated pass.
* College of Design — ~25-page directory mixing Faculty/Adjunct/Staff/GAs/
  Emeriti; the position facet doesn't filter via GET, and the gate would be a
  fragile title-regex on a concatenated "Name Role, Program" cell.
* CEHD (Ed Psych, C&I, Family Social Science, Kinesiology, ICD) — college
  directory's Faculty facet is not reliably URL-addressable; dept subsites
  each use a slightly different theme and mix teaching specialists — per-dept
  recon needed.
* Medical School, School of Public Health, Nursing, Pharmacy, Dentistry,
  Veterinary Medicine, Law, Humphrey School — large clinical/professional
  schools on separate sites, not fetched in the recon pass; basic-science
  Medical School depts are undergrad-relevant but need a scoped pass.
* CCAPS — primarily non-tenure instructional programs; low research-faculty
  density.
* CLA humanities depts with variant slugs (Art History, CNES, GNSD, AMES,
  GWSS, Comm Studies, Writing Studies, CSCL, American Indian Studies,
  Afro-American Studies, HSTM) — same two CLA families certainly apply, but
  the exact ``/people/faculty`` slugs 404'd or 429'd before live confirmation;
  re-probe each real slug with throttling.
* CFANS Applied Economics + centers — expected to match the CFANS table
  family but unconfirmed live.
"""

from __future__ import annotations

from .. import faculty_graph

# Rank extracted from flowed text (table cells / HSJMC <p> blocks) where the
# title has no element of its own. "Senior Fellow" and the postdoc ranks are
# deliberately in the alternation so non-ladder people are EXTRACTED and then
# dropped by the gates (an unmatched title defaults to "Professor" and would
# slip through — FWCB's "Postdoctoral Fellow" did exactly that before).
_RANK_RE = (
    r"\b((?:(?:Regents|Distinguished|McKnight|University|Assistant|Associate|"
    r"Adjunct|Visiting|Teaching|Research|Extension|Clinical)\s+)*"
    r"Professor(?:\s+Emerit\w+)?|Senior\s+Lecturer|Senior\s+Fellow|Lecturer|Instructor"
    r"|Postdoctoral\s+(?:Fellow|Associate|Researcher|Scholar))\b"
)

# "affiliat" also catches per-card "Affiliate Faculty" role titles (Geography's
# grid and CBS cards carry them with no section/field to gate on); an
# affiliate's primary appointment lives in another unit's directory.
_LADDER = {"drop": r"emerit|adjunct|visiting|postdoc|affiliat"}

# Emeritus/Affiliated/Adjunct groups sit under their own h2 on the pages that
# have them ("Adjuct" [sic] on ISyE — hence the adju stem; Statistics adds
# "Associate Faculty" = other-dept members and a "Postdocs" table); core
# faculty's nearest h2 is nav ("Breadcrumb"/"In This Section"), so the gate
# must be exclude-based, never include-based.
# ("memoriam": CS appends an "In Memoriam" h2 of deceased faculty whose cards
# have no jobroles element — they'd default-pass as "Professor".)
_SECTION_EXCLUDE = {
    "heading": "h2",
    "exclude": r"emerit|adju|affiliat|visiting|postdoc|associate faculty|instructional|memoriam",
}

# Shared /about/directory/profile/<uid> pages: clean specialties tag list +
# Cloudflare-shielded email. The person's OWN address is ``field--name-mail``;
# ``field--name-field-email`` is the shared unit inbox (cla@umn.edu) — one
# alias on hundreds of professors would also collapse them in the email
# dedupe. Gated behind OFE_ENRICH_PROFILES (richer-dedup keeps the enriched
# records, so the cost is paid once).
_CLA_ENRICH = {
    "email_selector": ".field--name-mail span.__cf_email__",
    "email_drop": r"^[^@]*$|^cla@|department@",
    "research_items_selector": ".field--name-field-specialties .field__item",
    "throttle": 0.3,
}

# ---- CSE Folwell people-list (cse.umn.edu) ---------------------------------
_CSE_SELECTORS = {
    "card": "div.views-row",
    "name": ".pl-item.people-title a",
    "link": ".pl-item.people-title a",
    "title": ".pl-item.people-jobroles",
    "email": "[data-cfemail]",
}

# ---- CLA teaser-grid -------------------------------------------------------
_CLA_GRID_SELECTORS = {
    "card": "article.user--view-mode-teaser-grid",
    "name": "h3.user--display-name a",
    "link": "h3.user--display-name a",
    "title": ".field--name-field-role-title",
}

# ---- CLA legacy directory-table --------------------------------------------
_CLA_TABLE_SELECTORS = {
    "card": "main table tr",
    "name": "td:first-child a",
    "link": "td:first-child a",
    "title_re": _RANK_RE,
    "research": "td:nth-of-type(3)",
    "email": "[data-cfemail]",
}

# ---- CBS college-wide directory --------------------------------------------
_CBS_SELECTORS = {
    "card": "div.views-row",
    "name": ".cbs-list--directory-title a",
    "link": ".cbs-list--directory-title a",
    "title": ".cbs-list--position-title",
    "email": "[data-cfemail]",
}

# ---- CFANS dept-subdomain table --------------------------------------------
_CFANS_SELECTORS = {
    "card": "table tr",
    "name": "td.views-field-title a",
    "link": "td.views-field-title a",
    "title_re": _RANK_RE,
    "research": "td.views-field-field-areas-of-interest",
    "email": "[data-cfemail]",
}


def _cse(short: str, name: str, majors: list[str], path: str) -> dict:
    """A College of Science & Engineering department (Folwell people-list)."""
    url = f"https://cse.umn.edu{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CSE_SELECTORS,
                       "section_filter": _SECTION_EXCLUDE, "ladder_filter": _LADDER,
                       "pre_delay": 1.5}}


def _grid(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A CLA department on the modern teaser-grid theme (faculty-only page)."""
    url = f"https://cla.umn.edu/{slug}/people/faculty"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CLA_GRID_SELECTORS,
                       "ladder_filter": _LADDER, "profile_enrich": _CLA_ENRICH,
                       "pre_delay": 1.5}}


def _table(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A CLA department on the legacy directory-table theme."""
    url = f"https://cla.umn.edu/{slug}/people/faculty"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CLA_TABLE_SELECTORS,
                       "section_filter": _SECTION_EXCLUDE, "ladder_filter": _LADDER,
                       "profile_enrich": _CLA_ENRICH, "pre_delay": 1.5}}


def _cbs(short: str, name: str, majors: list[str], dept_label: str) -> dict:
    """One CBS department, partitioned out of the shared college directory by
    its per-card department label (also drops the Dean's Office card)."""
    url = "https://cbs.umn.edu/directory/faculty"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CBS_SELECTORS,
                       "field_filter": {"selector": ".cbs-list--department",
                                        "include": dept_label},
                       "ladder_filter": _LADDER,
                       "paginate": {"param": "page", "start": 1, "max": 5},
                       "pre_delay": 1.5}}


def _cfans(short: str, name: str, majors: list[str], url: str) -> dict:
    """A CFANS department subdomain (3-column faculty table, clean tags)."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CFANS_SELECTORS,
                       "ladder_filter": _LADDER, "pre_delay": 1.0}}


SCHOOL: dict = {
    "school_slug": "umn",
    "source": "umn_faculty",
    "organization": "University of Minnesota Twin Cities",
    "location": "Minneapolis, MN",
    "id_prefix": "umn",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Minnesota Twin Cities) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Science & Engineering ------------------------------
        _cse("CS", "Computer Science & Engineering",
             ["Computer Science", "Data Science"], "/cs/faculty"),
        _cse("ECE", "Electrical & Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], "/ece/ece-faculty-0"),
        _cse("ME", "Mechanical Engineering", ["Mechanical Engineering"], "/me/faculty"),
        _cse("BME", "Biomedical Engineering", ["Biomedical Engineering"], "/bme/faculty"),
        _cse("CEMS", "Chemical Engineering & Materials Science",
             ["Chemical Engineering", "Materials Science & Engineering"], "/cems/people"),
        _cse("AEM", "Aerospace Engineering & Mechanics",
             ["Aerospace Engineering & Mechanics"], "/aem/aem-faculty-page-0"),
        _cse("Chem", "Chemistry", ["Chemistry"], "/chem/core-faculty"),
        _cse("Physics", "Physics & Astronomy", ["Physics", "Astronomy"],
             "/physics/physics-astronomy-faculty"),
        _cse("Math", "School of Mathematics", ["Mathematics"], "/math/faculty"),
        _cse("ISyE", "Industrial & Systems Engineering",
             ["Industrial Engineering", "Data Science"], "/isye/faculty"),
        _cse("CEGE", "Civil, Environmental & Geo- Engineering",
             ["Civil Engineering", "Environmental Engineering"], "/cege/faculty-0"),
        _cse("ESci", "Earth & Environmental Sciences",
             ["Earth Sciences", "Environmental Sciences"], "/esci/faculty"),
        # ---- College of Liberal Arts (teaser-grid) -------------------------
        _grid("Psych", "Psychology", ["Psychology", "Neuroscience"], "psychology"),
        _grid("Soc", "Sociology", ["Sociology"], "sociology"),
        _grid("Ling", "Linguistics", ["Linguistics"], "linguistics"),
        _grid("Hist", "History", ["History"], "history"),
        _grid("Engl", "English", ["English"], "english"),
        _grid("Geog", "Geography, Environment & Society", ["Geography"], "geography"),
        _grid("Art", "Art", ["Art"], "art"),
        _grid("FrIt", "French & Italian", ["French", "Italian"], "french-italian"),
        _grid("SpanPort", "Spanish & Portuguese Studies",
              ["Spanish", "Portuguese"], "spanish-portuguese"),
        # ---- College of Liberal Arts (directory-table) ---------------------
        _table("Econ", "Economics", ["Economics"], "economics"),
        _table("PolSci", "Political Science", ["Political Science"], "polisci"),
        _table("Phil", "Philosophy", ["Philosophy"], "philosophy"),
        _table("Stat", "School of Statistics", ["Statistics", "Data Science"],
               "statistics"),
        _table("Anth", "Anthropology", ["Anthropology"], "anthropology"),
        _table("AmStud", "American Studies", ["American Studies"], "american-studies"),
        # ---- Hubbard School (views-row variant of the table family) --------
        {
            "short": "HSJMC",
            "name": "Hubbard School of Journalism & Mass Communication",
            "majors": ["Journalism & Mass Communication"],
            "directory_url": "https://cla.umn.edu/hsjmc/people/faculty",
            "scrape": {
                "url": "https://cla.umn.edu/hsjmc/people/faculty",
                "selectors": {"card": "div.views-row.table-cell", "name": "h4 a",
                              "link": "h4 a", "title_re": _RANK_RE,
                              "email": "[data-cfemail]"},
                "name_flip": True,
                # Require a real rank: the roster's one "Senior Fellow" must not
                # default-pass as "Professor".
                "ladder_filter": {"require": r"\bprofessor\b|\blecturer\b|\binstructor\b",
                                  "drop": r"emerit|adjunct|visiting"},
                "profile_enrich": _CLA_ENRICH,
                "pre_delay": 1.5,
            },
        },
        # ---- College of Biological Sciences (shared directory) -------------
        _cbs("CBS-GCD", "Genetics, Cell Biology & Development",
             ["Genetics, Cell Biology & Development", "Biology"],
             r"Genetics,\s*Cell Biology"),
        _cbs("CBS-BMBB", "Biochemistry, Molecular Biology & Biophysics",
             ["Biochemistry", "Biophysics"], r"Biochemistry"),
        _cbs("CBS-EEB", "Ecology, Evolution & Behavior",
             ["Ecology, Evolution & Behavior", "Biology"], r"Ecology"),
        _cbs("CBS-PMB", "Plant & Microbial Biology",
             ["Plant Biology", "Microbiology"], r"Plant and Microbial"),
        _cbs("CBS-BTL", "Biology Teaching & Learning", ["Biology"],
             r"Biology Teaching"),
        # ---- CFANS dept subdomains -----------------------------------------
        _cfans("BBE", "Bioproducts & Biosystems Engineering",
               ["Bioproducts & Biosystems Engineering"],
               "https://bbe.umn.edu/people/faculty"),
        _cfans("AnSci", "Animal Science", ["Animal Science"],
               "https://ansci.umn.edu/about/people/faculty"),
        _cfans("Agron", "Agronomy & Plant Genetics", ["Agronomy & Plant Genetics"],
               "https://agronomy.cfans.umn.edu/people/faculty"),
        _cfans("FScN", "Food Science & Nutrition", ["Food Science", "Nutrition"],
               "https://fscn.cfans.umn.edu/people/faculty"),
        _cfans("Forest", "Forest Resources", ["Forest & Natural Resource Management"],
               "https://forestry.umn.edu/people/faculty"),
        _cfans("Hort", "Horticultural Science", ["Horticulture"],
               "https://horticulture.umn.edu/people/faculty"),
        _cfans("PlPa", "Plant Pathology", ["Plant Pathology", "Plant Biology"],
               "https://plpa.cfans.umn.edu/people/faculty"),
        _cfans("FWCB", "Fisheries, Wildlife & Conservation Biology",
               ["Fisheries & Wildlife"], "https://fwcb.cfans.umn.edu/faculty"),
        _cfans("Entom", "Entomology", ["Entomology"],
               "https://entomology.umn.edu/faculty"),
        _cfans("SWAC", "Soil, Water & Climate",
               ["Environmental Sciences", "Soil Science"],
               "https://swac.umn.edu/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
