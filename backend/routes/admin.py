"""
Admin endpoints for data-quality monitoring.

Protected by the ADMIN_TOKEN env var. Call with either:
- Header: X-Admin-Token: <token>
- Query param: ?token=<token>

If ADMIN_TOKEN is unset, all requests return 503 (admin disabled).
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Query

from backend.data_loader import load_opportunities

router = APIRouter()

_UNSORTED_SENTINELS = frozenset({"unsorted", "uncategorized", "misc"})


def _is_unsorted(keywords) -> bool:
    if not keywords:
        return True
    cleaned = [k for k in keywords if isinstance(k, str) and k.strip()]
    if not cleaned:
        return True
    return all(k.strip().lower() in _UNSORTED_SENTINELS for k in cleaned)


def _authenticate(token_query: str | None, token_header: str | None) -> None:
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin endpoints disabled (ADMIN_TOKEN unset)")
    provided = token_header or token_query
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.get("/admin/data-quality")
async def data_quality(
    token: str | None = Query(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    _authenticate(token, x_admin_token)

    opps = load_opportunities()
    total = len(opps)

    by_source: dict[str, dict] = {}
    global_counts = Counter(
        empty_majors=0, empty_keywords=0, empty_description=0,
        short_description=0, missing_deadline=0, missing_skills=0,
        past_deadline=0, stale_verify=0,
    )

    today = datetime.now(timezone.utc).date()
    for o in opps:
        src = o.get("source", "?")
        b = by_source.setdefault(src, Counter(total=0))
        b["total"] += 1

        elig = o.get("eligibility", {}) or {}
        if not (elig.get("majors") or []):
            b["empty_majors"] += 1
            global_counts["empty_majors"] += 1
        if _is_unsorted(o.get("keywords") or []):
            b["empty_keywords"] += 1
            global_counts["empty_keywords"] += 1
        desc = (o.get("description_raw") or o.get("description_clean") or "").strip()
        if not desc:
            b["empty_description"] += 1
            global_counts["empty_description"] += 1
        elif len(desc) < 100:
            b["short_description"] += 1
            global_counts["short_description"] += 1
        if not o.get("deadline"):
            b["missing_deadline"] += 1
            global_counts["missing_deadline"] += 1
        else:
            try:
                dl = datetime.fromisoformat(str(o["deadline"])[:10]).date()
                if dl < today:
                    b["past_deadline"] += 1
                    global_counts["past_deadline"] += 1
            except (ValueError, TypeError):
                pass
        if not (elig.get("skills_required") or []):
            b["missing_skills"] += 1
            global_counts["missing_skills"] += 1
        last_verified = (o.get("metadata") or {}).get("last_verified")
        if last_verified:
            try:
                lv = datetime.fromisoformat(str(last_verified).replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - lv).days > 60:
                    b["stale_verify"] += 1
                    global_counts["stale_verify"] += 1
            except (ValueError, TypeError):
                pass

    sources_list = sorted(
        [
            {"source": src, **dict(c), "total": c["total"]}
            for src, c in by_source.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )

    worst_fields = []
    for o in opps:
        elig = o.get("eligibility", {}) or {}
        missing = 0
        if not (elig.get("majors") or []): missing += 1
        if _is_unsorted(o.get("keywords") or []): missing += 1
        if not (o.get("description_raw") or o.get("description_clean")): missing += 1
        if not o.get("deadline"): missing += 1
        if not (elig.get("skills_required") or []): missing += 1
        if missing >= 3:
            worst_fields.append({
                "id": o.get("id"),
                "title": (o.get("title") or "")[:80],
                "source": o.get("source"),
                "missing_count": missing,
                "url": o.get("url"),
            })
    worst_fields.sort(key=lambda x: x["missing_count"], reverse=True)

    return {
        "total": total,
        "global": dict(global_counts),
        "sources": sources_list,
        "worst_fields": worst_fields[:20],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
