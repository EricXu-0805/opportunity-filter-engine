"""Faithful same-language rewrites main shows that the branch keeps as written, under ANY row (criterion 2).

Criterion (2): 0 faithful rewrites are judged fabricated, and same-language
rewrites get no new rejections relative to main. scripts/measure_rewrite_refusals.py
counts the faithful pairs main accepts that the branch does not send to the
review under the rows it tries (a contract keep: beyond_allowed_edit or
cosmetic_only, never a fabrication finding on a route). This script asks
whether such a keep is only an artifact of those rows: it runs each pair through
scripts/trap_review_reach.py's exhaustive row search, the same search criterion
(5) counts traps with.

Run from the repository root, after measure_rewrite_refusals.py has written its rows:

    python scripts/measure_rewrite_refusals.py --main-root <checkout of origin/main> --json refusals.json
    python scripts/faithful_keeps_any_row.py refusals.json

Prints how many reach the review under some row and how many are kept under
every row searched, by source, and each pair kept. Deterministic.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "scripts"))
import trap_review_reach as reach  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    rows = json.loads(Path(argv[0]).read_text())
    keeps = [row for row in rows if row["label"] == "faithful"
             and (row["main"].get("tailor") or row["main"].get("full_target")) and not row["branch_reviewed"]]
    print("faithful, main accepts, branch does not reach the review (tried rows):", len(keeps))
    passes, kept = [], []
    for row in keeps:
        sample = {"original": row["original"], "rewrite": row["rewrite"], "support": (), "source": row["source"],
                  "kind": row.get("kind"), "label": "faithful"}
        _, findings = reach.locks_pass(sample)
        _, gated_row = reach.exhaustive(sample, stop_at_contract=False)
        (passes if gated_row else kept).append((row, findings))
    print("  reach the review under some row of the exhaustive search:", len(passes))
    print("  kept under every row searched:", len(kept))
    print("  of which corpus pairs:", sum(row["source"].startswith("corpus:") for row, _ in kept))
    print("  by source:", dict(Counter(row["source"].split(":")[0].split("[")[0] for row, _ in kept)))
    for row, findings in kept:
        print(f"  - [{row['source']}] {row['original']!r} -> {row['rewrite']!r} locks={findings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
