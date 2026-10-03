"""Faithful refusals and refusals new relative to main, for same-language résumé rewrites.

Acceptance criterion (2) of fix/tailor-review: 0 faithful rewrites are judged
fabricated, and same-language rewrites get no new rejections relative to main.

Run from the repository root of the branch, with a checkout of main beside it:

    git worktree add ../main-checkout origin/main
    python scripts/measure_rewrite_refusals.py --main-root ../main-checkout

Pairs (same language only: em.language(original) == em.language(rewrite), as
tests/test_tailor_review.py's SAME_LANGUAGE reads the corpus):
  * tests/fixtures/resume_rewrite_faithfulness_corpus.json, faithful and unfaithful;
  * tests/fixtures/evidence_map_cases.json, each with its own declared map;
  * faithful pairs the test files parametrize (FAITHFUL_TEST_SOURCES below).

Branch side, through the functions the routes call:
  * "locks": evidence_map.gate on the rewrite as written (no relabel), for a
    Tailor unit and a keyed full-target unit: the grounding step plus the
    claim locks. A finding here is a refusal as fabrication (rewrite_rejected).
  * "route": the contract and the locks as each route runs them, for every
    declared row tried (the evidence-map case's own map, and the row
    tests/test_tailor_review.declared_row builds with the original and the
    rewrite as anchors, the widest target any posting can give, and a lead_with
    on every 1-4 word phrase the two texts share):
    routes.tailor._checked_outcomes (/tailor, /tailor/renovate, /tailor/bullet)
    and lib.target_resume_ai.parse_output (full-target v6). The pair passes
    when some row comes out "pending", i.e. reaches the model review.
Main side, in a subprocess at --main-root: routes.tailor._validate_bullet_rewrite
(main's check on /tailor, /tailor/renovate and /tailor/bullet) and full-target
v6's validate_no_fabrication + supported_claim_upgrade_detected.

Prints counts and every listed pair; --json writes the per-pair rows.
Deterministic; stdlib plus repository imports.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from backend.lib import evidence_map as em  # noqa: E402
from backend.lib import target_resume_ai  # noqa: E402
from backend.routes import tailor  # noqa: E402

CORPUS = ROOT / "tests" / "fixtures" / "resume_rewrite_faithfulness_corpus.json"
CASES = ROOT / "tests" / "fixtures" / "evidence_map_cases.json"

# Faithful pairs the test files parametrize: (module, attribute path, filter on the argument dict).
FAITHFUL_TEST_SOURCES = [
    ("tests.test_tailor_review", "FAITHFUL", None),
    ("tests.test_tailor_review", "UNFLAGGED", None),
    ("tests.test_tailor_review", "VERB_FIRST", None),
    ("tests.test_tailor_review", "OWN_PART_FIRST", None),
    ("tests.test_tailor_review", "ROLE_LINES", None),
    ("tests.test_tailor_review", "TestFindingsSplit.test_a_word_the_original_already_uses_is_not_padding", None),
    ("tests.test_tailor_review", "TestLockChangesForEvidenceMappedRewrites."
     "test_result_first_course_aside_own_part_first_and_verb_first_go_to_the_review", None),
    ("tests.test_tailor_review", "TestLockChangesForEvidenceMappedRewrites."
     "test_status_kept_in_another_form_is_not_an_upgrade", None),
    ("tests.test_tailor_review", "TestLockChangesForEvidenceMappedRewrites."
     "test_reorders_that_keep_each_doer_and_qualifier_are_not_moves", None),
    ("tests.test_tailor_review", "test_personal_first_keeps_the_students_part_a_clause_of_its_own",
     lambda args: args["kept"] is False),
    ("tests.test_tailor_review", "test_a_participle_or_a_dash_after_a_role_noun_still_heads_the_line", None),
    ("tests.test_evidence_map", "TestUnknownVerbs.test_a_role_word_in_ing_keeps_verb_first_open", None),
    ("tests.test_full_target_resume_attribution", "GOOD", None),
    ("tests.test_email_experience_attribution", "test_reviewed_legacy_structures_preserve_full_object_tool_and_course",
     None),
    ("tests.test_resume_writing_quality", "test_local_evidence_and_truthful_reordering_still_work", None),
    ("tests.test_resume_writing_quality", "test_same_claim_rule_covers_full_target_receipts",
     lambda args: args["accepted"] is True),
]
# Faithful pairs a test spells out in its body rather than in a parametrize list.
FAITHFUL_TEST_INLINE = [
    ("tests/test_tailor_review.py::TestFaithfulnessCorpus::test_a_dropped_manner_adverb_goes_to_the_review",
     "Tested the code thoroughly.", "Tested the code."),
    ("tests/test_tailor_review.py::TestFindingsSplit::test_padding_the_original_already_states_is_not_new",
     "Cleaned 212 survey responses in R, applying the lab's exclusion rules.",
     "Cleaned the 212 survey responses in R, applying the lab's exclusion rules."),
    ("tests/test_email_experience_attribution.py::test_reviewed_sample_equivalence_can_omit_only_the_confirmed_tool",
     "Analyzed measurements with PyTorch across 88 samples.", "Analyzed 88 samples."),
    ("tests/test_email_experience_attribution.py::test_reviewed_sample_equivalence_can_omit_only_the_confirmed_tool",
     "I Analyzed measurements with PyTorch across 88 samples.", "I Analyzed 88 samples."),
]
# evidence_map_cases.json carries no faithful label: a case its fixture expects to reach the
# review ("pending") is faithful unless named here, plus the kept cases named here whose
# rewrite says nothing its original does not.
CASE_TRAPS_THAT_PASS = {"ZH relabel drops 近"}
CASE_FAITHFUL_KEPT = {
    "cap_tr4 ', reaching' declared tighten", "cap_tr4 drop I declared tighten", "cap_tr4 'Served as' declared verb_first",
    "tense only", "same-language line marked translate", "own part folded by dropping I",
    "mech x ramezani: personal first + lead with design", "CS trim with permission (drop 'validation split')",
}
CASE_TRAP_GROUPS = {"trap", "filter", "relabel_from", "relabel", "span", "marker", "status", "churn"}


def _params(module, path, keep):
    obj = module
    for part in path.split("."):
        obj = getattr(obj, part)
    if isinstance(obj, tuple):
        return [obj]
    if isinstance(obj, list):
        return [tuple(getattr(value, "values", value)) for value in obj]
    for mark in getattr(obj, "pytestmark", []):
        if mark.name != "parametrize":
            continue
        names = mark.args[0]
        names = [name.strip() for name in names.split(",")] if isinstance(names, str) else list(names)
        if "original" not in names:
            continue
        rows = []
        for value in mark.args[1]:
            values = tuple(getattr(value, "values", value))
            args = dict(zip(names, values, strict=True))
            if keep is None or keep(args):
                rows.append((args["original"], args.get("proposed", args.get("rewrite"))))
        return rows
    raise LookupError(path)


def collect_pairs():
    import importlib

    pairs = []
    corpus = json.loads(CORPUS.read_text())
    for side in ("faithful", "unfaithful"):
        for index, case in enumerate(corpus[side]):
            pairs.append({"source": f"corpus:{side}[{index}]", "label": "faithful" if side == "faithful" else "trap",
                          "kind": case["kind"], "caught": case.get("caught"), "original": case["original"],
                          "rewrite": case["rewrite"], "rows": []})
    for case in json.loads(CASES.read_text())["cases"]:
        if case["label"] in CASE_TRAPS_THAT_PASS:
            label = "trap"
        elif case["expected"][0] == "pending" or case["label"] in CASE_FAITHFUL_KEPT:
            label = "faithful"
        elif case["group"] in CASE_TRAP_GROUPS:
            label = "trap"
        else:
            label = "unlabelled"
        pairs.append({"source": f"evidence_map_cases:{case['label']}", "label": label, "kind": case["group"],
                      "caught": None, "original": case["original"], "rewrite": case["rewrite"],
                      "rows": [{"links": case["links"], "ops": case["ops"], "anchors": case["anchors"]}]})
    for module_name, path, keep in FAITHFUL_TEST_SOURCES:
        module = importlib.import_module(module_name)
        for original, rewrite in _params(module, path, keep):
            pairs.append({"source": f"{module_name.replace('.', '/')}.py::{path}", "label": "faithful", "kind": "test",
                          "caught": None, "original": original, "rewrite": rewrite, "rows": []})
    for source, original, rewrite in FAITHFUL_TEST_INLINE:
        pairs.append({"source": source, "label": "faithful", "kind": "test", "caught": None, "original": original,
                      "rewrite": rewrite, "rows": []})
    return pairs


def _anchor(ident, text):
    return em.Anchor(ident, {"field": "description", "requirement_index": None, "start": 0, "end": len(text),
                             "quote": text})


def lock_findings(original, rewrite, *, keyed):
    unit = em.Unit("b1", original, original, keyed=keyed)
    outcome = em.gate(em.Outcome("b1", "pending", text=rewrite), unit)
    return outcome.findings if outcome.status != "pending" else []


_WORDS = re.compile(r"[A-Za-z0-9]+(?:[+#.'-][A-Za-z0-9]+)*[+#]*|[一-鿿]+")


def _lead_with_candidates(original, rewrite):
    """lead_with rows a model could declare beyond declared_row's: every 1-4 word phrase of the
    original (a CJK run counts as one word) that the rewrite also holds, quoted from the original
    as its own anchor (t1), alone or with verb_first or personal_first."""
    words = _WORDS.findall(original)
    seen = []
    for size in (1, 2, 3, 4):
        for start in range(len(words) - size + 1):
            phrase = em.source_span(original, " ".join(words[start:start + size]))
            if phrase is None:
                continue
            text = original[phrase[0]:phrase[1]]
            if text in seen or em.source_span(rewrite, text) is None:
                continue
            seen.append(text)
    for text in seen:
        link = {"id": "L1", "anchor": "t1", "term": text, "source": text, "relation": "same"}
        for extra in ([], [{"op": "verb_first"}], [{"op": "personal_first"}]):
            yield [link], [{"op": "lead_with", "link": "L1"}, *extra]


def _first_passing(tries, original, rewrite):
    """Every case/declared_row try, plus the first n-gram try that reaches "pending", if any."""
    fixed = [item for item in tries if item[0] != "lead_with_ngram"]
    for item in tries:
        if item[0] != "lead_with_ngram":
            continue
        by_id = {anchor.id: anchor for anchor in item[3]}
        row = {"unit_id": "b1", "decision": "rewrite", "text": rewrite, "keep_reason": None, "links": item[1],
               "ops": item[2]}
        if em.check_rewrite(em.Unit("b1", original, original), row, by_id,
                            output_language=em.language(original)).status == "pending":
            return [*fixed, item]
    return fixed


def route_outcomes(original, rewrite, declared):
    """(tailor outcome, full-target outcome) for each declared row: (status, code, detail, findings)."""
    from tests.test_tailor_review import declared_row

    tries = []
    for item in declared:
        anchors = [_anchor(f"t{i}", text) for i, text in enumerate(item["anchors"], start=1) if text]
        tries.append(("case", item["links"], item["ops"], anchors))
    anchors = [_anchor(f"t{i}", text) for i, text in enumerate(dict.fromkeys([original, rewrite]), start=1)]
    row = declared_row("b1", original, rewrite, {anchor.id: anchor for anchor in anchors})
    tries.append(("declared_row", row["links"], row["ops"], anchors))
    tries += [("lead_with_ngram", links, ops, anchors) for links, ops in _lead_with_candidates(original, rewrite)]
    results = []
    for name, links, ops, anchors in _first_passing(tries, original, rewrite):
        by_id = {anchor.id: anchor for anchor in anchors}
        row = {"unit_id": "b1", "decision": "rewrite", "text": rewrite, "keep_reason": None, "links": links, "ops": ops}
        out = tailor._checked_outcomes([em.Unit("b1", original, original)], {"b1": row}, by_id)["b1"]
        unit = {"unit_id": "b1", "section_id": "s1", "block_id": "k1", "original": original, "before_text": original,
                "evidence": {"kind": "experience", "id": "entry", "revision": 1}}
        raw = json.dumps({"units": [{**row, "priority": "normal", "reason": "method_relevance"}]})
        receipts, pending = target_resume_ai.parse_output(raw, [unit], anchors, em.language(original))
        if pending:
            full = ("pending", None, None, [])
        else:
            receipt = receipts[0]
            full = ("kept", receipt.get("reason_code"), None, [])
        results.append({"row": name, "ops": [op.get("op") for op in ops],
                        "tailor": [out.status, out.code, out.detail, list(out.findings)], "full_target": list(full)})
    return results


MAIN_CODE = r"""
import json, logging, sys
sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)
from backend.routes import tailor
from backend.lib.grounding import LENIENT_PROSE_NUMERIC, validate_no_fabrication
from backend.lib.target_resume_ai_grounding import supported_claim_upgrade_detected
out = []
for original, rewrite in json.load(sys.stdin):
    passed, findings = tailor._validate_bullet_rewrite(rewrite[:600], original)
    grounded, _ = validate_no_fabrication(rewrite, original, policy=LENIENT_PROSE_NUMERIC)
    full = grounded and not supported_claim_upgrade_detected(rewrite, [original])
    out.append({"tailor": bool(passed), "findings": list(findings), "full_target": bool(full)})
json.dump(out, sys.stdout)
"""


def main_verdicts(main_root, pairs):
    unique = list(dict.fromkeys((pair["original"], pair["rewrite"]) for pair in pairs))
    env = {**os.environ, "PYTHONPATH": str(main_root)}
    done = subprocess.run([sys.executable, "-c", MAIN_CODE], input=json.dumps(unique), capture_output=True, text=True,
                          cwd=main_root, env=env, check=True)
    return dict(zip(unique, json.loads(done.stdout), strict=True))


STAGES = ("review", "cosmetic_only", "contract_keep", "locks", "locks_behind_contract")


def _stage(pair):
    """Where the branch stops a pair: it reaches the review on some tried row; the contract keeps it
    as cosmetic or beyond the allowed moves; the locks refuse it on a row the contract passes; or the
    locks would refuse it but the contract keeps it first on every tried row."""
    rejected = any(item["tailor"][1] == "rewrite_rejected" or item["full_target"][1] == "rewrite_rejected"
                   for item in pair["route"])
    if rejected:
        return "locks"
    if pair["branch_reviewed"] and pair["branch_reviewed_full_target"]:
        return "review"
    if pair["locks"] or pair["locks_full_target"]:
        return "locks_behind_contract"
    codes = {item["tailor"][1] for item in pair["route"]}
    return "cosmetic_only" if codes == {"cosmetic_only"} else "contract_keep"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--main-root", required=True, help="a checkout of origin/main")
    parser.add_argument("--json", help="write the per-pair rows here")
    args = parser.parse_args()
    pairs = [pair for pair in collect_pairs() if em.language(pair["original"]) == em.language(pair["rewrite"])]
    on_main = main_verdicts(Path(args.main_root).resolve(), pairs)
    for pair in pairs:
        original, rewrite = pair["original"], pair["rewrite"]
        pair["locks"] = lock_findings(original, rewrite, keyed=False)
        pair["locks_full_target"] = lock_findings(original, rewrite, keyed=True)
        pair["route"] = route_outcomes(original, rewrite, pair.pop("rows"))
        pair["branch_reviewed"] = any(item["tailor"][0] == "pending" for item in pair["route"])
        pair["branch_reviewed_full_target"] = any(item["full_target"][0] == "pending" for item in pair["route"])
        pair["main"] = on_main[(original, rewrite)]

    def show(title, rows, extra):
        print(f"\n{title}: {len(rows)}")
        for pair in rows:
            print(f"  - [{pair['source']}] {pair['original']!r}\n      -> {pair['rewrite']!r}\n      {extra(pair)}")

    faithful = [pair for pair in pairs if pair["label"] == "faithful"]
    traps = [pair for pair in pairs if pair["label"] == "trap"]
    print(f"same-language pairs: {len(pairs)} (faithful {len(faithful)}, trap {len(traps)}, "
          f"unlabelled {len(pairs) - len(faithful) - len(traps)})")
    for name, subset in (("corpus", "corpus:"), ("evidence_map_cases", "evidence_map_cases:"), ("tests", "tests/")):
        rows = [pair for pair in pairs if pair["source"].startswith(subset)]
        print(f"  {name}: {len(rows)} (faithful {sum(p['label'] == 'faithful' for p in rows)}, "
              f"trap {sum(p['label'] == 'trap' for p in rows)})")
    # (a) Faithful pairs judged fabricated: a lock finding, or a route row refused by the locks.
    judged = [pair for pair in faithful if pair["locks"] or pair["locks_full_target"]
              or any(item["tailor"][1] == "rewrite_rejected" or item["full_target"][1] == "rewrite_rejected"
                     for item in pair["route"])]
    show("(a) faithful pairs judged fabricated (lock finding or rewrite_rejected on any route)", judged,
         lambda p: f"locks={p['locks']} full_target_locks={p['locks_full_target']} "
                   f"route={[(i['row'], i['tailor'][1], i['tailor'][3]) for i in p['route']]}")
    shown_fabricated = [pair for pair in judged if any(item["tailor"][1] == "rewrite_rejected"
                                                       or item["full_target"][1] == "rewrite_rejected"
                                                       for item in pair["route"])]
    print(f"  of which corpus pairs: {sum(p['source'].startswith('corpus:') for p in judged)}; "
          f"refused as rewrite_rejected on a route: {len(shown_fabricated)}")
    # (b) Pairs main accepts on every route that the branch keeps before the review.
    main_ok = [pair for pair in pairs if pair["main"]["tailor"] and pair["main"]["full_target"]]
    print(f"\nmain accepts {len(main_ok)} of {len(pairs)} same-language pairs "
          f"(faithful {sum(p['label'] == 'faithful' for p in main_ok)}, trap {sum(p['label'] == 'trap' for p in main_ok)})")
    by_locks = [pair for pair in main_ok if pair["locks"] or pair["locks_full_target"]]
    by_contract = [pair for pair in main_ok if not (pair["locks"] or pair["locks_full_target"])
                   and not (pair["branch_reviewed"] and pair["branch_reviewed_full_target"])]
    for label in ("faithful", "trap", "unlabelled"):
        show(f"(b) {label}: main accepts, the branch's claim locks refuse",
             [pair for pair in by_locks if pair["label"] == label],
             lambda p: f"locks={p['locks'] or p['locks_full_target']}")
        show(f"(b) {label}: main accepts, no locks finding, but no tried row passes the branch's contract",
             [pair for pair in by_contract if pair["label"] == label],
             lambda p: "contract=" + str([(i["row"], i["ops"], i["tailor"][1], i["tailor"][2], i["full_target"][1])
                                         for i in p["route"]]))
    print("\nstage each pair stops at on the branch (rows: source / label / main's verdict):")
    for name, subset in (("corpus", "corpus:"), ("evidence_map_cases", "evidence_map_cases:"), ("tests", "tests/"),
                         ("all", "")):
        for label in ("faithful", "trap", "unlabelled"):
            rows = [pair for pair in pairs if pair["source"].startswith(subset) and pair["label"] == label]
            for verdict, keep in (("main accepts", True), ("main refuses", False)):
                chosen = [pair for pair in rows if bool(pair["main"]["tailor"] and pair["main"]["full_target"]) is keep]
                if chosen:
                    counts = Counter(_stage(pair) for pair in chosen)
                    print(f"  {name:18} {label:10} {verdict:12} {len(chosen):3}: "
                          + ", ".join(f"{stage} {counts[stage]}" for stage in STAGES if counts[stage]))
    main_refuses = [pair for pair in pairs if not (pair["main"]["tailor"] and pair["main"]["full_target"])]
    print(f"\nmain refuses {len(main_refuses)} same-language pairs "
          f"(faithful {sum(p['label'] == 'faithful' for p in main_refuses)}, "
          f"trap {sum(p['label'] == 'trap' for p in main_refuses)})")
    show("faithful pairs main refuses (not new on the branch)", [p for p in main_refuses if p["label"] == "faithful"],
         lambda p: f"main={p['main']} branch_locks={p['locks']} branch_reviewed={p['branch_reviewed']}")
    if args.json:
        Path(args.json).write_text(json.dumps(pairs, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
