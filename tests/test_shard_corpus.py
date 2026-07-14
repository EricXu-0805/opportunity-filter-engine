"""Offline tests for scripts/shard_corpus.py — the split shrink guard.

Locks in the safeguard that a flaked re-scrape (Cloudflare/AWS-WAF/render
failing on CI's IP, or an assemble-skip on a stale work file) can never clobber
an established school's committed shard: if a school's new shard would drop
below SHRINK_KEEP_RATIO of the already-committed shard (>= SHRINK_GUARD_FLOOR
records), the prior shard is kept untouched.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from shard_corpus import split


def _recs(school: str, n: int) -> list[dict]:
    return [{"school": school, "id": f"{school}-{i}", "title": f"Research {i}"}
            for i in range(n)]


def _write(work_file: Path, records: list[dict]) -> None:
    work_file.write_text(json.dumps(records), encoding="utf-8")


def _shard_count(shards_dir: Path, slug: str) -> int:
    return len(json.loads((shards_dir / f"{slug}.json").read_text(encoding="utf-8")))


def test_split_writes_per_school_shards(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    _write(wf, _recs("cornell", 150) + _recs("rice", 50))
    counts = split(wf, sd)
    assert counts == {"cornell": 150, "rice": 50}
    assert _shard_count(sd, "cornell") == 150


def test_shrink_guard_keeps_prior_shard(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "cornell.json").write_text(json.dumps(_recs("cornell", 200)), encoding="utf-8")
    _write(wf, _recs("cornell", 120))  # 60% < 70% → flaked, keep prior
    counts = split(wf, sd)
    assert counts["cornell"] == 200            # reported as the retained count
    assert _shard_count(sd, "cornell") == 200  # committed shard untouched


def test_modest_drop_updates_normally(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "cornell.json").write_text(json.dumps(_recs("cornell", 200)), encoding="utf-8")
    _write(wf, _recs("cornell", 150))  # 75% ≥ 70% → real attrition, update
    counts = split(wf, sd)
    assert counts["cornell"] == 150
    assert _shard_count(sd, "cornell") == 150


def test_small_shard_not_guarded(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "tiny.json").write_text(json.dumps(_recs("tiny", 40)), encoding="utf-8")
    _write(wf, _recs("tiny", 5))  # big drop but below the 100-record floor → update
    counts = split(wf, sd)
    assert counts["tiny"] == 5
    assert _shard_count(sd, "tiny") == 5


def test_growth_updates_normally(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "cornell.json").write_text(json.dumps(_recs("cornell", 200)), encoding="utf-8")
    _write(wf, _recs("cornell", 260))  # grew → update
    counts = split(wf, sd)
    assert counts["cornell"] == 260
    assert _shard_count(sd, "cornell") == 260


def test_new_school_writes_without_guard(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    _write(wf, _recs("newschool", 300))  # no prior shard → writes freely
    counts = split(wf, sd)
    assert counts["newschool"] == 300
    assert _shard_count(sd, "newschool") == 300
