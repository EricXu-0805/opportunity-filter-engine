"""Single policy point for offering a professor's contact email to a caller.

W10b contact tightening. Two independent bars, both enforced server-side:

1. **Provenance** — an address is a valid SEND TARGET only when it is real
   harvested data. Collectors stamp ``metadata.email_source``; synthesized
   origins (``constructed_sunetid`` / ``constructed_netid`` — derived from a
   campus naming convention, never observed on a page) must NEVER be offered
   as a send target: a construction can silently misdirect mail. Harvested
   stamps (``profile_page``, ``wayback``, ``digitalmeasures_profile``) and the
   legacy unstamped majority (real scrapes that predate provenance stamping)
   pass.

2. **Session** — the reveal is gated on a signed-in (non-anonymous) Supabase
   account. Guests hold real anonymous-session tokens, so "token present" is
   not "signed in"; see backend.lib.supabase_auth.

The caller-facing status is deliberately the SAME for "no token", "stale
token", and "anonymous session": the anonymous shape plus a reveal flag —
degrade, never a 401 that breaks the page.
"""

from __future__ import annotations

# Any email_source starting with one of these was synthesized, not observed.
# Prefix match so future variants (e.g. "constructed_<campus>") stay covered.
_SYNTHESIZED_PREFIXES = ("constructed", "inferred", "guessed", "pattern")

STATUS_REVEALED = "revealed"
STATUS_SIGN_IN_REQUIRED = "sign_in_required"
STATUS_UNAVAILABLE = "unavailable"


def verified_send_target(opp: dict) -> str:
    """The opportunity's contact email when it passes the provenance bar, else ``""``."""
    email = opp.get("contact_email") or ""
    if not isinstance(email, str) or not email.strip():
        return ""
    source = (opp.get("metadata") or {}).get("email_source") or ""
    if isinstance(source, str) and source.startswith(_SYNTHESIZED_PREFIXES):
        return ""
    return email.strip()


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
