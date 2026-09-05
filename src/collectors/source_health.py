"""Per-source publication health — the shard-level freshness ledger.

Publication used to be judged per RUN, so on 2026-08-08 one broken UCSB
sitemap withheld fifteen unrelated schools' fresh data. #8 fixed that by
attributing each release reason to the shard file it describes. This module
fixes the same mistake one level down.

A shard file is per school, but a school is collected by MANY independent
department sources — UC Berkeley has 54 ``ucb_*_faculty`` collectors. The
release contract mapped every one of them onto the single ``ucb`` unit, so a
zero-emitting department set ``by_unit["ucb"].ready = False`` and the whole
school went unpublished. ``ucb_ling_faculty`` did exactly that: its department
moved host and template, the parser silently matched nothing, and 3,106 UC
Berkeley records froze at 2026-07-21 for 44 days while runs on 08-18 and 08-25
collected healthy data for the other 53 departments and threw it away.

The invariant this module exists to hold:

    one department failing degrades that department
    one department failing does NOT veto its school

Three questions had no answer anywhere in the pipeline, and each is answered
here:

1. **Is this zero real?** ``fetch_soup`` returns None on a 403 bot wall and
   ``_scrape_directory`` degrades to ``[]``, so "the department is behind a
   WAF" and "the department has no faculty" produced byte-identical summaries:
   ``{"fetched": 0, "status": "ok"}``. :func:`classify` separates them using
   the one piece of evidence that cannot be faked by pipeline execution — the
   records the corpus already holds for that source.

2. **When did this source last actually work?** Only per-record
   ``last_seen_at`` and one corpus-wide timestamp existed. A school publishing
   today said nothing about which of its departments contributed, so a
   permanently broken department was invisible behind its fresh siblings.
   :func:`update_ledger` keeps ``last_attempt_at``, ``last_success_at`` and
   ``last_publish_at`` strictly separate, and NEVER advances
   ``last_success_at`` for an attempt that did not succeed.

3. **Is this school stale, or just one of its departments?**
   :func:`school_rows` summarizes shard health instead of collapsing it to a
   boolean, so partial degradation is representable and ``fully_stale`` means
   what it says: no eligible source in the school has fresh trusted data.

The ledger is data/processed/source_health.json, committed with the shards it
describes so it survives a clean deploy exactly as collector_status.json does.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEDGER_FILE = PROJECT_ROOT / "data" / "processed" / "source_health.json"

LEDGER_NAME = "source_health.json"


def ledger_path_for(processed_dir: Path) -> Path:
    """The ledger belonging to a given data/processed directory.

    Every writer derives its path from the processed directory it is already
    working in, rather than from the module-level default. Without this a
    test that points refresh_all or shard_corpus at a tmp directory still
    wrote the REAL committed ledger - which is not a hypothetical: it
    happened, and rewrote 58 UC Berkeley source rows with fixture values
    before this existed.
    """
    return Path(processed_dir) / LEDGER_NAME

SCHEMA_VERSION = 1

# --- zero-output vocabulary -------------------------------------------------
# The four outcomes a source run can have. "ok" was all three of the last
# three, which is precisely why a broken collector could look healthy.
SUCCESS_NONZERO = "success_nonzero"
VALID_ZERO = "valid_zero"
SUSPICIOUS_ZERO = "suspicious_zero"
FAILED = "failed"

#: Outcomes that mean this run produced trustworthy output for the source.
HEALTHY_OUTCOMES = frozenset({SUCCESS_NONZERO, VALID_ZERO})
#: Outcomes that must never advance ``last_success_at``.
DEGRADED_OUTCOMES = frozenset({SUSPICIOUS_ZERO, FAILED})

# --- how stale is "stale" --------------------------------------------------
# Each shard is scraped once a week (scripts/refresh_rotation.py owns the
# day->schools table), so a healthy source's last success is 0-9 days old —
# the whole committed corpus sits in that band apart from the four frozen
# shards this work fixes. The boundaries are therefore counted in MISSED
# WEEKLY SLOTS, not in the corpus-wide 72/96 HOURS that
# backend/lib/corpus_freshness.py uses: applying an hours-scale bound per
# shard would mark every correctly-refreshed school stale six days out of
# seven.
#
#   warn  > 10 days — missed its weekly slot once
#   stale > 17 days — missed two, and past deactivate_stale_faculty's
#                     14-day GRACE_DAYS, so its records are now being
#                     retired for absence. That is real product impact,
#                     which is the honest place to draw "stale".
_DEFAULT_WARN_DAYS = 10.0
_DEFAULT_STALE_DAYS = 17.0


def _days_from_env(var: str, default: float) -> float:
    """A positive float from ``var``, or ``default`` when unset/unusable.

    Never returns 0 or a negative: a typo must not silently mark every source
    stale, nor (with a negative stale bound) mark none of them stale.
    """
    raw = os.environ.get(var)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        logger.warning("Ignoring invalid %s=%r; using %g days", var, raw, default)
        return default
    return value


def staleness_thresholds() -> tuple[float, float]:
    """``(warn_days, stale_days)``, re-read from the environment per call.

    ``warn`` is clamped to ``stale`` because the reverse ordering is
    incoherent: a source past the stale bound but short of a larger warn
    bound would be reported fresh by the same call that considers it stale.
    """
    warn = _days_from_env("OFE_SOURCE_WARN_DAYS", _DEFAULT_WARN_DAYS)
    stale = _days_from_env("OFE_SOURCE_STALE_DAYS", _DEFAULT_STALE_DAYS)
    return min(warn, stale), stale


def classify(
    *,
    emitted: object,
    baseline: int,
    errored: bool = False,
    allow_confirmed_empty: bool = False,
) -> str:
    """Which of the four outcomes this source run had.

    ``baseline`` is how many ACTIVE records the corpus already holds for the
    source. It is the evidence that separates a legitimate empty from a
    broken collector, and it cannot be manufactured by running the pipeline:
    a source that has produced records before has to keep producing them or
    explain itself.

    ``allow_confirmed_empty`` is the explicit declaration that emitting
    nothing is expected behaviour for this source (a seasonal project
    listing outside its application window). It is never inferred — an
    undeclared source that has held records and now emits none is
    ``suspicious_zero``, which is the whole point.

    An unusable ``emitted`` (None, bool, negative, non-int) is ``FAILED``:
    a source that cannot say how much it produced has not demonstrated it
    produced anything.
    """
    if errored:
        return FAILED
    if isinstance(emitted, bool) or not isinstance(emitted, int) or emitted < 0:
        return FAILED
    if emitted > 0:
        return SUCCESS_NONZERO
    if allow_confirmed_empty:
        return VALID_ZERO
    if baseline > 0:
        # Historically populated and suddenly empty: suspicious until a human
        # or a later successful run says otherwise. Never resolved by
        # redefinition.
        return SUSPICIOUS_ZERO
    # Never produced a record and does not claim empty is expected. Not
    # "fine" — a registered mandatory producer that has never produced is
    # degraded (ucd_faculty, walled off by Cloudflare, is the live example).
    return SUSPICIOUS_ZERO


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def empty_ledger() -> dict:
    return {"schema_version": SCHEMA_VERSION, "sources": {}, "shards": {}}


def load_ledger(path: Path | None = None) -> dict:
    """Read the ledger, or an empty one when absent/unreadable/foreign.

    A ledger written by a future schema is NOT merged into: guessing at its
    shape could overwrite a real ``last_success_at`` with a fabricated one,
    and the whole point of this file is that those timestamps are earned.
    """
    target = path if path is not None else LEDGER_FILE
    try:
        with target.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return empty_ledger()
    if not isinstance(payload, dict):
        return empty_ledger()
    if payload.get("schema_version") != SCHEMA_VERSION:
        logger.warning(
            "source_health: ignoring ledger with schema_version=%r (expected %d)",
            payload.get("schema_version"), SCHEMA_VERSION,
        )
        return empty_ledger()
    sources = payload.get("sources")
    shards = payload.get("shards")
    return {
        "schema_version": SCHEMA_VERSION,
        "sources": sources if isinstance(sources, dict) else {},
        "shards": shards if isinstance(shards, dict) else {},
    }


def save_ledger(ledger: dict, path: Path | None = None) -> None:
    from .atomic_json import atomic_write_json

    target = path if path is not None else LEDGER_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, ledger, sort_keys=True, indent=2)


def record_attempt(
    ledger: dict,
    *,
    source: str,
    school: str | None,
    outcome: str,
    emitted: int | None,
    baseline: int,
    now: datetime,
    failure_reason: str | None = None,
) -> dict:
    """Fold one source run into the ledger (in place) and return its row.

    The timestamp discipline this function exists to enforce:

    * ``last_attempt_at`` — always advances. The run happened.
    * ``last_success_at`` — advances ONLY for a healthy outcome. This is the
      field every staleness answer is computed from, so an attempt that
      failed must not refresh it. Doing so is how a permanently broken
      source hides: it is attempted weekly forever.
    * ``last_good_count`` — the last count actually achieved, kept across
      failures so a suspicious zero can be reported against what it lost.

    ``consecutive_failures`` counts degraded runs since the last healthy one,
    so repeated failure stays visible instead of looking like one bad day.
    """
    row = ledger.setdefault("sources", {}).setdefault(source, {})
    row["school"] = school
    row["last_attempt_at"] = _iso(now)
    row["status"] = outcome
    row["current_count"] = emitted if isinstance(emitted, int) and not isinstance(
        emitted, bool
    ) else None
    row["baseline_count"] = baseline

    if outcome in HEALTHY_OUTCOMES:
        row["last_success_at"] = _iso(now)
        row["consecutive_failures"] = 0
        row["failure_reason"] = None
        if isinstance(emitted, int) and not isinstance(emitted, bool):
            row["last_good_count"] = emitted
    else:
        row["consecutive_failures"] = int(row.get("consecutive_failures") or 0) + 1
        row["failure_reason"] = failure_reason
        # last_success_at / last_good_count are deliberately untouched.
        if row.get("last_good_count") is None and baseline > 0:
            # First recorded failure for a source the corpus already holds
            # records for: seed the last-known-good from those records so the
            # regression is reportable even without a prior healthy run in
            # the ledger.
            row["last_good_count"] = baseline
    return row


def record_publish(
    ledger: dict, *, shards: dict[str, int], now: datetime,
) -> None:
    """Stamp ``last_publish_at`` for the shard files a run actually wrote.

    Publishing is per SHARD; succeeding is per SOURCE. Conflating them is the
    stale-source masking bug: "UCB published today" must not become "every UCB
    department succeeded today". This function therefore writes only into the
    ``shards`` section and never touches a source row.
    """
    section = ledger.setdefault("shards", {})
    for shard, count in shards.items():
        row = section.setdefault(shard, {})
        row["last_publish_at"] = _iso(now)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            row["last_publish_record_count"] = count


def _age_days(value: object, now: datetime) -> float | None:
    parsed = _parse(value)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 86400.0


def freshness_of(row: dict, now: datetime) -> str:
    """``fresh`` / ``warn`` / ``stale`` / ``unknown`` for one source row.

    ``unknown`` (no parseable ``last_success_at``) is NEVER reported as
    fresh — a source that cannot prove it ever succeeded is not fresh, and
    counting it as such is how a zero denominator turns a gate vacuously
    green.
    """
    warn_days, stale_days = staleness_thresholds()
    age = _age_days(row.get("last_success_at"), now)
    if age is None:
        return "unknown"
    if age > stale_days:
        return "stale"
    if age > warn_days:
        return "warn"
    return "fresh"


def monitored_source_names() -> frozenset[str] | None:
    """The sources a weekly clock may judge, or None when unknowable.

    Delegated to refresh_contract.monitored_sources() so the monitoring
    definition of "required producer" is the SAME one publication uses. The
    import is local because refresh_contract is a heavier module that pulls
    every school config; source_health is imported by low-level callers that
    must not pay for it.

    ``None`` means the answer is unavailable, and callers then treat every
    row as eligible: under-reporting staleness would be the more dangerous
    failure.
    """
    try:
        from .refresh_contract import monitored_sources
    except Exception as exc:  # noqa: BLE001
        logger.warning("source_health: monitored source set unavailable: %s", exc)
        return None
    return monitored_sources()



def source_rows(
    ledger: dict,
    now: datetime | None = None,
    eligible: frozenset[str] | set[str] | None = None,
) -> list[dict]:
    """Per-source monitoring rows, sorted by school then source.

    One row per department/source shard, carrying exactly what an operator
    needs to act without re-reading the corpus: what it holds now, what it
    last held, when it last worked, and why it stopped.
    """
    now = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    shards = ledger.get("shards") or {}
    eligible = monitored_source_names() if eligible is None else eligible
    rows: list[dict] = []
    for source, row in (ledger.get("sources") or {}).items():
        if not isinstance(row, dict):
            continue
        school = row.get("school")
        shard_row = shards.get(school) if isinstance(school, str) else None
        shard_row = shard_row if isinstance(shard_row, dict) else {}
        rows.append({
            "school": school,
            "source": source,
            "last_attempt_at": row.get("last_attempt_at"),
            "last_success_at": row.get("last_success_at"),
            "last_publish_at": shard_row.get("last_publish_at"),
            "current_record_count": row.get("current_count"),
            "last_good_record_count": row.get("last_good_count"),
            "freshness_age_days": _round(_age_days(row.get("last_success_at"), now)),
            "freshness": freshness_of(row, now),
            "status": row.get("status"),
            "failure_reason": row.get("failure_reason"),
            "consecutive_failures": int(row.get("consecutive_failures") or 0),
            # Whether a weekly clock may judge this source at all. False for
            # data the corpus carries but no scheduled run reproduces -
            # ``manual`` seeds and the ``*_external_research`` pages a campus
            # crawl only re-stamps when it rediscovers them. Shown, never
            # counted as stale.
            "eligible": eligible is None or source in eligible,
        })
    rows.sort(key=lambda r: (r["school"] or "", r["source"]))
    return rows


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def school_rows(
    ledger: dict,
    now: datetime | None = None,
    eligible: frozenset[str] | set[str] | None = None,
) -> list[dict]:
    """Per-school aggregate rows: shard health, not one school-wide boolean.

    ``fully_stale`` is true only when NO eligible source in the school has
    fresh trusted data — the condition the product actually cares about. One
    stale department among fresh siblings is ``partially_degraded``, which is
    publishable under the partial-degradation policy; it is not, and must not
    be reported as, a dead school.

    The converse guard matters as much: a school is fully stale when every
    source is stale even if the shard file was rewritten today, because a
    rewrite that carried only retained records forward is not a refresh.
    """
    now = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    shards = ledger.get("shards") or {}
    by_school: dict[str, list[dict]] = {}
    for row in source_rows(ledger, now, eligible):
        school = row["school"]
        if not isinstance(school, str) or not school:
            continue
        if not row["eligible"]:
            # Carried, not scheduled. Judging it on the weekly clock would
            # report a healthy school permanently degraded.
            continue
        by_school.setdefault(school, []).append(row)

    out: list[dict] = []
    for school, rows in sorted(by_school.items()):
        fresh = sum(1 for r in rows if r["freshness"] == "fresh")
        warn = sum(1 for r in rows if r["freshness"] == "warn")
        stale = sum(1 for r in rows if r["freshness"] in {"stale", "unknown"})
        failed = sum(1 for r in rows if r["status"] == FAILED)
        degraded = sum(1 for r in rows if r["status"] in DEGRADED_OUTCOMES)
        ages = [
            r["freshness_age_days"]
            for r in rows
            if r["freshness"] in {"stale", "unknown"}
            and r["freshness_age_days"] is not None
        ]
        successes = [
            _parse(r["last_success_at"]) for r in rows if r["last_success_at"]
        ]
        successes = [s for s in successes if s is not None]
        shard_row = shards.get(school)
        shard_row = shard_row if isinstance(shard_row, dict) else {}
        out.append({
            "school": school,
            "fresh_shard_count": fresh,
            "warn_shard_count": warn,
            "stale_shard_count": stale,
            "failed_shard_count": failed,
            "degraded_shard_count": degraded,
            "total_shard_count": len(rows),
            "oldest_stale_age_days": max(ages) if ages else None,
            "last_successful_school_activity": (
                _iso(max(successes)) if successes else None
            ),
            "last_publish_at": shard_row.get("last_publish_at"),
            # No fresh source anywhere in the school. Note this is computed
            # from earned per-source successes, never from the publish
            # timestamp, so republishing retained data cannot clear it.
            "fully_stale": fresh == 0 and warn == 0,
            "state": (
                "fully_stale" if fresh == 0 and warn == 0
                else "partially_degraded" if stale or degraded
                else "fully_fresh"
            ),
        })
    return out


def corpus_report(
    ledger: dict,
    now: datetime | None = None,
    eligible: frozenset[str] | set[str] | None = None,
) -> dict:
    """Corpus-wide freshness roll-up — the production acceptance numbers."""
    schools = school_rows(ledger, now, eligible)
    return {
        "generated_at": _iso(
            now.astimezone(UTC) if now is not None else datetime.now(UTC)
        ),
        "school_count": len(schools),
        "fully_fresh_school_count": sum(
            1 for s in schools if s["state"] == "fully_fresh"
        ),
        "partially_degraded_school_count": sum(
            1 for s in schools if s["state"] == "partially_degraded"
        ),
        "fully_stale_school_count": sum(1 for s in schools if s["fully_stale"]),
        "fully_stale_schools": sorted(
            s["school"] for s in schools if s["fully_stale"]
        ),
        "stale_shard_count": sum(s["stale_shard_count"] for s in schools),
        "failed_shard_count": sum(s["failed_shard_count"] for s in schools),
        "degraded_shard_count": sum(s["degraded_shard_count"] for s in schools),
        "total_shard_count": sum(s["total_shard_count"] for s in schools),
        "warn_days": staleness_thresholds()[0],
        "stale_days": staleness_thresholds()[1],
    }


def active_baselines(opps: list[dict[str, Any]]) -> dict[str, int]:
    """Active record count per source — the baseline :func:`classify` needs.

    Counted from the corpus rather than from a stored number so it cannot
    drift away from the records it claims to describe. Inactive rows are
    excluded: a source whose records were all retired has no live output to
    lose, and counting retired rows would keep it permanently suspicious.
    """
    counts: dict[str, int] = {}
    for opp in opps:
        source = opp.get("source")
        if not isinstance(source, str) or not source:
            continue
        if (opp.get("metadata") or {}).get("is_active") is False:
            continue
        counts[source] = counts.get(source, 0) + 1
    return counts
