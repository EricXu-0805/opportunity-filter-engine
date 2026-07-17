"""Usage metering — inert scaffold, OFF by default.

Paid tiers (résumé renovation "first free then per-optimization"; cold-email
agent send) need a usage ledger. This module is the write/quota adapter for the
``usage_events`` table (migration 020). It ships DISABLED — ``record_usage``
no-ops and ``check_quota`` always allows — until the paid tiers actually go live
after the August pricing decision. Enabling is a one-flag flip
(``OFE_METERING_ENABLED=1``) plus a real ``QUOTAS`` table; no code path change,
no migration. Mirrors ``backend/lib/payments`` — adapter present, real path
gated — so nothing bills a user before pricing exists.

Write model matches 019/020: the client can never forge its own ledger (that
would let it under-report to dodge quota), so rows are written ONLY here via the
service-role Supabase REST endpoint, which bypasses RLS. A missing service-role
config or any HTTP error is swallowed — metering must never break a feature.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger("ofe.metering")

# When metering is live, the free allowance per feature before a charge applies.
# Unused while disabled; kept here so turning metering on is a config change, not
# a code change. ``None`` == unmetered.
FREE_QUOTA: dict[str, int | None] = {
    "renovation": 1,        # first résumé renovation free, then per-optimization
    "bullet_optimize": None,
    "cold_email_send": 0,   # agent send is paid from the first use
}


def metering_enabled() -> bool:
    """True only when explicitly switched on. Default OFF (pre-pricing)."""
    return os.environ.get("OFE_METERING_ENABLED", "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    remaining: int | None       # None == unmetered / unknown
    reason: str                 # "metering_disabled" | "within_free_quota" | "quota_exceeded"


async def check_quota(device_id: str, feature: str) -> QuotaDecision:
    """Whether ``device_id`` may use ``feature`` now.

    Always allows while metering is disabled — the ONLY behavior today. When
    enabled this will count prior ``usage_events`` against ``FREE_QUOTA`` and, if
    exhausted, whether the device holds a paid entitlement (orders). Deliberately
    never raises: a metering failure must not block a core feature.
    """
    if not metering_enabled():
        return QuotaDecision(allowed=True, remaining=None, reason="metering_disabled")
    # Live-metering accounting is intentionally not implemented until pricing is
    # decided; fail OPEN (allow) so a half-configured deploy never wrongly blocks
    # a user. The gate that matters — no silent charging — is that record_usage
    # only writes when enabled AND service-role configured.
    return QuotaDecision(allowed=True, remaining=None, reason="within_free_quota")


async def record_usage(
    device_id: str,
    feature: str,
    *,
    quantity: int = 1,
    meta: dict | None = None,
) -> bool:
    """Best-effort append to ``usage_events``. Returns True iff a row was written.

    No-ops (returns False) when metering is disabled or service-role env is
    missing. Never raises — callers fire-and-forget; a metering write must never
    surface as a feature error.
    """
    if not metering_enabled():
        return False
    if not device_id or not feature:
        return False

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        logger.info("metering: enabled but service-role env missing; skipping record")
        return False

    payload = {
        "device_id": device_id,
        "feature": feature,
        "quantity": max(1, int(quantity)),
        "meta": meta or {},
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{url}/rest/v1/usage_events",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json=payload,
            )
        if resp.status_code >= 400:
            logger.info("metering: usage_events insert returned %s", resp.status_code)
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — "never raises" is the contract:
        # a non-serializable meta or any client bug must degrade to a skipped
        # metering row, never to a broken feature response.
        logger.info("metering: usage_events insert failed: %s", exc)
        return False
