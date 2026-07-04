"""
Email endpoints — lets users email themselves their match results or
favorites without creating an account.

Resend is the delivery backend (100 emails/day free tier). Set
RESEND_API_KEY + RESEND_FROM_EMAIL env vars to enable. When keys are
unset every endpoint returns 503 so the frontend degrades gracefully.

Rate-limit: 3 emails per IP per hour (enforced in backend/main.py).
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict

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
    "FRONTEND_URL", "https://joinalab.com"
).rstrip("/")

MAX_ITEMS_PER_EMAIL = 50

# SEC-3: the IP rate limit (3/hr, keyed on client IP in main.py) does not stop an
# attacker rotating or spoofing IPs from bombing ONE victim address with mail from
# our verified sending domain. Cap sends per normalized recipient too, so a single
# mailbox can't be flooded regardless of source IP. In-memory + time-windowed,
# mirroring the main rate-limit middleware's purge pattern.
_RECIPIENT_SEND_LIMIT = 3
_RECIPIENT_SEND_WINDOW_S = 3600
_recipient_sends: dict[str, list[float]] = defaultdict(list)
_recipient_last_purge = 0.0


def _enforce_recipient_quota(email: str) -> None:
    """Raise 429 when ``email`` (already normalized by _validate_email) has
    received too many sends within the window — the IP-independent backstop to
    the per-IP limit."""
    global _recipient_last_purge
    now = time.time()
    if now - _recipient_last_purge > 300:
        stale = [
            k for k, ts in _recipient_sends.items()
            if not ts or ts[-1] < now - _RECIPIENT_SEND_WINDOW_S
        ]
        for k in stale:
            del _recipient_sends[k]
        _recipient_last_purge = now

    recent = [t for t in _recipient_sends[email] if t > now - _RECIPIENT_SEND_WINDOW_S]
    if len(recent) >= _RECIPIENT_SEND_LIMIT:
        _recipient_sends[email] = recent
        raise HTTPException(
            status_code=429,
            detail="This address has received too many emails recently. Try again later.",
        )
    recent.append(now)
    _recipient_sends[email] = recent


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


def _safe_url(url: str) -> str:
    """Return the URL only if it is http(s); otherwise "".

    send-matches/send-favorites accept caller-supplied item URLs and render
    them as clickable links under the JoinALab brand. Restricting the
    scheme blocks javascript:/data:/other-scheme links from riding the sending
    domain's reputation. Non-http(s) items render as plain text, not links.
    """
    u = (url or "").strip()
    low = u.lower()
    return u if low.startswith("http://") or low.startswith("https://") else ""


def _render_match_email(items: list[MatchItem], subject_hint: str) -> tuple[str, str, str]:
    title_line = subject_hint or f"Your top {len(items)} matches from JoinALab"
    rows_html = []
    rows_text = []
    for i, m in enumerate(items, 1):
        score_str = f"{m.score:.0f}% match" if m.score is not None else ""
        dl_str = f" · due {m.deadline}" if m.deadline else ""
        safe = _safe_url(m.url)
        title_html = (
            f'<a href="{_html_escape(safe)}" style="color:#4f46e5;text-decoration:none">{_html_escape(m.title)}</a>'
            if safe else
            f'<span style="color:#111827">{_html_escape(m.title)}</span>'
        )
        rows_html.append(
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #eee">'
            f'<div style="font-size:13px;color:#6b7280">#{i} · {_html_escape(score_str)}{_html_escape(dl_str)}</div>'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'{title_html}'
            f'</div>'
            f'<div style="font-size:12px;color:#9ca3af">{_html_escape(m.organization)} · {_html_escape(m.source)}</div>'
            f'</td></tr>'
        )
        rows_text.append(
            f"#{i} {score_str}{dl_str}\n"
            f"  {m.title}\n"
            f"  {m.organization} · {m.source}\n"
            f"  {safe or '(no link)'}\n"
        )

    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white">
  <tr><td style="height:4px;background:#4f46e5;font-size:0;line-height:0">&nbsp;</td></tr>
  <tr><td style="padding:32px 28px">
    <div style="font-size:22px;font-weight:700;color:#4f46e5;letter-spacing:-0.5px">JoinALab</div>
    <div style="font-size:12px;color:#9ca3af;margin-top:2px">Research opportunity matching</div>
    <h1 style="font-size:22px;margin:24px 0 6px;color:#111827">{_html_escape(title_line)}</h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 18px">
      Here {'is' if len(items) == 1 else 'are'} {len(items)} opportunit{'y' if len(items) == 1 else 'ies'} we surfaced for you.
      Links take you directly to the application page.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">
      {''.join(rows_html)}
    </table>
    <p style="margin-top:28px;color:#9ca3af;font-size:11px">
      You asked JoinALab to email you these matches · <a href="{FRONTEND_BASE}" style="color:#4f46e5">{FRONTEND_BASE}</a>
    </p>
  </td></tr>
</table>
</body></html>"""

    text = (
        f"{title_line}\n\n"
        + "".join(rows_text)
        + f"\n---\nSent from JoinALab · {FRONTEND_BASE}\n"
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
        safe = _safe_url(f.url)
        title_html = (
            f'<a href="{_html_escape(safe)}" style="color:#4f46e5;text-decoration:none">{_html_escape(f.title)}</a>'
            if safe else
            f'<span style="color:#111827">{_html_escape(f.title)}</span>'
        )
        rows_html.append(
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #eee">'
            f'<div>{status_badge}<span style="font-size:12px;color:#9ca3af">{_html_escape(dl_str.lstrip(" ·"))}</span></div>'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'{title_html}'
            f'</div>'
            f'<div style="font-size:12px;color:#9ca3af">{_html_escape(f.source)}</div>'
            f'{notes_html}</td></tr>'
        )
        rows_text.append(
            f"#{i} [{f.status.upper() if f.status else 'saved'}]{dl_str}\n"
            f"  {f.title}\n"
            f"  {safe or '(no link)'}\n"
            + (f"  notes: {f.notes}\n" if f.notes.strip() else "")
        )

    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white;padding:32px 24px">
  <tr><td>
    <div style="font-size:22px;font-weight:700;color:#0f172a">JoinALab</div>
    <h1 style="font-size:24px;margin:20px 0 8px">{_html_escape(subject)}</h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 20px">
      Your saved opportunities, with any notes and status you've tracked.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">
      {''.join(rows_html)}
    </table>
    <p style="margin-top:28px;color:#9ca3af;font-size:11px">
      Sent from JoinALab · <a href="{FRONTEND_BASE}/favorites" style="color:#9ca3af">View in app</a>
    </p>
  </td></tr>
</table>
</body></html>"""

    text = f"{subject}\n\n" + "".join(rows_text) + f"\n---\nJoinALab · {FRONTEND_BASE}/favorites\n"
    return subject, html, text


def _restore_signing_secret() -> str:
    # Legacy env-var name; now the shared secret for signing saved-search
    # digest unsubscribe links (see saved_searches.py). The profile-restore
    # feature it was named for was removed as inert dead code.
    return os.environ.get("RESTORE_LINK_SECRET", "").strip()


@router.post("/email/send-matches")
async def send_matches(req: SendMatchesRequest):
    api_key, from_addr = _resend_configured()
    if not req.items:
        raise HTTPException(status_code=400, detail="No items to send")
    _enforce_recipient_quota(req.email)

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
    _enforce_recipient_quota(req.email)

    subject, html, text = _render_favorites_email(req.items)
    await _send_via_resend(
        api_key=api_key, from_addr=from_addr, to=req.email,
        subject=subject, html=html, text=text,
    )
    return {"ok": True, "count": len(req.items)}


