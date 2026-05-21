"""Collector for UIUC URSA (Undergraduate Research in Scientific Advancement).

Student-run RSO in Grainger College of Engineering. Pairs freshmen/sophomores
with grad student mentors each semester. Mentor project list only appears on
the site during the application window (first 1–2 weeks of Fall and Spring).
Outside that window we emit a single "URSA — application closed" record so
the program stays discoverable.

Usage:
    python -m src.collectors.uiuc_ursa
    python -m src.collectors.uiuc_ursa --save
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, RawOpportunity

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
BASE_URL = "https://ursa.grainger.illinois.edu/"
HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}

OPEN_KEYWORDS = ("apply now", "applications open", "application open", "register now", "now accepting")
CLOSED_KEYWORDS = ("applications closed", "application closed", "closed for", "no longer accepting")


class UIUCURSACollector(BaseCollector):
    def __init__(self, config: dict | None = None):
        super().__init__(source_name="uiuc_ursa", config=config or {"rate_limit_delay": 3})

    def collect(self) -> list[RawOpportunity]:
        status = "unknown"
        page_excerpt = ""
        try:
            resp = requests.get(BASE_URL, timeout=30, headers=HEADERS)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            text = soup.get_text(" ", strip=True).lower()
            page_excerpt = (soup.get_text(" ", strip=True))[:800]
            if any(k in text for k in OPEN_KEYWORDS):
                status = "open"
            elif any(k in text for k in CLOSED_KEYWORDS):
                status = "closed"
        except Exception as e:
            self.logger.warning(f"URSA scrape failed: {e}")
        return [self._program_record(status, page_excerpt)]

    def _program_record(self, status: str, page_excerpt: str) -> RawOpportunity:
        suffix = {"open": "applications open", "closed": "applications closed", "unknown": ""}[status]
        title = "URSA — Undergraduate Research in Scientific Advancement"
        if suffix:
            title = f"{title} ({suffix})"
        base_desc = (
            "URSA pairs first- and second-year Grainger Engineering students with "
            "grad student mentors for a semester-long research project. Application "
            "windows open the first 1–2 weeks of Fall and Spring semesters. "
            "Open to all engineering majors; no prior research experience required."
        )
        if page_excerpt:
            base_desc = f"{base_desc}\n\nFrom the URSA site: {page_excerpt[:500]}"
        return RawOpportunity(
            source="uiuc_ursa",
            source_url=BASE_URL,
            title=title,
            description_raw=base_desc,
            url=BASE_URL,
            organization="URSA — Grainger College of Engineering",
            extra_fields={
                "program": "URSA",
                "college": "Grainger Engineering",
                "level": "program_overview",
                "status": status,
            },
        )


def _hash_id(title: str, source: str) -> str:
    return hashlib.md5(f"{source}::{title}".encode()).hexdigest()[:16]


def _to_normalized(r: RawOpportunity) -> dict:
    now = datetime.utcnow().isoformat()
    return {
        "id": _hash_id("URSA Program Overview", r.source),
        "source": r.source,
        "source_url": r.source_url,
        "title": r.title,
        "description": r.description_raw,
        "url": r.url,
        "organization": r.organization,
        "opportunity_type": "research",
        "paid": "unknown",
        "deadline": None,
        "is_rolling": True,
        "on_campus": True,
        "eligibility": {
            "majors": ["Engineering"],
            "preferred_year": ["freshman", "sophomore"],
            "skills_required": [],
            "international_friendly": "yes",
            "citizenship_required": False,
        },
        "application": {
            "application_url": r.url,
            "application_effort": "low",
            "requires_resume": "no",
            "requires_cover_letter": "no",
            "requires_recommendation": "no",
        },
        "keywords": ["research", "engineering", "freshman", "sophomore", "mentor"],
        "metadata": {
            "is_active": True,
            "scraped_at": now,
            "first_seen": now,
        },
        **r.extra_fields,
    }


def fetch_and_normalize() -> list[dict]:
    raw = UIUCURSACollector().collect()
    return [_to_normalized(r) for r in raw]


def merge_into_processed(opps: list[dict]) -> tuple[int, int]:
    if not PROCESSED_FILE.exists():
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    by_id = {o.get("id"): o for o in existing if o.get("id")}
    added = updated = 0
    for opp in opps:
        if opp["id"] not in by_id:
            existing.append(opp)
            added += 1
        else:
            old = by_id[opp["id"]]
            if old.get("title") != opp["title"] or old.get("description") != opp["description"]:
                old["title"] = opp["title"]
                old["description"] = opp["description"]
                old["status"] = opp.get("status", "unknown")
                old.setdefault("metadata", {})["last_updated"] = opp["metadata"]["scraped_at"]
                updated += 1
    with PROCESSED_FILE.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
    return (added, updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    opps = fetch_and_normalize()
    print(f"Fetched {len(opps)} URSA record(s)")
    for o in opps:
        print(f"  - {o['title']} (status={o.get('status', '?')})")
    if args.save:
        a, u = merge_into_processed(opps)
        print(f"Saved: +{a} new, ~{u} updated")
