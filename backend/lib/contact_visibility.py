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

import ipaddress
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

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
IDENTITY_BOUND_EMAIL_SOURCES = frozenset({
    "bound_directory_card",
    "bound_directory_name_join",
    "bound_profile_container",
    "bound_profile_custom_obfuscated",
    "bound_profile_obfuscated",
})
_IDENTITY_BOUND_EMAIL_SOURCES = IDENTITY_BOUND_EMAIL_SOURCES

CONTACT_EVIDENCE_FIELDS = frozenset({
    "identity_bound",
    "email_source",
    "contact_verified_email",
    "contact_source_url",
    "contact_verified_at",
})

_EMAIL_TARGET_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    flags=re.IGNORECASE,
)
_NONSTANDARD_NUMERIC_HOST_RE = re.compile(
    r"^(?:0x[0-9a-f]+|0[0-7]+|[0-9]+)"
    r"(?:\.(?:0x[0-9a-f]+|0[0-7]+|[0-9]+)){0,3}$",
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


def safe_contact_source_url(value: object) -> str | None:
    """Return an HTTPS, externally routable URL suitable as contact evidence.

    ``safe_public_http_url`` is the browser-link boundary and intentionally
    permits HTTP and local hosts. Contact evidence is a stronger claim: it must
    point to the actual public response where the identity/email binding was
    observed, never localhost, a private address, or a downgrade to cleartext.
    """

    safe = safe_public_http_url(value)
    if safe is None:
        return None
    try:
        parsed = urlsplit(safe)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
    except ValueError:
        return None
    if "%" in hostname or not hostname.isascii():
        # Browser URL parsers decode percent/full-width host spellings before
        # navigation, which can turn them into loopback/private literals.
        return None
    if parsed.scheme.casefold() != "https" or "." not in hostname:
        return None
    if hostname == "localhost" or hostname.endswith((
        ".localhost",
        ".local",
        ".internal",
        ".home",
        ".lan",
        ".test",
        ".invalid",
        ".example",
    )):
        return None
    if _NONSTANDARD_NUMERIC_HOST_RE.fullmatch(hostname) is not None:
        return None
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return safe
    # A reviewed academic directory should have a stable DNS identity. Reject
    # raw IP literals entirely, including globally routed ones.
    return None


def canonical_profile_evidence_url(value: object) -> tuple[str, int, str, str] | None:
    """Return the strict identity tuple used by profile-bound contact proof.

    A trailing slash is the only path canonicalization accepted. In
    particular, a same-host redirect from ``/people/ada`` to ``/directory`` is
    not proof about Ada, and a query-bearing profile must keep the same query.
    """

    safe = safe_contact_source_url(value)
    if safe is None:
        return None
    try:
        parsed = urlsplit(safe)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port or 443
    except ValueError:
        return None
    if parsed.fragment:
        return None
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return hostname, port, path, parsed.query


def _profile_evidence_matches_record(opp: dict, source_url: object) -> bool:
    expected = canonical_profile_evidence_url(source_url)
    if expected is None:
        return False
    application = opp.get("application")
    # Profile proof is anchored to the two authoritative normalized profile
    # projections. An optional application URL may corroborate them, but must
    # never establish identity by itself after the primary fields disappear.
    if not opp.get("url") or not opp.get("source_url"):
        return False
    candidates = [
        opp.get("url"),
        opp.get("source_url"),
        application.get("application_url")
        if isinstance(application, dict)
        else None,
    ]
    present = [candidate for candidate in candidates if candidate]
    if not present:
        return False
    # url/source_url/application_url are duplicate projections of the same
    # profile identity in normalized records. A stale alternate field must not
    # rescue a changed primary URL, so every present projection must agree.
    return all(
        canonical_profile_evidence_url(candidate) == expected
        for candidate in present
    )


def build_identity_bound_contact_evidence(
    *,
    email: object,
    email_source: object,
    contact_source_url: object,
    contact_verified_at: datetime | str | None = None,
) -> dict[str, object] | None:
    """Build the five-field evidence tuple, or fail without partial output.

    Collectors call this only after one reviewed extraction event has bound an
    address to a person. The returned dict is complete and canonical, so a
    caller can attach it with one ``dict.update`` rather than writing evidence
    fields piecemeal.
    """

    if not isinstance(email, str):
        return None
    canonical_email = email.strip().casefold()
    if not canonical_email or not _valid_email_target(canonical_email):
        return None

    if not isinstance(email_source, str):
        return None
    canonical_source = email_source.strip().casefold()
    if (
        canonical_source != email_source
        or canonical_source not in IDENTITY_BOUND_EMAIL_SOURCES
    ):
        return None

    safe_source_url = safe_contact_source_url(contact_source_url)
    if safe_source_url is None:
        return None

    # A proof timestamp comes from the fetch event. Defaulting a missing value
    # to "now" would let a later apply/carry step impersonate an observation.
    observed = contact_verified_at
    if isinstance(observed, str):
        try:
            observed = datetime.fromisoformat(
                observed.strip().replace("Z", "+00:00")
            )
        except ValueError:
            return None
    if (
        not isinstance(observed, datetime)
        or observed.tzinfo is None
        or observed.utcoffset() is None
    ):
        return None
    observed_utc = observed.astimezone(UTC)
    if observed_utc > datetime.now(UTC) + _CLOCK_SKEW_GRACE:
        return None

    return {
        "identity_bound": True,
        "email_source": canonical_source,
        "contact_verified_email": canonical_email,
        "contact_source_url": safe_source_url,
        "contact_verified_at": observed_utc.isoformat(),
    }


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
    if not isinstance(source, str):
        return False
    canonical_source = source.strip().casefold()
    if (
        source != canonical_source
        or canonical_source not in IDENTITY_BOUND_EMAIL_SOURCES
    ):
        return False

    verified_email = metadata.get("contact_verified_email")
    if (
        not isinstance(verified_email, str)
        or verified_email.strip().casefold() != email.casefold()
    ):
        return False

    contact_source_url = metadata.get("contact_source_url")
    if safe_contact_source_url(contact_source_url) is None:
        return False
    if (
        canonical_source.startswith("bound_profile_")
        and not _profile_evidence_matches_record(opp, contact_source_url)
    ):
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
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        return False
    current = current.astimezone(UTC)
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
