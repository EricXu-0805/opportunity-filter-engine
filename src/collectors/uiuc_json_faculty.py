"""UIUC faculty from campus JSON directory APIs (no per-profile HTML scraping).

Two large UIUC units publish their directory as a paginated JSON API that
already carries each person's email and (for the WIGG units) structured
research keywords, so the slow per-profile page fetch the HTML collector needs
is unnecessary here:

  WIGG DirectoryCore — College of Applied Health Sciences + School of Social
  Work:  ``directoryapi.wigg.illinois.edu/api/Directory/Search/{slug}?take=N``
     -> ``{"people": [{jobProfiles:[{jobType, office, title}], keywords, ...}]}``
     Faculty are the rows carrying a ``jobType == "Faculty"`` job profile (the
     rest are staff/admin and must be dropped); ``keywords`` are
     publication-derived research areas (deduped + lightly noise-stripped here).

  Gies facultysearchapi — Gies College of Business:
     ``facultysearchapi.itpartners.illinois.edu/api/Search?collegeType=business&take=N``
     -> ``{"items": [{title, department, email, ...}]}``
     No ``jobType`` field, so faculty are selected by an academic-title pattern
     (professor / lecturer / instructor, excluding PhD students + postdocs). No
     structured keywords are exposed, so each gets only its honest department
     broad field.

Both reuse :func:`uiuc_faculty.normalize_faculty` (identical record schema,
``source="uiuc_faculty"``) and merge through
:func:`uiuc_faculty.merge_into_processed`, so the cross-college email dedup, the
faculty DQ sequence, and the source-keyed school/audience tagging all apply
unchanged.
"""

from __future__ import annotations

import logging
import re

import requests

from .uiuc_faculty import (
    HEADERS,
    _dept_broad_field,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

WIGG_URL = "https://directoryapi.wigg.illinois.edu/api/Directory/Search/{slug}?take=2000"
GIES_URL = (
    "https://facultysearchapi.itpartners.illinois.edu/api/Search"
    "?collegeType=business&take=2000"
)
TIMEOUT = 30

# WIGG ``keywords`` are publication-derived (MeSH-style): most are real research
# areas, but a minority are population/geography descriptors that aren't topical.
# Drop only the unambiguous ones — never anything that could be a research focus.
_KEYWORD_NOISE = frozenset({
    "adult", "adults", "us adults", "young adults", "middle-aged", "older adults",
    "aged", "child", "children", "infant", "infants", "adolescent", "adolescents",
    "humans", "human", "female", "male", "usa", "united states", "us", "science",
})

# A Library-of-Congress call number leaked as a keyword ("RA0421 Public health.
# Hygiene...", "RC0321 Neuroscience..."). 1-3 letters + 3+ digits at the start is
# unambiguous — real areas like "p53", "CD4", "3D printing" never match it.
_LC_CODE_RE = re.compile(r"^[a-z]{1,3}\d{3,}\b", re.IGNORECASE)

# Faculty title patterns for the Gies directory (which has no jobType field).
_GIES_FACULTY_TITLE = re.compile(r"\b(professor|lecturer|instructor)\b", re.IGNORECASE)
_GIES_NON_FACULTY = re.compile(r"(ph\.?d student|postdoc)", re.IGNORECASE)


def _clean_keywords(raw: list[str], fallback: str) -> list[str]:
    """Dedupe (case-insensitive, order-preserving — the API ranks by publication
    frequency so the leading terms are the truest focus), drop population/
    geography noise, cap at 8. Empty -> the department broad field so the record
    is never keyword-less."""
    seen: set[str] = set()
    out: list[str] = []
    for k in raw or []:
        k = (k or "").strip()
        kl = k.lower()
        if not k or kl in seen or kl in _KEYWORD_NOISE or _LC_CODE_RE.match(kl):
            continue
        seen.add(kl)
        out.append(k)
        if len(out) >= 8:
            break
    return out or [fallback]


def _fetch_json(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _ahs_dept_and_majors(office: str) -> tuple[str, list[str]]:
    """Route an AHS faculty member to their academic department by primary
    office (the WIGG ``primaryOffice`` is the clean academic unit for faculty)."""
    o = (office or "").lower()
    if "kinesiolog" in o:
        return ("Department of Health and Kinesiology",
                ["Kinesiology", "Community Health", "Interdisciplinary Health Sciences"])
    if "speech" in o or "hearing" in o:
        return ("Department of Speech and Hearing Science",
                ["Speech & Hearing Science", "Communication Sciences and Disorders"])
    if "recreation" in o or "sport" in o or "tourism" in o:
        # No comma in the stored name: the DQ atomizes a comma-bearing broad
        # field, which then fails to strip from the title (false specificity).
        return ("Department of Recreation Sport and Tourism",
                ["Recreation, Sport & Tourism", "Sport Management"])
    return ("College of Applied Health Sciences",
            ["Interdisciplinary Health Sciences", "Kinesiology", "Community Health"])


# Gies College of Business academic departments, keyed on the API ``department``
# field: (department, broad_keyword, majors). The broad keyword is explicit (not
# derived from the department name) because Gies faculty carry no structured
# research areas, so each falls back to it — and "business administration" is
# nav-furniture the keyword DQ rejects, so Business Administration anchors on the
# clean "business". Stragglers (library / dean's office) fall back to it too.
_GIES_DEPTS: dict[str, tuple[str, str, list[str]]] = {
    "Business Administration": (
        "Department of Business Administration", "business",
        ["Business Administration", "Management", "Marketing", "Operations Management",
         "Strategy & Entrepreneurship", "Information Systems", "Supply Chain Management"],
    ),
    "Finance": ("Department of Finance", "finance", ["Finance", "Business Administration"]),
    "Accountancy": (
        "Department of Accountancy", "accountancy",
        ["Accountancy", "Accounting", "Business Administration"],
    ),
}
_GIES_FALLBACK = ("Department of Business Administration", "business", ["Business Administration"])


def _normalize_wigg(person: dict, short: str, dept: str, majors: list[str]) -> dict | None:
    broad = _dept_broad_field(dept)
    kws = _clean_keywords(person.get("keywords") or [], broad)
    return normalize_faculty(
        {
            "name": (person.get("fullName") or "").strip(),
            "email": (person.get("email") or "").strip(),
            "url": person.get("profileUrl") or "",
            "title": (person.get("primaryTitle") or "Professor").strip(),
            "research_areas": "; ".join(kws),
        },
        {"short": short, "name": dept, "majors": majors, "keywords": [broad]},
        keywords=kws,
    )


def _fetch_wigg(slug: str, short: str, resolve) -> list[dict]:
    """Fetch a WIGG DirectoryCore unit, keeping only ``jobType == "Faculty"``
    rows. ``resolve(office) -> (department, majors)`` assigns each faculty member
    to an academic department."""
    data = _fetch_json(WIGG_URL.format(slug=slug))
    out: list[dict] = []
    for person in data.get("people", []):
        if not any(j.get("jobType") == "Faculty" for j in person.get("jobProfiles") or []):
            continue
        dept, majors = resolve(person.get("primaryOffice") or "")
        rec = _normalize_wigg(person, short, dept, majors)
        if rec:
            out.append(rec)
    logger.info(f"{short}: {len(out)} faculty (WIGG /{slug})")
    return out


def fetch_ahs() -> list[dict]:
    return _fetch_wigg("ahs", "AHS", _ahs_dept_and_majors)


def fetch_socialwork() -> list[dict]:
    return _fetch_wigg(
        "socialwork", "Social Work",
        lambda office: ("School of Social Work", ["Social Work"]),
    )


def fetch_gies() -> list[dict]:
    """Gies College of Business faculty (title-filtered out of an all-staff feed)."""
    data = _fetch_json(GIES_URL)
    out: list[dict] = []
    for item in data.get("items", []):
        title = (item.get("title") or "").strip()
        if not title or not _GIES_FACULTY_TITLE.search(title) or _GIES_NON_FACULTY.search(title):
            continue
        name = (item.get("fullnamefirst") or "").strip()
        if not name:
            continue
        dept, broad, majors = _GIES_DEPTS.get(item.get("department"), _GIES_FALLBACK)
        rec = normalize_faculty(
            {
                "name": name,
                "email": (item.get("email") or "").strip(),
                "url": item.get("externalurlwithpath") or "",
                "title": title,
                "research_areas": broad,
            },
            {"short": "Gies", "name": dept, "majors": majors, "keywords": [broad]},
            keywords=[broad],
        )
        if rec:
            out.append(rec)
    logger.info(f"Gies: {len(out)} faculty")
    return out


def fetch_and_normalize() -> list[dict]:
    """All JSON-API faculty (AHS + Social Work + Gies), normalized. A fetch
    failure for one unit is logged and skipped so a single dead endpoint can't
    sink the rest."""
    out: list[dict] = []
    for label, fn in (("AHS", fetch_ahs), ("Social Work", fetch_socialwork), ("Gies", fetch_gies)):
        try:
            out.extend(fn())
        except Exception as e:
            logger.error(f"JSON faculty fetch failed for {label}: {e}")
    logger.info(f"Total JSON-API faculty: {len(out)}")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    opps = fetch_and_normalize()
    print(f"\nFetched {len(opps)} JSON-API faculty research opportunities")
    for o in opps[:8]:
        email = o.get("contact_email") or "no email"
        print(f"\n  {o['title'][:72]}")
        print(f"    PI: {o.get('pi_name')} ({email})")
        print(f"    Dept: {o['department']}")
        print(f"    Keywords: {', '.join(o.get('keywords', []))}")
