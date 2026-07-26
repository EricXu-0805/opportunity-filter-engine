"""Oregon State University faculty config (via the faculty_graph engine).

Two server-rendered markup families, both plain static 200s to a bare request
(no WAF, no JS render). Live-verified 2026-07-20.

* **College of Engineering "coe-brand" people cards (EECS + MIME).**
  ``engineering.oregonstate.edu/<SCHOOL>/About/People`` is a Drupal 10 people
  view: each person is a ``div.coe-brand-people-card`` whose card body holds the
  name (``h2.coe-brand-people-card-name``), the rank as the first ``<p class=
  "mb-4-5">`` ("Associate Professor | Welty Faculty Fellow"), and — uniquely for
  this school — a real ``mailto`` inline (``p.coe-brand-people-email > a``). The
  view is a full people roster: it MIXES ladder faculty with academic advisors,
  office managers, instructors, research associates, program coordinators, deans,
  and emeriti. A ``field_filter`` on the rank paragraph (``require_present`` +
  ``include: professor|lecturer``) keeps only professor / lecturer ranks and drops
  the rest; the require_present guard means a title-less staff card can't fall
  through the engine's default-to-"Professor". The roster paginates ``?page=N``
  (39 cards/page, alphabetical), so ``paginate`` walks every page.

* **College of Science directory cards (Physics / Chemistry / Mathematics /
  Statistics).** ``<dept>.oregonstate.edu/directory`` is a Drupal directory view:
  each person is a ``div.card`` with the name in ``a.directory__title`` (the
  profile link), the home department in ``.directory__department``, and the rank
  in ``.directory__position`` — but NO email on the listing (recovered downstream
  from the profile link by the enrichment pass). These directories are heavily
  grad-student / postdoc / courtesy-faculty mixed (a page is mostly "PhD Graduate
  Student" / "Master's Graduate Student" / "Postdoc Scholar" / "Courtesy
  Faculty"), so the same ``field_filter`` on ``.directory__position`` is
  load-bearing here: it drops students, postdocs, courtesy/adjunct, and admin
  staff, keeping only the professor / lecturer ladder. Paginated ``?page=N``.

Title gate (``field_filter`` require_present + ``include: professor|lecturer``):
keeps every professor / lecturer rank (incl. Professor of Teaching, Distinguished
Professor, professor-of-practice); drops students, postdocs, courtesy/adjunct
faculty (primary appointment elsewhere), instructors, and every non-teaching staff
title. A handful of real professors listed only by an administrative title
("Associate Dean for Academic Affairs", "School Head", "Dean of the College of
Science") are dropped by the gate — accuracy over recall, so no non-ladder rows
leak in. Emeriti are additionally dropped by the engine's own retired-title gate.

Three further server-rendered families added 2026-07-26 to grow past the
original STEM core (all plain static 200s, no WAF/render):

* **College of Forestry Display-Suite directory** (own subdomain
  ``directory.forestry.oregonstate.edu``) — one college-wide roster, "Last,
  First" names, inline mailto; the site's position-type=Faculty flag leaks
  postdocs/staff so a title ladder is also applied.
* **College of Business per-department "person-teaser" pages**
  (``business.oregonstate.edu/faculty/<slug>``) — first/last split names, rank
  gate, no listing email (downstream enrichment). Nine departments.
* **College of Liberal Arts college-wide directory** — ONE directory for the
  whole college; each card carries the person's home School in ``div.school``,
  so ``department_field`` lands every record with real per-School attribution
  from a single scrape. Rank-gated; the Cloudflare-obfuscated listing email is
  recovered by the engine's cf-shield decode.

Single source ("oregonstate_faculty"); department rides each record, ids
namespaced by department short-code.

Live-verified 2026-07-20 (page-1 cards → kept-after-gate on page 1; full run
paginates every page): EECS 39→16, MIME 39→14, Physics 36→3 (grad-heavy),
Chemistry 36→6, Mathematics 56→9, Statistics 36→9. EECS + MIME publish a real
mailto per card (~100% email on the kept engineering faculty); the College of
Science directories publish none on the listing (name+title only — emails come
from the downstream profile-enrichment pass via the directory__title link).

Deferred (phase-2, live-verified 2026-07-26): the entire College of
Agricultural Sciences (Animal & Rangeland Sciences, Crop & Soil Science,
Horticulture, Fisheries/Wildlife/Conservation Sciences, Food Science &
Technology, Applied Economics) plus Botany & Plant Pathology run the legacy
Drupal-7 "larch" AJAX view — the GET returns only the filter shell and an empty
view (rows inject client-side), so they need headless render or a bespoke
/views/ajax POST. CEOAS + Veterinary Medicine share the madrone directory but
keep the rank as a bare text node (no selectable element) so their
courtesy/DVM/resident-heavy rosters can't be rank-gated cleanly; Public Health &
Human Sciences is on the same template but very staff-heavy; Pharmacy is a small
A-Z-paginated directory with cf-obfuscated email — all await a rank-bearing
selector or their own pass. The central directory.oregonstate.edu is SAML
login-gated and deliberately avoided.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- College of Engineering "coe-brand" people card (EECS + MIME) ----------
# Rank is the first <p class="mb-4-5"> under the card body; email is an inline
# mailto in p.coe-brand-people-email. The roster mixes staff, so gate on the
# rank paragraph: require it present (a title-less staff card can't default to
# "Professor") and keep only professor/lecturer ranks.
_COE_SEL = {
    "card": "div.coe-brand-people-card",
    "name": "h2.coe-brand-people-card-name",
    "link": "a[href]",
    "title": "p.mb-4-5",
    "email": "p.coe-brand-people-email a[href^='mailto:']",
}
_COE_FIELD = {
    "selector": "p.mb-4-5",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- College of Science directory card (Physics/Chem/Math/Stat) ------------
# Name + profile link in a.directory__title; rank in .directory__position; no
# email on the listing. The directories are grad/postdoc/courtesy heavy, so the
# same rank gate on .directory__position is the load-bearing filter.
_SCI_SEL = {
    "card": "div.card",
    "name": "a.directory__title",
    "link": "a.directory__title",
    "title": "div.directory__position",
}
_SCI_FIELD = {
    "selector": "div.directory__position",
    "require_present": True,
    "include": r"professor|lecturer",
}

# Drupal ``?page=N`` query pagination (39/36/56 cards per page, alphabetical);
# the engine walks pages until one surfaces no new (name, url) pair.
_PAGINATE = {"param": "page"}


def _coe(short: str, name: str, majors: list[str], url: str) -> dict:
    """A College of Engineering school on the shared coe-brand people card."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _COE_SEL,
                   "field_filter": _COE_FIELD, "paginate": _PAGINATE},
    }


def _sci(short: str, name: str, majors: list[str], url: str) -> dict:
    """A College of Science department on the shared directory card."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SCI_SEL,
                   "field_filter": _SCI_FIELD, "paginate": _PAGINATE},
    }


# ---- College of Forestry Display-Suite directory (own subdomain) -----------
# directory.forestry.oregonstate.edu is one college-wide Drupal Display-Suite
# view: name is "Last, First" (name_flip), rank in the job-title field, email
# inline. The site's own position-type field flags Faculty vs Staff/Graduate
# Student, but it leaks postdocs and a few staff, so a title ladder
# (professor/lecturer/instructor, minus courtesy/emeritus/adjunct/postdoc) is
# also applied. 25 cards per page, ``?page=N``.
_FOR_SEL = {
    "card": "div.views-row",
    "name": "div.field--name-node-title h2 a",
    "link": "div.field--name-node-title h2 a",
    "title": "div.field--name-field-person-job-title .field__item",
    "email": "div.field--name-field-person-email .field__item a[href^='mailto:']",
}
_FOR_FIELD = {
    "selector": "div.field--name-field-person-position-type .field__item",
    "require_present": True,
    "include": r"Faculty",
}
_FOR_LADDER = {"require": r"professor|lecturer|instructor",
               "drop": r"courtesy|emerit|adjunct|postdoc"}

# ---- College of Business per-department "person-teaser" pages ---------------
# business.oregonstate.edu/faculty/<slug> server-renders an article.person-teaser
# list; the name is split across first/last name cells (name + name_last), the
# rank is field-position, no listing email (downstream enrichment). Mixes staff,
# so the same professor/lecturer rank gate applies. One page per department.
_BUS_SEL = {
    "card": "article.person-teaser",
    "name": "div.field-name-field-first-name",
    "name_last": "div.field-name-field-last-name",
    "link": "div.person-image a[href]",
    "title": "div.field-name-field-position",
}
_BUS_FIELD = {
    "selector": "div.field-name-field-position",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- College of Liberal Arts college-wide directory (madrone) --------------
# liberalarts.oregonstate.edu/directory is ONE directory for the whole college;
# each card carries the person's home School in ``div.school``, so a single
# scrape lands with real per-School department attribution (``department_field``).
# Rank in ``div.position`` (gated), email is Cloudflare-obfuscated (the engine's
# cf-shield decode recovers it from ``p.dir-email a``). ``?page=N``.
_CLA_SEL = {
    "card": "div.views-field.views-field-nothing",
    "name": "div.dir-name a",
    "link": "div.dir-name a",
    "title": "div.position",
    "email": "p.dir-email a",
    "department_field": "div.school",
}
_CLA_FIELD = {
    "selector": "div.position",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _for(short: str, name: str, majors: list[str], url: str) -> dict:
    """The College of Forestry Display-Suite college-wide directory."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _FOR_SEL, "name_flip": True,
                   "field_filter": _FOR_FIELD, "ladder_filter": _FOR_LADDER,
                   "paginate": _PAGINATE},
    }


def _bus(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A College of Business department (business.oregonstate.edu/faculty/<slug>)."""
    url = f"https://business.oregonstate.edu/faculty/{slug}"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _BUS_SEL, "field_filter": _BUS_FIELD},
    }


SCHOOL: dict = {
    "school_slug": "oregonstate",
    "source": "oregonstate_faculty",
    "organization": "Oregon State University",
    "location": "Corvallis, OR",
    "id_prefix": "oregonstate",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Oregon State University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering (coe-brand, email inline) ---------------
        _coe("EECS", "School of Electrical Engineering and Computer Science",
             ["Electrical and Computer Engineering", "Computer Science",
              "Electrical Engineering", "Computer Engineering"],
             "https://engineering.oregonstate.edu/EECS/About/People"),
        _coe("MIME", "School of Mechanical, Industrial, and Manufacturing Engineering",
             ["Mechanical Engineering", "Industrial Engineering",
              "Manufacturing Engineering", "Energy Systems Engineering"],
             "https://engineering.oregonstate.edu/MIME/About/People"),
        _coe("CBEE", "School of Chemical, Biological, and Environmental Engineering",
             ["Chemical Engineering", "Bioengineering", "Environmental Engineering"],
             "https://engineering.oregonstate.edu/CBEE/About/People"),
        _coe("CCE", "School of Civil and Construction Engineering",
             ["Civil Engineering", "Construction Engineering Management"],
             "https://engineering.oregonstate.edu/CCE/About/People"),
        _coe("NSE", "School of Nuclear Science and Engineering",
             ["Nuclear Engineering", "Radiation Health Physics"],
             "https://engineering.oregonstate.edu/NSE/About/People"),
        # ---- College of Science (directory card, no listing email) ----------
        _sci("PHYS", "Department of Physics", ["Physics"],
             "https://physics.oregonstate.edu/directory"),
        _sci("CHEM", "Department of Chemistry", ["Chemistry"],
             "https://chemistry.oregonstate.edu/directory"),
        _sci("MATH", "Department of Mathematics",
             ["Mathematics", "Applied Mathematics"],
             "https://math.oregonstate.edu/directory"),
        _sci("STAT", "Department of Statistics", ["Statistics", "Data Science"],
             "https://stat.oregonstate.edu/directory"),
        _sci("BB", "Department of Biochemistry and Biophysics",
             ["Biochemistry", "Biophysics"],
             "https://biochem.oregonstate.edu/directory"),
        _sci("MICRO", "Department of Microbiology", ["Microbiology"],
             "https://microbiology.oregonstate.edu/directory"),
        _sci("IB", "Department of Integrative Biology",
             ["Integrative Biology", "Zoology", "Botany"],
             "https://ib.oregonstate.edu/directory"),
        # ---- College of Forestry (Display-Suite college-wide directory) -----
        _for("FOR", "College of Forestry",
             ["Forestry", "Forest Ecosystems and Society",
              "Forest Engineering, Resources and Management",
              "Wood Science and Engineering"],
             "https://directory.forestry.oregonstate.edu/"),
        # ---- College of Business (per-department person-teaser pages) -------
        _bus("ACTG", "College of Business — Accounting", ["Accounting"], "accounting"),
        _bus("FIN", "College of Business — Finance", ["Finance"], "finance"),
        _bus("MGMT", "College of Business — Management",
             ["Management"], "management"),
        _bus("MKTG", "College of Business — Marketing", ["Marketing"], "marketing"),
        _bus("BANA", "College of Business — Business Analytics",
             ["Business Analytics"], "business-analytics"),
        _bus("BIS", "College of Business — Business Information Systems",
             ["Business Information Systems"], "business-information-systems"),
        _bus("DSGN", "College of Business — Design and Merchandising Management",
             ["Design", "Merchandising Management"], "design"),
        _bus("IE", "College of Business — Innovation and Entrepreneurship",
             ["Innovation", "Entrepreneurship"], "innovation-and-entrepreneurship"),
        _bus("SCLM", "College of Business — Supply Chain and Logistics Management",
             ["Supply Chain Management", "Logistics"],
             "supply-chain-and-logistics-management"),
        # ---- College of Liberal Arts (one directory, split by home School) --
        {
            "short": "CLA", "name": "College of Liberal Arts",
            "majors": ["Political Science", "Public Policy", "History",
                       "Philosophy", "Religious Studies", "Psychology",
                       "Communication", "Art", "Music", "Design",
                       "English", "Writing", "Anthropology", "Sociology",
                       "Ethnic Studies", "Women, Gender and Sexuality Studies",
                       "Languages"],
            "directory_url": "https://liberalarts.oregonstate.edu/directory",
            "scrape": {
                "url": "https://liberalarts.oregonstate.edu/directory",
                "selectors": _CLA_SEL,
                "field_filter": _CLA_FIELD,
                "paginate": _PAGINATE,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
