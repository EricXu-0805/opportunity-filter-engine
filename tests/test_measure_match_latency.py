"""scripts/measure_match_latency.py (M27) runs end to end on a small corpus.

The script times the match route by wrapping its private functions by name.
A rename there has to fail here, not leave the script's breakdown empty the
next time someone needs the numbers.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import measure_match_latency as measure

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "measure_match_latency.py"


def _corpus() -> list[dict]:
    samples = json.loads((ROOT / "examples" / "sample_opportunities.json").read_text(encoding="utf-8"))
    records = []
    for school in ("uiuc", "ucb", "jhu", "mit", None):
        for index in range(8):
            record = copy.deepcopy(samples[index % len(samples)])
            record["id"] = f"measure-{school or 'national'}-{index}"
            record["school"] = school
            records.append(record)
    return records


def test_every_scenario_runs_and_every_wrapper_reports(tmp_path):
    data_dir = tmp_path / "processed"
    (data_dir / "shards").mkdir(parents=True)
    (data_dir / "shards" / "all.json").write_text(json.dumps(_corpus()), encoding="utf-8")
    # The deployed API reads the shards. A developer checkout also holds the
    # assembled work file, which the loader prefers; the script must not
    # measure that file instead.
    (data_dir / "opportunities.json").write_text(json.dumps(_corpus()[:8]), encoding="utf-8")
    out = tmp_path / "latency.json"
    # conftest turns snapshot reuse off for in-process suites; the script
    # must see the production default or every warm request ranks again.
    env = {**os.environ}
    env.pop("OFE_MATCH_SNAPSHOT_TTL", None)
    # The results page opens on High Priority, and these synthetic records all
    # score under its 70-point floor: without this every first page is empty
    # and the per-row response wrapper is never reached.
    env["OFE_BUCKET_HIGH"] = "0"

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--data-dir", str(data_dir),
            "--repeats", "1", "--warm-repeats", "1",
            "--cancel-after", "0.05", "--profile-cards", "5",
            "--json", str(out),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr[-4000:]
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["corpus"] == {"source": "shards", "data_dir": str(data_dir), "records": 40}
    assert set(document["boot"]["phases_s"]) >= {"canonicalize", "fit_tfidf", "register_matrix"}

    summary = {(row["scenario"], row["persona"]): row for row in document["summary"]}
    assert {scenario for scenario, _ in summary} == {
        "first", "home_cold", "home_warm", "cross_cold", "cross_warm", "home_after_cross",
        "cancel", "concurrent_home", "concurrent_mixed", "concurrent_warm", "concurrent_same",
    }
    for (scenario, persona), row in summary.items():
        if persona.endswith("(dropped)"):
            continue
        assert set(row["status"].split(",")) <= {"200", "200x4"}, (scenario, persona, row["status"])

    samples = document["samples"]
    ranked = [sample for sample in samples if sample.get("served_from") == "new_ranking"]
    assert ranked and all(sample.get("ranking") for sample in ranked)
    for sample in ranked:
        assert set(sample["ranking"]["phases_s"]) >= {"rank", "cards", "result_set_id", "store"}
        assert set(sample["ranking"]["calls"]) >= {"hard_exclusion", "eligibility", "score"}
        assert set(sample["request_phases_s"]) >= {
            "corpus_lookup", "release_filter", "actionable_filter", "view_pass", "page_rows",
        }
    assert any("static_builds" in sample["ranking"]["calls"] for sample in ranked)
    assert any("tfidf" in sample["ranking"]["calls"] for sample in ranked)
    warm = [sample for sample in samples if sample["scenario"] in ("home_warm", "cross_warm")]
    assert warm and {sample["served_from"] for sample in warm} == {"snapshot"}
    assert all(sample["returned_count"] > 0 for sample in samples if sample["status"] == 200)

    ranking_scenarios = [ranking["scenario"] for ranking in document["rankings"]]
    assert set(ranking_scenarios) >= {"first", "home_cold", "cross_cold", "cancel", "concurrent_home"}
    assert ranking_scenarios.count("memory_trace") == 2

    diagnostics = document["diagnostics"]
    assert diagnostics["card_projection_profile"]["cards"] == 5
    assert len(diagnostics["view_parity"]) == 16
    assert [trace["status"] for trace in diagnostics["memory_trace"]] == [200, 200]
    assert all(trace["snapshot_rows"] > 0 for trace in diagnostics["memory_trace"])


def _ranking(start: float, end: float) -> measure.ComputeRecord:
    return measure.ComputeRecord(key="k", persona="p", scenario="s", start=start, end=end, universe=1)


def test_a_miss_is_charged_to_the_ranking_that_answered_it():
    recorder = measure.Recorder()
    joined = _ranking(0.0, 2.0)
    own = _ranking(2.5, 4.0)
    # A later request's ranking of the same key, started while this one was
    # still writing its response.
    later = _ranking(4.2, 6.0)
    recorder.computes.extend([joined, own, later])

    def miss(start: float, end: float) -> measure.RequestRecord:
        return measure.RequestRecord("r", key="k", miss_start=start, miss_end=end)

    assert recorder.compute_for(miss(1.0, 2.0)) is joined
    assert recorder.compute_for(miss(2.4, 4.3)) is own
    assert recorder.compute_for(miss(4.1, 6.0)) is later
