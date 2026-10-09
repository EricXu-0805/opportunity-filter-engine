#!/usr/bin/env python3
"""A role noun whose own verb sits in the next clause (after a comma, "then", "who"...).

Run from the repository root: python3 scripts/actor_clause_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from backend.lib import evidence_map as em  # noqa: E402

TRAPS = [
    ("Professor Lee, who leads the lab, designed the study; I recruited 30 participants.",
     "Designed the study; recruited 30 participants."),
    ("Professor Lee, PI of the lab, designed the study; I recruited 30 participants.",
     "Designed the study; recruited 30 participants."),
    ("Professor Lee then designed the study; I recruited 30 participants.",
     "Designed the study and recruited 30 participants."),
    ("Supervisor Lee, an expert in EEG, designed the study; I recruited 30 participants.",
     "Designed the study; recruited 30 participants."),
]
reached = 0
for original, rewrite in TRAPS:
    findings = [*em.grounding_findings(rewrite, original), *em.rewrite_findings(rewrite, original, [])]
    reached += not findings
    print(f"{'PASS-TO-REVIEW' if not findings else 'refused':14} {sorted(set(findings))!s:20} {original} -> {rewrite}")
print(f"reaching the review: {reached} of {len(TRAPS)}")
