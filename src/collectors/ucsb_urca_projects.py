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

from .ucb_common import PROCESSED_FILE

logger = logging.getLogger(__name__)

SOURCE = "ucsb_urca_projects"
SITEMAP_INDEX = "https://ucsb.my.site.com/urca/s/sitemap.xml"
PORTAL = "https://ucsb.my.site.com/urca/s/urad"
_LOC_RE = re.compile(
    r"<loc>(https://ucsb\.my\.site\.com/urca/s/funding-program/([A-Za-z0-9]+)/([^<]+))</loc>"
)
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
    index = _fetch_text(SITEMAP_INDEX)
    if not index:
        return []
    subs = re.findall(r"<loc>([^<]*funding_program__c[^<]*)</loc>", index, re.I)
    if not subs:  # some deployments inline the records in the index itself
        subs = []
    raw: list[dict] = []
    seen: set[str] = set()
    for sub in subs or [SITEMAP_INDEX]:
        xml = _fetch_text(sub) if sub != SITEMAP_INDEX else index
        for url, sid, slug in _LOC_RE.findall(xml):
            if sid in seen or _ADMIN_SLUG_RE.search(slug):
                continue
            seen.add(sid)
            raw.append({"id": sid, "url": url, "title": _title_from_slug(slug), "slug": slug})
    return raw


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


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Upsert by id. Never overwrites the corpus with an empty scrape."""
    if not PROCESSED_FILE.exists():
        return (0, 0)
    if not new_opps:
        logger.info("URCA projects: 0 scraped — leaving corpus untouched")
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
    args = parser.parse_args()
    opps = fetch_and_normalize()
    print(f"Fetched {len(opps)} URCA projects")
    for o in opps[:8]:
        print(" ", o["title"])
    if args.save:
        print("merged:", merge_into_processed(opps))
