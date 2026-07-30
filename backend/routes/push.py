from __future__ import annotations

import hmac
import os
from datetime import UTC, date, datetime

from fastapi import APIRouter, Header, HTTPException

from backend.data_loader import load_opportunities_by_id
from backend.lib.release_scope import release_visible_opportunity_by_id
from backend.lib.safe_webpush import (
    UnsafePushEndpointError,
    WebPushDeliveryTimeout,
    send_webpush_safely,
)
from backend.routes.email import (
    FRONTEND_BASE,
    _enforce_recipient_quota,
    _send_via_resend,
    _validate_email,
)

router = APIRouter()


def _verify_cron_secret(secret: str | None) -> None:
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Push cron not configured (CRON_SECRET missing)")
    # Use constant-time comparison to avoid timing attacks. The encode is required
    # because hmac.compare_digest works on bytes; the strings are short so there's
    # no allocation concern.
    provided = (secret or "").encode("utf-8")
    expected_bytes = f"Bearer {expected}".encode()
    if not hmac.compare_digest(provided, expected_bytes):
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


def _render_reminder_email(opportunity_id: str) -> tuple[str, str, str]:
    url = f"{FRONTEND_BASE}/opportunities/{opportunity_id}"
    subject = "Reminder: follow up on your application"
    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white">
  <tr><td style="height:4px;background:#4f46e5;font-size:0;line-height:0">&nbsp;</td></tr>
  <tr><td style="padding:32px 28px">
    <div style="font-size:22px;font-weight:700;color:#4f46e5;letter-spacing:-0.5px">JoinALab</div>
    <div style="font-size:12px;color:#9ca3af;margin-top:2px">Research opportunity matching</div>
    <h1 style="font-size:22px;margin:24px 0 6px;color:#111827">{subject}</h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 18px">
      The follow-up reminder you set on an application is due today.
    </p>
    <a href="{url}" style="display:inline-block;margin-top:8px;padding:11px 22px;background:#4f46e5;color:white;text-decoration:none;border-radius:8px;font-weight:600;font-size:14px">View the opportunity</a>
    <p style="margin-top:28px;color:#9ca3af;font-size:11px">
      You set this reminder in JoinALab · <a href="{FRONTEND_BASE}/favorites" style="color:#4f46e5">Manage your tracker</a>
    </p>
  </td></tr>
</table>
</body></html>"""
    text = (
        f"{subject}\n\n"
        "The follow-up reminder you set on an application is due today.\n"
        f"{url}\n\n"
        f"---\nSent from JoinALab · {FRONTEND_BASE}/favorites\n"
    )
    return subject, html, text


async def _account_email(client, supabase_url: str, headers: dict, uid: str) -> str | None:
    """device_id == Supabase auth uid; anonymous users have no email."""
    resp = await client.get(
        f"{supabase_url}/auth/v1/admin/users/{uid}", headers=headers,
    )
    if resp.status_code >= 400:
        return None
    try:
        return _validate_email((resp.json() or {}).get("email") or "")
    except ValueError:
        return None


@router.get("/cron/reminders")
async def reminders_cron(authorization: str | None = Header(default=None)):
    """Invoked by an external scheduler (Vercel Cron / GitHub Actions).

    Scans push_subscriptions joined with interactions.remind_at where
    remind_at <= today and status in ('applied','replied','interviewing'),
    sends a Web Push notification to each matching subscription. Falls back
    to a reminder email when the device has no working push subscription.
    Delivered reminders get remind_at cleared so they fire once, not daily;
    gone (404/410) subscriptions are pruned.
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
        from pywebpush import WebPushException, webpush
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
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    resend_from = os.environ.get("RESEND_FROM_EMAIL", "").strip()

    sent, failed, emailed, pruned, skipped = 0, 0, 0, 0, 0
    vapid_claims = {"sub": env["VAPID_SUBJECT"]}

    async with httpx.AsyncClient(timeout=20.0, trust_env=False, follow_redirects=False) as client:
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

        # A reminder can outlive the release surface that originally exposed
        # its target. Keep the user's reminder row intact for a future release,
        # but never send a push/email that points at a now-hidden record.
        # Unknown ids retain the historical behavior (the corpus may be
        # temporarily incomplete during refresh); only known hidden records are
        # skipped by this release gate.
        opportunity_lookup = load_opportunities_by_id()
        sendable_due = []
        for row in due:
            opportunity_id = row["opportunity_id"]
            if (
                opportunity_id in opportunity_lookup
                and release_visible_opportunity_by_id(
                    opportunity_lookup,
                    opportunity_id,
                )
                is None
            ):
                skipped += 1
                continue
            sendable_due.append(row)

        if not sendable_due:
            return {
                "status": "ok",
                "due": len(due),
                "sent": 0,
                "failed": 0,
                "emailed": 0,
                "pruned": 0,
                "skipped": skipped,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        device_ids = list({row["device_id"] for row in sendable_due})
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

        email_by_device: dict[str, str | None] = {}
        now_iso = datetime.now(UTC).isoformat()

        for row in sendable_due:
            device_id = row["device_id"]
            delivered = False
            for sub in list(subs_by_device.get(device_id, [])):
                payload = (
                    '{"title":"Reminder due","body":"You set a follow-up reminder for an application.",'
                    f'"url":"/opportunities/{row["opportunity_id"]}","tag":"reminder-{row["opportunity_id"]}"'
                    "}"
                )
                sub_params = {
                    "device_id": f"eq.{device_id}",
                    "endpoint": f"eq.{sub['endpoint']}",
                }
                try:
                    # The endpoint is a client-persisted URL consumed by this
                    # cron: validate it at send time (public-IP-only DNS,
                    # https, no redirects/proxy) and run the sync pywebpush
                    # call in safe_webpush's bounded executor with a wall-clock
                    # budget — never directly on the event loop.
                    await send_webpush_safely(
                        subscription_info={
                            "endpoint": sub["endpoint"],
                            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                        },
                        data=payload,
                        vapid_private_key=env["VAPID_PRIVATE_KEY"],
                        vapid_claims=vapid_claims,
                        webpush_func=webpush,
                    )
                    sent += 1
                    delivered = True
                    await client.patch(
                        f"{supabase_url}/rest/v1/push_subscriptions",
                        params=sub_params,
                        headers=headers,
                        json={"last_delivered_at": now_iso},
                    )
                except UnsafePushEndpointError:
                    # Junk or an SSRF probe — prune so the cron never
                    # re-attempts it. The reason code never includes the URL.
                    failed += 1
                    await client.delete(
                        f"{supabase_url}/rest/v1/push_subscriptions",
                        params=sub_params,
                        headers=headers,
                    )
                    subs_by_device[device_id].remove(sub)
                    pruned += 1
                except WebPushDeliveryTimeout:
                    failed += 1
                except WebPushException as e:
                    failed += 1
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    if status in (404, 410):
                        await client.delete(
                            f"{supabase_url}/rest/v1/push_subscriptions",
                            params=sub_params,
                            headers=headers,
                        )
                        subs_by_device[device_id].remove(sub)
                        pruned += 1

            if not delivered and resend_key and resend_from:
                if device_id not in email_by_device:
                    email_by_device[device_id] = await _account_email(
                        client, supabase_url, headers, device_id,
                    )
                to_email = email_by_device[device_id]
                if to_email:
                    subject, html, text = _render_reminder_email(row["opportunity_id"])
                    try:
                        _enforce_recipient_quota(to_email)
                        await _send_via_resend(
                            api_key=resend_key, from_addr=resend_from, to=to_email,
                            subject=subject, html=html, text=text,
                        )
                        emailed += 1
                        delivered = True
                    except HTTPException:
                        failed += 1

            if delivered:
                await client.patch(
                    f"{supabase_url}/rest/v1/interactions",
                    params={
                        "device_id": f"eq.{device_id}",
                        "opportunity_id": f"eq.{row['opportunity_id']}",
                    },
                    headers=headers,
                    json={"remind_at": None},
                )

    return {
        "status": "ok",
        "due": len(due),
        "sent": sent,
        "failed": failed,
        "emailed": emailed,
        "pruned": pruned,
        "skipped": skipped,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/push/vapid-public-key")
async def get_vapid_public_key():
    key = os.environ.get("VAPID_PUBLIC_KEY") or os.environ.get("NEXT_PUBLIC_VAPID_PUBLIC_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Push not configured")
    return {"key": key}
