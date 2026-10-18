#!/usr/bin/env python3
"""Is a hand-exported snapshot due for a new export? Checked once a week by
.github/workflows/snapshot-reminder.yml.

CMU's undergraduate research project list opens only for a CMU login, so it
reaches the corpus as a snapshot someone exports by hand
(data/snapshots/cmu_uro_projects.json). This reads the snapshot's own dates
and prints the reminder and writes the email the workflow sends every week
while a refresh is due or the snapshot is within 30 days of its end date.
Past the end date the rows are retired, so the email goes out on the first
weekly run after it and then every fifth week, never more than once a month.
The decision and the wording come from ``src.collectors.cmu_uro_projects`` —
the same functions the ops-scan incident uses.

The workflow is scheduled every day because GitHub starts scheduled runs
hours late and sometimes not at all (snapshot-reminder.yml says what was
seen), and a weekly job that misses once is silent for two weeks. The first
run of a week to succeed does that week's check, as of the week's Monday so
a late run sends exactly what Monday's would have; the runs after it find it
in ``--earlier-runs`` and stop.

Exit status is 0 whether or not anything is due; 1 only when the snapshot
cannot be read or fails validation.

Usage:
    python3 scripts/snapshot_reminder.py
    python3 scripts/snapshot_reminder.py --today 2027-01-11
    python3 scripts/snapshot_reminder.py --github-output "$GITHUB_OUTPUT" \\
        --email-payload "$RUNNER_TEMP/snapshot-reminder.json" \\
        --earlier-runs "$RUNNER_TEMP/earlier-runs.json"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors import cmu_uro_projects  # noqa: E402

DEFAULT_FROM = "JoinALab <onboarding@resend.dev>"


def _run_link() -> str | None:
    server, repo, run = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run}" if server and repo and run else None


def week_start(day: date) -> date:
    """The Monday of ``day``'s week (UTC): the date a week's check is made as of."""
    return day - timedelta(days=day.weekday())


def earlier_check(runs_file: Path, monday: date, this_run: str | None) -> str | None:
    """The link to a run that already did this week's check, if there is one.

    ``runs_file`` holds ``gh run list --status success --json
    databaseId,createdAt,url`` for this workflow. A file that is missing (a
    manual run lists nothing) or unreadable finds no run: the check is made,
    since a second email in a week costs less than none.
    """
    if not runs_file.exists():
        return None
    try:
        runs = json.loads(runs_file.read_text(encoding="utf-8"))
        for run in runs:
            created = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
            if created.astimezone(UTC).date() >= monday and str(run["databaseId"]) != this_run:
                return run["url"]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"::warning::cannot read the earlier runs ({exc}); checking anyway", file=sys.stderr)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", type=date.fromisoformat, default=None,
                        help="run as on this ISO date (default: today, UTC); the check is "
                             "made as of the Monday of its week")
    parser.add_argument("--snapshot", type=Path, default=None, help="snapshot file to check")
    parser.add_argument("--github-output", type=Path, default=None,
                        help="append due=true|false for later workflow steps")
    parser.add_argument("--email-payload", type=Path, default=None,
                        help="when due, write the Resend request body here")
    parser.add_argument("--earlier-runs", type=Path, default=None,
                        help="this workflow's successful runs (gh run list --json "
                             "databaseId,createdAt,url); one from this week means the check is done")
    args = parser.parse_args(argv)

    monday = week_start(args.today or datetime.now(UTC).date())
    done = (earlier_check(args.earlier_runs, monday, os.environ.get("GITHUB_RUN_ID"))
            if args.earlier_runs is not None else None)
    if done:
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as out:
                out.write("due=false\n")
        print(f"this week's check (week of {monday}) was made by {done}; nothing to do")
        return 0

    try:
        snapshot = cmu_uro_projects.load_snapshot(args.snapshot)
    except (OSError, ValueError) as exc:
        print(f"::error::cannot read the snapshot: {exc}", file=sys.stderr)
        return 1
    status = cmu_uro_projects.refresh_status(snapshot, monday)
    print(f"{snapshot['snapshot']['name']}: {status['state']} (taken {status['snapshot_date']}, "
          f"refresh due {status['refresh_due']}, shown until {status['valid_until']})")

    send = cmu_uro_projects.email_due(status)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as out:
            out.write(f"due={'true' if send else 'false'}\n")
    if not send:
        print("past the end date: the notice goes out on the first weekly run after it and then "
              "every fifth week, and this is not one of those weeks; no email"
              if status["due"] else "nothing is due; no email")
        return 0

    note = cmu_uro_projects.reminder(snapshot, status)
    text = note["text"]
    link = _run_link()
    if link:
        text += f"\n\nChecked by {link}"
    print(text)
    if args.email_payload is not None:
        args.email_payload.write_text(json.dumps({
            "from": os.environ.get("RESEND_FROM") or DEFAULT_FROM,
            "to": [os.environ.get("OPERATOR_EMAIL", "")],
            "subject": note["subject"],
            "text": text,
        }), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
