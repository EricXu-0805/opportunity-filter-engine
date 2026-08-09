"""Corpus-freshness reader (W16 extraction of the W15 admin fix).

The public /opportunities/stats/summary endpoint used to stat the GITIGNORED
work file data/processed/opportunities.json, so `last_updated_at` was always
null in production and the only user-facing freshness signal rendered nothing.
Admin already had the fix; these tests pin the now-SHARED helper so the two
surfaces cannot drift apart again — and pin that "unknown" stays None rather
than degrading into a confident-looking zero age.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from backend.lib.corpus_freshness import corpus_last_updated_at
from backend.main import app

client = TestClient(app)


def _write_snapshot(processed: Path, timestamp: str) -> None:
    (processed / "collector_status.json").write_text(
        json.dumps({"timestamp": timestamp, "collectors": {}}), encoding="utf-8"
    )


class TestSnapshotTimestamp:
    def test_reads_the_collector_snapshot_timestamp(self, tmp_path):
        stamp = "2026-07-01T04:05:06+00:00"
        _write_snapshot(tmp_path, stamp)
        assert corpus_last_updated_at(tmp_path) == stamp

    def test_naive_snapshot_timestamp_is_normalized_to_utc(self, tmp_path):
        # write_status stores a naive-UTC string; callers subtract it from an
        # aware now(), which raises on a naive value.
        _write_snapshot(tmp_path, "2026-07-01T04:05:06")
        parsed = datetime.fromisoformat(corpus_last_updated_at(tmp_path))
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)

    def test_snapshot_wins_over_the_local_work_file(self, tmp_path):
        # The work file exists only in dev/CI; the committed snapshot is what
        # survives a deploy, so it is the authoritative signal.
        _write_snapshot(tmp_path, "2026-07-01T04:05:06+00:00")
        (tmp_path / "opportunities.json").write_text("[]", encoding="utf-8")
        assert corpus_last_updated_at(tmp_path) == "2026-07-01T04:05:06+00:00"

    def test_unusable_snapshot_falls_through_instead_of_raising(self, tmp_path):
        (tmp_path / "collector_status.json").write_text("{not json", encoding="utf-8")
        shards = tmp_path / "shards"
        shards.mkdir()
        (shards / "a.json").write_text("[]", encoding="utf-8")
        value = corpus_last_updated_at(tmp_path)
        assert value is not None
        assert datetime.fromisoformat(value).tzinfo is not None

    def test_snapshot_without_a_timestamp_field_falls_through(self, tmp_path):
        (tmp_path / "collector_status.json").write_text('{"collectors": {}}', encoding="utf-8")
        assert corpus_last_updated_at(tmp_path) is None


class TestShardFallback:
    def test_falls_back_to_the_newest_shard_mtime(self, tmp_path):
        # Production ships shards but no snapshot only in a partial deploy;
        # reporting the newest shard beats reporting nothing.
        shards = tmp_path / "shards"
        shards.mkdir()
        older = shards / "mon.json"
        newer = shards / "tue.json"
        older.write_text("[]", encoding="utf-8")
        newer.write_text("[]", encoding="utf-8")
        old_mtime = time.time() - 86_400
        os.utime(older, (old_mtime, old_mtime))
        value = corpus_last_updated_at(tmp_path)
        assert value is not None
        expected = datetime.fromtimestamp(newer.stat().st_mtime, tz=UTC).isoformat()
        assert value == expected

    def test_empty_shard_directory_is_not_a_freshness_claim(self, tmp_path):
        (tmp_path / "shards").mkdir()
        assert corpus_last_updated_at(tmp_path) is None


class TestUnknownIsNone:
    def test_returns_none_when_nothing_is_available(self, tmp_path):
        # The honest answer when no source exists. Callers render "unknown";
        # they must never substitute now() (which would read as perfectly
        # fresh) or epoch 0 (which would read as infinitely stale).
        assert corpus_last_updated_at(tmp_path) is None

    def test_missing_directory_is_none_not_an_error(self, tmp_path):
        assert corpus_last_updated_at(tmp_path / "does-not-exist") is None


class TestSharedWithBothSurfaces:
    def test_admin_imports_the_shared_helper(self):
        # The whole point of the extraction: admin's private name is now an
        # alias for the shared function, so the two surfaces cannot diverge.
        from backend.routes import admin

        assert admin._opportunities_mtime is corpus_last_updated_at

    def test_public_stats_endpoint_uses_the_shared_helper(self):
        # The repo ships collector_status.json, so the public endpoint must
        # report a real timestamp — not the None the gitignored work file
        # produced in production.
        from backend.routes import opportunities as opportunities_routes

        opportunities_routes._stats_cache = None
        opportunities_routes._stats_cache_time = 0.0
        body = client.get("/api/opportunities/stats/summary").json()
        assert body["last_updated_at"] == corpus_last_updated_at()
        assert body["last_updated_at"] is not None
