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

import hashlib
import hmac
import logging
import os
import re
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse

from backend.data_loader import load_opportunities
from backend.routes.email import (
    FRONTEND_BASE,
    _enforce_recipient_quota,
    _html_escape,
    _restore_signing_secret,
    _send_via_resend,
    _validate_email,
)
from backend.routes.push import _required_env, _verify_cron_secret
from src.saved_searches.filter import matching_ids

router = APIRouter()
logger = logging.getLogger(__name__)


SUPABASE_BATCH_LIMIT = 1000

# Unsubscribe links must point at THIS service (the endpoint flips the
# Supabase row server-side), unlike FRONTEND_BASE links. Render injects
# RENDER_EXTERNAL_URL automatically; PUBLIC_BACKEND_URL is the manual
# override, and the hardcoded prod URL mirrors api-server.ts's fallback.
BACKEND_BASE = (
    os.environ.get("PUBLIC_BACKEND_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or "https://opportunity-filter-engine-api.onrender.com"
).rstrip("/")

DIGEST_MAX_ITEMS = 10
DIGEST_MIN_INTERVAL_DAYS = 7
# Unsubscribe must keep working long after the email lands (CAN-SPAM floor
# is 30 days; a year covers any realistic inbox archaeology) — deliberately
# much longer than the restore-link TTL.
DIGEST_UNSUB_TTL_DAYS = 365

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _sign_digest_unsub(search_id: str, ts: int) -> str:
    """Same HMAC-SHA256 construction as email.py's restore token, with a
    distinct context prefix so digest tokens can never be replayed as
    restore tokens (and vice versa) under the shared RESTORE_LINK_SECRET.
    """
    secret = _restore_signing_secret().encode()
    if not secret:
        return ""
    msg = f"digest-unsub|{search_id}|{ts}".encode()
    return hmac.new(secret, msg, hashlib.sha256).digest()[:16].hex()


def _build_unsubscribe_url(search_id: str) -> str | None:
    ts = int(time.time())
    sig = _sign_digest_unsub(search_id, ts)
    if not sig:
        return None
    return f"{BACKEND_BASE}/api/email/digest-unsubscribe?sid={search_id}&t={ts}&s={sig}"


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# CAN-SPAM: a recurring opt-in digest must carry the sender's physical postal
# address. Kept in an env var (set on Render once there's a mailing address /
# PO box) so we never ship a placeholder or a hard-coded home address; the line
# is simply omitted until it's set.
_POSTAL_ADDRESS = os.environ.get("EMAIL_POSTAL_ADDRESS", "").strip()


def _digest_footer_html(search_name: str, unsubscribe_url: str) -> str:
    addr = (f'<div style="margin-top:6px">{_html_escape(_POSTAL_ADDRESS)}</div>'
            if _POSTAL_ADDRESS else "")
    return (
        '<hr style="border:none;border-top:1px solid #eee;margin:28px 0 14px">'
        '<p style="color:#9ca3af;font-size:11px;line-height:1.6;margin:0">'
        'JoinALab · research opportunity matching<br>'
        f'You opted in to this weekly digest when you saved "{_html_escape(search_name)}". '
        f'<a href="{_html_escape(unsubscribe_url)}" style="color:#4f46e5">Unsubscribe</a> · '
        f'<a href="{FRONTEND_BASE}/favorites" style="color:#4f46e5">Manage saved searches</a>'
        f'{addr}'
        '</p>'
    )


def _digest_footer_text(search_name: str, unsubscribe_url: str) -> str:
    addr = f"{_POSTAL_ADDRESS}\n" if _POSTAL_ADDRESS else ""
    return (
        "\n---\nJoinALab · research opportunity matching\n"
        f'You opted in to this weekly digest when you saved "{search_name}".\n'
        f"Unsubscribe: {unsubscribe_url}\n"
        f"Manage saved searches: {FRONTEND_BASE}/favorites\n"
        f"{addr}"
    )


def _render_digest_email(
    search_name: str, items: list[dict], unsubscribe_url: str,
) -> tuple[str, str, str]:
    count = len(items)
    subject = (
        f"1 new match for \"{search_name}\"" if count == 1
        else f"{count} new matches for \"{search_name}\""
    )
    rows_html = []
    rows_text = []
    for i, opp in enumerate(items, 1):
        title = opp.get("title") or "Untitled opportunity"
        org = opp.get("organization") or ""
        deadline = opp.get("deadline") or ""
        dl_str = f" · due {deadline}" if deadline else ""
        detail_url = f"{FRONTEND_BASE}/opportunities/{opp.get('id', '')}"
        rows_html.append(
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #eee">'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'<a href="{_html_escape(detail_url)}" style="color:#4f46e5;text-decoration:none">{_html_escape(title)}</a>'
            f'</div>'
            f'<div style="font-size:12px;color:#9ca3af">{_html_escape(org)}{_html_escape(dl_str)}</div>'
            f'</td></tr>'
        )
        rows_text.append(f"#{i} {title}\n  {org}{dl_str}\n  {detail_url}\n")

    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white">
  <tr><td style="height:4px;background:#4f46e5;font-size:0;line-height:0">&nbsp;</td></tr>
  <tr><td style="padding:32px 28px">
    <div style="font-size:22px;font-weight:700;color:#4f46e5;letter-spacing:-0.5px">JoinALab</div>
    <div style="font-size:12px;color:#9ca3af;margin-top:2px">Research opportunity matching</div>
    <h1 style="font-size:22px;margin:24px 0 6px;color:#111827">{_html_escape(subject)}</h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 18px">
      New opportunities that started matching your saved search since we last checked.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">
      {''.join(rows_html)}
    </table>
    <a href="{FRONTEND_BASE}/favorites" style="display:inline-block;margin-top:24px;padding:11px 22px;background:#4f46e5;color:white;text-decoration:none;border-radius:8px;font-weight:600;font-size:14px">View all in JoinALab</a>
    {_digest_footer_html(search_name, unsubscribe_url)}
  </td></tr>
</table>
</body></html>"""

    text = (
        f"{subject}\n\n"
        + "".join(rows_text)
        + f"\nView all: {FRONTEND_BASE}/favorites\n"
        + _digest_footer_text(search_name, unsubscribe_url)
    )
    return subject, html, text


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


@router.get("/cron/saved-searches/digest")
async def saved_searches_digest(authorization: str | None = Header(default=None)):
    """Weekly opt-in email digest of new saved-search matches.

    Invoked by the same workflow as /cron/saved-searches/refresh, right
    after it (so new_match_ids is fresh). For every row with
    digest_opt_in=true, a digest_email, and unseen new matches, sends ONE
    email via the email.py Resend machinery — throttled to at most one
    digest per search per DIGEST_MIN_INTERVAL_DAYS via last_digest_sent_at.
    No email is ever sent without the explicit opt-in flag.
    """
    _verify_cron_secret(authorization)

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "skipped", "reason": "supabase env not configured", "missing": missing}
    env = env_result

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_addr = os.environ.get("RESEND_FROM_EMAIL", "").strip()
    if not api_key or not from_addr:
        logger.info("digest cron: RESEND_API_KEY / RESEND_FROM_EMAIL unset — skipping sends")
        return {"status": "skipped", "reason": "resend not configured"}

    # An opt-in email without a working unsubscribe link is worse than no
    # email — refuse to send rather than degrade the link away.
    if not _restore_signing_secret():
        logger.info("digest cron: RESTORE_LINK_SECRET unset — cannot sign unsubscribe links")
        return {"status": "skipped", "reason": "unsubscribe signing secret not configured"}

    try:
        import httpx
    except ImportError:
        return {"status": "skipped", "reason": "httpx not installed"}

    opportunities = load_opportunities()
    if not opportunities:
        return {"status": "skipped", "reason": "no opportunities loaded"}
    opp_by_id = {o.get("id"): o for o in opportunities if o.get("id")}

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    now = datetime.now(UTC)
    sent = 0
    throttled = 0
    skipped = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        list_resp = await client.get(
            f"{supabase_url}/rest/v1/saved_searches",
            params={
                "select": "id,name,digest_email,new_match_ids,last_digest_sent_at",
                "digest_opt_in": "eq.true",
                "digest_unsubscribed_at": "is.null",
                "digest_email": "not.is.null",
                "limit": str(SUPABASE_BATCH_LIMIT),
            },
            headers=headers,
        )
        list_resp.raise_for_status()
        rows = list_resp.json()

        for row in rows:
            sid = str(row.get("id", "?"))
            try:
                new_ids = row.get("new_match_ids") or []
                items = [opp_by_id[i] for i in new_ids if i in opp_by_id][:DIGEST_MAX_ITEMS]
                if not items:
                    skipped += 1
                    continue

                last_sent = _parse_iso_ts(row.get("last_digest_sent_at"))
                if last_sent and now - last_sent < timedelta(days=DIGEST_MIN_INTERVAL_DAYS):
                    throttled += 1
                    continue

                try:
                    to_email = _validate_email(row.get("digest_email") or "")
                except ValueError:
                    skipped += 1
                    continue

                unsubscribe_url = _build_unsubscribe_url(sid)
                if not unsubscribe_url:
                    skipped += 1
                    continue

                # Same per-recipient mail-bomb backstop as the user-facing
                # send endpoints; a 429 here just defers to the next run.
                try:
                    _enforce_recipient_quota(to_email)
                except HTTPException:
                    throttled += 1
                    continue

                subject, html, text = _render_digest_email(
                    row.get("name") or "Saved search", items, unsubscribe_url,
                )
                await _send_via_resend(
                    api_key=api_key, from_addr=from_addr, to=to_email,
                    subject=subject, html=html, text=text,
                )
                patch_resp = await client.patch(
                    f"{supabase_url}/rest/v1/saved_searches",
                    params={"id": f"eq.{sid}"},
                    headers=headers,
                    json={"last_digest_sent_at": now.isoformat()},
                )
                patch_resp.raise_for_status()
                sent += 1
            except Exception as e:  # noqa: BLE001 — keep cron iterating
                errors.append(f"{sid}: {type(e).__name__}: {e}")

    return {
        "status": "ok" if not errors else "partial",
        "sent": sent,
        "throttled": throttled,
        "skipped": skipped,
        "errors": errors[:10],
        "timestamp": datetime.now(UTC).isoformat(),
    }


_UNSUB_CONFIRMATION_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><title>Unsubscribed</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#fafafa;margin:0;padding:48px 24px">
<div style="max-width:480px;margin:0 auto;background:white;padding:32px;border-radius:12px;text-align:center">
  <h1 style="font-size:20px;margin:0 0 12px;color:#111827">You're unsubscribed</h1>
  <p style="color:#4b5563;font-size:14px;line-height:1.6;margin:0 0 8px">
    This saved search will no longer email you a weekly digest.
    You can turn it back on anytime from your saved searches.
  </p>
  <p style="color:#6b7280;font-size:13px;line-height:1.6;margin:0 0 20px">
    已退订 — 该保存搜索不会再发送每周摘要邮件，可随时在「我的收藏」中重新开启。
  </p>
  <a href="{FRONTEND_BASE}/favorites" style="color:#4f46e5;font-size:14px;text-decoration:none">JoinALab →</a>
</div>
</body></html>"""


@router.get("/email/digest-unsubscribe")
async def digest_unsubscribe(sid: str, t: int, s: str):
    """One-click unsubscribe from a saved search's weekly digest.

    No auth beyond the HMAC token: the link lands in the recipient's
    inbox, and the only effect of a valid token is turning email OFF —
    same threat model as email.py's restore link, lower stakes.
    """
    if not _UUID_RE.match(sid):
        raise HTTPException(status_code=400, detail="Invalid saved search id")
    if not _restore_signing_secret():
        raise HTTPException(status_code=503, detail="Unsubscribe disabled")

    age_seconds = int(time.time()) - t
    if age_seconds < 0 or age_seconds > DIGEST_UNSUB_TTL_DAYS * 86400:
        raise HTTPException(status_code=400, detail="Link expired")

    expected = _sign_digest_unsub(sid, t)
    if not expected or not hmac.compare_digest(expected, s):
        raise HTTPException(status_code=400, detail="Invalid signature")

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        raise HTTPException(status_code=503, detail="Storage not configured")
    env = env_result

    import httpx

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.patch(
            f"{supabase_url}/rest/v1/saved_searches",
            params={"id": f"eq.{sid}"},
            headers=headers,
            json={
                "digest_opt_in": False,
                "digest_unsubscribed_at": datetime.now(UTC).isoformat(),
            },
        )
    if resp.status_code >= 400:
        logger.warning("digest unsubscribe PATCH failed: %s %s", resp.status_code, resp.text[:200])
        raise HTTPException(status_code=502, detail="Could not update digest settings")

    return HTMLResponse(_UNSUB_CONFIRMATION_HTML)
