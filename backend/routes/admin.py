"""
Admin endpoints for data-quality monitoring.

Protected by the ADMIN_TOKEN env var. Call with either:
- Header: X-Admin-Token: <token>
- Query param: ?token=<token>

If ADMIN_TOKEN is unset, all requests return 503 (admin disabled).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query

from backend.data_loader import load_opportunities

router = APIRouter()

_HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "admin_history.jsonl"
_HISTORY_MAX_ENTRIES = 365

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
        short_description=0, missing_deadline=0, rolling_deadline=0,
        missing_skills=0, past_deadline=0, stale_verify=0,
        flagged_inactive=0,
    )

    today = datetime.now(timezone.utc).date()
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
        if o.get("metadata", {}).get("is_active") is False:
            continue
        elig = o.get("eligibility", {}) or {}
        missing = 0
        if not (elig.get("majors") or []): missing += 1
        if _is_unsorted(o.get("keywords") or []): missing += 1
        if not (o.get("description_raw") or o.get("description_clean")): missing += 1
        if not o.get("deadline") and not o.get("is_rolling"): missing += 1
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

    generated_at = datetime.now(timezone.utc)
    snapshot = {
        "total": total,
        "global": dict(global_counts),
        "sources": sources_list,
        "worst_fields": worst_fields[:20],
        "generated_at": generated_at.isoformat(),
    }

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
    token: str | None = Query(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    limit: int = Query(default=30, ge=1, le=365),
):
    _authenticate(token, x_admin_token)

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
