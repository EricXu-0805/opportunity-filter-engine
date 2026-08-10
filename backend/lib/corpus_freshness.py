"""When the opportunity corpus was last refreshed — one source of truth.

W15 fixed the admin stale-data alert, which used to stat
``data/processed/opportunities.json``: a GITIGNORED work file that
render.yaml never assembles, so in production the path never existed, the
freshness read was always None, and the "the cron died" detector could
never fire. The public ``/opportunities/stats/summary`` endpoint carried a
byte-for-byte copy of the same bug (its ``last_updated_at`` was always null
in production, so the home page's live-database card rendered nothing).

W16 extracts the fixed reader here so the admin surface and the public
surface cannot drift apart again. Order of trust:

1. ``collector_status.json``'s own run ``timestamp`` — committed by the
   refresh job, so it survives a clean deploy and describes when the data
   was actually collected (not when a file happened to be written).
2. The local work file's mtime — present only in dev/CI, where the corpus
   is assembled on the box.
3. The newest shard mtime — the deploy-time fallback: shards ARE committed,
   so this is the last resort that still beats claiming nothing is known.

Returns None only when none of the three exist. None means "unknown" and
callers must render it as such — never as "fresh" and never as a zero age.

This module also owns the WARN/STALE hour boundaries every surface compares
that timestamp against — see ``corpus_freshness_thresholds`` below.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

# --- how old is "old" -------------------------------------------------------
# ONE definition of the freshness boundary. There were three, and the one that
# actually pages a human was the loosest:
#
#   docs/integrity_hardening_report.md    warn >= 72h,  stale >= 96h
#   frontend admin FreshnessBanner        warn >= 72h,  stale >= 96h
#   backend admin _HEALTH_THRESHOLDS      warn >= 96h,  alert >= 192h
#
# The refresh cron runs twice a week, so 96h is already one missed run and 192h
# is two: the backend's alert fired a full extra cycle after the docs and the
# admin UI both claimed the data was stale, and an operator reading the banner
# had no way to know the alert disagreed. The documented 72/96 pair wins;
# backend/routes/admin.py and backend/routes/readiness.py now both import these
# names, so the next change to the boundary lands in exactly one place.
_DEFAULT_WARN_HOURS = 72.0
_DEFAULT_STALE_HOURS = 96.0


def _hours_from_env(var: str, default: float) -> float:
    """A positive float from ``var``, or ``default`` when unset/unusable.

    Never returns 0 or a negative: a typo must not silently mark every corpus
    stale (or, with a negative stale bound, silently mark none of them fresh).
    """
    raw = os.environ.get(var)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        logger.warning("Ignoring invalid %s=%r; using %g hours", var, raw, default)
        return default
    return value


def corpus_freshness_thresholds() -> tuple[float, float]:
    """``(warn_hours, stale_hours)``, re-read from the environment per call.

    Read per call rather than cached so a boundary can be retuned on a running
    instance (``OFE_CORPUS_WARN_HOURS`` / ``OFE_CORPUS_STALE_HOURS``) without a
    redeploy — which matters most during the exact incident where the cron is
    late and someone has to decide whether the API stays in rotation.

    ``warn`` is clamped to ``stale`` because the reverse ordering is incoherent:
    a corpus past the stale bound but short of a larger warn bound would be
    reported "fresh" by the same call that considers it stale.
    """
    warn = _hours_from_env("OFE_CORPUS_WARN_HOURS", _DEFAULT_WARN_HOURS)
    stale = _hours_from_env("OFE_CORPUS_STALE_HOURS", _DEFAULT_STALE_HOURS)
    return min(warn, stale), stale


# Import-time snapshot, for the callers that build static config at module scope
# (admin.py's _HEALTH_THRESHOLDS table). Anything evaluating freshness per
# request should call corpus_freshness_thresholds() instead so an env override
# takes effect without a restart.
CORPUS_FRESHNESS_WARN_HOURS, CORPUS_FRESHNESS_STALE_HOURS = corpus_freshness_thresholds()


def corpus_last_updated_at(processed_dir: Path | None = None) -> str | None:
    """ISO-8601 timestamp of the last corpus refresh, or None if unknown.

    The returned string is always timezone-aware: ``write_status`` stores a
    naive-UTC snapshot timestamp, and callers subtract it from an aware
    ``now()`` — a naive value would raise instead of reporting an age.
    """
    base = processed_dir if processed_dir is not None else _PROCESSED_DIR
    snapshot = base / "collector_status.json"
    if snapshot.exists():
        try:
            with snapshot.open("r", encoding="utf-8") as f:
                ts = json.load(f).get("timestamp")
            if isinstance(ts, str) and ts:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.isoformat()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    work_file = base / "opportunities.json"
    if work_file.exists():
        return datetime.fromtimestamp(work_file.stat().st_mtime, tz=UTC).isoformat()
    shards = base / "shards"
    if shards.is_dir():
        try:
            newest = max((p.stat().st_mtime for p in shards.glob("*.json")), default=None)
        except OSError:
            newest = None
        if newest:
            return datetime.fromtimestamp(newest, tz=UTC).isoformat()
    return None
