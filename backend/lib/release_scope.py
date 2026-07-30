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
    "compare",
    "fellowships",
    "resume_renovate",
    "roadmap",
    "ask_ai",
    "professor_signals",
    "payments",
]

RELEASE_SCOPE = MappingProxyType(
    {
        "match_ai_refine": False,
        "compare": False,
        "fellowships": False,
        "resume_renovate": False,
        "roadmap": False,
        "ask_ai": False,
        "professor_signals": False,
        "payments": False,
    }
)

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
