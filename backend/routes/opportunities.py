from __future__ import annotations

import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query

from backend.data_loader import load_opportunities

router = APIRouter()

REDACTED_FIELDS = {"contact_email", "pi_email"}

_stats_cache: dict | None = None
_stats_cache_time: float = 0
_STATS_TTL = 300


def _redact(opp: dict) -> dict:
    return {k: v for k, v in opp.items() if k not in REDACTED_FIELDS}


@router.get("/opportunities")
async def list_opportunities(
    opportunity_type: str | None = None,
    paid: str | None = None,
    international_friendly: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
):
    opportunities = load_opportunities()

    if opportunity_type:
        opportunities = [o for o in opportunities if o.get("opportunity_type") == opportunity_type]
    if paid:
        opportunities = [o for o in opportunities if o.get("paid") == paid]
    if international_friendly:
        opportunities = [
            o for o in opportunities
            if o.get("eligibility", {}).get("international_friendly") == international_friendly
        ]

    total = len(opportunities)
    page = opportunities[offset:offset + limit]

    return {
        "total": total,
        "opportunities": [_redact(o) for o in page],
        "limit": limit,
        "offset": offset,
    }


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: str):
    if len(opportunity_id) > 100:
        raise HTTPException(status_code=400, detail="Invalid opportunity ID")

    opportunities = load_opportunities()
    opp = next((o for o in opportunities if o["id"] == opportunity_id), None)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return _redact(opp)


@router.get("/opportunities/stats/summary")
async def get_stats():
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache and now - _stats_cache_time < _STATS_TTL:
        return _stats_cache

    opportunities = load_opportunities()

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

    result = {
        "total": len(opportunities),
        "active": active,
        "paid_total": paid_total,
        "international_friendly_total": intl_total,
        "by_type": type_counts,
        "by_source": source_counts,
        "by_paid": paid_counts,
        "by_international": intl_counts,
    }
    _stats_cache = result
    _stats_cache_time = now
    return result
