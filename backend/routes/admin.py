"""Admin endpoints for data-quality monitoring + ops actions.

Protected by the ADMIN_TOKEN env var, sent via the X-Admin-Token header
only. The legacy ?token= query param was removed — query strings leak
into referrer headers, access logs, and browser history.

If ADMIN_TOKEN is unset, all admin requests return 503 (admin disabled).

Operator attribution: routes may additionally read an X-Admin-Actor header
(see ``require_admin``). It is a SELF-DECLARED label, not a second factor —
every operator shares the one ADMIN_TOKEN.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.data_loader import load_opportunities
from backend.lib.corpus_freshness import (
    CORPUS_FRESHNESS_STALE_HOURS,
    CORPUS_FRESHNESS_WARN_HOURS,
)
from backend.lib.corpus_freshness import corpus_last_updated_at as _opportunities_mtime
from backend.routes.email import _enforce_recipient_quota, _html_escape, _send_via_resend
from backend.routes.push import _required_env
from backend.routes.saved_searches import _parse_iso_ts
from src.matcher.feedback_learning import analyze_votes

router = APIRouter()
logger = logging.getLogger(__name__)

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


# The corpus-freshness reader (W15's fix for the gitignored work file) now
# lives in backend/lib/corpus_freshness.py, shared with the public stats
# endpoint so the two surfaces cannot report different ages; imported above
# under its original name because this module and its tests call it.

_UNSORTED_SENTINELS = frozenset({"unsorted", "uncategorized", "misc"})


def _is_unsorted(keywords) -> bool:
    if not keywords:
        return True
    cleaned = [k for k in keywords if isinstance(k, str) and k.strip()]
    if not cleaned:
        return True
    return all(k.strip().lower() in _UNSORTED_SENTINELS for k in cleaned)


def _authenticate(token_header: str | None) -> None:
    """Constant-time check of the shared ADMIN_TOKEN; 503 when it is unset.

    Failures are logged (never with token material — only whether a token was
    absent or wrong) so a credential-stuffing run against the admin surface
    leaves a trace instead of being silently absorbed into 401s.

    Kept as a plain function because orders.py imports it; new routes should
    prefer the ``require_admin`` dependency below, which also resolves the
    operator label.
    """
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        logger.warning("Admin request refused: ADMIN_TOKEN is unset (admin surface disabled)")
        raise HTTPException(status_code=503, detail="Admin endpoints disabled (ADMIN_TOKEN unset)")
    provided = (token_header or "").encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    if not provided or not hmac.compare_digest(provided, expected_bytes):
        logger.warning(
            "Admin authentication failed: X-Admin-Token %s",
            "missing" if not provided else "did not match",
        )
        raise HTTPException(status_code=401, detail="Invalid admin token")


# Operator labels are opaque short identifiers ("ops:alice", "eric.x"). Anything
# outside this alphabet is dropped rather than rejected: the label is decoration
# on an audit row, and a 400 over a stray space would block a real mutation.
_ACTOR_DISALLOWED_RE = re.compile(r"[^A-Za-z0-9:._-]+")
_ACTOR_MAX_LEN = 64
DEFAULT_ACTOR = "operator"


def _sanitize_actor(raw: str | None) -> str:
    """Normalize an X-Admin-Actor header to ``[A-Za-z0-9:._-]{1,64}``."""
    cleaned = _ACTOR_DISALLOWED_RE.sub("", (raw or "").strip())[:_ACTOR_MAX_LEN]
    return cleaned or DEFAULT_ACTOR


def _sanitize_label(raw: str | None) -> str | None:
    """Same alphabet as the actor, but empty means "no label" (unassigned)."""
    cleaned = _ACTOR_DISALLOWED_RE.sub("", (raw or "").strip())[:_ACTOR_MAX_LEN]
    return cleaned or None


def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: str | None = Header(default=None, alias="X-Admin-Actor"),
) -> str:
    """Authenticate an admin request and return the operator's claimed label.

    THE ACTOR IS SELF-DECLARED, NOT AUTHENTICATED. Every operator holds the
    same ADMIN_TOKEN, so X-Admin-Actor is an unverified string that anyone with
    the token can set to anything — including another operator's label. It
    exists so the feedback_events trail can answer "who says they did this",
    which is useful for coordinating a small ops team, and it is worthless as
    evidence in a dispute. Real attribution needs per-operator credentials
    (documented residual, same one migration 026 records).

    Defaults to ``operator`` when the header is absent or sanitizes to empty.
    """
    _authenticate(x_admin_token)
    return _sanitize_actor(x_admin_actor)


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
    # Imported, not literal: these used to be a local 96/192 while the docs and
    # the admin dashboard's own FreshnessBanner both said 72/96, so the alert
    # that pages an operator fired a full extra cron cycle after the UI had
    # already turned red. backend/lib/corpus_freshness now owns the boundary for
    # this surface, /api/ready, and the frontend banner alike. The keys keep
    # their warn/alert names because the alert-level logic below reads them.
    "data_age_warn_hours": CORPUS_FRESHNESS_WARN_HOURS,
    "data_age_alert_hours": CORPUS_FRESHNESS_STALE_HOURS,
    "metric_pct_jump": 50.0,
    "metric_min_delta": 30,
    # Render instance has 2 GB; the corpus + TF-IDF fit grow with every school,
    # so surface RSS before the OOM killer does. Warn leaves headroom to plan,
    # alert means stop expanding and slim.
    "memory_warn_mb": 1400,
    "memory_alert_mb": 1700,
}


def _process_rss_mb() -> float | None:
    """Resident set size of this process in MiB. /proc on Linux (Render);
    ru_maxrss fallback elsewhere (peak, close enough for alerting)."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)  # kB -> MiB
    except (OSError, ValueError, IndexError):
        pass
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is KiB on Linux, bytes on macOS
        return round(rss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    except Exception:
        return None


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
    prior = _find_baseline(history, days_ago=7) if len(history) >= 2 else None
    if prior is None and history:
        # Honest about the gap rather than silently skipping comparison: with
        # no usable baseline the regression detector is blind, and an operator
        # reading a clean board deserves to know that (W15).
        alerts.append({
            "level": "warn",
            "kind": "baseline_unavailable",
            "message": (
                "No data-quality baseline within "
                f"{_BASELINE_MAX_AGE_DAYS}d — regression alerts are inactive "
                "(admin_history resets on deploy)"
            ),
        })
    if prior is not None:
        latest = history[-1]
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

    memory_mb = _process_rss_mb()
    if memory_mb is not None:
        if memory_mb >= _HEALTH_THRESHOLDS["memory_alert_mb"]:
            alerts.append({
                "level": "alert",
                "kind": "memory",
                "message": f"backend RSS {memory_mb:.0f} MiB — near the 2 GB instance limit; stop expanding the corpus and slim",
            })
        elif memory_mb >= _HEALTH_THRESHOLDS["memory_warn_mb"]:
            alerts.append({
                "level": "warn",
                "kind": "memory",
                "message": f"backend RSS {memory_mb:.0f} MiB — plan memory headroom before onboarding more schools",
            })

    return {
        "ok": not any(a["level"] == "alert" for a in alerts),
        "alerts": alerts,
        "memory_mb": memory_mb,
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


# A baseline older than this is not a baseline, it is a fossil. admin_history
# lives on Render's ephemeral disk and resets to the committed file on every
# deploy, so the "7 days ago" pick could land on a months-old snapshot from a
# corpus 50x smaller — every metric then reads as a catastrophic regression and
# the daily operator email cries wolf forever. Beyond this age we report no
# baseline instead of a false one (W15).
_BASELINE_MAX_AGE_DAYS = 21


def _find_baseline(history: list[dict], days_ago: int) -> dict | None:
    """Snapshot closest to (now - days_ago) without going past it.

    Returns None when nothing in the retained history is recent enough to be a
    meaningful comparison — callers must treat that as "no baseline", never as
    a zero baseline.
    """
    now = datetime.now(UTC)
    target = now - timedelta(days=days_ago)
    floor = now - timedelta(days=_BASELINE_MAX_AGE_DAYS)
    best: dict | None = None
    for entry in history:
        try:
            t = datetime.fromisoformat(str(entry.get("t", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        if t < floor:
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
        async with httpx.AsyncClient(timeout=15.0, trust_env=False, follow_redirects=False) as client:
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
    """Fail closed while target-only refresh publication is not authorized."""
    _authenticate(x_admin_token)
    raise HTTPException(
        status_code=503,
        detail=(
            "Data refresh publication is paused pending explicit authorization "
            "of the target-only publisher."
        ),
    )


# ---------------------------------------------------------------------------
# Feedback tickets (migration 026)
# ---------------------------------------------------------------------------
# 016 shipped feedback as an insert-only inbox an operator could read and
# nothing else. 026 gives each submission a lifecycle; these routes are the
# ONLY sanctioned mutation path (RLS grants users insert+select on their own
# rows and no update at all), and every accepted mutation appends to the
# append-only feedback_events log.

FEEDBACK_STATUSES = ("open", "triaged", "in_progress", "waiting_on_user", "resolved", "closed")
FEEDBACK_PRIORITIES = ("low", "normal", "high", "urgent")
FEEDBACK_RESOLUTIONS = (
    "fixed", "expected_behavior", "duplicate", "data_corrected",
    "unable_to_reproduce", "wont_fix", "user_guidance_provided",
)
# A ticket in one of these states carries a handling decision (DB CHECK
# feedback_resolved_has_decision enforces the same thing as a backstop).
TERMINAL_STATUSES = frozenset({"resolved", "closed"})

# Explicit column list, not `*`: props/message can be large and the operator UI
# should get a stable shape. Mirrors the columns migration 026 adds.
_TICKET_COLUMNS = (
    "id,created_at,updated_at,category,subject,message,email,props,"
    "status,priority,assigned_to,"
    "admin_reply,admin_reply_at,admin_reply_by,admin_reply_delivery,"
    "resolution,resolution_note,resolved_by,resolved_at,closed_at"
)
_EVENT_COLUMNS = "id,ticket_id,actor,action,from_value,to_value,note,created_at"
# Audit values are labels and short notes, not payloads; keep one long message
# from bloating the log.
_EVENT_VALUE_MAX = 500

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _service_role_env() -> tuple[str, dict]:
    """(base_url, service-role headers) or 503 when Supabase env is unset.

    The ticket routes 503 rather than returning the inbox's ``status:skipped``
    shape: a mutation that cannot reach storage must not look like a success.
    """
    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        raise HTTPException(
            status_code=503,
            detail=f"Feedback storage not configured (missing: {', '.join(missing)})",
        )
    env = env_result
    return env["SUPABASE_URL"].rstrip("/"), {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
    }


def _split_csv(values: list[str] | None) -> list[str]:
    """Flatten repeated ?k=a&k=b and CSV ?k=a,b into one list."""
    out: list[str] = []
    for raw in values or []:
        out.extend(part.strip() for part in str(raw).split(",") if part.strip())
    return out


def _validate_enum_filter(values: list[str], allowed: tuple[str, ...], field: str) -> set[str] | None:
    """Validated filter set, or None when no filter was supplied.

    Unknown values 400 here rather than reaching PostgREST, where an invalid
    enum surfaces as an opaque upstream error.
    """
    if not values:
        return None
    unknown = sorted({v for v in values if v not in allowed})
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown {field}: {', '.join(unknown)} (allowed: {', '.join(allowed)})",
        )
    return set(values)


def _require_enum(value: str | None, allowed: tuple[str, ...], field: str) -> str:
    if value is None:
        raise HTTPException(status_code=400, detail=f"{field} cannot be null")
    if value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown {field} '{value}' (allowed: {', '.join(allowed)})",
        )
    return value


def _event_row(
    ticket_id: str, actor: str, action: str,
    from_value: str | None = None, to_value: str | None = None, note: str | None = None,
) -> dict:
    def _trim(v: str | None) -> str | None:
        return None if v is None else str(v)[:_EVENT_VALUE_MAX]

    return {
        "ticket_id": ticket_id,
        "actor": actor,
        "action": action,
        "from_value": _trim(from_value),
        "to_value": _trim(to_value),
        "note": _trim(note),
    }


async def _fetch_ticket(client: httpx.AsyncClient, supabase_url: str, headers: dict, ticket_id: str) -> dict:
    """One ticket by id, or 404.

    A malformed id is 404 too: it identifies no ticket, and letting PostgREST
    reject the uuid cast would leak a storage-layer 400 to the operator.
    """
    if not _UUID_RE.match(ticket_id or ""):
        raise HTTPException(status_code=404, detail="Ticket not found")
    resp = await client.get(
        f"{supabase_url}/rest/v1/feedback",
        params={"id": f"eq.{ticket_id}", "select": _TICKET_COLUMNS, "limit": "1"},
        headers=headers,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return rows[0]


async def _patch_ticket(
    client: httpx.AsyncClient, supabase_url: str, headers: dict, ticket_id: str, updates: dict,
) -> dict:
    resp = await client.patch(
        f"{supabase_url}/rest/v1/feedback",
        params={"id": f"eq.{ticket_id}", "select": _TICKET_COLUMNS},
        headers={**headers, "Prefer": "return=representation"},
        json=updates,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not isinstance(rows, list) or not rows:
        # PostgREST answers 200 + [] when the predicate matched nothing (the
        # row was deleted mid-request). Never report that as a successful edit.
        raise HTTPException(status_code=404, detail="Ticket not found")
    return rows[0]


async def _log_events(
    client: httpx.AsyncClient, supabase_url: str, headers: dict, rows: list[dict],
) -> str | None:
    """Append audit rows; return an error string instead of raising.

    Deliberately called AFTER the ticket mutation lands. Logging first would
    risk an event asserting a change that then failed — a fabricated audit
    trail, which is worse than a missing entry. The residual (mutation applied,
    log write failed) is surfaced to the caller as ``audit_log_error`` and
    logged, never swallowed.
    """
    if not rows:
        return None
    try:
        resp = await client.post(
            f"{supabase_url}/rest/v1/feedback_events",
            headers={**headers, "Prefer": "return=minimal"},
            json=rows,
        )
        status = getattr(resp, "status_code", 200)
        if status >= 400:
            body = str(getattr(resp, "text", ""))[:200]
            logger.warning("feedback_events insert failed (%s): %s", status, body)
            return f"audit log write failed ({status})"
    except httpx.HTTPError as e:
        logger.warning("feedback_events insert unreachable: %s", e)
        return f"audit log write failed ({type(e).__name__})"
    return None


def _render_reply_email(ticket: dict, reply: str) -> tuple[str, str, str]:
    subj = (ticket.get("subject") or "").strip()
    subject = f"Re: {subj}" if subj else "Re: your JoinALab feedback"
    original = (ticket.get("message") or "").strip()
    quoted_html = (
        f'<div style="margin-top:24px;padding:12px 14px;background:#f9fafb;'
        f'border-left:3px solid #e5e7eb;font-size:13px;color:#6b7280;white-space:pre-wrap">'
        f"{_html_escape(original[:2000])}</div>"
        if original else ""
    )
    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white">
  <tr><td style="height:4px;background:#4f46e5;font-size:0;line-height:0">&nbsp;</td></tr>
  <tr><td style="padding:32px 28px">
    <div style="font-size:22px;font-weight:700;color:#4f46e5;letter-spacing:-0.5px">JoinALab</div>
    <h1 style="font-size:20px;margin:20px 0 6px;color:#111827">{_html_escape(subject)}</h1>
    <div style="font-size:14px;color:#374151;white-space:pre-wrap">{_html_escape(reply)}</div>
    <div style="margin-top:20px;font-size:12px;color:#9ca3af">You wrote:</div>
    {quoted_html}
  </td></tr>
</table>
</body></html>"""
    text = f"{subject}\n\n{reply}\n"
    if original:
        text += "\n--- You wrote ---\n" + original[:2000] + "\n"
    return subject, html, text


class FeedbackPatchRequest(BaseModel):
    """Ticket mutation body. Unset fields are left alone; ``assigned_to: null``
    explicitly unassigns (model_fields_set distinguishes the two)."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    priority: str | None = None
    assigned_to: str | None = None
    resolution: str | None = None
    resolution_note: str | None = Field(default=None, max_length=2000)


class FeedbackReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, max_length=5000)
    deliver: bool = False

    @field_validator("reply")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("reply cannot be blank")
        return cleaned


@router.get("/admin/feedback")
async def feedback_inbox(
    actor: str = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    since_hours: int | None = Query(default=None, ge=1, le=720),
    status: list[str] | None = Query(
        default=None, description="Repeatable or CSV, e.g. ?status=open&status=triaged"
    ),
    priority: list[str] | None = Query(default=None, description="Repeatable or CSV"),
    assigned_to: str | None = Query(default=None, max_length=64),
    unresolved_only: bool = Query(
        default=False, description="Exclude resolved/closed tickets"
    ),
):
    """User feedback inbox + match-feedback (thumbs) summary.

    The feedback / match_feedback tables are operator-read-only under RLS
    (clients may insert, and read back only their own rows) — this endpoint is
    the operator's read path, via the service-role key. `since_hours` narrows
    the inbox window so the daily cron can ask "anything new in the last 24h?";
    the status/priority/assigned_to/unresolved_only filters drive triage views.
    """
    wanted_status = _validate_enum_filter(_split_csv(status), FEEDBACK_STATUSES, "status")
    wanted_priority = _validate_enum_filter(_split_csv(priority), FEEDBACK_PRIORITIES, "priority")
    if unresolved_only:
        # Intersect rather than clobber: asking for status=closed AND
        # unresolved_only is contradictory, and silently honouring one of the
        # two would answer a question the operator did not ask.
        base = wanted_status if wanted_status is not None else set(FEEDBACK_STATUSES)
        wanted_status = base - TERMINAL_STATUSES

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
        "select": _TICKET_COLUMNS,
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if since_hours is not None:
        cutoff = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()
        params["created_at"] = f"gte.{cutoff}"
    if wanted_status:
        params["status"] = "in.(" + ",".join(sorted(wanted_status)) + ")"
    if wanted_priority:
        params["priority"] = "in.(" + ",".join(sorted(wanted_priority)) + ")"
    if assigned_to:
        params["assigned_to"] = f"eq.{assigned_to}"
    # An empty (not absent) status set is an unsatisfiable filter — skip the
    # query rather than emit `in.()`, which PostgREST rejects.
    no_match = wanted_status is not None and not wanted_status

    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=False) as client:
            entries: list = []
            if not no_match:
                fb_resp = await client.get(
                    f"{supabase_url}/rest/v1/feedback", params=params, headers=headers
                )
                fb_resp.raise_for_status()
                entries = fb_resp.json()

            mf_resp = await client.get(
                f"{supabase_url}/rest/v1/match_feedback",
                # select=* so bucket/final_score feed the analysis block and the
                # request stays valid whether or not migration 018 (context) has
                # been applied yet.
                params={
                    "select": "*",
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
    titles: dict = {}
    schools: dict = {}
    for o in load_opportunities():
        titles[o.get("id")] = o.get("title")
        schools[o.get("id")] = o.get("school")
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
        # Echo the effective filter so a UI cannot mistake "nothing matched"
        # for "nothing exists" (unresolved_only silently narrows `status`).
        "filters": {
            "status": sorted(wanted_status) if wanted_status is not None else None,
            "priority": sorted(wanted_priority) if wanted_priority is not None else None,
            "assigned_to": assigned_to,
            "unresolved_only": unresolved_only,
            "since_hours": since_hours,
        },
        "match_feedback": {
            "up": up,
            "down": down,
            "up_7d": sum(1 for t in recent if t.get("verdict") == "up"),
            "down_7d": sum(1 for t in recent if t.get("verdict") == "down"),
            "sample_size": len(thumbs),
            "top_downvoted": top_downvoted,
            "analysis": analyze_votes(thumbs, schools),
        },
    }


@router.get("/admin/feedback/{ticket_id}")
async def feedback_ticket_detail(
    ticket_id: str,
    actor: str = Depends(require_admin),
):
    """One ticket plus its full admin action history, oldest event first."""
    supabase_url, headers = _service_role_env()

    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=False) as client:
            ticket = await _fetch_ticket(client, supabase_url, headers, ticket_id)
            ev_resp = await client.get(
                f"{supabase_url}/rest/v1/feedback_events",
                params={
                    "ticket_id": f"eq.{ticket_id}",
                    "select": _EVENT_COLUMNS,
                    "order": "created_at.asc",
                    "limit": "500",
                },
                headers=headers,
            )
            ev_resp.raise_for_status()
            events = ev_resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e

    return {"status": "ok", "ticket": ticket, "events": events, "event_count": len(events)}


@router.patch("/admin/feedback/{ticket_id}")
async def update_feedback_ticket(
    ticket_id: str,
    req: FeedbackPatchRequest,
    actor: str = Depends(require_admin),
):
    """Move a ticket through its lifecycle, logging every accepted change.

    Invariants (the DB CHECKs in 026 are the backstop, not the first line):
      * resolved/closed REQUIRES a resolution — no silent closes. The decision
        may arrive in this request or already sit on the row (resolved→closed).
      * a resolution only exists on a resolved/closed ticket; moving off those
        states clears it, stamps a 'reopened' event, and carries the retracted
        decision into that event's note so it is not lost.
      * from_value on every event is read from the live row, so the trail
        records what actually changed rather than what the caller assumed.
      * unknown enum values are rejected here with 400; letting them reach
        PostgREST would surface as a 500-shaped upstream failure.
    """
    fields = req.model_fields_set
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Validate before touching env or the network: a malformed request should
    # cost nothing and must not depend on storage being configured.
    new_status = _require_enum(req.status, FEEDBACK_STATUSES, "status") if "status" in fields else None
    new_priority = (
        _require_enum(req.priority, FEEDBACK_PRIORITIES, "priority") if "priority" in fields else None
    )
    if "resolution" in fields and req.resolution is not None:
        _require_enum(req.resolution, FEEDBACK_RESOLUTIONS, "resolution")

    supabase_url, headers = _service_role_env()
    now_iso = datetime.now(UTC).isoformat()

    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=False) as client:
            ticket = await _fetch_ticket(client, supabase_url, headers, ticket_id)

            cur_status = ticket.get("status") or "open"
            cur_priority = ticket.get("priority") or "normal"
            cur_assigned = ticket.get("assigned_to")
            cur_resolution = ticket.get("resolution")
            cur_note = ticket.get("resolution_note")

            target_status = new_status if new_status is not None else cur_status
            entering_terminal = target_status in TERMINAL_STATUSES and cur_status not in TERMINAL_STATUSES
            leaving_terminal = cur_status in TERMINAL_STATUSES and target_status not in TERMINAL_STATUSES

            target_resolution = req.resolution if "resolution" in fields else cur_resolution
            if leaving_terminal:
                if "resolution" in fields and req.resolution is not None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot set a resolution while moving to '{target_status}'; reopening clears it",
                    )
                target_resolution = None
            if target_status in TERMINAL_STATUSES and not target_resolution:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"status '{target_status}' requires a resolution "
                        f"(one of: {', '.join(FEEDBACK_RESOLUTIONS)})"
                    ),
                )
            if target_resolution and target_status not in TERMINAL_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail="A resolution only belongs on a resolved/closed ticket; set status too",
                )

            target_note = (req.resolution_note or None) if "resolution_note" in fields else cur_note
            if leaving_terminal:
                target_note = None
            if target_note and not target_resolution:
                raise HTTPException(
                    status_code=400,
                    detail="resolution_note requires a resolution",
                )

            updates: dict = {}
            events: list[dict] = []

            def _log(action: str, from_value=None, to_value=None, note=None) -> None:
                events.append(_event_row(ticket_id, actor, action, from_value, to_value, note))

            if new_priority is not None and new_priority != cur_priority:
                updates["priority"] = new_priority
                _log("priority_changed", cur_priority, new_priority)

            if "assigned_to" in fields:
                new_assigned = _sanitize_label(req.assigned_to)
                if new_assigned != cur_assigned:
                    updates["assigned_to"] = new_assigned
                    if new_assigned is None:
                        _log("unassigned", cur_assigned, None)
                    else:
                        _log("assigned", cur_assigned, new_assigned)

            if new_status is not None and new_status != cur_status:
                updates["status"] = new_status
                _log("status_changed", cur_status, new_status)

            if target_resolution != cur_resolution:
                updates["resolution"] = target_resolution
            if target_note != cur_note:
                updates["resolution_note"] = target_note

            if leaving_terminal:
                updates["resolved_at"] = None
                updates["resolved_by"] = None
                updates["closed_at"] = None
                _log(
                    "reopened", cur_status, target_status,
                    note=f"cleared resolution: {cur_resolution}" if cur_resolution else None,
                )
            elif target_status in TERMINAL_STATUSES:
                decision_changed = target_resolution != cur_resolution
                if entering_terminal or decision_changed:
                    updates["resolved_by"] = actor
                    # Keep the ORIGINAL resolved_at across resolved→closed: when
                    # the ticket was decided is a different fact from when it
                    # was filed away.
                    if entering_terminal or not ticket.get("resolved_at"):
                        updates["resolved_at"] = now_iso
                if decision_changed:
                    _log("resolved", cur_resolution, target_resolution)
                elif target_note != cur_note:
                    _log("note_added", cur_note, target_note)
                if target_status == "closed" and not ticket.get("closed_at"):
                    updates["closed_at"] = now_iso

            if not updates:
                return {
                    "status": "ok", "ticket": ticket, "changed": False,
                    "events_written": [], "actor": actor,
                }

            # No trigger on the table, so updated_at is ours to maintain.
            updates["updated_at"] = now_iso
            updated = await _patch_ticket(client, supabase_url, headers, ticket_id, updates)
            audit_error = await _log_events(client, supabase_url, headers, events)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e

    out = {
        "status": "ok",
        "ticket": updated,
        "changed": True,
        "events_written": [e["action"] for e in events],
        "actor": actor,
    }
    if audit_error:
        out["audit_log_error"] = audit_error
    return out


@router.post("/admin/feedback/{ticket_id}/reply")
async def reply_to_feedback_ticket(
    ticket_id: str,
    req: FeedbackReplyRequest,
    actor: str = Depends(require_admin),
):
    """Record an operator reply, optionally emailing it to the submitter.

    Delivery honesty (the W12/W14 invariant): admin_reply_delivery is set to
    'emailed' ONLY when Resend accepted the message. `deliver=false`, a ticket
    with no email, or an unconfigured provider all record 'stored' — the reply
    exists in the ticket and nobody was told. A requested send that fails
    records 'email_failed' and returns the reason; it never degrades to a
    silent 'stored' (which would read as "we chose not to send") and never
    claims 'emailed'.

    A reply is not a handling decision: status and resolution are untouched.
    """
    supabase_url, headers = _service_role_env()
    now_iso = datetime.now(UTC).isoformat()

    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=False) as client:
            ticket = await _fetch_ticket(client, supabase_url, headers, ticket_id)

            recipient = (ticket.get("email") or "").strip().lower()
            api_key = os.environ.get("RESEND_API_KEY", "").strip()
            from_addr = os.environ.get("RESEND_FROM_EMAIL", "").strip()

            delivery = "stored"
            delivery_error: str | None = None
            if req.deliver:
                if not recipient:
                    delivery_error = "ticket has no email address; reply stored only"
                elif not (api_key and from_addr):
                    delivery_error = "email provider not configured; reply stored only"
                else:
                    subject, html, text = _render_reply_email(ticket, req.reply)
                    try:
                        # Same per-recipient cap the user-facing send paths obey,
                        # so an admin reply loop cannot flood one mailbox.
                        _enforce_recipient_quota(recipient)
                        await _send_via_resend(
                            api_key=api_key, from_addr=from_addr, to=recipient,
                            subject=subject, html=html, text=text,
                        )
                        delivery = "emailed"
                    except Exception as e:  # provider 4xx/5xx, timeout, quota
                        delivery = "email_failed"
                        detail = getattr(e, "detail", None) or str(e)
                        delivery_error = f"{type(e).__name__}: {detail}"[:200]
                        logger.warning(
                            "Admin reply delivery failed for ticket %s: %s", ticket_id, delivery_error
                        )

            updates = {
                "admin_reply": req.reply,
                "admin_reply_at": now_iso,
                "admin_reply_by": actor,
                "admin_reply_delivery": delivery,
                "updated_at": now_iso,
            }
            updated = await _patch_ticket(client, supabase_url, headers, ticket_id, updates)
            audit_error = await _log_events(
                client, supabase_url, headers,
                [_event_row(
                    ticket_id, actor, "replied",
                    from_value=ticket.get("admin_reply_delivery"),
                    to_value=delivery,
                    note=delivery_error,
                )],
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e

    out = {
        "status": "ok",
        "ticket": updated,
        "delivery": delivery,
        "delivery_error": delivery_error,
        "actor": actor,
    }
    if audit_error:
        out["audit_log_error"] = audit_error
    return out
