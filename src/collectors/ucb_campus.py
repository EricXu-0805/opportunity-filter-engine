"""Campus-wide UC Berkeley opportunity collector.

Turns the ``ucb_sources`` registry into normalized opportunity records. This is
the collector that broadens Berkeley coverage beyond URAP + faculty directories
into announcements, programs, department pages, career boards, and lab
recruiting — the rest of the campus research graph.

Two layers:

  1. **Seed layer (always on, stdlib only, offline-safe).** Every curated
     program in the registry is emitted unconditionally and normalized. No
     network call is required, so the system has real Berkeley coverage even
     when a page is unreachable — and the data-generation/test paths never
     touch the network.

  2. **Crawl layer (deep mode).** When ``deep=True`` the collector
     fetches each source's seed pages to (a) refine open/closed status and pull
     a fresh description excerpt onto the matching seed record, and (b) for
     ``recursive`` sources, run a depth-limited, keyword-prioritized BFS to
     *discover* additional opportunity postings and emit them as lower-
     confidence records. Every configured seed must load for publication;
     recursively discovered pages may fail with explicit degraded evidence.

The HTTP/HTML deps (``requests``/``bs4``) are imported lazily inside the crawl
functions so importing this module — and running the seed path — needs nothing
beyond the standard library.

Usage:
    python -m src.collectors.ucb_campus                # preview seeds (offline)
    python -m src.collectors.ucb_campus --deep         # + best-effort crawl
    python -m src.collectors.ucb_campus --save         # merge into processed data
    python -m src.collectors.ucb_campus --report       # source-breakdown report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from src.normalizers.ucb_dedup import dedupe_against_existing

from . import ucb_sources as reg
from .application_status import detect_application_status
from .atomic_json import atomic_write_json
from .ucb_common import _readable_excerpt

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

# Browser-like UA — Berkeley department sites reset connections on requests that
# don't look like a real browser (same reason ucb_common sends a full header set).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Emit bucket -> (source value, school, audience). MUST stay in lockstep with
# src/normalizers/school_audience.SOURCE_DEFAULTS or the data-quality gate
# (test_per_source_pairs_match_source_defaults) fails.
EMIT_TO_SCHOOL_AUDIENCE: dict[str, tuple[str, str | None, str]] = {
    reg.EMIT_CAMPUS: ("ucb_research_programs", "ucb", "campus"),
    reg.EMIT_OPEN: ("ucb_external_research", None, "open"),
    reg.EMIT_LAB: ("ucb_labs", "ucb", "unknown"),
}

# Crawl tuning.
_CRAWL_TIMEOUT = 20
_MAX_PAGES_PER_SOURCE = 25      # hard cap so a recursive crawl can't run away
_MAX_DISCOVERED_PER_SOURCE = 20
_DESC_CAP = 1500


# ---------------------------------------------------------------------------
# Normalization (stdlib only)
# ---------------------------------------------------------------------------

def _hash_id(source: str, key: str) -> str:
    return "ucb-" + hashlib.md5(f"{source}::{key}".encode()).hexdigest()[:14]


def _normalize_program(
    source: dict,
    program: dict,
    *,
    status: str = "unknown",
    extra_desc: str = "",
    seed_page_verified: bool = False,
) -> dict:
    """Convert one curated program spec into the normalized opportunity schema.

    Pure data transform — no network. Sets ``school``/``audience`` directly from
    the emit bucket so a record is valid even when generated outside refresh_all
    (apply_school_audience re-stamps the identical values, so it stays
    idempotent)."""
    emit = source["emit"]
    src_value, school, audience = EMIT_TO_SCHOOL_AUDIENCE[emit]
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    last_verified = now if seed_page_verified else None

    description = program["description"]
    if extra_desc:
        description = f"{description}\n\nFrom the program page: {extra_desc}"
    description = description[:_DESC_CAP]

    title = program["title"]
    if status == "open":
        title = f"{title} (applications open)"
    elif status == "closed":
        title = f"{title} (applications closed)"

    intl = program.get("international_friendly", "unknown")
    keywords = list(dict.fromkeys(
        [k for k in program.get("keywords", []) if k]
        + [source["source_type"]]
    ))

    return {
        "id": _hash_id(src_value, program["key"]),
        "source": src_value,
        # `source_type` is the matcher-facing field; keep it descriptive but
        # never "faculty_research" (that triggers faculty-only re-weighting).
        "source_type": f"ucb_{source['source_type']}",
        # `ucb_source_type` is the program/lab/department/career/announcement
        # axis the product separates results on.
        "ucb_source_type": source["source_type"],
        "source_url": program["url"],
        "title": title,
        "organization": program.get("organization", "University of California, Berkeley"),
        "department": program.get("department", ""),
        "lab_or_program": program.get("lab_or_program", ""),
        # Lab/program pages are not individual people — no PI / cold-email
        # target, which also keeps them out of the ucb_* shared-email DQ gate.
        "pi_name": None,
        "contact_email": None,
        "url": program["url"],
        "location": "Berkeley, CA",
        # Derived, not hardcoded: EMIT_OPEN rows are genuinely external listings
        # that merely surfaced on a Berkeley page (school=None), while campus
        # and lab rows are Berkeley's own. The old blanket False encoded
        # "external to this product's UIUC users", which stopped being a fact
        # about the record once the product served 117 schools; whose campus it
        # is, is the ranker's question (school vs profile.home_school).
        "on_campus": school is not None,
        "remote_option": "unknown",
        "opportunity_type": program.get("opportunity_type", "research"),
        "paid": program.get("paid", "unknown"),
        "compensation_details": program.get("compensation", ""),
        # Rolling: these are program/hub pages, not single dated postings. No
        # structured deadline (the cycle note lives in the description) so
        # deactivate_past never wrongly retires them.
        "deadline": None,
        "is_rolling": True,
        "posted_date": None,
        "start_date": None,
        "duration": None,
        "eligibility": {
            "preferred_year": program.get("preferred_year", ["sophomore", "junior", "senior"]),
            "min_gpa": None,
            "majors": program.get("eligibility_majors", []),
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": intl == "no",
            "international_friendly": intl,
            "work_auth_notes": "",
            "eligibility_text_raw": (program.get("deadline_note", "") or "")[:300],
        },
        "application": {
            "contact_method": "website",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": program["url"],
        },
        "description": description,
        "description_raw": description,
        "description_clean": description[:_DESC_CAP],
        "keywords": keywords,
        "school": school,
        "audience": audience,
        "metadata": {
            "confidence_score": 0.7,
            "last_verified": last_verified,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": status != "closed",
            "manually_reviewed": False,
            "notes": f"Auto-imported from {source['source_name']} ({source['source_type']})",
            "collector_key": program["key"],
            "collector_source": source["source_name"],
            "status": status,
            "deadline_note": program.get("deadline_note", ""),
            # Distinguish a loaded page with no status marker from a seed that
            # was never fetched. Merge must not let the latter reactivate a
            # record closed by an earlier live crawl.
            "seed_page_verified": seed_page_verified,
        },
    }


def _normalize_discovered(source: dict, title: str, url: str, snippet: str) -> dict:
    """Normalize a crawl-discovered posting into a lower-confidence record."""
    emit = source["emit"]
    src_value, school, audience = EMIT_TO_SCHOOL_AUDIENCE[emit]
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    desc = (snippet or title)[:_DESC_CAP]
    # A stable id from the canonical-ish URL so re-crawls upsert instead of
    # duplicating.
    key = "disc-" + hashlib.md5(url.encode()).hexdigest()[:10]
    return {
        "id": _hash_id(src_value, key),
        "source": src_value,
        "source_type": f"ucb_{source['source_type']}",
        "ucb_source_type": source["source_type"],
        "source_url": url,
        "title": title[:200],
        "organization": "University of California, Berkeley",
        "department": source.get("programs", [{}])[0].get("department", "") if source.get("programs") else "",
        "lab_or_program": "",
        "pi_name": None,
        "contact_email": None,
        "url": url,
        "location": "Berkeley, CA",
        "on_campus": school is not None,
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
            "min_gpa": None,
            "majors": [],
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": False,
            "international_friendly": "unknown",
            "work_auth_notes": "",
            "eligibility_text_raw": desc[:300],
        },
        "application": {
            "contact_method": "website",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": url,
        },
        "description": desc,
        "description_raw": desc,
        "description_clean": desc[:_DESC_CAP],
        "keywords": [source["source_type"], "undergraduate research"],
        "school": school,
        "audience": audience,
        "metadata": {
            "confidence_score": 0.4,
            "last_verified": None,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": False,
            "manually_reviewed": False,
            "notes": f"Crawl-discovered from {source['source_name']}",
            "collector_source": source["source_name"],
            "discovered": True,
            "discovered_page_verified": False,
            "status": "unknown",
        },
    }


# ---------------------------------------------------------------------------
# Crawl layer (lazy HTTP deps)
# ---------------------------------------------------------------------------

def _fetch(url: str):
    """Fetch a page and return BeautifulSoup, or None on any failure.

    Lazy-imports requests/bs4 so the seed path never needs them."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception as e:  # noqa: BLE001
        logger.warning("Crawl deps unavailable (%s); seed-only mode", e)
        return None
    try:
        resp = requests.get(url, timeout=_CRAWL_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser")
    except Exception as e:  # noqa: BLE001 — never crash the run on one page
        logger.warning("fetch failed for %s: %s", url, e)
        return None


def _detect_status(page_text: str) -> str:
    return detect_application_status(page_text)


def _looks_like_opportunity(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in reg.PRIORITY_KEYWORDS)


# Generic section/CTA anchors that carry a priority keyword but aren't a
# concrete posting ("Undergraduate Research" nav item, "Apply", "Learn more").
# Emitting them as discovered records adds noise (and DQ-gate surface area), so
# a discovered anchor must say something beyond one of these bare phrases.
_GENERIC_ANCHOR = frozenset({
    "undergraduate research", "research", "research opportunities",
    "research opportunity", "summer research", "opportunities", "opportunity",
    "apply", "apply now", "apply here", "learn more", "read more", "more",
    "join our lab", "join the lab", "internships", "internship",
    "research assistant", "fellowships", "fellowship", "get involved",
    "for students", "prospective students", "current students",
})


# Discovered anchors that carry a priority keyword and clear the length bar but
# still aren't a student opportunity: news/announcement headlines, an email
# address mistaken for a title, pure application-instruction or graduate-program
# nav, and employer-facing CTAs. These leaked into ucb_research_programs from
# deep crawls of scholarship/news/career hubs; reject them at the source.
_NOISE_DISCOVERED_RE = re.compile(
    r"@"                                              # email-as-title
    r"|\breceives?\b|\bwrap-?up\b|\bnamed\b|\bawarded\b"   # news/announcement headlines
    r"|['’]\d{2}\)"                                    # ('25) — student-profile news
    r"|^how to apply\b|^apply or transfer\b"          # bare application instructions
    r"|^read (more|through)\b"                         # "Read more about …" nav fragments
    r"|\bmeng\b"                                       # graduate (M.Eng.) program nav
    r"|recruiting our students",                       # employer-facing CTA
    re.IGNORECASE,
)


def _is_noise_discovered(anchor: str) -> bool:
    """True for crawl-discovered anchors that read like a posting but are
    actually news headlines, emails, application-instruction/grad nav, or
    employer-facing CTAs — never a student research opportunity."""
    return bool(_NOISE_DISCOVERED_RE.search(anchor.strip()))


def _is_specific_opportunity(anchor: str) -> bool:
    """A discovered anchor must read like a concrete posting — not a bare
    section/CTA link, and not a news/email/grad-nav false positive. Requires a
    priority keyword, reasonable length, that it isn't just one of the generic
    phrases above, and that it doesn't match the noise patterns."""
    a = anchor.strip().lower().rstrip(" »›>").strip()
    if a in _GENERIC_ANCHOR or len(anchor.strip()) < 12:
        return False
    if _is_noise_discovered(anchor):
        return False
    return _looks_like_opportunity(anchor)


def _same_site(seed: str, candidate: str) -> bool:
    """Keep the crawl on the seed's host (and its subdomains under berkeley.edu)
    so a BFS can't wander off-campus."""
    try:
        sh = (urlsplit(seed).hostname or "").lower()
        ch = (urlsplit(candidate).hostname or "").lower()
    except ValueError:
        return False
    if not ch:
        return False
    return ch == sh or (ch.endswith("berkeley.edu") and sh.endswith("berkeley.edu"))


_NAV_TITLE_RE = re.compile(r"^(home|menu|skip to|search|login|apply now|contact|about)$", re.IGNORECASE)


def _crawl_source(source: dict) -> tuple[dict, list[dict], dict]:
    """Best-effort crawl of one source.

    Returns ``(status_by_url, discovered)`` where ``status_by_url`` maps a seed
    URL to a refinement dict ``{status, excerpt}`` for the matching program, and
    ``discovered`` is a list of normalized lower-confidence records found via
    keyword-prioritized BFS (only for ``recursive`` sources)."""
    status_by_url: dict[str, dict] = {}
    discovered: list[dict] = []
    seeds = list(dict.fromkeys(source.get("seeds", [])))
    seed_urls = set(seeds)
    depth_limit = source.get("crawl_depth", 1)
    recursive = source.get("crawl") == reg.RECURSIVE

    visited: set[str] = set()
    # Queue of (url, depth). Seeds at depth 0.
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
            logger.warning("parse failed for %s: %s", url, e)
            if url in seed_urls:
                seed_page_errors.append(url)
            else:
                degraded_page_errors.append(url)
            continue

        # Refinement for a seed page that backs a curated program. Status reads
        # the whole page (a "closed" banner can live in the header), but the
        # excerpt uses the chrome-excluded main-content text so nav/menu
        # furniture never lands in the shown description.
        status = _detect_status(page_text)
        excerpt = _readable_excerpt(soup)
        status_by_url[url] = {"status": status, "excerpt": excerpt}

        if not recursive or depth >= depth_limit:
            continue

        # Keyword-prioritized link expansion: collect (priority, anchor) and
        # follow the highest-signal links first.
        scored_links: list[tuple[int, str, str]] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"].split("#")[0])
            if not href.startswith("http") or not _same_site(url, href):
                continue
            anchor = a.get_text(" ", strip=True)
            if not anchor or _NAV_TITLE_RE.match(anchor):
                continue
            score = sum(1 for kw in reg.PRIORITY_KEYWORDS if kw in (anchor.lower() + " " + href.lower()))
            if score:
                scored_links.append((score, href, anchor))

        scored_links.sort(key=lambda t: t[0], reverse=True)
        for score, href, anchor in scored_links:
            if href in visited:
                continue
            # Enqueue for deeper crawl.
            queue.append((href, depth + 1))
            # Emit a discovered record when the anchor itself reads like a
            # concrete posting (not just a section link).
            if href in discovered_urls or not _is_specific_opportunity(anchor):
                continue
            if len(discovered) < _MAX_DISCOVERED_PER_SOURCE:
                discovered_urls.add(href)
                discovered.append(
                    _normalize_discovered(source, anchor, href, anchor)
                )
            else:
                discovery_truncated = True

    # Seeing an anchor on a parent page is not enough to publish or reactivate
    # a dynamic posting. Its own detail page must load, and only an explicit
    # open signal makes the record active.
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_and_normalize_with_evidence(
    deep: bool = False,
) -> tuple[list[dict], dict]:
    """Return normalized campus opportunity records.

    ``deep=False`` (default): seed records only, no network.
    ``deep=True``: crawl refines seed status/description and adds discovered
    records. Evidence distinguishes mandatory configured-seed failures from
    optional recursive-page degradation."""
    errors = reg.validate_registry()
    if errors:
        # Fail loud: a malformed registry should not silently drop sources.
        raise ValueError("ucb_sources registry invalid: " + "; ".join(errors))

    records: list[dict] = []
    evidence = {
        "deep": deep,
        "crawl_sources_expected": len(reg.UCB_SOURCES) if deep else 0,
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
    for source in reg.UCB_SOURCES:
        status_by_url: dict[str, dict] = {}
        discovered: list[dict] = []
        if deep:
            try:
                status_by_url, discovered, crawl_evidence = _crawl_source(
                    source
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
                    source.get("crawl") == reg.RECURSIVE
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

        for program in source.get("programs", []):
            refine = status_by_url.get(program["url"], {})
            records.append(_normalize_program(
                source, program,
                status=refine.get("status", "unknown"),
                extra_desc=refine.get("excerpt", ""),
                seed_page_verified=program["url"] in status_by_url,
            ))
            evidence["seed_records"] += 1
        records.extend(discovered)
        evidence["discovered_records"] += len(discovered)

    # Collapse within-batch duplicates (a discovered URL that matches a seed, a
    # lab listed under two sources, ...). Existing list is empty here so this is
    # purely intra-batch.
    records, dropped = dedupe_against_existing(records, [])
    if dropped:
        logger.info("ucb_campus: dropped %d intra-batch duplicate(s)", dropped)
    return records, evidence


def fetch_and_normalize(deep: bool = False) -> list[dict]:
    records, _evidence = fetch_and_normalize_with_evidence(deep=deep)
    return records


def merge_into_processed(
    new_opps: list[dict],
    *,
    complete_recursive_sources: set[str] | frozenset[str] = frozenset(),
) -> tuple[int, int]:
    """Upsert campus records into processed/opportunities.json.

    Upserts by id, and suppresses different-id near-duplicates (same canonical
    URL / normalized title) already in the corpus so re-runs never flood.
    Old verified discoveries are retired only for explicitly authorized,
    completely crawled recursive sources; the default empty set holds them."""
    if not PROCESSED_FILE.exists():
        return (0, 0)
    if any(
        not isinstance(source, str) or not source.strip()
        for source in complete_recursive_sources
    ):
        raise ValueError("complete recursive source names must be nonempty strings")
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    observed_discovered_ids = {
        opp.get("id")
        for opp in new_opps
        if (
            opp.get("id")
            and opp.get("school") == "ucb"
            and isinstance(opp.get("source_type"), str)
            and opp["source_type"].startswith("ucb_")
            and isinstance(opp.get("metadata"), dict)
            and opp["metadata"].get("discovered") is True
            and opp["metadata"].get("collector_source")
            in complete_recursive_sources
        )
    }

    new_opps, dropped = dedupe_against_existing(new_opps, existing)
    if dropped:
        logger.info("ucb_campus: suppressed %d near-duplicate(s) vs corpus", dropped)

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
                # A loaded page with no explicit status signal is not evidence
                # that a previously closed opportunity reopened.
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
                or opp.get("school") != "ucb"
                or not isinstance(opp.get("source_type"), str)
                or not opp["source_type"].startswith("ucb_")
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
            "ucb_campus: retired %d absent verified discovery record(s)",
            retired,
        )
    atomic_write_json(PROCESSED_FILE, existing)
    return (added, updated)


def source_breakdown(opps: list[dict]) -> dict:
    """Summarize what each source/level contributed — the 'source breakdown'
    output the product surfaces alongside the ranked feed."""
    by_bucket = Counter(o.get("source") for o in opps)
    by_level = Counter(o.get("ucb_source_type") for o in opps)
    by_collector = Counter(o.get("metadata", {}).get("collector_source") for o in opps)
    by_type = Counter(o.get("opportunity_type") for o in opps)
    return {
        "total": len(opps),
        "by_emit_bucket": dict(by_bucket),
        "by_source_type": dict(by_level),
        "by_collector": dict(by_collector),
        "by_opportunity_type": dict(by_type),
        "seed_count": reg.total_seed_count(),
        "discovered": sum(1 for o in opps if o.get("metadata", {}).get("discovered")),
    }


def _print_report(opps: list[dict]) -> None:
    bd = source_breakdown(opps)
    print("\n" + "=" * 60)
    print("UC BERKELEY CAMPUS SOURCE BREAKDOWN")
    print("=" * 60)
    print(f"Total records: {bd['total']}  (seeds: {bd['seed_count']}, discovered: {bd['discovered']})")
    print("\nBy emit bucket (→ school/audience):")
    for k, v in sorted(bd["by_emit_bucket"].items(), key=lambda x: -x[1]):
        print(f"  {v:3d}  {k}")
    print("\nBy source type (program/lab/department/career/announcement):")
    for k, v in sorted(bd["by_source_type"].items(), key=lambda x: -x[1]):
        print(f"  {v:3d}  {k}")
    print("\nBy opportunity type:")
    for k, v in sorted(bd["by_opportunity_type"].items(), key=lambda x: -x[1]):
        print(f"  {v:3d}  {k}")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true", help="Best-effort live crawl (else seed-only)")
    parser.add_argument("--save", action="store_true", help="Merge into processed/opportunities.json")
    parser.add_argument("--report", action="store_true", help="Print the source breakdown")
    args = parser.parse_args()

    opps = fetch_and_normalize(deep=args.deep)
    print(f"Fetched {len(opps)} UC Berkeley campus opportunity records "
          f"({'deep crawl' if args.deep else 'seed-only'})")
    for o in opps[:12]:
        print(f"  [{o['ucb_source_type']:<12}] {o['title'][:72]}")

    if args.report:
        _print_report(opps)

    if args.save:
        if not opps:
            print("\nSkipping save: fetched 0 records.")
        else:
            a, u = merge_into_processed(opps)
            print(f"\nSaved: +{a} new, ~{u} updated")
    elif not args.report:
        print("\n(Use --save to merge, --deep to crawl, --report for the breakdown)")
