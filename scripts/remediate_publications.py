#!/usr/bin/env python3
"""Historical remediation of professor-paper attribution, end to end.

The publication-trust boundary asks "is this stamped verified". It cannot ask
"by a rule we still believe in", and for 6,255 professors the answer to the
second question is no: gate 1 approved a paper if its OpenAlex field sat
anywhere in the nine-field family the professor's *department* could plausibly
touch, which handed a UIUC MRI professor a search-agent paper and a
geochemistry paper while discarding his own imaging work. #846 replaced the
rule and could only bind future harvests.

This is the driver that closes the gap for the records already in the corpus.

    # 1. What is affected? Mutates nothing.
    python3 scripts/remediate_publications.py audit

    # 2. Make the window safe. Withdraws trust corpus-wide; no network.
    python3 scripts/remediate_publications.py invalidate --save

    # 3. Buy the answers. Metered OpenAlex; resumable; stops on a dead budget.
    python3 scripts/remediate_publications.py harvest --schools uiuc,yale \
        --out /tmp/works.json --manifest /tmp/manifest.json

    # 4. Land them. Re-attributes, retracts, settles the ledger.
    python3 scripts/remediate_publications.py apply /tmp/works.json \
        --manifest /tmp/manifest.json --save

    # 5. Prove it.
    python3 scripts/remediate_publications.py report

WHY THE STEPS ARE SEPARATE, AND WHY 2 COMES BEFORE 3

Step 3 needs a third party, a budget and hours. If trust were withdrawn
professor-by-professor as each one's turn came, every professor whose turn had
not come would keep serving citations that no living rule approves, for the
whole window. Step 2 is one cheap local pass over the corpus that withdraws all
of it at once, before a single request is made — so the failure mode of a slow
or abandoned remediation is missing personalisation, never false attribution.

ORDER OF DURABILITY IN STEP 4

The corpus write and the ledger append are two files and cannot be one atomic
act, so the corpus is written FIRST and the ledger settles after. A crash in
between leaves a record carrying ``works_gate`` at the target version with no
terminal ledger entry — which the next run detects and *reconciles* (records
the completion) instead of re-applying. That is what makes the retry in §9 of
the remediation contract safe: attempt 1 dies after the commit, attempt 2 sees
the proof and does not mutate again.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.atomic_json import atomic_write_json  # noqa: E402
from src.publication_remediation import (  # noqa: E402
    HARVEST_SUCCEEDED,
    LEDGER_PATH,
    QUEUED,
    Ledger,
    apply_disposition,
    disposition_for,
    invalidate_population,
    pending_population,
    population_summary,
    remediation_population,
    unit_for,
    write_json_atomic,
)
from src.publication_trust import (  # noqa: E402
    CURRENT_WORKS_GATE,
    is_pending_remediation,
)

SHARDS_DIR = PROJECT_ROOT / "data" / "processed" / "shards"


# ---------------------------------------------------------------------------
# Corpus access — shards, not the work file
# ---------------------------------------------------------------------------
# The shards are what git stores and what CI reassembles; the work file is a
# gitignored local artifact that does not exist on a fresh checkout. Reading and
# writing the shards directly is also what keeps this field-scoped: the same
# reason src/normalizers/deactivate_past.py grew a --shards mode.

def load_shards(shards_dir: Path = SHARDS_DIR) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for path in sorted(shards_dir.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            out[path.stem] = json.load(fh)
    return out


def all_records(shards: dict[str, list[dict]]) -> list[dict]:
    return [r for records in shards.values() for r in records]


def save_shards(shards: dict[str, list[dict]], touched: set[str],
                shards_dir: Path = SHARDS_DIR) -> list[str]:
    """Rewrite only the shards this run actually changed, minified as committed."""
    written = []
    for slug in sorted(touched):
        atomic_write_json(shards_dir / f"{slug}.json", shards[slug],
                          indent=None, separators=(",", ":"))
        written.append(slug)
    return written


def _trust_fingerprint(record: dict) -> tuple:
    """Everything about a record that the remediation is allowed to change.

    Used to prove a run changed only what it claimed. Compares the trust state
    and the citation list, not the whole record, so an unrelated field written
    by another pass in the same process is not mistaken for an unaccounted
    remediation.
    """
    md = record.get("metadata") or {}
    works = md.get("recent_works") or []
    return (
        md.get("publication_attribution_status"),
        md.get("works_gate"),
        md.get("publication_author_id"),
        len(works),
        tuple(str(w.get("title", ""))[:80] for w in works),
        tuple(record.get("keywords") or []),
    )


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

def cmd_audit(args: argparse.Namespace) -> int:
    shards = load_shards()
    records = all_records(shards)
    summary = population_summary(records)
    population = remediation_population(records)
    pending = pending_population(records)

    by_school: dict[str, dict[str, int]] = {}
    for unit in population + pending:
        row = by_school.setdefault(
            unit["school"] or "?", {"professors": 0, "relationships": 0}
        )
        row["professors"] += 1
        row["relationships"] += unit["relationship_count"]

    ledger = Ledger(Path(args.ledger))
    report = {
        "works_gate": CURRENT_WORKS_GATE,
        "corpus_summary": summary,
        "affected_professor_count": len(population),
        "affected_relationship_count": sum(u["relationship_count"] for u in population),
        "already_withdrawn_professor_count": len(pending),
        "already_withdrawn_relationship_count": sum(u["relationship_count"] for u in pending),
        "by_school": dict(sorted(by_school.items())),
        "ledger": ledger.report(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.out:
        write_json_atomic(Path(args.out), report)
        print(f"\nwrote {args.out}", file=sys.stderr)
    if args.units_out:
        write_json_atomic(Path(args.units_out), population + pending)
        print(f"wrote {args.units_out} ({len(population) + len(pending)} units)",
              file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# invalidate
# ---------------------------------------------------------------------------

def cmd_invalidate(args: argparse.Namespace) -> int:
    shards = load_shards()
    ledger = Ledger(Path(args.ledger))

    touched: set[str] = set()
    queued = 0
    withdrawn_relationships = 0
    index = ledger.index()
    for slug, records in shards.items():
        population = remediation_population(records)
        if not population:
            continue
        # The ledger entry comes first and the mutation second, deliberately
        # the opposite way round from `apply`. QUEUED is not a claim of work
        # done — it records that this unit entered the population, with the
        # pre-state (how many citations it held, which gate stamped them) that
        # nothing can reconstruct once the withdrawal has happened.
        for unit in population:
            if not ledger.is_complete(unit["idempotency_key"], index):
                # The one event that carries the paper list. Title+year is the
                # only identity these relationships have, and after the
                # withdrawal-then-retraction there is nothing left on the
                # record to reconstruct it from — so "which three citations did
                # this professor lose" is answerable here or nowhere.
                ledger.append(unit, QUEUED,
                              paper_ids=unit["paper_ids"],
                              relationships_before=unit["relationship_count"],
                              old_attribution_status=unit["old_attribution_status"])
                queued += 1
        result = invalidate_population(records)
        withdrawn_relationships += result["relationships_withdrawn"]
        if result["professors_withdrawn"]:
            touched.add(slug)

    print(f"queued        : {queued} professor(s)")
    print(f"withdrawn     : {withdrawn_relationships} relationship(s)")
    print(f"shards touched: {len(touched)} ({', '.join(sorted(touched)) or '-'})")
    if not args.save:
        print("\n(dry run — pass --save to write the shards)")
        return 0
    written = save_shards(shards, touched)
    print(f"wrote {len(written)} shard file(s)")
    return 0


# ---------------------------------------------------------------------------
# harvest
# ---------------------------------------------------------------------------

def cmd_harvest(args: argparse.Namespace) -> int:
    # Imported here, not at module scope: the harvest is the only subcommand
    # that needs `requests` and a metered key, and `audit`/`invalidate`/`report`
    # must stay runnable on a machine that has neither.
    from src.collectors import openalex_enrich as oa

    shards = load_shards()
    records = all_records(shards)
    schools = args.schools.split(",") if args.schools else None
    targets = pending_population(records)
    if schools:
        targets = [u for u in targets if u["school"] in schools]
    if args.limit:
        targets = targets[: args.limit]
    print(f"pending units: {len(targets)}"
          f"{' in ' + args.schools if schools else ''}", file=sys.stderr)

    mapping, reasons = oa.harvest_works_by_roster(
        records, schools=schools, roster_dir=args.roster_dir, progress=True
    )

    # Which schools were REALLY asked. A school whose roster came back
    # incomplete, or whose batches died against an exhausted budget, was not —
    # and `apply` must not read its silence as "these professors have nothing
    # citable". This manifest is the difference between the two, and it is why
    # a harvest that fetched nothing cannot produce a completed remediation.
    asked = sorted({
        u["school"] for u in targets
        if u["person_key"] in mapping
    })
    manifest = {
        "works_gate": CURRENT_WORKS_GATE,
        "schools_requested": schools or sorted({u["school"] for u in targets}),
        "schools_answered": asked,
        "budget_exhausted": bool(oa._warned_429),
        "reasons": reasons,
        "mapping_entries": len(mapping),
    }
    atomic_write_json(Path(args.out), mapping)
    write_json_atomic(Path(args.manifest), manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"\nwrote {args.out} and {args.manifest}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def cmd_apply(args: argparse.Namespace) -> int:
    from src.collectors.openalex_enrich import apply_works

    with open(args.mapping, encoding="utf-8") as fh:
        mapping = json.load(fh)
    manifest = {}
    if args.manifest and Path(args.manifest).exists():
        with open(args.manifest, encoding="utf-8") as fh:
            manifest = json.load(fh)
    answered = set(manifest.get("schools_answered") or [])
    if not answered:
        print("refusing to apply: the manifest names no school that was actually "
              "answered, so every disposition would be a guess about a professor "
              "nobody asked about", file=sys.stderr)
        return 2

    shards = load_shards()
    ledger = Ledger(Path(args.ledger))
    index = ledger.index()

    # 1. Choose the units. Only schools the harvest really reached, only units
    #    without a logical result already, and reconcile anything whose
    #    mutation landed before its ledger entry did.
    claimed: list[tuple[str, dict, dict]] = []   # (shard, unit, record)
    reconciled = skipped_complete = 0
    for slug, records in shards.items():
        if slug not in answered:
            continue
        for record in records:
            if not is_pending_remediation(record):
                continue
            unit = unit_for(record)
            if ledger.is_complete(unit["idempotency_key"], index):
                skipped_complete += 1
                continue
            if ledger.reconcile(unit, record):
                reconciled += 1
                continue
            if not ledger.claim(unit):
                skipped_complete += 1
                continue
            unit["relationships_before"] = unit["relationship_count"]
            claimed.append((slug, unit, record))

    print(f"claimed {len(claimed)} unit(s); reconciled {reconciled}; "
          f"already complete {skipped_complete}", file=sys.stderr)
    if not claimed:
        return 0

    for _slug, unit, _record in claimed:
        ledger.append(unit, HARVEST_SUCCEEDED,
                      mapping_hit=unit["person_key"] in mapping)

    # 2. Re-attribute through the SUPPORTED path. apply_works owns the upgrade
    #    and retraction rules; re-implementing them here is how the driver and
    #    the pipeline would come to disagree about what a verified record is.
    #
    #    Handed the WHOLE corpus, not just the claimed records: its bare-URL
    #    fallback is gated on a URL being owned by exactly one faculty member,
    #    and counting that over a subset would call a shared directory URL
    #    unique and stamp one person's papers onto their colleagues.
    #
    #    The mapping is narrowed to the claimed keys instead. Every mutation
    #    has to have a ledger entry behind it, and a mapping entry for an
    #    unclaimed person is a mutation nobody is accounting for.
    corpus = all_records(shards)
    claimed_keys = {u["person_key"] for _s, u, _r in claimed}
    scoped = {k: v for k, v in mapping.items() if k in claimed_keys}
    before = {id(r): _trust_fingerprint(r) for r in corpus}
    applied = apply_works(corpus, scoped)
    print(f"apply_works touched {applied} record(s) "
          f"({len(scoped)}/{len(mapping)} mapping entries in scope)", file=sys.stderr)

    #    The check that the narrowing actually held. A record that changed
    #    without being claimed is an unaccounted mutation, and the honest
    #    response is to refuse the write rather than commit a corpus the ledger
    #    cannot explain.
    claimed_ids = {id(r) for _s, _u, r in claimed}
    stray = [
        r for r in corpus
        if id(r) not in claimed_ids and before[id(r)] != _trust_fingerprint(r)
    ]
    if stray:
        print(f"refusing to save: {len(stray)} record(s) changed that no ledger "
              f"entry claims (first: {stray[0].get('id')})", file=sys.stderr)
        for _slug, unit, _record in claimed:
            ledger.fail(unit, f"aborted: {len(stray)} unaccounted mutations in run")
        return 3

    # 3. Decide each unit's disposition from the record's POST state, and close
    #    the gaps apply_works does not own (a unit nobody could resolve, and the
    #    keyword derivation that shared the discredited author resolution).
    dispositions: dict[str, str] = {}
    touched_shards: set[str] = set()
    for slug, unit, record in claimed:
        entry = mapping.get(unit["person_key"])
        disposition = disposition_for(record, entry, harvested=True)
        outcome = apply_disposition(record, disposition)
        unit["_disposition"] = disposition
        unit["_outcome"] = outcome
        dispositions[disposition] = dispositions.get(disposition, 0) + 1
        touched_shards.add(slug)

    # 4. DURABILITY ORDER: the corpus goes to disk BEFORE the ledger says so.
    #    The reverse would let a crash leave a ledger claiming a completion the
    #    corpus never received, which is the one lie this whole mechanism is
    #    built to prevent. A crash here instead leaves records that
    #    `reconcile` closes on the next run.
    if not args.save:
        print("\n(dry run — no shard written, no ledger settlement)")
        print(json.dumps(dispositions, indent=2, sort_keys=True))
        return 0
    written = save_shards(shards, touched_shards)
    print(f"wrote {len(written)} shard file(s)", file=sys.stderr)

    # 5. Settle.
    #
    #    `relationships_removed` is measured before-minus-after rather than
    #    taken from apply_disposition's return. Both steps can retract: when
    #    the gate rejects every paper, apply_works' retraction has already
    #    cleared them by the time apply_disposition looks, so its own count is
    #    zero and the ledger would record "removed 0" for a record that lost
    #    three citations. The difference between the two counts is the only
    #    number that describes what actually happened to the professor.
    for _slug, unit, record in claimed:
        after = len((record.get("metadata") or {}).get("recent_works") or [])
        ledger.settle(
            unit, record, unit["_disposition"],
            relationships_before=unit["relationships_before"],
            relationships_removed=max(0, unit["relationships_before"] - after),
            keywords_invalidated=unit["_outcome"]["keywords_invalidated"] or None,
        )

    print(json.dumps(dispositions, indent=2, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def cmd_report(args: argparse.Namespace) -> int:
    shards = load_shards()
    records = all_records(shards)
    ledger = Ledger(Path(args.ledger))
    report = ledger.report()
    report["corpus_summary"] = population_summary(records)
    report["still_untrusted_professors"] = report["corpus_summary"]["pending_professors"]
    report["manual_review_queue_size"] = len(ledger.manual_review_queue())
    # The acceptance invariant, evaluated rather than asserted.
    report["invariants"] = {
        "no_superseded_gate_trust":
            report["corpus_summary"]["old_gate_professors"] == 0,
        "no_duplicate_logical_remediation":
            report["duplicate_logical_remediations"] == 0,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.out:
        write_json_atomic(Path(args.out), report)
    if args.queue_out:
        write_json_atomic(Path(args.queue_out), ledger.manual_review_queue())
    return 0 if all(report["invariants"].values()) else 1


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ledger", default=str(LEDGER_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("audit", help="report the population; mutates nothing")
    p.add_argument("--out")
    p.add_argument("--units-out")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("invalidate", help="withdraw trust corpus-wide (no network)")
    p.add_argument("--save", action="store_true")
    p.set_defaults(func=cmd_invalidate)

    p = sub.add_parser("harvest", help="re-harvest pending units through OpenAlex")
    p.add_argument("--schools")
    p.add_argument("--limit", type=int)
    p.add_argument("--roster-dir", default="data/openalex_rosters")
    p.add_argument("--out", default="/tmp/remediation_works.json")
    p.add_argument("--manifest", default="/tmp/remediation_manifest.json")
    p.set_defaults(func=cmd_harvest)

    p = sub.add_parser("apply", help="re-attribute, retract, settle the ledger")
    p.add_argument("mapping")
    p.add_argument("--manifest", default="/tmp/remediation_manifest.json")
    p.add_argument("--save", action="store_true")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("report", help="ledger + corpus proof")
    p.add_argument("--out")
    p.add_argument("--queue-out")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
