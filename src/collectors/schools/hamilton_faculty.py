"""Hamilton College faculty config (via the faculty_graph engine).

Hamilton is a top-tier US liberal arts college (~2,000 undergraduates, no
graduate/professional schools) in Clinton, NY, known for its open curriculum
and its writing-intensive program. Its entire public site sits behind an AWS
WAF "challenge" front (CloudFront returns HTTP 202 with an
``x-amzn-waf-action: challenge`` header and an empty body to a bare request),
so EVERY page must be fetched through headless Chromium — a real browser
clears the JavaScript challenge that a plain ``requests`` GET cannot.
``scrape["render"] = True`` on every department routes fetches through
:func:`faculty_graph._render_soup`, whose ``expect_selector`` wait lets the
cold WAF challenge resolve before the card check.

Markup family (``hamilton_dir`` — one selector set for the whole college):
each academic department publishes its roster on the shared college template
at ``hamilton.edu/academics/departments/<slug>``. Every person is a
``div.faculty_card`` whose name/label is ``.faculty_card_name_link_label``
inside the profile anchor ``a.faculty_card_name_link`` (an
``/academics/our-faculty/directory/faculty-detail/<slug>`` page), the rank is
``p.faculty_card_title`` (named chairs, "Assistant Professor of Instruction",
etc.), the public email is the ``a.faculty_card_email_link`` ``mailto:``
(inline for essentially every professor — no profile-enrich pass needed), and
``.faculty_card_expertise_info`` is a "; "-separated prose expertise string
that the engine splits into research keywords. Live-verified 2026-07-23 via
the engine's render path (e.g. Biology 14, Economics 15, Physics 7 after the
ladder gate).

Why the per-department pages and NOT the college-wide directory: the shared
directory at ``/academics/our-faculty/directory/faculty`` hard-caps every
response at 10 rows (``maxrows``/``perpage`` are ignored) and paginates only
via a literal ``startrow`` row-offset (``startrow=2`` returns rows 2–11), so
the engine's linear query-paginate can't walk it without one render per row.
The per-department pages instead render each department's COMPLETE roster in a
single page load, so one render per department covers the whole college.

Ladder gate keeps professorial + lecturer ranks (the cold-emailable research /
teaching faculty) and drops emeriti, visiting, and adjunct appointments plus
the non-teaching staff (lab coordinators, technicians, managers) whose titles
carry neither "professor" nor "lecturer".

Single source ("hamilton_faculty"); department rides each record, ids
namespaced by department short-code. The engine's per-school email/url dedup
collapses the faculty cross-listed onto more than one department page (a
Biology professor also under Environmental Studies or Neuroscience).

Scope (2026-07-23): the ~32 core concentration-granting departments below are
each rendered once. Because the whole site is WAF-gated and every fetch is a
cold headless render (~15–20s each), the smaller interdisciplinary / area-
studies programs are deferred on the faculty side — they only cross-list
faculty whose home department is already captured here (adding them would
produce email-deduped duplicates with arbitrary department attribution) and
are represented on the campus side as programs. Deferred: American Studies,
American Indian & Indigenous Studies, Asian Studies, Chemical Physics,
Cinema & Media Studies, Data Science, Digital Arts, East Asian Languages &
Literatures, Education Studies, Geoarchaeology, Hebrew, Italian Studies,
Jewish Studies, Jurisprudence Law & Justice Studies, Latin American & Latine
Studies, Medieval & Renaissance Studies, Middle East/Islamicate Worlds
Studies, Public Policy, Arabic.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.hamilton.edu/academics/departments"

# Person card on the shared Hamilton department roster template. Fetched
# through headless Chromium (the whole site is behind an AWS WAF challenge).
_SELECTORS = {
    "card": "div.faculty_card",
    "name": ".faculty_card_name_link_label",
    "link": "a.faculty_card_name_link",
    "title": "p.faculty_card_title",
    "research": ".faculty_card_expertise_info",
    "email": "a.faculty_card_email_link",
}

# Keep professorial + lecturer ranks; drop emeriti, visiting, and adjunct
# appointments as well as the staff whose titles carry no professorial rank.
_LADDER = {
    "require": r"professor|lecturer",
    "drop": r"emerit|\bvisiting\b|\badjunct\b",
}


def _dept(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A Hamilton academic department on the shared faculty-card template."""
    url = f"{_BASE}/{slug}"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "render": True,
            "selectors": _SELECTORS,
            "ladder_filter": _LADDER,
        },
    }


SCHOOL: dict = {
    "school_slug": "hamilton",
    "source": "hamilton_faculty",
    "organization": "Hamilton College",
    "location": "Clinton, NY",
    "id_prefix": "hamilton",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Hamilton College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Sciences & Mathematics --------------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("BMB", "Biochemistry & Molecular Biology",
              ["Biochemistry", "Molecular Biology"],
              "biochemistry-molecular-biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("CS", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("GEO", "Department of Geosciences", ["Geosciences"], "geosciences"),
        _dept("MATH", "Department of Mathematics & Statistics",
              ["Mathematics", "Statistics"], "mathematics-and-statistics"),
        _dept("NEURO", "Neuroscience Program", ["Neuroscience"], "neuroscience"),
        _dept("PHYS", "Department of Physics", ["Physics"], "physics"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("ENVS", "Environmental Studies Program", ["Environmental Studies"],
              "environmental-studies"),
        # ---- Social Sciences ---------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "anthropology"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("GOVT", "Department of Government", ["Government"], "government"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("AFRST", "Africana Studies", ["Africana Studies"],
              "africana-studies"),
        _dept("WGS", "Women's & Gender Studies",
              ["Women's and Gender Studies"], "womens-and-gender-studies"),
        # ---- Humanities --------------------------------------------------
        _dept("CLAS", "Department of Classics",
              ["Classics", "Classical Languages"], "classics"),
        _dept("LIT", "Literature & Creative Writing",
              ["Literature", "Creative Writing"], "literature-and-creative-writing"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELST", "Department of Religious Studies", ["Religious Studies"],
              "religious-studies"),
        _dept("ARTH", "Art History Program", ["Art History"], "art-history"),
        # ---- Arts --------------------------------------------------------
        _dept("ART", "Department of Art", ["Art", "Studio Art"], "art"),
        _dept("MUS", "Department of Music", ["Music"], "music"),
        _dept("THTR", "Department of Theatre", ["Theatre"], "theatre"),
        _dept("DANCE", "Dance & Movement Studies",
              ["Dance and Movement Studies"], "dance-and-movement-studies"),
        # ---- Languages & Literatures -------------------------------------
        _dept("FREN", "French & Francophone Studies",
              ["French", "Francophone Studies"], "french-and-francophone-studies"),
        _dept("GERM", "German Studies", ["German Studies"], "german-studies"),
        _dept("HISP", "Hispanic Studies", ["Hispanic Studies"], "hispanic-studies"),
        _dept("RUSS", "Russian Studies", ["Russian Studies"], "russian-studies"),
        _dept("CHIN", "Chinese", ["Chinese"], "chinese"),
        _dept("JAPN", "Japanese", ["Japanese"], "japanese"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
