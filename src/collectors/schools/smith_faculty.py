"""Smith College faculty config (via the faculty_graph engine).

Smith is a top liberal-arts women's college (~2,500 undergraduates) in
Northampton, MA and a member of the Five College Consortium (Amherst, Mount
Holyoke, Hampshire, and UMass Amherst). It is one of the few liberal-arts
colleges with an ABET-accredited engineering major (the Picker Engineering
Program) alongside strong laboratory sciences.

Every academic department publishes its roster on ONE shared Drupal
"teaser" component at ``smith.edu/academics/departments-programs-courses/
<slug>`` — there is no scrapeable college-wide people directory (the
``/your-campus/people-directory`` page is a client-side search app that
returns no cards to curl), but every department page shares the same markup,
so a single scrape source with per-dept URLs covers the whole college.
Live-verified 2026-07-22 (all plain HTTP 200s, no WAF, no render mode).

Markup family (``smith_teaser``): each person is an ``article.teaser`` card
whose name + profile link is ``h2.teaser__heading a`` (an ``/people/<slug>``
profile), and whose rank is ``p.teaser__subheading`` ("Assistant Professor of
Biological Sciences", "Lecturer in Engineering", named chairs such as "Gates
Foundation Professor of Engineering"). A ``link_filter`` keeps only cards that
link to a ``/people/`` profile (department pages can also carry news/event
teasers with the same class). Emails are not on the listing card — each
profile page carries a single decodable ``mailto:`` — so an env-gated
``profile_enrich`` pass (OFF in CI/weekly refresh, mirroring Amherst)
backfills the public email; by default no email/topics are inferred here and
enrichment comes from OpenAlex.

Because these are combined faculty/staff listings, each list mixes teaching
faculty with laboratory instructors, coordinators, and technicians (whose
titles carry neither "professor" nor "lecturer"), plus emeriti, visiting,
adjunct, and "(in memoriam)" appointments. The ladder filter keeps only
professorial + lecturer ranks and drops the rest; the engine additionally
drops emeritus/retired titles and rejects in-memoriam names.

Single source ("smith_faculty"); department rides each record, ids namespaced
by department short-code. The engine's per-school url/email dedup collapses
faculty cross-listed onto an interdisciplinary program page and their home
department (Smith professors are frequently double-listed), so the core
departments are listed first.

Verified live (curl + bs4) across sciences, social sciences, humanities and
arts on 2026-07-22 (e.g. Biological Sciences 24 cards, Chemistry 21,
Engineering 13, Physics 11, Computer Science 12 — post-ladder counts smaller).
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.smith.edu/academics/departments-programs-courses"

# Person card on the shared Smith Drupal "teaser" department template.
_SELECTORS = {
    "card": "article.teaser",
    "name": "h2.teaser__heading a",
    "link": "h2.teaser__heading a",
    "title": "p.teaser__subheading",
}

# Keep professorial + lecturer ranks; drop emeriti, visiting, adjunct,
# in-memoriam appointments and (via the require gate) the laboratory
# instructors / coordinators / technicians whose titles carry no
# professorial rank.
_LADDER = {
    "require": r"professor|lecturer",
    "drop": r"emerit|visiting|adjunct|memoriam",
}

# Profiles carry a single public mailto (no email on the listing card).
# Env-gated (OFF in CI / weekly refresh, like Amherst); when the deliberate
# local enrichment run turns it on it backfills the public contact email.
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "throttle": 0.2,
}


def _dept(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A Smith academic department on the shared teaser template."""
    url = f"{_BASE}/{slug}"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": _SELECTORS,
            "link_filter": r"/people/",
            "ladder_filter": _LADDER,
            "profile_enrich": _ENRICH,
        },
    }


SCHOOL: dict = {
    "school_slug": "smith",
    "source": "smith_faculty",
    "organization": "Smith College",
    "location": "Northampton, MA",
    "id_prefix": "smith",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Smith College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences, Math & Engineering ------------------------
        _dept("BIO", "Department of Biological Sciences", ["Biological Sciences"],
              "biological-sciences"),
        _dept("BCHM", "Program in Biochemistry", ["Biochemistry"], "biochemistry"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("CSC", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("EGR", "Picker Engineering Program", ["Engineering"], "engineering"),
        _dept("MTH", "Department of Mathematical Sciences",
              ["Mathematics", "Statistics"], "mathematical-sciences"),
        _dept("SDS", "Program in Statistical and Data Sciences",
              ["Statistical and Data Sciences"], "statistical-data-sciences"),
        _dept("PHY", "Department of Physics", ["Physics"], "physics"),
        _dept("AST", "Department of Astronomy", ["Astronomy"], "astronomy"),
        _dept("GEO", "Department of Geosciences", ["Geosciences"], "geosciences"),
        _dept("NSC", "Program in Neuroscience", ["Neuroscience"], "neuroscience"),
        _dept("PSY", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("ESS", "Department of Exercise and Sport Studies",
              ["Exercise and Sport Studies"], "exercise-sport-studies"),
        _dept("ENV", "Program in Environmental Science and Policy",
              ["Environmental Science and Policy"], "environmental-science-policy"),
        _dept("AEM", "AEMES (Achieving Excellence in Math, Engineering and Science)",
              ["Sciences"], "aemes"),
        # ---- Social Sciences ---------------------------------------------
        _dept("ECO", "Department of Economics", ["Economics"], "economics"),
        _dept("GOV", "Department of Government", ["Government"], "government"),
        _dept("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("ANT", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _dept("EDC", "Department of Education and Child Study",
              ["Education and Child Study"], "education-child-study"),
        _dept("PPY", "Program in Public Policy", ["Public Policy"], "public-policy"),
        _dept("URB", "Program in Urban Studies", ["Urban Studies"], "urban-studies"),
        _dept("LSS", "Program in Landscape Studies", ["Landscape Studies"],
              "landscape-studies"),
        # ---- Humanities --------------------------------------------------
        _dept("HST", "Department of History", ["History"], "history"),
        _dept("HSC", "Program in History of Science and Technology",
              ["History of Science and Technology"], "history-science-technology"),
        _dept("PHI", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("REL", "Department of Religion", ["Religion"], "religion"),
        _dept("ENG", "Department of English Language and Literature",
              ["English"], "english-language-literature"),
        _dept("CLS", "Department of Classical Languages and Literatures",
              ["Classics"], "classical-studies"),
        _dept("WLT", "Program in World Literatures", ["Comparative Literature"],
              "world-literatures"),
        _dept("LNG", "Program in Linguistics", ["Linguistics"], "linguistics"),
        # ---- Languages & Area Studies ------------------------------------
        _dept("EAL", "Department of East Asian Languages and Cultures",
              ["East Asian Languages and Cultures"], "east-asian-languages-cultures"),
        _dept("FRN", "Department of French Studies", ["French Studies"],
              "french-studies"),
        _dept("GER", "Department of German Studies", ["German Studies"],
              "german-studies"),
        _dept("ITL", "Department of Italian Studies", ["Italian Studies"],
              "italian-studies"),
        _dept("SPP", "Department of Spanish and Portuguese",
              ["Spanish", "Portuguese"], "spanish-portuguese"),
        _dept("REE", "Program in Russian, East European and Eurasian Studies",
              ["Russian, East European and Eurasian Studies"],
              "russian-east-european-eurasian-studies"),
        _dept("AFR", "Program in Africana Studies", ["Africana Studies"],
              "africana-studies"),
        _dept("AMS", "Program in American Studies", ["American Studies"],
              "american-studies"),
        _dept("LAS", "Program in Latin American and Latino/a Studies",
              ["Latin American and Latino/a Studies"],
              "latin-american-latinoa-studies"),
        _dept("SAS", "Program in South Asian Studies", ["South Asian Studies"],
              "south-asian-studies"),
        _dept("MES", "Program in Middle East Studies", ["Middle East Studies"],
              "middle-east-studies"),
        _dept("JST", "Program in Jewish Studies", ["Jewish Studies"],
              "jewish-studies"),
        _dept("BST", "Program in Buddhist Studies", ["Buddhist Studies"],
              "buddhist-studies"),
        _dept("MDV", "Program in Medieval Studies", ["Medieval Studies"],
              "medieval-studies"),
        _dept("ANC", "Program in Ancient Studies", ["Ancient Studies"],
              "ancient-studies"),
        _dept("ARC", "Program in Archaeology", ["Archaeology"], "archaeology"),
        _dept("SWG", "Program in the Study of Women and Gender",
              ["Study of Women and Gender"], "study-women-gender-sexuality"),
        # ---- Arts --------------------------------------------------------
        _dept("DAN", "Department of Dance", ["Dance"], "dance"),
        _dept("THE", "Department of Theatre", ["Theatre"], "theatre"),
        _dept("FMS", "Program in Film and Media Studies",
              ["Film and Media Studies"], "film-media-studies"),
        _dept("ATP", "Program in Arts and Technology", ["Arts and Technology"],
              "arts-technology-program"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
