"""Optional (non-raising) Supabase identity resolution for reveal-style routes.

Same GoTrue round-trip as ``orders._caller_uid`` — the token is validated by
Supabase itself, never decoded locally — but every failure degrades to ``None``
instead of a 401. Reveal paths must serve the anonymous response shape on a
stale token, not break the page; routes that gate a WRITE keep using the
raising ``orders._caller_uid`` pattern.
"""

from __future__ import annotations

import os

import httpx

from backend.lib.release_scope import session_provider_accepted


async def authenticated_uid(authorization: str | None) -> str | None:
    """The caller's Supabase uid, or ``None`` for anything but a signed-in account.

    ``None`` covers: missing/malformed header, expired or invalid token,
    Supabase env unconfigured, GoTrue unreachable, a session minted through a
    sign-in provider this release has not accepted, and — critically —
    ANONYMOUS sessions: every guest holds a real token from
    ``signInAnonymously``, so ``is_anonymous`` is what separates a guest from
    a signed-in account.
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
    uid = user.get("id")
    return str(uid) if uid else None
