"""Count the lines the rewrite pipeline could show without the faithfulness review, or in another script.

Criteria (1) and (3) of fix/tailor-review (round-1 review). Deterministic,
provider-free, stdlib plus repository imports. Run from the repository root:

    python scripts/count_unreviewed_lines.py

It reads tests/fixtures/evidence_map_cases.json (declared rows, as a model
returns them) and, for every case the contract and the claim locks pass
("pending": what goes to the review), reports:

  * alternatives: pending rewrites that also get a version "without the
    posting's terms" (evidence_map.without_terms). Since round 1 that text is
    only a candidate: the routes send it to the same review as a pair of its
    own and offer it only on its own accepted verdict
    (tests/test_rewrite_display_paths.py).
  * other_script: pending rewrites holding a letter that is neither ASCII nor
    a CJK ideograph and that their own line does not hold.

Then it runs the probe set below (one shape per round-1 finding, each
faithful-looking so a review could accept it) and reports, for each, whether
the contract and the locks still pass it ("pending") or keep it ("kept"), and
any version without the terms it would produce.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.lib import evidence_map as em  # noqa: E402

CASES = Path("tests/fixtures/evidence_map_cases.json")


def anchors_for(texts):
    return {f"t{i}": em.Anchor(f"t{i}", {"field": "description", "requirement_index": None, "start": 0,
                                         "end": len(text), "quote": text})
            for i, text in enumerate(texts, start=1) if text}


def new_letters(text: str, line: str) -> set[str]:
    """Letters of ``text`` outside ASCII and the CJK ideographs that ``line`` does not hold."""
    return {ch for ch in text if ch.isalpha() and not ch.isascii() and not em._CJK.match(ch)} - set(line)


def run(original, rewrite, links, ops, anchors):
    """(status after contract and locks, alternative or None)."""
    unit = em.Unit("u1", original, original)
    row = {"unit_id": "u1", "links": links, "decision": "rewrite", "ops": ops, "text": rewrite}
    outcome = em.check_rewrite(unit, row, anchors, output_language=em.language(original))
    if outcome.status == "pending":
        outcome = em.gate(outcome, unit)
    if outcome.status != "pending":
        return outcome.status, None
    return "pending", em.without_terms(outcome, unit, ops)


PROBES = [
    ("alternative, two relabels undone in list order",
     "Responsible for writing Python scripts for data cleaning and Python notebooks for plotting.",
     "Wrote Python code for data cleaning and Python code for plotting.",
     [{"id": "L1", "anchor": "t1", "term": "Python code", "source": "Python scripts", "relation": "same"},
      {"id": "L2", "anchor": "t1", "term": "Python code", "source": "Python notebooks", "relation": "same"}],
     [{"op": "relabel", "link": "L2", "from": "Python notebooks", "to": "Python code"},
      {"op": "relabel", "link": "L1", "from": "Python scripts", "to": "Python code"}, {"op": "verb_first"}],
     ["Experience writing Python code is required."]),
    ("cross-script relabel 脑电 -> brain",
     "负责 脑电 signal preprocessing, feature extraction, model training 和 classification",
     "负责 brain signal preprocessing, feature extraction, model training 和 classification",
     [{"id": "L1", "anchor": "t1", "term": "brain signal", "source": "脑电 signal", "relation": "same"}],
     [{"op": "relabel", "link": "L1", "from": "脑电 signal", "to": "brain signal"}],
     ["We study brain signal processing in children."]),
    ("function word 和 -> and",
     "负责 data cleaning, feature engineering, model training 和 deployment",
     "负责 model training, data cleaning, feature engineering and deployment",
     [{"id": "L1", "anchor": "t1", "term": "model training", "source": "model training", "relation": "same"}],
     [{"op": "lead_with", "link": "L1"}], ["Experience with model training is a plus."]),
    *[(f"appended {name}",
       "Research assistant in the Fluids Lab, analyzing Python simulation data for CS 225.",
       "Analyzed Python simulation data for CS 225 as a research assistant in the Fluids Lab." + tail,
       [], [{"op": "verb_first"}], ["We study fluid dynamics with simulations."])
      for name, tail in (("katakana", " (フルイド・ラボ)"), ("hangul", " (유체 연구실)"), ("cyrillic", " (лаборатория)"),
                         ("full-width Latin", " （ＦＬＵＩＤＳ　ＬＡＢ）"))],
    ("full-width tool name",
     "Research assistant in the Fluids Lab, analyzing Python simulation data for CS 225.",
     "Analyzed Python simulation data with ＰｙＴｏｒｃｈ for CS 225 as a research assistant in the Fluids Lab.",
     [], [{"op": "verb_first"}], ["We study fluid dynamics with simulations."]),
]


def main() -> None:
    cases = json.loads(CASES.read_text())["cases"]
    pending = alternatives = other_script = 0
    for case in cases:
        status, alternative = run(case["original"], case["rewrite"], case["links"], case["ops"],
                                  anchors_for(case["anchors"]))
        if status != "pending":
            continue
        pending += 1
        alternatives += alternative is not None
        other_script += bool(new_letters(case["rewrite"], case["original"]))
    print(f"evidence_map_cases.json: {len(cases)} cases, {pending} pass the contract and the locks")
    print(f"  with a version without the posting's terms (reviewed as its own pair): {alternatives}")
    print(f"  with letters in a script their line lacks: {other_script}")
    print("probes (contract + locks):")
    for label, original, rewrite, links, ops, anchors in PROBES:
        status, alternative = run(original, rewrite, links, ops, anchors_for(anchors))
        print(f"  {label}: {status}" + (f"; version without the terms: {alternative!r}" if alternative else
                                        "; no version without the terms" if status == "pending" else ""))


if __name__ == "__main__":
    main()
