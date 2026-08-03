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

# The synthesized-vs-observed provenance predicate is shared with the ranker's
# actionability tie-break (src.matcher.ranker._is_actionable) via src.evidence
# so the two bars cannot drift apart; likewise the unit-mailbox predicate is
# shared with the collector nulling pass (W12 cold-email boundary).
from src.evidence import is_synthesized_email_source, is_unit_mailbox_email

STATUS_REVEALED = "revealed"
STATUS_SIGN_IN_REQUIRED = "sign_in_required"
STATUS_UNAVAILABLE = "unavailable"


def verified_send_target(opp: dict) -> str:
    """The opportunity's contact email when it passes the provenance bar, else ``""``.

    Three bars (W10b + W12):
    * provenance — a synthesized address is never a send target;
    * liveness — a deactivated record (departed/retired faculty, expired
      posting) must not hand out an outreach address: the stored email may be
      dead and the outreach premise ("I saw your posting/lab") is stale;
    * recipient type — for a faculty record, a department/unit mailbox is not
      the professor's address ("Dear Prof. X" to english@ misfires). Program
      records legitimately use unit/program contacts, so the bar is
      faculty-only. Collector hygiene nulls most of these at build time; this
      is the serve-time backstop for page_scan grabs and below-threshold
      shared inboxes it never sees.
    """
    email = opp.get("contact_email") or ""
    if not isinstance(email, str) or not email.strip():
        return ""
    md = opp.get("metadata") or {}
    if is_synthesized_email_source(md.get("email_source") or ""):
        return ""
    if md.get("is_active") is False:
        return ""
    if (opp.get("source_type") == "faculty_research"
            and is_unit_mailbox_email(email, opp.get("department") or "")):
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
