"""Admin endpoints for data-quality monitoring + ops actions.

Protected by the ADMIN_TOKEN env var, sent via the X-Admin-Token header
only. The legacy ?token= query param was removed — query strings leak
into referrer headers, access logs, and browser history.

If ADMIN_TOKEN is unset, all admin requests return 503 (admin disabled).
"""

from __future__ import annotations

import hmac
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException, Query

from backend.data_loader import load_opportunities
from backend.routes.push import _required_env
from backend.routes.saved_searches import _parse_iso_ts

router = APIRouter()

_PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
_HISTORY_PATH = _PROCESSED_DIR / "admin_history.jsonl"
_COLLECTOR_STATUS_PATH = _PROCESSED_DIR / "collector_status.json"
_COLLECTOR_HISTORY_PATH = _PROCESSED_DIR / "collector_status_history.jsonl"
_HISTORY_MAX_ENTRIES = 365

# Cache for the data-quality endpoint. Scanning 1741 opportunities takes
# ~80-120ms; cached it's sub-millisecond. TTL set to 5 minutes so admin
# refresh reflects changes within a reasonable window but polling is cheap.
_CACHE_TTL_SECONDS = 300
_cache: dict = {"snapshot": None, "built_at": 0.0}


def _opportunities_mtime() -> str | None:
    path = Path(__file__).resolve().parents[2] / "data" / "processed" / "opportunities.json"
    if not path.exists():
        return None
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return ts.isoformat()

_UNSORTED_SENTINELS = frozenset({"unsorted", "uncategorized", "misc"})


def _is_unsorted(keywords) -> bool:
    if not keywords:
        return True
    cleaned = [k for k in keywords if isinstance(k, str) and k.strip()]
    if not cleaned:
        return True
    return all(k.strip().lower() in _UNSORTED_SENTINELS for k in cleaned)


def _authenticate(token_header: str | None) -> None:
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin endpoints disabled (ADMIN_TOKEN unset)")
    provided = (token_header or "").encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    if not provided or not hmac.compare_digest(provided, expected_bytes):
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.get("/admin/data-quality")
async def data_quality(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    force: bool = Query(default=False, description="Bypass cache"),
):
    _authenticate(x_admin_token)

    now = time.time()
    if not force and _cache["snapshot"] and (now - _cache["built_at"]) < _CACHE_TTL_SECONDS:
        cached = dict(_cache["snapshot"])
        cached["cache_age_seconds"] = round(now - _cache["built_at"], 1)
        return cached

    opps = load_opportunities()
    total = len(opps)

    by_source: dict[str, dict] = {}
    global_counts = Counter(
        empty_majors=0, empty_keywords=0, empty_description=0,
        short_description=0, missing_deadline=0, rolling_deadline=0,
        missing_skills=0, past_deadline=0, stale_verify=0,
        flagged_inactive=0,
    )

    today = datetime.now(UTC).date()
    for o in opps:
        src = o.get("source", "?")
        b = by_source.setdefault(src, Counter(total=0))
        b["total"] += 1

        if o.get("metadata", {}).get("is_active") is False:
            b["flagged_inactive"] += 1
            global_counts["flagged_inactive"] += 1

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
        if o.get("deadline"):
            try:
                dl = datetime.fromisoformat(str(o["deadline"])[:10]).date()
                if dl < today:
                    b["past_deadline"] += 1
                    global_counts["past_deadline"] += 1
            except (ValueError, TypeError):
                pass
        elif o.get("is_rolling"):
            b["rolling_deadline"] += 1
            global_counts["rolling_deadline"] += 1
        else:
            b["missing_deadline"] += 1
            global_counts["missing_deadline"] += 1
        if not (elig.get("skills_required") or []):
            b["missing_skills"] += 1
            global_counts["missing_skills"] += 1
        last_verified = (o.get("metadata") or {}).get("last_verified")
        if last_verified:
            try:
                lv = datetime.fromisoformat(str(last_verified).replace("Z", "+00:00"))
                if (datetime.now(UTC) - lv).days > 60:
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
        if o.get("metadata", {}).get("is_active") is False:
            continue
        elig = o.get("eligibility", {}) or {}
        missing_fields: list[str] = []
        if not (elig.get("majors") or []):
            missing_fields.append("empty_majors")
        if _is_unsorted(o.get("keywords") or []):
            missing_fields.append("empty_keywords")
        if not (o.get("description_raw") or o.get("description_clean")):
            missing_fields.append("empty_description")
        if not o.get("deadline") and not o.get("is_rolling"):
            missing_fields.append("missing_deadline")
        if not (elig.get("skills_required") or []):
            missing_fields.append("missing_skills")
        if len(missing_fields) >= 3:
            worst_fields.append({
                "id": o.get("id"),
                "title": (o.get("title") or "")[:80],
                "source": o.get("source"),
                "missing_count": len(missing_fields),
                "missing_fields": missing_fields,
                "url": o.get("url"),
            })
    worst_fields.sort(key=lambda x: x["missing_count"], reverse=True)

    generated_at = datetime.now(UTC)
    data_mtime = _opportunities_mtime()
    snapshot = {
        "total": total,
        "global": dict(global_counts),
        "sources": sources_list,
        "worst_fields": worst_fields[:20],
        "generated_at": generated_at.isoformat(),
        "data_updated_at": data_mtime,
        "cache_age_seconds": 0,
    }
    _cache["snapshot"] = snapshot
    _cache["built_at"] = now

    _append_history_snapshot(generated_at, total, dict(global_counts))

    return snapshot


def _append_history_snapshot(ts: datetime, total: int, global_counts: dict) -> None:
    """Append a compact snapshot to history file. Skips if the last
    entry was written less than an hour ago (prevents noise on refresh).
    """
    try:
        if _HISTORY_PATH.exists():
            with _HISTORY_PATH.open("rb") as f:
                try:
                    f.seek(-2048, 2)
                except OSError:
                    f.seek(0)
                tail = f.read().decode("utf-8", errors="ignore").splitlines()
                last = tail[-1] if tail else ""
            if last:
                try:
                    last_obj = json.loads(last)
                    last_ts = datetime.fromisoformat(last_obj.get("t", "").replace("Z", "+00:00"))
                    if (ts - last_ts).total_seconds() < 3600:
                        return
                except (json.JSONDecodeError, ValueError):
                    pass

        entry = {"t": ts.isoformat(), "total": total, **global_counts}
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


@router.get("/admin/data-quality/history")
async def data_quality_history(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    limit: int = Query(default=30, ge=1, le=365),
):
    _authenticate(x_admin_token)

    if not _HISTORY_PATH.exists():
        return {"history": []}

    entries = []
    with _HISTORY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return {"history": entries[-limit:]}


@router.get("/admin/collector-status")
async def collector_status(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Per-collector last-run health, written by refresh_all.py.

    Reads data/processed/collector_status.json. Returns an empty structure
    if the file doesn't exist yet (first deploy / refresh hasn't run).
    """
    _authenticate(x_admin_token)

    if not _COLLECTOR_STATUS_PATH.exists():
        return {"sources": [], "last_run_at": None}

    try:
        with _COLLECTOR_STATUS_PATH.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"sources": [], "last_run_at": None}

    sources_obj = payload.get("sources", {}) or {}
    sources_list = []
    for name, info in sources_obj.items():
        if not isinstance(info, dict):
            continue
        sources_list.append({
            "source": name,
            "status": info.get("status", "unknown"),
            "fetched": info.get("fetched"),
            "new": info.get("new"),
            "updated": info.get("updated"),
            "error": info.get("error"),
            "deep": info.get("deep"),
        })
    sources_list.sort(key=lambda x: x["source"])
    return {
        "sources": sources_list,
        "last_run_at": payload.get("timestamp"),
        "duration_seconds": payload.get("duration_seconds"),
        "total_in_file": payload.get("total_in_file"),
    }


@router.get("/admin/collector-status/history")
async def collector_status_history(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    limit: int = Query(default=30, ge=1, le=200),
):
    """Per-source freshness trend, written by refresh_all.write_status.

    Returns the last ``limit`` entries from collector_status_history.jsonl
    (newest last). Each row carries the timestamp, totals, and per-source
    counts so the admin dashboard can chart "which source has been failing
    most weeks" without re-scanning opportunities.json.
    """
    _authenticate(x_admin_token)

    if not _COLLECTOR_HISTORY_PATH.exists():
        return {"entries": [], "count": 0}

    entries: list[dict] = []
    try:
        with _COLLECTOR_HISTORY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return {"entries": [], "count": 0}

    return {"entries": entries[-limit:], "count": len(entries)}


_HEALTH_THRESHOLDS = {
    "data_age_warn_hours": 96,
    "data_age_alert_hours": 192,
    "metric_pct_jump": 50.0,
    "metric_min_delta": 30,
}


@router.get("/admin/health-check")
async def health_check(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Compute alert-worthy data-quality regressions vs ~7 days ago.

    Returns ok=true with empty alerts when nothing has crossed thresholds.
    Wired into the daily-reminders cron so an operator gets paged when
    a scrape silently degrades.
    """
    _authenticate(x_admin_token)

    alerts: list[dict] = []

    data_mtime = _opportunities_mtime()
    if data_mtime:
        try:
            data_age_hours = (datetime.now(UTC) - datetime.fromisoformat(data_mtime)).total_seconds() / 3600
            if data_age_hours >= _HEALTH_THRESHOLDS["data_age_alert_hours"]:
                alerts.append({
                    "level": "alert",
                    "kind": "stale_data",
                    "message": f"opportunities.json hasn't been refreshed in {int(data_age_hours)}h — Mon/Thu cron may have failed",
                })
            elif data_age_hours >= _HEALTH_THRESHOLDS["data_age_warn_hours"]:
                alerts.append({
                    "level": "warn",
                    "kind": "stale_data",
                    "message": f"opportunities.json is {int(data_age_hours)}h old — past expected refresh window",
                })
        except (ValueError, TypeError):
            pass

    history = _read_history()
    if len(history) >= 2:
        latest = history[-1]
        prior = _find_baseline(history, days_ago=7)
        for metric in ("empty_majors", "empty_keywords", "missing_deadline", "flagged_inactive"):
            cur = int(latest.get(metric) or 0)
            base = int(prior.get(metric) or 0)
            delta = cur - base
            if base > 0:
                pct_jump = (delta / base) * 100
            else:
                pct_jump = 100.0 if delta > 0 else 0.0
            if delta >= _HEALTH_THRESHOLDS["metric_min_delta"] and pct_jump >= _HEALTH_THRESHOLDS["metric_pct_jump"]:
                alerts.append({
                    "level": "alert",
                    "kind": "metric_regression",
                    "metric": metric,
                    "current": cur,
                    "baseline": base,
                    "delta": delta,
                    "pct_jump": round(pct_jump, 1),
                    "message": f"{metric} jumped from {base} to {cur} (+{delta}, +{pct_jump:.0f}%)",
                })

    return {
        "ok": not any(a["level"] == "alert" for a in alerts),
        "alerts": alerts,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def _read_history() -> list[dict]:
    if not _HISTORY_PATH.exists():
        return []
    out: list[dict] = []
    with _HISTORY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _find_baseline(history: list[dict], days_ago: int) -> dict:
    """Pick the snapshot closest to (now - days_ago) without going past it."""
    target = datetime.now(UTC) - timedelta(days=days_ago)
    best = history[0]
    for entry in history:
        try:
            t = datetime.fromisoformat(str(entry.get("t", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if t <= target:
            best = entry
        else:
            break
    return best


_SAVED_SEARCH_STALE_HOURS = 48
_SAVED_SEARCH_FETCH_LIMIT = 1000


@router.get("/admin/saved-search-health")
async def saved_search_health(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Saved-search refresh-cron + email-digest health rollup.

    Aggregates the per-row run state (migration 011) and digest state (013)
    from saved_searches so the dead-cron case is visible on the admin
    dashboard without Supabase console access. Reports env *presence* only
    (resend_configured) — never the values. When Supabase env is missing
    (local dev) returns status "unconfigured" instead of 500, mirroring the
    cron routes' skip behaviour.
    """
    _authenticate(x_admin_token)

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "unconfigured", "missing": missing}
    env = env_result

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{supabase_url}/rest/v1/saved_searches",
                params={
                    "select": "id,last_run_at,digest_opt_in,digest_unsubscribed_at,last_digest_sent_at",
                    "limit": str(_SAVED_SEARCH_FETCH_LIMIT),
                },
                headers=headers,
            )
            resp.raise_for_status()
            rows = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e

    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(hours=_SAVED_SEARCH_STALE_HOURS)
    opted_in = 0
    never_run = 0
    stale = 0
    opted_in_never_sent = 0
    last_run_max: datetime | None = None
    last_digest_max: datetime | None = None

    for row in rows:
        run_at = _parse_iso_ts(row.get("last_run_at"))
        if run_at is None:
            never_run += 1
        else:
            if last_run_max is None or run_at > last_run_max:
                last_run_max = run_at
            if run_at < stale_cutoff:
                stale += 1
        sent_at = _parse_iso_ts(row.get("last_digest_sent_at"))
        if sent_at is not None and (last_digest_max is None or sent_at > last_digest_max):
            last_digest_max = sent_at
        if row.get("digest_opt_in") and not row.get("digest_unsubscribed_at"):
            opted_in += 1
            if sent_at is None:
                opted_in_never_sent += 1

    return {
        "status": "ok",
        "searches": {"total": len(rows), "digest_opt_in": opted_in},
        "refresh": {
            "last_run_at": last_run_max.isoformat() if last_run_max else None,
            "never_run": never_run,
            "stale_over_48h": stale,
        },
        "digest": {
            "last_sent_at": last_digest_max.isoformat() if last_digest_max else None,
            "opted_in_never_sent": opted_in_never_sent,
        },
        "resend_configured": bool(
            os.environ.get("RESEND_API_KEY") and os.environ.get("RESEND_FROM_EMAIL")
        ),
        "generated_at": now.isoformat(),
    }


@router.post("/admin/trigger-refresh")
async def trigger_refresh(
    mode: str = Query(default="quick", pattern="^(quick|deep)$"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Dispatch the refresh-data.yml workflow on GitHub Actions.

    Requires GITHUB_REFRESH_PAT (fine-grained PAT with actions:write on the
    repo) and GITHUB_REPO (e.g. 'EricXu-0805/opportunity-filter-engine').
    Returns 503 when either is unset so the UI can render a setup hint.
    """
    _authenticate(x_admin_token)

    pat = os.environ.get("GITHUB_REFRESH_PAT")
    repo = os.environ.get("GITHUB_REPO", "EricXu-0805/opportunity-filter-engine")
    if not pat:
        raise HTTPException(
            status_code=503,
            detail="Refresh trigger disabled (set GITHUB_REFRESH_PAT on the backend)",
        )

    workflow_url = f"https://api.github.com/repos/{repo}/actions/workflows/refresh-data.yml/dispatches"
    payload = {"ref": "main", "inputs": {"deep": "true" if mode == "deep" else "false"}}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                workflow_url,
                json=payload,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {pat}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"GitHub API unreachable: {e}") from e

    if resp.status_code == 204:
        return {
            "ok": True,
            "mode": mode,
            "dispatched_at": datetime.now(UTC).isoformat(),
            "workflow": "refresh-data.yml",
            "note": "Watch GitHub Actions tab for run status; commits land on main when complete.",
        }

    detail = resp.text[:300] if resp.text else f"GitHub returned {resp.status_code}"
    raise HTTPException(status_code=resp.status_code, detail=detail)


@router.get("/admin/feedback")
async def feedback_inbox(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    limit: int = Query(default=50, ge=1, le=200),
    since_hours: int | None = Query(default=None, ge=1, le=720),
):
    """User feedback inbox + match-feedback (thumbs) summary.

    The feedback / match_feedback tables are INSERT-only under RLS (clients
    can never read them back) — this endpoint is the operator's read path,
    via the service-role key. `since_hours` narrows the inbox window so the
    daily cron can ask "anything new in the last 24h?".
    """
    _authenticate(x_admin_token)

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "skipped", "reason": "supabase env not configured", "missing": missing}
    env = env_result

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
    }
    params = {
        "select": "id,created_at,message,email,props",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if since_hours is not None:
        cutoff = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()
        params["created_at"] = f"gte.{cutoff}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            fb_resp = await client.get(
                f"{supabase_url}/rest/v1/feedback", params=params, headers=headers
            )
            fb_resp.raise_for_status()
            entries = fb_resp.json()

            mf_resp = await client.get(
                f"{supabase_url}/rest/v1/match_feedback",
                params={
                    "select": "opportunity_id,verdict,created_at",
                    "order": "created_at.desc",
                    "limit": "1000",
                },
                headers=headers,
            )
            mf_resp.raise_for_status()
            thumbs = mf_resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e

    week_ago = datetime.now(UTC) - timedelta(days=7)
    up = sum(1 for t in thumbs if t.get("verdict") == "up")
    down = sum(1 for t in thumbs if t.get("verdict") == "down")
    recent = [t for t in thumbs if (_parse_iso_ts(t.get("created_at")) or week_ago) >= week_ago]
    titles = {o.get("id"): o.get("title") for o in load_opportunities()}
    down_counts = Counter(
        t["opportunity_id"] for t in thumbs if t.get("verdict") == "down" and t.get("opportunity_id")
    )
    top_downvoted = [
        {"opportunity_id": oid, "downs": n, "title": titles.get(oid)}
        for oid, n in down_counts.most_common(10)
    ]

    return {
        "status": "ok",
        "entries": entries,
        "count": len(entries),
        "match_feedback": {
            "up": up,
            "down": down,
            "up_7d": sum(1 for t in recent if t.get("verdict") == "up"),
            "down_7d": sum(1 for t in recent if t.get("verdict") == "down"),
            "sample_size": len(thumbs),
            "top_downvoted": top_downvoted,
        },
    }
