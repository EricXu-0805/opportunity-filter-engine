"""Claremont McKenna College faculty config (via the faculty_graph engine).

CMC (a top-ten national liberal-arts college in Claremont, CA) runs every
academic department's faculty roster on ONE shared Drupal "views" template
served from ``www.cmc.edu/<dept>/faculty``. Each page splits people into three
Drupal view displays — ``view-display-id-active``, ``...-visiting`` and
``...-emeritus`` — so scoping the card selector to the *active* block alone
drops emeriti and visiting faculty structurally, before any title gate. Person
cards render in one of two layouts (a multi-column ``.views-col`` grid or a
single-person-per-``.views-row`` stack); the unifying card selector
``.view-display-id-active :has(> .views-field-name)`` matches exactly one
element per person in both. Names arrive as ``"First Last, Ph.D."`` (credential
stripped via ``name_strip``), the rank sits in
``.views-field-field-faculty-title``, the profile link is the name anchor
(``/academic/faculty/profile/<slug>``), and the public email is a Cloudflare
``/cdn-cgi/l/email-protection#<hex>`` anchor that the engine decodes inline.

Sciences: CMC founded its own **Kravis Department of Integrated Sciences** after
withdrawing from the tri-college W.M. Keck Science Department, so CMC's science
faculty live at ``/kravis-department-of-integrated-sciences/faculty-and-staff``.
That page uses a different ``.profile.vcard`` layout and mixes three groups —
Kravis (CMC) faculty, CMC science staff (directors/administrators), and the
shared "Department of Natural Sciences, Pitzer and Scripps Colleges" (the
current Keck department, whose profiles link off-site to
``natsci.claremont.edu``). A ``ladder_filter`` requiring "professor"/"lecturer"
and dropping "emerit"/"visiting" keeps only the CMC-owned Kravis professors: the
staff titles ("Director of ...", "Administrator") and the Pitzer/Scripps rows
(whose leading line is their consortium affiliation, not a rank) are excluded.

Live-verified on 2026-07-21: the current shared Keck directory
(``natsci.claremont.edu``) carries NO Claremont-McKenna-affiliated faculty — its
profiles are footered with Pitzer and Scripps addresses only, and CMC's science
faculty are all in the Kravis department captured above. No CMC-Keck records are
fabricated.

Single source ("cmc_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Shared CMC department "views" template (static HTML), scoped to the active
# faculty display so emeriti/visiting (separate Drupal displays) never appear.
# ``:has(> .views-field-name)`` yields one card per person in both the
# multi-column (.views-col) and single-column (.views-row) layouts.
_DEPT_SELECTORS = {
    "card": ".view-display-id-active :has(> .views-field-name)",
    "name": ".views-field-name a",
    "link": ".views-field-name a",
    "title": ".views-field-field-faculty-title .field-content",
    "email": ".views-field-mail a",
    "name_strip": r",.*$",  # strip the ", Ph.D." (etc.) credential tail
}

# Belt-and-suspenders on top of the active-display scoping.
_DEPT_LADDER = {"drop": r"emerit|emerita|visiting"}


def _dept(short: str, name: str, majors: list[str], path: str) -> dict:
    """A CMC department on the shared /<path>/faculty views template."""
    url = f"https://www.cmc.edu/{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _DEPT_SELECTORS,
                       "ladder_filter": _DEPT_LADDER}}


# Kravis Department of Integrated Sciences (CMC's own science department) —
# a ``.profile.vcard`` layout mixing faculty, staff and the shared Pitzer/Scripps
# (natsci.claremont.edu) rows. Require a professorial/lecturer rank to keep only
# CMC's Kravis faculty; the name's ", Ph.D." tail is stripped; the email is a
# Cloudflare-protected span the engine decodes.
_KRAVIS_SELECTORS = {
    "card": ".profile.vcard",
    "name": ".fn",
    "link": ".fn a",
    "title": ".fn + p",
    "email": "span.__cf_email__",
    "name_strip": r",.*$",
}
_KRAVIS_URL = ("https://www.cmc.edu/kravis-department-of-integrated-sciences/"
               "faculty-and-staff")
_KRAVIS_LADDER = {"require": r"\bprofessor\b|\blecturer\b",
                  "drop": r"emerit|visiting|adjunct"}


SCHOOL: dict = {
    "school_slug": "cmc",
    "source": "cmc_faculty",
    "organization": "Claremont McKenna College",
    "location": "Claremont, CA",
    "id_prefix": "cmc",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Claremont McKenna College) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        _dept("ECON", "Robert Day School of Economics & Finance",
              ["Economics", "Economics-Accounting", "Finance"],
              "robert-day-school/faculty"),
        _dept("GOVT", "Department of Government",
              ["Government", "International Relations"], "government/faculty"),
        _dept("HIST", "Department of History", ["History"], "history/faculty"),
        _dept("LIT", "Department of Literature", ["Literature"], "literature/faculty"),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematics", "Computer Science", "Data Science"],
              "mathematics/math-faculty"),
        _dept("MLL", "Department of Modern Languages & Literatures",
              ["French", "Spanish", "Arabic", "Chinese"], "modern-languages/faculty"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy/faculty"),
        _dept("PSYC", "Department of Psychological Science",
              ["Psychology", "Neuroscience"], "psychological-science/faculty"),
        _dept("RLST", "Department of Religious Studies", ["Religious Studies"],
              "religious-studies/faculty"),
        # CMC's own science department (post-Keck-withdrawal).
        {"short": "KDIS", "name": "Kravis Department of Integrated Sciences",
         "majors": ["Integrated Sciences", "Biology", "Chemistry", "Physics",
                    "Neuroscience", "Environmental Science"],
         "directory_url": _KRAVIS_URL,
         "scrape": {"url": _KRAVIS_URL, "selectors": _KRAVIS_SELECTORS,
                    "ladder_filter": _KRAVIS_LADDER}},
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
