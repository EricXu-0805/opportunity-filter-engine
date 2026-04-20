"""
Email endpoints — lets users save match results, favorites, and restore
their profile to a new device without creating an account.

Resend is the delivery backend (100 emails/day free tier). Set
RESEND_API_KEY + RESEND_FROM_EMAIL env vars to enable. When keys are
unset every endpoint returns 503 so the frontend degrades gracefully.

Rate-limit: 3 emails per IP per hour (enforced in backend/main.py).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _validate_email(value: str) -> str:
    v = (value or "").strip().lower()
    if not _EMAIL_RE.match(v) or len(v) > 254:
        raise ValueError("invalid email")
    return v

router = APIRouter()
logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
FRONTEND_BASE = os.environ.get(
    "FRONTEND_URL", "https://opportunity-filter-engine.vercel.app"
).rstrip("/")

MAX_ITEMS_PER_EMAIL = 50
RESTORE_TOKEN_TTL_HOURS = 24 * 30


class MatchItem(BaseModel):
    title: str
    url: str = ""
    score: float | None = None
    source: str = ""
    deadline: str | None = None
    organization: str = ""


class SendMatchesRequest(BaseModel):
    email: str
    items: list[MatchItem] = Field(..., max_length=MAX_ITEMS_PER_EMAIL)
    subject_hint: str = ""

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


class FavoriteItem(BaseModel):
    title: str
    url: str = ""
    score: float | None = None
    source: str = ""
    deadline: str | None = None
    notes: str = ""
    status: str = ""


class SendFavoritesRequest(BaseModel):
    email: str
    items: list[FavoriteItem] = Field(..., max_length=MAX_ITEMS_PER_EMAIL)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


class RestoreLinkRequest(BaseModel):
    email: str
    device_id: str = Field(..., min_length=4, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


def _resend_configured() -> tuple[str, str]:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_addr = os.environ.get("RESEND_FROM_EMAIL", "").strip()
    if not api_key or not from_addr:
        raise HTTPException(
            status_code=503,
            detail="Email service not configured (RESEND_API_KEY / RESEND_FROM_EMAIL unset)",
        )
    return api_key, from_addr


async def _send_via_resend(*, api_key: str, from_addr: str, to: str,
                            subject: str, html: str, text: str) -> None:
    payload = {
        "from": from_addr,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(RESEND_API_URL, json=payload, headers=headers)
    if resp.status_code >= 400:
        logger.warning("Resend returned %s: %s", resp.status_code, resp.text[:300])
        raise HTTPException(status_code=502, detail="Email delivery failed")


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _render_match_email(items: list[MatchItem], subject_hint: str) -> tuple[str, str, str]:
    title_line = subject_hint or f"Your top {len(items)} matches from OpportunityEngine"
    rows_html = []
    rows_text = []
    for i, m in enumerate(items, 1):
        score_str = f"{m.score:.0f}% match" if m.score is not None else ""
        dl_str = f" · due {m.deadline}" if m.deadline else ""
        link = m.url or "#"
        rows_html.append(
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #eee">'
            f'<div style="font-size:13px;color:#6b7280">#{i} · {_html_escape(score_str)}{_html_escape(dl_str)}</div>'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'<a href="{_html_escape(link)}" style="color:#2563eb;text-decoration:none">{_html_escape(m.title)}</a>'
            f'</div>'
            f'<div style="font-size:12px;color:#9ca3af">{_html_escape(m.organization)} · {_html_escape(m.source)}</div>'
            f'</td></tr>'
        )
        rows_text.append(
            f"#{i} {score_str}{dl_str}\n"
            f"  {m.title}\n"
            f"  {m.organization} · {m.source}\n"
            f"  {m.url or '(no link)'}\n"
        )

    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white;padding:32px 24px">
  <tr><td>
    <div style="font-size:22px;font-weight:700;color:#0f172a;letter-spacing:-0.5px">OpportunityEngine</div>
    <h1 style="font-size:24px;margin:20px 0 8px;color:#111827">{_html_escape(title_line)}</h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 20px">
      Here {'is' if len(items) == 1 else 'are'} {len(items)} opportunit{'y' if len(items) == 1 else 'ies'} we surfaced for you.
      Links take you directly to the application page.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">
      {''.join(rows_html)}
    </table>
    <p style="margin-top:28px;color:#9ca3af;font-size:11px">
      Sent from OpportunityEngine · <a href="{FRONTEND_BASE}" style="color:#9ca3af">{FRONTEND_BASE}</a>
    </p>
  </td></tr>
</table>
</body></html>"""

    text = (
        f"{title_line}\n\n"
        + "".join(rows_text)
        + f"\n---\nSent from OpportunityEngine · {FRONTEND_BASE}\n"
    )
    return title_line, html, text


def _render_favorites_email(items: list[FavoriteItem]) -> tuple[str, str, str]:
    subject = f"Your {len(items)} saved opportunities"
    rows_html = []
    rows_text = []
    for i, f in enumerate(items, 1):
        status_badge = ""
        if f.status:
            color = {
                "applied": "#2563eb", "replied": "#7c3aed",
                "interviewing": "#d97706", "rejected": "#6b7280",
            }.get(f.status, "#6b7280")
            status_badge = (
                f'<span style="display:inline-block;padding:2px 8px;'
                f'background:{color}1a;color:{color};border-radius:8px;'
                f'font-size:11px;font-weight:600;text-transform:uppercase;'
                f'letter-spacing:0.5px;margin-right:8px">{_html_escape(f.status)}</span>'
            )
        dl_str = f" · due {f.deadline}" if f.deadline else ""
        notes_html = ""
        if f.notes.strip():
            notes_html = (
                f'<div style="margin-top:6px;padding:8px 12px;background:#f9fafb;'
                f'border-left:3px solid #e5e7eb;font-size:13px;color:#4b5563;white-space:pre-wrap">'
                f'{_html_escape(f.notes)}</div>'
            )
        link = f.url or "#"
        rows_html.append(
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #eee">'
            f'<div>{status_badge}<span style="font-size:12px;color:#9ca3af">{_html_escape(dl_str.lstrip(" ·"))}</span></div>'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'<a href="{_html_escape(link)}" style="color:#2563eb;text-decoration:none">{_html_escape(f.title)}</a>'
            f'</div>'
            f'<div style="font-size:12px;color:#9ca3af">{_html_escape(f.source)}</div>'
            f'{notes_html}</td></tr>'
        )
        rows_text.append(
            f"#{i} [{f.status.upper() if f.status else 'saved'}]{dl_str}\n"
            f"  {f.title}\n"
            f"  {f.url or '(no link)'}\n"
            + (f"  notes: {f.notes}\n" if f.notes.strip() else "")
        )

    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white;padding:32px 24px">
  <tr><td>
    <div style="font-size:22px;font-weight:700;color:#0f172a">OpportunityEngine</div>
    <h1 style="font-size:24px;margin:20px 0 8px">{_html_escape(subject)}</h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 20px">
      Your saved opportunities, with any notes and status you've tracked.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">
      {''.join(rows_html)}
    </table>
    <p style="margin-top:28px;color:#9ca3af;font-size:11px">
      Sent from OpportunityEngine · <a href="{FRONTEND_BASE}/favorites" style="color:#9ca3af">View in app</a>
    </p>
  </td></tr>
</table>
</body></html>"""

    text = f"{subject}\n\n" + "".join(rows_text) + f"\n---\nOpenEngine · {FRONTEND_BASE}/favorites\n"
    return subject, html, text


def _restore_signing_secret() -> str:
    return os.environ.get("RESTORE_LINK_SECRET") or os.environ.get("ADMIN_TOKEN") or ""


def _sign_restore_payload(device_id: str, ts: int) -> str:
    """HMAC-SHA256 over device_id|ts. Email is intentionally excluded
    from the signed payload so the restore URL doesn't leak the user's
    email address in the query string.
    """
    secret = _restore_signing_secret().encode()
    if not secret:
        return ""
    msg = f"{device_id}|{ts}".encode()
    digest = hmac.new(secret, msg, hashlib.sha256).digest()
    return digest[:16].hex()


def _build_restore_url(device_id: str) -> str | None:
    if not _restore_signing_secret():
        return None
    ts = int(time.time())
    sig = _sign_restore_payload(device_id, ts)
    if not sig:
        return None
    return f"{FRONTEND_BASE}/restore?d={device_id}&t={ts}&s={sig}"


@router.post("/email/send-matches")
async def send_matches(req: SendMatchesRequest):
    api_key, from_addr = _resend_configured()
    if not req.items:
        raise HTTPException(status_code=400, detail="No items to send")

    subject, html, text = _render_match_email(req.items, req.subject_hint)
    await _send_via_resend(
        api_key=api_key, from_addr=from_addr, to=req.email,
        subject=subject, html=html, text=text,
    )
    return {"ok": True, "count": len(req.items)}


@router.post("/email/send-favorites")
async def send_favorites(req: SendFavoritesRequest):
    api_key, from_addr = _resend_configured()
    if not req.items:
        raise HTTPException(status_code=400, detail="No items to send")

    subject, html, text = _render_favorites_email(req.items)
    await _send_via_resend(
        api_key=api_key, from_addr=from_addr, to=req.email,
        subject=subject, html=html, text=text,
    )
    return {"ok": True, "count": len(req.items)}


@router.post("/email/restore-link")
async def restore_link(req: RestoreLinkRequest):
    """Emails a signed URL that lets a user recover their profile on a
    new device. Returns {ok: true} even when Resend is unconfigured so
    the frontend doesn't leak configuration state — just logs a warning.
    """
    url = _build_restore_url(req.device_id)
    if not url:
        logger.warning("restore-link requested but RESTORE_LINK_SECRET/ADMIN_TOKEN unset")
        return {"ok": True, "note": "disabled"}

    try:
        api_key, from_addr = _resend_configured()
    except HTTPException as e:
        if e.status_code == 503:
            return {"ok": True, "note": "email-disabled"}
        raise

    subject = "Your OpportunityEngine restore link"
    html = f"""<!doctype html><html><body style="font-family:sans-serif;padding:24px;background:#fafafa">
<div style="max-width:500px;margin:0 auto;background:white;padding:32px;border-radius:12px">
  <h1 style="font-size:20px;margin:0 0 12px">Restore your OpportunityEngine session</h1>
  <p style="color:#4b5563;font-size:14px;line-height:1.5">
    Click the button below on any device to load your saved profile,
    favorites, and application notes. The link works for {RESTORE_TOKEN_TTL_HOURS // 24} days.
  </p>
  <p style="text-align:center;margin:28px 0">
    <a href="{_html_escape(url)}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:white;text-decoration:none;border-radius:8px;font-weight:600">Open my session</a>
  </p>
  <p style="color:#9ca3af;font-size:12px;margin-top:20px">
    Didn't ask for this? You can safely ignore this email — no account was created.
  </p>
</div>
</body></html>"""
    text = (
        f"Restore your OpportunityEngine session:\n\n{url}\n\n"
        f"The link works for {RESTORE_TOKEN_TTL_HOURS // 24} days. "
        f"If you didn't request this, ignore the email.\n"
    )
    await _send_via_resend(
        api_key=api_key, from_addr=from_addr, to=req.email,
        subject=subject, html=html, text=text,
    )
    return {"ok": True}


@router.get("/email/verify-restore")
async def verify_restore(d: str, t: int, s: str):
    """Verify the signed restore link. The frontend calls this when
    the user clicks the email link; we respond with the validated
    device_id so the app can load their profile.
    """
    if not re.match(r"^[a-zA-Z0-9_\-]{4,128}$", d):
        raise HTTPException(status_code=400, detail="Invalid device_id")
    secret = _restore_signing_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Restore disabled")

    age_seconds = int(time.time()) - t
    if age_seconds < 0 or age_seconds > RESTORE_TOKEN_TTL_HOURS * 3600:
        raise HTTPException(status_code=400, detail="Link expired")

    expected = _sign_restore_payload(d, t)
    if not expected or not hmac.compare_digest(expected, s):
        raise HTTPException(status_code=400, detail="Invalid signature")
    return {"ok": True, "device_id": d}
