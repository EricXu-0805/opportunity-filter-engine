"""Collector for Siebel School Undergraduate Research programs.

The Siebel CDS undergraduate-research page is a curated static list of named
programs (SRP, NCSA SPIN, CS STARS, ISUR, DaRin Butz, MUSE, etc.) — not live
project postings. We emit one record per program; the page is scraped to
discover any new programs the school adds.

Usage:
    python -m src.collectors.uiuc_siebel
    python -m src.collectors.uiuc_siebel --save
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, RawOpportunity

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
BASE_URL = "https://siebelschool.illinois.edu/research/undergraduate-research"
HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}

SEED_PROGRAMS = [
    {
        "title": "Siebel Summer Research Program (SRP)",
        "description": "10-week paid summer research program for CS and CS+X undergraduates. Students work closely with a Siebel CDS faculty member. Application typically opens January, deadline early February.",
        "program": "SRP",
        "preferred_year": ["sophomore", "junior", "senior"],
        "paid": "yes",
    },
    {
        "title": "CS DRP — Directed Reading Program (Winter)",
        "description": "Winter-break reading program where CS juniors/seniors pair with grad student mentors for a deep dive into a CS topic.",
        "program": "CS-DRP",
        "preferred_year": ["junior", "senior"],
        "paid": "no",
    },
    {
        "title": "CS STARS / CS Ambassadors",
        "description": "Broadening Participation in Computing program — student-led mentorship and research community focused on supporting first-year CS students from underrepresented groups.",
        "program": "CS-STARS",
        "preferred_year": ["freshman", "sophomore"],
        "paid": "unknown",
    },
    {
        "title": "ISUR — Illinois Scholars Undergraduate Research",
        "description": "2-semester structured apprenticeship program (Grainger College of Engineering). Students identify a faculty mentor and produce a research deliverable. Annual Spring recruitment with an April application deadline.",
        "program": "ISUR",
        "preferred_year": ["sophomore", "junior"],
        "paid": "stipend",
    },
    {
        "title": "NCSA SPIN — Students Pushing Innovation",
        "description": "Paid semester-long research internship at the National Center for Supercomputing Applications. Students choose from a published list of NCSA projects and work part-time with the project mentor.",
        "program": "NCSA-SPIN",
        "preferred_year": ["sophomore", "junior", "senior"],
        "paid": "yes",
    },
    {
        "title": "UR2PhD (CS 397)",
        "description": "1-credit course preparing undergraduates for PhD applications and a research career. Cohort-based, runs each Spring.",
        "program": "UR2PhD",
        "preferred_year": ["junior", "senior"],
        "paid": "no",
    },
    {
        "title": "DaRin Butz Research Scholars",
        "description": "Endowed scholarship + summer research stipend for CS undergraduates working with Siebel CDS faculty. Spring application.",
        "program": "DaRin-Butz",
        "preferred_year": ["sophomore", "junior"],
        "paid": "stipend",
    },
    {
        "title": "I-MRSEC REU — Materials Research",
        "description": "NSF-funded summer REU program at the Illinois Materials Research Science and Engineering Center. Open to STEM undergrads; includes CS/computational tracks.",
        "program": "I-MRSEC-REU",
        "preferred_year": ["sophomore", "junior"],
        "paid": "yes",
    },
    {
        "title": "MUSE — Multidisciplinary Undergraduate Software Engineering",
        "description": "Multidisciplinary undergrad software engineering research program at Siebel CDS.",
        "program": "MUSE",
        "preferred_year": ["junior", "senior"],
        "paid": "unknown",
    },
    {
        "title": "Undergraduate Research Symposium & Open House",
        "description": "Annual events showcasing undergraduate research and connecting students with potential faculty mentors. Open House each Fall, Symposium each Spring.",
        "program": "Symposium",
        "preferred_year": ["freshman", "sophomore", "junior", "senior"],
        "paid": "no",
    },
]


class UIUCSiebelCollector(BaseCollector):
    def __init__(self, config: dict | None = None):
        super().__init__(source_name="uiuc_siebel", config=config or {"rate_limit_delay": 3})

    def collect(self) -> list[RawOpportunity]:
        page_programs = self._scrape_page()
        program_map = {p["title"].lower(): p for p in SEED_PROGRAMS}
        for found in page_programs:
            key = found["title"].lower()
            if key in program_map:
                program_map[key]["description"] = found.get("description") or program_map[key]["description"]
            else:
                program_map[key] = found
        return [self._to_raw(p) for p in program_map.values()]

    def _scrape_page(self) -> list[dict]:
        try:
            resp = requests.get(BASE_URL, timeout=30, headers=HEADERS)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Siebel page fetch failed (using seeds only): {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        found: list[dict] = []
        for heading in soup.find_all(re.compile(r"^h[2-4]$")):
            title = heading.get_text(" ", strip=True)
            if not title or len(title) < 4 or len(title) > 200:
                continue
            if not any(kw in title.lower() for kw in (
                "research", "drp", "program", "symposium", "scholars", "stars", "ambassadors", "reu", "spin", "muse",
            )):
                continue
            paragraphs: list[str] = []
            sibling = heading.find_next_sibling()
            while sibling and sibling.name not in {"h2", "h3", "h4"}:
                if sibling.name in {"p", "ul", "div"}:
                    text = sibling.get_text(" ", strip=True)
                    if text and len(text) > 25:
                        paragraphs.append(text)
                sibling = sibling.find_next_sibling()
            description = " ".join(paragraphs)[:1000]
            if description:
                found.append({"title": title, "description": description})
        return found

    def _to_raw(self, p: dict) -> RawOpportunity:
        return RawOpportunity(
            source="uiuc_siebel",
            source_url=BASE_URL,
            title=p["title"][:240],
            description_raw=p["description"],
            url=BASE_URL,
            organization="Siebel School of Computing and Data Science",
            extra_fields={
                "program": p.get("program", "Siebel-UG-Research"),
                "college": "Siebel CDS",
                "level": "program_overview",
                "_paid": p.get("paid", "unknown"),
                "_preferred_year": p.get("preferred_year", ["sophomore", "junior", "senior"]),
            },
        )


def _hash_id(title: str, source: str) -> str:
    return hashlib.md5(f"{source}::{title}".encode()).hexdigest()[:16]


def _to_normalized(r: RawOpportunity) -> dict:
    now = datetime.utcnow().isoformat()
    paid = r.extra_fields.pop("_paid", "unknown")
    preferred_year = r.extra_fields.pop("_preferred_year", ["junior", "senior"])
    return {
        "id": _hash_id(r.title, r.source),
        "source": r.source,
        "source_url": r.source_url,
        "title": r.title,
        "description": r.description_raw,
        "url": r.url,
        "organization": r.organization,
        "opportunity_type": "research",
        "paid": paid,
        "deadline": None,
        "is_rolling": True,
        "on_campus": True,
        "eligibility": {
            "majors": ["Computer Science", "CS+X", "Data Science"],
            "preferred_year": preferred_year,
            "skills_required": [],
            "international_friendly": "yes",
            "citizenship_required": False,
        },
        "application": {
            "application_url": r.url,
            "application_effort": "medium",
            "requires_resume": "yes",
            "requires_cover_letter": "unknown",
            "requires_recommendation": "unknown",
        },
        "keywords": ["research", "computer_science", "siebel", "mentor"],
        "metadata": {
            "is_active": True,
            "scraped_at": now,
            "first_seen": now,
        },
        **r.extra_fields,
    }


def fetch_and_normalize() -> list[dict]:
    raw = UIUCSiebelCollector().collect()
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
            if old.get("description") != opp["description"]:
                old["description"] = opp["description"]
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
    print(f"Fetched {len(opps)} Siebel research programs")
    for o in opps:
        print(f"  - {o['title'][:80]}")
    if args.save:
        a, u = merge_into_processed(opps)
        print(f"Saved: +{a} new, ~{u} updated")
