"""University of Nebraska-Lincoln faculty config (via the faculty_graph engine).

Every UNL department directory renders on ONE campus-wide UNLcms component — a
Drupal "unlcms-teaser-person" teaser wrapped in a schema.org/Person list item.
All ten departments below (School of Computing + five engineering departments on
the engineering.unl.edu / bse.unl.edu CMS, plus Physics & Astronomy, Chemistry,
Mathematics and Statistics on the College of Arts & Sciences subdomains) share
the identical markup, so one shared selector set + one title gate covers them all.
Live-verified 2026-07-20 — every page is a plain server-rendered 200 through the
proxy (no WAF, no JS render).

One card is ``li[itemscope itemtype="…/schema.org/Person"]`` (the inner
``div.unlcms-teaser-person`` carries ``data-uid`` = netid = email local-part and a
``data-preferred-name`` attribute). Inside it:

* an ``a.dcf-card-link[itemprop="name"]`` whose direct anchor text is only
  whitespace — the display name lives in an inner ``<span>``, so the name selector
  targets ``… span`` (the anchor itself is the profile ``/person/<slug>/`` link,
  RELATIVE to each department host, resolved by the engine's ``urljoin`` against
  that department's own listing URL);
* a ``span[itemprop="jobTitle"]`` with the rank (the reliable gate field);
* a plain ``mailto:`` inside the card ``<address>`` — no Cloudflare / hex / base64
  obfuscation anywhere on any UNL page, so email coverage is high wherever the
  listing exposes an address (~90-100% of kept faculty on every department except
  Physics, whose grid omits the address for many rows — those recover on the
  downstream per-profile enrichment pass).

Title gate (``field_filter``, require ``professor|lecturer|instructor``): the
directories interleave ladder faculty with emeriti, adjuncts, and a large block
of non-teaching staff (project managers, systems managers, academic advisors,
grants coordinators, communications associates) — Mathematics alone lists 153
people of whom only ~40 are professors. A ``field_filter`` (not ``ladder_filter``)
is used so a title-less staff card can't fall through the engine's
default-to-"Professor": ``require_present`` reads ``span[itemprop='jobTitle']``
directly and drops the card when the rank is absent/blank, then ``include`` keeps
only Professor / Lecturer / Instructor ranks (endowed-chair and
professor-of-practice titles still contain "Professor"). Emeriti that carry the
word "Professor" are additionally dropped by the engine's own retired-title guard.

Single source ("unl_faculty"); department rides each record, ids namespaced by
department short-code. The intra-batch dedup collapses the leadership
featured-card duplicate some departments render (same name → same id → same
email/url), so a chair listed twice lands once.

Live-verified 2026-07-20 (page cards → kept-after-gate → deduped in the deep=True
run): CSE 78/49, ECE 53/32, MME 49/37, CEE 58/34, CHME 22/13, BSE 88/41,
PHYS 50/25, CHEM 40/27, MATH 153/40, STAT 23/14 → 312 total, 98% emailed. The
CEE gate keeps 46 but the batch dedup collapses 9 leadership featured-card
duplicates plus a few cross-department joint appointments to 34; the same joint-
appointment dedup trims CHME 15→13 and MME 39→37.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared UNLcms "unlcms-teaser-person" teaser — identical markup on every
# department host. The name anchor's own text is whitespace (the visible name is
# in an inner <span>), so the name selector reaches the span; the anchor is the
# /person/<slug>/ profile link. Email is a plain mailto inside the card <address>.
_SEL = {
    "card": 'li[itemtype*="schema.org/Person"]',
    "name": 'a.dcf-card-link[itemprop="name"] span',
    "link": 'a.dcf-card-link[itemprop="name"]',
    "title": 'span[itemprop="jobTitle"]',
    "email": 'address a[href^="mailto:"]',
}

# Keep Professors (ladder + of-practice + research + endowed-chair) and any
# Lecturer / Instructor; drop the staff, adjuncts, and admin the directories mix
# in. field_filter (not ladder_filter) so a title-less staff card can't fall
# through the engine's default-to-"Professor": require_present reads the jobTitle
# span directly and drops the card when absent/blank; include then keeps only
# Professor/Lecturer/Instructor ranks. Emeriti are additionally dropped by the
# engine's retired-title guard.
_FIELD = {
    "selector": 'span[itemprop="jobTitle"]',
    "require_present": True,
    "include": r"professor|lecturer|instructor",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A UNL department on the shared unlcms-teaser-person component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


SCHOOL: dict = {
    "school_slug": "unl",
    "source": "unl_faculty",
    "organization": "University of Nebraska-Lincoln",
    "location": "Lincoln, NE",
    "id_prefix": "unl",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Nebraska-Lincoln) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering ---------------------------------------
        _dept("CSE", "School of Computing",
              ["Computer Science", "Computer Engineering", "Software Engineering",
               "Data Science"],
              "https://computing.unl.edu/directory/"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://engineering.unl.edu/ece/about/faculty-staff/"),
        _dept("MME", "Department of Mechanical and Materials Engineering",
              ["Mechanical Engineering", "Materials Engineering", "Materials Science"],
              "https://engineering.unl.edu/mme/about/faculty-staff/"),
        _dept("CEE", "Department of Civil and Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              "https://engineering.unl.edu/civil/about/faculty-staff/"),
        _dept("CHME", "Department of Chemical and Biomolecular Engineering",
              ["Chemical Engineering", "Biomolecular Engineering"],
              "https://engineering.unl.edu/chme/about/faculty-staff/"),
        _dept("BSE", "Department of Biological Systems Engineering",
              ["Biological Systems Engineering", "Agricultural Engineering",
               "Biomedical Engineering"],
              "https://bse.unl.edu/our-people/faculty-directory/"),
        # ---- College of Arts & Sciences -----------------------------------
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy", "Astrophysics"],
              "https://physics.unl.edu/about/directory/"),
        _dept("CHEM", "Department of Chemistry",
              ["Chemistry", "Biochemistry"],
              "https://chem.unl.edu/research/faculty/"),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics"],
              "https://math.unl.edu/about/directory/"),
        _dept("STAT", "Department of Statistics",
              ["Statistics", "Data Science"],
              "https://statistics.unl.edu/faculty/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
