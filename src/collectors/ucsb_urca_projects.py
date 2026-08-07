"""Collector for the UC Santa Barbara URCA Undergraduate Research Directory.

UCSB's analog to Berkeley's URAP project database (``ucb_urap_projects``): the
URCA "Undergraduate Research Assistant Directory" is a board of individual
faculty-posted research projects open to undergraduates — the volume layer that
sits under the handful of curated program hubs in ``schools/ucsb.py``.

Mechanism: the board itself (``ucsb.my.site.com/urca/s/urad``) is a Salesforce
Experience Cloud (Aura/Lightning) SPA whose per-record detail pages render
client-side and don't yield their fields to a headless fetch reliably — but the
site publishes a PUBLIC sitemap that enumerates every record with its stable
Salesforce id + human-readable slug, no auth. So this collector reads the
sitemap (not the JS board), derives each project's title from its slug, and
links to the project's own page. Faculty/description live on the (JS) detail
page and are not scraped; the record's value is the project topic + a direct
apply link into the URCA portal.

The Salesforce object is Outbound-Funds ``Funding_Program__c``; the sitemap
mixes ~30 administrative entries (URCA grants, the Faculty Research Assistant
Program, per-course summer scholarships, the directory node itself) in with the
real per-project postings — those are filtered out by ``_ADMIN_SLUG_RE`` so only
individual research projects are emitted.

Seasonal like URAP: faculty post on a rolling basis, so the sitemap grows/shrinks
over time; ``merge_into_processed`` never wipes the corpus on an empty fetch.

The HTTP deps (``requests``) are imported lazily so importing this module (and
the normalization path) needs only the standard library.

Usage:
    python -m src.collectors.ucsb_urca_projects            # preview
    python -m src.collectors.ucsb_urca_projects --save     # merge into processed data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from urllib.parse import unquote
from xml.etree import ElementTree

from .atomic_json import atomic_write_json
from .ucb_common import PROCESSED_FILE

logger = logging.getLogger(__name__)

SOURCE = "ucsb_urca_projects"
SITEMAP_INDEX = "https://ucsb.my.site.com/urca/s/sitemap.xml"
PORTAL = "https://ucsb.my.site.com/urca/s/urad"
_RECORD_URL_RE = re.compile(
    r"(https://ucsb\.my\.site\.com/urca/s/funding-program/"
    r"([A-Za-z0-9]+)/([^?#]+))(?:[?#].*)?"
)
_REQUIRED_FUNDING_SITEMAPS = frozenset(
    {
        (
            "https://ucsb.my.site.com/urca/s/"
            "sitemap-outfunds__funding_program__c-1.xml"
        ),
        (
            "https://ucsb.my.site.com/urca/s/"
            "sitemap-outfunds__funding_program__c-weekly.xml"
        ),
    }
)
_KNOWN_NON_TARGET_SITEMAPS = frozenset(
    {
        "https://ucsb.my.site.com/urca/s/sitemap-view-1.xml",
        "https://ucsb.my.site.com/urca/s/sitemap-listview-1.xml",
    }
)
# A single sitemap snapshot is not enough evidence to explain a sharp seasonal
# contraction.  Keep the threshold deliberately conservative until the refresh
# pipeline has a durable, consecutive-snapshot confirmation ledger.
_SHRINK_GUARD_MIN_BASELINE = 2
_MIN_SNAPSHOT_RETENTION_RATIO = 0.80
# Administrative / non-project entries that share the funding_program object.
_ADMIN_SLUG_RE = re.compile(
    r"course-scholarship|scholarship$|urca-grants|^urca-|faculty-research-assistant"
    r"|summer-sessions|^summer-\d{4}-|-grant$|research-assistant-directory",
    re.I,
)
_ACRONYM_RE = re.compile(r"\b(dna|rna|nmr|ai|ml|nlp|usa|uv|led|mri|ph|3d|2d|hiv|ucsb)\b", re.I)

KEYWORD_BANK = [
    "machine learning", "computer vision", "data science", "artificial intelligence",
    "robotics", "neuroscience", "genomics", "ecology", "evolution", "marine biology",
    "chemistry", "physics", "materials", "climate", "sustainability", "biochemistry",
    "molecular biology", "psychology", "economics", "engineering", "astrophysics",
]


class UnsafeUrcaSnapshotError(RuntimeError):
    """Raised before writing when one snapshot could retire trusted history."""


def _title_from_slug(slug: str) -> str:
    """De-slugify a URCA record slug into a readable project title."""
    title = slug.replace("-", " ").strip().title()
    # Re-uppercase common acronyms the title-case step lowercased.
    return _ACRONYM_RE.sub(lambda m: m.group(0).upper(), title)


def _fetch_text(url: str) -> str:
    try:
        import requests

        from .ucb_common import HEADERS
    except Exception:  # noqa: BLE001
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        return resp.text
    except Exception as e:  # noqa: BLE001
        logger.warning("URCA: fetch failed for %s: %s", url, e)
        return ""


def scrape_projects() -> list[dict]:
    """Enumerate individual URCA research projects from the public sitemap.

    Reads the sitemap index, follows every ``funding_program`` sub-sitemap, drops
    the administrative entries, and returns one raw dict per project (id, url,
    title). Degrades to ``[]`` on any fetch failure.
    """
    records, _evidence = scrape_projects_with_evidence()
    return records


def _parse_sitemap(text: str) -> tuple[str | None, list[str], bool]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None, [], False
    root_name = root.tag.rsplit("}", 1)[-1].casefold()
    expected_entry = {
        "urlset": "url",
        "sitemapindex": "sitemap",
    }.get(root_name)
    if expected_entry is None:
        return root_name, [], False

    locations: list[str] = []
    shape_valid = True
    for entry in list(root):
        if entry.tag.rsplit("}", 1)[-1].casefold() != expected_entry:
            shape_valid = False
            continue
        locs = [
            (child.text or "").strip()
            for child in list(entry)
            if child.tag.rsplit("}", 1)[-1].casefold() == "loc"
        ]
        if len(locs) != 1 or not locs[0]:
            shape_valid = False
            continue
        locations.append(locs[0])
    return root_name, locations, shape_valid


def scrape_projects_with_evidence() -> tuple[list[dict], dict]:
    """Return raw projects plus fail-closed sitemap evidence.

    A network failure, HTML error page, malformed XML, missing child sitemap,
    or unexpected sitemap-index shape is never a complete snapshot. A single
    structurally valid but empty response is also insufficient to confirm a
    legitimate empty season; that requires a future consecutive-snapshot
    evidence mechanism.
    """

    index = _fetch_text(SITEMAP_INDEX)
    index_root, index_locations, index_shape_valid = (
        _parse_sitemap(index) if index else (None, [], False)
    )
    if index_root not in {"urlset", "sitemapindex"} or not index_shape_valid:
        return [], {
            "sitemap_complete": False,
            "sitemap_structure_complete": False,
            "sitemaps_expected": 1,
            "sitemaps_loaded": 0,
            "empty_confirmed": False,
        }
    unexpected_locations: list[str] = []
    missing_locations: list[str] = []
    if index_root == "sitemapindex":
        subs = [
            location
            for location in index_locations
            if location in _REQUIRED_FUNDING_SITEMAPS
        ]
        unexpected_locations.extend(
            location
            for location in index_locations
            if location not in subs
            and location not in _KNOWN_NON_TARGET_SITEMAPS
        )
        missing_locations = sorted(
            _REQUIRED_FUNDING_SITEMAPS - set(subs)
        )
    else:
        subs = []
    if index_root == "sitemapindex" and (
        missing_locations or unexpected_locations
    ):
        return [], {
            "sitemap_complete": False,
            "sitemap_structure_complete": False,
            "sitemaps_expected": len(_REQUIRED_FUNDING_SITEMAPS),
            "sitemaps_loaded": 0,
            "locations_seen": len(index_locations),
            "recognized_locations": 0,
            "unexpected_location_count": len(unexpected_locations),
            "unexpected_location_samples": unexpected_locations[:5],
            "missing_sitemap_count": len(missing_locations),
            "missing_sitemap_samples": missing_locations[:5],
            "empty_confirmed": False,
        }
    pages = subs or [SITEMAP_INDEX]
    raw: list[dict] = []
    seen: set[str] = set()
    loaded = 0
    complete = True
    locations_seen = 0
    recognized_locations = 0
    for sub in pages:
        xml = _fetch_text(sub) if sub != SITEMAP_INDEX else index
        root_name, locations, shape_valid = _parse_sitemap(xml)
        if root_name != "urlset" or not shape_valid:
            complete = False
            continue
        loaded += 1
        locations_seen += len(locations)
        for location in locations:
            match = _RECORD_URL_RE.fullmatch(location)
            if match is None:
                unexpected_locations.append(location)
                continue
            url, sid, encoded_slug = match.groups()
            slug = unquote(encoded_slug)
            recognized_locations += 1
            if sid in seen or _ADMIN_SLUG_RE.search(slug):
                continue
            seen.add(sid)
            raw.append({"id": sid, "url": url, "title": _title_from_slug(slug), "slug": slug})
    complete = (
        complete
        and loaded == len(pages)
        and not unexpected_locations
    )
    snapshot_complete = complete and bool(raw)
    return raw, {
        # Structural completeness is useful diagnostic evidence, but it does
        # not authorize publishing or retiring a zero-record snapshot.
        "sitemap_complete": snapshot_complete,
        "sitemap_structure_complete": complete,
        "sitemaps_expected": len(pages),
        "sitemaps_loaded": loaded,
        "locations_seen": locations_seen,
        "recognized_locations": recognized_locations,
        "unexpected_location_count": len(unexpected_locations),
        "unexpected_location_samples": unexpected_locations[:5],
        "empty_confirmed": False,
    }


def _keywords(text: str) -> list[str]:
    low = text.lower()
    return [k for k in KEYWORD_BANK if k in low][:6]


def normalize_project(raw: dict) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    opp_id = "ucsb-urca-proj-" + hashlib.md5(raw["id"].encode()).hexdigest()[:12]
    description = (
        f"Undergraduate research project posted to the UC Santa Barbara URCA "
        f"Undergraduate Research Directory: \"{raw['title']}\". Open to matriculated "
        f"UCSB undergraduates; the posting faculty mentor, project details, and "
        f"application instructions are on the project's URCA page. Browse and apply "
        f"through the URCA portal."
    )[:1500]
    return {
        "id": opp_id,
        "source": SOURCE,
        "source_type": "campus_program",
        "campus_source_type": "program",
        "source_url": raw["url"],
        "title": raw["title"][:200],
        "organization": "University of California, Santa Barbara",
        "department": "",
        "lab_or_program": "URCA Undergraduate Research Directory",
        # No pi_name: the mentor isn't reliably on the sitemap, and a shared/blank
        # name across 240+ project records would trip the shared-name DQ gate.
        "pi_name": None,
        "contact_email": None,
        "url": raw["url"],
        "location": "Santa Barbara, CA",
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
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": [],
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": False,
            "international_friendly": "unknown",
            "work_auth_notes": "",
            "eligibility_text_raw": "",
        },
        "application": {
            "contact_method": "website",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": raw["url"],
        },
        "description": description,
        "description_raw": description,
        "description_clean": description[:1500],
        "keywords": _keywords(raw["title"]) + ["undergraduate research"],
        "school": "ucsb",
        "audience": "campus",
        "metadata": {
            "confidence_score": 0.5,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": "Auto-imported from the UCSB URCA Undergraduate Research Directory sitemap",
            "urca_record_id": raw["id"],
            "discovered": True,
        },
    }


def fetch_and_normalize() -> list[dict]:
    return [normalize_project(r) for r in scrape_projects()]


def fetch_and_normalize_with_evidence() -> tuple[list[dict], dict]:
    raw, evidence = scrape_projects_with_evidence()
    return [normalize_project(record) for record in raw], evidence


def merge_snapshot_into_processed(
    new_opps: list[dict],
    *,
    snapshot_complete: bool,
) -> tuple[int, int, int]:
    """Upsert a safe URCA snapshot and retire rows absent from it.

    Empty snapshots and sharp one-run contractions fail before any mutation.
    They may become publishable only after a durable consecutive-snapshot
    confirmation mechanism exists.
    """
    if not new_opps:
        if snapshot_complete:
            raise UnsafeUrcaSnapshotError(
                "refusing complete zero-record URCA snapshot without "
                "consecutive-snapshot evidence"
            )
        logger.info("URCA projects: 0 scraped — leaving corpus untouched")
        return (0, 0, 0)
    if not PROCESSED_FILE.exists():
        return (0, 0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    if snapshot_complete:
        existing_active_ids = {
            opp.get("id")
            for opp in existing
            if (
                opp.get("source") == SOURCE
                and opp.get("id")
                and (opp.get("metadata") or {}).get("is_active") is not False
            )
        }
        incoming_active_ids = {
            opp.get("id")
            for opp in new_opps
            if (
                opp.get("source") == SOURCE
                and opp.get("id")
                and (opp.get("metadata") or {}).get("is_active") is not False
            )
        }
        retained_active_ids = existing_active_ids & incoming_active_ids
        if (
            len(existing_active_ids) >= _SHRINK_GUARD_MIN_BASELINE
            and len(retained_active_ids) / len(existing_active_ids)
            < _MIN_SNAPSHOT_RETENTION_RATIO
        ):
            raise UnsafeUrcaSnapshotError(
                "refusing sharp URCA identity churn without "
                "consecutive-snapshot evidence: "
                f"{len(retained_active_ids)}/{len(existing_active_ids)} "
                f"previous active IDs remain, below "
                f"{_MIN_SNAPSHOT_RETENTION_RATIO:.0%}"
            )
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
    deactivated = 0
    if snapshot_complete:
        active_ids = {opp["id"] for opp in new_opps}
        deactivated_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
        for opp in existing:
            if (
                opp.get("source") != SOURCE
                or opp.get("id") in active_ids
                or (opp.get("metadata") or {}).get("is_active") is False
            ):
                continue
            metadata = opp.setdefault("metadata", {})
            metadata["is_active"] = False
            metadata["deactivated_at"] = deactivated_at
            metadata["deactivation_reason"] = (
                "absent_from_complete_urca_sitemap"
            )
            deactivated += 1
    atomic_write_json(PROCESSED_FILE, existing)
    return (added, updated, deactivated)


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Compatibility upsert; without evidence, never retire absent records."""
    added, updated, _deactivated = merge_snapshot_into_processed(
        new_opps,
        snapshot_complete=False,
    )
    return added, updated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="Merge into processed/opportunities.json")
    args = parser.parse_args()
    opps = fetch_and_normalize()
    print(f"Fetched {len(opps)} URCA projects")
    for o in opps[:8]:
        print(" ", o["title"])
    if args.save:
        print("merged:", merge_into_processed(opps))
