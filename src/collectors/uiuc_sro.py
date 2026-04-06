"""
Collector for UIUC Summer Research Opportunities Database.
URL: https://researchops.web.illinois.edu/
Drupal CMS with paginated table view.

Usage:
    python -m src.collectors.uiuc_sro              # fetch & preview
    python -m src.collectors.uiuc_sro --save       # fetch & merge into processed data
"""

import re
import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, RawOpportunity

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Research area IDs from the Drupal filter
RESEARCH_AREAS = {
    "12": "Agriculture & Food Sciences",
    "14": "Business & Economics",
    "13": "Data Science",
    "11": "Education",
    "2": "Humanities & Arts",
    "1": "Medicine & Health",
    "4": "Natural Sciences",
    "5": "Science & Technology",
    "3": "Social Sciences & Behavior",
}


class UIUCSROCollector(BaseCollector):
    """Scrapes UIUC Summer Research Opportunities Database."""

    BASE_URL = "https://researchops.web.illinois.edu/"
    MAX_PAGES = 15  # Safety cap; stops when no more rows

    def __init__(self, config: dict = None):
        super().__init__(
            source_name="uiuc_sro",
            config=config or {"rate_limit_delay": 3},
        )

    def collect(self) -> list[RawOpportunity]:
        """Scrape all paginated pages."""
        opportunities = []

        for page in range(self.MAX_PAGES):
            url = f"{self.BASE_URL}?page={page}"
            self.logger.info(f"Scraping page {page + 1}: {url}")

            try:
                resp = requests.get(url, timeout=30, headers={
                    "User-Agent": "OpportunityFilterEngine/1.0 (educational project)"
                })
                resp.raise_for_status()

                page_opps = self._parse_page(resp.text, url)
                if not page_opps:
                    self.logger.info(f"No more results on page {page + 1}, stopping.")
                    break

                opportunities.extend(page_opps)
                self._rate_limit()

            except Exception as e:
                self.logger.error(f"Failed to scrape page {page}: {e}")

        return opportunities

    def _parse_page(self, html: str, page_url: str) -> list[RawOpportunity]:
        """Parse a single page of the table-based listing."""
        soup = BeautifulSoup(html, "html.parser")
        opportunities = []

        table = soup.select_one("table.views-table")
        if not table:
            return []

        rows = table.select("tbody tr")
        for row in rows:
            opp = self._parse_row(row, page_url)
            if opp:
                opportunities.append(opp)

        return opportunities

    def _parse_row(self, row, page_url: str) -> Optional[RawOpportunity]:
        """Parse a single table row into RawOpportunity."""
        try:
            # Title and link
            title_td = row.select_one("td.views-field-title")
            if not title_td:
                return None

            link_el = title_td.select_one("a")
            if not link_el:
                return None

            title = link_el.get_text(strip=True)
            href = link_el.get("href", "")
            if href and not href.startswith("http"):
                href = f"https://researchops.web.illinois.edu{href}"

            # Description (text after the <br> in the same td)
            desc_parts = []
            for child in title_td.children:
                if isinstance(child, str):
                    text = child.strip()
                    if text and text != title:
                        desc_parts.append(text)
            # Also try getting all text minus title
            full_text = title_td.get_text(separator=" ", strip=True)
            description = full_text.replace(title, "", 1).strip()

            # Research area
            area_td = row.select_one("td.views-field-field-research-area")
            research_area = area_td.get_text(strip=True) if area_td else ""

            # Timing
            timing_td = row.select_one("td.views-field-field-timing")
            timing = timing_td.get_text(strip=True) if timing_td else ""

            # Deadline
            deadline_td = row.select_one("td.views-field-nothing, td.views-field-field-deadline-anticipated")
            deadline_text = deadline_td.get_text(strip=True) if deadline_td else ""

            return RawOpportunity(
                source="uiuc_sro",
                source_url=page_url,
                title=title,
                description_raw=description,
                url=href,
                organization=None,
                deadline=deadline_text if deadline_text else None,
                location=None,
                extra_fields={
                    "research_area": research_area,
                    "timing": timing,
                    "deadline_raw": deadline_text,
                },
            )

        except Exception as e:
            self.logger.error(f"Failed to parse row: {e}")
            return None


def _detect_international_friendly(text: str) -> str:
    """Heuristic for international student eligibility."""
    lower = text.lower()
    if any(kw in lower for kw in ["u.s. citizen", "us citizen", "citizenship required",
                                    "permanent resident only", "us only",
                                    "must be a u.s.", "u.s. citizenship"]):
        return "no"
    if any(kw in lower for kw in ["international students welcome", "open to all",
                                    "international students eligible", "all students",
                                    "no citizenship requirement"]):
        return "yes"
    return "unknown"


def _parse_deadline(text: str) -> Optional[str]:
    """Try to parse deadline text into ISO-ish date."""
    if not text:
        return None
    # Remove "Anticipated" prefix
    clean = re.sub(r"(?i)anticipated\s*", "", text).strip()
    if not clean:
        return None
    return clean


def _research_area_to_majors(area: str) -> list[str]:
    """Map SRO research areas to approximate majors."""
    area_lower = area.lower()
    majors = []
    if "science & technology" in area_lower or "natural sciences" in area_lower:
        majors.extend(["CS", "ECE", "Physics", "Chemistry", "Engineering"])
    if "data science" in area_lower:
        majors.extend(["CS", "STAT", "Data Science", "IS"])
    if "medicine" in area_lower or "health" in area_lower:
        majors.extend(["Biology", "Bioengineering", "Chemistry"])
    if "business" in area_lower or "economics" in area_lower:
        majors.extend(["Business", "Economics", "STAT"])
    if "social sciences" in area_lower:
        majors.extend(["Psychology", "Sociology", "Political Science"])
    if "agriculture" in area_lower:
        majors.extend(["Agriculture", "Biology", "Chemistry"])
    if "humanities" in area_lower or "arts" in area_lower:
        majors.extend(["English", "History", "Art"])
    if "education" in area_lower:
        majors.extend(["Education"])
    return list(set(majors))


def raw_to_normalized(raw: RawOpportunity) -> dict:
    """Convert a RawOpportunity from SRO into the normalized schema."""
    desc = raw.description_raw or ""
    intl = _detect_international_friendly(desc)
    deadline = _parse_deadline(raw.extra_fields.get("deadline_raw", ""))
    research_area = raw.extra_fields.get("research_area", "")
    timing = raw.extra_fields.get("timing", "")
    majors = _research_area_to_majors(research_area)

    url_hash = hashlib.md5(raw.url.encode()).hexdigest()[:8]
    opp_id = f"sro-{url_hash}"
    now = datetime.utcnow().isoformat()

    return {
        "id": opp_id,
        "source": "uiuc_sro",
        "source_url": raw.source_url,
        "source_type": "summer_program",
        "title": raw.title.strip(),
        "organization": raw.organization or "",
        "department": "",
        "lab_or_program": raw.title.strip(),
        "pi_name": None,
        "url": raw.url,
        "location": "",
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": "summer_program",
        "paid": "unknown",
        "compensation_details": "",
        "deadline": deadline,
        "posted_date": None,
        "start_date": None,
        "duration": timing or "Summer",
        "eligibility": {
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": majors,
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": intl == "no",
            "international_friendly": intl,
            "work_auth_notes": "",
            "eligibility_text_raw": desc[:300],
        },
        "application": {
            "contact_method": "online",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": raw.url,
        },
        "description_raw": desc,
        "description_clean": desc[:500],
        "keywords": [a.strip() for a in research_area.split(",") if a.strip()],
        "metadata": {
            "confidence_score": 0.7,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": "Auto-imported from UIUC SRO database",
        },
    }


def fetch_and_normalize() -> list[dict]:
    """Fetch SRO database and return normalized records."""
    collector = UIUCSROCollector()
    raw_opps = collector.collect()
    logger.info(f"Fetched {len(raw_opps)} entries from SRO")

    normalized = []
    for raw in raw_opps:
        try:
            norm = raw_to_normalized(raw)
            normalized.append(norm)
        except Exception as e:
            logger.error(f"Failed to normalize '{raw.title}': {e}")

    return normalized


def merge_into_processed(new_opps: list[dict], filepath: str = None) -> tuple[int, int]:
    """Merge new opportunities into the processed data file."""
    filepath = filepath or str(PROCESSED_DIR / "opportunities.json")

    existing = []
    if Path(filepath).exists():
        with open(filepath, "r", encoding="utf-8") as f:
            existing = json.load(f)

    index = {opp["id"]: opp for opp in existing}
    added, updated = 0, 0

    for opp in new_opps:
        if opp["id"] in index:
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get("metadata", {}).get(
                "first_seen_at", opp["metadata"]["first_seen_at"]
            )
            index[opp["id"]] = opp
            updated += 1
        else:
            index[opp["id"]] = opp
            added += 1

    all_opps = list(index.values())
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_opps, f, indent=2, ensure_ascii=False, default=str)

    return added, updated


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="UIUC SRO Collector")
    parser.add_argument("--save", action="store_true", help="Merge into processed/opportunities.json")
    parser.add_argument("--pages", type=int, default=None, help="Max pages to scrape (default: all)")
    args = parser.parse_args()

    collector = UIUCSROCollector()
    if args.pages:
        collector.MAX_PAGES = args.pages

    opps_raw = collector.collect()
    opps = []
    for raw in opps_raw:
        try:
            opps.append(raw_to_normalized(raw))
        except Exception as e:
            logger.error(f"Normalize failed: {e}")

    print(f"\nFetched and normalized {len(opps)} opportunities from SRO\n")

    for i, opp in enumerate(opps[:5]):
        intl = opp["eligibility"]["international_friendly"]
        deadline = opp.get("deadline") or "none"
        areas = ", ".join(opp.get("keywords", []))
        print(f"[{i+1}] {opp['title'][:65]}")
        print(f"    Areas: {areas} | Intl: {intl} | Deadline: {deadline}")
        print(f"    URL: {opp['url']}")
        print()

    if args.save:
        added, updated = merge_into_processed(opps)
        print(f"Saved: {added} new, {updated} updated")
    else:
        print("(Use --save to merge into processed/opportunities.json)")
