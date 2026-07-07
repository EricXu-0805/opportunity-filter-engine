#!/usr/bin/env python3
"""Commit-time corpus compaction — the single chokepoint the refresh workflow
runs on data/processed/opportunities.json right before it is pushed.

The corpus is one JSON file living against GitHub's hard 100 MB blob limit, so
every refresh has to hand back a compact file. Two transforms, both lossless
for every consumer:

1. Drop ``description_raw`` on any record where it is byte-identical to
   ``description_clean``. Every reader in the codebase resolves the description
   as ``description_clean or description_raw`` (or the reverse); when the two
   are equal, removing raw leaves the resolved text unchanged. The ~2% of
   records whose raw carries the uncapped long form (raw != clean) keep it.
2. Minify — strip JSON whitespace. The Python writers stay pretty for local-dev
   readability; this restores compactness whichever writer ran last.
"""
from __future__ import annotations

import json
import sys

DEFAULT_PATH = "data/processed/opportunities.json"


def prune_duplicate_raw(records):
    """Remove description_raw where it equals description_clean. Returns count removed."""
    removed = 0
    for record in records:
        raw = record.get("description_raw")
        if raw is not None and raw == record.get("description_clean"):
            del record["description_raw"]
            removed += 1
    return removed


def compact(path):
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    removed = prune_duplicate_raw(records)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, separators=(",", ":"), default=str)
    print(f"minify_corpus: pruned {removed}/{len(records)} duplicate description_raw fields")


if __name__ == "__main__":
    compact(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
