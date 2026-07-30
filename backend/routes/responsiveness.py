"""Internal responsiveness signals (红黑榜 v1) — aggregated and anonymous.

Rolls the append-only interaction_status_changes log up into per-opportunity
{contacted_n, replied_n} counts. Service-role access is required because RLS
scopes that table to each device's own rows. Privacy guarantees enforced HERE,
not in the client: only aggregates with contacted_n >= RESPONSIVENESS_MIN_N
ever leave the endpoint, and no device-level data is exposed anywhere.

Absence of evidence is never a judgment: an opportunity with no (or too few)
tracked contacts is simply absent from the map — never scored 0, never ranked
down. The public endpoint additionally serves POSITIVE aggregates only
(replied_n >= 1): "N contacted, zero replies" is a reputation-shaped negative
claim built from self-reported statuses, which stays internal per
docs/REPUTATION_BOARD.md. Both consumers (the "heard back" badge and the
ranker bonus) already require replied_n >= 1, so nothing user-visible changes;
the raw zero-reply aggregate just no longer leaves the backend.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter

from src.matcher.config import RESPONSIVENESS_MIN_N

router = APIRouter()
logger = logging.getLogger("ofe.responsiveness")

CONTACT_STATUSES = frozenset({"applied", "replied", "interviewing", "rejected"})
REPLIED_STATUSES = frozenset({"replied", "interviewing"})

_CACHE_TTL = 3600
# With the bonus on by default, signals_map sits on the match request path.
# A failed fetch must not retry per-request (worst case 30s httpx timeout each);
# serve the (possibly empty) cache and retry after this backoff instead.
_FAILURE_BACKOFF = 120
_PAGE_SIZE = 1000
_MAX_PAGES = 50

_cache: dict[str, dict[str, int]] | None = None
_cache_time: float = 0.0


async def _fetch_status_rows(supabase_url: str, headers: dict) -> list[dict]:
    import httpx

    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=False) as client:
        for page in range(_MAX_PAGES):
            resp = await client.get(
                f"{supabase_url}/rest/v1/interaction_status_changes",
                params={
                    "select": "opportunity_id,device_id,to_status",
                    "limit": str(_PAGE_SIZE),
                    "offset": str(page * _PAGE_SIZE),
                    "order": "changed_at.desc",
                },
                headers=headers,
            )
            resp.raise_for_status()
            batch = resp.json()
            rows.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
    return rows


def _aggregate(rows: list[dict]) -> dict[str, dict[str, int]]:
    contacted: dict[str, set[str]] = {}
    replied: dict[str, set[str]] = {}
    for row in rows:
        opp = row.get("opportunity_id")
        dev = row.get("device_id")
        status = row.get("to_status")
        if not opp or not dev:
            continue
        if status in CONTACT_STATUSES:
            contacted.setdefault(opp, set()).add(dev)
        if status in REPLIED_STATUSES:
            replied.setdefault(opp, set()).add(dev)
    return {
        opp: {"contacted_n": len(devs), "replied_n": len(replied.get(opp, ()))}
        for opp, devs in contacted.items()
        if len(devs) >= RESPONSIVENESS_MIN_N
    }


async def signals_map() -> dict[str, dict[str, int]]:
    global _cache, _cache_time
    now = time.time()
    if _cache is not None and now - _cache_time < _CACHE_TTL:
        return _cache

    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not key:
        return {}

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    try:
        rows = await _fetch_status_rows(supabase_url, headers)
    except Exception as exc:
        logger.warning("responsiveness fetch failed: %s", type(exc).__name__)
        _cache = _cache or {}
        _cache_time = now - _CACHE_TTL + _FAILURE_BACKOFF
        return _cache

    _cache = _aggregate(rows)
    _cache_time = now
    return _cache


@router.get("/opportunities/responsiveness")
async def get_responsiveness():
    """Public boundary: positive signals only.

    Zero-reply aggregates stay server-side — sparse self-reported tracking
    data must not become a public "no one heard back here" judgment on a
    named professor's lab.
    """
    signals = {
        opp: sig
        for opp, sig in (await signals_map()).items()
        if sig.get("replied_n", 0) >= 1
    }
    return {"signals": signals, "min_n": RESPONSIVENESS_MIN_N}
