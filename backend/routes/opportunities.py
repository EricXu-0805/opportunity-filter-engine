from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, date, timedelta

from fastapi import APIRouter, HTTPException, Query

from backend.data_loader import load_opportunities, load_opportunities_by_id

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


@router.post("/opportunities/batch")
async def get_opportunities_batch(request: dict):
    """Return multiple opportunities by ID in a single request.

    Body: {"ids": ["id1", "id2", ...]} — capped at 200 to bound work.
    Missing IDs are silently skipped so the caller can always iterate
    the response alongside its own list.
    """
    ids = request.get("ids") if isinstance(request, dict) else None
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="Body must be {ids: string[]}")
    if len(ids) > 200:
        raise HTTPException(status_code=400, detail="At most 200 IDs per request")

    lookup = load_opportunities_by_id()
    results = []
    for oid in ids:
        if not isinstance(oid, str) or len(oid) > 100:
            continue
        opp = lookup.get(oid)
        if opp is not None:
            results.append(_redact(opp))
    return {"opportunities": results, "requested": len(ids), "found": len(results)}


@router.get("/opportunities/upcoming")
async def get_upcoming_deadlines(days: int = Query(default=30, ge=1, le=365)):
    """Opportunities with deadlines within the next ``days`` days, sorted ascending.

    Useful for building a calendar / "what's due soon" widget without
    re-ranking the full corpus per request.
    """
    opportunities = load_opportunities()
    today = date.today()
    cutoff = today + timedelta(days=days)
    upcoming = []
    for o in opportunities:
        deadline = o.get("deadline", "")
        if not deadline or len(deadline) < 10 or deadline[4] != "-":
            continue
        try:
            dl = date.fromisoformat(deadline[:10])
        except ValueError:
            continue
        if today <= dl <= cutoff:
            upcoming.append({
                "id": o.get("id"),
                "title": o.get("title"),
                "organization": o.get("organization"),
                "deadline": deadline,
                "days_left": (dl - today).days,
                "opportunity_type": o.get("opportunity_type"),
                "paid": o.get("paid"),
                "url": o.get("url"),
                "source": o.get("source"),
            })
    upcoming.sort(key=lambda o: o["deadline"])
    return {"total": len(upcoming), "opportunities": upcoming, "days": days}


@router.get("/opportunities/{opportunity_id}/similar")
async def get_similar_opportunities(
    opportunity_id: str,
    limit: int = Query(default=5, ge=1, le=20),
):
    """Return opportunities similar to the given one.

    Similarity is the weighted sum of:
      * shared keyword count  (primary signal)
      * same opportunity_type (small bonus)
      * shared majors         (small bonus)
      * same organization     (small bonus for "more from this lab")
    The source opportunity is always excluded.
    """
    if len(opportunity_id) > 100:
        raise HTTPException(status_code=400, detail="Invalid opportunity ID")

    lookup = load_opportunities_by_id()
    source = lookup.get(opportunity_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    source_keywords = {k.lower() for k in (source.get("keywords") or []) if isinstance(k, str)}
    source_majors = {m.lower() for m in (source.get("eligibility") or {}).get("majors", []) if isinstance(m, str)}
    source_type = source.get("opportunity_type")
    source_org = (source.get("organization") or "").lower()

    scored: list[tuple[float, dict]] = []
    for opp in load_opportunities():
        if opp.get("id") == opportunity_id:
            continue
        if not opp.get("metadata", {}).get("is_active", True):
            continue

        kws = {k.lower() for k in (opp.get("keywords") or []) if isinstance(k, str)}
        majors = {m.lower() for m in (opp.get("eligibility") or {}).get("majors", []) if isinstance(m, str)}

        shared_keywords = len(source_keywords & kws)
        shared_majors = len(source_majors & majors)

        score = 0.0
        if source_keywords:
            score += shared_keywords * 3.0
        if source_type and opp.get("opportunity_type") == source_type:
            score += 1.0
        if source_majors:
            score += shared_majors * 0.5
        if source_org and (opp.get("organization") or "").lower() == source_org:
            score += 0.5

        if score <= 0:
            continue
        scored.append((score, opp))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    return {
        "source_id": opportunity_id,
        "total": len(top),
        "opportunities": [
            {**_redact(o), "_similarity": round(s, 2)}
            for s, o in top
        ],
    }


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: str):
    if len(opportunity_id) > 100:
        raise HTTPException(status_code=400, detail="Invalid opportunity ID")

    opp = load_opportunities_by_id().get(opportunity_id)
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

    from datetime import datetime
    from pathlib import Path
    data_path = Path(__file__).resolve().parents[2] / "data" / "processed" / "opportunities.json"
    last_updated_at = None
    if data_path.exists():
        last_updated_at = datetime.fromtimestamp(
            data_path.stat().st_mtime, tz=UTC
        ).isoformat()

    result = {
        "total": len(opportunities),
        "active": active,
        "paid_total": paid_total,
        "international_friendly_total": intl_total,
        "by_type": type_counts,
        "by_source": source_counts,
        "by_paid": paid_counts,
        "by_international": intl_counts,
        "last_updated_at": last_updated_at,
    }
    _stats_cache = result
    _stats_cache_time = now
    return result
