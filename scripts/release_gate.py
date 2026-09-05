#!/usr/bin/env python3
"""Production release gate: evidence in, GO/NO-GO out.

The default answer is NO-GO. A release becomes GO only when every *applicable*
required gate presents current, verifiable evidence bound to one frozen release
SHA. Missing evidence, a skipped critical check, a SHA mismatch, stale evidence,
or an unverifiable gate all keep the answer NO-GO — the gate never assumes, and
it never treats "we could not check" as "fine".

That last rule is the whole point. This repo already contains four
production-grade gate primitives that were wired to nothing
(``scripts/verify_refresh_pr.py``, the professor-tracking ``release_ready``
contract, ``scripts/truthfulness_audit.py``'s GO/NO-GO, and the
``ops_incidents`` queue). This aggregates them and records what is still
unproven, rather than inventing new checks that would be easier to pass.

Four rules distinguish this from a checklist that drifts into decoration:

1. **Applicability is not leniency.** A gate whose only consumers sit behind a
   source-controlled-off feature flag reports ``NOT_APPLICABLE`` with the
   flag named — never ``FAIL`` (an unexplained permanent red nobody can
   action) and never ``PASS`` (a claim the evidence does not support). The
   underlying numbers are still recorded, so the gap stays visible and the
   check re-arms by itself when the flag flips.
2. **Evidence expires.** Every gate that describes a live observation must
   carry ``observed_at``; past its gate-specific maximum age it is stale
   evidence and blocks, exactly as absent evidence does.
3. **The ledger checks itself.** A committed ledger for a different SHA, or
   one older than its own maximum age, is stale evidence about today's
   candidate and is reported as such rather than being quietly consulted.
4. **Every non-PASS carries a reason, an owner, and an action.** A blocker
   nobody can act on is how a gate becomes decoration.

Usage:
    python scripts/release_gate.py --release-sha <sha> [--evidence FILE ...]
    python scripts/release_gate.py --release-sha <sha> --out data/releases/<sha>.json
    python scripts/release_gate.py --release-sha <sha> ... --update-current

Exit codes: 0 = GO, 1 = NO-GO. A non-zero exit is the normal, expected
outcome for a release that has not yet gathered its infrastructure evidence.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# Verdicts a gate may carry. UNVERIFIED is deliberately distinct from FAIL:
# a failure is evidence of a problem, while UNVERIFIED means we have no
# evidence either way. Both block, but conflating them would hide which
# gates need infrastructure access versus which need fixing.
#
# NOT_APPLICABLE is the one verdict that does NOT block, and the only one that
# may be assigned without evidence about the thing itself — because the claim
# it makes is about the release surface, not about the check: "no shipped path
# depends on this". It must always name the flag that makes it true, so it can
# be re-derived, and re-armed, when that flag flips.
PASS = "PASS"
FAIL = "FAIL"
UNVERIFIED = "UNVERIFIED"
BLOCKED = "BLOCKED"
CANNOT_VERIFY = "CANNOT_VERIFY"
SKIPPED = "SKIPPED"
NOT_RUN = "NOT_RUN"
NOT_APPLICABLE = "NOT_APPLICABLE"

# All of these block. They are kept apart because they need different people
# on different days:
#
#   FAIL           we measured it and the requirement is not met. Fix the thing.
#   UNVERIFIED     nobody has gathered the evidence yet. Go and gather it.
#   BLOCKED        the evidence CANNOT be gathered without access or
#                  authorization that does not currently exist. Someone has to
#                  provision something first.
#   CANNOT_VERIFY  we tried and the answer was indeterminate — an unreadable
#                  artifact, an unparseable threshold. Repair the input.
#
# The distinction that actually cost this project a release cycle is FAIL vs
# UNVERIFIED: a known-failing number reported as "no evidence" reads like
# paperwork, and paperwork gets deferred. A measured 91.17% against a 95%
# floor is not missing evidence. It is a failure.
_BLOCKING = (FAIL, UNVERIFIED, BLOCKED, CANNOT_VERIFY, SKIPPED, NOT_RUN)

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

# How old a live observation may be before it stops describing the release.
# A canary reading is a statement about a running deploy, and decays fast. A
# backup recovery point decays on the retention window — 7 days here, so a
# recorded point older than that is no longer restorable at all.
_EVIDENCE_MAX_AGE_DAYS: dict[str, float] = {
    "render_canary": 3.0,
    "vercel_canary": 3.0,
    "supabase_canary": 3.0,
    "api_ready": 3.0,
    "promotion": 7.0,
    "rollback": 30.0,
    "scheduler": 7.0,
    "dead_man": 30.0,
    "backup": 7.0,
    "open_incidents": 3.0,
    "provider_readiness": 3.0,
}

CORPUS_MIN_RECORDS = 1000
TRUTHFULNESS_MAX_AGE_DAYS = 30.0
LEDGER_MAX_AGE_DAYS = 7.0
RESTORE_DRILL_MAX_AGE_DAYS = 180.0


# ---------------------------------------------------------------------------
# Ownership and remediation. A blocking gate with no named owner and no next
# step is the shape every permanently-red check here has taken before: it
# stops being read, because reading it changes nothing.
# ---------------------------------------------------------------------------

_OWNERS: dict[str, str] = {
    "release_sha": "release operator",
    "worktree": "release operator",
    "corpus": "data pipeline owner",
    "ledger_currency": "release operator",
    "corpus_freshness": "data pipeline owner",
    "tracking_freshness": "data pipeline owner",
    "no_fully_stale_school": "data pipeline owner",
    "tracking_release_ready": "data pipeline owner",
    "truthfulness": "data pipeline owner",
    "open_incidents": "ops on-call",
    "flag_parity": "backend owner",
    "provider_readiness": "release operator",
    "restore_drill": "infrastructure owner (Supabase project owner)",
    "backup": "infrastructure owner (Supabase project owner)",
    "restore": "infrastructure owner (Supabase project owner)",
    "render_canary": "release operator",
    "vercel_canary": "release operator",
    "supabase_canary": "infrastructure owner",
    "api_ready": "release operator",
    "promotion": "release operator",
    "rollback": "release operator",
    "scheduler": "ops on-call",
    "dead_man": "ops on-call",
}
_DEFAULT_OWNER = "release operator"

_ACTIONS: dict[str, str] = {
    "ledger_currency": "re-run scripts/release_gate.py against the candidate SHA "
                       "with --update-current",
    "corpus_freshness": "repair the collectors behind the stale sources and re-run "
                        "their shard; see scripts/source_freshness_report.py report",
    "tracking_freshness": "run a refresh that profile-verifies the stale baselines, or "
                          "keep professor_signals closed",
    "no_fully_stale_school": "repair the collectors for the named schools and re-run "
                             "their shards",
    "tracking_release_ready": "raise professor-tracking coverage, or keep "
                              "professor_signals closed",
    "truthfulness": "re-run scripts/truthfulness_audit.py against the current corpus",
    "open_incidents": "resolve or explicitly triage the open ops_incidents rows",
    "flag_parity": "align backend/lib/release_scope.py with "
                   "frontend/src/lib/release-scope.ts",
    "provider_readiness": "GET /api/ready with X-Admin-Token and record "
                          "reported.providers as provider_readiness evidence",
    "restore_drill": "perform the drill in docs/DISASTER_RECOVERY.md §2 and record it "
                     "under data/releases/drills/",
    "backup": "record the current recovery point in the release evidence file",
    "restore": "record the restore-drill outcome as `restore` evidence",
}
_DEFAULT_ACTION = ("gather the evidence named in docs/RELEASE.md §2 and add it to "
                   "data/releases/evidence/<sha>.json")

# Gates whose evidence cannot be produced by anyone without credentials or a
# provisioning decision. Absent evidence here is BLOCKED, not UNVERIFIED: the
# difference is whether the next step is "go and look" or "someone has to grant
# access first", and only the second one needs escalating.
_ACCESS_REQUIRED = frozenset({
    "restore_drill",   # a billed scratch project the owner must provision
    "backup",          # Supabase dashboard
    "restore",         # depends on the drill above
    "supabase_canary", # authenticated project read
    "open_incidents",  # ADMIN_TOKEN
    "provider_readiness",  # ADMIN_TOKEN
    "dead_man",        # SQL against production
})


def _absent_status(name: str) -> str:
    """UNVERIFIED when someone could just go and look; BLOCKED when they can't."""
    return BLOCKED if name in _ACCESS_REQUIRED else UNVERIFIED


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat()


def _default_reason(status: str) -> str:
    return {
        FAIL: "check_failed",
        UNVERIFIED: "evidence_absent",
        BLOCKED: "access_required",
        CANNOT_VERIFY: "indeterminate",
        SKIPPED: "required_check_skipped",
        NOT_RUN: "required_check_not_run",
        NOT_APPLICABLE: "not_applicable",
    }.get(status, "unknown")


def _gate(name: str, status: str, detail: str, evidence: object = None,
          *, reason: str | None = None) -> dict:
    """One gate verdict, annotated so a blocker is actionable.

    ``reason`` is the machine-readable *why* (``feature_flag_disabled``,
    ``evidence_absent``, ``evidence_stale``…); ``detail`` stays the human
    sentence. Owner and action are attached to everything that is not a plain
    PASS, NOT_APPLICABLE included — a check that stopped applying still needs a
    named owner for the day its flag flips back on.
    """
    out: dict = {"gate": name, "status": status, "detail": detail,
                 "evidence": evidence, "last_checked_at": _now_iso()}
    if status != PASS:
        out["reason"] = reason or _default_reason(status)
        out["release_blocking"] = status in _BLOCKING
        out["owner"] = _OWNERS.get(name, _DEFAULT_OWNER)
        out["recommended_action"] = _ACTIONS.get(name, _DEFAULT_ACTION)
    return out


def _parse_stamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _age_days(value: object, *, now: datetime | None = None) -> float | None:
    stamp = _parse_stamp(value)
    if stamp is None:
        return None
    return ((now or _now()) - stamp).total_seconds() / 86400


# ---------------------------------------------------------------------------
# Feature-flag applicability
#
# A gate exists to protect a shipped path. When every path it protects is
# source-controlled off, the honest verdict is NOT_APPLICABLE with the flag
# named — not FAIL, which is an unexplained permanent red, and not PASS, which
# claims evidence nobody gathered.
#
# The mapping is deliberately gate -> the features that REQUIRE it, plural. A
# gate stops applying only when EVERY requiring feature is off; one enabled
# consumer keeps it blocking. That asymmetry is what stops "some feature is
# off" from quietly excusing a dependency a live path still needs.
# ---------------------------------------------------------------------------

_GATE_REQUIRED_BY: dict[str, tuple[str, ...]] = {
    # professor_tracking.json has exactly four consumers and every one of them
    # sits behind professor_signals: /api/professors/updates and
    # /api/opportunities/responsiveness are 404'd by ReleaseScopeMiddleware,
    # the record-scoped professor_id is stripped from opportunity detail
    # (backend/routes/opportunities.py), and the responsiveness ranking bonus
    # is skipped (backend/routes/matches.py). /api/ready reads the artifact but
    # reports it under "reported", explicitly outside the gating checks.
    "tracking_release_ready": ("professor_signals",),
    "tracking_freshness": ("professor_signals",),
}

# Providers, and the features that need them. Same rule: a provider stops
# blocking only when every feature requiring it is off. ``None`` means "the
# core product path", which is never flag-disabled and therefore always
# applies — the entry exists so that adding features to a list can never
# accidentally excuse a core dependency.
_PROVIDER_REQUIRED_BY: dict[str, tuple[str | None, ...]] = {
    "supabase": (None,),
    "admin_surface": (None,),
    "cron_surface": (None,),
    # The LLM key is what ask_ai would need, but resume_renovate is ACCEPTED
    # and shares it, and so does the already-public /api/tailor. Closing
    # ask_ai must not excuse it.
    "llm": (None, "ask_ai", "resume_renovate"),
    "resend_email": (None,),
    "web_push": (None,),
    "sentry": (None,),
}


def load_release_scope() -> dict[str, bool] | None:
    """The backend's source-controlled feature table, or None if unreadable.

    None is load-bearing: an unknown flag state must fail safe — every gate
    keeps applying — rather than silently excusing checks.
    """
    try:
        sys.path.insert(0, str(_REPO))
        from backend.lib.release_scope import RELEASE_SCOPE  # noqa: PLC0415

        scope = {str(k): bool(v) for k, v in dict(RELEASE_SCOPE).items()}
    except Exception:  # noqa: BLE001 — any import/shape problem means "unknown"
        return None
    return scope or None


def feature_applicability(gate_name: str,
                          scope: dict[str, bool] | None) -> tuple[bool, dict]:
    """``(applies, detail)`` for one gate under the current flag table.

    Fails safe in every uncertain direction: an unreadable table, an
    unrecognised flag name, or a missing entry all leave the gate applying.
    """
    features = _GATE_REQUIRED_BY.get(gate_name)
    if not features:
        return True, {"required_by": []}
    if scope is None:
        return True, {"required_by": list(features), "flag_state": "unknown",
                      "note": "release-scope table unreadable; gate keeps applying"}
    unknown = [f for f in features if f not in scope]
    if unknown:
        return True, {"required_by": list(features), "flag_state": "unknown",
                      "unknown_features": unknown,
                      "note": "unrecognised flag name; gate keeps applying"}
    enabled = [f for f in features if scope[f]]
    return bool(enabled), {
        "required_by": list(features),
        "enabled_features": enabled,
        "disabled_features": [f for f in features if not scope[f]],
        "flag_state": "known",
    }


def apply_applicability(gate: dict, scope: dict[str, bool] | None) -> dict:
    """Re-label a gate NOT_APPLICABLE when no enabled feature requires it.

    The original verdict is preserved under ``evidence.would_be`` rather than
    discarded: a disabled feature's real state is still worth reading, and
    keeping it is what makes the check re-armable instead of forgotten. A gate
    that already PASSes is left alone — a genuine pass is more informative than
    "we did not need to look".
    """
    applies, detail = feature_applicability(gate["gate"], scope)
    if applies or gate["status"] == PASS:
        return gate
    disabled = ", ".join(detail.get("disabled_features") or []) or "its feature"
    return _gate(
        gate["gate"], NOT_APPLICABLE,
        f"no shipped path depends on this: {disabled} is disabled in "
        f"backend/lib/release_scope.py (underlying state kept below, not waived)",
        {"applicability": detail,
         "would_be": {"status": gate["status"], "detail": gate["detail"],
                      "evidence": gate.get("evidence")}},
        reason="feature_flag_disabled",
    )


# ---------------------------------------------------------------------------
# Candidate identity: what, exactly, is being decided
# ---------------------------------------------------------------------------

def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=_REPO, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def migration_set_identity() -> dict:
    """Identity of the committed migration set.

    A restore drill is only evidence about the schema state it restored.
    Migrations here are forward-only, so a drill taken before new ones landed
    says nothing about recovering to today's target — this is what a drill
    record has to match to still count.
    """
    import hashlib  # noqa: PLC0415

    directory = _REPO / "supabase" / "migrations"
    names = sorted(p.name for p in directory.glob("*.sql")) if directory.is_dir() else []
    digest = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()[:16]
    return {"count": len(names), "head": names[-1] if names else None,
            "digest": digest}


def candidate_identity(sha: str | None) -> dict:
    """Everything that has to agree for evidence to describe one candidate."""
    try:
        sys.path.insert(0, str(_REPO))
        from src.tracking.professor_profiles import (  # noqa: PLC0415
            TRACKING_SCHEMA_VERSION,
        )

        tracking_schema: int | None = int(TRACKING_SCHEMA_VERSION)
    except Exception:  # noqa: BLE001
        tracking_schema = None
    try:
        from src.matcher.config import MATCHER_VERSION  # noqa: PLC0415

        matcher_version: str | None = str(MATCHER_VERSION)
    except Exception:  # noqa: BLE001
        matcher_version = None
    return {
        "release_sha": sha,
        "candidate_created_at": _git("show", "-s", "--format=%cI", sha) if sha else None,
        # Content-addressed and free: the git tree hash of the shard directory
        # changes if and only if the committed corpus changes.
        "corpus_version": _git("rev-parse", f"{sha}:data/processed/shards")
        if sha else None,
        "matcher_version": matcher_version,
        "schema_version": {
            "tracking_artifact": tracking_schema,
            "migrations": migration_set_identity(),
        },
    }


# ---------------------------------------------------------------------------
# In-repo gates: things this process can genuinely verify
# ---------------------------------------------------------------------------

def check_release_sha(sha: str | None) -> dict:
    """The release must be a real, unambiguous, committed SHA."""
    if not sha:
        return _gate("release_sha", FAIL, "no --release-sha supplied",
                     reason="candidate_not_frozen")
    if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha.lower()):
        return _gate("release_sha", FAIL,
                     f"not a full 40-hex commit sha: {sha!r} "
                     "(short shas and tags are ambiguous)",
                     reason="candidate_ambiguous")
    try:
        subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                       cwd=_REPO, check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return _gate("release_sha", FAIL, f"sha not present in this repository: {sha}",
                     reason="candidate_unresolvable")
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
                     "gathered here would not describe the release sha",
                     reason="worktree_dirty")
    if sha and head.lower() != sha.lower():
        return _gate("worktree", FAIL,
                     f"HEAD {head[:8]} != release sha {sha[:8]}: local evidence "
                     "would come from different code",
                     reason="sha_mismatch")
    return _gate("worktree", PASS, "clean worktree at the release sha", {"head": head})


def check_corpus_floor(min_records: int) -> dict:
    """A corpus that is present but empty passes shape checks vacuously."""
    shard_dir = _REPO / "data" / "processed" / "shards"
    if not shard_dir.is_dir():
        return _gate("corpus", FAIL, "data/processed/shards is missing",
                     reason="corpus_absent")
    shards = sorted(shard_dir.glob("*.json"))
    if not shards:
        return _gate("corpus", FAIL, "no shards present", reason="corpus_absent")
    total = 0
    for shard in shards:
        try:
            with shard.open(encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return _gate("corpus", FAIL, f"{shard.name} unreadable: {exc}",
                         reason="corpus_unreadable")
        if not isinstance(payload, list):
            return _gate("corpus", FAIL, f"{shard.name} is not a record list",
                         reason="corpus_malformed")
        total += len(payload)
    if total < min_records:
        return _gate("corpus", FAIL,
                     f"{total} records below floor {min_records}: the data-quality "
                     "gate would pass vacuously on a corpus this small",
                     {"records": total, "shards": len(shards)},
                     reason="corpus_below_floor")
    return _gate("corpus", PASS, f"{total} records across {len(shards)} shards",
                 {"records": total, "shards": len(shards)})


# Resolved against ``_REPO`` at call time, not import time, so a test can
# repoint the whole tree at a fixture directory (``monkeypatch.setattr(gate,
# "_REPO", tmp_path)``) instead of asserting against whatever the committed
# artifacts happen to look like today. Binding these at import would silently
# read the real corpus while the test believed it had substituted one.
def _tracking_path() -> Path:
    return _REPO / "data" / "processed" / "professor_tracking.json"


# Overridable for the same reason as the drill directory below: the ledger for
# a candidate is generated AFTER it, so it cannot exist inside that commit's
# tree, while check_worktree_clean requires HEAD to equal the release SHA. CI
# reads it from the default branch and points this here.
_LEDGER_PATH_OVERRIDE: Path | None = None


def _ledger_path() -> Path:
    return _LEDGER_PATH_OVERRIDE or (_REPO / "data" / "releases" / "CURRENT.json")


# Overridable for the same reason the operator evidence file is read from the
# default branch rather than the checkout: a drill is recorded AFTER the
# candidate it vouches for, so it cannot exist inside that commit, while
# check_worktree_clean requires HEAD to equal the release SHA.
_DRILL_DIR_OVERRIDE: Path | None = None


def _drill_dir() -> Path:
    return _DRILL_DIR_OVERRIDE or (_REPO / "data" / "releases" / "drills")


def _tracking_release_block() -> tuple[dict | None, str | None]:
    if not _tracking_path().exists():
        return None, "artifact absent"
    try:
        sys.path.insert(0, str(_REPO))
        from src.tracking.professor_profiles import (  # noqa: PLC0415
            load_tracking_state,
        )

        state = load_tracking_state(_tracking_path())
    except Exception as exc:  # noqa: BLE001
        return None, f"could not evaluate: {exc}"
    block = (state or {}).get("release")
    if not isinstance(block, dict):
        return None, "artifact carries no release block"
    return block, None


def check_tracking_freshness() -> dict:
    """Professor-tracking baseline freshness against the project's approved 95% floor.

    The threshold and the TTL are read from the producer
    (``src.tracking.professor_profiles``) rather than restated here, so this
    gate cannot drift away from the contract the artifact is written against.

    The percentage is RECOMPUTED from the stored numerator and denominator
    rather than trusted, and the denominator is required to be the active
    corpus count the producer was handed. That closes the three ways this
    number normally improves without anything improving: editing the percent,
    counting only the professors that happen to be tracked, and dropping the
    schools that failed. ``fresh`` itself only advances on a strictly-newer
    real profile fetch, so an attempted-but-failed refresh cannot move it.
    """
    block, err = _tracking_release_block()
    if block is None:
        return _gate("tracking_freshness", UNVERIFIED,
                     f"freshness cannot be established: {err}",
                     reason="artifact_unreadable")
    try:
        sys.path.insert(0, str(_REPO))
        from src.tracking.professor_profiles import (  # noqa: PLC0415
            FRESHNESS_MIN_PCT,
            FRESHNESS_TTL_DAYS,
        )
    except Exception as exc:  # noqa: BLE001
        return _gate("tracking_freshness", UNVERIFIED,
                     f"freshness threshold unreadable: {exc}",
                     reason="threshold_unreadable")

    fresh = block.get("fresh_profiles")
    total = block.get("total_profiles")
    expected = block.get("expected_profile_count")
    stored_pct = block.get("freshness_pct")
    fully_stale = block.get("fully_stale_school_count")
    computed_at = block.get("computed_at")
    age = _age_days(computed_at)

    evidence = {
        "freshness_percent": None,
        "freshness_threshold": FRESHNESS_MIN_PCT,
        "freshness_ttl_days": FRESHNESS_TTL_DAYS,
        "fresh_profiles": fresh,
        "total_profiles": total,
        "expected_profile_count": expected,
        "stored_freshness_pct": stored_pct,
        "fully_stale_school_count": fully_stale,
        "fully_stale_schools": (block.get("fully_stale_schools") or [])[:20],
        "computed_at": computed_at,
        "computed_age_days": round(age, 2) if age is not None else None,
    }

    if not isinstance(fresh, int) or not isinstance(total, int) or total <= 0:
        return _gate("tracking_freshness", UNVERIFIED,
                     "artifact carries no usable fresh/total counts, so freshness "
                     "has no denominator and cannot be vacuously satisfied",
                     evidence, reason="denominator_absent")
    if not isinstance(expected, int) or expected != total:
        # The producer records the ACTIVE corpus count separately. If the
        # denominator is not that number, the artifact is measuring the subset
        # it already tracks — a shrunken denominator, which is the classic way
        # this percentage improves while coverage does not.
        return _gate("tracking_freshness", FAIL,
                     f"denominator {total} is not the active corpus count "
                     f"{expected!r}: freshness computed over a shrunken population "
                     "is not freshness",
                     evidence, reason="denominator_shrunk")

    actual_pct = 100.0 * fresh / total
    evidence["freshness_percent"] = round(actual_pct, 2)
    if isinstance(stored_pct, int | float) and abs(float(stored_pct) - actual_pct) > 0.05:
        return _gate("tracking_freshness", FAIL,
                     f"stored freshness_pct {stored_pct} does not match "
                     f"{fresh}/{total} = {actual_pct:.2f}%: the recorded number was "
                     "not produced by the recorded counts",
                     evidence, reason="freshness_inconsistent")
    if age is None:
        return _gate("tracking_freshness", UNVERIFIED,
                     "artifact has no parseable computed_at, so the currency of this "
                     "freshness reading cannot be established",
                     evidence, reason="evidence_undated")
    if age > FRESHNESS_TTL_DAYS:
        return _gate("tracking_freshness", FAIL,
                     f"freshness was computed {age:.1f}d ago, beyond the "
                     f"{FRESHNESS_TTL_DAYS}d TTL: it describes a corpus that has "
                     "since moved",
                     evidence, reason="evidence_stale")
    if actual_pct < FRESHNESS_MIN_PCT:
        return _gate("tracking_freshness", FAIL,
                     f"{actual_pct:.2f}% of {total} active professor records are "
                     f"profile-verified within {FRESHNESS_TTL_DAYS}d, below the "
                     f"{FRESHNESS_MIN_PCT}% floor",
                     evidence, reason="below_threshold")
    if fully_stale:
        return _gate("tracking_freshness", FAIL,
                     f"{fully_stale} school(s) have no fresh baseline at all: "
                     f"{', '.join(evidence['fully_stale_schools'][:10])}",
                     evidence, reason="fully_stale_schools")
    return _gate("tracking_freshness", PASS,
                 f"{actual_pct:.2f}% >= {FRESHNESS_MIN_PCT}% across {total} active "
                 "records, no fully-stale school", evidence)
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
        return _gate("no_fully_stale_school", CANNOT_VERIFY,
                     "source_health.json absent: per-source freshness unknown. "
                     "corpus_freshness above still answers the record-level "
                     "question from the shards themselves",
                     reason="ledger_absent")
    try:
        sys.path.insert(0, str(_REPO))
        from src.collectors import source_health  # noqa: PLC0415
        report = source_health.corpus_report(source_health.load_ledger(path))
    except Exception as exc:  # noqa: BLE001
        return _gate("no_fully_stale_school", CANNOT_VERIFY,
                     f"could not evaluate: {exc}", reason="ledger_unreadable")
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


# The corpus-freshness bound and floor are both existing project constants,
# imported rather than restated: GRACE_DAYS is what deactivate_stale_faculty
# already treats as "unseen for two missed weekly deep runs", and
# FRESHNESS_MIN_PCT is the percentage floor the tracking contract was written
# against. Re-declaring either here would let the gate drift away from the
# pipeline it is judging.
def corpus_freshness_policy() -> tuple[float, float]:
    """``(min_percent, stale_days)`` for corpus-record freshness."""
    sys.path.insert(0, str(_REPO))
    from src.normalizers.deactivate_stale_faculty import (  # noqa: PLC0415
        GRACE_DAYS,
    )
    from src.tracking.professor_profiles import (  # noqa: PLC0415
        FRESHNESS_MIN_PCT,
    )

    return float(FRESHNESS_MIN_PCT), float(GRACE_DAYS)


def corpus_freshness_report(now: datetime | None = None) -> dict:
    """Record-level freshness of the committed corpus, computed from the shards.

    This reads what actually shipped: every record's own ``last_seen_at``, the
    stamp a collector writes only when it really re-observed that record. A
    run that executed and fetched nothing moves no stamp, so an attempted
    refresh cannot raise this number — which is the property the whole gate
    depends on.

    Deactivated records are excluded from BOTH sides of the ratio. They are
    not stale data being served; they are data the pipeline has already
    retired, and counting them as stale would report a working deactivation
    pass as a freshness failure.
    """
    now = now or _now()
    min_pct, stale_days = corpus_freshness_policy()
    cutoff = now - timedelta(days=stale_days)

    shard_dir = _REPO / "data" / "processed" / "shards"
    if not shard_dir.is_dir():
        raise FileNotFoundError("data/processed/shards is missing")

    active = fresh = inactive = 0
    schools: dict[str, dict] = {}
    for path in sorted(shard_dir.glob("*.json")):
        school = path.stem
        with path.open(encoding="utf-8") as handle:
            records = json.load(handle)
        row = {"active": 0, "fresh": 0, "last_seen_at": None}
        for record in records:
            meta = record.get("metadata") or {}
            if not meta.get("is_active"):
                inactive += 1
                continue
            row["active"] += 1
            seen = _parse_stamp(meta.get("last_seen_at"))
            if seen is not None and (row["last_seen_at"] is None
                                     or seen > row["last_seen_at"]):
                row["last_seen_at"] = seen
            if seen is not None and seen >= cutoff:
                row["fresh"] += 1
        active += row["active"]
        fresh += row["fresh"]
        schools[school] = row

    def _state(row: dict) -> str:
        if row["active"] == 0:
            return "no_active_records"
        if row["fresh"] == row["active"]:
            return "fully_fresh"
        return "partially_stale" if row["fresh"] else "fully_stale"

    states = {name: _state(row) for name, row in schools.items()}
    fully_stale = sorted(n for n, st in states.items() if st == "fully_stale")
    return {
        "generated_at": now.isoformat(),
        "freshness_percent": round(100.0 * fresh / active, 2) if active else None,
        "freshness_threshold": min_pct,
        "stale_days": stale_days,
        "active_records": active,
        "fresh_records": fresh,
        "stale_records": active - fresh,
        "inactive_records": inactive,
        "school_count": len(schools),
        "fully_fresh_school_count": sum(1 for v in states.values() if v == "fully_fresh"),
        "partially_stale_school_count": sum(
            1 for v in states.values() if v == "partially_stale"),
        "fully_stale_school_count": len(fully_stale),
        "fully_stale_schools": fully_stale,
        "no_active_record_school_count": sum(
            1 for v in states.values() if v == "no_active_records"),
        "schools": {
            name: {
                "active": row["active"],
                "fresh": row["fresh"],
                "state": states[name],
                "last_seen_at": (row["last_seen_at"].isoformat()
                                 if row["last_seen_at"] else None),
            }
            for name, row in schools.items()
        },
    }


def check_corpus_freshness() -> dict:
    """Corpus freshness against the configured floor. Always applicable.

    This is the gate the release requirement actually names, and it does not
    depend on any feature flag: every student-facing surface reads the corpus,
    so a corpus that has stopped refreshing is a release problem no matter
    which optional features are open.

    It is deliberately separate from ``tracking_freshness``. Those two numbers
    measure different populations — this one, whether the records we serve were
    re-observed recently; that one, whether professor-tracking baselines exist
    and are current. Reporting either as "freshness" without saying which is
    how a 34.8% coverage gap and a 91.2% corpus reading got read as the same
    fact.
    """
    try:
        report = corpus_freshness_report()
    except Exception as exc:  # noqa: BLE001
        return _gate("corpus_freshness", CANNOT_VERIFY,
                     f"corpus freshness could not be computed: {exc}",
                     reason="corpus_unreadable")

    evidence = {k: v for k, v in report.items() if k != "schools"}
    evidence["fully_stale_schools"] = report["fully_stale_schools"][:20]
    evidence["worst_schools"] = sorted(
        ({"school": name, **row} for name, row in report["schools"].items()
         if row["state"] != "fully_fresh"),
        key=lambda r: (r["fresh"] - r["active"]),
    )[:15]

    pct = report["freshness_percent"]
    threshold = report["freshness_threshold"]
    if pct is None:
        return _gate("corpus_freshness", CANNOT_VERIFY,
                     "no active records: freshness has no denominator and must "
                     "not be read as satisfied",
                     evidence, reason="denominator_absent")

    failures = []
    if pct < threshold:
        failures.append(
            f"{pct:.2f}% of {report['active_records']:,} active records were "
            f"re-observed within {report['stale_days']:.0f}d, below the "
            f"{threshold}% floor")
    if report["fully_stale_school_count"]:
        failures.append(
            f"{report['fully_stale_school_count']} school(s) have no fresh "
            f"record at all: {', '.join(report['fully_stale_schools'][:10])}")
    if failures:
        return _gate("corpus_freshness", FAIL, "; ".join(failures), evidence,
                     reason="below_threshold" if pct < threshold
                     else "fully_stale_schools")
    return _gate("corpus_freshness", PASS,
                 f"{pct:.2f}% >= {threshold}% across "
                 f"{report['active_records']:,} active records, "
                 f"no fully-stale school", evidence)


def check_tracking_release_ready() -> dict:
    """The professor-tracking artifact's own strict release contract."""
    if not _tracking_path().exists():
        return _gate("tracking_release_ready", UNVERIFIED, "artifact absent",
                     reason="artifact_absent")
    try:
        sys.path.insert(0, str(_REPO))
        from src.tracking.professor_profiles import (  # noqa: PLC0415
            artifact_release_ready,
            load_tracking_state,
        )

        state = load_tracking_state(_tracking_path())
    except Exception as exc:  # noqa: BLE001 — any import/parse issue is unverified
        return _gate("tracking_release_ready", UNVERIFIED, f"could not evaluate: {exc}",
                     reason="artifact_unreadable")
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
            {"stored_release_ready": block.get("release_ready"), "failing": failing,
             "freshness_pct": block.get("freshness_pct"),
             "fully_stale_school_count": block.get("fully_stale_school_count"),
             "computed_at": block.get("computed_at")},
            reason="artifact_contract_unmet",
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
        return _gate("truthfulness", UNVERIFIED, "no truthfulness report",
                     reason="evidence_absent")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _gate("truthfulness", UNVERIFIED, f"unreadable: {exc}",
                     reason="evidence_unreadable")
    decision = payload.get("decision")
    generated = payload.get("generated_at")
    age_days = _age_days(generated)
    evidence = {"decision": decision, "generated_at": generated, "age_days": age_days}
    if decision != "GO":
        return _gate("truthfulness", FAIL, f"decision={decision!r}", evidence,
                     reason="check_failed")
    if age_days is None:
        return _gate("truthfulness", UNVERIFIED,
                     "GO but generated_at is missing/unparseable, so its currency "
                     "cannot be established", evidence, reason="evidence_undated")
    if age_days > TRUTHFULNESS_MAX_AGE_DAYS:
        return _gate("truthfulness", FAIL,
                     f"GO but {age_days:.1f}d old (max {TRUTHFULNESS_MAX_AGE_DAYS}d): "
                     "a human audit predating the corpus is not evidence about it",
                     evidence, reason="evidence_stale")
    return _gate("truthfulness", PASS, f"GO, {age_days:.1f}d old", evidence)


def check_ledger_currency(sha: str | None, *, refreshing: bool = False) -> dict:
    """The committed ledger must describe THIS candidate.

    Nothing in the pipeline consumes ``CURRENT.json`` to reach a verdict — the
    gate always recomputes — but humans do, and on 2026-09-03 it was 20 days
    and 127 commits behind while still reading as the project's release
    posture. A stale ledger is stale evidence whether or not a machine trusts
    it, so it is checked like any other evidence.

    ``refreshing`` is what keeps this from being unsatisfiable. A ledger is
    written AFTER the candidate it describes, so the copy sitting in the
    candidate's own tree always describes an earlier commit — this gate would
    fail forever on a tip candidate no matter what anyone did. When the run is
    itself regenerating the ledger (``--update-current``), the statement "the
    committed ledger describes this candidate" is made true by the run, so it
    passes on that basis and says so. Every other run — CI dispatch, an
    operator re-checking an older SHA — still reads a real file, which is
    where a stale ledger actually gets caught.
    """
    if refreshing:
        return _gate("ledger_currency", PASS,
                     "regenerated by this run against the candidate "
                     f"({sha[:8] if sha else 'unspecified'})",
                     {"refreshed": True, "path": str(_ledger_path())})
    if not _ledger_path().exists():
        return _gate("ledger_currency", UNVERIFIED,
                     f"no committed ledger at {_ledger_path().name}",
                     reason="evidence_absent")
    try:
        payload = json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _gate("ledger_currency", UNVERIFIED, f"unreadable: {exc}",
                     reason="evidence_unreadable")
    ledger_sha = payload.get("release_sha")
    generated = payload.get("generated_at")
    age = _age_days(generated)
    evidence = {"ledger_release_sha": ledger_sha, "candidate_release_sha": sha,
                "generated_at": generated,
                "age_days": round(age, 2) if age is not None else None,
                "final_decision": payload.get("final_decision")}
    if sha and str(ledger_sha or "").lower() != sha.lower():
        behind = _git("rev-list", "--count", f"{ledger_sha}..{sha}") if ledger_sha else None
        evidence["commits_behind"] = behind
        return _gate("ledger_currency", FAIL,
                     f"committed ledger describes {str(ledger_sha)[:8]}, candidate is "
                     f"{sha[:8]}"
                     + (f" ({behind} commits behind)" if behind else "")
                     + ": a verdict from another SHA is not evidence about this one",
                     evidence, reason="sha_mismatch")
    if age is None:
        return _gate("ledger_currency", UNVERIFIED,
                     "committed ledger has no parseable generated_at",
                     evidence, reason="evidence_undated")
    if age > LEDGER_MAX_AGE_DAYS:
        return _gate("ledger_currency", FAIL,
                     f"committed ledger is {age:.1f}d old (max {LEDGER_MAX_AGE_DAYS}d): "
                     "regenerate it against the candidate",
                     evidence, reason="evidence_stale")
    return _gate("ledger_currency", PASS,
                 f"committed ledger describes {sha[:8] if sha else 'this candidate'}, "
                 f"{age:.1f}d old", evidence)


def load_latest_drill() -> tuple[dict | None, str | None]:
    """Most recent restore-drill record on disk, by ``performed_at``."""
    if not _drill_dir().is_dir():
        return None, "no restore-drill record has ever been filed"
    records: list[tuple[datetime, dict]] = []
    for path in sorted(_drill_dir().glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        stamp = _parse_stamp(payload.get("performed_at"))
        records.append((stamp or datetime.min.replace(tzinfo=UTC), payload))
    if not records:
        return None, "no restore-drill record has ever been filed"
    records.sort(key=lambda pair: pair[0])
    return records[-1][1], None


_DRILL_VALIDATIONS = ("schema_validation", "data_validation", "rls_validation",
                      "application_smoke")


def check_restore_drill(migrations: dict | None = None) -> dict:
    """A recorded, successful, schema-matched restore drill.

    Backups here are Supabase daily physicals with no PITR, and every one of
    the committed migrations is forward-only — so a restore is the ONLY
    recovery path from a bad migration. That makes an untested backup the one
    assumption with nothing behind it, which is why the absence of a drill is
    UNVERIFIED-and-blocking rather than a warning.

    The drill is bound to the schema state it restored: migrations only move
    forward, so a drill taken before new ones landed is not evidence about
    recovering to today's target.
    """
    expected = migrations if migrations is not None else migration_set_identity()
    record, err = load_latest_drill()
    if record is None:
        return _gate("restore_drill", BLOCKED,
                     f"{err}: recovery capability is assumed, not proven. The "
                     "drill needs an isolated scratch Supabase project, which is "
                     "a provisioning decision, not a task anyone here can do "
                     "(docs/DISASTER_RECOVERY.md §2, §5)",
                     {"expected_schema_version": expected,
                      "required_access": "scratch Supabase project + management "
                                         "access authorised by the project owner"},
                     reason="scratch_project_access_required")

    drill_id = record.get("drill_id")
    result = str(record.get("final_result") or "").upper()
    performed = record.get("performed_at")
    age = _age_days(performed)
    restored_schema = record.get("restored_schema_version")
    validations = {k: str(record.get(k) or "").upper() for k in _DRILL_VALIDATIONS}
    evidence = {
        "drill_id": drill_id,
        "performed_at": performed,
        "age_days": round(age, 2) if age is not None else None,
        "source_backup_id": record.get("source_backup_id"),
        "source_environment": record.get("source_environment"),
        "scratch_environment": record.get("scratch_environment"),
        "source_schema_version": record.get("source_schema_version"),
        "restored_schema_version": restored_schema,
        "expected_schema_version": expected,
        "validations": validations,
        "issues_found": record.get("issues_found"),
        "final_result": result or None,
    }

    if not drill_id:
        return _gate("restore_drill", UNVERIFIED,
                     "drill record carries no drill_id, so it cannot be traced back "
                     "to a run", evidence, reason="evidence_untraceable")
    if not record.get("source_backup_id"):
        return _gate("restore_drill", UNVERIFIED,
                     "drill record names no source_backup_id: a restore that cannot "
                     "name what it restored proves nothing about the backups",
                     evidence, reason="backup_unidentified")
    if age is None:
        return _gate("restore_drill", UNVERIFIED,
                     "drill record has no parseable performed_at",
                     evidence, reason="evidence_undated")
    if result == FAIL:
        return _gate("restore_drill", FAIL,
                     f"drill {drill_id} failed: "
                     f"{record.get('issues_found') or 'see the drill record'}",
                     evidence, reason="drill_failed")
    if result != PASS:
        return _gate("restore_drill", UNVERIFIED,
                     f"drill {drill_id} recorded final_result="
                     f"{record.get('final_result')!r}, which is not a pass",
                     evidence, reason="drill_inconclusive")
    failed = sorted(k for k, v in validations.items() if v != PASS)
    if failed:
        return _gate("restore_drill", FAIL,
                     f"drill {drill_id} reports final_result=PASS but "
                     f"{', '.join(failed)} did not pass: the summary disagrees with "
                     "its own steps", evidence, reason="drill_internally_inconsistent")
    if age > RESTORE_DRILL_MAX_AGE_DAYS:
        return _gate("restore_drill", FAIL,
                     f"drill {drill_id} is {age:.1f}d old (max "
                     f"{RESTORE_DRILL_MAX_AGE_DAYS}d): re-run it rather than citing a "
                     "stale row", evidence, reason="evidence_stale")
    if restored_schema is None:
        return _gate("restore_drill", UNVERIFIED,
                     "drill record names no restored_schema_version, so it cannot be "
                     "bound to a recovery target", evidence,
                     reason="schema_state_unknown")
    if isinstance(restored_schema, dict) and isinstance(expected, dict) \
            and restored_schema.get("digest") != expected.get("digest"):
        return _gate("restore_drill", UNVERIFIED,
                     f"drill {drill_id} restored migration set "
                     f"{restored_schema.get('head')} "
                     f"({restored_schema.get('count')} files); the candidate targets "
                     f"{expected.get('head')} ({expected.get('count')}). Forward-only "
                     "migrations mean that drill is not evidence about this recovery "
                     "target", evidence, reason="schema_state_advanced")
    return _gate("restore_drill", PASS,
                 f"drill {drill_id} restored {record.get('source_backup_id')} into "
                 f"{record.get('scratch_environment')} and validated schema, data, "
                 f"RLS and application reads ({age:.1f}d ago)", evidence)


def check_open_incidents(evidence: dict | None) -> dict:
    """Unresolved operational incidents block a release.

    The queue lives in Supabase, which this process cannot reach, so the
    count must be supplied as evidence from an authenticated admin call.
    """
    if not evidence:
        return _gate("open_incidents", BLOCKED,
                     "no incident rollup supplied and none can be: "
                     "GET /api/admin/ops/incidents?unresolved_only=true needs "
                     "ADMIN_TOKEN", reason="access_required")
    stale = _stale_evidence("open_incidents", evidence)
    if stale is not None:
        return stale
    rollup = evidence.get("rollup") or {}
    total = rollup.get("open_total")
    if not isinstance(total, int):
        return _gate("open_incidents", UNVERIFIED, "rollup.open_total absent",
                     reason="evidence_incomplete")
    if rollup.get("truncated"):
        return _gate("open_incidents", UNVERIFIED,
                     "rollup truncated: a capped count cannot prove zero",
                     reason="evidence_truncated")
    if total > 0:
        return _gate("open_incidents", FAIL, f"{total} unresolved incident(s)",
                     {"open_by_kind": rollup.get("open_by_kind"),
                      "observed_at": evidence.get("observed_at")},
                     reason="check_failed")
    return _gate("open_incidents", PASS, "no unresolved incidents", rollup)


def check_flag_parity() -> dict:
    """Backend and frontend release-scope flags must not drift apart."""
    be = _REPO / "backend" / "lib" / "release_scope.py"
    fe = _REPO / "frontend" / "src" / "lib" / "release-scope.ts"
    if not be.exists() or not fe.exists():
        return _gate("flag_parity", UNVERIFIED, "release-scope module missing",
                     reason="evidence_absent")
    import re  # noqa: PLC0415

    be_keys = set(re.findall(r'"([a-z0-9_]+)"\s*:\s*(?:True|False)', be.read_text()))
    fe_keys = {
        re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
        for k in re.findall(r"^\s*([a-zA-Z0-9]+)\s*:\s*(?:true|false)",
                            fe.read_text(), re.MULTILINE)
    }
    if not be_keys or not fe_keys:
        return _gate("flag_parity", UNVERIFIED, "could not parse flag tables",
                     reason="evidence_unreadable")
    only_be = sorted(be_keys - fe_keys)
    only_fe = sorted(fe_keys - be_keys)
    if only_be or only_fe:
        # Frontend-only flags mean a surface with no server-side gate.
        return _gate("flag_parity", FAIL,
                     f"flag drift — backend-only: {only_be or 'none'}, "
                     f"frontend-only (ungated server-side): {only_fe or 'none'}",
                     {"backend_only": only_be, "frontend_only": only_fe},
                     reason="flag_drift")
    return _gate("flag_parity", PASS, f"{len(be_keys)} flags aligned")


def required_providers(scope: dict[str, bool] | None) -> tuple[list[str], list[str]]:
    """``(required, not_applicable)`` providers under the current flag table.

    A provider stops blocking only when EVERY feature requiring it is off.
    ``llm`` is the case that makes the rule worth writing down: ask_ai is
    closed, but resume_renovate is accepted and shares the same key, so a
    missing LLM key still blocks.
    """
    required: list[str] = []
    not_applicable: list[str] = []
    for provider, features in _PROVIDER_REQUIRED_BY.items():
        named = [f for f in features if f]
        if any(f is None for f in features):
            required.append(provider)
        elif scope is None or any(f not in scope for f in named):
            required.append(provider)  # unknown flag state fails safe
        elif any(scope[f] for f in named):
            required.append(provider)
        else:
            not_applicable.append(provider)
    return sorted(required), sorted(not_applicable)


def check_providers(evidence: dict | None, scope: dict[str, bool] | None) -> dict:
    """Provider readiness, mapped to the features that actually require it."""
    required, not_applicable = required_providers(scope)
    summary = {"required_providers": required,
               "not_applicable_providers": not_applicable,
               "flag_state": "unknown" if scope is None else "known"}
    if not evidence:
        return _gate("provider_readiness", BLOCKED,
                     "no provider report supplied and none can be: GET /api/ready "
                     "-> reported.providers needs X-Admin-Token",
                     summary, reason="access_required")
    stale = _stale_evidence("provider_readiness", evidence)
    if stale is not None:
        return stale
    reported = evidence.get("providers") or {}
    missing: list[str] = []
    unreported: list[str] = []
    for provider in required:
        got = reported.get(provider)
        status = got.get("status") if isinstance(got, dict) else got
        if status is None:
            unreported.append(provider)
        elif str(status).lower() not in {"configured", "present", "ok", "pass"}:
            missing.append(provider)
    summary["reported"] = {k: (v.get("status") if isinstance(v, dict) else v)
                           for k, v in reported.items()}
    if unreported:
        return _gate("provider_readiness", UNVERIFIED,
                     f"required provider(s) not reported: {', '.join(unreported)}",
                     summary, reason="evidence_incomplete")
    if missing:
        return _gate("provider_readiness", FAIL,
                     f"required provider(s) not configured: {', '.join(missing)} — "
                     "each is required by an enabled feature",
                     summary, reason="provider_unconfigured")
    return _gate("provider_readiness", PASS,
                 f"{len(required)} required provider(s) configured; "
                 f"{len(not_applicable)} not applicable while their features are off",
                 summary)


def check_ci_evidence(evidence: dict | None, sha: str | None) -> list[dict]:
    """Required CI checks: same SHA, all green, nothing critical skipped.

    ``scripts/verify_refresh_pr.py`` already encodes the required-check names
    and the same-SHA rule; this consumes a snapshot in that shape rather than
    inventing a second definition.

    CI evidence needs no age check: it is keyed on the commit, so a result for
    the candidate SHA cannot predate a code change to the candidate.
    """
    required = ("Backend (lint + pytest)", "Frontend (typecheck + build)",
                "Migrations (Flow B merge + CLI replay)", "E2E (Playwright)")
    if not evidence:
        return [_gate(f"ci:{name}", UNVERIFIED, "no CI evidence supplied",
                      reason="evidence_absent")
                for name in required]
    head = evidence.get("head_sha")
    checks = {c.get("name"): c for c in (evidence.get("checks") or [])}
    out: list[dict] = []
    for name in required:
        got = checks.get(name)
        if got is None:
            out.append(_gate(f"ci:{name}", NOT_RUN, "check not registered",
                             reason="required_check_not_run"))
            continue
        if sha and head and head.lower() != sha.lower():
            out.append(_gate(f"ci:{name}", FAIL,
                             f"evidence is for {head[:8]}, release is {sha[:8]}",
                             reason="sha_mismatch"))
            continue
        state = (got.get("conclusion") or got.get("state") or "").upper()
        if state in ("SKIPPED", "NEUTRAL"):
            out.append(_gate(f"ci:{name}", SKIPPED,
                             "a skipped required check is not a pass",
                             reason="required_check_skipped"))
        elif state == "SUCCESS":
            out.append(_gate(f"ci:{name}", PASS, f"green on {head[:8]}",
                             {"head_sha": head, "check_run_id": got.get("id"),
                              "url": got.get("html_url")}))
        else:
            out.append(_gate(f"ci:{name}", FAIL, f"conclusion={state or 'unknown'}",
                             reason="check_failed"))
    return out


def _stale_evidence(name: str, evidence: dict) -> dict | None:
    """``None`` if the evidence is current, else the gate that rejects it.

    Evidence describing a live observation must say when it was observed.
    Undated evidence is not treated as fresh — that assumption is the one this
    whole file exists to refuse.
    """
    limit = _EVIDENCE_MAX_AGE_DAYS.get(name)
    if limit is None:
        return None
    observed = evidence.get("observed_at")
    if observed is None:
        return _gate(name, UNVERIFIED,
                     "evidence carries no observed_at, so its currency cannot be "
                     f"established (max age {limit}d)",
                     evidence, reason="evidence_undated")
    age = _age_days(observed)
    if age is None:
        return _gate(name, UNVERIFIED,
                     f"observed_at {observed!r} is not a parseable timestamp",
                     evidence, reason="evidence_undated")
    if age > limit:
        return _gate(name, FAIL,
                     f"evidence was observed {age:.1f}d ago, past this gate's {limit}d "
                     "maximum age: re-gather it against the candidate",
                     evidence, reason="evidence_stale")
    return None


def check_external(name: str, evidence: dict | None, sha: str | None) -> dict:
    """A gate whose evidence must come from outside the repo."""
    if not evidence:
        blocked = name in _ACCESS_REQUIRED
        return _gate(name, _absent_status(name),
                     "no evidence supplied; this gate cannot be verified from "
                     "inside the repository and must not be assumed"
                     + (" — and cannot be gathered without access nobody here has"
                        if blocked else ""),
                     reason="access_required" if blocked else "evidence_absent")
    got_sha = evidence.get("release_sha")
    if sha and got_sha and str(got_sha).lower() != sha.lower():
        return _gate(name, FAIL,
                     f"evidence sha {str(got_sha)[:8]} != release sha {sha[:8]}",
                     evidence, reason="sha_mismatch")
    if sha and not got_sha:
        return _gate(name, UNVERIFIED, "evidence carries no release_sha to bind it",
                     evidence, reason="evidence_unbound")
    status = str(evidence.get("status", "")).upper()
    if status == NOT_APPLICABLE:
        # An operator may declare a gate inapplicable only WITH a reason. A
        # bare "N/A" is how a real blocker gets retired without being fixed.
        why = evidence.get("reason")
        if not why:
            return _gate(name, UNVERIFIED,
                         "evidence claims NOT_APPLICABLE without a reason; an "
                         "unexplained exemption is not an exemption",
                         evidence, reason="exemption_unexplained")
        return _gate(name, NOT_APPLICABLE,
                     str(evidence.get("detail") or f"declared not applicable: {why}"),
                     evidence, reason=str(why))
    stale = _stale_evidence(name, evidence)
    if stale is not None:
        return stale
    if status != PASS:
        return _gate(name, FAIL if status else UNVERIFIED,
                     f"status={status or 'absent'}", evidence,
                     reason="check_failed" if status else "evidence_incomplete")
    return _gate(name, PASS, str(evidence.get("detail") or "evidence supplied"),
                 evidence)


# ---------------------------------------------------------------------------

def build_ledger(sha: str | None, evidence: dict, *, min_records: int,
                 refreshing: bool = False) -> dict:
    scope = load_release_scope()
    migrations = migration_set_identity()
    gates: list[dict] = [
        check_release_sha(sha),
        check_worktree_clean(sha),
        check_ledger_currency(sha, refreshing=refreshing),
        check_corpus_floor(min_records),
        check_corpus_freshness(),
        check_no_fully_stale_school(),
        check_tracking_freshness(),
        check_tracking_release_ready(),
        check_truthfulness(),
        check_open_incidents(evidence.get("open_incidents")),
        check_flag_parity(),
        check_providers(evidence.get("provider_readiness"), scope),
        check_restore_drill(migrations),
        *check_ci_evidence(evidence.get("ci"), sha),
        *(check_external(name, evidence.get(name), sha) for name in _EXTERNAL_GATES),
        check_external("api_ready", evidence.get("api_ready"), sha),
        check_external("promotion", evidence.get("promotion"), sha),
        check_external("rollback", evidence.get("rollback"), sha),
        check_external("scheduler", evidence.get("scheduler"), sha),
    ]
    gates = [apply_applicability(g, scope) for g in gates]
    blocking = [g for g in gates if g["status"] in _BLOCKING]

    def _find(name: str) -> dict:
        return next((g for g in gates if g["gate"] == name), {})

    def _reported(name: str) -> dict:
        """A gate's numbers, even when applicability moved it out of the way."""
        found = _find(name)
        ev = found.get("evidence") or {}
        if found.get("status") == NOT_APPLICABLE:
            ev = ((ev.get("would_be") or {}).get("evidence")) or {}
        return ev

    corpus_ev = _reported("corpus_freshness")
    fresh_ev = _reported("tracking_freshness")
    drill_gate = _find("restore_drill")
    drill_ev = drill_gate.get("evidence") or {}

    return {
        "release_sha": sha,
        "generated_at": _now_iso(),
        "gate_version": "release-gate-v2",
        "candidate": candidate_identity(sha),
        "feature_flag_states": scope if scope is not None else "UNKNOWN",
        "gates": gates,
        "summary": {
            "passed": sum(1 for g in gates if g["status"] == PASS),
            "failed": sum(1 for g in gates if g["status"] == FAIL),
            "blocked": sum(1 for g in gates if g["status"] == BLOCKED),
            "cannot_verify": sum(1 for g in gates if g["status"] == CANNOT_VERIFY),
            "unverified": sum(1 for g in gates if g["status"] == UNVERIFIED),
            "skipped": sum(1 for g in gates if g["status"] == SKIPPED),
            "not_run": sum(1 for g in gates if g["status"] == NOT_RUN),
            "not_applicable": sum(1 for g in gates if g["status"] == NOT_APPLICABLE),
            "release_blocking": len(blocking),
        },
        # The named fields a reader looks for without walking the gate list.
        "release_gate_status": "GO" if not blocking else "NO-GO",
        "tracking_release_ready": _find("tracking_release_ready").get("status"),
        # The release requirement. Always applicable, always measured.
        "freshness_percent": corpus_ev.get("freshness_percent"),
        "freshness_threshold": corpus_ev.get("freshness_threshold"),
        "fully_stale_school_count": corpus_ev.get("fully_stale_school_count"),
        "fully_stale_schools": corpus_ev.get("fully_stale_schools"),
        "stale_records": corpus_ev.get("stale_records"),
        "active_records": corpus_ev.get("active_records"),
        # A different population, kept under its own name so the two can never
        # be confused for one number again.
        "tracking_freshness_percent": fresh_ev.get("freshness_percent"),
        "tracking_fully_stale_school_count": fresh_ev.get("fully_stale_school_count"),
        "backend_test_status": _find("ci:Backend (lint + pytest)").get("status"),
        "frontend_test_status": _find("ci:Frontend (typecheck + build)").get("status"),
        "migration_status": _find(
            "ci:Migrations (Flow B merge + CLI replay)").get("status"),
        "e2e_status": _find("ci:E2E (Playwright)").get("status"),
        "backup_status": _find("backup").get("status"),
        "restore_drill_status": drill_gate.get("status"),
        "restore_drill_id": drill_ev.get("drill_id"),
        "provider_readiness": _find("provider_readiness").get("status"),
        "not_applicable_gates": [
            {"gate": g["gate"], "reason": g.get("reason"), "detail": g["detail"]}
            for g in gates if g["status"] == NOT_APPLICABLE
        ],
        "blocking_reasons": [f"{g['gate']}: {g['detail']}" for g in blocking],
        "blockers": [
            {"check": g["gate"], "status": g["status"], "reason": g.get("reason"),
             "release_blocking": True, "owner": g.get("owner"),
             "recommended_action": g.get("recommended_action"),
             "last_checked_at": g.get("last_checked_at")}
            for g in blocking
        ],
        "final_decision": "GO" if not blocking else "NO-GO",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release-sha", help="full 40-hex commit sha being released")
    ap.add_argument("--evidence", action="append", default=[],
                    help="JSON file of external gate evidence (repeatable)")
    ap.add_argument("--out", type=Path, help="write the ledger here")
    ap.add_argument("--update-current", action="store_true",
                    help="also refresh data/releases/CURRENT.json from this run")
    ap.add_argument("--min-records", type=int, default=CORPUS_MIN_RECORDS)
    ap.add_argument("--ledger", type=Path,
                    help="read (and with --update-current, write) the committed "
                         "ledger here instead of data/releases/CURRENT.json — the "
                         "ledger for a candidate is generated after it, so CI "
                         "reads it from the default branch")
    ap.add_argument("--drill-dir", type=Path,
                    help="read restore-drill records from here instead of "
                         "data/releases/drills (the drill for a candidate is "
                         "recorded after it, so CI reads them from the default "
                         "branch)")
    args = ap.parse_args()

    if args.drill_dir:
        global _DRILL_DIR_OVERRIDE
        _DRILL_DIR_OVERRIDE = args.drill_dir
    if args.ledger:
        global _LEDGER_PATH_OVERRIDE
        _LEDGER_PATH_OVERRIDE = args.ledger

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

    ledger = build_ledger(args.release_sha, evidence, min_records=args.min_records,
                          refreshing=args.update_current)
    serialised = json.dumps(ledger, indent=2) + "\n"

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialised, encoding="utf-8")
    if args.update_current:
        # Refreshing CURRENT.json is what keeps check_ledger_currency honest
        # instead of permanently red: the ledger is regenerated, never edited.
        _ledger_path().parent.mkdir(parents=True, exist_ok=True)
        _ledger_path().write_text(serialised, encoding="utf-8")

    s = ledger["summary"]
    print(f"release_sha: {ledger['release_sha'] or '(none)'}")
    print()
    # Counts first, and FAIL on its own line. The previous format printed
    # "failed=0" beside nine other numbers, which read as "almost ready" while
    # a measured requirement sat under its floor.
    print(f"  PASS           {s['passed']:>3}")
    print(f"  FAIL           {s['failed']:>3}   <- measured, requirement not met")
    print(f"  BLOCKED        {s['blocked']:>3}   <- needs access nobody here has")
    print(f"  CANNOT_VERIFY  {s['cannot_verify']:>3}   <- attempted, indeterminate")
    print(f"  UNVERIFIED     {s['unverified']:>3}   <- evidence not gathered yet")
    print(f"  SKIPPED        {s['skipped']:>3}")
    print(f"  NOT_RUN        {s['not_run']:>3}")
    print(f"  NOT_APPLICABLE {s['not_applicable']:>3}   (does not block)")
    print(f"\n  release-blocking items: {s['release_blocking']}")
    if ledger.get("freshness_percent") is not None:
        print(f"  corpus freshness: {ledger['freshness_percent']}% "
              f"(floor {ledger['freshness_threshold']}%), "
              f"fully-stale schools: {ledger['fully_stale_school_count']}")
    print()
    for gate in ledger["gates"]:
        print(f"  [{gate['status']:<14}] {gate['gate']}: {gate['detail']}")
    if ledger["not_applicable_gates"]:
        print("\nnot applicable (explicitly, with reason):")
        for entry in ledger["not_applicable_gates"]:
            print(f"  - {entry['gate']}: {entry['reason']}")
    if ledger["blockers"]:
        print("\nblocking:")
        for blocker in ledger["blockers"]:
            print(f"  - {blocker['check']} [{blocker['status']}] "
                  f"({blocker['reason']}) owner={blocker['owner']}")
            print(f"      -> {blocker['recommended_action']}")
    print(f"\nDECISION: {ledger['final_decision']}")
    return 0 if ledger["final_decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
