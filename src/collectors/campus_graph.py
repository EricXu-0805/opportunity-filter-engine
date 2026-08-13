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
The seed layer is stdlib-only and offline-safe (records can be generated without
any network); the deep-mode BFS crawl lazy-imports requests/bs4 and refines
status + discovers extra postings. Publication is stricter than collection:
every configured seed page must load in deep mode, while failures on recursively
discovered pages are reported as degraded evidence.
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

from .application_status import detect_application_status
from .atomic_json import atomic_write_json
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
        "preferred_year": preferred_year or ["freshman", "sophomore", "junior", "senior"],
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
            # Mirror the corpus integrity tests' enum sets: a curated value
            # outside them only detonates at refresh time (the DQ gate rejects
            # the whole shard), so catch it here where PR CI validates configs.
            if p.get("international_friendly", "unknown") not in {"yes", "no", "unknown"}:
                errors.append(
                    f"{p['key']}: bad international_friendly "
                    f"{p.get('international_friendly')!r} (use yes/no/unknown)"
                )
            if p.get("paid", "unknown") not in {"yes", "no", "stipend", "unknown"}:
                errors.append(
                    f"{p['key']}: bad paid {p.get('paid')!r} (use yes/no/stipend/unknown)"
                )
    return errors


# --- Normalization (stdlib only) -------------------------------------------

def _hash_id(slug: str, source: str, key: str) -> str:
    return f"{slug}-" + hashlib.md5(f"{source}::{key}".encode()).hexdigest()[:12]


def _normalize_program(
    school: dict,
    source: dict,
    program_spec: dict,
    *,
    status: str = "unknown",
    extra_desc: str = "",
    seed_page_verified: bool = False,
) -> dict:
    src_value, school_slug, audience = school["emit"][source["emit"]]
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    last_verified = now if seed_page_verified else None
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
        # Derived from the emit bucket, not hardcoded: "open" rows are external
        # listings that merely surfaced on a campus page (school_slug None),
        # everything else is this school's own program. The blanket False dated
        # from the single-school era and made the field assert something untrue.
        "on_campus": school_slug is not None,
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
            "preferred_year": program_spec.get("preferred_year", ["freshman", "sophomore", "junior", "senior"]),
            "min_gpa": None,
            "majors": program_spec.get("eligibility_majors", []),
            "skills_required": [],
            "skills_preferred": [],
            # Tri-state (truthfulness W11): an explicit "no" implies a
            # citizenship bar; an explicit "yes" implies none; unknown stays
            # None — never asserted False without evidence.
            "citizenship_required": True if intl == "no" else (False if intl == "yes" else None),
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
            "last_verified": last_verified,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": status != "closed",
            "manually_reviewed": False,
            "notes": f"Auto-imported from {source['source_name']} ({source['source_type']})",
            "collector_key": program_spec["key"],
            "collector_source": source["source_name"],
            "status": status,
            "deadline_note": program_spec.get("deadline_note", ""),
            # This is deliberately separate from ``status``: a page can load
            # successfully without containing an explicit open/closed marker.
            # Merge uses it to avoid replacing a previously verified closed
            # state with an offline/quick-mode ``unknown + active`` default.
            "seed_page_verified": seed_page_verified,
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
        "on_campus": school_slug is not None,
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
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
            "min_gpa": None, "majors": [], "skills_required": [], "skills_preferred": [],
            "citizenship_required": None, "international_friendly": "unknown",
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
            "confidence_score": 0.4, "last_verified": None, "first_seen_at": now,
            "last_seen_at": now, "is_active": False, "manually_reviewed": False,
            "notes": f"Crawl-discovered from {source['source_name']}",
            "collector_source": source["source_name"], "discovered": True,
            "discovered_page_verified": False,
            "status": "unknown",
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
        from .ucb_common import _ca_bundle

        resp = requests.get(
            url,
            timeout=_CRAWL_TIMEOUT,
            headers=HEADERS,
            verify=_ca_bundle(),
        )
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser")
    except Exception as e:  # noqa: BLE001
        logger.warning("campus_graph: fetch failed for %s: %s", url, e)
        return None


def _detect_status(page_text: str) -> str:
    return detect_application_status(page_text)


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
        s, c = urlsplit(seed), urlsplit(candidate)
        sh = (s.hostname or "").lower()
        ch = (c.hostname or "").lower()
        # Force port parsing here so a malformed netloc — e.g. a phone number
        # scraped into an href ("host:(949) 824-1947") — is rejected at this gate
        # (returns False) rather than raising ``ValueError: Port could not be cast``
        # uncaught deeper in the fetch/normalize path and zeroing the whole source.
        _ = (s.port, c.port)
    except ValueError:
        return False
    if not ch:
        return False
    # same host, or shares the school's registrable domain (last two labels).
    sh_root = ".".join(sh.split(".")[-2:])
    return ch == sh or (sh_root and ch.endswith(sh_root))


def _crawl_source(school: dict, source: dict) -> tuple[dict, list[dict], dict]:
    status_by_url: dict[str, dict] = {}
    discovered: list[dict] = []
    seeds = list(dict.fromkeys(source.get("seeds", [])))
    seed_urls = set(seeds)
    depth_limit = source.get("crawl_depth", 1)
    recursive = source.get("crawl") == RECURSIVE
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque((s, 0) for s in seeds)
    discovered_urls: set[str] = set()
    seed_page_errors: list[str] = []
    degraded_page_errors: list[str] = []
    discovery_truncated = False

    while queue and len(visited) < _MAX_PAGES_PER_SOURCE:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        soup = _fetch(url)
        if soup is None:
            if url in seed_urls:
                seed_page_errors.append(url)
            else:
                degraded_page_errors.append(url)
            continue
        try:
            page_text = soup.get_text(" ", strip=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("campus_graph: parse failed for %s: %s", url, e)
            if url in seed_urls:
                seed_page_errors.append(url)
            else:
                degraded_page_errors.append(url)
            continue
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
            if href in discovered_urls or not _is_specific_opportunity(anchor):
                continue
            if len(discovered) < _MAX_DISCOVERED_PER_SOURCE:
                discovered_urls.add(href)
                discovered.append(_normalize_discovered(school, source, anchor, href, anchor))
            else:
                discovery_truncated = True
    # Anchors are candidates, not publication evidence. Only emit a discovered
    # record after its own page loaded; an unknown-status detail page stays
    # inactive until a later crawl sees an explicit open signal.
    verified_discovered: list[dict] = []
    verified_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
    for record in discovered:
        observation = status_by_url.get(record["url"])
        if not isinstance(observation, dict):
            continue
        status = observation.get("status", "unknown")
        metadata = record["metadata"]
        metadata["discovered_page_verified"] = True
        metadata["status"] = status
        metadata["last_verified"] = verified_at
        metadata["is_active"] = status == "open"
        verified_discovered.append(record)

    seed_pages_loaded = sum(url in status_by_url for url in seed_urls)
    queue_truncated = any(url not in visited for url, _depth in queue)
    return status_by_url, verified_discovered, {
        "live_pages_attempted": len(visited),
        "live_pages_loaded": len(status_by_url),
        "seed_pages_expected": len(seed_urls),
        "seed_pages_loaded": seed_pages_loaded,
        "seed_pages_failed": len(seed_urls) - seed_pages_loaded,
        "seed_page_errors": seed_page_errors,
        "degraded_page_errors": degraded_page_errors,
        "crawl_complete": not (
            seed_page_errors
            or degraded_page_errors
            or queue_truncated
            or discovery_truncated
        ),
    }


# --- Public API -------------------------------------------------------------

def fetch_and_normalize_with_evidence(
    school: dict,
    deep: bool = False,
) -> tuple[list[dict], dict]:
    errors = validate(school)
    if errors:
        raise ValueError(f"{school.get('school_slug')} config invalid: " + "; ".join(errors))
    records: list[dict] = []
    evidence = {
        "deep": deep,
        "crawl_sources_expected": len(school.get("sources", [])) if deep else 0,
        "crawl_sources_loaded": 0,
        "live_pages_attempted": 0,
        "live_pages_loaded": 0,
        "seed_pages_expected": 0,
        "seed_pages_loaded": 0,
        "seed_pages_failed": 0,
        "seed_records": 0,
        "discovered_records": 0,
        "complete_recursive_sources": [],
        "crawl_errors": [],
        "degraded_page_errors": [],
    }
    for source in school.get("sources", []):
        status_by_url: dict[str, dict] = {}
        discovered: list[dict] = []
        if deep:
            try:
                status_by_url, discovered, crawl_evidence = _crawl_source(
                    school,
                    source,
                )
                evidence["live_pages_attempted"] += crawl_evidence[
                    "live_pages_attempted"
                ]
                evidence["live_pages_loaded"] += crawl_evidence[
                    "live_pages_loaded"
                ]
                evidence["seed_pages_expected"] += crawl_evidence[
                    "seed_pages_expected"
                ]
                evidence["seed_pages_loaded"] += crawl_evidence[
                    "seed_pages_loaded"
                ]
                evidence["seed_pages_failed"] += crawl_evidence[
                    "seed_pages_failed"
                ]
                evidence["crawl_errors"].extend(
                    f"{source['source_name']}: seed fetch failed: {url}"
                    for url in crawl_evidence["seed_page_errors"]
                )
                evidence["degraded_page_errors"].extend(
                    f"{source['source_name']}: discovered-page fetch failed: {url}"
                    for url in crawl_evidence["degraded_page_errors"]
                )
                if crawl_evidence["live_pages_loaded"] > 0:
                    evidence["crawl_sources_loaded"] += 1
                if (
                    source.get("crawl") == RECURSIVE
                    and crawl_evidence["crawl_complete"] is True
                ):
                    evidence["complete_recursive_sources"].append(
                        source["source_name"]
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("crawl failed for %s: %s", source["source_name"], e)
                source_seed_count = len(set(source.get("seeds", [])))
                evidence["seed_pages_expected"] += source_seed_count
                evidence["seed_pages_failed"] += source_seed_count
                evidence["crawl_errors"].append(
                    f"{source['source_name']}: crawl failed: {e}"
                )
        for spec in source.get("programs", []):
            refine = status_by_url.get(spec["url"], {})
            records.append(_normalize_program(
                school, source, spec,
                status=refine.get("status", "unknown"),
                extra_desc=refine.get("excerpt", ""),
                seed_page_verified=spec["url"] in status_by_url,
            ))
            evidence["seed_records"] += 1
        records.extend(discovered)
        evidence["discovered_records"] += len(discovered)
    records, dropped = dedupe_against_existing(records, [])
    if dropped:
        logger.info("%s: dropped %d intra-batch duplicate(s)", school["school_slug"], dropped)
    return records, evidence


def fetch_and_normalize(school: dict, deep: bool = False) -> list[dict]:
    records, _evidence = fetch_and_normalize_with_evidence(school, deep=deep)
    return records


def merge_into_processed(
    new_opps: list[dict],
    *,
    complete_recursive_sources: set[str] | frozenset[str] = frozenset(),
    school_slug: str | None = None,
) -> tuple[int, int]:
    """Upsert records and retire safely absent recursive discoveries.

    Absence is authoritative only for source names whose complete deep crawl
    was explicitly supplied by ``fetch_and_normalize_with_evidence``. The
    default empty set preserves all old records, as do partial/failed crawls.
    """

    if not PROCESSED_FILE.exists():
        return (0, 0)
    if any(
        not isinstance(source, str) or not source.strip()
        for source in complete_recursive_sources
    ):
        raise ValueError("complete recursive source names must be nonempty strings")
    if complete_recursive_sources and not school_slug:
        raise ValueError("school_slug is required for discovery retirement")
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    observed_discovered_ids = {
        opp.get("id")
        for opp in new_opps
        if (
            opp.get("id")
            and opp.get("school") == school_slug
            and isinstance(opp.get("source_type"), str)
            and opp["source_type"].startswith("campus_")
            and isinstance(opp.get("metadata"), dict)
            and opp["metadata"].get("discovered") is True
            and opp["metadata"].get("collector_source")
            in complete_recursive_sources
        )
    }
    new_opps, dropped = dedupe_against_existing(new_opps, existing)
    if dropped:
        logger.info("campus_graph: suppressed %d near-duplicate(s) vs corpus", dropped)
    index = {o.get("id"): o for o in existing if o.get("id")}
    added = updated = 0
    for opp in new_opps:
        if opp["id"] in index:
            existing_opp = index[opp["id"]]
            opp["metadata"]["first_seen_at"] = existing_opp.get(
                "metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            unverified_seed = (
                not opp["metadata"].get("discovered")
                and opp["metadata"].get("seed_page_verified") is not True
            )
            ambiguous_status = opp["metadata"].get("status") == "unknown"
            if unverified_seed or ambiguous_status:
                # Quick/failed fetches, and loaded pages with no explicit
                # status signal, cannot prove a prior closed record reopened.
                existing_metadata = existing_opp.get("metadata", {})
                for key in ("status", "is_active"):
                    if key in existing_metadata:
                        opp["metadata"][key] = existing_metadata[key]
                if unverified_seed:
                    if "last_verified" in existing_metadata:
                        opp["metadata"]["last_verified"] = existing_metadata[
                            "last_verified"
                        ]
                if (
                    existing_metadata.get("status") in {"open", "closed"}
                    or existing_metadata.get("is_active") is False
                ):
                    opp["title"] = existing_opp.get("title", opp["title"])
            existing_opp.update(opp)
            updated += 1
        else:
            existing.append(opp)
            index[opp["id"]] = opp
            added += 1
    retired = 0
    if complete_recursive_sources:
        deactivated_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
        for opp in existing:
            metadata = opp.get("metadata")
            if (
                opp.get("id") in observed_discovered_ids
                or opp.get("school") != school_slug
                or not isinstance(opp.get("source_type"), str)
                or not opp["source_type"].startswith("campus_")
                or not isinstance(metadata, dict)
                or metadata.get("discovered") is not True
                or metadata.get("discovered_page_verified") is not True
                or metadata.get("collector_source")
                not in complete_recursive_sources
                or metadata.get("is_active") is False
            ):
                continue
            metadata["is_active"] = False
            metadata["status"] = "unknown"
            metadata["deactivated_at"] = deactivated_at
            metadata["deactivation_reason"] = (
                "absent_from_complete_recursive_crawl"
            )
            retired += 1
    if retired:
        logger.info(
            "campus_graph: retired %d absent verified discovery record(s)",
            retired,
        )
    atomic_write_json(PROCESSED_FILE, existing)
    return (added, updated)


def quarantine_unverified_discovered(
    opps: list[dict],
    *,
    collector_sources: set[str] | frozenset[str],
) -> int:
    """Hide legacy crawl discoveries that never proved their detail page.

    Older collector versions emitted a parent-page anchor as active and
    "verified" before loading the linked detail page. Preserve the row for
    audit/history, but do not keep showing it as a live opportunity.
    """

    quarantined = 0
    deactivated_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
    for opp in opps:
        source_type = opp.get("source_type")
        metadata = opp.get("metadata")
        collector_source = (
            metadata.get("collector_source")
            if isinstance(metadata, dict)
            else None
        )
        if (
            not isinstance(source_type, str)
            or not source_type.startswith(("campus_", "ucb_"))
            or not isinstance(metadata, dict)
            or metadata.get("discovered") is not True
            # Recursive campus crawlers stamp their configured source. Other
            # collectors also use ``discovered`` for legitimate sitemap/API
            # records (notably UCSB URCA), so that generic flag is insufficient
            # authority for a corpus-wide migration.
            or not isinstance(collector_source, str)
            or not collector_source.strip()
            or collector_source not in collector_sources
            or metadata.get("urca_record_id") is not None
            or metadata.get("discovered_page_verified") is True
            or metadata.get("is_active") is False
        ):
            continue
        metadata["is_active"] = False
        metadata["deactivated_at"] = deactivated_at
        metadata["deactivation_reason"] = (
            "legacy_discovery_missing_detail_page_evidence"
        )
        metadata["quarantined_unverified_discovery"] = True
        quarantined += 1
    return quarantined


def source_breakdown(opps: list[dict]) -> dict:
    return {
        "total": len(opps),
        "by_source": dict(Counter(o.get("source") for o in opps)),
        "by_source_type": dict(Counter(o.get("campus_source_type") for o in opps)),
        "by_opportunity_type": dict(Counter(o.get("opportunity_type") for o in opps)),
        "discovered": sum(1 for o in opps if o.get("metadata", {}).get("discovered")),
    }
