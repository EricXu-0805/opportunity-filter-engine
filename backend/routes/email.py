"""
Email endpoints — lets users email themselves their match results or
favorites without creating an account.

Resend is the delivery backend (100 emails/day free tier). Set
RESEND_API_KEY + RESEND_FROM_EMAIL env vars to enable. When keys are
unset every endpoint returns 503 so the frontend degrades gracefully.

Rate-limit: 3 emails per IP per hour (enforced in backend/main.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import time
from collections import defaultdict
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.data_loader import load_opportunities_by_id
from backend.lib.position_truth import displayed_title
from backend.lib.public_projection import (
    neutralize_lifecycle_title,
    safe_public_http_url,
    safe_public_text,
)
from backend.lib.release_scope import (
    release_visible_opportunities,
    release_visible_opportunity_by_id,
)
from backend.lib.supabase_auth import authenticated_identity
from backend.lib.target_actionability import assert_target_actionable, prework_refusal
from src.evidence import (
    faculty_availability_status,
    faculty_safe_public_record,
    record_kind,
    target_truth,
)

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
# Bounded so a malformed or hostile payload is rejected at parse time rather
# than after it has been carried through a lookup and into a rendered email.
_MAX_ID_LENGTH = 100
_MAX_NOTES_LENGTH = 2000
_MAX_STATUS_LENGTH = 40
_MAX_EMAIL_LENGTH = 254
# Bound for the legacy describing fields the rollout bridge still accepts and
# ignores. Generous enough for any real value, small enough that a hostile
# payload is refused at parse time.
_MAX_TEXT_LENGTH = 500


def _require_real_id(value: str | None) -> str | None:
    """Strip, then refuse what is left if it is nothing.

    ``min_length=1`` accepts "   ", which would then travel all the way to a
    corpus lookup and come back as a 409 — a slower, vaguer way of saying the
    request was malformed.

    ``None`` is the one value that passes through, and it means something
    different: not a malformed id, but an old client stating it has no id to
    give (see ROLLOUT BRIDGE below). A blank string is NOT that statement and
    must never be read as one — otherwise a CURRENT client with one empty field
    silently stops addressing the record it holds an id for and starts
    addressing whichever record happens to match its describing text.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("opportunity_id must not be blank")
    return stripped


def _require_usable_identity(item: BaseModel) -> BaseModel:
    """Every item must say WHICH record it means, one way or the other.

    With an id, that is the id. Without one, the only thing the server can use
    is the exact public locator the client was served, so both halves have to be
    present and be strings. A url may legitimately be ``""`` — a record with no
    public top-level url resolves on the empty string — but a title may not,
    because ``""`` is indistinguishable from a field the client never sent.
    """
    if item.opportunity_id is not None:
        return item
    if not isinstance(item.title, str) or not item.title:
        raise ValueError("an item without opportunity_id must supply a title")
    if not isinstance(item.url, str):
        raise ValueError("an item without opportunity_id must supply a url")
    return item

# SEC-3: the IP rate limit (3/hr, keyed on client IP in main.py) does not stop an
# attacker rotating or spoofing IPs from bombing ONE victim address with mail from
# our verified sending domain. Cap sends per normalized recipient too, so a single
# mailbox can't be flooded regardless of source IP. In-memory + time-windowed,
# mirroring the main rate-limit middleware's purge pattern.
_RECIPIENT_SEND_LIMIT = 3
_RECIPIENT_SEND_WINDOW_S = 3600
_recipient_sends: dict[str, list[float]] = defaultdict(list)
_recipient_last_purge = 0.0
# Guards the check-and-reserve on _recipient_sends. Held across synchronous
# statements only — never across the await that sends.
_recipient_lock = threading.Lock()


def _enforce_recipient_quota(email: str) -> None:
    """Reserve one send attempt against ``email``'s anti-bombing quota.

    The quota counts *attempts that reach the provider*, not confirmed
    deliveries. That is the only definition this code can honour: a manual
    send carries no idempotency key, so a timeout or a 5xx may well have been
    accepted and delivered anyway. Refunding the slot on a failed-looking send
    would let a client retry an ambiguous failure repeatedly and bomb an
    address through the very cap meant to stop it. An attempt therefore counts
    once it starts, whatever the provider then says.

    Only a refusal raised *before* the provider is touched avoids the slot, and
    those all raise ahead of this call. Callers must invoke this after every
    validation and render step, immediately before sending, so nothing between
    here and the provider can fail and leave a slot spent for no attempt.

    Locked because check-then-append is a read-modify-write: two concurrent
    requests could each see room and both send, putting the address one over.

    ``email`` is already normalized by ``_validate_email``. This is the
    IP-independent backstop to the per-IP limit.
    """
    global _recipient_last_purge
    now = time.time()
    with _recipient_lock:
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
            # Tagged: this cap is reached before Resend is called, so no send
            # was paid for and the global spend ceiling gives its slot back.
            # The per-IP bucket still counts the request — a client retrying
            # into a recipient cap is exactly the traffic that bucket slows.
            raise prework_refusal(
                429,
                "This address has received too many emails recently. Try again later.",
            )
        recent.append(now)
        _recipient_sends[email] = recent


class MatchItemRequest(BaseModel):
    """One mailed match. Nothing the client says about it is believed.

    A digest arrives hours later with no way for the reader to check it, so
    everything it asserts is read from the corpus at send time. Even a score is
    refused: a client-computed "91% match" is a ranking claim we would be
    republishing on that client's word.

    ROLLOUT BRIDGE — do not delete these legacy fields yet.
    The frontend (Vercel) and backend (Render) deploy independently, and the
    frontend usually lands first. So for this release both sides send both
    shapes: the client keeps emitting title/url/score/... so an OLD backend
    still works, and this model still accepts them so a NEW backend does not
    422 a client mid-rollout.

    They fall into two kinds, and the difference matters:
      * title and url are a LOCATOR. When the client sends no id — HEAD's
        bundle never does — they are the only way to say which record it means,
        matched exactly against the public projection (see `_public_locator`).
      * source, deadline, organization, record_kind and score are IGNORED
        outright. Every one is overwritten from the canonical record before
        rendering, and a test mails a poisoned value to prove it never reaches
        the message.
    Neither kind is ever trusted as mail CONTENT: a locator says which record,
    never what to print about it.

    Once both sides are on the same SHA, a follow-up PR drops them here and
    stops sending them there. Deleting them earlier breaks the deploy window.
    """

    model_config = ConfigDict(extra="forbid")

    # Optional for the rollout window only. `None` means "old client, use the
    # locator"; a blank string stays a 422 (see `_require_real_id`).
    opportunity_id: str | None = Field(default=None, max_length=_MAX_ID_LENGTH)

    # Locator when there is no id (title, url), otherwise ignored.
    title: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    url: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    # Ignored outright (see ROLLOUT BRIDGE above).
    score: float | None = None
    source: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    deadline: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    organization: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    record_kind: str | None = Field(default=None, max_length=_MAX_STATUS_LENGTH)

    _strip_id = field_validator("opportunity_id")(_require_real_id)
    _identity = model_validator(mode="after")(_require_usable_identity)


class MatchItem(BaseModel):
    """One rendered row. Built in the handler; never parsed from a request."""

    opportunity_id: str
    title: str = ""
    url: str = ""
    source: str = ""
    deadline: str | None = None
    organization: str = ""
    record_kind: Literal["listing", "faculty_contact", "unknown"] = "unknown"
    # A guess the app renders as "· estimated" and refuses to call passed.
    # The email has to carry it or it makes the claim the app declines to.
    deadline_is_estimate: bool = False
    # Server-written, never accepted from the wire: a warning a client could
    # omit is not a warning.
    advisory: str | None = None


class SendMatchesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ROLLOUT BRIDGE, like the describing fields above: accepted so a client
    # that still sends it is not 422'd, and optional so one that has stopped is
    # not either. It is NEVER the send target — see `_self_send_target`, which
    # mails the caller's own confirmed address and refuses any other.
    email: str | None = Field(default=None, max_length=_MAX_EMAIL_LENGTH)
    items: list[MatchItemRequest] = Field(..., max_length=MAX_ITEMS_PER_EMAIL)
    # ROLLOUT BRIDGE, accepted and ignored. The old subject was "Your top N
    # matches from JoinALab" — a ranking claim, phrased by the client, about a
    # list the server had not checked. The server writes its own neutral
    # subject now; this field only exists so a client mid-rollout is not 422'd
    # for still sending it. Dropped in the follow-up PR.
    subject_hint: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _validate_email(v) if v is not None else None


class FavoriteItemRequest(BaseModel):
    """A saved row: which target, plus the notes and status the user wrote.

    Notes and status are the user's own words about their own process, so they
    travel. Nothing describing the target does.

    ROLLOUT BRIDGE: the describing fields below are a locator (title, url) or
    ignored outright, for the duration of the split frontend/backend deploy —
    see MatchItemRequest.
    """

    model_config = ConfigDict(extra="forbid")

    opportunity_id: str | None = Field(default=None, max_length=_MAX_ID_LENGTH)
    notes: str = Field(default="", max_length=_MAX_NOTES_LENGTH)
    status: str = Field(default="", max_length=_MAX_STATUS_LENGTH)

    # Locator when there is no id (title, url), otherwise ignored.
    title: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    url: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    # Ignored outright (see ROLLOUT BRIDGE above).
    score: float | None = None
    source: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    deadline: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    record_kind: str | None = Field(default=None, max_length=_MAX_STATUS_LENGTH)

    _strip_id = field_validator("opportunity_id")(_require_real_id)
    _identity = model_validator(mode="after")(_require_usable_identity)


class FavoriteItem(BaseModel):
    """One rendered row. Built in the handler; never parsed from a request."""

    # Stated rather than left to the default, because it is load-bearing here:
    # both digests are built from the one `_describe`, and a saved row prints
    # the source name where a match row prints the organization. Dropping the
    # field it does not render is the point — the alternative is a second
    # describer, and two describers is how one of them ends up unsanitized.
    model_config = ConfigDict(extra="ignore")

    opportunity_id: str
    notes: str = ""
    status: str = ""
    title: str = ""
    url: str = ""
    source: str = ""
    deadline: str | None = None
    record_kind: Literal["listing", "faculty_contact", "unknown"] = "unknown"
    # A guess the app renders as "· estimated" and refuses to call passed.
    # The email has to carry it or it makes the claim the app declines to.
    deadline_is_estimate: bool = False
    advisory: str | None = None
    # A saved target can close between saving and mailing, and the digest must
    # say so rather than repeat what the browser remembered.
    historical: bool = False
    historical_reason: str = "unknown"


class SendFavoritesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ROLLOUT BRIDGE, like the describing fields above: accepted so a client
    # that still sends it is not 422'd, and optional so one that has stopped is
    # not either. It is NEVER the send target — see `_self_send_target`, which
    # mails the caller's own confirmed address and refuses any other.
    email: str | None = Field(default=None, max_length=_MAX_EMAIL_LENGTH)
    items: list[FavoriteItemRequest] = Field(..., max_length=MAX_ITEMS_PER_EMAIL)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _validate_email(v) if v is not None else None


async def _self_send_target(authorization: str | None, claimed: str | None) -> str:
    """The one address a user-facing digest may go to: the caller's own.

    The recipient used to come straight off the wire with no session at all,
    which made both endpoints a way to mail a JoinALab-branded digest to any
    address a stranger named — over the same verified domain that carries every
    magic link. #790 closed the other half of that (every describing field is
    re-read from the corpus, so the content cannot be forged); this closes the
    recipient.

    ``claimed`` is the request body's ``email``, kept as a ROLLOUT BRIDGE while
    clients still send it. It is never the send target. When it names someone
    else this REFUSES rather than quietly substituting the session address:
    silently redirecting would leave the sender believing a message reached the
    address they typed.

    Raised before the recipient quota and before the provider, so no refusal
    here can cost a send or a slot.
    """
    identity = await authenticated_identity(authorization)
    if identity is None:
        raise prework_refusal(401, {
            "code": "SIGN_IN_REQUIRED",
            "message": "Sign in to email yourself these results.",
            "retryable": False,
        })
    if identity.email is None:
        raise prework_refusal(409, {
            "code": "EMAIL_NOT_CONFIRMED",
            "message": (
                "Confirm your account's email address before JoinALab can send "
                "to it."
            ),
            "retryable": False,
        })
    if claimed is not None and claimed.strip().lower() != identity.email:
        raise prework_refusal(409, {
            "code": "RECIPIENT_NOT_SELF",
            "message": (
                "JoinALab only emails your own confirmed address. Nothing was "
                "sent to the address you entered."
            ),
            "retryable": False,
        })
    return identity.email


def _resend_configured() -> tuple[str, str]:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_addr = os.environ.get("RESEND_FROM_EMAIL", "").strip()
    if not api_key or not from_addr:
        raise prework_refusal(
            503,
            "Email service not configured (RESEND_API_KEY / RESEND_FROM_EMAIL unset)",
        )
    return api_key, from_addr


# ---------------------------------------------------------------------------
# Provider-side idempotency (W16)
# ---------------------------------------------------------------------------
# Every automated send in this codebase can be retried: the reminder cron
# re-runs nightly, the digest cron re-runs after a transport failure. Without a
# key, a retry after an AMBIGUOUS failure (the request timed out but Resend had
# already accepted it) is a second email in the user's inbox. Resend dedupes on
# the `Idempotency-Key` header, so the key must be derived from what the send
# IS — never freshly generated per attempt, or it defeats its own purpose.
#
# Resend retains a key for 24 hours, which is the natural window for both
# callers: a same-day retry dedupes, and a legitimately-different send (the
# next day's reminder, next week's digest) is a different key anyway.

def build_idempotency_key(scope: str, *parts: str) -> str:
    """Stable per-logical-send key: ``<scope>-<sha256(parts)[:32]>``.

    Deterministic in its inputs (same send -> same key on every attempt),
    bounded well under Resend's 256-character limit however long the natural
    identifiers are, and hashed so device/opportunity/search identifiers do not
    end up in a third party's request logs.
    """

    material = "|".join(str(part) for part in parts)
    return f"{scope}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"


def _deadline_phrase(row: MatchItem | FavoriteItem) -> str:
    """The deadline fragment for one email row.

    "due" is a claim. For an NSF REU the date is derived from the award start
    date and stamped `deadline_is_estimate`, and every in-app surface honours
    that: the card renders a gray "2025-02-15 · estimated" badge and
    getDeadlineUrgency refuses to return 'passed' for it. The email said "due
    2025-02-15" — the one place the app's caveats cannot follow the student.
    """
    if not row.deadline or row.record_kind != "listing":
        return ""
    if row.deadline_is_estimate:
        return f" · estimated {row.deadline}"
    return f" · due {row.deadline}"


def classify_send_failure(exc: BaseException) -> str:
    """``"ambiguous"`` when the send may already have been accepted.

    The distinction an operator actually needs: "this definitely did not go
    out" (safe to describe as a failure, retry is a first attempt) versus "this
    may or may not have gone out" (a retry may be a duplicate at the user, and
    only the Idempotency-Key keeps it from being one).
    """

    if isinstance(exc, HTTPException):
        # We got an answer from Resend (or refused before sending, e.g. the
        # recipient quota). A 5xx is the one answer that is NOT conclusive:
        # the request reached the provider and its fate is unknown.
        upstream = getattr(exc, "upstream_status", None)
        return "ambiguous" if isinstance(upstream, int) and upstream >= 500 else "definitive"
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout):
        # No connection was ever established: nothing was sent, definitively.
        return "definitive"
    # Read/write/pool timeouts and protocol errors all happen after the request
    # has been put on the wire. Anything unrecognised is treated the same way:
    # assuming a send did NOT happen is the assumption that duplicates mail.
    return "ambiguous"


async def _send_via_resend(*, api_key: str, from_addr: str, to: str,
                            subject: str, html: str, text: str,
                            idempotency_key: str | None = None) -> None:
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
    if idempotency_key:
        # Retry-safety for the automated senders; the user-facing endpoints
        # (send-matches/send-favorites) pass none, because a second click there
        # is a second deliberate request, not a retry.
        headers["Idempotency-Key"] = idempotency_key
    async with httpx.AsyncClient(timeout=10.0, trust_env=False, follow_redirects=False) as client:
        resp = await client.post(RESEND_API_URL, json=payload, headers=headers)
    if resp.status_code >= 400:
        logger.warning("Resend returned %s: %s", resp.status_code, resp.text[:300])
        failure = HTTPException(status_code=502, detail="Email delivery failed")
        # Preserve the provider's own status: it is what separates a definitive
        # rejection (4xx) from an ambiguous outcome (5xx) for callers that must
        # decide whether a retry risks duplicating a delivered message.
        failure.upstream_status = resp.status_code
        raise failure


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _safe_url(url: str) -> str:
    """Return the URL only if the public link contract accepts it, else "".

    Delegates to the one boundary the API already enforces rather than
    restating it. The previous check here was `startswith("http")`, which
    accepts a great deal the projection refuses: embedded credentials
    (`https://user:pw@host`), an embedded address (`http://vpue-fellowships@
    stanford.edu/`, a real shape in this corpus), leading or interior
    whitespace and newlines, and several URLs crammed into one field. Every
    one of those renders as a clickable link under the JoinALab brand, in a
    message the reader cannot check against anything.

    Two copies of a rule drift. This is the same function `/api` uses, so a
    link this build refuses to serve is a link it also refuses to mail.
    """
    return safe_public_http_url(url) or ""


def _render_match_email(items: list[MatchItem]) -> tuple[str, str, str]:
    # Server-written and deliberately not a ranking claim: "top N" asserted an
    # order the reader cannot check, from a score the client computed.
    title_line = f"{len(items)} results from your JoinALab search"
    rows_html = []
    rows_text = []
    # Unnumbered on purpose. "#1" read as a ranking, but the order here is
    # just the order the request arrived in — the server never re-ranked it,
    # and the score that once justified the number is no longer accepted.
    for m in items:
        faculty_contact = m.record_kind == "faculty_contact"
        score_str = ""
        dl_str = _deadline_phrase(m)
        kind_str = (
            "Faculty contact profile · current opening not confirmed"
            if faculty_contact
            else "Opportunity listing"
            if m.record_kind == "listing"
            else "Saved match · type not confirmed"
        )
        # Appended to the kind line rather than given its own block: it belongs
        # to the same sentence about what this row is, and this way the plain
        # text part carries it too. A warning only the HTML half states is a
        # warning half the recipients never see.
        if m.advisory:
            kind_str = f"{kind_str} · {m.advisory}"
        safe = _safe_url(m.url)
        title_html = (
            f'<a href="{_html_escape(safe)}" style="color:#4f46e5;text-decoration:none">{_html_escape(m.title)}</a>'
            if safe else
            f'<span style="color:#111827">{_html_escape(m.title)}</span>'
        )
        rows_html.append(
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #eee">'
            f'<div style="font-size:13px;color:#6b7280">{_html_escape(kind_str)}{_html_escape(score_str)}{_html_escape(dl_str)}</div>'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'{title_html}'
            f'</div>'
            f'<div style="font-size:12px;color:#9ca3af">{_html_escape(m.organization)} · {_html_escape(m.source)}</div>'
            f'</td></tr>'
        )
        rows_text.append(
            f"{kind_str}{score_str}{dl_str}\n"
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
      Here {'is' if len(items) == 1 else 'are'} {len(items)} match{'es' if len(items) != 1 else ''} we surfaced for you.
      Links open the corresponding listing or faculty profile; a faculty profile does not confirm a current opening.
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
    subject = f"Your {len(items)} saved JoinALab results"
    rows_html = []
    rows_text = []
    # Unnumbered for the same reason as the match digest above.
    for f in items:
        faculty_contact = f.record_kind == "faculty_contact"
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
        dl_str = _deadline_phrase(f)
        # The historical label replaces the kind rather than sitting beside it:
        # "Opportunity listing · closed" invites a reader to skim the first
        # half. Each reason gets its own words — a closed listing, a reference
        # record and a deactivated row are three different facts, and none of
        # them implies anything about a lab.
        kind_str = (
            _HISTORICAL_LABELS.get(f.historical_reason, _HISTORICAL_LABELS["unknown"])
            if f.historical
            else "Faculty contact profile · current opening not confirmed"
            if faculty_contact
            else "Opportunity listing"
            if f.record_kind == "listing"
            else "Saved match · type not confirmed"
        )
        # Stacks with a historical label instead of replacing it: "no longer
        # carried" and "no current active research" are two separate facts, and
        # a row can honestly carry both.
        if f.advisory:
            kind_str = f"{kind_str} · {f.advisory}"
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
            f'<div>{status_badge}<span style="font-size:12px;color:#9ca3af">{_html_escape(kind_str)}{_html_escape(dl_str)}</span></div>'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'{title_html}'
            f'</div>'
            f'<div style="font-size:12px;color:#9ca3af">{_html_escape(f.source)}</div>'
            f'{notes_html}</td></tr>'
        )
        rows_text.append(
            f"[{f.status.upper() if f.status else 'saved'}] {kind_str}{dl_str}\n"
            f"  {f.title}\n"
            f"  {safe or '(no link)'}\n"
            + (f"  notes: {f.notes}\n" if f.notes.strip() else "")
        )

    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white">
  <tr><td style="height:4px;background:#4f46e5;font-size:0;line-height:0">&nbsp;</td></tr>
  <tr><td style="padding:32px 28px">
    <div style="font-size:22px;font-weight:700;color:#4f46e5;letter-spacing:-0.5px">JoinALab</div>
    <div style="font-size:12px;color:#9ca3af;margin-top:2px">Research opportunity matching</div>
    <h1 style="font-size:22px;margin:24px 0 6px;color:#111827">{_html_escape(subject)}</h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 18px">
      Your saved results, with any notes and status you've tracked.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">
      {''.join(rows_html)}
    </table>
    <p style="margin-top:28px;color:#9ca3af;font-size:11px">
      Sent from JoinALab · <a href="{FRONTEND_BASE}/favorites" style="color:#4f46e5">View in app</a>
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


_MISSING_TARGET_DETAIL = {
    "code": "TARGET_NOT_ACTIONABLE",
    "reason": "unresolved",
    "message": "One of these results is no longer available. Refresh and try again.",
    "retryable": False,
}
_DUPLICATE_TARGET_DETAIL = {
    "code": "DUPLICATE_TARGET",
    "reason": "duplicate_opportunity_id",
    "message": "The same result was listed twice. Refresh and try again.",
    "retryable": False,
}
# One line per reason, neutral about everything the reason does not state. A
# closed listing says nothing about whether the lab still exists; a reference
# record was never a listing; a deactivated row is simply no longer carried.
_HISTORICAL_LABELS = {
    "listing_closed": "Closed — no longer accepting applications",
    "reference_only": "Reference record — not an open listing",
    # Attributed and narrow. Not "unavailable", which would also imply the lab
    # is gone, and not "closed", which would claim a posting existed.
    "faculty_not_accepting": (
        "Source profile states this faculty member is not currently accepting "
        "undergraduate students"
    ),
    "inactive": "Inactive — no longer carried in the catalog",
    # Nobody has confirmed what this record is, so it is not presented as an
    # opening. Distinct from "unknown" below, which means we could not read the
    # status at all.
    "record_kind_unverified": "Record type unverified — not presented as an open listing",
    "unknown": "Status unconfirmed — check the source",
}

# Carried on rows that stay actionable but whose source states there is no
# active research right now. The student may still write — that is the whole
# reason this is not a refusal — but the digest must not let the row read like
# an opening. Quoted as the source's report, never as our verdict.
_RESEARCH_INACTIVE_ADVISORY = (
    "Source reports no current active research — this is not an opening"
)


def _describe(record: dict) -> dict:
    """The display fields for one target, read from the corpus only."""
    truth = target_truth(record)
    # Never default to "listing": an unreviewed or stale source_type is not
    # evidence that an opening exists, and "Opportunity listing" in an inbox
    # is a claim we would have to stand behind.
    kind = record_kind(record)
    confirmed_listing = truth.actionable and kind == "listing"

    # An application URL is offered only for a confirmed, still-actionable
    # listing. For anything else — faculty profile, unknown kind, historical
    # row — the link is the source page, and an application URL is never
    # substituted for one: sending someone to an application form under a
    # "view source" affordance is the same false claim, differently labelled.
    # Sanitize each candidate BEFORE choosing between them, not after. Picking
    # `apply_url or source_url` on the raw values and sanitizing the winner
    # meant an unsafe application URL beat a perfectly good source URL and then
    # collapsed to no link at all — the reader lost the one link they could
    # have used, because of a field they were never going to see.
    application = record.get("application")
    apply_url = (
        _safe_url(application.get("application_url"))
        if confirmed_listing and isinstance(application, dict)
        else ""
    )
    # Ordered by preference, each already known-safe. `source_url` before
    # `url`: the scraped source page is the canonical thing to read, and `url`
    # is often a display alias.
    source_url = _safe_url(record.get("source_url")) or _safe_url(record.get("url"))

    # `research_inactive` never reaches this as a refusal — it stays actionable
    # on purpose. What it does is strip the row down to a question: no
    # application link, no deadline, and a line saying what the source reported.
    # Structurally the first two already hold (a faculty row is not a confirmed
    # listing), so this is belt-and-braces on the two fields plus the warning
    # that would otherwise be missing.
    research_inactive = (
        faculty_availability_status(record) == "research_inactive"
    )
    if research_inactive:
        apply_url = ""

    # Every text field here is corpus text, and the URL boundary above proves
    # corpus text carries addresses: `stanford-f0a974ed2bd2` is a real,
    # release-visible record whose TITLE is `vpue-fellowships@stanford.edu`.
    # The link contract already refuses its URL, but a title, a source name and
    # an organization go straight into the HTML and the plain-text part, where
    # nothing else looks at them. `safe_public_text` is the same boundary the
    # API projection applies to descriptions, per field, so a redacted title
    # does not take the source name down with it.
    return {
        # All three shared title rules, in the order detail and match cards
        # apply them, imported rather than re-implemented. `_describe` read the
        # RAW corpus record, so it was the one surface that skipped every one:
        # `faculty_safe_public_record` rewrites an unverified faculty row's
        # title to the person's name rather than a scraped directory heading,
        # `displayed_title` drops a "Prof." honorific the record's own stated
        # rank contradicts — a Lecturer promoted by a legacy scrape — and the
        # lifecycle neutralizer drops a "(applications open)" suffix on a record
        # we will not call an open listing. A saved-favorites digest printed the
        # raw title and reintroduced all of it in an inbox.
        #
        # The faculty projection also has to be here for the rollout bridge to
        # be coherent: `_public_locator` resolves a legacy item by the public
        # title, so a describer that rendered a different string would name a
        # record by one title and print another over it. Copy-on-write — the
        # helper returns a fresh dict and never touches the shared corpus row.
        "title": safe_public_text(
            neutralize_lifecycle_title(
                displayed_title(faculty_safe_public_record(record)), record,
            ),
        ),
        "source": safe_public_text(record.get("source")),
        # Read here rather than at the MatchItem call site, which used to build
        # it from the raw record and so was not covered by any of this.
        "organization": safe_public_text(record.get("organization")),
        # Both candidates are already sanitized, so this only decides which
        # safe link to offer. Empty means every candidate failed the contract,
        # and the row renders as plain text — never as a link to something we
        # would refuse to serve.
        "url": apply_url or source_url,
        # A date is corpus text like any other — scraped from the same pages,
        # by the same collectors, into a free-form field. `or None` keeps the
        # existing "no date" value exactly as it was; a date that turns out to
        # be an address renders as the placeholder rather than vanishing,
        # because a row that quietly loses its due line reads as rolling.
        "deadline": (
            safe_public_text(record.get("deadline")) or None
            if confirmed_listing and not research_inactive
            else None
        ),
        "record_kind": kind,
        "deadline_is_estimate": bool(record.get("deadline_is_estimate")),
        "advisory": _RESEARCH_INACTIVE_ADVISORY if research_inactive else None,
    }


_LEGACY_UNRESOLVED_DETAIL = {
    "code": "TARGET_NOT_ACTIONABLE",
    "reason": "legacy_identity_unresolved",
    "message": (
        "One of these results no longer matches a current record. "
        "Refresh and try again."
    ),
    "retryable": False,
}
_LEGACY_AMBIGUOUS_DETAIL = {
    "code": "TARGET_NOT_ACTIONABLE",
    "reason": "legacy_identity_ambiguous",
    "message": (
        "One of these results matches more than one current record. "
        "Refresh and try again."
    ),
    "retryable": False,
}


def _public_locator(record: dict) -> tuple[str, str]:
    """The (title, url) pair this record was published under.

    Built through the same projection the public API applies, because that is
    all the client holds — it can only echo back what it was served. Reading
    ``record["title"]`` here would look up a string no client was ever given:
    the projection rewrites a faculty row's title to the person's name, drops an
    honorific the record's own stated rank contradicts, and strips a terminal
    "(applications open)". Every affected row would stop resolving, and the
    reader would be told their saved result no longer exists.

    The URL is the record's TOP-LEVEL ``url`` and nothing else. `_describe`
    prefers ``source_url`` and links to an application URL, but neither of those
    is what the client was handed as this record's address.
    """
    public = faculty_safe_public_record(record)
    title = safe_public_text(
        neutralize_lifecycle_title(displayed_title(public), record),
    )
    return title, safe_public_http_url(record.get("url")) or ""


def _build_legacy_index(lookup: dict) -> dict[tuple[str, str], list[dict]]:
    """Group every release-visible record by its exact public locator.

    Candidates are kept as a LIST rather than first-win. Two records really can
    share a title and a url, and then the request genuinely does not say which
    one the reader saved — so the caller refuses instead of choosing. Silently
    preferring the live row over the historical one would mail someone an open
    listing they never shortlisted.

    Release-visible only. Indexing the raw lookup would give the legacy path a
    back door into exactly the records the release decided not to publish, and
    would let a hidden record collide with a visible one and turn a perfectly
    resolvable request into a permanent ambiguity refusal.
    """
    index: dict[tuple[str, str], list[dict]] = {}
    for record in release_visible_opportunities(lookup.values()):
        index.setdefault(_public_locator(record), []).append(record)
    return index


async def _legacy_index_if_needed(items: list, lookup: dict) -> dict | None:
    """Build the locator index off the event loop, and only when it is needed.

    The scan touches every release-visible record — seconds of CPU. Run inline
    in an async handler it blocks the one event loop this process has, so every
    other request in flight — matches, detail, health — stops until it finishes.
    A request whose items all carry ids, which is every current client, never
    pays for it at all.
    """
    if all(item.opportunity_id is not None for item in items):
        return None
    return await asyncio.to_thread(_build_legacy_index, lookup)


def _resolve_all(items: list, lookup: dict, legacy_index: dict | None) -> list[dict]:
    """Resolve every item against ONE snapshot, in request order.

    One map and one index, read once: resolving per item could straddle a
    corpus refresh and produce a digest whose rows came from two different
    generations of the data.

    Duplicates are refused rather than deduped — a repeated target means the
    caller and the server disagree about what the list is, and silently
    collapsing it would send a digest with fewer rows than were asked for. The
    comparison is on the CANONICAL id, after resolution: an id item and a legacy
    item look nothing alike as request shapes, so comparing what was sent would
    pass them both and mail the same row twice under a count that says one.
    """
    seen: set[str] = set()
    records: list[dict] = []
    for item in items:
        if item.opportunity_id is None:
            # Exact tuple, no trimming or casefolding: a locator that "nearly"
            # matches is a different record, and guessing which one the reader
            # meant is the fabrication this whole path exists to avoid.
            candidates = (legacy_index or {}).get((item.title, item.url), ())
            if not candidates:
                raise prework_refusal(409, _LEGACY_UNRESOLVED_DETAIL)
            if len(candidates) > 1:
                raise prework_refusal(409, _LEGACY_AMBIGUOUS_DETAIL)
            record = candidates[0]
        else:
            record = release_visible_opportunity_by_id(lookup, item.opportunity_id)
            if record is None:
                raise prework_refusal(409, _MISSING_TARGET_DETAIL)
        canonical_id = record.get("id")
        if canonical_id in seen:
            raise HTTPException(status_code=422, detail=_DUPLICATE_TARGET_DETAIL)
        seen.add(canonical_id)
        records.append(record)
    return records


@router.post("/email/send-matches")
async def send_matches(
    req: SendMatchesRequest,
    authorization: str | None = Header(default=None),
):
    api_key, from_addr = _resend_configured()
    recipient = await _self_send_target(authorization, req.email)
    if not req.items:
        raise prework_refusal(400, "No items to send")

    # Before the quota is spent and before the provider is called. A matches
    # digest is a list of things worth doing something about; one dead entry
    # makes the whole list untrustworthy, and quietly dropping it would send a
    # "top 10" containing nine.
    lookup = load_opportunities_by_id()
    legacy_index = await _legacy_index_if_needed(req.items, lookup)
    records = _resolve_all(req.items, lookup, legacy_index)
    rehydrated = []
    for record in records:
        assert_target_actionable(record)
        # Kind is a labelling decision here, never a refusal — but note what
        # the line above already did. The 26 UIUC/UCB rows that carry no
        # `source_type` are NOT actionable: the truth contract answers
        # `record_kind_unverified`, so `assert_target_actionable` has already
        # refused this whole digest before any of them could be labelled. What
        # remains for `_describe` is the actionable population, where kind
        # still decides the copy: faculty says the opening is unconfirmed, and
        # neither faculty nor unknown gets a deadline or an application link.
        rehydrated.append(MatchItem(
            # The canonical id, never the client's. A legacy item has none, and
            # an id item has already been resolved through it.
            opportunity_id=record["id"],
            **_describe(record),
        ))

    subject, html, text = _render_match_email(rehydrated)
    # Last thing before the provider. Reserving earlier would spend the
    # recipient's quota on a request that a later render failure means was
    # never attempted.
    _enforce_recipient_quota(recipient)
    await _send_via_resend(
        api_key=api_key, from_addr=from_addr, to=recipient,
        subject=subject, html=html, text=text,
    )
    return {"ok": True, "count": len(req.items)}


@router.post("/email/send-favorites")
async def send_favorites(
    req: SendFavoritesRequest,
    authorization: str | None = Header(default=None),
):
    api_key, from_addr = _resend_configured()
    recipient = await _self_send_target(authorization, req.email)
    if not req.items:
        raise prework_refusal(400, "No items to send")

    # A shortlist is a record of what the student chose, so a closed target
    # stays in the digest — labelled, without a deadline, and linking to the
    # source rather than an application. Unlike matches, one historical entry
    # does not invalidate the list.
    lookup = load_opportunities_by_id()
    legacy_index = await _legacy_index_if_needed(req.items, lookup)
    records = _resolve_all(req.items, lookup, legacy_index)
    rehydrated = []
    for item, record in zip(req.items, records, strict=True):
        truth = target_truth(record)
        rehydrated.append(FavoriteItem(
            opportunity_id=record["id"],
            notes=item.notes,
            status=item.status,
            historical=not truth.actionable,
            historical_reason=truth.reason_code or "unknown",
            **_describe(record),
        ))

    subject, html, text = _render_favorites_email(rehydrated)
    _enforce_recipient_quota(recipient)
    await _send_via_resend(
        api_key=api_key, from_addr=from_addr, to=recipient,
        subject=subject, html=html, text=text,
    )
    return {"ok": True, "count": len(req.items)}
