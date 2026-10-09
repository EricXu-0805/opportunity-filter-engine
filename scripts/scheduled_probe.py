#!/usr/bin/env python3
"""Does the lock gate refuse a rewrite that drops "scheduled" from a not-yet-run study?

Run from the repository root: python3 scripts/scheduled_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from backend.lib import evidence_map as em  # noqa: E402

PAIRS = [
    # Traps: the study has not run yet; the rewrite drops the word that says so.
    ("Designed the protocol for a scheduled EEG study with 30 participants.",
     "Designed the protocol for an EEG study with 30 participants."),
    ("Recruited 30 participants for the scheduled sleep study.", "Recruited 30 participants for the sleep study."),
    ("Prepared materials for a scheduled clinical trial of 40 patients.",
     "Prepared materials for a clinical trial of 40 patients."),
    # Faithful controls (routine work done to a schedule), from the branch's ROLE_LINES.
    ("Lab technician intern, performing the scheduled maintenance of -80 freezers.",
     "Performed scheduled maintenance of -80 freezers as lab technician intern."),
    ("Responsible for the scheduled cleaning of the fume hoods each Friday.",
     "Cleaned the fume hoods each Friday on schedule."),
    # Still planned on every head.
    ("Recruited 30 participants for a study scheduled for May.", "Recruited 30 participants for a study."),
]
reached = 0
for original, rewrite in PAIRS:
    findings = [*em.grounding_findings(rewrite, original), *em.rewrite_findings(rewrite, original, [])]
    reached += not findings
    print(f"{'PASS-TO-REVIEW' if not findings else 'refused':14} {sorted(set(findings))!s:28} {original} -> {rewrite}")
print(f"reaching the review: {reached} of {len(PAIRS)}")
