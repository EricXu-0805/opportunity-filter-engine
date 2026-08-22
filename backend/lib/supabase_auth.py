"""Optional (non-raising) Supabase identity resolution for reveal-style routes.

Same GoTrue round-trip as ``orders._caller_uid`` — the token is validated by
Supabase itself, never decoded locally — but every failure degrades to ``None``
instead of a 401. Reveal paths must serve the anonymous response shape on a
stale token, not break the page; routes that gate a WRITE keep using the
raising ``orders._caller_uid`` pattern.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from backend.lib.release_scope import session_provider_accepted


@dataclass(frozen=True)
class SessionIdentity:
    """Who the caller is, as GoTrue states it — never as the client claims it.

    ``email`` is populated only for an address GoTrue reports as CONFIRMED.
    An account can hold an unconfirmed address (a typo at sign-up, or someone
    else's address entered deliberately), and mailing that is the same
    unsolicited send this type exists to prevent. Unconfirmed reads as ``None``
    so a caller cannot mistake "we know of an address" for "the account proved
    it owns one".
    """

    uid: str
    email: str | None


async def _session_user(authorization: str | None) -> dict | None:
    """The GoTrue user behind a bearer token, or ``None``.

    ``None`` covers: missing/malformed header, expired or invalid token,
    Supabase env unconfigured, GoTrue unreachable, a session minted through a
    sign-in provider this release has not accepted, and — critically —
    ANONYMOUS sessions: every guest holds a real token from
    ``signInAnonymously``, so ``is_anonymous`` is what separates a guest from
    a signed-in account.

    One round trip, shared by every caller: the uid and the confirmed address
    come out of the same answer, so no route can end up trusting a uid from one
    validation and an address from another.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):].strip()
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not token or not url or not key:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=5.0, trust_env=False, follow_redirects=False,
        ) as client:
            resp = await client.get(
                f"{url}/auth/v1/user",
                headers={"apikey": key, "Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        user = resp.json()
    except ValueError:
        return None
    if not isinstance(user, dict) or user.get("is_anonymous"):
        return None
    if not session_provider_accepted(user):
        return None
    return user if user.get("id") else None


async def authenticated_uid(authorization: str | None) -> str | None:
    """The caller's Supabase uid, or ``None`` for anything but a signed-in account."""
    user = await _session_user(authorization)
    return str(user["id"]) if user else None


async def authenticated_identity(authorization: str | None) -> SessionIdentity | None:
    """The caller's uid plus their confirmed address, or ``None``.

    Confirmation is read from GoTrue's own ``email_confirmed_at`` (falling back
    to the legacy ``confirmed_at`` older projects still emit). A present but
    unconfirmed address yields ``SessionIdentity(uid, None)`` rather than a
    refusal, so a route can tell "not signed in" apart from "signed in, no
    address we may write to" and say the right thing to each.
    """
    user = await _session_user(authorization)
    if user is None:
        return None
    email = user.get("email")
    confirmed = user.get("email_confirmed_at") or user.get("confirmed_at")
    usable = (
        email.strip().lower()
        if isinstance(email, str) and email.strip() and confirmed
        else None
    )
    return SessionIdentity(uid=str(user["id"]), email=usable)
