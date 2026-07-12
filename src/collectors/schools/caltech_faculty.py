"""Caltech faculty config (via the faculty_graph engine).

All six divisions (and every EAS/PMA option site) run one shared Caltech CMS:
a ``div.person-teaser`` card with name + profile link in
``a.person-teaser__link`` and rank in ``div.person-teaser__job-title`` —
plain server-rendered HTML everywhere (no headless browser, no bot wall).
Where the platform's ``?category=`` filter is server-side (PMA, GPS, HSS,
BBE) the listing is pre-filtered to professorial faculty; where it is
client-side JS only (aph.caltech.edu) or absent, the ladder filter does the
cut. Card hrefs carry ``?back_url=…`` navigation state, stripped via
``link_strip_query`` so joint appointments dedupe on one canonical URL.

Emails: NO division publishes a ``mailto:`` anywhere — profile pages hold the
address behind Cloudflare's email-protection shield (``data-cfemail`` hex),
decoded by the engine's ``_decode_cfemail``. The gated per-profile pass
(OFE_ENRICH_PROFILES) recovers email + the profile's Research Summary prose;
the selector MUST stay scoped to ``div.field__email`` or assistants' addresses
(under ``.person-page2__assistants__email``) would be picked up instead.

Single source ("caltech_faculty"); division/option rides each record's
``department``. Audience "unknown" (per-professor openness).
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Caltech CMS person-teaser theme (all divisions + option sites).
_CT_SEL = {"card": "div.person-teaser", "name": "a.person-teaser__link",
           "link": "a.person-teaser__link", "title": "div.person-teaser__job-title",
           "link_strip_query": True}
# Keep the professorial ladder (incl. named chairs and Research/Teaching
# Professors); drop emeriti ("…, Emeritus"), lecturers, visitors, postdocs,
# instructors, and staff. Non-professor titles (Scientist/Engineer/
# Administrator) already fail the require gate.
_CT_LADDER = {"require": r"\bprofessor\b",
              "drop": r"\bemerit|\blecturer|\bvisiting|\badjunct|\binstructor|\bpostdoc|\bstaff\b"}
# Per-profile pass: Cloudflare-shielded email + Research Summary prose.
# Caltech's robots.txt asks Crawl-delay: 10 — the monthly enrich is the only
# bulk-profile consumer, so keep the throttle generous.
_CT_ENRICH = {"email_selector": "div.field__email span.__cf_email__",
              "research_selector": "div.field__research_summary",
              "throttle": 1.5}


def _ct(short: str, name: str, majors: list[str], url: str,
        paginate: dict | None = None) -> dict:
    scrape: dict = {"url": url, "selectors": _CT_SEL, "ladder_filter": _CT_LADDER,
                    "profile_enrich": _CT_ENRICH}
    if paginate:
        scrape["paginate"] = paginate
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "caltech",
    "source": "caltech_faculty",
    "organization": "California Institute of Technology",
    "location": "Pasadena, CA",
    "id_prefix": "caltech",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Caltech) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # --- PMA: server-side option+rank filter (782/784/783 × 773) ---
        _ct("PHYS", "Physics", ["Physics", "Applied Physics"],
            "https://www.pma.caltech.edu/people?search=&category=782&category=773&category=&submit=Search"),
        _ct("MATH", "Mathematics", ["Mathematics", "Applied Mathematics"],
            "https://www.pma.caltech.edu/people?search=&category=784&category=773&category=&submit=Search"),
        _ct("ASTRO", "Astronomy", ["Astronomy", "Astrophysics"],
            "https://www.pma.caltech.edu/people?search=&category=783&category=773&category=&submit=Search"),
        # PMA research faculty (Research Professors) live under their own rank
        # category, outside the professorial filter above.
        _ct("PMA-RF", "Physics, Mathematics & Astronomy (Research Faculty)",
            ["Physics", "Mathematics", "Astronomy"],
            "https://www.pma.caltech.edu/people?category=775"),
        # --- BBE: category 194 = all professorial + research/teaching profs ---
        _ct("BBE", "Biology & Biological Engineering",
            ["Biology", "Bioengineering", "Neuroscience", "Biochemistry"],
            "https://www.bbe.caltech.edu/people?search=&category=194&submit=Search"),
        # --- CCE: directory mounts at /faculty (curated professorial list) ---
        _ct("CCE", "Chemistry & Chemical Engineering",
            ["Chemistry", "Chemical Engineering", "Biochemistry"],
            "https://cce.caltech.edu/faculty"),
        # --- GPS: category 17 = Professorial Faculty (server-side) ---
        _ct("GPS", "Geological & Planetary Sciences",
            ["Geology", "Planetary Science", "Geophysics", "Environmental Science"],
            "https://www.gps.caltech.edu/people?category=17"),
        _ct("GPS-RF", "Geological & Planetary Sciences (Research Faculty)",
            ["Geology", "Planetary Science", "Geophysics"],
            "https://www.gps.caltech.edu/people?category=29"),
        # --- HSS: category 54 = Professorial Faculty; two pages (?p=2) ---
        _ct("HSS", "Humanities & Social Sciences",
            ["Economics", "Political Science", "Philosophy", "History", "English"],
            "https://www.hss.caltech.edu/people?category=54&submit=Search",
            paginate={"param": "p", "start": 2, "max": 3}),
        # --- EAS option sites (division /people mixes all options; the option
        # sites are the clean per-department rosters). Affiliated Faculty
        # sections are joint appointments — the post-enrich email dedupe
        # collapses them onto the home-division record. ---
        _ct("GALCIT", "Aerospace (GALCIT)",
            ["Aerospace Engineering"],
            "https://www.galcit.caltech.edu/people"),
        # aph.caltech.edu's ?category= filter is client-side JS (ignored by the
        # server), so this roster mixes staff/lecturers — the ladder filter cuts.
        _ct("APHMS", "Applied Physics & Materials Science",
            ["Applied Physics", "Materials Science"],
            "https://www.aph.caltech.edu/people"),
        _ct("CMS", "Computing & Mathematical Sciences",
            ["Computer Science", "Applied Mathematics", "Statistics", "Data Science"],
            "https://www.cms.caltech.edu/people/faculty"),
        _ct("EE", "Electrical Engineering",
            ["Electrical Engineering", "Computer Engineering"],
            "https://www.ee.caltech.edu/people"),
        _ct("ESE", "Environmental Science & Engineering",
            ["Environmental Science", "Environmental Engineering"],
            "https://www.ese.caltech.edu/people"),
        _ct("MCE", "Mechanical & Civil Engineering",
            ["Mechanical Engineering", "Civil Engineering"],
            "https://www.mce.caltech.edu/people"),
        _ct("MEDE", "Medical Engineering",
            ["Medical Engineering", "Biomedical Engineering"],
            "https://www.mede.caltech.edu/people"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
