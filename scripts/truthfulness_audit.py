#!/usr/bin/env python3
"""Manual truthfulness sample-verification framework (Phase-2 of the audit).

Phase 1 (docs/truthfulness_audit.md) audited the *code*: where each data
category's values come from and which ones are optimistic completions. This
script runs the complementary *data* check — a structured manual verification
pass in which representative samples per category are drawn from the corpus,
a human/AI reviewer compares each system value against the live source, and an
aggregate report gates "truthfulness approval" FAIL-CLOSED.

    sample   draw deterministic per-category samples (risk quotas + random)
             -> data/audits/samples/<category>.json  (reviewer fills verdicts)
    report   aggregate reviewed samples -> data/audits/truthfulness_report.json
             + GO / NO-GO decision (missing category or any pending => NO-GO)

The corpus work file (data/processed/opportunities.json) is gitignored; if it
is absent, assemble it first:  python scripts/shard_corpus.py assemble

Reviewer instructions and pass/fail criteria: docs/truthfulness_sample_plan.md
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CORPUS = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
DEFAULT_SAMPLES_DIR = PROJECT_ROOT / "data" / "audits" / "samples"
DEFAULT_REPORT = PROJECT_ROOT / "data" / "audits" / "truthfulness_report.json"

DEFAULT_SEED = 20260731
DEFAULT_PER_CATEGORY = 10
MIN_REVIEWED_FOR_COMPLETE = 8
TRUNCATE_AT = 300

CATEGORIES = (
    "school", "department", "professor", "position", "program",
    "deadline", "international", "email", "research_area", "publication",
)

FIELD_NAMES = {
    "school": "school",
    "department": "department",
    "professor": "pi_name",
    "position": "metadata.faculty_title",
    "program": "title+metadata.status",
    "deadline": "deadline/is_rolling",
    "international": "eligibility.international_friendly",
    "email": "contact_email",
    "research_area": "keywords",
    "publication": "metadata.recent_works",
}

REVIEW_RESULTS = (
    "verified_correct", "correctly_unknown", "incorrect_value",
    "unsupported_value", "source_mismatch", "entity_mismatch",
    "conflicting", "stale", "blocked", "pending",
)
# review_results that count as an actual finding (a wrong claim, not just an
# unreviewable page) — these are the ones a "critical" severity can block on.
FINDING_RESULTS = frozenset({
    "incorrect_value", "unsupported_value", "source_mismatch",
    "entity_mismatch", "conflicting",
})

ROW_FIELDS = (
    "sample_id", "entity_type", "entity_id", "field_name", "system_value",
    "verification_status", "source_url", "source_evidence",
    "manual_expected_value", "review_result", "error_type", "severity",
    "reviewer", "reviewed_at", "notes", "risk_case",
)

JOB_BOARD_SOURCES = ("simplify_internships", "handshake")
JOB_BOARD_SOURCE_TYPES = ("internship", "job")


# ---------------------------------------------------------------- helpers ---

def _md(record: dict) -> dict:
    return record.get("metadata") or {}


def _elig(record: dict) -> dict:
    return record.get("eligibility") or {}


def _org(record: dict) -> str:
    return (record.get("organization") or "").strip()


def _is_active(record: dict) -> bool:
    return _md(record).get("is_active") is not False


def _is_faculty(record: dict) -> bool:
    return record.get("source_type") == "faculty_research"


def _is_campus_program(record: dict) -> bool:
    """Campus program-ish record: not faculty, not a job board."""
    return (not _is_faculty(record)
            and record.get("source") not in JOB_BOARD_SOURCES
            and record.get("source_type") not in JOB_BOARD_SOURCE_TYPES)


def _truncate(value, limit: int = TRUNCATE_AT):
    """Clip long strings (recursively) so sample files stay reviewable."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 3] + "..."
    if isinstance(value, list):
        return [_truncate(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: _truncate(v, limit) for k, v in value.items()}
    return value


# ------------------------------------------ verification_status derivation ---

_EMAIL_INFERRED_PREFIXES = ("constructed", "inferred", "guessed", "pattern")
_EMAIL_VERIFIED_SOURCES = ("profile_page", "digitalmeasures_profile")


def _publication_status(record: dict) -> str:
    status = _md(record).get("publication_attribution_status")
    return "verified" if status == "verified_author_id" else "unverified"


def _email_status(record: dict) -> str:
    if not record.get("contact_email"):
        return "unknown"
    source = _md(record).get("email_source") or ""
    if source.startswith(_EMAIL_INFERRED_PREFIXES):
        return "inferred"
    if source in _EMAIL_VERIFIED_SOURCES:
        return "verified"
    return "unverified"


def _international_status(record: dict) -> str:
    value = _elig(record).get("international_friendly")
    return "unknown" if value in (None, "unknown") else "unverified"


def _deadline_status(record: dict) -> str:
    if record.get("deadline_is_estimate"):
        return "inferred"
    if record.get("is_rolling") and _is_faculty(record):
        return "policy_default"
    if record.get("deadline"):
        return "unverified"
    return "unknown"


def _position_status(record: dict) -> str:
    return "unverified" if (_md(record).get("faculty_title") or "").strip() else "unknown"


def _research_area_status(record: dict) -> str:
    return "unverified" if record.get("keywords") else "unknown"


_STATUS_RULES = {
    "school": lambda r: "unverified",
    "department": lambda r: "unverified",
    "professor": lambda r: "unverified",
    "program": lambda r: "unverified",
    "position": _position_status,
    "deadline": _deadline_status,
    "international": _international_status,
    "email": _email_status,
    "research_area": _research_area_status,
    "publication": _publication_status,
}


def derive_verification_status(category: str, record: dict) -> str:
    """What the SYSTEM claims about this value — not the reviewer's verdict.

    One of "verified" | "unverified" | "inferred" | "unknown" |
    "policy_default", derived from the record's own provenance stamps. The
    mapping mirrors the Phase-1 audit findings (docs/truthfulness_audit.md):

    - publication: "verified" only on the fail-closed
      ``metadata.publication_attribution_status == "verified_author_id"``
      equality gate (src/publication_trust.py); anything else — including the
      100 %-unstamped legacy corpus — is "unverified".
    - email: ``metadata.email_source`` is the only field-level stamp.
      constructed/inferred/guessed/pattern* -> "inferred" (synthesized
      address); profile_page / digitalmeasures_profile -> "verified" (read
      off the person's own page); any other/absent stamp with an email
      present -> "unverified" (legacy majority); no email -> "unknown".
    - international: legacy data cannot distinguish stated-on-page from
      llm_tagger-inferred (Phase-1 Q4 "not distinguishable") — so only the
      explicit "unknown" enum maps to "unknown"; every yes/no claim is
      "unverified". Surfacing which of those claims are actually supported
      is the point of this audit.
    - deadline: ``deadline_is_estimate`` -> "inferred" (e.g. nsf_reu
      fabricated estimates); the blanket ``is_rolling=True`` default on
      faculty records -> "policy_default" (a policy statement, not a scraped
      fact); an explicit date -> "unverified"; neither -> "unknown".
    - position: ``metadata.faculty_title`` is scraped-but-unverified when
      present ("Professor" may be the known default-fill), else "unknown".
    - research_area: keywords carry no per-keyword provenance (scraped /
      LLM / OpenAlex indistinguishable at rest) -> "unverified" when
      non-empty, "unknown" when empty.
    - school / department / professor / program: record-level provenance
      only (source_url attribution) -> always "unverified".
    """
    return _STATUS_RULES[category](record)


# ------------------------------------------------------------ risk context ---

_ORG_TOKEN_STOPWORDS = frozenset({
    "university", "college", "institute", "school", "state", "technology",
    "system", "campus", "main", "north", "south", "east", "west",
})
_UNIT_TYPE_RE = re.compile(r"\b(?:Institute|Center|Laboratory|School of)\b")
_NON_PROFESSOR_RANK_RE = re.compile(r"\b(?:Lecturer|Instructor|Director|Scientist|Fellow)\b")
_EMERITUS_VISITING_RE = re.compile(r"\b(?:Emeritus|Visiting)\b")
_TITLE_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_INITIALS_ONLY_RE = re.compile(r"[A-Z]\.?(?:[A-Z]\.?)?")
_GENERIC_LOCALPART_PREFIXES = ("info", "admin", "contact", "office", "dept")


def _org_tokens(org: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z]{4,}", org)
            if t.lower() not in _ORG_TOKEN_STOPWORDS}


def build_risk_context(records: list[dict]) -> dict:
    """Corpus-wide precomputations the risk selectors need (one pass)."""
    org_schools: dict[str, set] = {}
    pi_schools: dict[str, set] = {}
    dept_kw_counts: dict[tuple, int] = {}
    for r in records:
        org = _org(r)
        if org:
            org_schools.setdefault(org, set()).add(r.get("school"))
        pi = r.get("pi_name")
        if pi:
            pi_schools.setdefault(pi, set()).add(r.get("school"))
        kws = r.get("keywords") or []
        if kws:
            key = (r.get("school"), r.get("department"), tuple(kws))
            dept_kw_counts[key] = dept_kw_counts.get(key, 0) + 1

    multi_school_orgs = {org for org, schools in org_schools.items()
                         if len({s for s in schools if s}) >= 2}
    token_orgs: dict[str, set] = {}
    for org in org_schools:
        for tok in _org_tokens(org):
            token_orgs.setdefault(tok, set()).add(org)
    shared_word_orgs = set()
    for orgs in token_orgs.values():
        if len(orgs) >= 2:
            shared_word_orgs.update(orgs)
    return {
        "multi_school_orgs": multi_school_orgs,
        "shared_word_orgs": shared_word_orgs,
        "multi_school_pis": {pi for pi, schools in pi_schools.items()
                             if len({s for s in schools if s}) >= 2},
        "blanket_kw_keys": {key for key, n in dept_kw_counts.items() if n >= 3},
    }


# ---------------------------------------------------------- risk selectors ---

def _past_deadline(record: dict) -> bool:
    d = record.get("deadline")
    if not isinstance(d, str) or len(d) < 10:
        return False
    try:
        return date.fromisoformat(d[:10]) < date.today()
    except ValueError:
        return False


def _stale_title_year(record: dict) -> bool:
    m = _TITLE_YEAR_RE.search(record.get("title") or "")
    return bool(m) and int(m.group(1)) < date.today().year


def _generic_localpart(record: dict) -> bool:
    email = record.get("contact_email") or ""
    local = email.split("@", 1)[0].lower()
    return bool(email) and local.startswith(_GENERIC_LOCALPART_PREFIXES)


def _initials_only_first_name(record: dict) -> bool:
    tokens = (record.get("pi_name") or "").split()
    return bool(tokens) and _INITIALS_ONLY_RE.fullmatch(tokens[0]) is not None


# Ordered (tag, predicate(record, ctx)) per category. Quotas are filled
# round-robin in this order; an empty pool is reported in risk_pool_gaps.
RISK_SELECTORS = {
    "school": (
        ("multi_campus_org", lambda r, c: _org(r) in c["multi_school_orgs"]
         or ("purdue" in _org(r).lower() and r.get("school") == "purdue")),
        ("similar_org_name", lambda r, c: _org(r) in c["shared_word_orgs"]),
    ),
    "department": (
        ("unit_type_confusion", lambda r, c: bool(_UNIT_TYPE_RE.search(r.get("department") or ""))),
        ("empty_department", lambda r, c: not (r.get("department") or "").strip()),
    ),
    "professor": (
        ("same_name_multi_school", lambda r, c: r.get("pi_name") in c["multi_school_pis"]),
        ("emeritus_or_visiting", lambda r, c: bool(
            _EMERITUS_VISITING_RE.search(_md(r).get("faculty_title") or ""))),
    ),
    "position": (
        ("non_professor_rank", lambda r, c: bool(
            _NON_PROFESSOR_RANK_RE.search(_md(r).get("faculty_title") or ""))),
        ("default_professor", lambda r, c: _md(r).get("faculty_title") == "Professor"),
        ("empty_title", lambda r, c: not (_md(r).get("faculty_title") or "").strip()),
    ),
    "program": (
        ("status_unknown", lambda r, c: _md(r).get("status") == "unknown"),
        ("discovered", lambda r, c: _md(r).get("discovered") is True),
        ("stale_year_title", lambda r, c: _stale_title_year(r)),
    ),
    "deadline": (
        ("estimated_deadline", lambda r, c: bool(r.get("deadline_is_estimate"))),
        ("past_deadline", lambda r, c: _past_deadline(r)),
        ("rolling_with_note", lambda r, c: bool(r.get("is_rolling")) and bool(_md(r).get("deadline_note"))),
        ("rolling_faculty_default", lambda r, c: bool(r.get("is_rolling")) and _is_faculty(r)
         and not _md(r).get("deadline_note")),
    ),
    "international": (
        ("policy_no_nsf_reu", lambda r, c: r.get("source") == "nsf_reu"
         and _elig(r).get("international_friendly") == "no"),
        ("explicit_yes_claim", lambda r, c: _elig(r).get("international_friendly") == "yes"),
        ("citizenship_required", lambda r, c: _elig(r).get("citizenship_required") is True),
        ("stays_unknown", lambda r, c: _elig(r).get("international_friendly") == "unknown"),
    ),
    "email": (
        ("constructed_email", lambda r, c: (_md(r).get("email_source") or "").startswith("constructed")),
        ("wayback_email", lambda r, c: _md(r).get("email_source") == "wayback"),
        ("null_email", lambda r, c: not r.get("contact_email")),
        ("generic_localpart", lambda r, c: _generic_localpart(r)),
    ),
    "research_area": (
        ("keywords_no_evidence", lambda r, c: bool(r.get("keywords"))
         and not (_md(r).get("research_areas_raw") or "").strip()),
        ("keywords_empty", lambda r, c: not r.get("keywords")),
        ("dept_blanket_keywords", lambda r, c: bool(r.get("keywords")) and (
            r.get("school"), r.get("department"), tuple(r.get("keywords"))) in c["blanket_kw_keys"]),
    ),
    "publication": (
        ("works_without_status", lambda r, c: bool(_md(r).get("recent_works"))
         and not _md(r).get("publication_attribution_status")),
        ("verified_author_id", lambda r, c:
            _md(r).get("publication_attribution_status") == "verified_author_id"),
        ("initials_only_name", lambda r, c: _initials_only_first_name(r)),
    ),
}


# ---------------------------------------------------------- category pools ---

POOL_FILTERS = {
    "school": lambda r: True,
    "department": lambda r: True,
    "professor": lambda r: bool(r.get("pi_name")),
    "position": _is_faculty,
    "program": _is_campus_program,
    "deadline": lambda r: True,
    "international": lambda r: True,
    "email": lambda r: True,
    "research_area": lambda r: True,
    "publication": _is_faculty,
}


def _program_preferred(record: dict) -> bool:
    """Prefer records a campus collector explicitly produced."""
    return bool(_md(record).get("collector_source")
                or record.get("campus_source_type")
                or _md(record).get("campus_source_type"))


# ------------------------------------------------------------ system value ---

def _recent_works_value(record: dict) -> dict:
    works = _md(record).get("recent_works") or []
    return {
        "publication_attribution_status": _md(record).get("publication_attribution_status"),
        "recent_works_count": len(works),
        "recent_work_titles": [(w.get("title") or "") if isinstance(w, dict) else str(w)
                               for w in works[:5]],
    }


SYSTEM_VALUE = {
    "school": lambda r: {"school": r.get("school"), "organization": r.get("organization")},
    "department": lambda r: r.get("department"),
    "professor": lambda r: {"pi_name": r.get("pi_name"), "department": r.get("department"),
                            "organization": r.get("organization")},
    "position": lambda r: _md(r).get("faculty_title"),
    "program": lambda r: {"title": r.get("title"), "status": _md(r).get("status")},
    "deadline": lambda r: {"deadline": r.get("deadline"), "is_rolling": r.get("is_rolling"),
                           "deadline_is_estimate": r.get("deadline_is_estimate", False),
                           "deadline_note": _md(r).get("deadline_note")},
    "international": lambda r: {"international_friendly": _elig(r).get("international_friendly"),
                                "citizenship_required": _elig(r).get("citizenship_required")},
    "email": lambda r: r.get("contact_email"),
    "research_area": lambda r: r.get("keywords"),
    "publication": _recent_works_value,
}


# ---------------------------------------------------------------- sampling ---

def build_sample_row(category: str, seq: int, record: dict, risk_case: str | None) -> dict:
    return {
        "sample_id": f"{category}-{seq:03d}",
        "entity_type": category,
        "entity_id": record.get("id"),
        "field_name": FIELD_NAMES[category],
        "system_value": _truncate(SYSTEM_VALUE[category](record)),
        "verification_status": derive_verification_status(category, record),
        "source_url": record.get("source_url") or record.get("url") or "",
        "source_evidence": "",
        "manual_expected_value": None,
        "review_result": "pending",
        "error_type": None,
        "severity": None,
        "reviewer": None,
        "reviewed_at": None,
        "notes": "",
        "risk_case": risk_case,
    }


def sample_category(category: str, records: list[dict], ctx: dict,
                    seed: int, per_category: int) -> tuple[list[dict], list[str]]:
    """Deterministic sample for one category: risk quotas first, then random.

    ``records`` must already be sorted by id; the per-category RNG is seeded
    from (seed, category) so sampling one category alone yields the same rows
    as sampling all of them.
    """
    rng = random.Random(f"{seed}:{category}")
    pool = [r for r in records if _is_active(r) and POOL_FILTERS[category](r)]

    risk_target = min(per_category, max(1, round(per_category * 0.4)))
    gaps: list[str] = []
    selector_pools: list[tuple[str, list[dict]]] = []
    for tag, pred in RISK_SELECTORS[category]:
        matches = [r for r in pool if pred(r, ctx)]
        if matches:
            selector_pools.append((tag, matches))
        else:
            gaps.append(tag)

    selected: list[tuple[dict, str | None]] = []
    chosen_ids: set = set()
    while len(selected) < risk_target:
        progressed = False
        for tag, matches in selector_pools:
            available = [r for r in matches if r.get("id") not in chosen_ids]
            if not available:
                continue
            pick = rng.choice(available)
            selected.append((pick, tag))
            chosen_ids.add(pick.get("id"))
            progressed = True
            if len(selected) >= risk_target:
                break
        if not progressed:
            break

    need = per_category - len(selected)
    if need > 0:
        remainder = [r for r in pool if r.get("id") not in chosen_ids]
        if category == "program":
            preferred = [r for r in remainder if _program_preferred(r)]
            if len(preferred) >= need:
                remainder = preferred
        for pick in rng.sample(remainder, min(need, len(remainder))):
            selected.append((pick, None))

    rows = [build_sample_row(category, seq, record, tag)
            for seq, (record, tag) in enumerate(selected, 1)]
    return rows, gaps


def load_corpus(corpus_path: Path) -> list[dict]:
    if not corpus_path.exists():
        raise SystemExit(
            f"truthfulness_audit: corpus not found at {corpus_path}\n"
            "The work file is gitignored; assemble it from the committed shards first:\n"
            "    python scripts/shard_corpus.py assemble\n"
            "or point --corpus at an existing corpus JSON."
        )
    with open(corpus_path, encoding="utf-8") as f:
        records = json.load(f)
    records.sort(key=lambda r: str(r.get("id")))
    return records


def run_sample(corpus_path: Path, out_dir: Path, category: str,
               seed: int, per_category: int) -> int:
    records = load_corpus(corpus_path)
    ctx = build_risk_context(records)
    wanted = list(CATEGORIES) if category == "all" else [category]
    out_dir.mkdir(parents=True, exist_ok=True)
    for cat in wanted:
        rows, gaps = sample_category(cat, records, ctx, seed, per_category)
        payload = {
            "category": cat,
            "generated_at": datetime.now(UTC).isoformat(),
            "seed": seed,
            "corpus_records": len(records),
            "risk_pool_gaps": gaps,
            "samples": rows,
        }
        path = out_dir / f"{cat}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        risk_n = sum(1 for r in rows if r["risk_case"])
        print(f"{cat}: {len(rows)} samples ({risk_n} risk, {len(rows) - risk_n} random)"
              + (f"; risk_pool_gaps: {', '.join(gaps)}" if gaps else ""))
    return 0


# ------------------------------------------------------------------ report ---

def run_report(samples_dir: Path, out_path: Path) -> int:
    categories: dict[str, dict] = {}
    critical_open: list[str] = []
    approved = True

    for cat in CATEGORIES:
        path = samples_dir / f"{cat}.json"
        if not path.exists():
            categories[cat] = {"present": False, "sample_count": 0,
                               "reviewed_count": 0, "complete": False,
                               "results": {r: 0 for r in REVIEW_RESULTS}}
            approved = False  # fail-closed: missing category file
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        samples = data.get("samples") or []
        results = {r: 0 for r in REVIEW_RESULTS}
        for s in samples:
            verdict = s.get("review_result") or "pending"
            if verdict not in results:
                verdict = "pending"  # fail-closed: unknown verdicts don't count as reviewed
            results[verdict] += 1
            if (s.get("severity") == "critical"
                    and s.get("review_result") in FINDING_RESULTS
                    and "RESOLVED:" not in (s.get("notes") or "")):
                critical_open.append(s.get("sample_id"))
        pending = results["pending"]
        complete = len(samples) >= MIN_REVIEWED_FOR_COMPLETE and pending == 0
        if not complete:
            approved = False  # fail-closed: any pending / thin category
        categories[cat] = {
            "present": True,
            "sample_count": len(samples),
            "reviewed_count": len(samples) - pending,
            "complete": complete,
            "results": results,
        }

    if critical_open:
        approved = False
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "categories": categories,
        "critical_open": critical_open,
        "truthfulness_approved": approved,
        "decision": "GO" if approved else "NO-GO",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    header = f"{'category':<15}{'samples':>8}{'reviewed':>9}{'pending':>8}{'findings':>9}  complete"
    print(header)
    print("-" * len(header))
    for cat, info in categories.items():
        findings = sum(info["results"].get(r, 0) for r in FINDING_RESULTS)
        status = ("MISSING" if not info["present"]
                  else "yes" if info["complete"] else "no")
        print(f"{cat:<15}{info['sample_count']:>8}{info['reviewed_count']:>9}"
              f"{info['results'].get('pending', 0):>8}{findings:>9}  {status}")
    if critical_open:
        print(f"\ncritical_open ({len(critical_open)}): {', '.join(critical_open)}")
    banner = f"TRUTHFULNESS DECISION: {report['decision']}"
    print()
    print("=" * len(banner))
    print(banner)
    print("=" * len(banner))
    print(f"report written to {out_path}")
    return 0


# --------------------------------------------------------------------- CLI ---

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="truthfulness_audit.py",
        description="Manual truthfulness sample-verification framework "
                    "(see docs/truthfulness_sample_plan.md).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("sample", help="draw deterministic per-category samples")
    sp.add_argument("--category", default="all", choices=[*CATEGORIES, "all"])
    sp.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    sp.add_argument("--out", type=Path, default=DEFAULT_SAMPLES_DIR)
    sp.add_argument("--seed", type=int, default=DEFAULT_SEED)
    sp.add_argument("--per-category", type=int, default=DEFAULT_PER_CATEGORY,
                    dest="per_category")

    rp = sub.add_parser("report", help="aggregate reviewed samples into the GO/NO-GO report")
    rp.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES_DIR)
    rp.add_argument("--out", type=Path, default=DEFAULT_REPORT)

    args = parser.parse_args(argv)
    if args.command == "sample":
        return run_sample(args.corpus, args.out, args.category, args.seed, args.per_category)
    return run_report(args.samples, args.out)


if __name__ == "__main__":
    sys.exit(main())
