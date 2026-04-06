"""
Collector for UIUC Summer Research Opportunities Database.
URL: https://researchops.web.illinois.edu/
Drupal CMS with paginated table view.

Usage:
    python -m src.collectors.uiuc_sro              # fetch & preview
    python -m src.collectors.uiuc_sro --save       # fetch & merge into processed data
    python -m src.collectors.uiuc_sro --deep       # deep scrape detail pages
"""

import re
import json
import hashlib
import logging
import time
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

DEEP_SCRAPE_DELAY = 3  # seconds between detail page fetches


class UIUCSROCollector(BaseCollector):
    """Scrapes UIUC Summer Research Opportunities Database."""

    BASE_URL = "https://researchops.web.illinois.edu/"
    MAX_PAGES = 15  # Safety cap; stops when no more rows

    def __init__(self, config: dict = None, deep: bool = False):
        super().__init__(
            source_name="uiuc_sro",
            config=config or {"rate_limit_delay": 3},
        )
        self.deep = deep

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

        if self.deep:
            self.logger.info(f"Deep scraping {len(opportunities)} detail pages...")
            for i, opp in enumerate(opportunities):
                if opp.url:
                    self._fetch_detail_page(opp)
                    if i < len(opportunities) - 1:
                        time.sleep(DEEP_SCRAPE_DELAY)

        return opportunities

    def _fetch_detail_page(self, opp: RawOpportunity) -> None:
        """Fetch and parse a detail page, enriching the RawOpportunity in-place."""
        try:
            self.logger.info(f"  Deep scraping: {opp.url}")
            resp = requests.get(opp.url, timeout=30, headers={
                "User-Agent": "OpportunityFilterEngine/1.0 (educational project)"
            })
            resp.raise_for_status()
            detail = self._parse_detail_page(resp.text)

            if detail.get("description"):
                opp.description_raw = detail["description"]
            if detail.get("organization"):
                opp.organization = detail["organization"]
            if detail.get("eligibility_text"):
                opp.extra_fields["eligibility_text"] = detail["eligibility_text"]
            if detail.get("application_url"):
                opp.extra_fields["application_url"] = detail["application_url"]
            if detail.get("deadline"):
                opp.deadline = detail["deadline"]
                opp.extra_fields["deadline_raw"] = detail["deadline"]
            if detail.get("citizenship_info"):
                opp.extra_fields["citizenship_info"] = detail["citizenship_info"]
            if detail.get("paid_info"):
                opp.extra_fields["paid_info"] = detail["paid_info"]

            opp.extra_fields["deep_scraped"] = True

        except Exception as e:
            self.logger.error(f"  Failed to deep scrape {opp.url}: {e}")

    def _parse_detail_page(self, html: str) -> dict:
        """Parse a detail page and extract structured fields."""
        soup = BeautifulSoup(html, "html.parser")
        detail = {}

        # Full description - look for the main content area
        content = soup.select_one(
            "div.field--name-body, "
            "div.node__content, "
            "article .field--name-field-description, "
            "div.field--name-field-body"
        )
        if content:
            detail["description"] = content.get_text(separator="\n", strip=True)

        # Sponsoring organization
        org_field = soup.select_one(
            "div.field--name-field-sponsoring-organization, "
            "div.field--name-field-organization, "
            "div.field--name-field-sponsor"
        )
        if org_field:
            detail["organization"] = org_field.get_text(strip=True)
            # Clean common prefixes from Drupal field labels
            for prefix in ["Sponsoring Organization", "Organization", "Sponsor"]:
                if detail["organization"].startswith(prefix):
                    detail["organization"] = detail["organization"][len(prefix):].strip()

        # Eligibility details
        elig_field = soup.select_one(
            "div.field--name-field-eligibility, "
            "div.field--name-field-eligibility-requirements, "
            "div.field--name-field-requirements"
        )
        if elig_field:
            detail["eligibility_text"] = elig_field.get_text(separator=" ", strip=True)

        # Application URL
        app_link = soup.select_one(
            "div.field--name-field-application-url a, "
            "div.field--name-field-apply-url a, "
            "div.field--name-field-application-link a, "
            "a[href*='apply'], a[href*='application']"
        )
        if app_link:
            detail["application_url"] = app_link.get("href", "")

        # Deadline from detail page
        deadline_field = soup.select_one(
            "div.field--name-field-deadline, "
            "div.field--name-field-deadline-anticipated, "
            "div.field--name-field-application-deadline"
        )
        if deadline_field:
            detail["deadline"] = deadline_field.get_text(strip=True)
            for prefix in ["Deadline", "Application Deadline", "Anticipated Deadline"]:
                if detail["deadline"].startswith(prefix):
                    detail["deadline"] = detail["deadline"][len(prefix):].strip()

        # Extract citizenship/international info from full page text
        full_text = soup.get_text(separator=" ", strip=True)
        citizenship_keywords = [
            "u.s. citizen", "us citizen", "citizenship required",
            "permanent resident", "us only", "must be a u.s.",
            "u.s. citizenship", "international students welcome",
            "open to all", "international students eligible",
            "all students", "no citizenship requirement",
            "international students", "non-citizen", "visa",
            "green card", "authorized to work", "work authorization",
        ]
        citizenship_mentions = []
        full_lower = full_text.lower()
        for kw in citizenship_keywords:
            idx = full_lower.find(kw)
            if idx != -1:
                start = max(0, idx - 50)
                end = min(len(full_text), idx + len(kw) + 50)
                citizenship_mentions.append(full_text[start:end].strip())
        if citizenship_mentions:
            detail["citizenship_info"] = " | ".join(citizenship_mentions)

        # Detect paid/stipend info
        paid_keywords = ["stipend", "paid", "salary", "compensation", "funded", "unfunded"]
        paid_mentions = []
        for kw in paid_keywords:
            idx = full_lower.find(kw)
            if idx != -1:
                start = max(0, idx - 40)
                end = min(len(full_text), idx + len(kw) + 40)
                paid_mentions.append(full_text[start:end].strip())
        if paid_mentions:
            detail["paid_info"] = " | ".join(paid_mentions)

        return detail

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
                                    "must be a u.s.", "u.s. citizenship",
                                    "authorized to work in the united states",
                                    "must be authorized to work in the u.s.",
                                    "u.s. persons only", "u.s. national"]):
        return "no"
    if any(kw in lower for kw in ["international students welcome", "open to all",
                                    "international students eligible", "all students",
                                    "no citizenship requirement",
                                    "international students are encouraged",
                                    "open to international"]):
        return "yes"
    return "unknown"


def _parse_deadline(text: str) -> Optional[str]:
    """Try to parse deadline text into ISO-ish date."""
    if not text:
        return None
    # Remove "Anticipated" prefix
    clean = re.sub(r"(?i)anticipated\s*", "", text).strip()
    # Remove field label prefixes
    for prefix in ["Deadline", "Application Deadline"]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):].strip()
    if not clean:
        return None
    return clean


def _detect_paid_status(text: str) -> str:
    """Detect paid/stipend/unpaid from text."""
    lower = text.lower()
    if any(kw in lower for kw in ["stipend", "funded position", "paid position",
                                    "salary", "compensation provided"]):
        return "yes"
    if any(kw in lower for kw in ["unpaid", "unfunded", "volunteer", "no compensation"]):
        return "no"
    return "unknown"


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
    extra = raw.extra_fields

    # Use deep-scraped citizenship info if available, else fall back to description
    citizenship_text = extra.get("citizenship_info", "") + " " + desc
    intl = _detect_international_friendly(citizenship_text)

    # Use deep-scraped deadline if available
    deadline = _parse_deadline(extra.get("deadline_raw", ""))

    research_area = extra.get("research_area", "")
    timing = extra.get("timing", "")
    majors = _research_area_to_majors(research_area)

    # Detect paid status from deep-scraped info or description
    paid_text = extra.get("paid_info", "") + " " + desc
    paid = _detect_paid_status(paid_text)

    # Use deep-scraped organization if available
    organization = raw.organization or ""

    # Application URL from detail page
    application_url = extra.get("application_url", raw.url)

    # Eligibility text from detail page
    eligibility_text = extra.get("eligibility_text", desc[:300])

    url_hash = hashlib.md5(raw.url.encode()).hexdigest()[:8]
    opp_id = f"sro-{url_hash}"
    now = datetime.utcnow().isoformat()

    is_deep = extra.get("deep_scraped", False)
    confidence = 0.85 if is_deep else 0.7

    return {
        "id": opp_id,
        "source": "uiuc_sro",
        "source_url": raw.source_url,
        "source_type": "summer_program",
        "title": raw.title.strip(),
        "organization": organization,
        "department": "",
        "lab_or_program": raw.title.strip(),
        "pi_name": None,
        "url": raw.url,
        "location": "",
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": "summer_program",
        "paid": paid,
        "compensation_details": extra.get("paid_info", ""),
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
            "work_auth_notes": extra.get("citizenship_info", ""),
            "eligibility_text_raw": eligibility_text[:500],
        },
        "application": {
            "contact_method": "online",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": application_url,
        },
        "description_raw": desc,
        "description_clean": desc[:500],
        "keywords": [a.strip() for a in research_area.split(",") if a.strip()],
        "metadata": {
            "confidence_score": confidence,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": "Auto-imported from UIUC SRO database" + (" (deep scraped)" if is_deep else ""),
        },
    }


def fetch_and_normalize(deep: bool = False) -> list[dict]:
    """Fetch SRO database and return normalized records."""
    collector = UIUCSROCollector(deep=deep)
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
    parser.add_argument("--deep", action="store_true", help="Deep scrape detail pages for richer data")
    args = parser.parse_args()

    collector = UIUCSROCollector(deep=args.deep)
    if args.pages:
        collector.MAX_PAGES = args.pages

    opps_raw = collector.collect()
    opps = []
    for raw in opps_raw:
        try:
            opps.append(raw_to_normalized(raw))
        except Exception as e:
            logger.error(f"Normalize failed: {e}")

    print(f"\nFetched and normalized {len(opps)} opportunities from SRO")
    if args.deep:
        deep_count = sum(1 for o in opps if o["metadata"]["notes"].endswith("(deep scraped)"))
        print(f"  Deep scraped: {deep_count}/{len(opps)}")
    print()

    for i, opp in enumerate(opps[:5]):
        intl = opp["eligibility"]["international_friendly"]
        paid = opp.get("paid", "unknown")
        deadline = opp.get("deadline") or "none"
        areas = ", ".join(opp.get("keywords", []))
        org = opp.get("organization", "") or "unknown org"
        print(f"[{i+1}] {opp['title'][:65]}")
        print(f"    Org: {org} | Areas: {areas}")
        print(f"    Intl: {intl} | Paid: {paid} | Deadline: {deadline}")
        print(f"    URL: {opp['url']}")
        print()

    if args.save:
        added, updated = merge_into_processed(opps)
        print(f"Saved: {added} new, {updated} updated")
    else:
        print("(Use --save to merge into processed/opportunities.json)")
