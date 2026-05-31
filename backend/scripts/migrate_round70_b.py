"""R70-B one-time migration: clear corrupted contact_email values.

`pi_enricher.py` used to call `soup.get_text()` without a `separator`
argument, which collapsed adjacent HTML elements into a single token.
When the page had ``<strong>265-4317</strong><a>nslack@illinois.edu</a>``
without whitespace between them, the regex ``[a-zA-Z0-9_.+-]+@illinois\\.edu``
matched the *concatenated* string ``265-4317nslack@illinois.edu`` and
that garbage address was stored as the record's contact_email.

R70-B fixed the root cause (separator=" " + ``_is_likely_real_email``
validator in pi_enricher) so future enrichment runs are clean. This
migration cleans up the 9 records that were already polluted by the
buggy version. We reset their contact_email to an empty string (matching
the original seed value in ``data/manual_entries/seed_v1.json``), so
the cold-email flow will refuse to send to an obviously-empty address
rather than bouncing off a fake one.

Idempotent: re-running with --save is a no-op once cleaned.

Usage:
    python3 -m backend.scripts.migrate_round70_b --dry-run
    python3 -m backend.scripts.migrate_round70_b --save
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "opportunities.json"

# Mirrors the corruption-detection regexes in src.collectors.pi_enricher
# (``_PHONE_IN_LOCAL`` + ``_CAPS_MASHED_LOCAL``). Keep them in sync if you
# tighten one.
_PHONE_IN_LOCAL = re.compile(r"^[^@]*\d{3,4}-\d{3,4}")
_CAPS_MASHED_LOCAL = re.compile(r"^[A-Z][a-z]+[^A-Z_@]{12,}@")


def _is_corrupted(email: str | None) -> bool:
    if not isinstance(email, str) or "@" not in email:
        return False
    return bool(_PHONE_IN_LOCAL.match(email) or _CAPS_MASHED_LOCAL.match(email))


def migrate(data: list[dict]) -> int:
    """Reset corrupted contact_email values to empty string. Returns count."""
    cleared = 0
    for o in data:
        ce = o.get("contact_email")
        if _is_corrupted(ce):
            o["contact_email"] = ""
            cleared += 1
    return cleared


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

    cleared = migrate(data)
    print(f"R70-B migration: cleared {cleared} corrupted contact_email values")
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
