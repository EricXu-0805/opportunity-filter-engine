"""Cron route for refreshing saved-search match-sets server-side.

Invoked by .github/workflows/saved-searches-refresh.yml (GH Actions
schedule, plus workflow_dispatch). Walks every row in saved_searches,
recomputes the current match-set against opportunities.json, and writes
back last_run_at + last_result_ids + new_match_ids.

Auth: same Bearer CRON_SECRET pattern as push.py /cron/reminders.
Supabase access: SERVICE_ROLE_KEY (bypasses RLS — required since cron
operates on every user's rows).

This route returns quickly even with thousands of saved searches because
the filter is a pure Python pass over the in-memory opportunities list;
the per-row supabase PATCH dominates wall time and is the obvious place
to add concurrency if scale ever requires it.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse

from backend.data_loader import load_opportunities
from backend.lib.release_scope import (
    opportunity_visible_in_release,
    release_visible_opportunities,
)
from backend.lib.target_actionability import actionable_opportunities
from backend.routes.email import (
    FRONTEND_BASE,
    _describe,
    _enforce_recipient_quota,
    _html_escape,
    _restore_signing_secret,
    _send_via_resend,
    _validate_email,
    build_idempotency_key,
    classify_send_failure,
)
from backend.routes.push import _IncidentSink, _required_env, _verify_cron_secret
from src.evidence import is_actionable_target
from src.matcher.ranker import _filter_context, hard_exclusion
from src.saved_searches.filter import matching_ids

router = APIRouter()
logger = logging.getLogger(__name__)


SUPABASE_BATCH_LIMIT = 1000

# Unsubscribe links must point at THIS service (the endpoint flips the
# Supabase row server-side), unlike FRONTEND_BASE links. Render injects
# RENDER_EXTERNAL_URL automatically; PUBLIC_BACKEND_URL is the manual
# override, and the hardcoded prod URL mirrors api-server.ts's fallback.
BACKEND_BASE = (
    os.environ.get("PUBLIC_BACKEND_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or "https://opportunity-filter-engine-api.onrender.com"
).rstrip("/")

DIGEST_MAX_ITEMS = 10
DIGEST_MIN_INTERVAL_DAYS = 7
# new_match_ids accumulates across nightly refreshes until a digest goes out
# (the digest is throttled to one per 7 days, so overwriting nightly would
# silently drop ~6/7 of a week's matches). The cap keeps the row bounded;
# oldest ids age out first.
NEW_MATCH_IDS_CAP = 200
# Unsubscribe must keep working long after the email lands (CAN-SPAM floor
# is 30 days; a year covers any realistic inbox archaeology) — deliberately
# much longer than the restore-link TTL.
DIGEST_UNSUB_TTL_DAYS = 365

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# ---------------------------------------------------------------------------
# W16: digest sends are idempotent, their failures are classified and durable
# ---------------------------------------------------------------------------
# The digest's throttle is a post-send stamp (last_digest_sent_at). If the send
# raises, the stamp never happens and the next nightly run re-sends the whole
# digest — correct when the send definitively failed, a duplicate email when it
# only LOOKED like it failed (a read timeout after Resend accepted it).
#
#  * Every send now carries an Idempotency-Key derived from (search, day), so a
#    same-day retry is collapsed by the provider rather than delivered twice.
#    Resend retains a key for ~24h, which is exactly the window a same-day
#    retry needs; a legitimate next-week digest is a different key by
#    construction (the 7-day throttle guarantees the dates differ).
#  * Failures are classified ambiguous vs definitive in the error string, so an
#    operator reading the cron response can tell "this did not go out" from
#    "this may have gone out" without guessing from an exception name.
#  * Failures also land in the ops_incidents queue via the same _IncidentSink
#    the reminders cron uses (W15 gave push.py durable incident records; the
#    digest had none). Best-effort throughout: recording never breaks the cron.
#
# Residual, deliberately not hidden: an ambiguous failure still retries on the
# NEXT night, which is outside the provider's 24h key window — so a duplicate
# remains possible there. Stamping last_digest_sent_at on ambiguity would trade
# that for silently skipping a week's digest that never arrived; for an opt-in
# weekly summary, the visible-and-recorded duplicate is the better failure.
_DIGEST_INCIDENT_SCOPE = "digest_cron"


def _sign_digest_unsub(search_id: str, ts: int) -> str:
    """Same HMAC-SHA256 construction as email.py's restore token, with a
    distinct context prefix so digest tokens can never be replayed as
    restore tokens (and vice versa) under the shared RESTORE_LINK_SECRET.
    """
    secret = _restore_signing_secret().encode()
    if not secret:
        return ""
    msg = f"digest-unsub|{search_id}|{ts}".encode()
    return hmac.new(secret, msg, hashlib.sha256).digest()[:16].hex()


def _build_unsubscribe_url(search_id: str) -> str | None:
    ts = int(time.time())
    sig = _sign_digest_unsub(search_id, ts)
    if not sig:
        return None
    return f"{BACKEND_BASE}/api/email/digest-unsubscribe?sid={search_id}&t={ts}&s={sig}"


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# CAN-SPAM: a recurring opt-in digest must carry the sender's physical postal
# address. Kept in an env var (set on Render once there's a mailing address /
# PO box) so we never ship a placeholder or a hard-coded home address; the line
# is simply omitted until it's set.
_POSTAL_ADDRESS = os.environ.get("EMAIL_POSTAL_ADDRESS", "").strip()


def _digest_footer_html(search_name: str, unsubscribe_url: str) -> str:
    addr = (f'<div style="margin-top:6px">{_html_escape(_POSTAL_ADDRESS)}</div>'
            if _POSTAL_ADDRESS else "")
    return (
        '<hr style="border:none;border-top:1px solid #eee;margin:28px 0 14px">'
        '<p style="color:#9ca3af;font-size:11px;line-height:1.6;margin:0">'
        'JoinALab · research opportunity matching<br>'
        f'You opted in to this weekly digest when you saved "{_html_escape(search_name)}". '
        f'<a href="{_html_escape(unsubscribe_url)}" style="color:#4f46e5">Unsubscribe</a> · '
        f'<a href="{FRONTEND_BASE}/favorites" style="color:#4f46e5">Manage saved searches</a>'
        f'{addr}'
        '</p>'
    )


def _digest_footer_text(search_name: str, unsubscribe_url: str) -> str:
    addr = f"{_POSTAL_ADDRESS}\n" if _POSTAL_ADDRESS else ""
    return (
        "\n---\nJoinALab · research opportunity matching\n"
        f'You opted in to this weekly digest when you saved "{search_name}".\n'
        f"Unsubscribe: {unsubscribe_url}\n"
        f"Manage saved searches: {FRONTEND_BASE}/favorites\n"
        f"{addr}"
    )


def _render_digest_email(
    search_name: str, items: list[dict], unsubscribe_url: str, overflow: int = 0,
) -> tuple[str, str, str]:
    # Subject counts the whole batch, not just the rendered rows — a week can
    # accumulate more matches than the email shows.
    count = len(items) + overflow
    subject = (
        f"1 new match for \"{search_name}\"" if count == 1
        else f"{count} new matches for \"{search_name}\""
    )
    rows_html = []
    rows_text = []
    for i, opp in enumerate(items, 1):
        faculty_contact = opp.get("source_type") == "faculty_research"
        # One describer for every digest we send, imported rather than
        # reimplemented. `_describe` applies the exact pipeline the manual
        # digests use — safe_public_text(neutralize_lifecycle_title(
        # displayed_title(opp), opp)) for the title, the same organization and
        # deadline boundary, and the research-inactive advisory. Keeping a
        # second copy here is precisely how the two drifted: this one printed
        # the raw title and dropped the advisory entirely.
        described = _describe(opp)
        # The "Untitled" fallback stays where it was — for a record with no
        # title at all. A redacted title is still a title.
        title = described["title"] or (
            "Untitled faculty contact" if faculty_contact else "Untitled opportunity"
        )
        org = described["organization"]
        deadline = described["deadline"] or ""
        # "due" is a claim. An NSF REU date is derived from the award start and
        # stamped an estimate; the app renders it "· estimated" and refuses to
        # call it passed, so the digest must not upgrade it to a due date.
        dl_str = (
            f" · estimated {deadline}"
            if deadline and described.get("deadline_is_estimate")
            else f" · due {deadline}" if deadline else ""
        )
        kind_str = (
            "Faculty contact profile · current opening not confirmed"
            if faculty_contact
            else "Opportunity listing"
        )
        # A warning, not a refusal. "I have no active research right now" is a
        # different statement from "do not ask me": the row stays actionable
        # and stays in the digest. What it must not do is arrive unqualified,
        # which is exactly what this digest did while the manual one said so.
        advisory = described["advisory"]
        # Percent-encoded, because the id is going into a URL PATH. HTML
        # escaping is a different job and never was one — it leaves a space or
        # a `#` intact, and the plain-text part is not escaped at all. 217 of
        # the visible+actionable records carry such ids (`faculty-art &
        # design-…`, `faculty-social work-…`), so those links arrived broken
        # or truncated at the fragment. safe='' on purpose: a `/` inside an id
        # is data, not a path separator.
        detail_url = f"{FRONTEND_BASE}/opportunities/{quote(str(opp.get('id', '')), safe='')}"
        advisory_html = (
            f'<div style="font-size:12px;color:#b45309;margin-top:4px">'
            f'{_html_escape(advisory)}</div>'
            if advisory else ""
        )
        rows_html.append(
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #eee">'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'<a href="{_html_escape(detail_url)}" style="color:#4f46e5;text-decoration:none">{_html_escape(title)}</a>'
            f'</div>'
            f'<div style="font-size:12px;color:#9ca3af">{_html_escape(kind_str)} · {_html_escape(org)}{_html_escape(dl_str)}</div>'
            f'{advisory_html}'
            f'</td></tr>'
        )
        advisory_text = f"  {advisory}\n" if advisory else ""
        rows_text.append(
            f"#{i} {title}\n  {kind_str} · {org}{dl_str}\n{advisory_text}  {detail_url}\n"
        )

    overflow_html = (
        f'<p style="color:#6b7280;font-size:13px;margin:14px 0 0">+{overflow} more in the app</p>'
        if overflow > 0 else ""
    )
    overflow_text = f"+{overflow} more in the app\n" if overflow > 0 else ""

    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;margin:0 auto;background:white">
  <tr><td style="height:4px;background:#4f46e5;font-size:0;line-height:0">&nbsp;</td></tr>
  <tr><td style="padding:32px 28px">
    <div style="font-size:22px;font-weight:700;color:#4f46e5;letter-spacing:-0.5px">JoinALab</div>
    <div style="font-size:12px;color:#9ca3af;margin-top:2px">Research opportunity matching</div>
    <h1 style="font-size:22px;margin:24px 0 6px;color:#111827">{_html_escape(subject)}</h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 18px">
      New listings and faculty contact profiles that started matching your saved search since we last checked. Faculty profiles do not confirm a current opening.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">
      {''.join(rows_html)}
    </table>
    {overflow_html}
    <a href="{FRONTEND_BASE}/favorites" style="display:inline-block;margin-top:24px;padding:11px 22px;background:#4f46e5;color:white;text-decoration:none;border-radius:8px;font-weight:600;font-size:14px">View all in JoinALab</a>
    {_digest_footer_html(search_name, unsubscribe_url)}
  </td></tr>
</table>
</body></html>"""

    text = (
        f"{subject}\n\n"
        + "".join(rows_text)
        + overflow_text
        + f"\nView all: {FRONTEND_BASE}/favorites\n"
        + _digest_footer_text(search_name, unsubscribe_url)
    )
    return subject, html, text


# The digest and the site disagreed about what "in your results" means.
# ranker.hard_exclusion calls itself "the single reason-coded implementation of
# every rule that drops a record from a profile's result universe" and lists its
# consumers; this cron was not one of them. It built the universe from release
# scope and target truth alone — both profile-independent — so no profile-
# dependent rule ever ran. Replaying the real path for a JHU profile, 2,085 of
# 3,122 matched ids (66.8%) were records the site would never show that student:
# Berkeley campus-only programs, each linking to a detail page that renders fine.
#
# filter.py's docstring said this was unavoidable — "Scoring requires the user's
# profile, which the cron doesn't have access to (and we don't want to
# denormalise the profile into saved_searches)". The first half is stale:
# saved_searches.device_id IS profiles.id (both auth.uid()::text), so the cron
# can read the profile it needs with one keyed lookup and no new column.
async def _ineligible_ids_by_device(
    client, supabase_url: str, headers: dict, corpus: list[dict], device_ids: list[str],
) -> dict[str, set[str]]:
    """For each device, the corpus ids its own profile excludes.

    A POSITIVE set of known-ineligible ids, deliberately shaped like
    hidden_opportunity_ids above and for the same reason: built over the whole
    corpus, so "absent from tonight's load" can never be mistaken for "not for
    you". A negative test against the eligible set would empty a student's
    pending queue on any night a shard failed to load.

    A profile that cannot be read yields an empty set — the digest then behaves
    exactly as it does today rather than filtering on a guess.
    """
    wanted = sorted({d for d in device_ids if d})
    if not wanted:
        return {}
    try:
        resp = await client.get(
            f"{supabase_url}/rest/v1/profiles",
            params={
                "select": "id,profile_data",
                "id": f"in.({','.join(wanted)})",
            },
            headers=headers,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:  # noqa: BLE001 - a read failure must not stop the run
        logger.warning("saved-search profiles unreadable, sending unfiltered: %s", exc)
        return {}

    # Students share contexts — one school, cross-school off — so the corpus
    # sweep runs once per distinct context rather than once per row.
    by_context: dict[tuple, set[str]] = {}
    out: dict[str, set[str]] = {}
    for row in rows:
        device_id = row.get("id")
        profile = row.get("profile_data")
        if not device_id or not isinstance(profile, dict):
            continue
        ctx = _filter_context(profile)
        key = (
            ctx.home_school, ctx.hide_cross_school, ctx.exclude_citizenship_restricted,
            ctx.international_student, frozenset(ctx.seeking),
            frozenset(ctx.student_majors_norm), frozenset(ctx.related_majors_norm),
        )
        cached = by_context.get(key)
        if cached is None:
            cached = {
                opportunity["id"]
                for opportunity in corpus
                if opportunity.get("id") and hard_exclusion(opportunity, ctx)
            }
            by_context[key] = cached
        out[device_id] = cached
    return out


@router.get("/cron/saved-searches/refresh")
async def saved_searches_refresh(authorization: str | None = Header(default=None)):
    """Re-run every saved search against current opportunities.json.

    For each saved_searches row:
      - compute current match IDs (filter + query text search)
      - diff against prior last_result_ids to find new matches
      - PATCH the row with last_run_at / last_result_ids / new_match_ids,
        where new_match_ids accumulates until the digest sends (and clears it)
    """
    _verify_cron_secret(authorization)

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "skipped", "reason": "supabase env not configured", "missing": missing}
    env = env_result

    try:
        import httpx
    except ImportError:
        return {"status": "skipped", "reason": "httpx not installed"}

    corpus = load_opportunities()
    if not corpus:
        return {"status": "skipped", "reason": "no opportunities loaded"}
    opportunities = actionable_opportunities(release_visible_opportunities(corpus))
    # Ids the queue must stop carrying: hidden by release scope, or stated
    # closed / reference-only / inactive / not-accepting by the source.
    #
    # Known-and-dead, not merely absent. An id the corpus no longer contains is
    # deliberately NOT here — a shard that failed to load, or a record between
    # refreshes, would otherwise silently empty a student's pending queue, and
    # "we cannot see it right now" is not evidence that it ended. Those stay
    # queued and simply do not render.
    hidden_opportunity_ids = {
        opportunity["id"]
        for opportunity in corpus
        if opportunity.get("id")
        and (
            not opportunity_visible_in_release(opportunity)
            or not is_actionable_target(opportunity)
        )
    }

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    processed = 0
    total_new_matches = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=False) as client:
        list_resp = await client.get(
            f"{supabase_url}/rest/v1/saved_searches",
            params={
                "select": "id,device_id,filters_json,query,last_result_ids,new_match_ids,last_run_at",
                "limit": str(SUPABASE_BATCH_LIMIT),
                "order": "last_run_at.asc.nullsfirst",
            },
            headers=headers,
        )
        list_resp.raise_for_status()
        rows = list_resp.json()
        if not rows:
            return {"status": "ok", "processed": 0, "new_matches": 0}

        ineligible_by_device = await _ineligible_ids_by_device(
            client, supabase_url, headers, corpus,
            [row.get("device_id") for row in rows],
        )

        now_iso = datetime.now(UTC).isoformat()

        for row in rows:
            try:
                ineligible = ineligible_by_device.get(row.get("device_id") or "", set())
                filters = row.get("filters_json") or {}
                query = row.get("query") or ""
                prior_ids = set(row.get("last_result_ids") or [])
                pending_ids = [
                    opportunity_id
                    for opportunity_id in (row.get("new_match_ids") or [])
                    if opportunity_id not in hidden_opportunity_ids
                    # Positive set, same as hidden_opportunity_ids: an id this
                    # student's profile excludes goes, an id tonight's corpus
                    # simply could not see stays.
                    and opportunity_id not in ineligible
                ]

                current_ids = [
                    oid for oid in matching_ids(opportunities, filters, query)
                    if oid not in ineligible
                ]
                # A search that has never run has no prior set to diff against
                # — last_result_ids defaults to '{}' — so everything it matches
                # looked new. The first digest went out hours after the search
                # was created, titled "200 new matches", under copy reading
                # "that started matching your saved search since we last
                # checked". Nothing had started matching anything. The first
                # run establishes the baseline instead; the next one reports
                # against it.
                first_run = not row.get("last_run_at")
                new_ids = (
                    []
                    if first_run
                    else [oid for oid in current_ids if oid not in prior_ids]
                )
                total_new_matches += len(new_ids)

                pending_set = set(pending_ids)
                accumulated = (
                    pending_ids + [oid for oid in new_ids if oid not in pending_set]
                )[-NEW_MATCH_IDS_CAP:]

                patch_body = {
                    "last_run_at": now_iso,
                    "last_result_ids": current_ids,
                    "new_match_ids": accumulated,
                }
                patch_resp = await client.patch(
                    f"{supabase_url}/rest/v1/saved_searches",
                    params={"id": f"eq.{row['id']}"},
                    headers=headers,
                    json=patch_body,
                )
                patch_resp.raise_for_status()
                processed += 1
            except Exception as e:  # noqa: BLE001 — keep cron iterating
                errors.append(f"{row.get('id', '?')}: {type(e).__name__}: {e}")

    return {
        "status": "ok" if not errors else "partial",
        "processed": processed,
        "new_matches": total_new_matches,
        "errors": errors[:10],
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/cron/saved-searches/digest")
async def saved_searches_digest(authorization: str | None = Header(default=None)):
    """Weekly opt-in email digest of new saved-search matches.

    Invoked by the same workflow as /cron/saved-searches/refresh, right
    after it (so new_match_ids is fresh). For every row with
    digest_opt_in=true, a digest_email, and unseen new matches, sends ONE
    email via the email.py Resend machinery — throttled to at most one
    digest per search per DIGEST_MIN_INTERVAL_DAYS via last_digest_sent_at.
    No email is ever sent without the explicit opt-in flag.
    """
    _verify_cron_secret(authorization)

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "skipped", "reason": "supabase env not configured", "missing": missing}
    env = env_result

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_addr = os.environ.get("RESEND_FROM_EMAIL", "").strip()
    if not api_key or not from_addr:
        logger.info("digest cron: RESEND_API_KEY / RESEND_FROM_EMAIL unset — skipping sends")
        return {"status": "skipped", "reason": "resend not configured"}

    # An opt-in email without a working unsubscribe link is worse than no
    # email — refuse to send rather than degrade the link away.
    if not _restore_signing_secret():
        logger.info("digest cron: RESTORE_LINK_SECRET unset — cannot sign unsubscribe links")
        return {"status": "skipped", "reason": "unsubscribe signing secret not configured"}

    try:
        import httpx
    except ImportError:
        return {"status": "skipped", "reason": "httpx not installed"}

    corpus = load_opportunities()
    if not corpus:
        return {"status": "skipped", "reason": "no opportunities loaded"}
    opportunities = actionable_opportunities(release_visible_opportunities(corpus))
    opp_by_id = {o.get("id"): o for o in opportunities if o.get("id")}
    # Ids the queue must stop carrying: hidden by release scope, or stated
    # closed / reference-only / inactive / not-accepting by the source.
    #
    # Known-and-dead, not merely absent. An id the corpus no longer contains is
    # deliberately NOT here — a shard that failed to load, or a record between
    # refreshes, would otherwise silently empty a student's pending queue, and
    # "we cannot see it right now" is not evidence that it ended. Those stay
    # queued and simply do not render.
    hidden_opportunity_ids = {
        opportunity["id"]
        for opportunity in corpus
        if opportunity.get("id")
        and (
            not opportunity_visible_in_release(opportunity)
            or not is_actionable_target(opportunity)
        )
    }

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    now = datetime.now(UTC)
    # The idempotency window for a digest send. The throttle guarantees at most
    # one digest per search per 7 days, so a day is unambiguous: two sends that
    # share (search, day) are the same logical send retried, never two digests.
    digest_window = now.date().isoformat()
    sent = 0
    throttled = 0
    skipped = 0
    ambiguous = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=False) as client:
        incidents = _IncidentSink(
            client,
            supabase_url,
            headers,
            scope=_DIGEST_INCIDENT_SCOPE,
            entity_type="saved_search",
        )
        list_resp = await client.get(
            f"{supabase_url}/rest/v1/saved_searches",
            params={
                "select": "id,device_id,name,digest_email,new_match_ids,last_digest_sent_at",
                "digest_opt_in": "eq.true",
                "digest_unsubscribed_at": "is.null",
                "digest_email": "not.is.null",
                "limit": str(SUPABASE_BATCH_LIMIT),
            },
            headers=headers,
        )
        list_resp.raise_for_status()
        rows = list_resp.json()
        ineligible_by_device: dict[str, set[str]] = {}
        if rows:
            # One read of the live queue, and only when there is something to
            # send — a night with no opted-in rows costs nothing extra.
            await incidents.load_open_keys()
            ineligible_by_device = await _ineligible_ids_by_device(
                client, supabase_url, headers, corpus,
                [row.get("device_id") for row in rows],
            )

        for row in rows:
            sid = str(row.get("id", "?"))
            digest_key = f"notification_failure:digest:{sid}"
            stamp_key = f"notification_failure:digest:bookkeeping:{sid}"
            try:
                stored_new_ids = row.get("new_match_ids") or []
                ineligible = ineligible_by_device.get(row.get("device_id") or "", set())
                new_ids = [
                    opportunity_id
                    for opportunity_id in stored_new_ids
                    if opportunity_id not in hidden_opportunity_ids
                    # A record this student's own profile excludes is not
                    # theirs to be mailed. Positive set, like the line above:
                    # an id tonight's corpus could not see is untouched.
                    and opportunity_id not in ineligible
                ]
                if new_ids != stored_new_ids:
                    cleanup_resp = await client.patch(
                        f"{supabase_url}/rest/v1/saved_searches",
                        params={"id": f"eq.{sid}"},
                        headers=headers,
                        json={"new_match_ids": new_ids},
                    )
                    cleanup_resp.raise_for_status()
                # new_match_ids accumulates oldest-first (refresh appends);
                # show the freshest matches and summarize the rest.
                matched = [opp_by_id[i] for i in reversed(new_ids) if i in opp_by_id]
                items = matched[:DIGEST_MAX_ITEMS]
                overflow = len(matched) - len(items)
                if not items:
                    skipped += 1
                    continue

                last_sent = _parse_iso_ts(row.get("last_digest_sent_at"))
                if last_sent and now - last_sent < timedelta(days=DIGEST_MIN_INTERVAL_DAYS):
                    throttled += 1
                    continue

                try:
                    to_email = _validate_email(row.get("digest_email") or "")
                except ValueError:
                    skipped += 1
                    continue

                unsubscribe_url = _build_unsubscribe_url(sid)
                if not unsubscribe_url:
                    skipped += 1
                    continue

                subject, html, text = _render_digest_email(
                    row.get("name") or "Saved search", items, unsubscribe_url,
                    overflow=overflow,
                )
                # Same key on every attempt at this search's digest today —
                # that is the whole point. A freshly generated key per attempt
                # would make the provider treat a retry as a new email.
                idempotency_key = build_idempotency_key("digest", sid, digest_window)

                # Same per-recipient mail-bomb backstop as the user-facing send
                # endpoints, and in the same position: last thing before the
                # provider. Reserving above the render meant a row that failed
                # to render, or failed to build its key, still spent a slot on
                # a send that was never attempted — and this loop then moved on
                # to the next row, so the loss was invisible. A 429 here just
                # defers this row to the next run.
                try:
                    _enforce_recipient_quota(to_email)
                except HTTPException:
                    throttled += 1
                    continue
                try:
                    await _send_via_resend(
                        api_key=api_key, from_addr=from_addr, to=to_email,
                        subject=subject, html=html, text=text,
                        idempotency_key=idempotency_key,
                    )
                except Exception as send_exc:  # noqa: BLE001 — classified below
                    # The blanket per-row handler used to swallow this as just
                    # another row error. An operator needs to know WHICH kind
                    # of failure it was: a definitive one delivered nothing, an
                    # ambiguous one may already be in the recipient's inbox.
                    outcome = classify_send_failure(send_exc)
                    is_ambiguous = outcome == "ambiguous"
                    if is_ambiguous:
                        ambiguous += 1
                    errors.append(
                        f"{sid}: digest send "
                        + (
                            "AMBIGUOUS (may have been delivered) "
                            if is_ambiguous
                            else "FAILED (definitively not delivered) "
                        )
                        + f"{type(send_exc).__name__} — not stamped, retries next run"
                        + (
                            f"; same-day retry reuses Idempotency-Key {idempotency_key}"
                            if is_ambiguous else ""
                        )
                    )
                    logger.warning(
                        "digest cron: send %s for %s (%s)",
                        outcome, sid, type(send_exc).__name__,
                    )
                    await incidents.record(
                        digest_key,
                        title=(
                            "Saved-search digest outcome unknown"
                            if is_ambiguous else "Saved-search digest send failed"
                        ),
                        summary=(
                            "the transport failed after the request was sent; the "
                            "provider may already have accepted the digest"
                            if is_ambiguous
                            else "the provider did not accept the digest"
                        ),
                        detail={
                            "error_category": "digest_send_failed",
                            "outcome": outcome,
                            "may_have_been_delivered": is_ambiguous,
                            # Deriving from (search, day), never per attempt.
                            "idempotency_key": idempotency_key,
                            "stamped": False,
                            "consequence": "digest re-sends on the next nightly run",
                            # Type only: an exception message can carry the
                            # recipient address or the provider's payload.
                            "exception_type": type(send_exc).__name__,
                            "http_status": getattr(send_exc, "status_code", None),
                        },
                        # failure_state is the OBSERVATION (and migration 031
                        # allows only five values); whether the outcome is
                        # ambiguous is a separate fact, recorded in the detail.
                        failure_state=(
                            "timed_out"
                            if isinstance(send_exc, httpx.TimeoutException)
                            else "failed"
                        ),
                        entity_id=sid,
                    )
                    continue
                await incidents.recover(digest_key, "digest accepted by the provider")
                # Emptying the queue outright would also discard the ids the
                # corpus could not resolve this run. Those were never mailed
                # about — they are not in `matched` — so clearing them would
                # silently drop matches a student is still waiting on because
                # of a transient load failure on our side. They stay; every id
                # that resolved is cleared, mailed or overflowed alike, per the
                # existing "one digest closes the window" contract.
                # The overflow stays for the same reason: the email says
                # "+190 more in the app" and offers a button to go find them.
                # Clearing them emptied new_match_ids, so the badge vanished,
                # savedSearchToUrl dropped its highlight, and the 190 records
                # the student was just told about could not be identified by
                # any action they could take. Only the ids actually rendered in
                # the email close their window.
                mailed_ids = {opportunity["id"] for opportunity in items}
                unresolved_ids = [i for i in new_ids if i not in mailed_ids]
                # The provider accepted the send; this stamp is what prevents
                # a duplicate digest tomorrow (throttle keys off
                # last_digest_sent_at). Retry once on failure and record a
                # loud, distinct error — the generic per-row handler below
                # would bury it as just another skipped row (W14).
                patch_resp = await client.patch(
                    f"{supabase_url}/rest/v1/saved_searches",
                    params={"id": f"eq.{sid}"},
                    headers=headers,
                    json={
                        "last_digest_sent_at": now.isoformat(),
                        "new_match_ids": unresolved_ids,
                    },
                )
                if patch_resp.status_code >= 400:
                    patch_resp = await client.patch(
                        f"{supabase_url}/rest/v1/saved_searches",
                        params={"id": f"eq.{sid}"},
                        headers=headers,
                        json={
                            "last_digest_sent_at": now.isoformat(),
                            "new_match_ids": unresolved_ids,
                        },
                    )
                if patch_resp.status_code >= 400:
                    errors.append(
                        f"{sid}: digest SENT but stamp failed twice "
                        f"({patch_resp.status_code}) — will duplicate next run"
                    )
                    await incidents.record(
                        stamp_key,
                        title="Saved-search digest bookkeeping write failed",
                        summary="last_digest_sent_at stamp failed twice; the digest will duplicate",
                        detail={
                            "stage": "last_digest_sent_at_stamp",
                            "error_category": "bookkeeping_write_failed",
                            "http_status": patch_resp.status_code,
                            "attempts": 2,
                            "consequence": "digest re-sends until the stamp succeeds",
                            "provider_accepted": True,
                        },
                        # 'partial': the digest WAS accepted, only the record
                        # of it failed.
                        failure_state="partial",
                        entity_id=sid,
                    )
                else:
                    await incidents.recover(
                        stamp_key, "last_digest_sent_at stamped after acceptance"
                    )
                sent += 1
            except Exception as e:  # noqa: BLE001 — keep cron iterating
                errors.append(f"{sid}: {type(e).__name__}: {e}")
                await incidents.record(
                    digest_key,
                    title="Saved-search digest row failed with an unexpected error",
                    summary="row isolated; remaining digests continued",
                    detail={
                        "error_category": "row_exception",
                        # Type only — the message can carry the recipient
                        # address or a provider payload.
                        "exception_type": type(e).__name__,
                    },
                    failure_state="failed",
                    entity_id=sid,
                )

    return {
        "status": "ok" if not errors else "partial",
        # `sent` counts provider ACCEPTANCES, not inbox arrivals.
        "sent": sent,
        "throttled": throttled,
        "skipped": skipped,
        # Sends whose outcome is unknown: not stamped, so they retry — and may
        # therefore duplicate if the original did land (see the W16 note above).
        "ambiguous": ambiguous,
        "errors": errors[:10],
        # W16 ops-queue bookkeeping, mirroring the reminders cron. Non-zero
        # incident_errors means failures that did NOT reach the operator queue;
        # `errors` above stays the source of truth for this run.
        "incidents_recorded": incidents.recorded,
        "incidents_recovered": incidents.recovered,
        "incident_errors": incidents.errors,
        "timestamp": datetime.now(UTC).isoformat(),
    }


_UNSUB_CONFIRMATION_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><title>Unsubscribed</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#fafafa;margin:0;padding:48px 24px">
<div style="max-width:480px;margin:0 auto;background:white;padding:32px;border-radius:12px;text-align:center">
  <h1 style="font-size:20px;margin:0 0 12px;color:#111827">You're unsubscribed</h1>
  <p style="color:#4b5563;font-size:14px;line-height:1.6;margin:0 0 8px">
    This saved search will no longer email you a weekly digest.
    You can turn it back on anytime from your saved searches.
  </p>
  <p style="color:#6b7280;font-size:13px;line-height:1.6;margin:0 0 20px">
    已退订 — 该保存搜索不会再发送每周摘要邮件，可随时在「我的收藏」中重新开启。
  </p>
  <a href="{FRONTEND_BASE}/favorites" style="color:#4f46e5;font-size:14px;text-decoration:none">JoinALab →</a>
</div>
</body></html>"""

# The form posts to action="" — the same URL including the signed query
# string — so the POST carries the exact sid/t/s token the GET validated.
_UNSUB_CONFIRM_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><title>Unsubscribe</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#fafafa;margin:0;padding:48px 24px">
<div style="max-width:480px;margin:0 auto;background:white;padding:32px;border-radius:12px;text-align:center">
  <h1 style="font-size:20px;margin:0 0 12px;color:#111827">Stop this weekly digest?</h1>
  <p style="color:#4b5563;font-size:14px;line-height:1.6;margin:0 0 8px">
    Confirm below to stop email for this saved search. Opening this page alone does not change your settings.
  </p>
  <p style="color:#6b7280;font-size:13px;line-height:1.6;margin:0 0 20px">
    确认退订 — 仅打开此页面不会修改你的邮件设置。
  </p>
  <form method="post" action="">
    <button type="submit" style="border:0;border-radius:8px;background:#111827;color:white;padding:11px 20px;font-weight:600;cursor:pointer">Unsubscribe / 确认退订</button>
  </form>
  <a href="{FRONTEND_BASE}/favorites" style="display:inline-block;margin-top:18px;color:#4f46e5;font-size:14px;text-decoration:none">Cancel · 返回 JoinALab</a>
</div>
</body></html>"""


def _validate_digest_unsubscribe_token(sid: str, t: int, signature: str) -> None:
    if not _UUID_RE.match(sid):
        raise HTTPException(status_code=400, detail="Invalid saved search id")
    if not _restore_signing_secret():
        raise HTTPException(status_code=503, detail="Unsubscribe disabled")

    age_seconds = int(time.time()) - t
    if age_seconds < 0 or age_seconds > DIGEST_UNSUB_TTL_DAYS * 86400:
        raise HTTPException(status_code=400, detail="Link expired")

    expected = _sign_digest_unsub(sid, t)
    if not expected or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")


@router.get("/email/digest-unsubscribe")
async def digest_unsubscribe(sid: str, t: int, s: str):
    """Validate a digest opt-out link and ask the human to confirm.

    Email security scanners routinely prefetch GET links, so a GET must never
    mutate subscription state (users were being silently unsubscribed by their
    own mail filters). The signed POST below performs the actual opt-out.
    """
    _validate_digest_unsubscribe_token(sid, t, s)
    return HTMLResponse(_UNSUB_CONFIRM_HTML)


@router.post("/email/digest-unsubscribe")
async def confirm_digest_unsubscribe(sid: str, t: int, s: str):
    """Turn a saved-search digest off after explicit signed confirmation.

    No auth beyond the HMAC token: the link lands in the recipient's
    inbox, and the only effect of a valid token is turning email OFF —
    same threat model as email.py's restore link, lower stakes.
    """
    _validate_digest_unsubscribe_token(sid, t, s)

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        raise HTTPException(status_code=503, detail="Storage not configured")
    env = env_result

    import httpx

    supabase_url = env["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    async with httpx.AsyncClient(timeout=15.0, trust_env=False, follow_redirects=False) as client:
        resp = await client.patch(
            f"{supabase_url}/rest/v1/saved_searches",
            params={"id": f"eq.{sid}"},
            headers=headers,
            json={
                "digest_opt_in": False,
                "digest_unsubscribed_at": datetime.now(UTC).isoformat(),
            },
        )
    if resp.status_code >= 400:
        logger.warning("digest unsubscribe PATCH failed: %s %s", resp.status_code, resp.text[:200])
        raise HTTPException(status_code=502, detail="Could not update digest settings")

    return HTMLResponse(_UNSUB_CONFIRMATION_HTML)
