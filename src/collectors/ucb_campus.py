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

  2. **Crawl layer (deep mode, best-effort).** When ``deep=True`` the collector
     fetches each source's seed pages to (a) refine open/closed status and pull
     a fresh description excerpt onto the matching seed record, and (b) for
     ``recursive`` sources, run a depth-limited, keyword-prioritized BFS to
     *discover* additional opportunity postings and emit them as lower-
     confidence records. Any network failure degrades silently to the seed.

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

OPEN_KEYWORDS = ("applications open", "apply now", "now accepting",
                 "application open", "now recruiting", "now hiring")
CLOSED_KEYWORDS = ("applications closed", "application closed",
                   "no longer accepting", "deadline has passed")

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
_MAX_DISCOVERED_PER_SOURCE = 12
_DESC_CAP = 1500


# ---------------------------------------------------------------------------
# Normalization (stdlib only)
# ---------------------------------------------------------------------------

def _hash_id(source: str, key: str) -> str:
    return "ucb-" + hashlib.md5(f"{source}::{key}".encode()).hexdigest()[:14]


def _normalize_program(source: dict, program: dict, *, status: str = "unknown",
                       extra_desc: str = "") -> dict:
    """Convert one curated program spec into the normalized opportunity schema.

    Pure data transform — no network. Sets ``school``/``audience`` directly from
    the emit bucket so a record is valid even when generated outside refresh_all
    (apply_school_audience re-stamps the identical values, so it stays
    idempotent)."""
    emit = source["emit"]
    src_value, school, audience = EMIT_TO_SCHOOL_AUDIENCE[emit]
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()

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
        # Berkeley is external to this product's UIUC users; the ranker's
        # on-campus work-auth boost must not apply, so on_campus=False (matches
        # the existing ucb_urap / faculty convention).
        "on_campus": False,
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
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Auto-imported from {source['source_name']} ({source['source_type']})",
            "collector_key": program["key"],
            "collector_source": source["source_name"],
            "status": status,
            "deadline_note": program.get("deadline_note", ""),
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
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Crawl-discovered from {source['source_name']}",
            "collector_source": source["source_name"],
            "discovered": True,
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
    low = page_text.lower()
    if any(k in low for k in OPEN_KEYWORDS):
        return "open"
    if any(k in low for k in CLOSED_KEYWORDS):
        return "closed"
    return "unknown"


def _looks_like_opportunity(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in reg.PRIORITY_KEYWORDS)


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


def _crawl_source(source: dict) -> tuple[dict, list[dict]]:
    """Best-effort crawl of one source.

    Returns ``(status_by_url, discovered)`` where ``status_by_url`` maps a seed
    URL to a refinement dict ``{status, excerpt}`` for the matching program, and
    ``discovered`` is a list of normalized lower-confidence records found via
    keyword-prioritized BFS (only for ``recursive`` sources)."""
    status_by_url: dict[str, dict] = {}
    discovered: list[dict] = []
    seeds = source.get("seeds", [])
    depth_limit = source.get("crawl_depth", 1)
    recursive = source.get("crawl") == reg.RECURSIVE

    visited: set[str] = set()
    # Queue of (url, depth). Seeds at depth 0.
    queue: deque[tuple[str, int]] = deque((s, 0) for s in seeds)
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

        # Refinement for a seed page that backs a curated program.
        status = _detect_status(page_text)
        excerpt = page_text[:400]
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
            if (
                len(discovered) < _MAX_DISCOVERED_PER_SOURCE
                and href not in discovered_urls
                and _looks_like_opportunity(anchor)
                and len(anchor) >= 12
            ):
                discovered_urls.add(href)
                discovered.append(
                    _normalize_discovered(source, anchor, href, anchor)
                )

    return status_by_url, discovered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_and_normalize(deep: bool = False) -> list[dict]:
    """Return normalized campus opportunity records.

    ``deep=False`` (default): seed records only, no network.
    ``deep=True``: best-effort crawl refines seed status/description and adds
    discovered records. Always degrades to seeds on any failure."""
    errors = reg.validate_registry()
    if errors:
        # Fail loud: a malformed registry should not silently drop sources.
        raise ValueError("ucb_sources registry invalid: " + "; ".join(errors))

    records: list[dict] = []
    for source in reg.UCB_SOURCES:
        status_by_url: dict[str, dict] = {}
        discovered: list[dict] = []
        if deep:
            try:
                status_by_url, discovered = _crawl_source(source)
            except Exception as e:  # noqa: BLE001
                logger.warning("crawl failed for %s: %s", source["source_name"], e)

        for program in source.get("programs", []):
            refine = status_by_url.get(program["url"], {})
            records.append(_normalize_program(
                source, program,
                status=refine.get("status", "unknown"),
                extra_desc=refine.get("excerpt", ""),
            ))
        records.extend(discovered)

    # Collapse within-batch duplicates (a discovered URL that matches a seed, a
    # lab listed under two sources, ...). Existing list is empty here so this is
    # purely intra-batch.
    records, dropped = dedupe_against_existing(records, [])
    if dropped:
        logger.info("ucb_campus: dropped %d intra-batch duplicate(s)", dropped)
    return records


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Upsert campus records into processed/opportunities.json.

    Upserts by id, and suppresses different-id near-duplicates (same canonical
    URL / normalized title) already in the corpus so re-runs never flood."""
    if not PROCESSED_FILE.exists():
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)

    new_opps, dropped = dedupe_against_existing(new_opps, existing)
    if dropped:
        logger.info("ucb_campus: suppressed %d near-duplicate(s) vs corpus", dropped)

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
