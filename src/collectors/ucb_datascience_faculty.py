"""Collector for UC Berkeley Computing, Data Science & Society (CDSS) faculty.

CDSS is an interdisciplinary *college*, not a department with its own faculty:
its members are almost entirely jointly appointed in EECS, Statistics, MCB,
Integrative Biology, etc. — departments this project already indexes. So this
collector's value is the handful of faculty whose primary home is a CDSS unit
and who aren't already covered; the ~90% overlap is dropped at merge time by
``ucb_common.merge_into_processed`` → ``drop_joint_appointment_duplicates``
(merged LAST in refresh_all, after every home department).

Two public CDSS unit directories are scraped; both list faculty as name
headings with a profile link and a role/department line, and neither exposes a
mailto, so records ship "lite" (contact_email=None):

  * Data Science Undergraduate Studies (DSUS) — the Data Science major's faculty:
    ``cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty``
  * Center for Computational Biology (CCB) principal investigators:
    ``ccb.berkeley.edu/people/core-faculty``

Directory: https://cdss.berkeley.edu/about/people

Usage:
    python -m src.collectors.ucb_datascience_faculty            # fetch & preview
    python -m src.collectors.ucb_datascience_faculty --save     # merge into processed data
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    clean_name,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

CDSS_CONFIG = {
    "source": "ucb_datascience_faculty",
    "name": "Computing, Data Science & Society (CDSS)",
    "short": "CDSS",
    "url": "https://cdss.berkeley.edu/about/people",
    "base": "https://cdss.berkeley.edu",
    "majors": ["Data Science", "Statistics", "Computer Science"],
    "keywords": ["data science"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
}

_DSUS = "https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty"
_CCB = "https://ccb.berkeley.edu/people/core-faculty"

# Individually verified Berkeley profiles, 2026-11-26. Only replace the
# reviewed DSUS card destination. A newly supplied link takes precedence.
_DSUS_PROFILES = {
    ("Giles Hooker", "https://gileshooker.com/"): "https://statistics.berkeley.edu/people/giles-hooker",
    ("Daniel Roddy", ""): "https://history.berkeley.edu/people/faculty/visiting/daniel-roddy",
    ("Eric Van Dusen", ""): "https://cdss.berkeley.edu/people/eric-van-dusen",
}

# The two unit directories: (url, base-for-relative-links).
_SOURCES = [
    (_DSUS, "https://cdss.berkeley.edu"),
    (_CCB, "https://ccb.berkeley.edu"),
]

# A person name heading: 2-4 capitalized tokens (allowing initials/accents/hyphens).
# Section/field headings ("Faculty", "Genomics", "…Committee") never match.
_PERSON_RE = re.compile(r"^[A-Z][A-Za-zé.\-']+(?: [A-Z][A-Za-zé.\-']+){1,3}$")

# Non-name words: any heading containing one of these is a section/unit label
# ("DSUS Faculty Leadership", "Data Science Course Instructors", "…Committee"),
# not a person — reject it even though it matches the capitalized-tokens shape.
_NON_NAME_WORDS = re.compile(
    r"\b(faculty|leadership|committee|instructors?|governance|program|science|"
    r"navigation|staff|overview|page|dsus|cdss|center|group|research)\b",
    re.IGNORECASE,
)


def _scrape_headings(soup: BeautifulSoup, base: str, page_url: str = "") -> list[dict]:
    """Parse a CDSS unit page whose faculty are name headings (h2/h3/h4), each
    followed by a role/department line and a profile link. Best-effort: the
    role line becomes the title, the first profile-ish link becomes the URL
    (falling back to the directory page when a person has no own link), and
    email is left empty (these directories expose no mailto)."""
    out: list[dict] = []
    for h in soup.find_all(["h2", "h3", "h4"]):
        raw = h.get_text(" ", strip=True)
        if not raw or not _PERSON_RE.match(raw) or _NON_NAME_WORDS.search(raw):
            continue
        name = clean_name(raw)
        if not name or len(name) < 3:
            continue
        block = h.parent
        # Role/department line = the block text with the name removed.
        block_text = block.get_text(" ", strip=True) if block else ""
        title = block_text.replace(raw, "", 1).strip(" |·-—") if block_text else ""
        # First profile link in the block: an absolute http(s) URL or a
        # /people|/faculty path, excluding mailto and social/nav links. Faculty
        # personal sites (dennisfeehan.org, carlboettiger.info) are common here,
        # so don't require a .edu/known-path pattern.
        url = ""
        if block:
            # CCB wraps the name and role together inside the profile anchor.
            # DSUS puts the anchor inside the name heading; the professor's
            # personal homepage can legitimately end at the domain root.
            named = h.find("a", href=True)
            if (block.name == "a" and block.has_attr("href")
                    and block.find_parent(class_="node-openberkeley-person")):
                named = block
            links = [named] if named is not None else block.find_all("a", href=True)
            for a in links:
                href = a["href"].strip()
                if not href.startswith(("http://", "https://", "/people/", "/person/", "/faculty/", "/pi/")):
                    continue
                target = urljoin(base, href)
                host = urlsplit(target).hostname or ""
                if re.search(r"(?:^|\.)(?:twitter|x|facebook|linkedin|instagram|bsky|youtube|github)\.com$", host, re.I):
                    continue
                if href.endswith("/") and (a is not named or (host == urlsplit(base).hostname and urlsplit(target).path == "/")):
                    continue
                url = target
                break
        if page_url == _DSUS:
            url = _DSUS_PROFILES.get((name, url), url)
        out.append({
            "name": name,
            # Real per-person profile link (may be ""); the directory-page
            # fallback is applied later in fetch_and_normalize so it is never
            # used as a dedup key (else every link-less person would collapse
            # onto the one shared directory URL).
            "url": url,
            "_page": page_url or base,
            "email": "",
            "title": title[:80],
            "research_areas": "",
        })
    return out


def _richness(r: dict) -> tuple[bool, bool, int]:
    """Orderable richness of a scraped row: a real profile link beats none,
    a stated role line beats an empty one, longer role text
    breaks ties."""
    title = (r.get("title") or "").strip()
    return (
        bool((r.get("url") or "").strip()),
        title.lower() not in ("", "professor"),
        len(title),
    )


def _dedup_keep_richer(raw: list[dict]) -> list[dict]:
    """Collapse same-name rows keeping the richer one (first-seen order kept).

    The DSUS listing repeats people across sections (leadership card + home-
    department card), and first-wins kept whichever came first — live probe
    2026-07: the link-less leadership card won for Lisa Yan / John DeNero /
    Zachary Pardos, dropping their real profile URLs."""
    kept: dict[str, dict] = {}
    for r in raw:
        key = r.get("name", "").strip().lower()
        if not key:
            continue
        cur = kept.get(key)
        if cur is None or _richness(r) > _richness(cur):
            kept[key] = r
    return list(kept.values())


def _first_last(name: str) -> tuple[str, str] | None:
    parts = (name or "").split()
    return (parts[0].lower(), parts[-1].lower()) if len(parts) >= 2 else None


def _drop_already_covered(records: list[dict]) -> list[dict]:
    """Drop scraped people whose (first, last) name is active under another
    ucb_* faculty source.

    CDSS is a pure overlay of existing departments, so a name already in the
    corpus IS the same person — but the shared drop_joint_appointment_duplicates
    keys on exact normalized name / email, so middle-initial variants ("Michael
    I. Jordan" vs "Michael Jordan", lite records with no email) slip through as
    soft duplicates. This looser (first,last) pass catches them before merge.
    Reads the corpus best-effort; if unavailable, returns records unchanged."""
    try:
        existing = json.loads(ucb_common.PROCESSED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return records
    covered = {
        _first_last(o.get("pi_name") or "")
        for o in existing
        if (o.get("source") or "").startswith("ucb_")
        and o.get("source") != CDSS_CONFIG["source"]
        and o.get("source_type") == "faculty_research"
        and (o.get("metadata") or {}).get("is_active") is not False
        and o.get("pi_name")
    }
    covered.discard(None)
    kept = [r for r in records if _first_last(r.get("name", "")) not in covered]
    if len(kept) != len(records):
        logger.info("  dropped %d CDSS faculty already covered by a home department",
                    len(records) - len(kept))
    return kept


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape the DSUS + CCB directories and return normalized records.

    ``enrich`` is accepted for CLI symmetry with the other UCB collectors but no
    per-profile hop is performed (the pages carry no emails). The heavy overlap
    with home departments is resolved at merge time by
    drop_joint_appointment_duplicates, leaving only the CDSS-primary faculty."""
    raw: list[dict] = []
    for url, base in _SOURCES:
        soup = fetch_soup(url)
        if not soup:
            logger.warning("CDSS: directory fetch failed for %s", url)
            continue
        rows = _scrape_headings(soup, base, page_url=url)
        logger.info("  %d faculty headings from %s", len(rows), url)
        raw.extend(rows)
    # Dedup by name (not profile URL): many CDSS faculty have no individual
    # link, so URL-dedup would be unreliable here.
    raw = _drop_already_covered(_dedup_keep_richer(raw))
    if not raw:
        return []
    # Apply the directory-page URL fallback now (after dedup) so every record
    # has a resolvable url without link-less people colliding during dedup.
    for r in raw:
        r["url"] = r.get("url") or r.get("_page") or CDSS_CONFIG["url"]
    normalized = []
    for person in raw:
        record = normalize_faculty(person, CDSS_CONFIG)
        if record:
            # The university directory is what this collector actually read.
            # A name-linked external homepage is the destination, not the source
            # for the faculty listing or for the recorded observation time.
            record["source_url"] = person["_page"]
            record["metadata"]["verification_scope"] = "directory"
            normalized.append(record)
    logger.info("Normalized %d CDSS/Data Science faculty opportunities", len(normalized))
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(CDSS_CONFIG, "UC Berkeley CDSS / Data Science Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
