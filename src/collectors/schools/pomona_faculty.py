"""Pomona College faculty config (via the faculty_graph engine).

Pomona is a top-10 US liberal arts college and the founding member of the
Claremont Colleges consortium (the 5Cs: Pomona, CMC, Harvey Mudd, Pitzer,
Scripps). It is undergraduate-only; "faculty" here are the professors and
lecturers a student would cold-email for mentored research.

ONE shared markup family, live-verified 2026-07-21: every academic
department publishes the SAME Drupal "staff listing" view at
``pomona.edu/academics/departments/<slug>/faculty-staff``. Each person is a
``div.text-brown-300`` card whose first child ``<div>`` is the rank line
("Professor of Biology", "Associate Professor of ...; Chair"), with the name
in an ``<a href="/directory/people/<slug>">`` and a plain ``mailto:`` inside
``.contact-us-email``. No WAF, no JS — plain 200s, all cards inline (no
pagination). Single ``scrape`` block reused across all departments via
``_dept``; ``short`` namespaces the record ids.

Consortium note: Pomona's intercollegiate/interdisciplinary programs (Asian
Studies, Gender & Women's Studies, Latin American Studies, Science Technology
& Society, Data Science, International Relations, PPE, Public Policy) list
cross-listed 5C faculty whose home college is CMC / Scripps / Pitzer / Harvey
Mudd. Every card links to a pomona.edu ``/directory/people`` profile, but the
displayed email reveals the home college. A ``field_filter`` on the email
cell keeps ONLY ``pomona.edu`` addresses, so only home-college (Pomona)
faculty are captured; the engine's per-school email/url dedup then collapses
the many people cross-listed across several Pomona departments/programs into
one record. Net distinct Pomona faculty ~200 as expected.

Ladder gate: keep titles matching ``professor|lecturer``, drop
``emerit|visiting|adjunct`` (plus the engine's unconditional emeritus drop).
This also filters the staff rows on each page (Operations Manager, Academic
Coordinator, Lab Coordinator, Director of ...) that carry no professorial
rank. No research areas live on the listing cards (they sit on the profile
pages behind the env-gated enrich pass, left OFF here) — topical keywords
come from the OpenAlex backfill.

Deferred: Physical Education (athletics, non-research); consortium-hosted
science depts have no Pomona-specific shared site beyond these department
pages, so nothing else to add.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.pomona.edu/academics/departments/{slug}/faculty-staff"

# Keep professorial ranks + lecturers; drop the temporary/retired tail. The
# engine compiles these case-insensitively, and also drops emeritus titles
# unconditionally on top of this gate.
_LADDER = {"require": r"\bprofessor\b|\blecturer\b",
           "drop": r"emerit|visiting|adjunct"}

# Card selectors shared by every department's Drupal staff-listing view.
_SEL = {
    "card": "div.text-brown-300",
    "name": "a[href*='/directory/people/']",
    "link": "a[href*='/directory/people/']",
    # First child <div> of the card is the rank line; .location / .contact-us-*
    # divs follow it, so the first div in document order is the title.
    "title": "div",
    "email": ".contact-us-email a[href^='mailto:']",
}

# Keep only Pomona home-college faculty: the email cell must show a pomona.edu
# address (consortium cross-listings carry cmc.edu / scrippscollege.edu / etc.).
_POMONA_ONLY = {"selector": ".contact-us-email", "include": r"pomona\.edu"}


def _dept(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A department on the shared faculty-staff staff-listing view."""
    url = _BASE.format(slug=slug)
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL,
                   "ladder_filter": _LADDER, "field_filter": _POMONA_ONLY,
                   # Profile "Areas of Expertise" section is a <ul><li> list
                   # (scoping to li excludes the <p> dept label); env-gated
                   # research-only per-profile pass.
                   "profile_enrich": {
                       "research_items_selector": 'h2:-soup-contains("Areas of Expertise") + div li',
                       "throttle": 0.2,
                   }},
    }


SCHOOL: dict = {
    "school_slug": "pomona",
    "source": "pomona_faculty",
    "organization": "Pomona College",
    "location": "Claremont, CA",
    "id_prefix": "pomona",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Pomona College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics --------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("CS", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("MATH", "Department of Mathematics and Statistics",
              ["Mathematics", "Statistics"], "mathematics-statistics"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics-and-astronomy"),
        _dept("GEOL", "Department of Geology", ["Geology"], "geology"),
        _dept("NEUR", "Program in Neuroscience", ["Neuroscience"], "neuroscience"),
        _dept("PSYC", "Department of Psychological Science", ["Psychology"],
              "psychological-science"),
        _dept("MBIO", "Program in Molecular Biology", ["Molecular Biology"],
              "molecular-biology"),
        _dept("EA", "Program in Environmental Analysis",
              ["Environmental Analysis", "Environmental Studies"],
              "environmental-analysis"),
        _dept("DS", "Program in Data Science", ["Data Science"], "data-science"),
        # ---- Social Sciences ------------------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("POLI", "Department of Politics", ["Politics", "Political Science"],
              "politics"),
        _dept("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _dept("LGCS", "Program in Linguistics and Cognitive Science",
              ["Linguistics", "Cognitive Science"],
              "linguistics-cognitive-science"),
        _dept("IR", "Program in International Relations",
              ["International Relations"], "international-relations"),
        _dept("PPA", "Program in Public Policy Analysis", ["Public Policy"],
              "public-policy-analysis"),
        _dept("PPE", "Program in Philosophy, Politics, and Economics",
              ["Philosophy, Politics, and Economics"],
              "philosophy-politics-economics"),
        # ---- Humanities -----------------------------------------------------
        _dept("ENGL", "Department of English", ["English", "Creative Writing"],
              "english"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RLST", "Department of Religious Studies", ["Religious Studies"],
              "religious-studies"),
        _dept("CLAS", "Department of Classics", ["Classics"], "classics"),
        _dept("RLL", "Department of Romance Languages and Literatures",
              ["French", "Spanish", "Italian"],
              "romance-languages-literatures"),
        _dept("ALL", "Department of Asian Languages and Literatures",
              ["Chinese", "Japanese"], "asian-languages-literatures"),
        _dept("GERM", "Program in German", ["German"], "german"),
        _dept("RUSS", "Program in Russian", ["Russian"], "russian"),
        _dept("AMST", "Program in American Studies", ["American Studies"],
              "american-studies"),
        _dept("MS", "Program in Media Studies", ["Media Studies"], "media-studies"),
        _dept("GWS", "Program in Gender and Women's Studies",
              ["Gender and Women's Studies"], "gender-womens-studies"),
        _dept("CHLT", "Department of Chicana/o-Latina/o Studies",
              ["Chicana/o-Latina/o Studies"], "chicana-o-latina-o-studies"),
        _dept("ASAM", "Program in Asian Studies", ["Asian Studies"],
              "asian-studies"),
        _dept("LTAM", "Program in Latin American Studies",
              ["Latin American Studies"], "latin-american-studies"),
        _dept("STS", "Program in Science, Technology, and Society",
              ["Science, Technology, and Society"], "science-technology-society"),
        # ---- Arts -----------------------------------------------------------
        _dept("ART", "Department of Art", ["Studio Art"], "art"),
        _dept("ARTH", "Department of Art History", ["Art History"], "art-history"),
        _dept("MUS", "Department of Music", ["Music"], "music"),
        _dept("THEA", "Department of Theatre", ["Theatre"], "theatre"),
        _dept("DANC", "Department of Dance", ["Dance"], "dance"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
