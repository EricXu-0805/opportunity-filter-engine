"""Server-side public release contract.

Unaccepted features are source-controlled off. Runtime variables can further
disable an accepted feature, but cannot promote an unaccepted one. Tests that
exercise dormant implementations patch their imported feature check directly;
there is deliberately no environment-variable escape hatch in this module.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Literal

ReleaseFeature = Literal[
    "match_ai_refine",
    "cross_school_matching",
    "compare",
    "fellowships",
    "resume_renovate",
    "roadmap",
    "ask_ai",
    "professor_signals",
    "payments",
    "microsoft_school_auth",
    "concierge_pay_qr",
]

RELEASE_SCOPE = MappingProxyType(
    {
        "match_ai_refine": True,
        "cross_school_matching": True,
        "compare": True,
        "fellowships": True,
        "resume_renovate": True,
        "roadmap": True,
        "ask_ai": True,
        "professor_signals": True,
        # Stays closed: migration 026 dropped the orders RLS policies and
        # revoked anon/authenticated access, and pricing.ts / the payment QR
        # assets are not on main. The flag is not the missing part.
        "payments": False,
        # Both of these were frontend-only until now, which release_gate's
        # flag_parity check reports as "ungated server-side" — correctly.
        # Hiding a control is not closing a door:
        #
        #   microsoft_school_auth — the azure provider is ENABLED on the
        #   Supabase project and reachable at /auth/v1/authorize?provider=azure
        #   without going through this app's UI at all. One real third-party
        #   account already exists that way (2026-06-25). The button being
        #   hidden never stopped anyone; refusing the resulting session does.
        #
        #   concierge_pay_qr — the QR is what turns a price into a payment.
        #   It stays separable from `payments` because it has its own
        #   prerequisite (a confirmed receiving account), so the manual channel
        #   must not mint orders even if payments is later switched on first.
        "microsoft_school_auth": False,
        "concierge_pay_qr": False,
    }
)

# The auth providers a session may be minted through. Anything else is a door
# this release has not opened, regardless of whether the provider is still
# configured upstream.
_PROVIDER_FEATURES: dict[str, ReleaseFeature] = {
    "azure": "microsoft_school_auth",
}

_RUNTIME_KILL_SWITCHES: dict[ReleaseFeature, str] = {
    "payments": "OFE_PAYMENTS_ENABLED",
}


def feature_enabled(feature: ReleaseFeature) -> bool:
    """Return whether ``feature`` is accepted and enabled for this process."""
    if not RELEASE_SCOPE[feature]:
        return False

    env_name = _RUNTIME_KILL_SWITCHES.get(feature)
    if env_name is None:
        return True
    return os.environ.get(env_name, "").strip().lower() in {"1", "true"}


def session_provider_accepted(user: Mapping[str, object]) -> bool:
    """Whether a GoTrue user's session came in through an accepted sign-in door.

    ``app_metadata.provider`` is the provider that minted THIS session, which is
    the question worth asking: a student who linked Microsoft to an otherwise
    Google account is not the risk, a session created straight against the
    provider endpoint is.
    """
    metadata = user.get("app_metadata")
    provider = metadata.get("provider") if isinstance(metadata, Mapping) else None
    if not isinstance(provider, str):
        return True
    feature = _PROVIDER_FEATURES.get(provider.strip().lower())
    return feature is None or feature_enabled(feature)


def opportunity_visible_in_release(opportunity: Mapping[str, object]) -> bool:
    """Whether one corpus record belongs on the current public release surface.

    Release-level record gates must be independent of a student's profile:
    removing ``fellowship`` from ``seeking_type`` is not enough because records
    with broad or missing major eligibility can still rank, and direct discovery
    endpoints do not consult a profile at all.  Accept both the canonical
    ``opportunity_type`` field and the legacy/import ``type`` alias so malformed
    or partially migrated data cannot bypass the gate.
    """
    if feature_enabled("fellowships"):
        return True

    for field in ("opportunity_type", "type"):
        value = opportunity.get(field)
        if isinstance(value, str) and value.strip().lower() == "fellowship":
            return False
    return True


def release_visible_opportunities(
    opportunities: Iterable[dict],
) -> list[dict]:
    """Return corpus records that are allowed on public release surfaces."""
    return [
        opportunity
        for opportunity in opportunities
        if opportunity_visible_in_release(opportunity)
    ]


def release_visible_opportunity_by_id(
    opportunities_by_id: Mapping[str, dict],
    opportunity_id: str,
) -> dict | None:
    """Resolve one public target without letting a known hidden id through."""
    opportunity = opportunities_by_id.get(opportunity_id)
    if opportunity is None or not opportunity_visible_in_release(opportunity):
        return None
    return opportunity
