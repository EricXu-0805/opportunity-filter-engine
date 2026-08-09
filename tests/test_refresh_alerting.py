"""The refresh workflow's operator alert must cover every way a run dies.

Its own file rather than a class in test_ops_plumbing.py: three other open
branches are editing the tail of TestWorkflowWiring, and a test that pins one
`if:` expression does not need to share their merge surface.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]


def _alert_step() -> dict:
    workflow = yaml.safe_load(
        (_REPO / ".github/workflows/refresh-data.yml").read_text()
    )
    job = next(iter(workflow["jobs"].values()))
    return next(
        step
        for step in job["steps"]
        if "Alert operator" in str(step.get("name", ""))
    )


def test_alert_fires_when_the_job_is_cancelled():
    """Exceeding timeout-minutes cancels the job; it does not fail it.

    `if: failure()` therefore skipped the alert on 2026-08-01, 08-03 and
    08-07 — three five-hour runs that produced nothing and told nobody.
    """
    condition = str(_alert_step().get("if", ""))

    assert "failure()" in condition
    assert "cancelled()" in condition


def test_alert_still_carries_the_run_link():
    """An alert that says only "it broke" costs a trip through the UI."""
    body = str(_alert_step().get("run", ""))

    assert "actions/runs/" in body
