"""University of Miami faculty config (via the faculty_graph engine).

University of Miami publishes faculty on three server-rendered markup families,
all plain static 200s to a bare request (no WAF, no JS render). Live-verified
2026-07-24.

* **Cascade CMS "people-profile" cards — the campus-wide component.**
  Every College of Arts & Sciences department (``<dept>.as.miami.edu``), every
  College of Engineering department (``<dept>.coe.miami.edu``) and the School of
  Nursing & Health Studies (``sonhs.miami.edu``) share ONE campus people
  component. Computer Science renders it as a table (``li.people-profile`` with a
  desktop + mobile copy per row); everyone else renders a grid
  (``div.people-profile``). Both carry the SAME inner classes, so
  ``.people-profile`` as the card, ``.profile-name span`` / ``.profile-position
  span`` for name / rank, and ``a.url-rewrite`` -> ``people.miami.edu/profile/<hash>``
  for the link cover every department. Only the roster PATH varies by department
  (``/people/faculty/``, ``/people/``, ``/people/primary-faculty/``,
  ``/faculty/``, or a school-specific path) — passed explicitly per department.

  Email IS recoverable: every card hides the address in
  ``<a class="email-decode" data-code="HEX">`` where HEX is the address's UTF-16-BE
  code units (``0076007800610033…`` -> ``vxa305@miami.edu``). The engine's
  ``_decode_datacode_email`` reverses it, so these departments land fully emailed.

  Title gate (``ladder_filter require: professor|lecturer``): the faculty pages
  are faculty-only but mix in the odd College Dean / Assistant Vice Provost whose
  card carries no rank — the require gate drops those while keeping every
  professor / lecturer rank (research / visiting / professor-of-practice incl.).
  Emeriti drop via the engine's own retired-title gate.

* **Mathematics — legacy hand-maintained ``<p>`` list.**
  ``mathematics.miami.edu/about-us/faculty/`` is NOT the people-profile template:
  each member is one ``<content> <p>`` block holding ``<strong>Name</strong>,
  Rank <br> … Research Interests: <areas> <br> Email: <a mailto>``. Name in the
  ``<strong>`` (trailing comma stripped), rank via a first-match ``title_re``,
  research areas via ``research_re``, and — uniquely here — a real ``mailto`` per
  person. The ladder require drops the two honorary "Distinguished Scholar" rows;
  the retired gate drops the lone "Professor Emeritus".

Single source ("miami_faculty"); department rides each record, ids namespaced by
department short-code.

Coverage (2026-07-24) — 23 departments, all fully emailed:
  Arts & Sciences: Computer Science, Physics, Chemistry, Mathematics, Biology,
    English, History, Political Science, Sociology, Philosophy, Anthropology,
    Geography, Classics, Modern Languages, Religious Studies, Theatre Arts,
    Art & Art History.
  Engineering: Electrical & Computer, Mechanical & Aerospace, Biomedical,
    Civil-Architectural-Environmental, Industrial & Systems.
  Health: School of Nursing & Health Studies.

Dropped / phase-2 (all reachable only via the v2 client-rendered directories or
name-only cards — no engine-decodable email at the directory level, so they'd
ship email-less; recover in a profile-enrich pass that resolves each
``people.miami.edu/profile/<hash>`` for its hex email):
  * Miami Herbert Business School — herbert.miami.edu ``/faculty-research/
    directory/`` server-renders ``div.column`` cards (h2.name + div.title +
    profile link) but carries NO email in the card. Name+title only -> DROP.
  * Frost School of Music — frost.miami.edu is the v2 template; the directory is
    painted client-side from ``people.miami.edu/collections/acad-mus/…/
    music-master.xml`` (a ``<people-profile>`` feed whose ``<primary-email>`` is
    the same hex-UTF16, but as element TEXT the engine's data-code decoder can't
    reach). Rendered DOM stays a filter shell -> DROP.
  * Rosenstiel School of Marine, Atmospheric & Earth Science — earth.miami.edu
    ``/about-us/people/`` is the same v2 client-only template (no server cards).
  * School of Communication — com.miami.edu is WordPress (Avada), no person CPT;
    ``/directory/faculty/`` lists ~190 cards linking to people.miami.edu profiles
    with no email in the card.
  * Economics (economics.as.miami.edu) — legacy minimal site with no local roster
    page; faculty listed only on people.miami.edu.
  * Psychology (psychology.as.miami.edu) — subdomain unreachable (DNS/TLS fails,
    curl 000 on every host/path variant).
"""

from __future__ import annotations

import json
import re
from urllib.parse import unquote, urlsplit

from backend.lib.public_projection import safe_public_http_url
from src.normalizers.deactivate_stale_faculty import canonical_profile_url

from .. import faculty_graph, ucb_common

# ---- Shared Cascade CMS "people-profile" component -------------------------
# CS renders it as a table row (li.people-profile, desktop + mobile copy), all
# others as a grid card (div.people-profile); ``.people-profile`` covers both.
# select_one takes the first match, so the CS row's duplicate copies collapse to
# one name/title. Name sits in a <span> under .profile-name; rank in
# .profile-position; the hex-UTF16 address in a.email-decode[data-code].
_CASCADE_SEL = {
    "card": ".people-profile",
    "name": ".profile-name span",
    "link": "a.url-rewrite[href*='/profile/']",
    "title": ".profile-position span",
    "email": "a.email-decode",
}
# Keep every professor / lecturer rank; drop the title-less admin cards (a College
# Dean, an Assistant Vice Provost) that ride the faculty page. Emeriti drop via the
# engine's retired-title gate.
_CASCADE_LADDER = {"require": r"professor|lecturer"}


def _cascade(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared Cascade people-profile component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CASCADE_SEL,
                   "ladder_filter": _CASCADE_LADDER},
    }


_BIOLOGY_DIRECTORY = "https://biology.as.miami.edu/people/index.html"
_DEANGELIS_CITATION = _BIOLOGY_DIRECTORY + "#:~:text=DeAngelis"
_DEANGELIS_OLD_NAME = "\u200cDon DeAngelis"
_DEANGELIS_ID = "faculty-miami-bio-4dfe1b88"
_DEANGELIS_EMAIL = "ddeangelis@miami.edu"
_DEANGELIS_PROFILE = "people.miami.edu/profile/" + _DEANGELIS_EMAIL


def _matches_previous_deangelis_profile(raw_url: str | None) -> bool:
    if not raw_url:
        return False
    if canonical_profile_url(unquote(raw_url)) == _DEANGELIS_PROFILE:
        # An encoded at-sign identifies the same institutional account.
        return True
    public = safe_public_http_url(raw_url)
    if not public:
        return False
    parts = urlsplit(public)
    if parts.netloc.lower() != "people.miami.edu" or not re.fullmatch(r"/profile/[\w-]+/?", parts.path, re.ASCII):
        return False
    # Only an ambiguous new card reaches here. An earlier directory observation
    # with the verified address can establish the same person's new URL.
    processed = ucb_common.PROCESSED_FILE
    shard = processed.parent / "shards" / "miami.json"
    try:
        source = processed if processed.is_file() else shard
        with source.open(encoding="utf-8") as file:
            prior = next((r for r in json.load(file) if r.get("id") == _DEANGELIS_ID), None)
    except (OSError, ValueError):
        return False
    return bool(prior and prior.get("source") == "miami_faculty"
                and prior.get("pi_name") in ("Don DeAngelis", _DEANGELIS_OLD_NAME)
                and canonical_profile_url(prior.get("url")) == canonical_profile_url(public))


def _biology() -> dict:
    dept = _cascade("BIO", "Department of Biology",
                    ["Biology", "Marine Science and Biology", "Microbiology and Immunology", "Neuroscience"],
                    _BIOLOGY_DIRECTORY)
    # The name's invisible leading character was part of its original published ID.
    dept["scrape"]["selectors"] = {**_CASCADE_SEL, "name_strip": r"^\u200c(?=Don DeAngelis$)"}
    dept["reserved_profile_identity"] = {
        "name": _DEANGELIS_OLD_NAME, "names": ("Don DeAngelis", _DEANGELIS_OLD_NAME),
        "profile": _DEANGELIS_PROFILE, "email": _DEANGELIS_EMAIL,
        "matches_previous_profile": _matches_previous_deangelis_profile,
    }
    return dept


# ---- Mathematics: legacy <p>-list template ---------------------------------
_MATH_URL = "https://mathematics.miami.edu/about-us/faculty/index.html"
# First rank phrase in the card text ("Ming-Liang Cai, Associate Professor<br>…").
# Ordered so a fuller phrase wins over the bare "Professor" (Distinguished /
# Emeritus suffixes ride along so the retired gate can see "Professor Emeritus").
_MATH_TITLE_RE = (
    r"((?:Distinguished |Research |Visiting |Clinical |Senior )*"
    r"(?:Assistant |Associate )?Professor(?:\s+Emerit\w+)?|Senior Lecturer|Lecturer)"
)


SCHOOL: dict = {
    "school_slug": "miami",
    "source": "miami_faculty",
    "organization": "University of Miami",
    "location": "Coral Gables, FL",
    "id_prefix": "miami",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Miami) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ==== College of Arts & Sciences (<dept>.as.miami.edu) =============
        _cascade("CS", "Department of Computer Science",
                 ["Computer Science", "Data Science"],
                 "https://csc.as.miami.edu/people/faculty/index.html"),
        _cascade("PHYS", "Department of Physics", ["Physics", "Astrophysics"],
                 "https://physics.as.miami.edu/people/index.html"),
        _cascade("CHEM", "Department of Chemistry",
                 ["Chemistry", "Biochemistry and Molecular Biology"],
                 "https://chemistry.as.miami.edu/people/faculty/index.html"),
        _biology(),
        _cascade("ENG", "Department of English", ["English"],
                 "https://english.as.miami.edu/people/index.html"),
        _cascade("HIST", "Department of History", ["History"],
                 "https://history.as.miami.edu/people/index.html"),
        _cascade("POL", "Department of Political Science", ["Political Science"],
                 "https://politicalscience.as.miami.edu/people/primary-faculty/index.html"),
        _cascade("SOC", "Department of Sociology and Criminology", ["Sociology"],
                 "https://sociology.as.miami.edu/people/index.html"),
        _cascade("PHIL", "Department of Philosophy", ["Philosophy"],
                 "https://philosophy.as.miami.edu/people/index.html"),
        _cascade("ANTH", "Department of Anthropology", ["Anthropology"],
                 "https://anthropology.as.miami.edu/people/index.html"),
        _cascade("GEOG", "Department of Geography and Sustainable Development",
                 ["Geography and Sustainable Development"],
                 "https://geography.as.miami.edu/people/faculty/index.html"),
        _cascade("CLAS", "Department of Classics", ["Classics"],
                 "https://classics.as.miami.edu/people/faculty/index.html"),
        _cascade("MLL", "Department of Modern Languages and Literatures",
                 ["Modern Languages", "International Studies"],
                 "https://mll.as.miami.edu/people/index.html") | {
            "profile_id_names": {
                "people.miami.edu/profile/516e10f611757d73af54c09a763afdcd":
                    ("Chloe Summers Edmondson", "Chloe Ming Hwa Summers Edmondson"),
            },
        },
        _cascade("REL", "Department of Religious Studies", ["Religious Studies"],
                 "https://religion.as.miami.edu/people/index.html"),
        _cascade("THA", "Department of Theatre Arts", ["Theatre Arts"],
                 "https://theatrearts.as.miami.edu/faculty/index.html"),
        _cascade("ART", "Department of Art and Art History",
                 ["Art", "Art History"],
                 "https://art.as.miami.edu/about/faculty-and-staff/faculty/index.html") | {
            "profile_id_names": {
                "people.miami.edu/profile/48a2c3ffab0fc77f5fa883edf97ace8c":
                    ("Nathan J. Timpano", "Nathan James Timpano"),
            },
        },
        # ---- Mathematics (legacy <p>-list) --------------------------------
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": _MATH_URL,
            "scrape": {
                "url": _MATH_URL,
                "selectors": {
                    "card": "content p",
                    "name": "strong",
                    "name_strip": r",\s*$",
                    "title_re": _MATH_TITLE_RE,
                    "research_re": r"Research Interests?:\s*(?:</em>)?(.*?)(?:<br\s*/?>\s*Email|Email\s*:)",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": {"require": r"professor|lecturer"},
            },
        },
        # ==== College of Engineering (<dept>.coe.miami.edu) ================
        _cascade("ECE", "Department of Electrical and Computer Engineering",
                 ["Electrical Engineering", "Computer Engineering"],
                 "https://ece.coe.miami.edu/people/faculty/index.html"),
        _cascade("MAE", "Department of Mechanical and Aerospace Engineering",
                 ["Mechanical Engineering", "Aerospace Engineering"],
                 "https://mae.coe.miami.edu/people/faculty/index.html"),
        _cascade("BME", "Department of Biomedical Engineering",
                 ["Biomedical Engineering"],
                 "https://bme.coe.miami.edu/people/faculty/index.html"),
        _cascade("CAE",
                 "Department of Civil, Architectural and Environmental Engineering",
                 ["Civil Engineering", "Environmental Engineering",
                  "Architectural Engineering"],
                 "https://cae.coe.miami.edu/people/faculty/index.html"),
        _cascade("ISE", "Department of Industrial and Systems Engineering",
                 ["Industrial and Systems Engineering"],
                 "https://ise.coe.miami.edu/people/faculty/index.html"),
        # ==== School of Nursing and Health Studies =========================
        _cascade("SONHS", "School of Nursing and Health Studies",
                 ["Nursing (BSN)", "Health Science", "Public Health"],
                 "https://www.sonhs.miami.edu/about-sonhs/faculty-and-staff/faculty-directory/index.html") | {
            "profile_id_names": {"people.miami.edu/profile/a1e7d2ef1ef8b9fd0c681b22e15044f7": ("Tony Umadhay", "Lonar Anthony Umadhay")},
        },
    ],
}


def fetch_and_normalize(deep: bool = True,
                        unit_ledger: dict | None = None) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    rows = faculty_graph.fetch_and_normalize(SCHOOL, deep=deep, unit_ledger=unit_ledger)
    for row in rows:
        if row["id"] == _DEANGELIS_ID and (
            not safe_public_http_url(row.get("url"))
            or canonical_profile_url(row.get("url")) == canonical_profile_url(_BIOLOGY_DIRECTORY)
        ):
            # His named card links to an address-bearing profile. Keep that
            # identity in the corpus and cite the public roster on the product.
            row["source_url"] = _DEANGELIS_CITATION
    return rows


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
