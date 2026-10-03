#!/usr/bin/env python3
"""Count the same-language trap rewrites that reach the model faithfulness review.

Acceptance criterion (5) of fix/tailor-review: same-language trap rewrites that
reach the review (pass the evidence-map contract and the claim locks) number at
most 14 on the corpus and at most 47 over all samples.

Run from the repository root:

    python scripts/trap_review_reach.py            # counts
    python scripts/trap_review_reach.py --list     # counts and every pair that reaches the review

A pair reaches the review when a model row for it passes
backend.lib.evidence_map.check_rewrite and then backend.lib.evidence_map.gate,
exactly as backend/routes/tailor.py (_checked_outcomes) and
backend/lib/target_resume_ai.py (parse_output) call them. The posting's
anchors are the pair's own original and rewrite, as in
tests/test_tailor_review.py's run(), so the model may cite any phrase of
either. The row is found by three declaration searches:

- suite: tests/test_tailor_review.py declared_row, the row every route test uses;
- exhaustive: every combination of verb_first, personal_first, tighten, one
  lead_with per possible leading word, and up to two relabels whose "from" is a
  span of the original and whose "to" a span of the rewrite (up to 8 words, or
  24 characters in Chinese, plus each whole line), each with every term the
  contract could accept;
- declared: for tests/fixtures/evidence_map_cases.json, the map the fixture
  declares, with its own anchors.

The claim locks read the rewrite as written, so a pair the locks refuse cannot
reach the review under any row; the searches only decide whether some row
passes the contract. A pair counts as reaching the review when any search
finds a row that does. Deterministic; stdlib plus repository imports.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import warnings
from collections import Counter
from itertools import combinations, product
from pathlib import Path

warnings.simplefilter("ignore")
sys.path.insert(0, os.getcwd())

from backend.lib import evidence_map as em  # noqa: E402

FIXTURES = Path("tests/fixtures")
CORPUS = json.loads((FIXTURES / "resume_rewrite_faithfulness_corpus.json").read_text())
CASES = json.loads((FIXTURES / "evidence_map_cases.json").read_text())["cases"]

# ---------------------------------------------------------------- sample sets


def corpus_traps() -> list[dict]:
    """The corpus's unfaithful pairs in the language of their original (the 'language' label excluded)."""
    out = []
    for index, case in enumerate(CORPUS["unfaithful"], start=1):
        if em.language(case["original"]) == em.language(case["rewrite"]):
            out.append({"original": case["original"], "rewrite": case["rewrite"], "support": (),
                        "source": f"corpus U{index}", "kind": case["kind"], "label": case.get("caught", "hard")})
    return out


# evidence_map_cases.json: groups whose maps are faithful moves or shapes, and the two churn maps that
# say nothing new. Every other map the fixture refuses is a trap, and so is the one 'ZH relabel drops 近'
# that it expects to reach the review.
_FAITHFUL_GROUPS = {"ideal", "cosmetic", "shape", "same"}
_FAITHFUL_CHURN = {"cap_tr4 ', reaching' declared tighten", "cap_tr4 'Served as' declared verb_first"}
_PENDING_TRAPS = {"ZH relabel drops 近"}


def _faithful_texts() -> set[tuple[str, str]]:
    """Pairs some fixture holds as faithful: a map that refuses one of them refuses a declaration, not the text."""
    texts = {(case["original"], case["rewrite"]) for case in CORPUS["faithful"]}
    texts |= {(case["original"], case["rewrite"]) for case in CASES
              if case["group"] in _FAITHFUL_GROUPS or case["label"] in _FAITHFUL_CHURN
              or case["expected"][0] == "pending" and case["label"] not in _PENDING_TRAPS}
    return texts


def case_traps() -> list[dict]:
    out, faithful = [], _faithful_texts()
    for case in CASES:
        if case["group"] in _FAITHFUL_GROUPS or case["label"] in _FAITHFUL_CHURN:
            continue
        if (case["original"], case["rewrite"]) in faithful:
            continue
        if case["expected"][0] == "pending" and case["label"] not in _PENDING_TRAPS:
            continue
        if em.language(case["original"]) != em.language(case["rewrite"]):
            continue
        out.append({"original": case["original"], "rewrite": case["rewrite"], "support": (),
                    "source": f"evidence_map_cases '{case['label']}'", "kind": case["group"], "label": "case",
                    "case": case})
    return out


def _values(param, count: int) -> tuple:
    """A parametrize value as a tuple of ``count`` arguments (pytest.param carries its own)."""
    if hasattr(param, "values"):
        return tuple(param.values)
    return tuple(param) if count > 1 else (param,)


def _parametrized(module, qualname):
    """Every parameter combination of a test, or none when this tree does not have the test."""
    obj = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return []
    sets = []
    for mark in getattr(obj, "pytestmark", []):
        if mark.name != "parametrize":
            continue
        names = mark.args[0]
        names = [name.strip() for name in names.split(",")] if isinstance(names, str) else list(names)
        sets.append([dict(zip(names, _values(value, len(names)), strict=True)) for value in mark.args[1]])
    rows = [{}]
    for values in sets:  # stacked parametrize marks multiply
        rows = [{**row, **value} for row in rows for value in values]
    return rows


# (module, test, how its parameters give (original, rewrite, support) for each trap it holds).
# Only tests whose every selected parameter is a trap the test refuses: faithful twins are left out.
def _pair(row):
    return [(row["original"], row.get("proposed", row.get("rewrite")), ())]


def _when(key, value):
    return lambda row: _pair(row) if row[key] is value else []


def _support_pair(row):
    return [(row["original"], row["proposed"], (("b2", row["support"]),))]


def _multi(row):
    first, *support = row["originals"]
    return [(first, row["proposed"], tuple((f"b{i}", text) for i, text in enumerate(support, start=2)))]


TEST_TRAPS = [
    ("tests.test_tailor_review", "TestFindingsSplit.test_dropped_qualifiers_new_actions_and_padding_are_hard", _pair),
    ("tests.test_tailor_review", "TestFindingsSplit.test_moved_denied_or_changed_claims_are_hard", _pair),
    ("tests.test_tailor_review", "TestFindingsSplit.test_relevance_clause_appended_to_the_original_is_hard",
     lambda row: [("Cleaned 212 survey responses in R.", row["proposed"], ())]),
    ("tests.test_tailor_review", "TestFindingsSplit.test_chinese_relevance_clause_appended_to_the_original_is_hard",
     lambda row: [("清洗了212份问卷数据。", row["proposed"], ())]),
    ("tests.test_tailor_review",
     "TestLockChangesForEvidenceMappedRewrites.test_a_gerund_counts_as_the_action_only_in_its_own_position", _pair),
    ("tests.test_tailor_review", "TestLockChangesForEvidenceMappedRewrites."
     "test_the_unreviewed_gates_still_read_team_credit_wording_as_a_new_action", _pair),
    ("tests.test_tailor_review", "TestLockChangesForEvidenceMappedRewrites.test_research_is_a_setting", _pair),
    ("tests.test_tailor_review", "TestLockChangesForEvidenceMappedRewrites.test_a_proficiency_is_a_quality_claim",
     _pair),
    ("tests.test_tailor_review", "TestLockChangesForEvidenceMappedRewrites.test_intended_work_stated_as_done_is_hard",
     _pair),
    ("tests.test_tailor_review",
     "TestLockChangesForEvidenceMappedRewrites.test_unfinished_work_stated_as_finished_is_hard", _pair),
    ("tests.test_tailor_review",
     "TestLockChangesForEvidenceMappedRewrites.test_an_action_that_changes_its_doer_is_hard", _pair),
    ("tests.test_tailor_review",
     "TestLockChangesForEvidenceMappedRewrites.test_a_qualifier_moved_to_another_action_is_hard", _pair),
    ("tests.test_tailor_review", "TestFaithfulnessCorpus.test_dropped_shared_credit_is_hard", _pair),
    ("tests.test_tailor_review", "test_personal_first_keeps_the_students_part_a_clause_of_its_own",
     _when("kept", True)),
    ("tests.test_tailor_review", "test_a_rewrite_without_its_lines_chinese_is_kept_unreviewed",
     lambda row: [(row["pair"][0], row["pair"][1], ())]),
    ("tests.test_tailor_review", "test_another_persons_action_still_cannot_become_the_students", _pair),
    ("tests.test_tailor_review", "TestHardRejectsNeverReachTheReviewer.test_rejected_without_a_review_call", _pair),
    ("tests.test_evidence_map", "TestUnknownVerbs.test_an_unknown_lead_is_finished_only_by_its_own_ed_form",
     _when("upgraded", True)),
    ("tests.test_evidence_map", "TestOwnPastVerbs.test_a_verb_that_is_its_own_past_finishes_work_under_way",
     _when("upgraded", True)),
    ("tests.test_evidence_map", "TestSupport.test_a_fact_moved_between_confirmed_lines_is_rejected",
     lambda row: [("My team built a Python parser; I wrote parser tests.", row["text"],
                   (("b2", "I ran 12 parser test cases."),))]),
    ("tests.test_target_resume_ai", "test_bounded_claim_locks_reject_negation_role_and_publication_upgrades", _pair),
    ("tests.test_target_resume_b52", "test_a_support_line_in_another_language_lets_no_trap_through", _support_pair),
    ("tests.test_target_resume_b52", "test_confirming_source_relationship_never_authorizes_fact_transfer", _multi),
    ("tests.test_target_resume_b52", "test_routes_refuse_unrecognized_multi_source_metric_transfer", _multi),
    ("tests.test_resume_writing_quality", "test_roles_negation_and_publication_cannot_be_upgraded", _pair),
    ("tests.test_resume_writing_quality", "test_same_claim_rule_covers_full_target_receipts", _when("accepted", False)),
    ("tests.test_resume_writing_quality", "test_temporal_not_yet_remains_negative", _pair),
    ("tests.test_full_target_resume_attribution", "test_three_attribution_failures_are_refused_through_real_route",
     _pair),
    ("tests.test_full_target_resume_attribution", "test_other_selected_entries_cannot_authorize_this_units_claim",
     lambda row: [(row["first"], row["borrowed"], ())]),
]


def test_traps() -> list[dict]:
    out, seen, faithful = [], set(), _faithful_texts()
    for module, qualname, pick in TEST_TRAPS:
        for row in _parametrized(module, qualname):
            for original, rewrite, support in pick(row):
                key = (original, rewrite, support)
                if key in seen or em.language(original) != em.language(rewrite) or (original, rewrite) in faithful:
                    continue
                seen.add(key)
                out.append({"original": original, "rewrite": rewrite, "support": support,
                            "source": f"{module.split('.')[-1]}::{qualname.split('.')[-1]}", "kind": "test",
                            "label": "test"})
    return out


# ----------------------------------------------------------------- pipeline


def unit_for(sample) -> em.Unit:
    support = tuple(sample["support"])
    return em.Unit("b1", sample["original"], sample["original"], support=support, keyed=bool(support))


def pair_anchors(sample) -> dict[str, em.Anchor]:
    texts = dict.fromkeys([sample["original"], sample["rewrite"]])
    return {f"t{i}": em.Anchor(f"t{i}", {"field": "description", "requirement_index": None, "start": 0,
                                         "end": len(text), "quote": text})
            for i, text in enumerate(texts, start=1)}


def checked(unit, row, anchors) -> tuple[em.Outcome, em.Outcome | None]:
    """(contract outcome, gate outcome or None), as the routes run them."""
    outcome = em.check_rewrite(unit, row, anchors, output_language=em.language(unit.evidence))
    return outcome, (em.gate(outcome, unit) if outcome.status == "pending" else None)


def locks_pass(sample) -> tuple[bool, list[str]]:
    """The claim locks and the grounding check on the rewrite as written; no row can change them."""
    unit = unit_for(sample)
    gated = em.gate(em.Outcome("b1", "pending", text=sample["rewrite"]), unit)
    return gated.status == "pending", gated.findings


def _row(text, links, ops):
    return {"unit_id": "b1", "decision": "rewrite", "text": text, "links": links, "ops": ops, "keep_reason": None}


# ---------------------------------------------------------------- searches


def suite_row(sample):
    from tests.test_tailor_review import declared_row

    return declared_row("b1", sample["original"], sample["rewrite"], pair_anchors(sample))


_EN_WORD = re.compile(r"[^\s]+")


def _spans(text: str, *, words: int, chars: int) -> list[str]:
    """Contiguous spans: up to ``words`` words (punctuation trimmed at the edges) in a Latin line, up to
    ``chars`` characters in a Chinese one, plus the whole line with and without its final mark."""
    out = {text, text.rstrip("。.；;，,")}
    if em.language(text) == "zh" or len(em._CJK.findall(text)) * 2 > len(text):
        for start in range(len(text)):
            for end in range(start + 1, min(len(text), start + chars) + 1):
                out.add(text[start:end])
    else:
        found = list(_EN_WORD.finditer(text))
        for i in range(len(found)):
            for j in range(i, min(len(found), i + words)):
                piece = text[found[i].start():found[j].end()]
                out.update({piece, piece.strip(".,;:()\"“”'"), piece.rstrip(".,;:)")})
    return sorted(piece for piece in out if piece.strip())


def _lead_links(original):
    """One lead_with link per leading word the original could offer, quoting the original as the anchor t1."""
    links, firsts = [], set()
    for phrase in _spans(original, words=3, chars=6):
        toks = em.tokens(phrase)
        if not toks or toks[0] in firsts:
            continue
        link = {"id": "L1", "anchor": "t1", "term": phrase, "source": phrase, "relation": "same"}
        verified = em.verify_links([link], [(None, original)], {"t1": em.Anchor("t1", {
            "field": "description", "requirement_index": None, "start": 0, "end": len(original), "quote": original})})
        if verified and verified[0].relation == "same":
            firsts.add(toks[0])
            links.append(link)
    return links


def _base_rows(sample):
    text = sample["rewrite"]
    leads = _lead_links(sample["original"])
    for vf, pf, lead, tighten in product((0, 1), (0, 1), [None, *leads], (0, 1)):
        ops = ([{"op": "verb_first"}] if vf else []) + ([{"op": "personal_first"}] if pf else [])
        links = []
        if lead is not None:
            links, ops = [lead], ops + [{"op": "lead_with", "link": "L1"}]
        if not ops:
            continue
        yield _row(text, links, ops + ([{"op": "tighten"}] if tighten else [])), "base"


_SUBTERMS: dict[str, list[tuple[str, Counter]]] = {}


def _subterms(to: str) -> list[tuple[str, Counter]]:
    """Sub-spans of ``to`` a link could quote as its term, shortest first, with their tokens."""
    if to not in _SUBTERMS:
        pieces = sorted(_spans(to, words=6, chars=len(to)), key=lambda piece: (len(piece), piece))
        _SUBTERMS[to] = [(piece, Counter(em.tokens(piece))) for piece in pieces
                         if em.term_span(to, piece) is not None]
    return _SUBTERMS[to]


def _term(to: str, added: Counter, source: str) -> str | None:
    """The shortest term a relabel's link may quote: it holds every added word and shares one with ``source``."""
    for term, toks in _subterms(to):
        if not added - toks and em._shares_content(source, term):
            return term
    return None


def _relabels(sample, evidence: set[str]):
    """(link, op) for every single relabel whose own checks could pass."""
    original, text = sample["original"], sample["rewrite"]
    froms = [(piece, Counter(em.tokens(piece))) for piece in _spans(original, words=8, chars=24)
             if em.source_span(original, piece) is not None]
    tos = []
    for piece in _spans(text, words=8, chars=24):
        toks = Counter(em.tokens(piece))
        if any(token not in evidence for token in toks) and em.written_span(text, piece) is not None:
            tos.append((piece, toks, Counter({t: n for t, n in toks.items() if t in evidence})))
    out, swap = [], {}
    for (target, to_toks, to_evidence), (source, from_toks) in product(tos, froms):
        # Every evidence word of "to" must come from "from": a relabel adds only words the line lacks.
        if to_evidence - from_toks:
            continue
        added = to_toks - from_toks
        if not added:
            continue
        key = (source, target)
        if key not in swap:
            swap[key] = em._relabel_swap_refusal(source, target)
        if swap[key]:
            continue
        term = _term(target, added, source)
        if term is not None:
            link = {"id": "R", "anchor": "t2", "term": term, "source": source, "relation": "same"}
            out.append((link, {"op": "relabel", "link": "R", "from": source, "to": target}))
    return out


def _relabel_rows(sample, unit):
    """Rows with one or two relabels. A row is tried with verb_first or personal_first beside the
    relabels only when the relabels alone leave a word dropped, which only those moves can allow."""
    evidence = {token for _, source in unit.sources for token in em.tokens(source)}
    if not any(token not in evidence for token in em.tokens(sample["rewrite"])):
        return
    anchors, language = pair_anchors(sample), em.language(unit.evidence)
    extras = [[{"op": "verb_first"}], [{"op": "personal_first"}], [{"op": "verb_first"}, {"op": "personal_first"}]]

    def tried(links, ops):
        row = _row(sample["rewrite"], links, [*ops, {"op": "tighten"}])
        outcome = em.check_rewrite(unit, row, anchors, output_language=language)
        rows = [row] if outcome.status == "pending" else []
        if outcome.detail and (outcome.detail.startswith("dropped:") or outcome.detail == "personal_marker_dropped"):
            rows += [_row(sample["rewrite"], links, [*ops, *extra, {"op": "tighten"}]) for extra in extras]
        return outcome, rows

    usable = []
    for link, op in _relabels(sample, evidence):
        outcome, rows = tried([{**link, "id": "L1"}], [{**op, "link": "L1"}])
        yield from ((row, "relabel") for row in rows)
        if outcome.detail and outcome.detail.startswith(("added:", "dropped:")):
            usable.append((link, op))
    # Two relabels help only when neither alone carries every word the rewrite adds. Of the relabels
    # that add the same words, the eight shortest are paired.
    new = {token for token in em.tokens(sample["rewrite"]) if token not in evidence}
    groups: dict[frozenset, list] = {}
    for link, op in sorted(usable, key=lambda item: (len(item[1]["from"]) + len(item[1]["to"]), item[1]["from"],
                                                      item[1]["to"])):
        groups.setdefault(frozenset(set(em.tokens(op["to"])) & new), []).append((link, op))
    usable = [item for group in groups.values() for item in group[:8]]
    adds = [set(em.tokens(op["to"])) & new for _, op in usable]
    for (i, (l1, o1)), (j, (l2, o2)) in combinations(enumerate(usable), 2):
        if o1["from"] == o2["from"] or o1["to"] == o2["to"]:
            continue
        if adds[i] >= new or adds[j] >= new or not (adds[i] | adds[j]) >= new:
            continue
        _, rows = tried([{**l1, "id": "L1"}, {**l2, "id": "L2"}], [{**o1, "link": "L1"}, {**o2, "link": "L2"}])
        yield from ((row, "relabel x2") for row in rows)


def exhaustive(sample, *, stop_at_contract: bool):
    """(row that passes the contract, row that also passes the gate) from the exhaustive search."""
    unit, anchors = unit_for(sample), pair_anchors(sample)
    passed = None
    for generator in (_base_rows(sample), _relabel_rows(sample, unit)):
        for row, _ in generator:
            outcome, gated = checked(unit, row, anchors)
            if outcome.status != "pending":
                continue
            passed = passed or row
            if gated.status == "pending":
                return passed, row
            if stop_at_contract:
                return passed, None
    return passed, None


def declared(sample):
    case = sample["case"]
    anchors = {f"t{i}": em.Anchor(f"t{i}", {"field": "description", "requirement_index": None, "start": 0,
                                            "end": len(text), "quote": text})
               for i, text in enumerate(case["anchors"], start=1)}
    row = _row(case["rewrite"], case["links"], case["ops"])
    return checked(unit_for(sample), row, anchors)


# ------------------------------------------------------------------- report


def measure(sample) -> dict:
    lock_ok, findings = locks_pass(sample)
    unit, anchors = unit_for(sample), pair_anchors(sample)
    suite_outcome, suite_gated = checked(unit, suite_row(sample), anchors)
    contract_row, reach_row = exhaustive(sample, stop_at_contract=not lock_ok)
    result = {
        "locks_pass": lock_ok, "findings": findings,
        "suite_contract": suite_outcome.status == "pending",
        "suite_reach": bool(suite_gated and suite_gated.status == "pending"),
        "suite_detail": suite_outcome.detail,
        "exhaustive_contract": contract_row is not None, "exhaustive_reach": reach_row is not None,
        "reach_row": reach_row,
    }
    if "case" in sample:
        outcome, gated = declared(sample)
        result["declared_contract"] = outcome.status == "pending"
        result["declared_reach"] = bool(gated and gated.status == "pending")
    result["contract"] = (result["suite_contract"] or result["exhaustive_contract"]
                          or result.get("declared_contract", False))
    result["reach"] = result["suite_reach"] or result["exhaustive_reach"] or result.get("declared_reach", False)
    return result


def _key(sample):
    return (sample["original"], sample["rewrite"], tuple(sample["support"]))


def main(argv: list[str]) -> None:
    listing = "--list" in argv
    dump = argv[argv.index("--json") + 1] if "--json" in argv else None
    if "--samples" in argv:  # another tree's sample sets, to measure the same pairs here
        sets = json.loads(Path(argv[argv.index("--samples") + 1]).read_text())
        for samples in sets.values():
            for sample in samples:
                sample["support"] = tuple(tuple(item) for item in sample["support"])
    else:
        sets = {"corpus": corpus_traps(), "evidence_map_cases": case_traps(), "tests": test_traps()}
    if "--write-samples" in argv:
        Path(argv[argv.index("--write-samples") + 1]).write_text(json.dumps(sets, ensure_ascii=False, indent=1))
    union, seen = [], set()
    for name in ("corpus", "evidence_map_cases", "tests"):
        for sample in sets[name]:
            if _key(sample) not in seen:
                seen.add(_key(sample))
                union.append(sample)
    results = {_key(sample): measure(sample) for sample in union}

    def summary(name, samples):
        rows = [results[_key(sample)] for sample in samples]
        return (f"{name}: {len(samples)} same-language traps; locks pass {sum(r['locks_pass'] for r in rows)}; "
                f"contract passes under the suite row {sum(r['suite_contract'] for r in rows)}, under any row "
                f"{sum(r['contract'] for r in rows)}; reach the review under the suite row "
                f"{sum(r['suite_reach'] for r in rows)}, under any row {sum(r['reach'] for r in rows)}")

    print(summary("corpus", sets["corpus"]))
    labels = Counter(sample["label"] for sample in sets["corpus"])
    reach_labels = Counter(sample["label"] for sample in sets["corpus"] if results[_key(sample)]["reach"])
    lock_labels = Counter(sample["label"] for sample in sets["corpus"] if results[_key(sample)]["locks_pass"])
    print(f"  corpus labels {dict(sorted(labels.items()))}; locks pass by label {dict(sorted(lock_labels.items()))}; "
          f"reach by label {dict(sorted(reach_labels.items()))}")
    print(summary("evidence_map_cases", sets["evidence_map_cases"]))
    # A case whose pair the corpus also holds was measured as the corpus pair; its declared map is run here.
    declared_reach = [sample for sample in sets["evidence_map_cases"]
                      if (lambda gated: bool(gated and gated.status == "pending"))(declared(sample)[1])]
    for sample in declared_reach:
        results[_key(sample)]["reach"] = results[_key(sample)]["declared_reach"] = True
    print(f"  under the fixture's own declared map: {len(declared_reach)} reach the review "
          f"({', '.join(sample['source'] for sample in declared_reach)})")
    print(summary("test parametrizations", sets["tests"]))
    print(summary("all samples (deduplicated union)", union))
    support = [s for s in union if s["support"]]
    print(f"  of which with confirmed support lines: {len(support)}, reaching the review "
          f"{sum(results[_key(s)]['reach'] for s in support)}")

    def counted(samples, key):
        return sum(bool(results[_key(s)][key] or results[_key(s)].get("declared_reach")) for s in samples)
    print(f"criterion (5), limits 14 on the corpus and 47 on all samples: under the suite row plus the fixture's "
          f"declared maps, corpus {counted(sets['corpus'], 'suite_reach')}, all samples {counted(union, 'suite_reach')}; "
          f"under any row the exhaustive search finds, corpus {counted(sets['corpus'], 'reach')}, all samples "
          f"{counted(union, 'reach')}")
    if dump:
        Path(dump).write_text(json.dumps([
            {"source": sample["source"], "original": sample["original"], "rewrite": sample["rewrite"],
             "support": list(sample["support"]), "label": sample["label"], "kind": sample["kind"],
             "row": results[_key(sample)]["reach_row"], "suite": results[_key(sample)]["suite_reach"]}
            for sample in union if results[_key(sample)]["reach"]], ensure_ascii=False, indent=1))
    if listing:
        print("\nPairs that reach the review (all samples):")
        for sample in union:
            r = results[_key(sample)]
            if not r["reach"]:
                continue
            how = [name for name in ("suite", "exhaustive", "declared") if r.get(f"{name}_reach")]
            ops = r["reach_row"]["ops"] if r["reach_row"] else None
            print(f"- [{sample['source']}] ({sample['kind']}; label {sample['label']}; found by {'+'.join(how)})")
            print(f"    original: {sample['original']}")
            print(f"    rewrite:  {sample['rewrite']}")
            if sample["support"]:
                print(f"    support:  {[text for _, text in sample['support']]}")
            if ops:
                print(f"    exhaustive row ops: {json.dumps(ops, ensure_ascii=False)}")
        print("\nCorpus pairs labelled 'review' that do not reach it:")
        for sample in sets["corpus"]:
            r = results[_key(sample)]
            if sample["label"] == "review" and not r["reach"]:
                print(f"- [{sample['source']}] {sample['kind']}: locks_pass={r['locks_pass']} "
                      f"suite_detail={r['suite_detail']}")
        print("\nCorpus pairs not labelled 'review' whose locks pass:")
        for sample in sets["corpus"]:
            r = results[_key(sample)]
            if sample["label"] != "review" and r["locks_pass"]:
                print(f"- [{sample['source']}] label {sample['label']} {sample['kind']}: reach={r['reach']} "
                      f"suite_detail={r['suite_detail']}")


if __name__ == "__main__":
    main(sys.argv[1:])
