"""Opportunity listing and detail endpoints."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


def _load_opportunities() -> list[dict]:
    processed = DATA_DIR / "opportunities.json"
    if processed.exists():
        with open(processed, encoding="utf-8") as f:
            data = json.load(f)
            if data:
                return data

    examples = EXAMPLES_DIR / "sample_opportunities.json"
    if examples.exists():
        with open(examples, encoding="utf-8") as f:
            return json.load(f)

    return []


@router.get("/opportunities")
async def list_opportunities(
    opportunity_type: str | None = None,
    paid: str | None = None,
    international_friendly: str | None = None,
):
    """List all opportunities with optional filters."""
    opportunities = _load_opportunities()

    if opportunity_type:
        opportunities = [o for o in opportunities if o.get("opportunity_type") == opportunity_type]
    if paid:
        opportunities = [o for o in opportunities if o.get("paid") == paid]
    if international_friendly:
        opportunities = [
            o for o in opportunities
            if o.get("eligibility", {}).get("international_friendly") == international_friendly
        ]

    sources = dict(Counter(o.get("source", "unknown") for o in opportunities))

    return {
        "total": len(opportunities),
        "opportunities": opportunities,
        "sources": sources,
    }


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: str):
    """Get a single opportunity by ID."""
    opportunities = _load_opportunities()
    opp = next((o for o in opportunities if o["id"] == opportunity_id), None)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp


@router.get("/opportunities/stats/summary")
async def get_stats():
    """Aggregate stats for dashboard."""
    opportunities = _load_opportunities()

    type_counts = dict(Counter(o.get("opportunity_type", "unknown") for o in opportunities))
    source_counts = dict(Counter(o.get("source", "unknown") for o in opportunities))
    paid_counts = dict(Counter(o.get("paid", "unknown") for o in opportunities))
    intl_counts = dict(Counter(
        o.get("eligibility", {}).get("international_friendly", "unknown")
        for o in opportunities
    ))

    active = sum(1 for o in opportunities if o.get("metadata", {}).get("is_active", True))
    paid_total = sum(1 for o in opportunities if o.get("paid") in ("yes", "stipend"))
    intl_total = sum(1 for o in opportunities if o.get("eligibility", {}).get("international_friendly") == "yes")

    return {
        "total": len(opportunities),
        "active": active,
        "paid_total": paid_total,
        "international_friendly_total": intl_total,
        "by_type": type_counts,
        "by_source": source_counts,
        "by_paid": paid_counts,
        "by_international": intl_counts,
    }
