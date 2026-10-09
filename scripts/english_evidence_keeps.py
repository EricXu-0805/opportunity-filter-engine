"""Same-language rewrites the default keep of criterion (3) keeps as written (round 4).

Criterion (3) of fix/tailor-review: a rewrite of a Latin-script line is shown only when the line
carries positive English evidence, two different English function words of three letters or more
outside the phrases the rewrite renames (backend.lib.evidence_map._english_line); without it the
line comes back as written (``beyond_allowed_edit``, ``english_unproven``), a contract keep under
the owner's reading (2b). This script counts what that costs.

Each same-language pair of scripts/measure_rewrite_refusals.py (the corpus, the evidence-map cases
and the faithful pairs the tests parametrize) runs through the same rows that script tries
(route_outcomes), twice: with the rule, and with _english_line answering True (no evidence asked).
A pair reaches the review when some row reaches it on the Tailor routes and on full target. A pair
the rule keeps reaches it without the rule and not with it.

Run from the repository root:

    python scripts/english_evidence_keeps.py [--list]

Prints, by source and label, the Latin-script pairs that reach the review without the rule and how
many of them the rule keeps; --list prints each kept pair. Deterministic; provider-free.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
logging.disable(logging.CRITICAL)

import measure_rewrite_refusals as refusals  # noqa: E402

from backend.lib import evidence_map as em  # noqa: E402


def reaches(pair: dict) -> bool:
    route = refusals.route_outcomes(pair["original"], pair["rewrite"], pair["rows"])
    return (any(item["tailor"][0] == "pending" for item in route)
            and any(item["full_target"][0] == "pending" for item in route))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--list", action="store_true", help="print every pair the rule keeps")
    args = parser.parse_args()
    pairs = [pair for pair in refusals.collect_pairs()
             if em.language(pair["original"]) == em.language(pair["rewrite"]) and not em._non_latin_frame(pair["original"])]
    rule = em._english_line
    for pair in pairs:
        pair["with_rule"] = reaches(pair)
    em._english_line = lambda line, renamed: True
    try:
        for pair in pairs:
            pair["without_rule"] = reaches(pair)
    finally:
        em._english_line = rule
    kept = [pair for pair in pairs if pair["without_rule"] and not pair["with_rule"]]
    gained = [pair for pair in pairs if pair["with_rule"] and not pair["without_rule"]]
    print(f"same-language pairs whose original is a Latin-script line: {len(pairs)}")
    for name, prefix in (("corpus", "corpus:"), ("evidence_map_cases", "evidence_map_cases:"), ("tests", "tests/"),
                         ("all samples", "")):
        for label in ("faithful", "trap", "unlabelled"):
            rows = [pair for pair in pairs if pair["source"].startswith(prefix) and pair["label"] == label]
            if not rows:
                continue
            reach = sum(pair["without_rule"] for pair in rows)
            lost = sum(pair in kept for pair in rows)
            print(f"  {name:18} {label:10} {len(rows):3} pairs; reach the review without the rule {reach:3}; "
                  f"kept by the rule {lost:3}; still reach it {reach - lost:3}")
    print(f"pairs the rule keeps: {len(kept)} ({dict(Counter(pair['label'] for pair in kept))}); "
          f"pairs that reach the review only with the rule: {len(gained)}")
    if args.list:
        for pair in kept:
            print(f"  - [{pair['source']}] ({pair['label']}) {pair['original']!r}\n      -> {pair['rewrite']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
