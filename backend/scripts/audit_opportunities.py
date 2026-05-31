"""Read-only data quality audit for data/processed/opportunities.json.

Usage:
    python3 -m backend.scripts.audit_opportunities

Prints a quality report covering:
  * Field coverage (null / empty rates per field)
  * Schema variants (schema-A program_overview vs schema-B standard)
  * Description truncation (records hitting the cap mid-sentence)
  * Deadline / is_rolling consistency (records with neither)
  * paid='unknown' distribution by source
  * Duplicate detection (title+url exact match)
  * application_url missing records
  * Past-deadline records (should be deactivated)

Idempotent. Does not mutate the data file.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "opportunities.json"

# Current cap applied at collector level (after R70-A migration this is 1500)
DESCRIPTION_CAP = 1500


def _pct(num: int, denom: int) -> str:
    if denom == 0:
        return "  0.0%"
    return f"{100 * num / denom:5.1f}%"


def _schema_buckets(data: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into program_overview (schema-A) and standard (schema-B)."""
    schema_a = [o for o in data if "description" in o and "description_clean" not in o]
    schema_b = [o for o in data if "description_clean" in o]
    return schema_a, schema_b


def _parse_iso(d: str | None) -> date | None:
    if not d or not isinstance(d, str):
        return None
    try:
        if "T" in d:
            return datetime.fromisoformat(d.replace("Z", "+00:00")).date()
        return datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def audit(data: list[dict]) -> dict:
    """Return a structured report dict (also prints human summary)."""
    total = len(data)
    schema_a, schema_b = _schema_buckets(data)
    today = date.today()

    report: dict = {
        "total": total,
        "sources": dict(Counter(o.get("source") for o in data)),
        "schema_a_count": len(schema_a),
        "schema_b_count": len(schema_b),
    }

    # ---- Description truncation ----
    capped = [o for o in schema_b if (o.get("description_clean") or "") and len(o["description_clean"]) >= DESCRIPTION_CAP]
    recoverable = sum(1 for o in capped if len(o.get("description_raw") or "") > DESCRIPTION_CAP)
    report["description_capped_at_limit"] = len(capped)
    report["description_recoverable"] = recoverable

    # ---- Deadline / is_rolling ----
    no_deadline_no_rolling = [
        o
        for o in data
        if not o.get("deadline") and not o.get("is_rolling")
    ]
    report["no_deadline_no_rolling"] = len(no_deadline_no_rolling)
    report["no_deadline_no_rolling_by_source"] = dict(
        Counter(o.get("source") for o in no_deadline_no_rolling)
    )

    past_active = 0
    for o in data:
        dt = _parse_iso(o.get("deadline"))
        if dt and dt < today:
            if o.get("metadata", {}).get("is_active") is not False:
                past_active += 1
    report["past_deadline_still_active"] = past_active

    # ---- paid distribution ----
    paid_counts = Counter(o.get("paid") for o in data)
    report["paid_distribution"] = dict(paid_counts)
    paid_unknown_by_source = defaultdict(int)
    for o in data:
        if o.get("paid") == "unknown":
            paid_unknown_by_source[o.get("source")] += 1
    report["paid_unknown_by_source"] = dict(paid_unknown_by_source)

    # ---- Duplicates (title+url exact) ----
    pairs = Counter(
        (o.get("title", "").strip().lower(), o.get("url", "").strip())
        for o in data
        if o.get("title") and o.get("url")
    )
    dup_pairs = {p: c for p, c in pairs.items() if c > 1}
    report["exact_dup_title_url_pairs"] = len(dup_pairs)
    report["exact_dup_records"] = sum(dup_pairs.values())

    # ---- application_url missing ----
    missing_app_url = [
        o
        for o in data
        if not (o.get("application") or {}).get("application_url")
    ]
    report["missing_application_url"] = len(missing_app_url)
    report["missing_application_url_by_source"] = dict(
        Counter(o.get("source") for o in missing_app_url)
    )

    # ---- Empty descriptions ----
    empty_desc = sum(
        1
        for o in data
        if not (o.get("description_clean") or o.get("description_raw") or o.get("description") or "")
    )
    report["empty_description"] = empty_desc

    # ---- Print human-readable summary ----
    print("=" * 70)
    print(f"OPPORTUNITY DATA QUALITY AUDIT — {DATA_FILE.name}")
    print("=" * 70)
    print(f"Total records: {total}")
    print(f"Sources: {len(report['sources'])} — {dict(sorted(report['sources'].items(), key=lambda x: -x[1]))}")
    print()
    print(f"Schema variants:  schema-A (program_overview, has `description`) = {len(schema_a)}")
    print(f"                  schema-B (standard, has description_clean)     = {len(schema_b)}")
    print()
    print(f"Description capped at {DESCRIPTION_CAP} chars: {len(capped)} ({_pct(len(capped), len(schema_b))})")
    print(f"  - of which recoverable from description_raw: {recoverable}")
    print()
    print(f"Past-deadline still is_active != False: {past_active}  (target: 0)")
    print(f"Records with no deadline AND no is_rolling: {len(no_deadline_no_rolling)}  (target: 0)")
    if no_deadline_no_rolling:
        print(f"  - by source: {report['no_deadline_no_rolling_by_source']}")
    print()
    print(f"paid distribution: {report['paid_distribution']}")
    print("  paid='unknown' by source (top 5):")
    for src, n in sorted(paid_unknown_by_source.items(), key=lambda x: -x[1])[:5]:
        src_total = report["sources"].get(src, 0)
        print(f"    {src:25s} {n:4d}/{src_total:4d} ({_pct(n, src_total)})")
    print()
    print(f"Exact duplicate (title+url) records: {report['exact_dup_records']} ({len(dup_pairs)} pairs)")
    print()
    print(f"Missing application.application_url: {report['missing_application_url']}")
    if missing_app_url:
        print(f"  - by source: {report['missing_application_url_by_source']}")
    print()
    print(f"Empty description (no clean/raw/description): {empty_desc}")
    print("=" * 70)
    return report


def main() -> int:
    if not DATA_FILE.exists():
        print(f"ERROR: {DATA_FILE} not found", file=sys.stderr)
        return 1
    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    audit(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
