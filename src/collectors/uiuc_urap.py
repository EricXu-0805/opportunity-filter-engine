"""Collector for UIUC URAP (Undergraduate Research Apprenticeship Program).

URAP publishes an annual mentor project list each fall. Outside that window the
program page only describes the program in general terms. We emit one
"URAP overview" seed entry unconditionally so the program shows up in the
system year-round, and attempt to scrape the current mentor list when it's
linked. Failures fall back silently to just the overview record.

Usage:
    python -m src.collectors.uiuc_urap              # preview
    python -m src.collectors.uiuc_urap --save       # merge into processed data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, RawOpportunity

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
BASE_URL = "https://undergradresearch.illinois.edu/programs/urap/"
HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}


class UIUCURAPCollector(BaseCollector):
    def __init__(self, config: dict | None = None):
        super().__init__(source_name="uiuc_urap", config=config or {"rate_limit_delay": 3})

    def collect(self) -> list[RawOpportunity]:
        opps: list[RawOpportunity] = [self._overview_record()]
        try:
            resp = requests.get(BASE_URL, timeout=30, headers=HEADERS)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            mentor_link = self._find_mentor_list_link(soup)
            if mentor_link:
                self.logger.info(f"Found mentor list at {mentor_link}")
                self._rate_limit()
                mentor_opps = self._scrape_mentor_page(mentor_link)
                opps.extend(mentor_opps)
                self.logger.info(f"Scraped {len(mentor_opps)} URAP mentor projects")
            else:
                self.logger.info("No URAP mentor list link found (likely out of season)")
        except Exception as e:
            self.logger.warning(f"URAP scrape failed (using overview only): {e}")
        return opps

    def _overview_record(self) -> RawOpportunity:
        return RawOpportunity(
            source="uiuc_urap",
            source_url=BASE_URL,
            title="URAP — Undergraduate Research Apprenticeship Program",
            description_raw=(
                "URAP pairs first- and second-year undergraduates with no prior "
                "research experience to a faculty-supervised grad student or "
                "postdoc mentor for a semester-long research apprenticeship. "
                "Mentor projects are listed in early fall; applications close in "
                "October; the program runs during the spring semester. Open to "
                "all majors. Counts as research credit (PSYC/STAT/independent "
                "study) or as a paid hourly experience depending on the mentor."
            ),
            url=BASE_URL,
            organization="UIUC Office of Undergraduate Research",
            extra_fields={
                "program": "URAP",
                "level": "program_overview",
                "college": "All",
                "is_rolling": False,
                "_contact_email": "undergradresearch@illinois.edu",
            },
        )

    def _find_mentor_list_link(self, soup: BeautifulSoup) -> str | None:
        for a in soup.find_all("a", href=True):
            text = (a.get_text() or "").lower().strip()
            href = a["href"]
            if any(k in text for k in ("mentor", "project list", "current projects")) and "urap" in (text + href).lower():
                return href if href.startswith("http") else f"https://undergradresearch.illinois.edu{href}"
        return None

    def _scrape_mentor_page(self, url: str) -> list[RawOpportunity]:
        try:
            resp = requests.get(url, timeout=30, headers=HEADERS)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            self.logger.warning(f"Mentor page fetch failed: {e}")
            return []

        opps: list[RawOpportunity] = []
        for heading in soup.find_all(re.compile(r"^h[2-4]$")):
            title = heading.get_text(strip=True)
            if not title or len(title) < 8 or len(title) > 200:
                continue
            paragraphs: list[str] = []
            sibling = heading.find_next_sibling()
            while sibling and sibling.name not in {"h2", "h3", "h4"}:
                if sibling.name in {"p", "div", "ul"}:
                    text = sibling.get_text(" ", strip=True)
                    if text:
                        paragraphs.append(text)
                sibling = sibling.find_next_sibling()
            description = " ".join(paragraphs)[:1200]
            if len(description) < 30:
                continue
            opps.append(RawOpportunity(
                source="uiuc_urap",
                source_url=url,
                title=f"URAP Mentor Project: {title}"[:240],
                description_raw=description,
                url=url,
                organization="UIUC URAP Mentor",
                extra_fields={"program": "URAP", "level": "mentor_project"},
            ))
        return opps


def _hash_id(title: str, source: str) -> str:
    return hashlib.md5(f"{source}::{title}".encode()).hexdigest()[:16]


def _to_normalized(r: RawOpportunity) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    is_overview = r.extra_fields.get("level") == "program_overview"
    contact_email = r.extra_fields.pop("_contact_email", None)
    return {
        "id": _hash_id(r.title, r.source),
        "source": r.source,
        "source_url": r.source_url,
        "title": r.title,
        # R70-A: emit description_clean + description_raw so the frontend (which
        # reads `description_clean || description_raw`) renders content for
        # these program_overview records. Keep legacy `description` for back-compat.
        "description": r.description_raw,
        "description_raw": r.description_raw,
        "description_clean": (r.description_raw or "")[:1500],
        "url": r.url,
        "organization": r.organization,
        "opportunity_type": "research",
        "paid": "unknown",
        "deadline": None,
        "is_rolling": True if is_overview else False,
        "on_campus": True,
        "contact_email": contact_email,
        "eligibility": {
            "majors": [],
            "preferred_year": ["freshman", "sophomore"],
            "skills_required": [],
            "international_friendly": "unknown",
            "citizenship_required": False,
        },
        "application": {
            "application_url": r.url,
            "application_effort": "medium",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_recommendation": "unknown",
        },
        "keywords": ["research", "mentorship", "undergraduate"],
        "metadata": {
            "is_active": True,
            "last_verified": now,
            "first_seen_at": now,
        },
        **{k: v for k, v in r.extra_fields.items() if k not in {"is_rolling"}},
    }


def fetch_and_normalize() -> list[dict]:
    raw = UIUCURAPCollector().collect()
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
            by_id[opp["id"]] = opp
            added += 1
        else:
            old = by_id[opp["id"]]
            if old.get("description") != opp["description"] or old.get("title") != opp["title"]:
                old["title"] = opp["title"]
                old["description"] = opp["description"]
                old.setdefault("metadata", {})["last_updated"] = opp["metadata"]["last_verified"]
                updated += 1
    with PROCESSED_FILE.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
    return (added, updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="Merge into processed data")
    args = parser.parse_args()
    opps = fetch_and_normalize()
    print(f"Fetched {len(opps)} URAP records")
    for o in opps[:5]:
        print(f"  - {o['title'][:80]}")
    if args.save:
        a, u = merge_into_processed(opps)
        print(f"Saved: +{a} new, ~{u} updated")
