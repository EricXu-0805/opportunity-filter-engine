"""Bounded, persisted condition-source refresh for normalized faculty records.

This pass does not enrich research, guess contacts, follow page links, or invoke
models/headless browsers. Its request budget includes every redirect hop.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from src.contact_instructions import (
    CAPTURE_KEY,
    PAGES_KEY,
    SOURCE_KEY,
    _identity,
    _url,
    capture_failure,
    capture_metadata,
    contact_instruction_pages,
)
from src.normalizers.school_audience import SOURCE_DEFAULTS


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _school(record: object) -> str:
    if not isinstance(record, dict):
        return "unknown"
    school = record.get("school")
    if isinstance(school, str) and school:
        return school
    source = record.get("source")
    fallback = SOURCE_DEFAULTS.get(source, (None, ""))[0] if isinstance(source, str) else None
    return fallback or "unknown"


def _candidate_pages(records: list[dict], now: datetime, freshness: timedelta, retry: timedelta):
    candidates = []
    skipped: dict[str, int] = {}
    for record in records:
        school = _school(record)
        if (not isinstance(record, dict) or record.get("source_type") != "faculty_research"
                or not isinstance(record.get("id"), str) or not record["id"]
                or not _identity(record.get("pi_name")) or not _url(record.get("url"))
                or not isinstance(record.get("metadata", {}), dict)
                or record.get("metadata", {}).get("is_active") is False):
            skipped[school] = skipped.get(school, 0) + 1
            continue
        metadata = record.get("metadata", {})
        ledger = metadata.get(PAGES_KEY, {})
        if PAGES_KEY in metadata and (not isinstance(ledger, dict)
                                     or not isinstance(ledger.get("pages"), list)):
            skipped[school] = skipped.get(school, 0) + 1
            continue
        pages = contact_instruction_pages(record)
        stored_pages = ledger.get("pages", [])
        stored_urls = {_url(page.get("requested_source_url")) for page in stored_pages if isinstance(page, dict)}
        full_ledger = isinstance(stored_pages, list) and len(stored_pages) >= 32
        current = _url(record["url"])
        # Only the current profile and previously bound, retained page identities
        # are eligible. This pass never discovers or follows arbitrary links.
        if not any(_url(page.get("requested_source_url")) == current for page in pages):
            pages.append({"requested_source_url": record["url"], "source_url": record["url"],
                          "record_source_url": record["url"], "identity_name": record["pi_name"],
                          "receipt": None, "sources": [], "last_success_at": None})
        for page in pages:
            target = page.get("requested_source_url") or page.get("source_url")
            if not _url(target) or _identity(page.get("identity_name")) != _identity(record["pi_name"]):
                continue
            receipt = page.get("receipt") or {}
            success = _timestamp(page.get("last_success_at"))
            attempted = _timestamp(receipt.get("attempted_at"))
            # A future timestamp cannot turn an unknown source into a fresh one.
            success = success if success and success <= now else None
            attempted = attempted if attempted and attempted <= now else None
            retry_at = _timestamp(receipt.get("next_retry_at"))
            failed = receipt.get("status") in ("failed", "unsupported")
            needed = (success is None or now - success >= freshness
                      or bool(failed and attempted and attempted >= success))
            cooling = bool(needed and failed and attempted and
                           (now < attempted + retry or (retry_at and now < retry_at)))
            candidates.append({"record": record, "page": page, "target": target, "school": school,
                               "success": success, "attempted": attempted,
                               "needed": needed, "cooling": cooling,
                               "blocked": full_ledger and _url(target) not in stored_urls})
    return candidates, skipped


def _retry_after(value: object, now: datetime) -> datetime | None:
    if not isinstance(value, str) or len(value) > 200:
        return None
    try:
        result = now + timedelta(seconds=int(value)) if value.strip().isdigit() else parsedate_to_datetime(value)
        if result.tzinfo is None:
            return None
        return result.astimezone(UTC) if result > now else None
    except (OverflowError, ValueError, TypeError):
        return None


def refresh_faculty_condition_sources(
    records: list[dict], *, max_requests: int = 100, max_pages: int = 100,
    freshness_days: int = 14, retry_hours: int = 24, deadline: float | None = None,
    persist: Callable[[], None] | None = None, now: datetime | None = None,
) -> dict:
    """Refresh due pages in-place, checkpointing each completed page via persist.

    The caller passes scoped references into its full corpus and persists that
    full corpus in the callback. No function here opens a corpus or state file.
    Checkpoints preserve page-local attempts, which form a durable oldest-first
    queue across invocations without a separate cursor that could lose sync.
    """
    for name, value, maximum in (("max_requests", max_requests, 10000), ("max_pages", max_pages, 10000),
                                 ("freshness_days", freshness_days, 365), ("retry_hours", retry_hours, 8760)):
        if type(value) is not int or value < (0 if name.startswith("max_") else 1) or value > maximum:
            raise ValueError(f"Invalid {name}.")
    reference_now = now
    def clock():
        return reference_now or datetime.now(UTC)
    now = clock()
    if now.tzinfo is None:
        raise ValueError("now must include a timezone.")
    now = now.astimezone(UTC)
    freshness, retry = timedelta(days=freshness_days), timedelta(hours=retry_hours)
    candidates, skipped = _candidate_pages(records, now, freshness, retry)
    due = [item for item in candidates if item["needed"] and not item["cooling"]]
    due.sort(key=lambda item: (item["attempted"] or datetime.min.replace(tzinfo=UTC),
                               item["record"]["id"], _url(item["target"])))
    record_counts = Counter(_school(record) for record in records)
    stats = {"records": len(records), "due": len(due), "backlog": sum(item["needed"] for item in candidates),
             "attempted": 0, "requests": 0, "deferred": 0, "updated": 0,
             "fresh": sum(not item["needed"] for item in candidates),
             "retry_deferred": sum(item["cooling"] for item in candidates),
             "missing": sum(item["success"] is None for item in candidates),
             "stale": sum(bool(item["success"] and now - item["success"] >= timedelta(days=60)) for item in candidates),
             "source_limit": 0, "storage_rejected": 0, "capacity_blocked": sum(item["needed"] and item["blocked"] for item in candidates),
             "skipped_records": sum(skipped.values()), "stop_reason": None,
             "updated_unit": "page",
             "request_budget": max_requests, "page_budget": max_pages, "freshness_days": freshness_days,
             "condition_capture_counts": {key: 0 for key in ("captured", "empty", "unsupported", "failed")},
             "minimum_runs_at_request_budget": math.ceil(sum(item["needed"] for item in candidates) / max_requests) if max_requests else None}
    if stats["capacity_blocked"]:
        stats["minimum_runs_at_request_budget"] = None
    count_fields = ("due", "backlog", "attempted", "requests", "deferred", "updated", "fresh",
                    "retry_deferred", "missing", "stale", "source_limit", "storage_rejected", "skipped_records", "capacity_blocked")
    by_school = {school: {key: 0 for key in count_fields}
                 for school in record_counts}
    for school, count in record_counts.items():
        by_school[school]["records"] = count
    for school, count in skipped.items():
        by_school[school]["skipped_records"] = count
    for item in candidates:
        local = by_school[item["school"]]
        local["due"] += int(item["needed"] and not item["cooling"])
        local["backlog"] += int(item["needed"])
        local["fresh"] += int(not item["needed"])
        local["retry_deferred"] += int(item["cooling"])
        local["missing"] += int(item["success"] is None)
        local["capacity_blocked"] += int(item["needed"] and item["blocked"])
        local["stale"] += int(bool(item["success"] and now - item["success"] >= timedelta(days=60)))
    stats["by_school"] = by_school

    from .faculty_graph import capture_profile_condition_response
    from .uiuc_faculty import carry_forward_contact_instruction_sources
    from .url_parser import _safe_fetch

    rate_limited = False
    next_retry_at = None
    page_blocked = None

    def before_request(_url_requested):
        nonlocal page_blocked
        if rate_limited:
            page_blocked = "rate_limited"
        elif deadline is not None and time.monotonic() >= deadline:
            page_blocked = "deadline"
        elif stats["requests"] >= max_requests:
            page_blocked = "request_budget"
        else:
            stats["requests"] += 1
            return True
        stats["stop_reason"] = page_blocked
        return False

    def on_response(response):
        nonlocal rate_limited, next_retry_at
        if response.status_code == 429:
            rate_limited = True
            stats["stop_reason"] = "rate_limited"
            next_retry_at = _retry_after(response.headers.get("Retry-After"), clock())

    for item in due:
        if item["blocked"]:
            continue  # Stored page capacity needs review; no futile request or fake attempt.
        if rate_limited or (deadline is not None and time.monotonic() >= deadline) or stats["requests"] >= max_requests:
            stats["stop_reason"] = "rate_limited" if rate_limited else ("deadline" if deadline is not None and time.monotonic() >= deadline else "request_budget")
            break
        if stats["attempted"] >= max_pages:
            stats["stop_reason"] = "page_budget"
            break
        page_blocked = None
        before = stats["requests"]
        response = _safe_fetch(item["target"], before_request=before_request, on_response=on_response)
        if page_blocked and stats["requests"] == before:
            break  # No network request began: this is deferred, not an attempt.
        record = item["record"]
        page = item["page"]
        local = by_school[item["school"]]
        local["requests"] += stats["requests"] - before
        binding = dict(source_url=item["target"], requested_source_url=item["target"],
                       record_source_url=page["record_source_url"], identity_name=record["pi_name"])
        if response is None:
            reason = "rate_limited" if rate_limited else page_blocked or "fetch_failed"
            result = capture_failure(**binding, reason=reason, checked_at=clock().isoformat(),
                                     next_retry_at=next_retry_at.isoformat() if next_retry_at else None)
        else:
            result = capture_profile_condition_response(response, requested_url=item["target"],
                                                        record_source_url=page["record_source_url"],
                                                        expected_name=record["pi_name"])
        incoming = deepcopy(record)
        metadata = incoming.setdefault("metadata", {})
        for key in (CAPTURE_KEY, SOURCE_KEY, PAGES_KEY):
            metadata.pop(key, None)
        metadata.update(capture_metadata(result))
        carry_forward_contact_instruction_sources(record, incoming)
        original_metadata = record.get("metadata", {})
        changed = incoming["metadata"] != original_metadata
        stats["attempted"] += 1
        local["attempted"] += 1
        refreshed = next((page for page in contact_instruction_pages(incoming)
                          if _url(page.get("requested_source_url")) == _url(item["target"])), None)
        saved_receipt = refreshed.get("receipt") if refreshed else None
        saved_receipt = saved_receipt if saved_receipt and saved_receipt.get("attempted_at") == result["attempted_at"] else None
        accepted = bool(saved_receipt and saved_receipt.get("status") == result["status"]
                        and saved_receipt.get("reason") == result.get("reason"))
        if not accepted:
            issue = incoming["metadata"].get(PAGES_KEY, {}).get("merge_issue")
            rejection = "source_limit" if issue in {"source_limit", "page_limit"} else "storage_rejected"
            stats[rejection] += 1
            local[rejection] += 1
        stats["condition_capture_counts"][result["status"] if accepted else "unsupported"] += 1
        if changed:
            record["metadata"] = incoming["metadata"]
            try:
                if persist is not None:
                    persist()
            except Exception:
                record["metadata"] = original_metadata
                raise
            stats["updated"] += 1
            local["updated"] += 1
        if accepted and result["status"] in {"captured", "empty"}:
            stats["backlog"] -= 1
            local["backlog"] -= 1
    stats["deferred"] = len(due) - stats["attempted"]
    for local in by_school.values():
        local["deferred"] = local["due"] - local["attempted"]
    return stats
