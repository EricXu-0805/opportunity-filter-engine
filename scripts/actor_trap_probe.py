#!/usr/bin/env python3
"""Another person's action rewritten as the student's: does the lock gate refuse it?

Each pair is (original, verb_first rewrite) where the original names someone else
as the doer of an action and the rewrite drops that doer. The gate is the
evidence map's lock gate (grounding_findings + rewrite_findings), as
tests/test_tailor_review.py's gate_findings runs it. Run from the repository root:
    python3 scripts/actor_trap_probe.py
Prints one line per pair and the number of pairs the gate lets through.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from backend.lib import evidence_map as em  # noqa: E402

TRAPS = [
    # Plural role noun + present-tense verb (a base form in English).
    ("Technicians run the assays; I analyze the data.", "Run the assays and analyze the data."),
    ("TAs grade the exams; I proctor them.", "Grade the exams and proctor them."),
    ("Nurses record vital signs; I enter them into the chart.", "Record vital signs and enter them into the chart."),
    ("Mentors design the study; I recruit 30 participants.", "Design the study and recruit 30 participants."),
    ("Supervisors review each report; I draft them.", "Review each report and draft them."),
    # Pronoun + base verb or auxiliary.
    ("They analyze the samples; I prepare the slides.", "Analyze the samples and prepare the slides."),
    ("They are building the website; I write the content.", "Building the website and writing the content."),
    ("She can operate the SEM; I prepare the samples.", "Operate the SEM and prepare the samples."),
    # Chinese role noun + adverb or a second person before the verb.
    ("导师亲自设计了实验方案，本人完成了数据录入。", "设计了实验方案，完成了数据录入。"),
    ("导师也负责数据分析，本人完成了数据录入。", "负责数据分析，完成了数据录入。"),
    ("导师和博士生设计了实验方案，本人完成了数据录入。", "设计了实验方案，完成了数据录入。"),
    # A past form followed by a preposition, read as a participle describing a title.
    ("Professor Lee presented at the conference; I made the slides.", "Presented at the conference; made the slides."),
    ("PI applied for the NSF grant; I wrote the budget.", "Applied for the NSF grant; wrote the budget."),
    ("Supervisor worked on the assay; I wrote the report.", "Worked on the assay; wrote the report."),
    # A word that is not a verb, or a comma, between the title and its verb.
    ("Professor Lee then designed the study; I recruited 30 participants.",
     "Designed the study and recruited 30 participants."),
    ("He then wrote the grant; I edited it.", "Wrote the grant; edited it."),
    ("Dr. Lee, my mentor, designed the study; I recruited 30 participants.",
     "Designed the study; recruited 30 participants."),
    # Controls the branch's own test pins (should be refused on every head).
    ("Lab technician ran the assays; I analyzed the data.", "Ran the assays as lab technician; analyzed the data."),
    ("导师设计了实验方案，本人完成了数据录入。", "设计了实验方案（导师），完成了数据录入。"),
]


def gate(original: str, rewrite: str) -> list[str]:
    return [*em.grounding_findings(rewrite, original), *em.rewrite_findings(rewrite, original, [])]


passed = 0
for original, rewrite in TRAPS:
    findings = gate(original, rewrite)
    passed += not findings
    print(f"{'PASS-TO-REVIEW' if not findings else 'refused':14} {sorted(set(findings))!s:40} {original} -> {rewrite}")
print(f"traps reaching the review: {passed} of {len(TRAPS)}")
