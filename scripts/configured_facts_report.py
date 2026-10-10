#!/usr/bin/env python3
"""Count the configured campus program values their page text bears out, and
list the ones it contradicts.

A campus program spec (campus_graph / ucb_campus config) carries pay, majors,
class years, an intl answer and a deadline note that a person typed in once.
`src.evidence.configured_fact` checks each against the page text its row
carries. The detail page shows a value as the page's where that text states
it, and as our inference where it does not. A value the text contradicts
stays our inference too, and someone should read the page and fix the
config: this lists those. A value another producer wrote on such a row (a
tagger's pay, the enricher's majors) is not the config's, and is left out.

Usage:
    python3 scripts/configured_facts_report.py          # counts + contradicted values
    python3 scripts/configured_facts_report.py --json   # every checked value

The corpus work file is gitignored; assemble it first:
    python scripts/shard_corpus.py assemble
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CORPUS = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

# The detail field each configured facet is served under.
_FIELD_OF = {
    "paid": "funding",
    "compensation": "funding",
    "international_students": "eligibility",
    "citizenship": "eligibility",
    "majors": "eligibility",
    "class_year": "eligibility",
    "application_window": "timing",
}


def _value(record: dict, path: str) -> object:
    value: object = record
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _is_set(facet: str, value: object) -> bool:
    """Whether the config gave ``facet`` a value (not left it unknown)."""
    if facet == "paid":
        return value in {"yes", "stipend", "no"}
    if facet == "international_students":
        return value in {"yes", "no"}
    if facet == "citizenship":
        return value is True or value is False
    if facet in {"majors", "class_year"}:
        return isinstance(value, list) and any(
            isinstance(v, str) and v.strip() and v.strip().lower() != "unknown" for v in value)
    return isinstance(value, str) and bool(value.strip())


def check_records(records: list[dict]) -> list[dict]:
    """One row per configured value: what the page text says of it, and how
    the detail page serves it (source, inferred, or unknown)."""
    from backend.lib.opportunity_detail import build_detail_fields
    from backend.routes.opportunities import _redact
    from src.evidence import (
        CONFIGURED_FACT_PATHS,
        CONFIGURED_PROGRAM_METHOD,
        configured_fact,
        inferred_method,
        is_configured_program,
        neutralize_unverified_faculty_claims,
        stamp_collector_templates,
    )

    rows = []
    for record in records:
        if not isinstance(record, dict) or not is_configured_program(record):
            continue
        # What the loader does to every served record.
        canonical = copy.deepcopy(record)
        neutralize_unverified_faculty_claims(canonical)
        stamp_collector_templates(canonical)
        fields = build_detail_fields(_redact(canonical), canonical)["fields"]
        for facet, path in CONFIGURED_FACT_PATHS.items():
            value = _value(canonical, path)
            if not _is_set(facet, value) or inferred_method(record, path) not in (None, CONFIGURED_PROGRAM_METHOD):
                continue
            fact = configured_fact(canonical, facet)
            field = fields[_FIELD_OF[facet]]
            served = ("source" if facet in field["explicit"]
                      else "inferred" if facet in field["inferred"] else "unknown")
            rows.append({
                "id": record.get("id"), "facet": facet, "value": value, "page_text": fact.state,
                "served": served, "quote": fact.quote, "source_url": fact.source_url,
                "observed_at": fact.observed_at,
            })
    return rows


def render(rows: list[dict]) -> str:
    counts = Counter((row["facet"], row["page_text"], row["served"]) for row in rows)
    lines = [
        f"{len({row['id'] for row in rows})} configured campus program rows, {len(rows)} configured values",
        "",
        f"{'facet':<24}{'values':>7}{'stated':>8}{'not stated':>12}{'contradicted':>14}"
        f"{'served source':>15}{'served inferred':>17}{'served unknown':>16}",
    ]
    for facet in _FIELD_OF:
        def n(page_text=None, served=None, facet=facet):
            return sum(c for (f, p, s), c in counts.items()
                       if f == facet and page_text in (None, p) and served in (None, s))
        lines.append(f"{facet:<24}{n():>7}{n('stated'):>8}{n('unstated'):>12}{n('contradicted'):>14}"
                     f"{n(served='source'):>15}{n(served='inferred'):>17}{n(served='unknown'):>16}")
    contradicted = [row for row in rows if row["page_text"] == "contradicted"]
    lines += ["", f"Contradicted by the page text ({len(contradicted)}; served as our inference, "
              "check the page and fix the config):"]
    for row in contradicted:
        lines.append(f"- {row['id']} {row['facet']} = {json.dumps(row['value'])}")
        lines.append(f"    page ({row['source_url']}, {row['observed_at']}): \"{row['quote']}\"")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--json", action="store_true", help="print every checked value as JSON")
    args = parser.parse_args(argv)
    records = json.loads(args.corpus.read_text(encoding="utf-8"))
    rows = check_records(records)
    print(json.dumps(rows, indent=2, ensure_ascii=False) if args.json else render(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
