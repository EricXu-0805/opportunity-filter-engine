"""Same-language rewrites the default keep of criterion (3) keeps as written (round 4).

Criterion (3) of fix/tailor-review: a rewrite of a line language() reads as English is shown only
when the line carries positive English evidence, two different English function words of three
letters or more outside the phrases the rewrite renames, neither "via" nor a hyphen-joined word
(backend.lib.evidence_map._english_line, rounds 4 and 5); without it the line comes back as written
(``beyond_allowed_edit``, ``english_unproven``), a contract keep under the owner's reading (2b). This
script counts what that costs.

Each same-language pair of scripts/measure_rewrite_refusals.py (the corpus, the evidence-map cases
and the faithful pairs the tests parametrize) runs through the same rows that script tries
(route_outcomes), twice: with the rule, and with _english_line answering True (no evidence asked).
A pair reaches the review when some row reaches it on the Tailor routes and on full target. A pair
the rule keeps reaches it without the rule and not with it.

Run from the repository root:

    python scripts/english_evidence_keeps.py [--list]

Prints, by source and label, the pairs whose original language() reads as English that reach the
review without the rule, and how many of them the rule keeps; then how many of those originals also
hold a letter of another script (a CJK name, "4º"), which round 5 asks for the evidence too. --list
prints each kept pair. Deterministic; provider-free.

Round 6 adds a probe set that is not among the samples: tests/fixtures/code_switched_zh_probe.json,
faithful rewrites of lines that mix Chinese and English and that language() reads as English. Its
pairs run the same way, each with its own declared row, and are counted on a line of their own.
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

PROBE = ROOT / "tests" / "fixtures" / "code_switched_zh_probe.json"


def probe_pairs() -> list[dict]:
    import json

    return [{"source": f"probe:{pair['label']}", "label": "faithful", "original": pair["original"],
             "rewrite": pair["rewrite"], "rows": [{"links": pair["links"], "ops": pair["ops"], "anchors": pair["anchors"]}]}
            for pair in json.loads(PROBE.read_text())["pairs"]]


def reaches(pair: dict) -> bool:
    route = refusals.route_outcomes(pair["original"], pair["rewrite"], pair["rows"])
    return (any(item["tailor"][0] == "pending" for item in route)
            and any(item["full_target"][0] == "pending" for item in route))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--list", action="store_true", help="print every pair the rule keeps")
    args = parser.parse_args()
    pairs = [pair for pair in refusals.collect_pairs()
             if em.language(pair["original"]) == em.language(pair["rewrite"]) == "en"]
    probe = probe_pairs()
    rule = em._english_line
    for pair in pairs + probe:
        pair["with_rule"] = reaches(pair)
    em._english_line = lambda line, renamed: True
    try:
        for pair in pairs + probe:
            pair["without_rule"] = reaches(pair)
    finally:
        em._english_line = rule
    kept = [pair for pair in pairs if pair["without_rule"] and not pair["with_rule"]]
    gained = [pair for pair in pairs if pair["with_rule"] and not pair["without_rule"]]
    print(f"same-language pairs whose original language() reads as English: {len(pairs)}")
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
    other = [pair for pair in pairs if em._non_latin_frame(pair["original"])]
    print(f"of the pairs, originals that also hold a letter of another script: {len(other)}; "
          f"the rule keeps {sum(pair in kept for pair in other)} of them")
    english = [pair for pair in probe if em.language(pair["original"]) == em.language(pair["rewrite"]) == "en"]
    reach = [pair for pair in english if pair["without_rule"]]
    probe_kept = [pair for pair in reach if not pair["with_rule"]]
    print(f"code-switched Chinese probe ({PROBE.relative_to(ROOT)}): {len(probe)} faithful pairs, "
          f"{len(english)} read as English; reach the review without the rule {len(reach)}; "
          f"kept by the rule {len(probe_kept)}; still reach it {len(reach) - len(probe_kept)}")
    if args.list:
        for pair in kept + probe_kept:
            print(f"  - [{pair['source']}] ({pair['label']}) {pair['original']!r}\n      -> {pair['rewrite']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
