#!/usr/bin/env python3
"""Count, against the real corpus, every place an unverified paper could leak.

`tests/test_publication_trust.py` proves each surface excludes an unverified
paper for a hand-built record. This asks the other question — the one a test
suite structurally cannot — of the actual data: *given the 137,776 records we
are about to ship, does any of them put a paper it may not claim in front of a
student?*

The two questions fail differently. A test fails when the gate is wrong. This
fails when a record is shaped in a way no fixture anticipated: a status literal
a half-finished migration left behind, a work list that survived a merge, a
keyword derivation whose papers were retracted underneath it. The remediation
is exactly the kind of change that produces those shapes, so the acceptance
number for it has to come from the corpus rather than from a fixture.

    python3 scripts/verify_publication_trust.py [--sample N] [--out report.json]

Exit code is 0 only when `downstream_unverified_leaks` is 0.

WHAT COUNTS AS A LEAK CANDIDATE

Every faculty record holding `metadata.recent_works` whose attribution is not
`verified_author_id`. That is deliberately wider than the remediation
population: it includes the ~14,710 legacy `name_match` records that were never
part of it, because "no serving path may cite an unverified paper" is a claim
about all of them, and a leak does not care which effort produced the record.

WHICH SURFACES ARE SCANNED EXHAUSTIVELY AND WHICH ARE SAMPLED

The dict-level projections are cheap, so every candidate goes through all of
them. Three paths are not cheap — the rule ranker fits against the whole corpus
generation, the rerank candidate builder and the cold-email brief each build
real prompt text — so those run over a bounded sample. The sample size is
reported next to the finding rather than hidden, because a sampled zero and an
exhaustive zero are different evidence and the report should not pretend
otherwise.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.publication_remediation import (  # noqa: E402
    LEDGER_PATH,
    Ledger,
    population_summary,
)
from src.publication_trust import (  # noqa: E402
    attribution_status,
    is_pending_remediation,
    verified_recent_works,
    works_are_verified,
)

SHARDS_DIR = PROJECT_ROOT / "data" / "processed" / "shards"
TRACKING_PATH = PROJECT_ROOT / "data" / "processed" / "professor_tracking.json"
CACHE_TS = PROJECT_ROOT / "frontend" / "src" / "lib" / "match-cache.ts"

# Metadata paths that must never reach a browser for an unverified record.
_FORBIDDEN_METADATA = (
    "recent_works",
    "publication_attribution_status",
    "publication_author_id",
    "publication_remediation",
    "works_gate",
)


def _titles(record: dict) -> list[str]:
    return [
        str(w.get("title", ""))
        for w in ((record.get("metadata") or {}).get("recent_works") or [])
        if w.get("title")
    ]


# A title only counts as evidence of a leaked CITATION when it is specific
# enough that finding it implies the paper rather than the subject.
#
# This is not a tuned threshold. OpenAlex indexes book and chapter records
# whose display_name is a bare field name — 'Art', 'Gender', 'Statistics',
# 'Anthropology' — and those land in recent_works like anything else. A
# professor's own keywords and description legitimately contain the word
# 'Anthropology' because that is their department, so a naive substring test
# reports sixteen "leaks" that are records describing themselves. Measured on
# this corpus: every such match was 1-3 words and ≤26 characters, while a real
# paper title ("SearchAuditor: Auditing and Attributing Failures in
# Long-Horizon Search Agents") is 78. The two populations do not overlap.
#
# Titles below the bar are counted and reported as `generic_titles_ignored`
# rather than silently dropped — a check that quietly stops looking at things
# is the failure mode this whole script exists to avoid.
_IDENTIFYING_CHARS = 40
_IDENTIFYING_WORDS = 5


def _is_identifying(title: str) -> bool:
    return len(title) >= _IDENTIFYING_CHARS or len(title.split()) >= _IDENTIFYING_WORDS


def _identifying_titles(record: dict) -> list[str]:
    return [t for t in _titles(record) if _is_identifying(t)]


def _load_records() -> list[dict]:
    out: list[dict] = []
    for path in sorted(SHARDS_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            out.extend(json.load(fh))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=300,
                    help="records to push through the expensive paths")
    ap.add_argument("--out")
    ap.add_argument("--seed", type=int, default=20260901)
    args = ap.parse_args(argv)

    records = _load_records()
    faculty = [r for r in records if r.get("source_type") == "faculty_research"]
    candidates = [
        r for r in faculty
        if (r.get("metadata") or {}).get("recent_works") and not works_are_verified(r)
    ]
    trusted = [r for r in faculty if works_are_verified(r)]

    findings: list[dict] = []
    surfaces: dict[str, dict] = {}

    def record_surface(name: str, scanned: int, leaks: list[str], exhaustive: bool) -> None:
        surfaces[name] = {
            "scanned": scanned,
            "leaks": len(leaks),
            "exhaustive": exhaustive,
            "examples": leaks[:3],
        }
        for rid in leaks:
            findings.append({"surface": name, "record_id": rid})

    # ---- 1. the trusted professor publication record -----------------------
    leaks = [r.get("id") for r in candidates if verified_recent_works(r)]
    record_surface("professor_trusted_publications", len(candidates), leaks, True)

    # ---- 2. the public professor API (real projection) ----------------------
    from backend.routes.opportunities import _redact

    leaks = []
    for r in candidates:
        md = (_redact(r).get("metadata") or {})
        if any(k in md for k in _FORBIDDEN_METADATA):
            leaks.append(r.get("id"))
    record_surface("professor_api_payload", len(candidates), leaks, True)

    # ---- 3. the match card (what the results page renders) ------------------
    from backend.routes.matches import _match_card

    leaks = []
    for r in candidates:
        card = _match_card(r)
        if "recent_works" in card or "publication_attribution_status" in card:
            leaks.append(r.get("id"))
    record_surface("match_card", len(candidates), leaks, True)

    # ---- 4. Ask AI prompt context + cold-email works block ------------------
    # One function serves both: opportunities.chat builds its context from it
    # and cold_email's brief formats the same string.
    from backend.routes.cold_email import _format_recent_works

    leaks = [r.get("id") for r in candidates if _format_recent_works(r).strip()]
    record_surface("ask_ai_and_cold_email_works_block", len(candidates), leaks, True)

    # ---- 5. publication-derived keywords whose papers were retracted --------
    # The sibling derivation: keywords stamped derived:openalex_topics rest on
    # the same author resolution the papers did. A record whose relationship
    # the remediation destroyed must not still be described by them.
    from src.evidence import inferred_method

    leaks = []
    for r in faculty:
        block = (r.get("metadata") or {}).get("publication_remediation") or {}
        destroyed = block.get("disposition") in ("removed", "unknown", "ambiguous",
                                                 "needs_review")
        if destroyed and inferred_method(r, "keywords") == "derived:openalex_topics":
            leaks.append(r.get("id"))
    record_surface("publication_derived_keywords", len(faculty), leaks, True)

    # ---- 6. embeddings / search documents -----------------------------------
    # Built from title + lab + keywords + description (embeddings.py). Works
    # never enter by construction; this asserts the construction, because the
    # index is fit over the whole corpus and one leaked title would be
    # searchable for every student.
    leaks = []
    generic_ignored = 0
    for r in candidates:
        lab = r.get("lab_or_program", "")
        keywords = ", ".join(r.get("keywords") or [])
        desc = (r.get("description_raw") or r.get("description_clean") or "")
        doc = f"{r.get('title', '')}. {lab}. {keywords}. {desc[:300]}"
        if any(t in doc for t in _identifying_titles(r)):
            leaks.append(r.get("id"))
        generic_ignored += sum(
            1 for t in _titles(r) if not _is_identifying(t) and t in doc
        )
    record_surface("embedding_search_document", len(candidates), leaks, True)
    surfaces["embedding_search_document"]["generic_titles_ignored"] = generic_ignored

    # The check above must still be able to fail. A bar set where nothing can
    # cross it is not a check, and this one was set after seeing the data — so
    # prove a real citation in a real document is caught before trusting the
    # zero it reports.
    probe_title = ("SearchAuditor: Auditing and Attributing Failures in "
                   "Long-Horizon Search Agents")
    probe_doc = f"Research with Prof. X. Lab. imaging. {probe_title} appears here."
    if not (_is_identifying(probe_title) and probe_title in probe_doc):
        record_surface("embedding_search_document_selftest", 1,
                       ["the leak detector cannot detect a known leak"], True)
    else:
        record_surface("embedding_search_document_selftest", 1, [], True)

    # ---- 7. cached professor summaries --------------------------------------
    # professor_tracking.json is the durable per-professor summary artifact.
    tracking_leaks: list[str] = []
    scanned_tracking = 0
    if TRACKING_PATH.exists():
        blob = TRACKING_PATH.read_text(encoding="utf-8")
        scanned_tracking = 1
        if '"recent_works"' in blob:
            tracking_leaks.append("professor_tracking.json")
        else:
            # Belt and braces: a title could be inlined without the key. Same
            # specificity bar as the embedding scan, and for the same reason —
            # a summary that says "Anthropology" is describing a department.
            sample_titles = [t for r in candidates[:400] for t in _identifying_titles(r)][:400]
            for t in sample_titles:
                if t in blob:
                    tracking_leaks.append(f"professor_tracking.json::{t[:60]}")
                    break
    record_surface("cached_professor_summaries", scanned_tracking, tracking_leaks,
                   TRACKING_PATH.exists())

    # ---- 8. client match cache ----------------------------------------------
    # The cache stores recent_works copied off the card, so its version string
    # is the only thing that discards payloads written before the remediation.
    cache_leaks: list[str] = []
    if CACHE_TS.exists():
        src = CACHE_TS.read_text(encoding="utf-8")
        if "pubtrust-v3" not in src:
            cache_leaks.append("match-cache.ts::CACHE_VERSION not bumped")
    else:
        cache_leaks.append("match-cache.ts::missing")
    record_surface("client_match_cache", 1, cache_leaks, True)

    # ---- 9-11. the expensive paths, sampled ---------------------------------
    rng = random.Random(args.seed)
    sample = rng.sample(candidates, min(args.sample, len(candidates))) if candidates else []

    # Match score + rule-ranker reasons.
    from src.matcher.ranker import rank_opportunity

    profile = {
        "year": "sophomore", "major": "Electrical Engineering",
        "college": "Grainger College of Engineering",
        "research_interests_text": "machine learning, imaging, materials",
        "desired_fields": ["machine learning", "imaging"],
        "hard_skills": [], "coursework": [], "seeking_type": ["research"],
        "home_school": "uiuc", "can_cold_email": True, "international_student": False,
    }
    leaks = []
    for r in sample:
        res = rank_opportunity(profile, r)
        blob = json.dumps([res.reasons_fit, res.reasons_gap, res.next_steps])
        if any(t in blob for t in _identifying_titles(r)):
            leaks.append(r.get("id"))
    record_surface("match_score_and_rule_reasons", len(sample), leaks, False)

    # Rerank candidate text — the string the model actually reads.
    from backend.routes import matches as matches_mod

    leaks = []
    for r in sample:
        works = "; ".join(
            f"{w.get('title', '')} ({w.get('year', '')})"
            for w in matches_mod.verified_recent_works(r)[:2]
            if w.get("title")
        )
        if works.strip():
            leaks.append(r.get("id"))
    record_surface("match_reason_rerank_context", len(sample), leaks, False)

    # Cold-email brief.
    from src.recommender.cold_email import _common_parts

    student = {"name": "A Student", "year": "sophomore", "major": "ECE",
               "school": "UIUC", "hard_skills": []}
    leaks = []
    for r in sample:
        parts = _common_parts(student, r)
        blob = json.dumps(parts, ensure_ascii=False)
        if parts.get("recent_works") or any(t in blob for t in _identifying_titles(r)):
            leaks.append(r.get("id"))
    record_surface("cold_email_brief", len(sample), leaks, False)

    # Résumé: the tailor module reads no publication data at all. Asserted
    # against the source rather than a call, because the property worth keeping
    # is that it never starts.
    from backend.routes import tailor as tailor_mod

    src = Path(tailor_mod.__file__).read_text(encoding="utf-8")
    leaks = ["tailor.py reads publication data"] if (
        "recent_works" in src or "publication_attribution_status" in src
    ) else []
    record_surface("resume_tailoring", 1, leaks, True)

    # ---- the report ---------------------------------------------------------
    ledger = Ledger(LEDGER_PATH)
    ledger_report = ledger.report()
    corpus = population_summary(records)
    by_status: dict[str, int] = {}
    for r in candidates:
        by_status[str(attribution_status(r))] = by_status.get(str(attribution_status(r)), 0) + 1

    report = {
        "corpus": corpus,
        "leak_candidates": len(candidates),
        "leak_candidates_by_status": by_status,
        "trusted_records": len(trusted),
        "trusted_relationships": sum(len(verified_recent_works(r)) for r in trusted),
        "still_withdrawn": sum(1 for r in faculty if is_pending_remediation(r)),
        "surfaces": surfaces,
        "downstream_unverified_leaks": len(findings),
        "findings": findings[:50],
        "ledger": ledger_report,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
