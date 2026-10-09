#!/usr/bin/env python3
"""Process time of the contract plus the claim locks on adversarial units at the 6,000-character cap.

The shapes aim at the code the last review round added: the role-noun reading
(_names_another_doer), the and/or gerund chain without any "and"/"or", the
personal_first clause rule and the support-line rebinding in gate(). Measured as
tests/test_rewrite_cpu_bounds.py measures (fastest of three, contract + locks,
three declarations), in Tailor and full-target form, alone and with a support line.
Run from the repository root: python3 scripts/cpu_new_shapes_probe.py
"""
from __future__ import annotations

import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from backend.lib import evidence_map as em  # noqa: E402
from tests.test_rewrite_cpu_bounds import CAP, _declarations, _fit, _unit  # noqa: E402


def _seconds(read):
    best = float("inf")
    for _ in range(3):
        started = time.process_time()
        read()
        best = min(best, time.process_time() - started)
    return best


SHAPES = {
    "gerunds, no and/or": lambda m: (_fit("helped aing ", CAP), "Helped aing.", "Aing, helped."),
    "gerunds, and + noun": lambda m: (_fit("helped aing and x ", CAP), "Helped aing and x.", "Aing and x, helped."),
    "role noun, names": lambda m: ("Professor " + _fit("Lee ", CAP - 40) + " designed the study.",
                                   "Professor Lee designed the study.", "Designed the study."),
    "role noun, many clauses": lambda m: (_fit("TA for x, ", CAP), "TA for x, grading.", "Graded as TA for x."),
    "role noun, words": lambda m: ("TA " + _fit("x ", CAP - 30) + " designed it.", "TA x designed it.",
                                   "Designed it as TA x."),
    "personal_first, with": lambda m: (_fit("built it with a friend; I wrote x with y. ", CAP),
                                       "Built it with a friend; I wrote x.", "Wrote x with a friend and built it."),
    "zh role noun": lambda m: (_fit("导师亲自设计了实验，", CAP), "导师亲自设计了实验。", "设计了实验（导师亲自）。"),
}
MODES = {"tailor": "tailor", "full target": "fulltarget"}

worst = 0.0
for name, shape in SHAPES.items():
    for mode, key in MODES.items():
        for support in (False, True):
            evidence, current, rewrite = shape(key)
            unit = _unit(evidence, current, key, support)
            anchors, declarations = _declarations(rewrite)
            language = em.language(unit.current)
            contract = 0.0
            for ops, links in declarations:
                row = {"unit_id": "b1", "decision": "rewrite", "text": rewrite, "keep_reason": None,
                       "links": links, "ops": ops}
                contract = max(contract, _seconds(partial(em.check_rewrite, unit, row, anchors,
                                                          output_language=language)))
            locks = _seconds(partial(em.gate, em.Outcome("b1", "pending", text=rewrite), unit))
            worst = max(worst, contract + locks)
            print(f"{name:26} {mode:11} {'support' if support else 'alone':7} "
                  f"contract {contract:.3f} s  locks {locks:.3f} s  total {contract + locks:.3f} s")
print(f"worst total: {worst:.3f} s (budget 0.25 s)")
