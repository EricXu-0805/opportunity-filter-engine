"""Collector for UIUC program-overview hubs that don't justify a dedicated module.

Bundles small, slow-changing program pages where each source produces only a
handful of records:

- LAS Research hub (college overview + PURSUE LAS funding program)
- Beckman Institute undergraduate fellowships (~4 named awards)
- Grainger ISUR (Illinois Scholars Undergraduate Research)
- ATLAS Internship Program (LAS technology internships, status flag only)

Each program is seeded so it shows up in the system unconditionally. The page
is scraped on each refresh to (a) detect open/closed status text, (b) pick up
description tweaks. Failures fall back to seed text.

Usage:
    python -m src.collectors.uiuc_other
    python -m src.collectors.uiuc_other --save
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, RawOpportunity

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}

OPEN_KEYWORDS = ("applications open", "apply now", "now accepting", "application open")
CLOSED_KEYWORDS = ("applications closed", "application closed", "no longer accepting")

PROGRAMS = [
    {
        "key": "las_research_hub",
        "url": "https://las.illinois.edu/research/students",
        "title": "LAS Research — College of Liberal Arts and Sciences",
        "organization": "College of Liberal Arts and Sciences",
        "college": "LAS",
        "majors": [],
        "preferred_year": ["freshman", "sophomore", "junior", "senior"],
        "paid": "unknown",
        "contact_email": "undergradresearch@illinois.edu",
        "fallback_desc": (
            "Hub page for undergraduate research in the College of Liberal Arts "
            "and Sciences. Aggregates major-specific research pages (Astronomy, "
            "Biochem, Chemistry, Psychology, ...), institute openings (Beckman, "
            "IGB), and LAS-funded research programs. Start here if your major "
            "is in LAS and you want a directory of where to apply."
        ),
    },
    {
        "key": "pursue_las",
        "url": "https://las.illinois.edu/research/resources/pursue",
        "title": "PURSUE LAS — LAS Undergraduate Research Funding",
        "organization": "College of Liberal Arts and Sciences",
        "college": "LAS",
        "majors": [],
        "preferred_year": ["sophomore", "junior", "senior"],
        "paid": "stipend",
        "contact_email": "undergradresearch@illinois.edu",
        "fallback_desc": (
            "PURSUE LAS funds LAS undergraduates conducting research with an LAS "
            "faculty mentor. Awards range from semester stipends to full summer "
            "research support. Open to all LAS majors. Application cycles tied "
            "to LAS departmental cohorts."
        ),
    },
    {
        "key": "beckman_fellowships",
        "url": "https://beckman.illinois.edu/opportunities/guidelines-requirements-for-other-sponsored-awards-and-fellowships",
        "title": "Beckman Institute — Undergraduate Fellowships",
        "organization": "Beckman Institute for Advanced Science and Technology",
        "college": "LAS / Beckman",
        "majors": ["Bioengineering", "Chemistry", "Physics", "Psychology", "Neuroscience", "Computer Science"],
        "preferred_year": ["sophomore", "junior", "senior"],
        "paid": "stipend",
        "contact_email": "beckman-info@illinois.edu",
        "fallback_desc": (
            "Beckman Institute hosts a handful of named undergraduate fellowships "
            "(Beckman Scholars Program, Engelbrecht Memorial Awards, Beckman "
            "Summer Research) for students working with Beckman-affiliated "
            "faculty. Spring application; summer + academic-year stipends. "
            "Interdisciplinary research in biological/cognitive/imaging/nano."
        ),
    },
    {
        "key": "grainger_isur",
        "url": "https://isur.engineering.illinois.edu/",
        "title": "ISUR — Illinois Scholars Undergraduate Research (Grainger Engineering)",
        "organization": "Grainger College of Engineering",
        "college": "Grainger Engineering",
        "majors": ["Engineering"],
        "preferred_year": ["sophomore", "junior"],
        "paid": "stipend",
        "contact_email": "isur@illinois.edu",
        "fallback_desc": (
            "Two-semester structured undergraduate research apprenticeship in the "
            "Grainger College of Engineering. Each cohort of ~30–50 scholars "
            "identifies a faculty mentor, attends cohort workshops, and produces "
            "a research deliverable. Annual Spring recruitment; April deadline. "
            "Open to engineering sophomores and juniors. Includes a stipend."
        ),
    },
    {
        "key": "grainger_opportunities_table",
        "url": "https://one.illinois.edu/graingerugresearch/research-opportunities/",
        "title": "Grainger Engineering — Undergraduate Research Opportunities Table",
        "organization": "Grainger College of Engineering",
        "college": "Grainger Engineering",
        "majors": ["Engineering"],
        "preferred_year": ["sophomore", "junior", "senior"],
        "paid": "unknown",
        "contact_email": "graingerugresearch@illinois.edu",
        "fallback_desc": (
            "Aggregated table of external scholarships, fellowships, and research "
            "programs for Grainger Engineering undergraduates (Sandia, ORISE, "
            "Army EOP, ISUR, NSF REUs, etc.) curated by the college's Undergrad "
            "Research office. Deadlines vary; refreshed each semester."
        ),
    },
    {
        "key": "atlas_internship",
        "url": "https://atlas.illinois.edu/atlas-internship-program",
        "title": "ATLAS — Applied Technologies for Learning in the Arts and Sciences",
        "organization": "ATLAS — College of Liberal Arts and Sciences",
        "college": "LAS / ATLAS",
        "majors": [],
        "preferred_year": ["freshman", "sophomore", "junior", "senior"],
        "paid": "yes",
        "contact_email": "atlas@illinois.edu",
        "fallback_desc": (
            "ATLAS Internship Program places LAS undergraduates with technology "
            "projects across UIUC and community organizations. Roles include "
            "data analysis, web development, technical writing, social media, "
            "and software engineering. ~30–60 placements per semester (Fall + "
            "Summer). Paid; matched internally — individual project listings "
            "are not public. Apply through atlas.illinois.edu."
        ),
    },
    {
        "key": "research_park_internships",
        "url": "https://researchpark.illinois.edu/work-here/careers/",
        "title": "UIUC Research Park — Student Internships and Part-Time Jobs",
        "organization": "Research Park",
        "college": "Cross-college",
        "majors": [],
        "preferred_year": ["freshman", "sophomore", "junior", "senior"],
        "paid": "yes",
        "contact_email": "uirp-jobs@illinois.edu",
        "fallback_desc": (
            "Research Park hosts 120+ technology companies (Fortune 500 and "
            "startups) on the south side of campus, employing 2000+ affiliated "
            "staff and 350+ student interns. Internships run year-round — "
            "part-time during the semester and full-time over the summer. "
            "Roles span data science, AI/ML, software, hardware, biotech, "
            "UI/UX, communications, and business. Each company hires "
            "independently through the central Job Board. Many positions are "
            "Research Park exclusive and do not appear on Handshake. Highest "
            "hiring volume: August–October and January–March. Open to all "
            "majors, all class years, and international students."
        ),
    },
]


class UIUCOtherCollector(BaseCollector):
    def __init__(self, config: dict | None = None):
        super().__init__(source_name="uiuc_other", config=config or {"rate_limit_delay": 2})

    def collect(self) -> list[RawOpportunity]:
        records: list[RawOpportunity] = []
        for spec in PROGRAMS:
            description = spec["fallback_desc"]
            status = "unknown"
            try:
                resp = requests.get(spec["url"], timeout=20, headers=HEADERS)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                page_text = soup.get_text(" ", strip=True).lower()
                if any(k in page_text for k in OPEN_KEYWORDS):
                    status = "open"
                elif any(k in page_text for k in CLOSED_KEYWORDS):
                    status = "closed"
                excerpt = soup.get_text(" ", strip=True)[:600]
                if excerpt:
                    description = f"{spec['fallback_desc']}\n\nFrom the program page: {excerpt[:400]}"
            except Exception as e:
                self.logger.warning(f"{spec['key']} fetch failed (using seed): {e}")
            finally:
                self._rate_limit()

            title = spec["title"]
            if status == "open":
                title = f"{title} (applications open)"
            elif status == "closed":
                title = f"{title} (applications closed)"

            records.append(RawOpportunity(
                source="uiuc_other",
                source_url=spec["url"],
                title=title,
                description_raw=description,
                url=spec["url"],
                organization=spec["organization"],
                extra_fields={
                    "program_key": spec["key"],
                    "college": spec["college"],
                    "status": status,
                    "level": "program_overview",
                    "_majors": spec["majors"],
                    "_preferred_year": spec["preferred_year"],
                    "_paid": spec["paid"],
                    "_contact_email": spec.get("contact_email"),
                },
            ))
        return records


def _hash_id(program_key: str, source: str) -> str:
    return hashlib.md5(f"{source}::{program_key}".encode()).hexdigest()[:16]


def _to_normalized(r: RawOpportunity) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    majors = r.extra_fields.pop("_majors", [])
    preferred_year = r.extra_fields.pop("_preferred_year", ["sophomore", "junior"])
    paid = r.extra_fields.pop("_paid", "unknown")
    contact_email = r.extra_fields.pop("_contact_email", None)
    program_key = r.extra_fields.get("program_key", "uiuc_other")
    return {
        "id": _hash_id(program_key, r.source),
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
        "opportunity_type": "research" if "research" in r.title.lower() else "internship",
        "paid": paid,
        "deadline": None,
        "is_rolling": True,
        "on_campus": True,
        "contact_email": contact_email,
        "eligibility": {
            "majors": majors,
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
        "keywords": ["research", "program_overview", program_key],
        "metadata": {
            "is_active": True,
            "last_verified": now,
            "first_seen_at": now,
        },
        **r.extra_fields,
    }


def fetch_and_normalize() -> list[dict]:
    raw = UIUCOtherCollector().collect()
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
                old.setdefault("metadata", {})["last_updated"] = opp["metadata"]["last_verified"]
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
    print(f"Fetched {len(opps)} program-overview records")
    for o in opps:
        print(f"  - {o['title'][:90]}")
    if args.save:
        a, u = merge_into_processed(opps)
        print(f"Saved: +{a} new, ~{u} updated")
