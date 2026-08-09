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
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

_PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


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
