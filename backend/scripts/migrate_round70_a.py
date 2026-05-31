"""R70-A one-time migration for data/processed/opportunities.json.

Three independent passes (each idempotent):

  1. Re-cap description_clean from description_raw at 1500 chars.
     Collectors previously hard-coded `[:500]` which truncated mid-sentence
     for 586 records (NSF REU hit hardest at 554/554). The full text is
     already stored in description_raw, so we recompute description_clean
     from it without re-scraping any source.

  2. Backfill description_clean + description_raw for schema-A
     "program_overview" records (URAP/URSA/DRP/Siebel/UIUC-Other).
     These 25 records use a `description` field instead, which the
     frontend doesn't read — leading to empty descriptions in the UI.
     We copy `description` into both description_clean and description_raw
     (preserving the original field for back-compat).

  3. Default is_rolling=True for records with no deadline AND no
     is_rolling already set (308 records: uiuc_sro 258, uiuc_our_rss 26,
     manual 24). These are aggregator/listing pages where rolling
     applications are the safe default.

Usage:
    python3 -m backend.scripts.migrate_round70_a --dry-run
    python3 -m backend.scripts.migrate_round70_a --save

Re-running with --save after the first run is a no-op (idempotent).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "opportunities.json"

DESCRIPTION_CAP = 1500
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_description(text: str, cap: int = DESCRIPTION_CAP) -> str:
    """Strip HTML tags + collapse whitespace + cap. Mirrors normalizer._clean_description."""
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()[:cap]


def pass1_recap_description(data: list[dict]) -> int:
    """Recompute description_clean = clean(description_raw)[:1500]. Returns count changed."""
    changed = 0
    for o in data:
        raw = o.get("description_raw")
        if not raw:
            continue
        new_clean = _clean_description(raw, cap=DESCRIPTION_CAP)
        if o.get("description_clean") != new_clean:
            o["description_clean"] = new_clean
            changed += 1
    return changed


def pass2_schema_a_backfill(data: list[dict]) -> int:
    """For schema-A records (have `description` but not `description_clean`),
    copy `description` into both description_clean + description_raw.
    Keeps the original `description` field for back-compat. Returns count changed.
    """
    changed = 0
    for o in data:
        if "description" not in o:
            continue
        if "description_clean" in o and "description_raw" in o:
            continue  # already migrated
        desc = o.get("description") or ""
        if "description_clean" not in o:
            o["description_clean"] = _clean_description(desc, cap=DESCRIPTION_CAP)
        if "description_raw" not in o:
            o["description_raw"] = desc
        changed += 1
    return changed


def pass3_rolling_default(data: list[dict]) -> int:
    """For records with no deadline AND no is_rolling (None/False from aggregator
    sources where this is the safe assumption), set is_rolling=True.

    Restricted to the three sources we audited: uiuc_sro, uiuc_our_rss, manual.
    Other sources are left alone so we don't accidentally mark genuinely
    deadline-less records (e.g. expired handshake postings) as rolling.

    Returns count changed.
    """
    eligible_sources = {"uiuc_sro", "uiuc_our_rss", "manual"}
    changed = 0
    for o in data:
        if o.get("source") not in eligible_sources:
            continue
        if o.get("deadline"):
            continue
        if o.get("is_rolling") is True:
            continue
        o["is_rolling"] = True
        changed += 1
    return changed


def migrate(data: list[dict]) -> dict[str, int]:
    return {
        "recap_description": pass1_recap_description(data),
        "schema_a_backfill": pass2_schema_a_backfill(data),
        "rolling_default": pass3_rolling_default(data),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DATA_FILE)
    parser.add_argument("--save", action="store_true", help="Write changes back to file")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without writing")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"ERROR: {args.path} not found", file=sys.stderr)
        return 1

    with args.path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    counts = migrate(data)
    print(f"R70-A migration counts: {counts}")
    print(f"  Total records: {len(data)}")

    if args.save and not args.dry_run:
        with args.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"Wrote {args.path}")
    elif args.dry_run:
        print("(dry-run, no file changes)")
    else:
        print("(no --save flag, no file changes; pass --save to persist)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
