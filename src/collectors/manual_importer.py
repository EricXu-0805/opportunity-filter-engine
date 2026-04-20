"""
Manual Importer — load opportunities from JSON/CSV files or add single entries.
This is the primary data entry tool for V1 before scrapers are fully operational.

Usage:
    # Import from JSON file
    python -m src.collectors.manual_importer --file data/manual_entries/batch_001.json

    # Import from CSV
    python -m src.collectors.manual_importer --file data/manual_entries/batch_001.csv

    # Validate existing data
    python -m src.collectors.manual_importer --validate data/processed/opportunities.json
"""

import json
import csv
import uuid
import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
MANUAL_DIR = DATA_DIR / "manual_entries"

# Ensure directories exist
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
MANUAL_DIR.mkdir(parents=True, exist_ok=True)


def create_opportunity(
    title: str,
    url: str,
    source: str = "manual",
    organization: str = "",
    opportunity_type: str = "research",
    location: str = "Champaign, IL",
    on_campus: bool = True,
    paid: str = "unknown",
    deadline: Optional[str] = None,
    preferred_year: Optional[list] = None,
    majors: Optional[list] = None,
    skills_required: Optional[list] = None,
    skills_preferred: Optional[list] = None,
    international_friendly: str = "unknown",
    contact_method: str = "unknown",
    requires_resume: str = "unknown",
    application_effort: str = "medium",
    description: str = "",
    department: str = "",
    lab_or_program: str = "",
    pi_name: Optional[str] = None,
    **kwargs,
) -> dict:
    """
    Create a single opportunity record in the normalized schema.
    This is the canonical way to add manual entries.
    """
    from src.normalizers.enricher import enrich_opportunity

    opp_id = kwargs.get("id") or f"manual-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    opp = {
        "id": opp_id,
        "source": source,
        "source_url": url,
        "source_type": kwargs.get("source_type", "manual"),
        "title": title.strip(),
        "organization": organization,
        "department": department,
        "lab_or_program": lab_or_program,
        "pi_name": pi_name,
        "url": url,
        "location": location,
        "on_campus": on_campus,
        "remote_option": kwargs.get("remote_option", "no" if on_campus else "unknown"),
        "opportunity_type": opportunity_type,
        "paid": paid,
        "compensation_details": kwargs.get("compensation_details", ""),
        "deadline": deadline,
        "posted_date": kwargs.get("posted_date", now[:10]),
        "start_date": kwargs.get("start_date"),
        "duration": kwargs.get("duration"),
        "eligibility": {
            "preferred_year": preferred_year or ["freshman", "sophomore", "junior", "senior"],
            "min_gpa": kwargs.get("min_gpa"),
            "majors": majors or [],
            "skills_required": skills_required or [],
            "skills_preferred": skills_preferred or [],
            "citizenship_required": kwargs.get("citizenship_required", False),
            "international_friendly": international_friendly,
            "work_auth_notes": kwargs.get("work_auth_notes", ""),
            "eligibility_text_raw": kwargs.get("eligibility_text", ""),
        },
        "application": {
            "contact_method": contact_method,
            "requires_resume": requires_resume,
            "requires_cover_letter": kwargs.get("requires_cover_letter", "unknown"),
            "requires_transcript": kwargs.get("requires_transcript", "unknown"),
            "requires_recommendation": kwargs.get("requires_recommendation", "unknown"),
            "application_effort": application_effort,
            "application_url": kwargs.get("application_url", url),
        },
        "description_raw": description,
        "description_clean": description[:500].strip(),
        "keywords": kwargs.get("keywords", []),
        "metadata": {
            "confidence_score": 0.90,  # Manual entries are high confidence
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": True,
            "notes": kwargs.get("notes", ""),
        },
    }
    return enrich_opportunity(opp)


def load_from_json(filepath: str) -> list[dict]:
    """Load opportunities from a JSON file. Accepts list or single object."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    results = []
    for item in data:
        # If already in full schema format, use as-is
        if "eligibility" in item and isinstance(item["eligibility"], dict):
            results.append(item)
        else:
            # Flat format — convert to nested schema
            results.append(create_opportunity(**item))

    logger.info(f"Loaded {len(results)} opportunities from {filepath}")
    return results


def load_from_csv(filepath: str) -> list[dict]:
    """
    Load opportunities from a CSV file.
    Expected columns: title, url, organization, opportunity_type, location,
    paid, deadline, majors, skills_required, international_friendly, description
    List fields (majors, skills_required) use semicolons as delimiters.
    """
    results = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse list fields
            majors = [m.strip() for m in row.get("majors", "").split(";") if m.strip()]
            skills = [s.strip() for s in row.get("skills_required", "").split(";") if s.strip()]
            years = [y.strip() for y in row.get("preferred_year", "").split(";") if y.strip()]

            opp = create_opportunity(
                title=row.get("title", ""),
                url=row.get("url", ""),
                organization=row.get("organization", ""),
                opportunity_type=row.get("opportunity_type", "research"),
                location=row.get("location", "Champaign, IL"),
                on_campus=row.get("on_campus", "true").lower() == "true",
                paid=row.get("paid", "unknown"),
                deadline=row.get("deadline") or None,
                preferred_year=years or None,
                majors=majors or None,
                skills_required=skills or None,
                international_friendly=row.get("international_friendly", "unknown"),
                contact_method=row.get("contact_method", "unknown"),
                requires_resume=row.get("requires_resume", "unknown"),
                application_effort=row.get("application_effort", "medium"),
                description=row.get("description", ""),
                department=row.get("department", ""),
                lab_or_program=row.get("lab_or_program", ""),
                pi_name=row.get("pi_name") or None,
            )
            results.append(opp)

    logger.info(f"Loaded {len(results)} opportunities from CSV {filepath}")
    return results


def save_opportunities(opportunities: list[dict], filepath: str = None):
    """Save opportunities to the processed data file. Merges with existing data by ID."""
    filepath = filepath or str(PROCESSED_DIR / "opportunities.json")

    # Load existing
    existing = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            existing = json.load(f)

    # Build index by ID
    index = {opp["id"]: opp for opp in existing}

    # Merge new data
    added, updated = 0, 0
    for opp in opportunities:
        if opp["id"] in index:
            index[opp["id"]] = opp
            updated += 1
        else:
            index[opp["id"]] = opp
            added += 1

    # Write back
    all_opps = list(index.values())
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_opps, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"Saved {len(all_opps)} opportunities ({added} new, {updated} updated) to {filepath}")
    return added, updated


def validate_opportunity(opp: dict) -> list[str]:
    """Validate a single opportunity record. Returns list of issues."""
    issues = []

    # Required fields
    if not opp.get("title"):
        issues.append("Missing title")
    if not opp.get("url"):
        issues.append("Missing url")
    if not opp.get("source"):
        issues.append("Missing source")
    if not opp.get("opportunity_type"):
        issues.append("Missing opportunity_type")

    # Schema structure
    if not isinstance(opp.get("eligibility"), dict):
        issues.append("Missing or invalid eligibility dict")
    if not isinstance(opp.get("application"), dict):
        issues.append("Missing or invalid application dict")

    # International tag
    intl = opp.get("eligibility", {}).get("international_friendly", "")
    if intl not in ("yes", "no", "unknown"):
        issues.append(f"Invalid international_friendly value: {intl}")

    return issues


def validate_file(filepath: str):
    """Validate all opportunities in a JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_issues = 0
    for i, opp in enumerate(data):
        issues = validate_opportunity(opp)
        if issues:
            total_issues += len(issues)
            print(f"  [{i}] {opp.get('title', 'NO TITLE')}")
            for issue in issues:
                print(f"      ⚠ {issue}")

    if total_issues == 0:
        print(f"✅ All {len(data)} records pass validation")
    else:
        print(f"\n⚠ {total_issues} issues found across {len(data)} records")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Manual Opportunity Importer")
    parser.add_argument("--file", "-f", help="Path to JSON or CSV file to import")
    parser.add_argument("--validate", "-v", help="Path to JSON file to validate")
    parser.add_argument("--output", "-o", help="Output path (default: data/processed/opportunities.json)")
    args = parser.parse_args()

    if args.validate:
        print(f"Validating {args.validate}...")
        validate_file(args.validate)
    elif args.file:
        filepath = args.file
        if filepath.endswith(".csv"):
            opps = load_from_csv(filepath)
        elif filepath.endswith(".json"):
            opps = load_from_json(filepath)
        else:
            print(f"Unsupported file type: {filepath}")
            sys.exit(1)

        # Validate before saving
        all_valid = True
        for opp in opps:
            issues = validate_opportunity(opp)
            if issues:
                all_valid = False
                print(f"⚠ {opp.get('title', 'NO TITLE')}: {issues}")

        if all_valid:
            output = args.output or str(PROCESSED_DIR / "opportunities.json")
            added, updated = save_opportunities(opps, output)
            print(f"✅ Import complete: {added} added, {updated} updated → {output}")
        else:
            print("Fix validation issues before importing. Use --validate to check.")
    else:
        parser.print_help()
