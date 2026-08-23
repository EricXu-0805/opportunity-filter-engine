"""Collector for the UC Berkeley URAP live project database.

This is Berkeley's analog to UIUC's SRO listings DB (``uiuc_sro``): the URAP
project database at ``urapprojects.berkeley.edu/list.php`` enumerates individual
faculty-posted research projects open to undergraduates. ``ucb_urap.py`` emits
only a static *program overview* and explicitly deferred scraping this DB; this
collector fills that gap.

Seasonal, by design: URAP projects are only posted during the application window
(Fall projects post in late summer). Off-window, ``status=Open`` returns zero
projects — so this collector legitimately yields 0 *open* records most of the
year and auto-populates (hundreds of projects) once the window opens.

Two statuses are collected:
  * ``status=Open``  — live, actionable projects currently recruiting apprentices.
  * ``status=Closed`` — the ~860 past/full projects. These are seeded (``past=True``)
    with honest, non-actionable messaging as a *reference* for the kind of
    undergraduate research each lab offers — valuable off-season when Open is
    empty, and a durable map of which faculty take URAP undergraduates. They are
    flagged ``is_rolling=False`` + ``metadata.urap_status="closed"`` so the UI and
    ranking can deprioritize them relative to live openings.

Page structure (validated against the live closed listing):
  * ``list.php?status=Open&skip=N`` — paginated 50/page via a ``skip`` offset.
  * Each project is a title link ``<a href="detail.php?id=ID">Title</a>`` inside
    a row that also carries a ``Faculty Name - Title, Department`` line, a
    ``Status: … Weekly Hours: … Location: …`` line, and a description.

Robustness note: the live markup exposes no stable CSS classes for the row
internals, so the parser anchors on the certain signal — the
``detail.php?id=`` title links — and best-effort-extracts the faculty/department/
description from each row's text. Title + project URL are always captured; the
other fields degrade gracefully to empty.

The HTTP deps (``requests``/``bs4``) are imported lazily so importing this module
(and the normalization path) needs only the standard library.

Usage:
    python -m src.collectors.ucb_urap_projects            # scrape open projects (preview)
    python -m src.collectors.ucb_urap_projects --save     # merge into processed data
    python -m src.collectors.ucb_urap_projects --status Closed  # dev: scrape closed (for validation)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

BASE_URL = "https://urapprojects.berkeley.edu"
LIST_URL = f"{BASE_URL}/list.php"
APPLICATION_URL = "https://research.berkeley.edu/urap/application/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PER_PAGE = 50          # the DB returns 50 projects/page
_MAX_PAGES = 40        # safety cap (40*50 = 2000 projects); Open is far smaller
_TIMEOUT = 30
_PAGE_DELAY = 1.0      # politeness between page fetches

SOURCE = "ucb_urap_projects"

# "Faculty Name - Job Title, Department" — the mentor line on each row.
_FACULTY_RE = re.compile(r"^\s*(.+?)\s+-\s+(.+?),\s+(.+?)\s*$")
_HOURS_RE = re.compile(r"Weekly Hours:\s*([^\n]+?)(?:\s{2,}|\n|Location:|$)", re.IGNORECASE)
_LOCATION_RE = re.compile(r"Location:\s*([^\n]+?)(?:\s{2,}|\n|$)", re.IGNORECASE)
_STATUS_RE = re.compile(r"Status:\s*([^\n]+?)(?:\s{2,}|\n|Weekly Hours:|$)", re.IGNORECASE)
_ID_RE = re.compile(r"id=([\w-]+)")

KEYWORD_BANK = [
    "machine learning", "deep learning", "computer vision", "data science",
    "artificial intelligence", "natural language processing", "robotics",
    "neuroscience", "genomics", "bioinformatics", "statistics", "biology",
    "chemistry", "physics", "materials science", "public health", "economics",
    "psychology", "climate", "sustainability", "signal processing",
]


# ---------------------------------------------------------------------------
# Parsing (operates on a BeautifulSoup object; no network)
# ---------------------------------------------------------------------------

def parse_list_page(soup) -> list[dict]:
    """Extract project rows from one list-page soup.

    Anchored on the certain ``detail.php?id=`` title links; the faculty/dept/
    description are best-effort from each row's text block.
    """
    projects: list[dict] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='detail.php?id=']"):
        href = a.get("href", "")
        m = _ID_RE.search(href)
        if not m:
            continue
        pid = m.group(1)
        title = a.get_text(" ", strip=True)
        if not title or pid in seen:
            continue
        seen.add(pid)

        # Walk up to the row container — the nearest ancestor whose text carries
        # the status/hours line that's part of every entry.
        container = a
        for _ in range(5):
            parent = getattr(container, "parent", None)
            if parent is None:
                break
            container = parent
            ctext = container.get_text(" ", strip=True)
            if "Weekly Hours" in ctext or "Location:" in ctext:
                break

        fields = _extract_row_fields(container.get_text("\n", strip=True), title)
        projects.append({
            "id": pid,
            "title": title,
            "url": urljoin(BASE_URL + "/", href),
            **fields,
        })
    return projects


def _extract_row_fields(block_text: str, title: str) -> dict:
    """Best-effort pull faculty / department / description / hours from a row's
    text. Every field degrades to '' when the heuristic doesn't match."""
    faculty = department = faculty_title = description = hours = location = status = ""
    lines = [ln.strip() for ln in block_text.split("\n") if ln.strip() and ln.strip() != title]
    for ln in lines:
        if not faculty:
            fm = _FACULTY_RE.match(ln)
            # Guard against matching the description: faculty line is short.
            if fm and len(ln) < 120:
                faculty, faculty_title, department = (g.strip() for g in fm.groups())
                continue
        if not hours:
            hm = _HOURS_RE.search(ln)
            if hm:
                hours = hm.group(1).strip()
        if not location:
            lm = _LOCATION_RE.search(ln)
            if lm:
                location = lm.group(1).strip()
        if not status:
            sm = _STATUS_RE.search(ln)
            if sm:
                status = sm.group(1).strip()
    # Description = the longest line that isn't the faculty/status line.
    candidates = [
        ln for ln in lines
        if ln not in (faculty,) and "Weekly Hours" not in ln and not ln.startswith("Status:")
        and not _FACULTY_RE.match(ln)
    ]
    if candidates:
        description = max(candidates, key=len)
    return {
        "faculty": faculty,
        "faculty_title": faculty_title,
        "department": department,
        "description": description,
        "weekly_hours": hours,
        "location": location,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Fetching (lazy HTTP deps)
# ---------------------------------------------------------------------------

def _fetch(url: str, params: dict):
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception as e:  # noqa: BLE001
        logger.warning("URAP projects: HTTP deps unavailable (%s)", e)
        return None
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser")
    except Exception as e:  # noqa: BLE001 — never crash the run
        logger.warning("URAP projects: fetch failed for %s %s: %s", url, params, e)
        return None


def scrape_projects(status: str = "Open") -> list[dict]:
    """Paginate the URAP DB for the given status and return raw project dicts."""
    out: list[dict] = []
    seen_ids: set[str] = set()
    for page in range(_MAX_PAGES):
        soup = _fetch(LIST_URL, {"status": status, "skip": page * PER_PAGE})
        if soup is None:
            break
        rows = parse_list_page(soup)
        fresh = [r for r in rows if r["id"] not in seen_ids]
        if not fresh:
            break  # empty page (off-season Open) or no new ids → done
        for r in fresh:
            seen_ids.add(r["id"])
            out.append(r)
        if len(rows) < PER_PAGE:
            break
        time.sleep(_PAGE_DELAY)
    logger.info("URAP projects (status=%s): %d projects scraped", status, len(out))
    return out


# ---------------------------------------------------------------------------
# Normalization (stdlib only)
# ---------------------------------------------------------------------------

def _keywords(text: str) -> list[str]:
    low = (text or "").lower()
    found = [kw for kw in KEYWORD_BANK if kw in low]
    return found[:6] or ["undergraduate research"]


def _row_states_closed(status: object) -> bool:
    """Whether a row's own parsed Status field states the project is closed.

    Deliberately narrow: the first word of the parsed field only. URAP writes
    "Closed - no longer accepting apprentices" and "Open- accepting new
    students", so the leading token is the whole signal. Scanning the free-text
    remainder would start guessing from prose.
    """
    if not isinstance(status, str):
        return False
    head = status.strip().lower().split("-", 1)[0].strip()
    return head == "closed"


def normalize_project(raw: dict, past: bool = False) -> dict:
    """Normalize one URAP project row.

    ``past=True`` marks a record scraped from the *Closed* listing: a project
    that is no longer recruiting, seeded as a reference for the kind of
    undergraduate research a lab offers (URAP posts fresh projects each
    application cycle, and the live ``status=Open`` collector picks those up).

    A past project is excluded from the actionable universe, not merely ranked
    lower: it emits ``metadata.is_active=False`` alongside the ``urap_status``
    marker, and carries no ``application_url``, because the only URL URAP
    offers is the program-wide portal — presenting that as this project's
    application is an invitation to apply to something that closed. The
    project page stays reachable through ``url``/``source_url`` as reference.

    A row whose own parsed ``status`` states it is closed is treated as past no
    matter which page it arrived on. ``?status=Open`` is a query, not a
    guarantee: URAP re-labels projects mid-cycle, and trusting only the
    caller's flag writes such a row back as open and actionable on the very
    next refresh. Only the parsed status field is consulted — never the
    description prose, which would be guesswork.
    """
    past = past or _row_states_closed(raw.get("status"))
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    opp_id = "ucb-urap-proj-" + hashlib.md5(raw["id"].encode()).hexdigest()[:12]
    faculty = raw.get("faculty", "")
    dept = raw.get("department", "")
    desc_parts = []
    if past:
        desc_parts.append(
            "[Past URAP project — this listing is closed and no longer recruiting "
            "apprentices. Shown as a reference for the kind of undergraduate "
            "research this lab offers; check the live URAP portal for current openings.]"
        )
    if faculty:
        ftitle = raw.get("faculty_title", "") or "Faculty"
        verb = "Past URAP research project with" if past else "URAP research project with"
        desc_parts.append(f"{verb} {ftitle} {faculty}"
                          + (f" ({dept})" if dept else "") + ".")
    if raw.get("description"):
        desc_parts.append(raw["description"])
    if raw.get("weekly_hours"):
        desc_parts.append(f"Weekly hours: {raw['weekly_hours']}.")
    if past:
        desc_parts.append(
            "URAP is open to matriculated UC Berkeley undergraduates for academic "
            "credit; this particular project is not currently accepting applications."
        )
    else:
        desc_parts.append(
            "Open to matriculated UC Berkeley undergraduates for academic credit "
            "(URAP). Apply through the URAP application portal."
        )
    description = " ".join(desc_parts)[:1500]

    lab = f"Prof. {faculty}'s URAP project" if faculty else "URAP project"

    return {
        "id": opp_id,
        "source": SOURCE,
        "source_type": "ucb_program",
        "source_url": raw["url"],
        "title": raw["title"][:200],
        "organization": "University of California, Berkeley",
        "department": dept,
        "lab_or_program": lab,
        # Never set pi_name: a professor with multiple URAP projects (or who also
        # appears in a faculty directory) would otherwise collide on a shared
        # pi_name and fail the ucb_* joint-appointment data-quality gate. The
        # mentor's name lives in lab_or_program + description instead.
        "pi_name": None,
        "contact_email": None,
        "url": raw["url"],
        "location": "Berkeley, CA",
        # A URAP project runs in a Berkeley lab; school (ucb) carries whose
        # campus it is, and the ranker compares that to profile.home_school.
        "on_campus": True,
        "remote_option": "unknown",
        "opportunity_type": "research",
        # URAP is for academic credit, not pay (per the program overview).
        "paid": "no",
        "compensation_details": "Academic credit (URAP)",
        # No per-project structured deadline is exposed; projects post per
        # application cycle. Open projects are rolling (no fixed deadline); past
        # projects are not currently recruiting, so they are not marked rolling.
        "deadline": None,
        "is_rolling": not past,
        "posted_date": None,
        "start_date": None,
        "duration": "Semester or academic year",
        "eligibility": {
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": [],
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": False,
            # URAP admits only Berkeley-matriculated students; openness to this
            # product's (non-Berkeley) users is therefore not "yes".
            "international_friendly": "unknown",
            "work_auth_notes": "",
            "eligibility_text_raw": (raw.get("description") or "")[:300],
        },
        "application": {
            "contact_method": "website",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": None if past else APPLICATION_URL,
        },
        "description": description,
        "description_raw": description,
        "description_clean": description[:1500],
        "keywords": _keywords(f"{raw['title']} {raw.get('description', '')}"),
        "school": "ucb",
        "audience": "campus",
        "metadata": {
            "confidence_score": 0.5 if past else 0.6,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": not past,
            "manually_reviewed": False,
            "notes": (
                "Auto-imported from URAP project database "
                "(urapprojects.berkeley.edu); closed/past project, seeded for reference"
                if past else
                "Auto-imported from URAP project database (urapprojects.berkeley.edu)"
            ),
            "urap_project_id": raw["id"],
            "urap_status": "closed" if past else "open",
        },
    }


def fetch_and_normalize(status: str = "Open") -> list[dict]:
    past = status.strip().lower() == "closed"
    return [normalize_project(r, past=past) for r in scrape_projects(status=status)]


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Upsert by id. Never overwrites the corpus with an empty scrape (off-season
    Open returns 0 — that must not delete previously-collected projects)."""
    if not PROCESSED_FILE.exists():
        return (0, 0)
    if not new_opps:
        logger.info("URAP projects: 0 scraped (likely off-season) — leaving corpus untouched")
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    index = {o.get("id"): o for o in existing if o.get("id")}
    added = updated = 0
    for opp in new_opps:
        if opp["id"] in index:
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get(
                "metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            index[opp["id"]].update(opp)
            updated += 1
        else:
            existing.append(opp)
            index[opp["id"]] = opp
            added += 1
    with PROCESSED_FILE.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
    return (added, updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="Merge into processed/opportunities.json")
    parser.add_argument("--status", default="Open", help="Project status to scrape (default: Open)")
    args = parser.parse_args()

    opps = fetch_and_normalize(status=args.status)
    print(f"Fetched {len(opps)} URAP projects (status={args.status})")
    for o in opps[:8]:
        print(f"  - {o['title'][:70]}  [{o['lab_or_program']}]")
    if not opps and args.status == "Open":
        print("\n(0 open projects — expected off-season; URAP posts projects "
              "during the application window, ~late summer.)")
    if args.save:
        a, u = merge_into_processed(opps)
        print(f"\nSaved: +{a} new, ~{u} updated")
    else:
        print("\n(Use --save to merge into processed/opportunities.json)")
