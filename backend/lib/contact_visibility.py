"""Single policy point for offering a professor's contact email to a caller.

W10b contact tightening. Two independent bars, both enforced server-side:

1. **Provenance** — an address is a valid SEND TARGET only when a collector
   has explicitly bound the page/card identity to this professor, recorded an
   approved ``metadata.email_source``, and stamped a timezone-aware
   ``metadata.contact_verified_at`` plus the exact verified address and source
   URL. Legacy, stale, mismatched, and synthesized origins fail closed; an
   address merely appearing somewhere on a page is not proof that it belongs
   to this person.

2. **Session** — the reveal is gated on a signed-in (non-anonymous) Supabase
   account. Guests hold real anonymous-session tokens, so "token present" is
   not "signed in"; see backend.lib.supabase_auth.

The caller-facing status is deliberately the SAME for "no token", "stale
token", and "anonymous session": the anonymous shape plus a reveal flag —
degrade, never a 401 that breaks the page.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from backend.lib.public_projection import safe_public_http_url
# The synthesized-vs-observed provenance predicate is shared with the ranker's
# actionability tie-break (src.matcher.ranker._is_actionable) via src.evidence
# so the two bars cannot drift apart.
from src.evidence import is_synthesized_email_source

# A harvested-looking string is not enough evidence that it belongs to the
# professor in this record. Only the identity-binding collectors below have a
# contract that ties the address to the expected person and stamps when that
# binding was observed. New collector methods must be reviewed and added
# explicitly; unknown, legacy, constructed, inferred, and guessed sources all
# fail closed.
_IDENTITY_BOUND_EMAIL_SOURCES = frozenset({
    "bound_directory_card",
    "bound_directory_name_join",
    "bound_profile_container",
    "bound_profile_custom_obfuscated",
    "bound_profile_obfuscated",
})

_EMAIL_TARGET_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    flags=re.IGNORECASE,
)

# The project already treats profile evidence older than 60 days as stale.
# Contact auto-fill uses the same conservative window; users can still follow
# the public profile link and enter an address themselves after it expires.
CONTACT_VERIFICATION_TTL_DAYS = 60
_CLOCK_SKEW_GRACE = timedelta(minutes=5)

STATUS_REVEALED = "revealed"
STATUS_SIGN_IN_REQUIRED = "sign_in_required"
STATUS_UNAVAILABLE = "unavailable"


def _valid_email_target(email: str) -> bool:
    if len(email) > 254 or _EMAIL_TARGET_RE.fullmatch(email) is None:
        return False
    local, _separator, domain = email.rpartition("@")
    return bool(
        local
        and domain
        and len(local) <= 64
        and not local.startswith(".")
        and not local.endswith(".")
        and ".." not in local
    )


def _has_identity_bound_contact_evidence(
    opp: dict,
    email: str,
    *,
    now: datetime | None = None,
) -> bool:
    metadata = opp.get("metadata")
    if not isinstance(metadata, dict):
        return False
    if metadata.get("identity_bound") is not True:
        return False

    source = metadata.get("email_source")
    if (
        not isinstance(source, str)
        or source.strip().casefold() not in _IDENTITY_BOUND_EMAIL_SOURCES
    ):
        return False

    verified_email = metadata.get("contact_verified_email")
    if (
        not isinstance(verified_email, str)
        or verified_email.strip().casefold() != email.casefold()
    ):
        return False

    if safe_public_http_url(metadata.get("contact_source_url")) is None:
        return False

    verified_at = metadata.get("contact_verified_at")
    if not isinstance(verified_at, str) or not verified_at.strip():
        return False
    try:
        timestamp = datetime.fromisoformat(
            verified_at.strip().replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return False
    checked_at = timestamp.astimezone(UTC)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return (
        checked_at <= current + _CLOCK_SKEW_GRACE
        and current - checked_at <= timedelta(days=CONTACT_VERIFICATION_TTL_DAYS)
    )


def verified_send_target(opp: dict) -> str:
    """Return a professor-specific, identity-bound send target or ``""``.

    Legacy rows without the three-part evidence contract
    (``identity_bound``, reviewed ``email_source``, timezone-aware
    ``contact_verified_at``, matching ``contact_verified_email``, and safe
    ``contact_source_url``) are deliberately unavailable. A draft can still be
    generated, but JoinALab must not present an unproven address as verified.
    """
    email = opp.get("contact_email") or ""
    if not isinstance(email, str):
        return ""
    email = email.strip()
    # Both bars are enforced together (AND, never OR): identity-bound evidence
    # (a collector explicitly tied this address to this person and stamped
    # when) and a non-synthesized source (never a constructed/inferred/
    # guessed/pattern-generated address) are independent failure modes — an
    # address that only clears one is not a proven send target.
    if (
        not email
        or not _valid_email_target(email)
        or not _has_identity_bound_contact_evidence(opp, email)
        or is_synthesized_email_source((opp.get("metadata") or {}).get("email_source") or "")
    ):
        return ""
    return email


def contact_email_status(opp: dict, *, authenticated: bool) -> tuple[str, str]:
    """``(status, email)`` for a caller: the email is non-empty only when revealed.

    * ``unavailable`` — no verified (harvested-provenance) address exists.
    * ``sign_in_required`` — a verified address exists but the session is
      anonymous/absent/stale; the UI renders a sign-in-to-reveal affordance.
    * ``revealed`` — verified address, signed-in caller.
    """
    email = verified_send_target(opp)
    if not email:
        return STATUS_UNAVAILABLE, ""
    if not authenticated:
        return STATUS_SIGN_IN_REQUIRED, ""
    return STATUS_REVEALED, email
