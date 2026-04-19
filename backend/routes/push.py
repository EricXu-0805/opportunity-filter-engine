from __future__ import annotations

import os
from datetime import date, datetime, timezone

from fastapi import APIRouter, Header, HTTPException

router = APIRouter()


def _verify_cron_secret(secret: str | None) -> None:
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Push cron not configured (CRON_SECRET missing)")
    if secret != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid cron secret")


def _required_env(keys: list[str]) -> dict[str, str] | tuple[None, list[str]]:
    out = {}
    missing = []
    for k in keys:
        v = os.environ.get(k)
        if not v:
            missing.append(k)
        else:
            out[k] = v
    if missing:
        return (None, missing)
    return out


@router.get("/cron/reminders")
async def reminders_cron(authorization: str | None = Header(default=None)):
    """Invoked by an external scheduler (Vercel Cron / GitHub Actions).

    Scans push_subscriptions joined with interactions.remind_at where
    remind_at <= today and status in ('applied','replied','interviewing'),
    sends a Web Push notification to each matching subscription.
    """
    _verify_cron_secret(authorization)

    env_result = _required_env([
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "VAPID_PRIVATE_KEY",
        "VAPID_PUBLIC_KEY",
        "VAPID_SUBJECT",
    ])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "skipped", "reason": "push env not configured", "missing": missing}
    env = env_result

    try:
        import httpx
        from pywebpush import webpush, WebPushException
    except ImportError:
        return {
            "status": "skipped",
            "reason": "pywebpush not installed (pip install pywebpush httpx)",
        }

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
    }
    today = date.today().isoformat()

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            f"{supabase_url}/rest/v1/interactions",
            params={
                "select": "device_id,opportunity_id,remind_at,interaction_type,notes",
                "remind_at": f"lte.{today}",
                "interaction_type": "in.(applied,replied,interviewing)",
            },
            headers=headers,
        )
        r.raise_for_status()
        due = r.json()
        if not due:
            return {"status": "ok", "sent": 0, "due": 0}

        device_ids = list({row["device_id"] for row in due})
        sub_resp = await client.get(
            f"{supabase_url}/rest/v1/push_subscriptions",
            params={
                "select": "device_id,endpoint,p256dh,auth",
                "device_id": f"in.({','.join(device_ids)})",
            },
            headers=headers,
        )
        sub_resp.raise_for_status()
        subs = sub_resp.json()

    subs_by_device: dict[str, list[dict]] = {}
    for s in subs:
        subs_by_device.setdefault(s["device_id"], []).append(s)

    sent, failed = 0, 0
    vapid_claims = {"sub": env["VAPID_SUBJECT"]}
    for row in due:
        for sub in subs_by_device.get(row["device_id"], []):
            payload = (
                '{"title":"Reminder due","body":"You set a follow-up reminder for an application.",'
                f'"url":"/opportunities/{row["opportunity_id"]}","tag":"reminder-{row["opportunity_id"]}"'
                "}"
            )
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub["endpoint"],
                        "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                    },
                    data=payload,
                    vapid_private_key=env["VAPID_PRIVATE_KEY"],
                    vapid_claims=vapid_claims,
                )
                sent += 1
            except WebPushException:
                failed += 1

    return {
        "status": "ok",
        "due": len(due),
        "sent": sent,
        "failed": failed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/push/vapid-public-key")
async def get_vapid_public_key():
    key = os.environ.get("VAPID_PUBLIC_KEY") or os.environ.get("NEXT_PUBLIC_VAPID_PUBLIC_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Push not configured")
    return {"key": key}
