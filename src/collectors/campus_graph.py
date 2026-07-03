"""School-agnostic campus opportunity-graph engine.

Generalizes the Berkeley campus collector (``ucb_campus``) into a reusable engine
so each new school (the US-News Top-50 rollout) is just a small config module
under ``src/collectors/schools/`` — not a fresh copy of the engine.

A school config (see ``schools/princeton.py`` for the first one) is a dict:

    {
      "school_slug": "princeton",                 # frontend SCHOOLS slug
      "organization": "Princeton University",
      "location": "Princeton, NJ",
      # emit bucket -> (source value, school slug | None, audience). MUST match
      # school_audience.SOURCE_DEFAULTS or the data-quality gate fails.
      "emit": {
        "campus": ("princeton_research_programs", "princeton", "campus"),
        "open":   ("princeton_external_research", None,        "open"),
        "lab":    ("princeton_labs",              "princeton", "unknown"),
      },
      "sources": [ {source_name, source_type, emit, seeds, crawl, programs:[...]}, ... ],
    }

Each source's ``programs`` are curated seed specs built with ``program(...)``.
The seed layer is stdlib-only and offline-safe (records can be generated and
committed without any network); the deep-mode BFS crawl lazy-imports requests/bs4
and only refines status + discovers extra postings. Same model as ucb_campus.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from src.normalizers.ucb_dedup import dedupe_against_existing

from .ucb_common import _readable_excerpt

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

# --- Taxonomy (shared across all schools) ----------------------------------
ANNOUNCEMENT, PROGRAM, DEPARTMENT, CAREER, LAB = (
    "announcement", "program", "department", "career", "lab",
)
SOURCE_TYPES = frozenset({ANNOUNCEMENT, PROGRAM, DEPARTMENT, CAREER, LAB})
STATIC, RECURSIVE, RSS, SITEMAP = "static", "recursive", "rss", "sitemap"
CRAWL_STRATEGIES = frozenset({STATIC, RECURSIVE, RSS, SITEMAP})
DAILY, WEEKLY, MONTHLY, SEASONAL = "daily", "weekly", "monthly", "seasonal"
EMIT_BUCKETS = frozenset({"campus", "open", "lab"})

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
OPEN_KEYWORDS = ("applications open", "apply now", "now accepting",
                 "application open", "now recruiting", "now hiring")
CLOSED_KEYWORDS = ("applications closed", "application closed",
                   "no longer accepting", "deadline has passed")
PRIORITY_KEYWORDS = (
    "undergraduate research", "summer research", "join our lab", "join the lab",
    "research assistant", "research opportunit", "research program",
    "research experience", "directed research", "independent study",
    "senior thesis", "design team", "internship", "fellowship", "scholarship",
    "reu", "apply", "recruiting", "open position", "open positions",
    "lab opening", "now hiring", "get involved", "work with us",
)
_GENERIC_ANCHOR = frozenset({
    "undergraduate research", "research", "research opportunities",
    "research opportunity", "summer research", "opportunities", "opportunity",
    "apply", "apply now", "apply here", "learn more", "read more", "more",
    "join our lab", "join the lab", "internships", "internship",
    "research assistant", "fellowships", "fellowship", "get involved",
    "for students", "prospective students", "current students",
})

_CRAWL_TIMEOUT = 20
_MAX_PAGES_PER_SOURCE = 25
_MAX_DISCOVERED_PER_SOURCE = 20
_DESC_CAP = 1500
_PAGE_DELAY = 0.0  # set per-call if needed
_NAV_TITLE_RE = re.compile(r"^(home|menu|skip to|search|login|apply now|contact|about)$", re.IGNORECASE)


def program(
    key: str, title: str, url: str, description: str, *,
    organization: str = "", department: str = "", lab_or_program: str = "",
    opportunity_type: str = "research", paid: str = "unknown", compensation: str = "",
    eligibility_majors: list[str] | None = None, preferred_year: list[str] | None = None,
    international_friendly: str = "unknown", deadline_note: str = "",
    keywords: list[str] | None = None,
) -> dict:
    """Build one curated opportunity spec (school-agnostic)."""
    return {
        "key": key, "title": title, "url": url, "description": description,
        "organization": organization, "department": department,
        "lab_or_program": lab_or_program, "opportunity_type": opportunity_type,
        "paid": paid, "compensation": compensation,
        "eligibility_majors": eligibility_majors or [],
        "preferred_year": preferred_year or ["sophomore", "junior", "senior"],
        "international_friendly": international_friendly, "deadline_note": deadline_note,
        "keywords": keywords or [],
    }


def validate(school: dict) -> list[str]:
    """Structural problems with a school config (empty = healthy)."""
    errors: list[str] = []
    if not school.get("school_slug"):
        errors.append("missing school_slug")
    emit = school.get("emit", {})
    for bucket in emit:
        if bucket not in EMIT_BUCKETS:
            errors.append(f"bad emit bucket {bucket!r}")
    seen_keys: set[str] = set()
    for s in school.get("sources", []):
        if s.get("source_type") not in SOURCE_TYPES:
            errors.append(f"{s.get('source_name')}: bad source_type {s.get('source_type')!r}")
        if s.get("emit") not in emit:
            errors.append(f"{s.get('source_name')}: emit {s.get('emit')!r} not in school's emit map")
        if s.get("crawl") not in CRAWL_STRATEGIES:
            errors.append(f"{s.get('source_name')}: bad crawl {s.get('crawl')!r}")
        if not s.get("seeds"):
            errors.append(f"{s.get('source_name')}: no seeds")
        for p in s.get("programs", []):
            if p["key"] in seen_keys:
                errors.append(f"duplicate program key {p['key']}")
            seen_keys.add(p["key"])
            if p.get("opportunity_type") not in {"research", "summer_program", "internship", "fellowship"}:
                errors.append(f"{p['key']}: bad opportunity_type {p.get('opportunity_type')!r}")
    return errors


# --- Normalization (stdlib only) -------------------------------------------

def _hash_id(slug: str, source: str, key: str) -> str:
    return f"{slug}-" + hashlib.md5(f"{source}::{key}".encode()).hexdigest()[:12]


def _normalize_program(school: dict, source: dict, program_spec: dict, *,
                       status: str = "unknown", extra_desc: str = "") -> dict:
    src_value, school_slug, audience = school["emit"][source["emit"]]
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    description = program_spec["description"]
    if extra_desc:
        description = f"{description}\n\nFrom the program page: {extra_desc}"
    description = description[:_DESC_CAP]
    title = program_spec["title"]
    if status == "open":
        title = f"{title} (applications open)"
    elif status == "closed":
        title = f"{title} (applications closed)"
    intl = program_spec.get("international_friendly", "unknown")
    keywords = list(dict.fromkeys(
        [k for k in program_spec.get("keywords", []) if k] + [source["source_type"]]
    ))
    return {
        "id": _hash_id(school["school_slug"], src_value, program_spec["key"]),
        "source": src_value,
        "source_type": f"campus_{source['source_type']}",
        "campus_source_type": source["source_type"],
        "source_url": program_spec["url"],
        "title": title,
        "organization": program_spec.get("organization") or school["organization"],
        "department": program_spec.get("department", ""),
        "lab_or_program": program_spec.get("lab_or_program", ""),
        "pi_name": None,
        "contact_email": None,
        "url": program_spec["url"],
        "location": school["location"],
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": program_spec.get("opportunity_type", "research"),
        "paid": program_spec.get("paid", "unknown"),
        "compensation_details": program_spec.get("compensation", ""),
        "deadline": None,
        "is_rolling": True,
        "posted_date": None,
        "start_date": None,
        "duration": None,
        "eligibility": {
            "preferred_year": program_spec.get("preferred_year", ["sophomore", "junior", "senior"]),
            "min_gpa": None,
            "majors": program_spec.get("eligibility_majors", []),
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": intl == "no",
            "international_friendly": intl,
            "work_auth_notes": "",
            "eligibility_text_raw": (program_spec.get("deadline_note", "") or "")[:300],
        },
        "application": {
            "contact_method": "website",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": program_spec["url"],
        },
        "description": description,
        "description_raw": description,
        "description_clean": description[:_DESC_CAP],
        "keywords": keywords,
        "school": school_slug,
        "audience": audience,
        "metadata": {
            "confidence_score": 0.7,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Auto-imported from {source['source_name']} ({source['source_type']})",
            "collector_key": program_spec["key"],
            "collector_source": source["source_name"],
            "status": status,
            "deadline_note": program_spec.get("deadline_note", ""),
        },
    }


def _normalize_discovered(school: dict, source: dict, title: str, url: str, snippet: str) -> dict:
    src_value, school_slug, audience = school["emit"][source["emit"]]
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    desc = (snippet or title)[:_DESC_CAP]
    key = "disc-" + hashlib.md5(url.encode()).hexdigest()[:10]
    return {
        "id": _hash_id(school["school_slug"], src_value, key),
        "source": src_value,
        "source_type": f"campus_{source['source_type']}",
        "campus_source_type": source["source_type"],
        "source_url": url,
        "title": title[:200],
        "organization": school["organization"],
        "department": "",
        "lab_or_program": "",
        "pi_name": None,
        "contact_email": None,
        "url": url,
        "location": school["location"],
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": "research",
        "paid": "unknown",
        "compensation_details": "",
        "deadline": None,
        "is_rolling": True,
        "posted_date": None,
        "start_date": None,
        "duration": None,
        "eligibility": {
            "preferred_year": ["sophomore", "junior", "senior"],
            "min_gpa": None, "majors": [], "skills_required": [], "skills_preferred": [],
            "citizenship_required": False, "international_friendly": "unknown",
            "work_auth_notes": "", "eligibility_text_raw": desc[:300],
        },
        "application": {
            "contact_method": "website", "requires_resume": "unknown",
            "requires_cover_letter": "unknown", "requires_transcript": "unknown",
            "requires_recommendation": "unknown", "application_effort": "medium",
            "application_url": url,
        },
        "description": desc,
        "description_raw": desc,
        "description_clean": desc[:_DESC_CAP],
        "keywords": [source["source_type"], "undergraduate research"],
        "school": school_slug,
        "audience": audience,
        "metadata": {
            "confidence_score": 0.4, "last_verified": now, "first_seen_at": now,
            "last_seen_at": now, "is_active": True, "manually_reviewed": False,
            "notes": f"Crawl-discovered from {source['source_name']}",
            "collector_source": source["source_name"], "discovered": True,
        },
    }


# --- Crawl layer (lazy HTTP deps) ------------------------------------------

def _fetch(url: str):
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception as e:  # noqa: BLE001
        logger.warning("campus_graph: HTTP deps unavailable (%s); seed-only", e)
        return None
    try:
        resp = requests.get(url, timeout=_CRAWL_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser")
    except Exception as e:  # noqa: BLE001
        logger.warning("campus_graph: fetch failed for %s: %s", url, e)
        return None


def _detect_status(page_text: str) -> str:
    low = page_text.lower()
    if any(k in low for k in OPEN_KEYWORDS):
        return "open"
    if any(k in low for k in CLOSED_KEYWORDS):
        return "closed"
    return "unknown"


def _looks_like_opportunity(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in PRIORITY_KEYWORDS)


def _is_specific_opportunity(anchor: str) -> bool:
    a = anchor.strip().lower().rstrip(" »›>").strip()
    if a in _GENERIC_ANCHOR or len(anchor.strip()) < 12:
        return False
    return _looks_like_opportunity(anchor)


def _same_site(seed: str, candidate: str) -> bool:
    try:
        sh = (urlsplit(seed).hostname or "").lower()
        ch = (urlsplit(candidate).hostname or "").lower()
    except ValueError:
        return False
    if not ch:
        return False
    # same host, or shares the school's registrable domain (last two labels).
    sh_root = ".".join(sh.split(".")[-2:])
    return ch == sh or (sh_root and ch.endswith(sh_root))


def _crawl_source(school: dict, source: dict) -> tuple[dict, list[dict]]:
    status_by_url: dict[str, dict] = {}
    discovered: list[dict] = []
    depth_limit = source.get("crawl_depth", 1)
    recursive = source.get("crawl") == RECURSIVE
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque((s, 0) for s in source.get("seeds", []))
    discovered_urls: set[str] = set()

    while queue and len(visited) < _MAX_PAGES_PER_SOURCE:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        soup = _fetch(url)
        if soup is None:
            continue
        page_text = soup.get_text(" ", strip=True)
        # Status reads the whole page; the excerpt uses chrome-excluded main
        # content so nav/menu furniture never lands in the shown description.
        status_by_url[url] = {"status": _detect_status(page_text), "excerpt": _readable_excerpt(soup)}
        if not recursive or depth >= depth_limit:
            continue
        scored: list[tuple[int, str, str]] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"].split("#")[0])
            if not href.startswith("http") or not _same_site(url, href):
                continue
            anchor = a.get_text(" ", strip=True)
            if not anchor or _NAV_TITLE_RE.match(anchor):
                continue
            score = sum(1 for kw in PRIORITY_KEYWORDS if kw in (anchor.lower() + " " + href.lower()))
            if score:
                scored.append((score, href, anchor))
        scored.sort(key=lambda t: t[0], reverse=True)
        for _score, href, anchor in scored:
            if href in visited:
                continue
            queue.append((href, depth + 1))
            if (len(discovered) < _MAX_DISCOVERED_PER_SOURCE
                    and href not in discovered_urls
                    and _is_specific_opportunity(anchor)):
                discovered_urls.add(href)
                discovered.append(_normalize_discovered(school, source, anchor, href, anchor))
    return status_by_url, discovered


# --- Public API -------------------------------------------------------------

def fetch_and_normalize(school: dict, deep: bool = False) -> list[dict]:
    errors = validate(school)
    if errors:
        raise ValueError(f"{school.get('school_slug')} config invalid: " + "; ".join(errors))
    records: list[dict] = []
    for source in school.get("sources", []):
        status_by_url: dict[str, dict] = {}
        discovered: list[dict] = []
        if deep:
            try:
                status_by_url, discovered = _crawl_source(school, source)
            except Exception as e:  # noqa: BLE001
                logger.warning("crawl failed for %s: %s", source["source_name"], e)
        for spec in source.get("programs", []):
            refine = status_by_url.get(spec["url"], {})
            records.append(_normalize_program(
                school, source, spec,
                status=refine.get("status", "unknown"),
                extra_desc=refine.get("excerpt", ""),
            ))
        records.extend(discovered)
    records, dropped = dedupe_against_existing(records, [])
    if dropped:
        logger.info("%s: dropped %d intra-batch duplicate(s)", school["school_slug"], dropped)
    return records


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    if not PROCESSED_FILE.exists() or not new_opps:
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    new_opps, dropped = dedupe_against_existing(new_opps, existing)
    if dropped:
        logger.info("campus_graph: suppressed %d near-duplicate(s) vs corpus", dropped)
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


def source_breakdown(opps: list[dict]) -> dict:
    return {
        "total": len(opps),
        "by_source": dict(Counter(o.get("source") for o in opps)),
        "by_source_type": dict(Counter(o.get("campus_source_type") for o in opps)),
        "by_opportunity_type": dict(Counter(o.get("opportunity_type") for o in opps)),
        "discovered": sum(1 for o in opps if o.get("metadata", {}).get("discovered")),
    }
