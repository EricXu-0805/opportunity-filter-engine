from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import UTC, date, datetime

from fastapi import APIRouter, Header, HTTPException

from backend.data_loader import load_opportunities_by_id
from backend.lib.release_scope import release_visible_opportunity_by_id
from backend.lib.safe_webpush import (
    WEBPUSH_DEFAULT_TTL_SECONDS,
    UnsafePushEndpointError,
    WebPushDeliveryTimeout,
    derive_push_topic,
    send_webpush_safely,
)
from backend.routes.email import (
    FRONTEND_BASE,
    _enforce_recipient_quota,
    _send_via_resend,
    _validate_email,
    build_idempotency_key,
    classify_send_failure,
)

router = APIRouter()
logger = logging.getLogger("ofe.push")


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


# ---------------------------------------------------------------------------
# W15: notification failures become durable incidents
# ---------------------------------------------------------------------------
# Before this, a failed reminder lived exactly as long as the cron response:
# a counter in JSON that nobody read once the request ended. The same failures
# now also upsert into the ops_incidents queue (migration 027), so an operator
# sees "device X has failed nine nights running" instead of a number that
# resets every night.
#
# Three rules govern everything below.
#
# 1. BEST EFFORT, ALWAYS. Recording an incident must never cost a reminder.
#    Every call is wrapped; a failure only bumps a counter that ships in the
#    cron response.
# 2. NO SECRETS, NO BODIES, NO PII. The push endpoint is a bearer-capability
#    URL and the message body is user content — neither goes into an incident.
#    A truncated SHA-256 fingerprint keeps the same subscription joinable
#    across runs without storing the capability itself.
# 3. LOCAL RPC HELPERS, NOT AN IMPORT. backend.routes.ops imports admin, which
#    imports this module; importing ops here would close the cycle. These few
#    lines of duplication are the price of that acyclic direction.

_ENDPOINT_FINGERPRINT_LEN = 16
_OPEN_INCIDENT_FETCH_LIMIT = 1000


def _endpoint_fingerprint(endpoint: str | None) -> str:
    return hashlib.sha256((endpoint or "").encode("utf-8")).hexdigest()[
        :_ENDPOINT_FINGERPRINT_LEN
    ]


def _provider_error_category(status: int | None) -> str:
    """Coarse, non-identifying bucket for a push provider's rejection."""
    if status is None:
        return "provider_rejected_no_status"
    if status in (404, 410):
        return "subscription_gone"
    if status == 401 or status == 403:
        return "provider_auth_rejected"
    if status == 429:
        return "provider_rate_limited"
    if status >= 500:
        return "provider_error"
    return "provider_rejected"


class _IncidentSink:
    """Best-effort ops_incidents writer for a notification cron.

    Writes exclusively through the SECURITY DEFINER RPCs, so this path can
    record a sighting or a verified recovery but can never set a status,
    assign an owner, or resolve anything (027 core invariant).

    ``scope``/``entity_type`` are parameters rather than constants so the
    saved-search digest cron (W16) can reuse this exact shape instead of
    growing a second, divergent copy — the digest had no durable incident
    record at all until then. The kind stays ``notification_failure`` for both:
    a digest that never reached its recipient is the same class of problem as a
    reminder that didn't.
    """

    def __init__(
        self,
        client,
        supabase_url: str,
        headers: dict,
        *,
        scope: str = "reminders_cron",
        entity_type: str = "reminder",
    ):
        self._client = client
        self._base = supabase_url
        self._headers = headers
        self._scope = scope
        self._entity_type = entity_type
        self.recorded = 0
        self.recovered = 0
        self.errors = 0
        # dedup_keys that already have a live incident. Lets a healthy run
        # skip a recovery RPC per delivered reminder instead of firing one
        # for every device that has never failed.
        self.open_keys: set[str] = set()

    async def load_open_keys(self) -> None:
        try:
            resp = await self._client.get(
                f"{self._base}/rest/v1/ops_incidents",
                params={
                    "select": "dedup_key",
                    "kind": "eq.notification_failure",
                    "scope": f"eq.{self._scope}",
                    "status": "not.in.(resolved,suppressed)",
                    "limit": str(_OPEN_INCIDENT_FETCH_LIMIT),
                },
                headers=self._headers,
            )
            rows = resp.json()
        except Exception:
            # A queue we cannot read simply means no recoveries this run; the
            # reminders themselves are unaffected.
            logger.warning("%s: open-incident prefetch failed", self._scope, exc_info=True)
            return
        if not isinstance(rows, list):
            return
        self.open_keys = {
            row["dedup_key"]
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("dedup_key"), str)
        }

    async def record(
        self,
        dedup_key: str,
        *,
        title: str,
        detail: dict,
        failure_state: str,
        summary: str | None = None,
        priority: str = "normal",
        entity_id: str | None = None,
    ) -> None:
        try:
            resp = await self._client.post(
                f"{self._base}/rest/v1/rpc/record_ops_incident",
                headers=self._headers,
                json={
                    "p_kind": "notification_failure",
                    "p_dedup_key": dedup_key,
                    "p_title": title,
                    "p_summary": summary,
                    "p_detail": detail,
                    "p_scope": self._scope,
                    "p_priority": priority,
                    "p_failure_state": failure_state,
                    "p_entity_type": self._entity_type if entity_id else None,
                    "p_entity_id": entity_id,
                    "p_field": None,
                },
            )
            if getattr(resp, "status_code", 500) >= 400:
                self.errors += 1
                logger.error(
                    "%s: incident record rejected (%s)", self._scope, resp.status_code
                )
                return
        except Exception:
            self.errors += 1
            logger.warning("%s: incident record failed", self._scope, exc_info=True)
            return
        self.recorded += 1
        self.open_keys.add(dedup_key)

    async def recover(self, dedup_key: str, note: str) -> None:
        """Record a verified success against a live incident.

        Only fires when this dedup_key actually has an open incident — a
        reminder that was never broken has nothing to recover. auto_resolve
        is true here because the evidence IS the outcome: the notification
        this incident is about was delivered.
        """
        if dedup_key not in self.open_keys:
            return
        try:
            resp = await self._client.post(
                f"{self._base}/rest/v1/rpc/record_ops_recovery",
                headers=self._headers,
                json={"p_dedup_key": dedup_key, "p_auto_resolve": True, "p_note": note},
            )
            if getattr(resp, "status_code", 500) >= 400:
                self.errors += 1
                logger.error(
                    "%s: incident recovery rejected (%s)", self._scope, resp.status_code
                )
                return
        except Exception:
            self.errors += 1
            logger.warning("%s: incident recovery failed", self._scope, exc_info=True)
            return
        self.recovered += 1
        self.open_keys.discard(dedup_key)


# ---------------------------------------------------------------------------
# W16: a timed-out push is AMBIGUOUS, not failed
# ---------------------------------------------------------------------------
# W14 established the acknowledgment ordering (clear remind_at only after the
# provider accepts). It left one window open: `WebPushDeliveryTimeout` is a
# wall-clock deadline on OUR side, and it says nothing about whether the push
# service accepted the message. Treating that as a plain failure double-notified
# the user twice over — the email fallback fired in the SAME run, and the
# retained remind_at re-sent the push the NEXT night.
#
# Three outcomes, not two:
#
#   delivered  the provider returned success. Clear remind_at, recover the
#              incident, no fallback.
#   ambiguous  the deadline expired with no answer. It may already be in the
#              user's notification tray.
#   failed     the provider (or our own validation) definitively rejected it.
#              Nothing was delivered; a fallback and a retry are both safe.
#
# What ambiguity buys:
#
# 1. NO SAME-RUN EMAIL FALLBACK. A second channel cannot "compensate" for a
#    send whose outcome is unknown — that is how one reminder becomes a push
#    AND an email. The fallback exists for a KNOWN non-delivery.
# 2. remind_at IS RETAINED (at-least-once, deliberately). The alternative —
#    clearing it — would be at-most-once and would silently drop reminders that
#    genuinely never arrived, which is the worse failure for a feature whose
#    entire job is to remind. Retaining it means the reminder is re-sent
#    tomorrow, and the RFC 8030 Topic below makes that re-send REPLACE any
#    still-pending copy at the push service rather than stack on it. So the
#    duplicate risk is bounded to "the first copy was already delivered to the
#    device", while a lost reminder is impossible. At-least-once wins.
# 3. THE INCIDENT SAYS SO. The queue records the outcome as ambiguous, so an
#    operator triaging it knows the user may have received it — the difference
#    between "resend this" and "do not resend this".
#
# Note on failure_state: migration 031 constrains it to
# (failed|timed_out|blocked|partial|recovered), and adding a value is a
# migration this change deliberately does not make. 'timed_out' is the exact
# truth about what we observed; the ambiguity of the OUTCOME lives in the
# detail payload (`outcome`, `may_have_been_delivered`).

_AMBIGUOUS_OUTCOME = "ambiguous"


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
    remind_at <= today and status in
    ('contacted','applied','replied','interviewing'),
    sends a Web Push notification to each matching subscription. Falls back
    to a reminder email when the device has no working push subscription and
    the push outcome is KNOWN to be a non-delivery (an ambiguous outcome is
    never compensated by a second channel — see the W16 block above).
    Provider-accepted reminders get remind_at cleared so they fire once, not
    daily; gone (404/410) subscriptions are pruned.

    Every failure path also upserts a notification_failure incident into the
    W15 ops queue (see _IncidentSink) and every verified delivery records a
    recovery against it, so a repeatedly failing reminder is visible to an
    operator instead of only to this run's counters. That path is strictly
    best-effort: ``incident_errors`` in the response counts the times it
    could not be written, and the counters remain authoritative.
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
    # Subset of `failed` whose outcome is genuinely unknown (W16). `failed`
    # stays the "we did not see an acceptance" counter that operator alerting
    # is built on; `ambiguous` is the part of it that may nonetheless have
    # reached the user, and therefore was NOT compensated by an email.
    ambiguous = 0
    vapid_claims = {"sub": env["VAPID_SUBJECT"]}

    async with httpx.AsyncClient(timeout=20.0, trust_env=False, follow_redirects=False) as client:
        r = await client.get(
            f"{supabase_url}/rest/v1/interactions",
            params={
                "select": "device_id,opportunity_id,remind_at,interaction_type,notes",
                "remind_at": f"lte.{today}",
                # 'contacted' joined the status set in W12 (cold-email
                # confirm-sent + follow-up chips write it) — its reminders
                # must fire like any other.
                "interaction_type": "in.(contacted,applied,replied,interviewing)",
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
                "ambiguous": 0,
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

        # One read of the live notification-failure queue, after the
        # nothing-due early return so a quiet night costs nothing extra.
        incidents = _IncidentSink(client, supabase_url, headers)
        await incidents.load_open_keys()

        bookkeeping_failed = 0
        row_errors = 0
        for row in sendable_due:
          # Per-row isolation (W14): one row's transport/Supabase error must
          # not abort the batch — remaining reminders still get their shot,
          # and an already-delivered-but-uncleared row is at worst retried
          # tomorrow (at-least-once, never lost). Iterates sendable_due — the
          # release gate above already excluded rows whose opportunity is no
          # longer visible (this branch), and those are counted in `skipped`.
          try:
            device_id = row["device_id"]
            opportunity_id = row["opportunity_id"]
            # Two identities per reminder: the delivery attempt itself, and
            # the bookkeeping that must follow a delivery. They fail for
            # different reasons and are fixed differently, so they are
            # different incidents.
            delivery_key = f"notification_failure:{device_id}:{opportunity_id}"
            bookkeeping_key = (
                f"notification_failure:bookkeeping:{device_id}:{opportunity_id}"
            )
            entity_id = f"{device_id}:{opportunity_id}"
            delivered = False
            row_ambiguous = False
            # One reminder = one notification identity. The service-worker
            # `tag` collapses duplicates that are already on screen; the RFC
            # 8030 Topic (derived from the same identity, hashed into the
            # spec's 32-char URL-safe base64 budget) collapses them a layer
            # earlier — a re-send REPLACES the copy still pending at the push
            # service. That is what makes the at-least-once retry above safe.
            topic = derive_push_topic(f"reminder-{opportunity_id}")
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
                        # Replace-not-stack identity + a bounded lifetime, so a
                        # message the device never picked up cannot resurface
                        # days later next to its own replacement.
                        headers={"Topic": topic},
                        ttl=WEBPUSH_DEFAULT_TTL_SECONDS,
                    )
                    sent += 1
                    delivered = True
                    # The provider ACCEPTED it (accepted ≠ shown to the user;
                    # nothing here tracks display or opens): verified evidence
                    # that any open incident for this reminder is over.
                    await incidents.recover(delivery_key, "push service accepted the message")
                    stamp = await client.patch(
                        f"{supabase_url}/rest/v1/push_subscriptions",
                        params=sub_params,
                        headers=headers,
                        # NAMING: the column reads `last_delivered_at`, but what
                        # is stamped here is the last time the push service
                        # ACCEPTED a message for this subscription. Renaming the
                        # column needs a migration; until then this comment is
                        # the column's true definition.
                        json={"last_delivered_at": now_iso},
                    )
                    if stamp.status_code >= 400:
                        # Cosmetic stamp — log, don't fail the row.
                        bookkeeping_failed += 1
                        logger.error(
                            "reminders cron: last_delivered_at stamp failed (%s)",
                            stamp.status_code,
                        )
                        await incidents.record(
                            bookkeeping_key,
                            title="Reminder bookkeeping write failed",
                            summary="delivery stamp (last_delivered_at) rejected by storage",
                            detail={
                                "stage": "delivery_stamp",
                                "error_category": "bookkeeping_write_failed",
                                "http_status": stamp.status_code,
                                "endpoint_fingerprint": _endpoint_fingerprint(
                                    sub.get("endpoint")
                                ),
                                "provider_accepted": True,
                            },
                            # 'partial': the notification WAS accepted, only
                            # the record of it failed.
                            failure_state="partial",
                            entity_id=entity_id,
                        )
                except UnsafePushEndpointError as e:
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
                    await incidents.record(
                        delivery_key,
                        title="Push endpoint rejected by the outbound-network policy",
                        summary="subscription pruned; endpoint failed send-time validation",
                        detail={
                            "error_category": "unsafe_endpoint",
                            "reason": getattr(e, "reason", None),
                            "endpoint_fingerprint": _endpoint_fingerprint(
                                sub.get("endpoint")
                            ),
                            "pruned": True,
                        },
                        failure_state="blocked",
                        entity_id=entity_id,
                    )
                except WebPushDeliveryTimeout:
                    # AMBIGUOUS, not failed (W16). Our deadline expired; the
                    # push service may have accepted the message before it did.
                    # Counted in `failed` (it is still "no acknowledgment", the
                    # thing alerting watches) and separately as `ambiguous`.
                    failed += 1
                    ambiguous += 1
                    row_ambiguous = True
                    await incidents.record(
                        delivery_key,
                        title="Web Push outcome unknown (delivery timed out)",
                        summary=(
                            "dispatcher exceeded its wall-clock budget; the push "
                            "service may already have accepted the message"
                        ),
                        detail={
                            "error_category": "delivery_timeout",
                            # The outcome, distinct from the observation.
                            # failure_state can only be one of migration 031's
                            # five values, so the ambiguity is recorded here.
                            "outcome": _AMBIGUOUS_OUTCOME,
                            "may_have_been_delivered": True,
                            # No second channel was used: an ambiguous push is
                            # never "compensated" by an email in the same run.
                            "email_fallback_suppressed": True,
                            "remind_at_retained": True,
                            "retry_semantics": "at_least_once_topic_collapsed",
                            "push_topic": topic,
                            "provider_status": None,
                            "endpoint_fingerprint": _endpoint_fingerprint(
                                sub.get("endpoint")
                            ),
                            "pruned": False,
                        },
                        failure_state="timed_out",
                        entity_id=entity_id,
                    )
                except WebPushException as e:
                    failed += 1
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    gone = status in (404, 410)
                    if gone:
                        await client.delete(
                            f"{supabase_url}/rest/v1/push_subscriptions",
                            params=sub_params,
                            headers=headers,
                        )
                        subs_by_device[device_id].remove(sub)
                        pruned += 1
                    await incidents.record(
                        delivery_key,
                        title="Web Push delivery rejected by the provider",
                        summary=f"provider responded {status}" if status else
                                "provider rejected the push with no status",
                        detail={
                            # The provider's status was read and thrown away
                            # before W15; it is the single most useful field
                            # for triage, so it is preserved here.
                            "provider_status": status,
                            "error_category": _provider_error_category(status),
                            "endpoint_fingerprint": _endpoint_fingerprint(
                                sub.get("endpoint")
                            ),
                            "pruned": gone,
                        },
                        failure_state="blocked" if status in (401, 403) else "failed",
                        entity_id=entity_id,
                    )

            # `not row_ambiguous` is the W16 rule: the fallback compensates a
            # KNOWN non-delivery (no subscription, pruned endpoint, provider
            # rejection). When the push outcome is unknown, adding a second
            # channel is how one reminder becomes two notifications.
            if not delivered and not row_ambiguous and resend_key and resend_from:
                if device_id not in email_by_device:
                    email_by_device[device_id] = await _account_email(
                        client, supabase_url, headers, device_id,
                    )
                to_email = email_by_device[device_id]
                if to_email:
                    subject, html, text = _render_reminder_email(row["opportunity_id"])
                    # One reminder for one device on one day is ONE logical
                    # send, however many times the cron retries it. Deriving
                    # the key from that identity (never generating one per
                    # attempt) is what makes a retry after an ambiguous Resend
                    # failure a no-op at the provider instead of a second
                    # email. The date is the natural window: tomorrow's
                    # reminder for the same row is a different send.
                    fallback_key = build_idempotency_key(
                        "reminder", device_id, opportunity_id, today,
                    )
                    try:
                        _enforce_recipient_quota(to_email)
                        await _send_via_resend(
                            api_key=resend_key, from_addr=resend_from, to=to_email,
                            subject=subject, html=html, text=text,
                            idempotency_key=fallback_key,
                        )
                        emailed += 1
                        delivered = True
                        await incidents.recover(
                            delivery_key, "email fallback accepted by the provider"
                        )
                    except Exception as e:
                        # HTTPException (quota/Resend 4xx) AND transport
                        # errors (httpx timeout in _send_via_resend or
                        # _account_email) — the fallback is best-effort and
                        # must never abort the cron (W14).
                        failed += 1
                        outcome = classify_send_failure(e)
                        if outcome == _AMBIGUOUS_OUTCOME:
                            ambiguous += 1
                        await incidents.record(
                            delivery_key,
                            title=(
                                "Reminder email fallback outcome unknown"
                                if outcome == _AMBIGUOUS_OUTCOME
                                else "Reminder email fallback failed"
                            ),
                            summary=(
                                "no push acknowledgment and the email fallback's "
                                "outcome is unknown (it may have been accepted)"
                                if outcome == _AMBIGUOUS_OUTCOME
                                else "no push acknowledgment and the email fallback failed"
                            ),
                            detail={
                                "error_category": "email_fallback_failed",
                                "outcome": outcome,
                                "may_have_been_delivered": outcome == _AMBIGUOUS_OUTCOME,
                                # The retry next run reuses this exact key, so
                                # the provider collapses it if it did land.
                                "idempotency_key": fallback_key,
                                # Type only: the message can carry the
                                # recipient address or provider payload.
                                "exception_type": type(e).__name__,
                                "http_status": getattr(e, "status_code", None),
                            },
                            failure_state="failed",
                            entity_id=entity_id,
                        )

            if delivered:
                # Only a provider-ACCEPTED send reaches here — never an
                # ambiguous one. An ambiguous reminder keeps its remind_at and
                # fires again tomorrow (at-least-once by choice: see the W16
                # block above — the Topic makes the repeat replace a pending
                # copy, whereas clearing it here would silently lose reminders
                # that never arrived).
                # One-shot semantics live or die on this PATCH: if it fails
                # silently the user gets the same reminder every day. Verify,
                # retry once, then log loudly so the operator alert fires on
                # the response counter (W14).
                cleared = await client.patch(
                    f"{supabase_url}/rest/v1/interactions",
                    params={
                        "device_id": f"eq.{device_id}",
                        "opportunity_id": f"eq.{row['opportunity_id']}",
                    },
                    headers=headers,
                    json={"remind_at": None},
                )
                if cleared.status_code >= 400:
                    cleared = await client.patch(
                        f"{supabase_url}/rest/v1/interactions",
                        params={
                            "device_id": f"eq.{device_id}",
                            "opportunity_id": f"eq.{row['opportunity_id']}",
                        },
                        headers=headers,
                        json={"remind_at": None},
                    )
                if cleared.status_code >= 400:
                    bookkeeping_failed += 1
                    logger.error(
                        "reminders cron: remind_at clear failed twice (%s) — "
                        "reminder will refire tomorrow",
                        cleared.status_code,
                    )
                    await incidents.record(
                        bookkeeping_key,
                        title="Reminder bookkeeping write failed",
                        summary="remind_at clear failed twice; the reminder will refire",
                        detail={
                            "stage": "remind_at_clear",
                            "error_category": "bookkeeping_write_failed",
                            "http_status": cleared.status_code,
                            "attempts": 2,
                            "consequence": "reminder refires until the clear succeeds",
                            "provider_accepted": True,
                        },
                        failure_state="partial",
                        entity_id=entity_id,
                    )
                else:
                    await incidents.recover(
                        bookkeeping_key, "remind_at cleared after provider acceptance"
                    )
          except Exception as e:
            row_errors += 1
            logger.exception("reminders cron: row failed; continuing batch")
            # The row blew up somewhere unexpected: record it against the
            # reminder's identity so a systematically broken row is visible
            # after the run, not just in the logs.
            hint_device = row.get("device_id") if isinstance(row, dict) else None
            hint_opp = row.get("opportunity_id") if isinstance(row, dict) else None
            await incidents.record(
                f"notification_failure:{hint_device or 'unknown'}:{hint_opp or 'unknown'}",
                title="Reminder row failed with an unexpected error",
                summary="row isolated; remaining reminders continued",
                detail={
                    "error_category": "row_exception",
                    # Type only — an exception message can carry the endpoint,
                    # the recipient address, or a provider payload.
                    "exception_type": type(e).__name__,
                },
                failure_state="failed",
                entity_id=(
                    f"{hint_device}:{hint_opp}" if hint_device and hint_opp else None
                ),
            )

    return {
        "status": "ok",
        "due": len(due),
        # `sent` counts provider ACCEPTANCES, not deliveries to a screen.
        "sent": sent,
        "failed": failed,
        # Subset of `failed` with an unknown outcome (W16): no email fallback
        # was attempted for these, and their remind_at was retained.
        "ambiguous": ambiguous,
        "emailed": emailed,
        "pruned": pruned,
        "skipped": skipped,
        "bookkeeping_failed": bookkeeping_failed,
        "row_errors": row_errors,
        # W15 ops-queue bookkeeping. incident_errors > 0 means failures
        # happened that did NOT reach the operator queue — the counters above
        # remain the source of truth for this run.
        "incidents_recorded": incidents.recorded,
        "incidents_recovered": incidents.recovered,
        "incident_errors": incidents.errors,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/push/vapid-public-key")
async def get_vapid_public_key():
    key = os.environ.get("VAPID_PUBLIC_KEY") or os.environ.get("NEXT_PUBLIC_VAPID_PUBLIC_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Push not configured")
    return {"key": key}
