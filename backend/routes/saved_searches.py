"""Cron route for refreshing saved-search match-sets server-side.

Invoked by .github/workflows/saved-searches-refresh.yml (GH Actions
schedule, plus workflow_dispatch). Walks every row in saved_searches,
recomputes the current match-set against opportunities.json, and writes
back last_run_at + last_result_ids + new_match_ids.

Auth: same Bearer CRON_SECRET pattern as push.py /cron/reminders.
Supabase access: SERVICE_ROLE_KEY (bypasses RLS — required since cron
operates on every user's rows).

This route returns quickly even with thousands of saved searches because
the filter is a pure Python pass over the in-memory opportunities list;
the per-row supabase PATCH dominates wall time and is the obvious place
to add concurrency if scale ever requires it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Header

from backend.data_loader import load_opportunities
from backend.routes.push import _required_env, _verify_cron_secret
from src.saved_searches.filter import matching_ids

router = APIRouter()


SUPABASE_BATCH_LIMIT = 1000


@router.get("/cron/saved-searches/refresh")
async def saved_searches_refresh(authorization: str | None = Header(default=None)):
    """Re-run every saved search against current opportunities.json.

    For each saved_searches row:
      - compute current match IDs (filter + query text search)
      - diff against prior last_result_ids to find new matches
      - PATCH the row with last_run_at / last_result_ids / new_match_ids
    """
    _verify_cron_secret(authorization)

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "skipped", "reason": "supabase env not configured", "missing": missing}
    env = env_result

    try:
        import httpx
    except ImportError:
        return {"status": "skipped", "reason": "httpx not installed"}

    opportunities = load_opportunities()
    if not opportunities:
        return {"status": "skipped", "reason": "no opportunities loaded"}

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    processed = 0
    total_new_matches = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        list_resp = await client.get(
            f"{supabase_url}/rest/v1/saved_searches",
            params={
                "select": "id,filters_json,query,last_result_ids",
                "limit": str(SUPABASE_BATCH_LIMIT),
                "order": "last_run_at.asc.nullsfirst",
            },
            headers=headers,
        )
        list_resp.raise_for_status()
        rows = list_resp.json()
        if not rows:
            return {"status": "ok", "processed": 0, "new_matches": 0}

        now_iso = datetime.now(UTC).isoformat()

        for row in rows:
            try:
                filters = row.get("filters_json") or {}
                query = row.get("query") or ""
                prior_ids = set(row.get("last_result_ids") or [])

                current_ids = matching_ids(opportunities, filters, query)
                new_ids = [oid for oid in current_ids if oid not in prior_ids]
                total_new_matches += len(new_ids)

                patch_body = {
                    "last_run_at": now_iso,
                    "last_result_ids": current_ids,
                    "new_match_ids": new_ids,
                }
                patch_resp = await client.patch(
                    f"{supabase_url}/rest/v1/saved_searches",
                    params={"id": f"eq.{row['id']}"},
                    headers=headers,
                    json=patch_body,
                )
                patch_resp.raise_for_status()
                processed += 1
            except Exception as e:  # noqa: BLE001 — keep cron iterating
                errors.append(f"{row.get('id', '?')}: {type(e).__name__}: {e}")

    return {
        "status": "ok" if not errors else "partial",
        "processed": processed,
        "new_matches": total_new_matches,
        "errors": errors[:10],
        "timestamp": datetime.now(UTC).isoformat(),
    }
