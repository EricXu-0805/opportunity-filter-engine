"""Every number the fix/tailor-review acceptance criteria need, each with the script it comes from.

Criterion (6): every number in the PR description names the script or test it
comes from. This script runs the committed measurement scripts and prints their
summary lines under the criterion each one serves, prefixed by the script:

  (2) scripts/measure_rewrite_refusals.py (needs --main-root, a checkout of
      origin/main: main's checks run in a subprocess there) and
      scripts/faithful_keeps_any_row.py on its rows;
  (3) scripts/other_script_probe.py;
  (4) scripts/rewrite_route_lag.py (worst stall per route), scripts/request_parse_lag.py,
      scripts/worst_inputs_lag.py and scripts/rewrite_check_lag.py (the slow one,
      about 4 minutes; --skip-slow leaves it out); --concurrent 1,4,10 (the default)
      sends 1, then 4, then 10 identical requests at once in the two route scripts, ten
      being one client's limit for /api/tailor* (backend/main.py RATE_LIMITS);
  (5) scripts/trap_review_reach.py.

Criterion (1)'s evidence is tests, not a count: tests/test_rewrite_display_paths.py,
tests/test_rewrite_display_paths_r2.py, tests/test_rewrite_display_paths_r3.py and the
frontend tests they name.

Run from the repository root:

    git worktree add ../main-checkout origin/main
    python scripts/rewrite_review_counts.py --main-root ../main-checkout [--skip-timing] [--skip-slow] [--concurrent 1,4,10]

Timings vary with load: check the load average (uptime) and re-run on a quiet
machine before reading a timing as a failure.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
STALL = re.compile(r"^(?:ok|OVER)\s+([\d.]+) ms lag")


def run(script: str, *args: str) -> list[str]:
    command = [sys.executable, str(ROOT / "scripts" / script), *args]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False,
                            env={**os.environ, "PYTHONWARNINGS": "ignore"})
    if result.returncode not in (0, 1):
        sys.stderr.write(result.stderr)
        raise SystemExit(f"{script} failed with exit code {result.returncode}")
    return result.stdout.splitlines()


def show(script: str, lines: list[str]) -> None:
    for line in lines:
        print(f"  [scripts/{script}] {line.strip()}")


def pick(lines: list[str], *starts: str) -> list[str]:
    return [line for line in lines if line.strip().startswith(starts)]


def worst_stall(lines: list[str]) -> str:
    stalls = [(float(match.group(1)), line.strip()) for line in lines if (match := STALL.match(line.strip()))]
    if not stalls:
        return "no cases"
    value, line = max(stalls)
    return f"worst {value:.1f} ms lag over {len(stalls)} cases: {line}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--main-root", help="a checkout of origin/main, for criterion (2)'s comparison")
    parser.add_argument("--skip-timing", action="store_true", help="leave out criterion (4)'s timing scripts")
    parser.add_argument("--skip-slow", action="store_true", help="leave out scripts/rewrite_check_lag.py")
    parser.add_argument("--concurrent", default="1,4,10",
                        help="identical requests sent at once by the route scripts, one level after another")
    args = parser.parse_args()

    print("criterion (2): faithful rewrites judged fabricated; new refusals relative to main")
    if args.main_root:
        with tempfile.TemporaryDirectory() as scratch:
            rows = str(Path(scratch) / "refusals.json")
            lines = run("measure_rewrite_refusals.py", "--main-root", args.main_root, "--json", rows)
            show("measure_rewrite_refusals.py", pick(lines, "same-language pairs", "corpus:", "evidence_map_cases:",
                                                     "tests:", "(a)", "of which corpus", "main accepts", "(b)"))
            show("faithful_keeps_any_row.py", pick(run("faithful_keeps_any_row.py", rows),
                                                   "faithful,", "reach the review", "kept under", "of which", "by source"))
    else:
        print("  (skipped: pass --main-root <checkout of origin/main>)")

    print("criterion (3): rewrites shown in another language than their line")
    show("other_script_probe.py", pick(run("other_script_probe.py"), "relabel out", "own conjunction", "English function"))

    if not args.skip_timing:
        print(f"criterion (4): event-loop stalls at the input caps (concurrent requests: {args.concurrent})")
        concurrent = ["--concurrent", args.concurrent]
        lines = run("rewrite_route_lag.py", *concurrent)
        start = next((i for i, line in enumerate(lines) if line.startswith("worst per route")), len(lines))
        show("rewrite_route_lag.py", lines[start:])
        lines = run("worst_inputs_lag.py", *concurrent)
        show("worst_inputs_lag.py", pick(lines, "over "))
        lines = run("request_parse_lag.py")
        show("request_parse_lag.py", [worst_stall(lines), *pick(lines, "over ")])
        if not args.skip_slow:
            show("rewrite_check_lag.py", pick(run("rewrite_check_lag.py"), "shapes:"))

    print("criterion (5): same-language traps that reach the review")
    show("trap_review_reach.py", pick(run("trap_review_reach.py"), "corpus:", "all samples", "criterion (5)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
