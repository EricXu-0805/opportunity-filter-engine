#!/usr/bin/env python3
"""Production release gate: evidence in, GO/NO-GO out.

The default answer is NO-GO. A release becomes GO only when every required
gate presents current, verifiable evidence bound to one frozen release SHA.
Missing evidence, a skipped critical check, a SHA mismatch, or an
unverifiable gate all keep the answer NO-GO — the gate never assumes, and it
never treats "we could not check" as "fine".

That last rule is the whole point. This repo already contains four
production-grade gate primitives that were wired to nothing
(``scripts/verify_refresh_pr.py``, the professor-tracking ``release_ready``
contract, ``scripts/truthfulness_audit.py``'s GO/NO-GO, and the
``ops_incidents`` queue). This aggregates them and records what is still
unproven, rather than inventing new checks that would be easier to pass.

Usage:
    python scripts/release_gate.py --release-sha <sha> [--evidence FILE ...]
    python scripts/release_gate.py --release-sha <sha> --out data/releases/<sha>.json

Exit codes: 0 = GO, 1 = NO-GO. A non-zero exit is the normal, expected
outcome for a release that has not yet gathered its infrastructure evidence.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# Verdicts a gate may carry. UNVERIFIED is deliberately distinct from FAIL:
# a failure is evidence of a problem, while UNVERIFIED means we have no
# evidence either way. Both block, but conflating them would hide which
# gates need infrastructure access versus which need fixing.
PASS = "PASS"
FAIL = "FAIL"
UNVERIFIED = "UNVERIFIED"
SKIPPED = "SKIPPED"
NOT_RUN = "NOT_RUN"

_BLOCKING = (FAIL, UNVERIFIED, SKIPPED, NOT_RUN)

# Gates whose evidence can only come from outside this repository: a deployed
# service, a provider dashboard, or a restore drill. The gate cannot fabricate
# them, so it demands them as signed evidence files and reports UNVERIFIED
# until they arrive.
_EXTERNAL_GATES = (
    "render_canary",
    "vercel_canary",
    "supabase_canary",
    "backup",
    "restore",
    "dead_man",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gate(name: str, status: str, detail: str, evidence: object = None) -> dict:
    return {"gate": name, "status": status, "detail": detail, "evidence": evidence}


# ---------------------------------------------------------------------------
# In-repo gates: things this process can genuinely verify
# ---------------------------------------------------------------------------

def check_release_sha(sha: str | None) -> dict:
    """The release must be a real, unambiguous, committed SHA."""
    if not sha:
        return _gate("release_sha", FAIL, "no --release-sha supplied")
    if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha.lower()):
        return _gate("release_sha", FAIL,
                     f"not a full 40-hex commit sha: {sha!r} "
                     "(short shas and tags are ambiguous)")
    try:
        subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                       cwd=_REPO, check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return _gate("release_sha", FAIL, f"sha not present in this repository: {sha}")
    return _gate("release_sha", PASS, "resolves to a commit in this repository",
                 {"release_sha": sha})


def check_worktree_clean(sha: str | None) -> dict:
    """Evidence must describe committed code, not a dirty checkout."""
    try:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=_REPO,
                               check=True, capture_output=True, text=True).stdout.strip()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO,
                              check=True, capture_output=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return _gate("worktree", UNVERIFIED, f"git unavailable: {exc}")
    if dirty:
        return _gate("worktree", FAIL,
                     f"{len(dirty.splitlines())} uncommitted change(s): evidence "
                     "gathered here would not describe the release sha")
    if sha and head.lower() != sha.lower():
        return _gate("worktree", FAIL,
                     f"HEAD {head[:8]} != release sha {sha[:8]}: local evidence "
                     "would come from different code")
    return _gate("worktree", PASS, "clean worktree at the release sha", {"head": head})


def check_corpus_floor(min_records: int) -> dict:
    """A corpus that is present but empty passes shape checks vacuously."""
    shard_dir = _REPO / "data" / "processed" / "shards"
    if not shard_dir.is_dir():
        return _gate("corpus", FAIL, "data/processed/shards is missing")
    shards = sorted(shard_dir.glob("*.json"))
    if not shards:
        return _gate("corpus", FAIL, "no shards present")
    total = 0
    for shard in shards:
        try:
            with shard.open(encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return _gate("corpus", FAIL, f"{shard.name} unreadable: {exc}")
        if not isinstance(payload, list):
            return _gate("corpus", FAIL, f"{shard.name} is not a record list")
        total += len(payload)
    if total < min_records:
        return _gate("corpus", FAIL,
                     f"{total} records below floor {min_records}: the data-quality "
                     "gate would pass vacuously on a corpus this small")
    return _gate("corpus", PASS, f"{total} records across {len(shards)} shards",
                 {"records": total, "shards": len(shards)})


# Module-level so a test can point the gate at a fixture ledger instead of
# asserting against whatever the committed corpus happens to look like today.
_SOURCE_HEALTH_PATH = _REPO / "data" / "processed" / "source_health.json"


def check_no_fully_stale_school() -> dict:
    """No school may have stopped refreshing entirely.

    The corpus floor above counts RECORDS, which a frozen school passes
    without trouble: UC Berkeley's 3,106 records sat 44 days stale and
    contributed every one of them to the total. Staleness is per source, so
    it needs its own gate reading the per-source ledger.

    ``fully_stale`` is deliberately the school-wide condition, not the
    per-shard one: one stale department among fresh siblings is the
    partial degradation the publish path now allows on purpose, and failing
    the release for it would re-create the veto from the other direction.
    A school with NO fresh source has stopped refreshing, and that is a
    release blocker.
    """
    path = _SOURCE_HEALTH_PATH
    if not path.exists():
        return _gate("no_fully_stale_school", UNVERIFIED,
                     "source_health.json absent: per-source freshness unknown")
    try:
        sys.path.insert(0, str(_REPO))
        from src.collectors import source_health  # noqa: PLC0415
        report = source_health.corpus_report(source_health.load_ledger(path))
    except Exception as exc:  # noqa: BLE001
        return _gate("no_fully_stale_school", UNVERIFIED,
                     f"could not evaluate: {exc}")
    count = report["fully_stale_school_count"]
    detail = {
        "fully_stale_school_count": count,
        "fully_stale_schools": report["fully_stale_schools"][:20],
        "school_count": report["school_count"],
        "partially_degraded_school_count": report[
            "partially_degraded_school_count"
        ],
        "stale_shard_count": report["stale_shard_count"],
        "failed_shard_count": report["failed_shard_count"],
        "stale_days": report["stale_days"],
    }
    if count:
        return _gate(
            "no_fully_stale_school", FAIL,
            f"{count} school(s) have no fresh source at all: "
            f"{', '.join(report['fully_stale_schools'][:10])}",
            detail,
        )
    return _gate(
        "no_fully_stale_school", PASS,
        f"every one of {report['school_count']} school(s) has fresh data "
        f"({report['partially_degraded_school_count']} partially degraded, "
        f"{report['stale_shard_count']} stale shard(s))",
        detail,
    )


def check_tracking_release_ready() -> dict:
    """The professor-tracking artifact's own strict release contract."""
    path = _REPO / "data" / "processed" / "professor_tracking.json"
    if not path.exists():
        return _gate("tracking_release_ready", UNVERIFIED, "artifact absent")
    try:
        sys.path.insert(0, str(_REPO))
        from src.tracking.professor_profiles import (  # noqa: PLC0415
            artifact_release_ready,
            load_tracking_state,
        )
        state = load_tracking_state(path)
    except Exception as exc:  # noqa: BLE001 — any import/parse issue is unverified
        return _gate("tracking_release_ready", UNVERIFIED, f"could not evaluate: {exc}")
    ready = bool(artifact_release_ready(state))
    block = (state or {}).get("release") or {}
    checks = block.get("checks") or {}
    failing = sorted(k for k, v in checks.items() if v is not True)
    if not ready:
        return _gate(
            "tracking_release_ready", FAIL,
            "strict artifact contract not satisfied "
            f"(stored release_ready={block.get('release_ready')!r}, "
            f"failing/absent checks: {failing or 'check set incomplete'})",
            {"stored_release_ready": block.get("release_ready"), "failing": failing},
        )
    return _gate("tracking_release_ready", PASS, "strict artifact contract satisfied",
                 {"checks": len(checks)})


def check_truthfulness() -> dict:
    """The manual-verification ledger's own GO/NO-GO, plus its age.

    The report is a human-review artifact with no TTL and no corpus binding,
    so a stale GO is not evidence about today's corpus. Age is reported and
    a very old report is refused rather than trusted.
    """
    path = _REPO / "data" / "audits" / "truthfulness_report.json"
    if not path.exists():
        return _gate("truthfulness", UNVERIFIED, "no truthfulness report")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _gate("truthfulness", UNVERIFIED, f"unreadable: {exc}")
    decision = payload.get("decision")
    generated = payload.get("generated_at")
    age_days: float | None = None
    if isinstance(generated, str) and generated:
        try:
            stamp = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            age_days = (datetime.now(UTC) - stamp).total_seconds() / 86400
        except ValueError:
            age_days = None
    evidence = {"decision": decision, "generated_at": generated, "age_days": age_days}
    if decision != "GO":
        return _gate("truthfulness", FAIL, f"decision={decision!r}", evidence)
    if age_days is None:
        return _gate("truthfulness", UNVERIFIED,
                     "GO but generated_at is missing/unparseable, so its currency "
                     "cannot be established", evidence)
    if age_days > TRUTHFULNESS_MAX_AGE_DAYS:
        return _gate("truthfulness", FAIL,
                     f"GO but {age_days:.1f}d old (max {TRUTHFULNESS_MAX_AGE_DAYS}d): "
                     "a human audit predating the corpus is not evidence about it",
                     evidence)
    return _gate("truthfulness", PASS, f"GO, {age_days:.1f}d old", evidence)


def check_open_incidents(evidence: dict | None) -> dict:
    """Unresolved operational incidents block a release.

    The queue lives in Supabase, which this process cannot reach, so the
    count must be supplied as evidence from an authenticated admin call.
    """
    if not evidence:
        return _gate("open_incidents", UNVERIFIED,
                     "no incident rollup supplied (GET /api/admin/ops/incidents"
                     "?unresolved_only=true)")
    rollup = evidence.get("rollup") or {}
    total = rollup.get("open_total")
    if not isinstance(total, int):
        return _gate("open_incidents", UNVERIFIED, "rollup.open_total absent")
    if rollup.get("truncated"):
        return _gate("open_incidents", UNVERIFIED,
                     "rollup truncated: a capped count cannot prove zero")
    if total > 0:
        return _gate("open_incidents", FAIL, f"{total} unresolved incident(s)",
                     {"open_by_kind": rollup.get("open_by_kind")})
    return _gate("open_incidents", PASS, "no unresolved incidents", rollup)


def check_flag_parity() -> dict:
    """Backend and frontend release-scope flags must not drift apart."""
    be = _REPO / "backend" / "lib" / "release_scope.py"
    fe = _REPO / "frontend" / "src" / "lib" / "release-scope.ts"
    if not be.exists() or not fe.exists():
        return _gate("flag_parity", UNVERIFIED, "release-scope module missing")
    import re  # noqa: PLC0415

    be_keys = set(re.findall(r'"([a-z0-9_]+)"\s*:\s*(?:True|False)', be.read_text()))
    fe_keys = {
        re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
        for k in re.findall(r"^\s*([a-zA-Z0-9]+)\s*:\s*(?:true|false)",
                            fe.read_text(), re.MULTILINE)
    }
    if not be_keys or not fe_keys:
        return _gate("flag_parity", UNVERIFIED, "could not parse flag tables")
    only_be = sorted(be_keys - fe_keys)
    only_fe = sorted(fe_keys - be_keys)
    if only_be or only_fe:
        # Frontend-only flags mean a surface with no server-side gate.
        return _gate("flag_parity", FAIL,
                     f"flag drift — backend-only: {only_be or 'none'}, "
                     f"frontend-only (ungated server-side): {only_fe or 'none'}",
                     {"backend_only": only_be, "frontend_only": only_fe})
    return _gate("flag_parity", PASS, f"{len(be_keys)} flags aligned")


def check_ci_evidence(evidence: dict | None, sha: str | None) -> list[dict]:
    """Required CI checks: same SHA, all green, nothing critical skipped.

    ``scripts/verify_refresh_pr.py`` already encodes the required-check names
    and the same-SHA rule; this consumes a snapshot in that shape rather than
    inventing a second definition.
    """
    required = ("Backend (lint + pytest)", "Frontend (typecheck + build)",
                "Migrations (Flow B merge + CLI replay)", "E2E (Playwright)")
    if not evidence:
        return [_gate(f"ci:{name}", UNVERIFIED, "no CI evidence supplied")
                for name in required]
    head = evidence.get("head_sha")
    checks = {c.get("name"): c for c in (evidence.get("checks") or [])}
    out: list[dict] = []
    for name in required:
        got = checks.get(name)
        if got is None:
            out.append(_gate(f"ci:{name}", NOT_RUN, "check not registered"))
            continue
        if sha and head and head.lower() != sha.lower():
            out.append(_gate(f"ci:{name}", FAIL,
                             f"evidence is for {head[:8]}, release is {sha[:8]}"))
            continue
        state = (got.get("conclusion") or got.get("state") or "").upper()
        if state in ("SKIPPED", "NEUTRAL"):
            out.append(_gate(f"ci:{name}", SKIPPED,
                             "a skipped required check is not a pass"))
        elif state == "SUCCESS":
            out.append(_gate(f"ci:{name}", PASS, f"green on {head[:8]}",
                             {"head_sha": head}))
        else:
            out.append(_gate(f"ci:{name}", FAIL, f"conclusion={state or 'unknown'}"))
    return out


def check_external(name: str, evidence: dict | None, sha: str | None) -> dict:
    """A gate whose evidence must come from outside the repo."""
    if not evidence:
        return _gate(name, UNVERIFIED,
                     "no evidence supplied; this gate cannot be verified from "
                     "inside the repository and must not be assumed")
    got_sha = evidence.get("release_sha")
    if sha and got_sha and str(got_sha).lower() != sha.lower():
        return _gate(name, FAIL,
                     f"evidence sha {str(got_sha)[:8]} != release sha {sha[:8]}")
    if sha and not got_sha:
        return _gate(name, UNVERIFIED, "evidence carries no release_sha to bind it")
    status = str(evidence.get("status", "")).upper()
    if status != PASS:
        return _gate(name, FAIL if status else UNVERIFIED,
                     f"status={status or 'absent'}", evidence)
    return _gate(name, PASS, str(evidence.get("detail") or "evidence supplied"),
                 evidence)


# ---------------------------------------------------------------------------

CORPUS_MIN_RECORDS = 1000
TRUTHFULNESS_MAX_AGE_DAYS = 30.0


def build_ledger(sha: str | None, evidence: dict, *, min_records: int) -> dict:
    gates: list[dict] = [
        check_release_sha(sha),
        check_worktree_clean(sha),
        check_corpus_floor(min_records),
        check_no_fully_stale_school(),
        check_tracking_release_ready(),
        check_truthfulness(),
        check_open_incidents(evidence.get("open_incidents")),
        check_flag_parity(),
        *check_ci_evidence(evidence.get("ci"), sha),
        *(check_external(name, evidence.get(name), sha) for name in _EXTERNAL_GATES),
        check_external("api_ready", evidence.get("api_ready"), sha),
        check_external("promotion", evidence.get("promotion"), sha),
        check_external("rollback", evidence.get("rollback"), sha),
        check_external("scheduler", evidence.get("scheduler"), sha),
    ]
    blocking = [g for g in gates if g["status"] in _BLOCKING]
    return {
        "release_sha": sha,
        "generated_at": _now(),
        "gate_version": "release-gate-v1",
        "gates": gates,
        "summary": {
            "passed": sum(1 for g in gates if g["status"] == PASS),
            "failed": sum(1 for g in gates if g["status"] == FAIL),
            "unverified": sum(1 for g in gates if g["status"] == UNVERIFIED),
            "skipped": sum(1 for g in gates if g["status"] == SKIPPED),
            "not_run": sum(1 for g in gates if g["status"] == NOT_RUN),
        },
        "blocking_reasons": [f"{g['gate']}: {g['detail']}" for g in blocking],
        "final_decision": "GO" if not blocking else "NO-GO",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release-sha", help="full 40-hex commit sha being released")
    ap.add_argument("--evidence", action="append", default=[],
                    help="JSON file of external gate evidence (repeatable)")
    ap.add_argument("--out", type=Path, help="write the ledger here")
    ap.add_argument("--min-records", type=int, default=CORPUS_MIN_RECORDS)
    args = ap.parse_args()

    evidence: dict = {}
    for raw in args.evidence:
        path = Path(raw)
        if not path.exists():
            print(f"::error::evidence file not found: {path}")
            return 1
        try:
            evidence.update(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            print(f"::error::evidence file {path} is not valid JSON: {exc}")
            return 1

    ledger = build_ledger(args.release_sha, evidence, min_records=args.min_records)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    s = ledger["summary"]
    print(f"release_sha: {ledger['release_sha'] or '(none)'}")
    print(f"passed={s['passed']} failed={s['failed']} unverified={s['unverified']} "
          f"skipped={s['skipped']} not_run={s['not_run']}")
    for gate in ledger["gates"]:
        print(f"  [{gate['status']:<10}] {gate['gate']}: {gate['detail']}")
    if ledger["blocking_reasons"]:
        print("\nblocking:")
        for reason in ledger["blocking_reasons"]:
            print(f"  - {reason}")
    print(f"\nDECISION: {ledger['final_decision']}")
    return 0 if ledger["final_decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
