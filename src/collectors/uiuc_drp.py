"""Collector for UIUC Directed Reading Programs (Math DRP + CS DRP).

Two distinct DRPs share the same model — pair undergrads with grad mentors
for a structured reading project. Math DRP runs Fall + Spring (1-week
application window before each semester). CS DRP runs only winter break.

Both programs publish a single program page that flips between "open" and
"closed" depending on the application window. We emit one record per program
unconditionally so they stay discoverable; status is updated from the page.

Usage:
    python -m src.collectors.uiuc_drp
    python -m src.collectors.uiuc_drp --save
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
HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}

MATH_DRP_URL = "https://mathdrp.web.illinois.edu/"
CS_DRP_URL = "https://siebelschool.illinois.edu/research/undergraduate-research/DRP"

OPEN_KEYWORDS = ("application open", "applications open", "apply now", "now accepting", "register now")
CLOSED_KEYWORDS = ("applications closed", "application closed", "no longer accepting", "closed for")


def _detect_status(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True).lower()
    excerpt = (soup.get_text(" ", strip=True))[:600]
    if any(k in text for k in OPEN_KEYWORDS):
        return "open", excerpt
    if any(k in text for k in CLOSED_KEYWORDS):
        return "closed", excerpt
    return "unknown", excerpt


class UIUCDRPCollector(BaseCollector):
    def __init__(self, config: dict | None = None):
        super().__init__(source_name="uiuc_drp", config=config or {"rate_limit_delay": 3})

    def collect(self) -> list[RawOpportunity]:
        return [self._fetch_one(*spec) for spec in self._specs()]

    def _specs(self) -> list[tuple]:
        return [
            (
                MATH_DRP_URL,
                "Math DRP — Directed Reading Program (Mathematics)",
                "Department of Mathematics",
                "DRP-Math",
                "LAS",
                "fall_spring",
                (
                    "Semester-long one-on-one reading project pairing math "
                    "undergraduates with graduate student mentors. Topic chosen "
                    "from outside the standard curriculum. Optional presentation "
                    "or write-up at the end. Application opens about a week before "
                    "each semester starts (Fall + Spring)."
                ),
                ["Mathematics", "Applied Math", "Statistics", "CS+Math"],
                ["sophomore", "junior", "senior"],
            ),
            (
                CS_DRP_URL,
                "CS DRP — Directed Reading Program (Computer Science, Winter Break)",
                "Siebel School of Computing and Data Science",
                "DRP-CS",
                "Siebel CDS",
                "winter",
                (
                    "Winter-break reading program in computer science. Junior or "
                    "senior CS / CS+X students pair with a grad student mentor for "
                    "a deep dive into a CS topic. Application opens in early "
                    "December and runs through January."
                ),
                ["Computer Science", "CS+X", "Data Science"],
                ["junior", "senior"],
            ),
        ]

    def _fetch_one(
        self,
        url: str,
        title: str,
        org: str,
        program: str,
        college: str,
        semester: str,
        fallback_desc: str,
        majors: list,
        preferred_year: list,
    ) -> RawOpportunity:
        status = "unknown"
        excerpt = ""
        try:
            resp = requests.get(url, timeout=30, headers=HEADERS)
            resp.raise_for_status()
            status, excerpt = _detect_status(resp.text)
        except Exception as e:
            self.logger.warning(f"DRP fetch failed for {url}: {e}")

        description = fallback_desc
        if excerpt:
            description = f"{fallback_desc}\n\nFrom the program page: {excerpt[:400]}"
        suffix = {"open": " (applications open)", "closed": " (applications closed)", "unknown": ""}[status]
        return RawOpportunity(
            source="uiuc_drp",
            source_url=url,
            title=f"{title}{suffix}",
            description_raw=description,
            url=url,
            organization=org,
            extra_fields={
                "program": program,
                "college": college,
                "semester": semester,
                "status": status,
                "level": "program_overview",
                "_majors": majors,
                "_preferred_year": preferred_year,
            },
        )


def _hash_id(program: str, source: str) -> str:
    return hashlib.md5(f"{source}::{program}".encode()).hexdigest()[:16]


def _to_normalized(r: RawOpportunity) -> dict:
    now = datetime.utcnow().isoformat()
    program = r.extra_fields.get("program", "DRP")
    majors = r.extra_fields.pop("_majors", [])
    preferred_year = r.extra_fields.pop("_preferred_year", ["junior", "senior"])
    return {
        "id": _hash_id(program, r.source),
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
        "paid": "no",
        "deadline": None,
        "is_rolling": True,
        "on_campus": True,
        "eligibility": {
            "majors": majors,
            "preferred_year": preferred_year,
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
        "keywords": ["research", "reading", "mentor", "directed_reading", program.lower()],
        "metadata": {
            "is_active": True,
            "scraped_at": now,
            "first_seen": now,
        },
        **r.extra_fields,
    }


def fetch_and_normalize() -> list[dict]:
    raw = UIUCDRPCollector().collect()
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
    print(f"Fetched {len(opps)} DRP records")
    for o in opps:
        print(f"  - {o['title']} (status={o.get('status', '?')})")
    if args.save:
        a, u = merge_into_processed(opps)
        print(f"Saved: +{a} new, ~{u} updated")
