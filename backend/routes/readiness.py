"""``GET /api/ready`` — can this process actually serve a match right now?

``/api/health`` is LIVENESS and stays exactly as it is: it answers "the event
loop is turning", it checks nothing, and three consumers depend on that
unconditional shape (the frontend's ``wakeBackend``, playwright.config's
``webServer`` gate, and ``tests/test_async_route_isolation.py``, which asserts
health answers *while* a blocking call is in flight). Nothing in this module
touches it.

READINESS is the separate question, and until now nobody asked it. ``_lifespan``
in backend/main.py swallows every warmup exception on purpose ("never let a
warmup hiccup block boot"), so a process whose corpus load failed — or that
loaded a corpus of zero records, or fitted a vectorizer against a generation it
no longer holds — boots green behind a 200 from ``/api/health`` and then answers
``/api/matches`` with an empty or wrongly-scored universe. This endpoint is the
place that notices.

WHAT GATES (any failure => HTTP 503 and ``ready: false``). Each of these is a
fact this process can observe about *itself*; none is a guess:

1. ``corpus_loaded`` — ``load_opportunities()`` returned records.
2. ``corpus_generation_published`` — the corpus version is not the cold
   sentinel. data_loader's version is the cache mtime and its initial value is
   ``0.000000``, so "never loaded" already has a distinct representation.
3. ``matcher_artifacts`` — the TF-IDF vectorizer is fitted and the ranker holds
   a similarity matrix. Without them every match falls back to a degraded path.
4. ``ranker_corpus_binding`` — those artifacts describe the corpus generation
   currently loaded, not a previous one. Checked with the NON-BLOCKING identity
   probe (``registered_corpus_identity_nowait``) on purpose: the locking variant
   would queue this probe behind an in-flight scorer, and the match executor is
   one worker with two pending slots, so a busy instance would report itself
   unready purely because it was busy.
5. ``corpus_freshness`` — the last refresh is KNOWN and within the stale bound.
   Unknown freshness is never a pass: ``corpus_last_updated_at()`` returning
   None means no signal exists, which is exactly the state a dead cron produces.

WHAT IS REPORTED BUT NEVER GATES:

* Matcher identity (``MATCHER_VERSION``, ``MATCH_CONTRACT_VERSION``). There is
  no recorded expected matcher version anywhere in this repo, so these are
  reported as the ACTIVE values and explicitly flagged as unvalidated —
  ``expected_matcher_version: null`` /
  ``matcher_version_validated: false``. Claiming a version check happened when
  nothing was compared would be the exact dishonesty this endpoint exists to
  remove.
* Providers, each ``configured``/``missing`` by env PRESENCE only. Every one is
  OPTIONAL and therefore non-gating: the product degrades by design without
  them (no LLM => no Ask AI / cold-email polish; no Resend => no digests; no
  VAPID => no web push; no ADMIN_TOKEN => the admin surface 503s itself). Gating
  on an optional provider would pull the whole API out of rotation over a
  feature that already fails cleanly on its own — an outage manufactured from a
  degraded state that was designed to be survivable.
* The professor-tracking release block, read via ops.py's cheap 64KB tail read.
  The artifact is ~31MB and parsing it to read nine booleans would be the
  biggest allocation this process makes all day. Non-gating because the feature
  is release-scoped off and already fail-closed where it is consumed
  (``artifact_release_ready``).

NOT DONE HERE, DELIBERATELY: render.yaml gets no ``healthCheckPath``. Pointing
Render's instance probe at a freshness-gating endpoint means a four-day cron
outage takes the API out of rotation — every read, for every user, because a
scraper is late. That trade (fail-closed serving vs. degraded-but-up) is an
owner decision with a real operational consequence, not a side effect this PR
should slip in. Until someone decides, ``/api/ready`` is for humans and external
monitoring, and ``/api/health`` stays the instance probe.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Header, Response

from backend.data_loader import corpus_version, load_opportunities
from backend.lib.build_info import BUILD_VERSION, release_sha
from backend.lib.corpus_freshness import (
    corpus_freshness_thresholds,
    corpus_last_updated_at,
)
from backend.lib.llm import is_configured as llm_is_configured
from backend.routes.admin import _authenticate
from backend.routes.matches import MATCH_CONTRACT_VERSION
from backend.routes.ops import _TRACKING_PATH, _read_release_block
from src.matcher import embeddings, ranker
from src.matcher.config import MATCHER_VERSION

# The producer's current required check set, imported rather than restated: a
# local copy would drift exactly the way the committed artifact already has
# (release_ready: true carrying only 5 of the 9 checks the producer now emits).
from src.tracking.professor_profiles import (
    _CURRENT_RELEASE_CHECKS as _REQUIRED_TRACKING_CHECKS,
)

router = APIRouter()
logger = logging.getLogger("ofe.readiness")

# data_loader initializes its cache mtime to 0, so this exact string means "no
# corpus generation was ever published in this process".
COLD_CORPUS_VERSION = "0.000000"

# Coarse, stable, machine-readable failure codes. Safe to expose
# unauthenticated: they name which invariant broke, never how big the corpus is,
# what is configured, or what any value contains.
REASON_CORPUS_EMPTY = "corpus_empty"
REASON_CORPUS_UNPUBLISHED = "corpus_generation_unpublished"
REASON_MATCHER_UNFITTED = "matcher_artifacts_unfitted"
REASON_SIM_MATRIX_MISSING = "similarity_matrix_missing"
REASON_RANKER_GENERATION_MISMATCH = "ranker_corpus_generation_mismatch"
REASON_FRESHNESS_UNKNOWN = "corpus_freshness_unknown"
REASON_CORPUS_STALE = "corpus_stale"
REASON_PROBE_ERROR = "readiness_probe_error"

# Non-gating advisories, same disclosure rules as the reason codes.
WARNING_CORPUS_AGING = "corpus_freshness_warn"


def _freshness() -> dict:
    """Age of the last corpus refresh against the shared warn/stale boundary.

    ``level`` is one of ``fresh`` / ``warn`` / ``stale`` / ``unknown``. Unknown
    is NOT ok: a missing or unparseable timestamp is the absence of evidence,
    and reporting the absence of evidence as freshness is how a dead cron went
    unnoticed in the first place.
    """
    warn_hours, stale_hours = corpus_freshness_thresholds()
    last_updated = corpus_last_updated_at()
    detail: dict = {
        "ok": False,
        "level": "unknown",
        "last_updated_at": last_updated,
        "age_hours": None,
        "warn_hours": warn_hours,
        "stale_hours": stale_hours,
    }
    if not last_updated:
        return detail
    try:
        age_hours = (
            datetime.now(UTC) - datetime.fromisoformat(last_updated)
        ).total_seconds() / 3600
    except (TypeError, ValueError):
        # Present but unparseable is still no usable freshness signal.
        logger.warning("readiness: unparseable corpus timestamp %r", last_updated)
        return detail

    detail["age_hours"] = round(age_hours, 2)
    if age_hours >= stale_hours:
        detail["level"] = "stale"
    elif age_hours >= warn_hours:
        detail["level"] = "warn"
        detail["ok"] = True
    else:
        detail["level"] = "fresh"
        detail["ok"] = True
    return detail


def _evaluate_gating() -> tuple[list[str], list[str], dict]:
    """Run every gating check once; return ``(reasons, warnings, checks)``.

    ``reasons`` non-empty means not ready. ``checks`` is the admin-tier detail
    and is never returned to an unauthenticated caller.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    # ONE load call, reused by the binding check below. Calling it twice would
    # stat the corpus twice and, worse, could straddle a hot reload and compare
    # one generation's identity against another's.
    corpus = load_opportunities()
    corpus_count = len(corpus)
    version = corpus_version()

    corpus_loaded_ok = corpus_count > 0
    if not corpus_loaded_ok:
        reasons.append(REASON_CORPUS_EMPTY)

    generation_ok = version != COLD_CORPUS_VERSION
    if not generation_ok:
        reasons.append(REASON_CORPUS_UNPUBLISHED)

    # Read as module attributes, never as from-imports: the fit REBINDS these
    # names, so a from-import would freeze whatever they were at boot — which is
    # precisely the unfitted state this check exists to catch.
    tfidf_fitted = embeddings._tfidf_fitted is True
    vectorizer_present = embeddings._tfidf_vectorizer is not None
    if not (tfidf_fitted and vectorizer_present):
        reasons.append(REASON_MATCHER_UNFITTED)

    sim_matrix_present = ranker._sim_matrix is not None
    if not sim_matrix_present:
        reasons.append(REASON_SIM_MATRIX_MISSING)

    # Non-blocking probe by design (see the module docstring): the locked
    # variant would make "busy" indistinguishable from "unready".
    registered = ranker.registered_corpus_identity_nowait()
    binding_ok = registered is not None and registered == id(corpus)
    if not binding_ok:
        reasons.append(REASON_RANKER_GENERATION_MISMATCH)

    freshness = _freshness()
    if freshness["level"] == "unknown":
        reasons.append(REASON_FRESHNESS_UNKNOWN)
    elif freshness["level"] == "stale":
        reasons.append(REASON_CORPUS_STALE)
    elif freshness["level"] == "warn":
        warnings.append(WARNING_CORPUS_AGING)

    checks = {
        "corpus_loaded": {
            "ok": corpus_loaded_ok,
            "gating": True,
            "opportunity_count": corpus_count,
        },
        "corpus_generation_published": {
            "ok": generation_ok,
            "gating": True,
            "corpus_version": version,
            "cold_sentinel": COLD_CORPUS_VERSION,
        },
        "matcher_artifacts": {
            "ok": tfidf_fitted and vectorizer_present and sim_matrix_present,
            "gating": True,
            "tfidf_fitted": tfidf_fitted,
            "tfidf_vectorizer_present": vectorizer_present,
            "sim_matrix_present": sim_matrix_present,
        },
        "ranker_corpus_binding": {
            "ok": binding_ok,
            "gating": True,
            # Booleans, not the id() values themselves: heap addresses are
            # useless to an operator and are not something a response should
            # hand out.
            "corpus_registered": registered is not None,
            "bound_to_current_generation": binding_ok,
            "probe": "registered_corpus_identity_nowait",
        },
        "corpus_freshness": {**freshness, "gating": True},
    }
    return reasons, warnings, checks


def _env_presence(keys: tuple[str, ...]) -> dict:
    """Presence-only status for a group of env vars — never their values.

    Follows the existing admin-surface rule (report that a secret is set, never
    what it is). Partially-configured groups report ``missing`` and name the
    absent KEYS, which is the actionable half and leaks nothing.
    """
    missing = [k for k in keys if not (os.environ.get(k) or "").strip()]
    return {
        "status": "missing" if missing else "configured",
        "requirement": "optional",
        "probe": "env_presence",
        "missing_env": missing,
    }


def _provider_report() -> dict:
    """Every provider's configuration status. ALL optional, NONE gating.

    The requirement label is not a formality: the audit behind this endpoint
    found no required provider on this service. Supabase absence degrades saved
    searches / push / orders to local-only, no LLM key hides Ask AI, no Resend
    key stops digests, no VAPID trio stops web push, no Sentry loses telemetry,
    and ADMIN_TOKEN / CRON_SECRET absence makes those surfaces refuse
    themselves. Turning any of that into a 503 would take every read for every
    user out of rotation to protect a feature that already fails cleanly.
    """
    return {
        # Data plane and token verification share the same two vars
        # (backend/lib/supabase_auth reads exactly these).
        "supabase": _env_presence(("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")),
        "llm": {
            "status": "configured" if llm_is_configured() else "missing",
            "requirement": "optional",
            # is_configured() only inspects the provider key table and returns a
            # bool. This probe must never contact a provider: a readiness check
            # that bills a completion is one nobody can afford to poll.
            "probe": "env_presence",
        },
        "resend_email": _env_presence(("RESEND_API_KEY", "RESEND_FROM_EMAIL")),
        "web_push": _env_presence(
            ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")
        ),
        "sentry": _env_presence(("SENTRY_DSN",)),
        # Surface enablement rather than an outbound integration: unset means
        # the route family answers 503/401 on its own terms.
        "admin_surface": _env_presence(("ADMIN_TOKEN",)),
        "cron_surface": _env_presence(("CRON_SECRET",)),
    }


def _tracking_release_report() -> dict:
    """The professor-tracking release block, strict view, via the tail read.

    Two numbers can disagree here and the difference matters. ``release_ready``
    as WRITTEN in the artifact is a raw boolean the producer computed against
    whatever check set existed when it ran; the STRICT verdict additionally
    requires the block to carry exactly the checks the producer requires today,
    all true. The committed artifact currently says ``release_ready: true`` while
    carrying only 5 of 9 checks, so the strict verdict is False — and the strict
    verdict is the one reported as the headline, because the consumer
    (``artifact_release_ready``) is what actually decides whether the feature may
    serve.

    Even the strict verdict here is an UPPER BOUND: the real consumer also
    validates the artifact's ``schema_version`` and the freshness expiry window,
    neither of which a 64KB tail read of the release block can see. So this can
    say "release_ready" where the consumer still refuses — never the reverse.
    """
    block, err = _read_release_block(_TRACKING_PATH)
    report: dict = {
        "gates_readiness": False,
        "verdict": "unknown",
        "strict_release_ready": False,
        "artifact_release_ready_flag": None,
        "failing_checks": [],
        "missing_checks": [],
        "unexpected_checks": [],
        "computed_at": None,
        "read_error": err,
        "strict_view_is_upper_bound": True,
    }
    if block is None:
        return report

    raw_checks = block.get("checks")
    checks = raw_checks if isinstance(raw_checks, dict) else {}
    present = set(checks)
    flag = block.get("release_ready") is True
    report["artifact_release_ready_flag"] = flag
    report["failing_checks"] = sorted(k for k, v in checks.items() if v is not True)
    report["missing_checks"] = sorted(_REQUIRED_TRACKING_CHECKS - present)
    report["unexpected_checks"] = sorted(present - _REQUIRED_TRACKING_CHECKS)
    report["computed_at"] = block.get("computed_at")
    strict = (
        flag
        and not report["failing_checks"]
        and not report["missing_checks"]
        and not report["unexpected_checks"]
    )
    report["strict_release_ready"] = strict
    report["verdict"] = "release_ready" if strict else "not_release_ready"
    return report


def _matcher_identity() -> dict:
    """Active matcher/contract identity as DATA, not as a validated assertion.

    No expected matcher version is recorded anywhere in this repo — there is no
    pinned value, no manifest, nothing to compare against. So this reports what
    is loaded and says plainly that nothing was checked. The field names carry
    that ("active_", "expected_...: null", "validated: false") so a reader
    skimming the payload cannot mistake it for a passed check.
    """
    return {
        "active_matcher_version": MATCHER_VERSION,
        "active_match_contract_version": MATCH_CONTRACT_VERSION,
        "expected_matcher_version": None,
        "matcher_version_validated": False,
        "gates_readiness": False,
    }


# Sync def, not async: FastAPI runs it in the threadpool, so a cold-cache
# corpus load inside the probe cannot stall the event loop (and cannot make
# every other request look unready). Deliberately NOT routed through
# backend.lib.blocking.run_blocking either — that executor is one worker with
# two pending slots, and queueing a probe behind a scorer is the same "busy
# reads as broken" failure the nowait identity probe avoids.
@router.get("/ready")
def readiness(
    response: Response,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Readiness probe. 200 when ready, 503 when not.

    The status code carries the verdict, unlike ``/admin/health-check``, which
    returns 200 with ``ok: false`` — a payload no infra probe can consume.

    Two disclosure tiers. Unauthenticated: the verdict, build identity, and
    coarse reason codes; no corpus sizes and no provider inventory. With a valid
    ``X-Admin-Token`` (same shared secret and same constant-time check as every
    admin route): the full per-check detail plus the non-gating reports.

    An X-Admin-Token that is present but wrong raises 401 exactly as it does on
    the admin surface, rather than silently downgrading to the coarse tier — a
    misconfigured ops script should fail loudly. Infra probes must therefore send
    NO token at all: with ADMIN_TOKEN unset, admin's own semantics turn a
    token-bearing request into a 503 that is indistinguishable from "not ready".
    """
    authenticated = x_admin_token is not None
    if authenticated:
        # Before any work: a bad token buys nothing, not even a corpus stat.
        _authenticate(x_admin_token)

    try:
        reasons, warnings, checks = _evaluate_gating()
    except Exception:
        # Fail closed and stay a probe: an unexpected error here is a 503 with a
        # reason code, never a 500 that a monitor has to interpret.
        logger.exception("readiness: gating evaluation failed")
        reasons, warnings, checks = [REASON_PROBE_ERROR], [], {}

    ready = not reasons
    response.status_code = 200 if ready else 503

    payload: dict = {
        "ready": ready,
        "checked_at": datetime.now(UTC).isoformat(),
        # Build identity from backend.lib.build_info, the same resolver
        # /api/health uses — one definition of "which build is this", and it
        # returns None rather than inventing a placeholder SHA. api_version
        # describes the API SHAPE; release_sha is the only field that
        # identifies the running code.
        "api_version": BUILD_VERSION,
        "release_sha": release_sha(),
        "reasons": reasons,
        "warnings": warnings,
    }
    if not authenticated:
        return payload

    payload["checks"] = checks
    payload["reported"] = {
        "matcher_identity": _matcher_identity(),
        "providers": _provider_report(),
        # Tail-read only on the authenticated path: the unauthenticated probe
        # touches no artifact at all, so polling it costs nothing.
        "professor_tracking_release": _tracking_release_report(),
    }
    return payload
