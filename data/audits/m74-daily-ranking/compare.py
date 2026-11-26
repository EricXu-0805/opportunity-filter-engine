"""Compare two complete checked-out releases, using the normal local HTTP application."""
import dataclasses
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time

# The audit script is external to this candidate's application checkout.
sys.path.insert(0, os.getcwd())
from scripts.measure_match_latency import FIRST_PAGE_VIEW, ISOLATION_ENV, PERSONAS
os.environ.update(ISOLATION_ENV)

from backend import data_loader
from backend.main import app
from backend.routes import matches
from fastapi.testclient import TestClient
from src.matcher import ranker


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run(destination):
    rows = []
    for path in sorted(Path("data/processed/shards").glob("*.json")):
        rows.extend(json.loads(path.read_bytes()))
    assert len(rows) == len({row["id"] for row in rows})
    rows = data_loader._canonicalize_corpus(rows)
    data_loader._maybe_fit_tfidf(rows, 0)
    ranker.register_corpus(rows)
    matches.load_opportunities_generation = lambda: (rows, "same-complete-corpus")
    start = time.monotonic()
    matches.prepare_match_views(rows)
    warm_seconds = time.monotonic() - start
    client = TestClient(app)
    result = {"ids": len(rows), "warm_seconds": warm_seconds, "profiles": {}}
    for profile in ("uiuc_cs_cross_all3", "ucb_eecs"):
        body = {"profile": PERSONAS[profile], "page_size": 50,
                "view": {**FIRST_PAGE_VIEW, "tab": "all", "today": date.today().isoformat()}}
        last = {}
        timings = []
        hashes = []
        for phase in ["first"] + ["repeat"] * 4 + ["next"] * 3 + ["search", "hide", "restore"]:
            request = {**body, "view": dict(body["view"])}
            if phase == "next":
                request["cursor"] = last["next_cursor"]
            elif phase == "search":
                request["view"]["search_query"] = "machine learning"
            elif phase == "hide":
                request["view"]["dismissed_ids"] = [rows[5]["id"]]
            start, cpu = time.monotonic(), time.process_time()
            response = client.post("/api/matches/view?llm=false", json=request)
            timings.append([phase, time.monotonic()-start, time.process_time()-cpu])
            response.raise_for_status()
            last = response.json()
            hashes.append(digest(last))
            if phase == "first":
                snapshot = list(matches._match_snapshots.values())[-1]
                whole_ranking = hashlib.sha256()
                for row in snapshot.visible:
                    whole_ranking.update(digest(dataclasses.asdict(row)).encode())
                visible = len(snapshot.visible)
        result["profiles"][profile] = {
            "ranked": visible, "full_ranking_sha256": whole_ranking.hexdigest(),
            "http_sha256": hashes, "times_seconds": timings,
        }
    # Ubuntu reports peak RSS in KiB.
    result["peak_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    Path(destination).write_text(json.dumps(result, indent=2)+"\n")


def compare(directory):
    root = Path(directory)
    runs = {p.stem: json.loads(p.read_text()) for p in root.glob("run-*.json")}
    before = [runs["run-base1"], runs["run-base2"]]
    after = [runs["run-candidate1"], runs["run-candidate2"]]
    assert len({v["ids"] for v in runs.values()}) == 1
    summary = {"ids": before[0]["ids"], "observations": {}, "peak_mib": {}}
    for profile in before[0]["profiles"]:
        first = before[0]["profiles"][profile]
        assert all(v["profiles"][profile]["http_sha256"] == first["http_sha256"] and
                   v["profiles"][profile]["full_ranking_sha256"] == first["full_ranking_sha256"]
                   for v in runs.values())
        summary["observations"][profile] = {
            "ranked": first["ranked"], "full_ranking_sha256": first["full_ranking_sha256"],
            "base_first": [v["profiles"][profile]["times_seconds"][0][1:] for v in before],
            "candidate_first": [v["profiles"][profile]["times_seconds"][0][1:] for v in after],
        }
    for key, group in (("base", before), ("candidate", after)):
        summary["peak_mib"][key] = [round(v["peak_mib"],3) for v in group]
        summary.setdefault("startup_seconds",{})[key] = [v["warm_seconds"] for v in group]
    summary["peak_median_difference_mib"] = statistics.median(summary["peak_mib"]["candidate"]) - statistics.median(summary["peak_mib"]["base"])
    summary["peak_maximum_difference_mib"] = max(summary["peak_mib"]["candidate"]) - max(summary["peak_mib"]["base"])
    print(json.dumps(summary,indent=2))
    (root/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    assert max(summary["peak_median_difference_mib"],summary["peak_maximum_difference_mib"]) <= 100


if __name__ == "__main__":
    (compare if sys.argv[1] == "compare" else run)(sys.argv[2])
