"""Thin payment-channel adapter for the concierge flow.

Only ``manual`` is implemented: the user scans a static QR code, claims
payment in the app, and the operator confirms by hand (admin confirm
endpoint → :func:`confirm_order`). The other channels raise until their
real-world prerequisites are met:

- wechat: WeChat Pay merchant onboarding requires a registered business
  entity (LLC) and, for a mainland-hosted checkout page, ICP filing.
- alipay: Alipay open-platform merchant account likewise requires a
  business license (LLC; ICP considerations for mainland hosting).
- stripe: Stripe US account activation requires an SSN/ITIN — blocked
  until the fall LLC.
"""

from __future__ import annotations

from datetime import UTC, datetime

CHANNELS = ("manual", "wechat", "alipay", "stripe")

_UNIMPLEMENTED = "channel '{0}' is not integrated yet — see module docstring for prerequisites"


def _require_manual(channel: str) -> None:
    if channel not in CHANNELS:
        raise ValueError(f"unknown payment channel: {channel}")
    if channel != "manual":
        raise NotImplementedError(_UNIMPLEMENTED.format(channel))


def create_order(
    channel: str,
    *,
    device_id: str,
    package: str,
    amount_cents: int,
    currency: str = "usd",
    note: str | None = None,
) -> dict:
    """Row values for a new pending order on the given channel."""
    _require_manual(channel)
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    return {
        "device_id": device_id,
        "package": package,
        "amount_cents": amount_cents,
        "currency": currency,
        "channel": channel,
        "status": "pending",
        "note": note,
    }


def confirm_order(channel: str, order: dict) -> dict:
    """Fields to persist when the operator confirms payment was received."""
    _require_manual(channel)
    return {"status": "paid", "paid_at": datetime.now(UTC).isoformat()}


def handle_webhook(channel: str, payload: dict) -> dict:
    """Manual has no webhook; real channels get one when integrated."""
    if channel == "manual":
        raise NotImplementedError("manual channel has no webhook")
    _require_manual(channel)
    raise AssertionError("unreachable")
