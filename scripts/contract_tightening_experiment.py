"""What a logic-only contract tightening would cost: traps and faithful pairs that reach the review, before and after.

Criterion (5) counts same-language traps that reach the review; under any row
scripts/trap_review_reach.py's exhaustive search finds, the corpus count is 19
(limit 14). The rows that let them through are relabels to a narrower or
different thing, a participle of another person made the student's verb under
lead_with alone, two words swapped between actions under lead_with alone, a new
action, and a dropped 近. This script tries the tightenings a reviewer or fixer
proposed, each logic only (no lock list, word, character or family is added; the
rules read the row's own spans and the frozen tokens()), by monkeypatching
backend.lib.evidence_map in this process, and counts with trap_review_reach's
searches:

  narrowing   refuse a relabel whose "to" holds every word of its "from" plus more
              (round-2 numbers review);
  surface     under a row of lead_with (and tighten) only, refuse a content word in a
              surface form the line does not use ("operating" -> "Operated");
  moved       under the same rows, refuse a content word that left both its
              neighbours (_number_moved generalised from numbers to every word);
  lead_with   surface and moved together.

Traps are the deduplicated union of trap_review_reach's sample sets; faithful pairs
are the same-language faithful pairs of scripts/measure_rewrite_refusals.py --json.

Run from the repository root:
    python scripts/measure_rewrite_refusals.py --main-root <checkout of origin/main> --json refusals.json
    python scripts/contract_tightening_experiment.py refusals.json {narrowing,surface,moved,lead_with}

Deterministic; about 90 seconds per mode.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "scripts"))
import trap_review_reach as reach  # noqa: E402

from backend.lib import evidence_map as em  # noqa: E402

CHECK_REWRITE, CHECK_SAME_LANGUAGE = em.check_rewrite, em._check_same_language
TOKEN = re.compile(r"[A-Za-z0-9]+|[一-鿿]")


def narrows(op) -> bool:
    if not isinstance(op, dict) or op.get("op") != "relabel":
        return False
    source = Counter(t.casefold() for t in TOKEN.findall(str(op.get("from") or "")))
    target = Counter(t.casefold() for t in TOKEN.findall(str(op.get("to") or "")))
    return bool(source) and not (source - target) and sum(target.values()) > sum(source.values())


def narrowing_check_rewrite(unit, row, anchors, **kwargs):
    if isinstance(row, dict) and any(narrows(op) for op in row.get("ops") or ()):
        return em._keep(unit, "beyond_allowed_edit", "relabel_narrows")
    return CHECK_REWRITE(unit, row, anchors, **kwargs)


def surface_words(text: str) -> set[str]:
    text = em._PERSONAL_MARKER.sub(" ", text).replace("-", " ")
    return {word.casefold() for word in re.findall(r"[A-Za-z]+(?:'[a-z]+)?", text) if word.casefold() not in em._FUNCTION_EN}


def word_moved(current: str, text: str) -> bool:
    before = em.tokens(current)
    known, pairs = set(before), set(zip([None, *before], [*before, None], strict=True))
    for clause in em._FIRST_CLAUSE.split(text):
        padded = [None, *em.tokens(clause), None]
        for i in range(2, len(padded) - 1):
            token = padded[i]
            if token in known and (padded[i - 1], token) not in pairs and (token, padded[i + 1]) not in pairs:
                return True
    return False


def lead_with_check(rules):
    def check(unit, text, links, ops_raw):
        outcome = CHECK_SAME_LANGUAGE(unit, text, links, ops_raw)
        names = {op.get("op") for op in ops_raw}
        if outcome.status != "pending" or "lead_with" not in names or not names <= {"lead_with", "tighten"}:
            return outcome
        own = surface_words(unit.current).union(*(surface_words(source) for _, source in unit.sources))
        if "surface" in rules and surface_words(text) - own:
            return em._keep(unit, "beyond_allowed_edit", "lead_with_new_form", links=links)
        if "moved" in rules and word_moved(unit.current, text):
            return em._keep(unit, "beyond_allowed_edit", "lead_with_word_moved", links=links)
        return outcome
    return check


def reaches(sample) -> tuple[bool, bool]:
    if not reach.locks_pass(sample)[0]:
        return False, False
    unit, anchors = reach.unit_for(sample), reach.pair_anchors(sample)
    _, gated = reach.checked(unit, reach.suite_row(sample), anchors)
    suite = bool(gated and gated.status == "pending")
    return suite, suite or reach.exhaustive(sample, stop_at_contract=False)[1] is not None


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("narrowing", "surface", "moved", "lead_with"):
        print(__doc__)
        return 2
    faithful = [{"original": r["original"], "rewrite": r["rewrite"], "support": (), "source": r["source"],
                 "kind": r.get("kind"), "label": "faithful"}
                for r in json.loads(Path(argv[0]).read_text()) if r["label"] == "faithful"]
    traps, seen = [], set()
    for sample in reach.corpus_traps() + reach.case_traps() + reach.test_traps():
        key = (sample["original"], sample["rewrite"], tuple(sample["support"]))
        if key not in seen:
            seen.add(key)
            traps.append(sample)
    sets = (("traps", traps), ("faithful", faithful))
    # Keyed by position too: one test's parametrizations share a source name.
    before = {name: {f"{s['source']} #{i}": reaches(s) for i, s in enumerate(samples)} for name, samples in sets}
    if argv[1] == "narrowing":
        em.check_rewrite = narrowing_check_rewrite
    else:
        em._check_same_language = lead_with_check({"surface", "moved"} if argv[1] == "lead_with" else {argv[1]})
    after = {name: {f"{s['source']} #{i}": reaches(s) for i, s in enumerate(samples)} for name, samples in sets}
    print(f"mode: {argv[1]}")
    for name in ("traps", "faithful"):
        old, new = before[name], after[name]
        corpus = [key for key in old if key.startswith("corpus")]
        print(f"{name}: {len(old)} (corpus {len(corpus)}); reach the review under the suite row "
              f"{sum(s for s, _ in old.values())} -> {sum(s for s, _ in new.values())}; under any row "
              f"{sum(a for _, a in old.values())} -> {sum(a for _, a in new.values())} "
              f"(corpus {sum(old[k][1] for k in corpus)} -> {sum(new[k][1] for k in corpus)})")
        for key in old:
            if old[key] != new[key]:
                print(f"  changed: {key} suite/any {old[key]} -> {new[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
