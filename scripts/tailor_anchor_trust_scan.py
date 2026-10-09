#!/usr/bin/env python3
"""Run every faculty record whose papers are unverified through Tailor's anchor builder.

Prints how many such records exist, how many anchors the builder cuts for them,
and how many put one of their identifying paper titles into an anchor while the
same title is absent from the record's own description (a real leak), plus the
source scan the publication trust verifier's resume_tailoring surface needs.
Run from the repository root: python3 scripts/tailor_anchor_trust_scan.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("vpt", ROOT / "scripts" / "verify_publication_trust.py")
vpt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vpt)

from backend.routes import tailor  # noqa: E402
from src.publication_trust import works_are_verified  # noqa: E402

records = vpt._load_records()
faculty = [r for r in records if r.get("source_type") == "faculty_research"]
candidates = [r for r in faculty if (r.get("metadata") or {}).get("recent_works") and not works_are_verified(r)]
trusted = [r for r in faculty if works_are_verified(r) and (r.get("metadata") or {}).get("recent_works")]

leaks, in_description = [], 0
for record in candidates:
    text = "\n".join(anchor.text for anchor in tailor._snapshot_anchors(record, record))
    description = record.get("description_clean") or record.get("description_raw") or ""
    hits = [t for t in vpt._identifying_titles(record) if t in text]
    if hits and all(t in description for t in hits):
        in_description += 1
    elif hits:
        leaks.append(record.get("id"))

trusted_with_titles = 0
for record in trusted:
    text = "\n".join(anchor.text for anchor in tailor._snapshot_anchors(record, record))
    if any(str(w.get("title") or "") in text for w in record["metadata"]["recent_works"] if w.get("title")):
        trusted_with_titles += 1

source = Path(tailor.__file__).read_text(encoding="utf-8")
print(json.dumps({
    "unverified_candidates": len(candidates),
    "candidates_with_title_in_anchor_not_in_description": len(leaks),
    "candidates_with_title_only_from_own_description": in_description,
    "leak_examples": leaks[:3],
    "verified_records_with_works": len(trusted),
    "verified_records_whose_title_reaches_an_anchor": trusted_with_titles,
    "source_recent_works": source.count("recent_works"),
    "source_verified_recent_works": source.count("verified_recent_works"),
    "source_unguarded_recent_works": len(re.findall(r"(?<!verified_)recent_works", source)),
    "source_publication_attribution_status": source.count("publication_attribution_status"),
}, indent=2))
