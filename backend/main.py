"""FastAPI application — wraps existing Python matching engine as a REST API."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / "backend" / ".env")
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from backend.lib.build_info import BUILD_VERSION, health_build_fields
from backend.lib.observability import init_sentry
from backend.lib.release_scope import ReleaseFeature, feature_enabled

init_sentry()

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from backend.routes import (
    admin,
    cold_email,
    import_text,
    import_url,
    matches,
    opportunities,
    ops,
    orders,
    professors,
    push,
    readiness,
    responsiveness,
    resume,
    roadmap,
    saved_searches,
    tailor,
)
from backend.routes import email as email_routes

# The declared API contract version, re-exported from backend.lib.build_info
# so the version string and the build-provenance fields have one home. This
# name and value are unchanged for existing consumers; it identifies the API
# shape, NOT the deployed code — that is /api/health's release_sha.
API_VERSION = BUILD_VERSION

_rate_buckets: dict[str, list[float]] = defaultdict(list)

CHAT_RATE_KEY = "/api/opportunities/*/chat"

RATE_LIMITS: dict[str, tuple[int, int]] = {
    # Search, filters, favorites and cursor pages are cheap reads over one
    # cached snapshot. Give this interactive view its own budget; longest-
    # prefix resolution keeps the expensive snapshot-creation route below at
    # its tighter scorer limit.
    # A complete exact export can traverse up to 50 pages (5,000 capped
    # favorites / 100 rows). Keep a small margin for the on-screen page while
    # the scorer itself remains protected by its separate single-worker belt.
    "/api/matches/view": (60, 60),
    "/api/matches": (10, 60),
    "/api/cold-email": (15, 60),
    "/api/cold-email/refine": (20, 60),
    "/api/cold-email/variants": (15, 60),
    # Status probe is a cheap GET the modal fires on every open — its generous
    # budget is preserved by longest-prefix matching below (a more specific key
    # always wins over "/api/tailor").
    "/api/tailor/status": (60, 60),
    "/api/tailor": (10, 60),
    "/api/resume/github": (10, 60),
    "/api/email/send-matches": (3, 3600),
    "/api/email/send-favorites": (3, 3600),
    "/api/import-url": (5, 60),
    "/api/import-text": (5, 60),
    # SEC-2: detail sub-routes under /api/opportunities/{id} used to inherit the
    # loose 60/60 default. The trailing slash scopes this bucket to them while
    # leaving the bare /api/opportunities list/stats on the default.
    "/api/opportunities/": (20, 60),
    # The paid chat endpoint gets its OWN per-IP bucket (synthetic key, resolved
    # in _rate_limit_key — no real path starts with it): sharing the
    # /api/opportunities/ bucket let one chatty user exhaust the quota that
    # detail GETs draw on, and vice versa.
    CHAT_RATE_KEY: (15, 60),
    # W15: the admin surface used to inherit the loose 60/60 default despite
    # being the highest-value target on the API — one shared ADMIN_TOKEN
    # guarding reads of student emails/feedback and writes that mutate ticket
    # state. A tighter bucket bounds an online token-guessing run and any
    # runaway ops script, while staying far above what a human operator (or the
    # admin dashboard's polling) generates. Longest-prefix matching scopes it to
    # every /api/admin/* route, mutations included.
    "/api/admin": (30, 60),
    # Readiness is an INFRA probe: it must not share the per-IP DEFAULT (60,60)
    # bucket with user traffic, in either direction. A monitor polling every few
    # seconds would otherwise burn the quota that ordinary reads from the same
    # egress IP draw on, and a burst of user traffic would throttle the probe
    # into reporting an outage that is really a rate limit. The endpoint is cheap
    # (module globals plus one already-cached corpus stat; no artifact read on
    # the unauthenticated path), so a generous ceiling is still a real ceiling.
    "/api/ready": (120, 60),
}
DEFAULT_RATE = (60, 60)
DEFAULT_RATE_KEY = "__default__"
MAX_RATE_WINDOW = max(DEFAULT_RATE[1], *(window for _, window in RATE_LIMITS.values()))

# SEC-4: resolve the rate bucket by LONGEST matching prefix, not insertion order.
# First-match-wins let "/api/cold-email" shadow "/api/cold-email/refine" (and
# /variants), making those dedicated buckets dead config. Longest-prefix is
# order-independent and removes that footgun.
_RATE_LIMIT_PREFIXES_BY_LEN = sorted(RATE_LIMITS, key=len, reverse=True)


def _rate_limit_key(path: str) -> str:
    """The RATE_LIMITS key governing ``path`` by longest matching prefix.

    Unknown paths deliberately share ``DEFAULT_RATE_KEY``. Returning the raw
    path let an attacker mint unlimited independent buckets (each with its own
    fresh default quota) by changing a path segment, bypassing the default
    ceiling while growing the in-memory map without bound.
    """
    if path.startswith("/api/opportunities/") and path.endswith("/chat"):
        return CHAT_RATE_KEY
    for prefix in _RATE_LIMIT_PREFIXES_BY_LEN:
        if path.startswith(prefix):
            return prefix
    return DEFAULT_RATE_KEY


_last_purge = 0.0

# Number of trusted reverse-proxy hops in front of the app. On Render exactly one
# trusted edge proxy sits in front and APPENDS the real client IP to the right of
# any client-supplied X-Forwarded-For, so the trustworthy address is the value
# _TRUSTED_PROXY_HOPS from the RIGHT. The old code took the leftmost value, which
# is fully client-controlled — an attacker rotated it to mint a fresh rate-limit
# bucket per request and bypass every per-IP limit (denial-of-wallet on the
# shared LLM key). Tunable via env if the proxy topology ever changes.
_TRUSTED_PROXY_HOPS = max(1, int(os.environ.get("OFE_TRUSTED_PROXY_HOPS", "1")))


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            # Count _TRUSTED_PROXY_HOPS from the right (the hop the trusted proxy
            # appended); clamp to the leftmost when the client sent fewer hops.
            return parts[max(0, len(parts) - _TRUSTED_PROXY_HOPS)]
    real = request.headers.get("x-real-ip", "")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


# Second-tier GLOBAL ceilings across ALL clients — the denial-of-wallet backstop
# that still bounds the bill if per-IP attribution is imperfect or an attacker
# spreads load over many real IPs (botnet). Set generously above real
# single-user load, low enough to cap a runaway OpenRouter spend / Resend quota.
# Per-worker (in-memory); on a multi-worker deploy the effective ceiling is N×,
# still a backstop. Tunable via env.
_global_buckets: dict[str, list[float]] = defaultdict(list)
GLOBAL_LLM_PER_MIN = int(os.environ.get("OFE_GLOBAL_LLM_PER_MIN", "240"))
GLOBAL_EMAIL_PER_HOUR = int(os.environ.get("OFE_GLOBAL_EMAIL_PER_HOUR", "60"))

_LLM_COST_PREFIXES = ("/api/cold-email", "/api/import-url", "/api/import-text")
_EMAIL_SEND_PATHS = frozenset(
    {
        "/api/email/send-matches",
        "/api/email/send-favorites",
    }
)


def _billable_class(request: Request, path: str) -> str | None:
    """Which global ceiling this request draws on — "llm", "email", or None for
    the cheap reads (list/stat/detail GETs, status probes) that must never be
    throttled by a global cap."""
    if request.method != "POST":
        return None
    release_feature = _release_feature_for_path(path)
    if release_feature is not None and not feature_enabled(release_feature):
        return None
    if path in _EMAIL_SEND_PATHS:
        return "email"
    if path.startswith("/api/tailor") and not path.startswith("/api/tailor/status"):
        return "llm"
    if path.startswith(_LLM_COST_PREFIXES):
        return "llm"
    if path.startswith("/api/opportunities/") and path.endswith("/chat"):
        return "llm"
    # Per-card explain is a paid LLM completion (the compare page fires one per
    # card); the exact "/api/matches" check below misses it. Gap analysis and
    # the plain matches list stay non-billable.
    if path.startswith("/api/matches/") and path.endswith("/explain"):
        return "llm"
    if (
        path == "/api/matches"
        and feature_enabled("match_ai_refine")
        and request.query_params.get("llm", "").lower() in ("1", "true")
    ):
        return "llm"
    return None


def _rate_limited(window: int) -> Response:
    return Response(
        content='{"detail":"Rate limit exceeded. Try again later."}',
        status_code=429,
        media_type="application/json",
        headers={"Retry-After": str(window)},
    )


RATE_LIMIT_DISABLED = os.environ.get("OFE_DISABLE_RATE_LIMIT") == "1"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if RATE_LIMIT_DISABLED:
            return await call_next(request)

        global _last_purge
        client_ip = _client_ip(request)
        path = request.url.path
        now = time.time()

        if now - _last_purge > 300:
            # Preserve buckets for the longest configured window. The old fixed
            # 120-second cutoff silently reset one-hour quotas (e.g. the 3/3600
            # email sends) on the five-minute cleanup cadence.
            stale = [
                k for k, ts in _rate_buckets.items()
                if not ts or ts[-1] < now - MAX_RATE_WINDOW
            ]
            for k in stale:
                del _rate_buckets[k]
            _last_purge = now

        limit_key = _rate_limit_key(path)
        max_requests, window = RATE_LIMITS.get(limit_key, DEFAULT_RATE)
        bucket_key = f"{client_ip}:{limit_key}"

        _rate_buckets[bucket_key] = [
            t for t in _rate_buckets[bucket_key] if t > now - window
        ]

        if len(_rate_buckets[bucket_key]) >= max_requests:
            return _rate_limited(window)

        # Second-tier GLOBAL ceiling on the billable (paid-LLM / email) endpoints:
        # bounds total spend even when the per-IP key is evaded or spread across
        # many real IPs, which the per-IP cap alone cannot.
        klass = _billable_class(request, path)
        if klass is not None:
            gwindow, gmax = (
                (60, GLOBAL_LLM_PER_MIN) if klass == "llm" else (3600, GLOBAL_EMAIL_PER_HOUR)
            )
            _global_buckets[klass] = [
                t for t in _global_buckets[klass] if t > now - gwindow
            ]
            if len(_global_buckets[klass]) >= gmax:
                logger.warning(
                    "Global %s ceiling reached (%d/%ds) — throttling; possible abuse or viral spike",
                    klass, gmax, gwindow,
                )
                return _rate_limited(gwindow)
            _global_buckets[klass].append(now)

        _rate_buckets[bucket_key].append(now)
        response = await call_next(request)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # Force HTTPS for one year, including subdomains. The backend is only
        # ever served over HTTPS in production (Render), so this prevents a
        # MitM downgrade attack from an attacker on the user's network.
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Minimal CSP for an API server: refuse to be embedded in any frame
        # and disallow loading anything cross-origin from API responses
        # themselves. The frontend has its own (looser) CSP via next.config.js.
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        path = request.url.path
        if (
            path == "/api/admin"
            or path.startswith("/api/admin/")
            # /api/ready for a different reason than PII: a cached readiness
            # answer is actively dangerous. An intermediary replaying a stored
            # "ready" would keep an instance with a dead corpus in rotation, and
            # replaying a stored 503 would keep a recovered one out. Its
            # authenticated tier is also token-varied, which no shared cache
            # keys on.
            or path == "/api/ready"
        ):
            # Admin responses can contain student email addresses, feedback
            # text, order rows, and internal notes. The X-Admin-Token custom
            # header is not a cache boundary any shared HTTP cache understands,
            # so make every admin response explicitly non-storable.
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


def _release_feature_for_path(path: str) -> ReleaseFeature | None:
    """Map direct API entry points for dormant features to their release gate."""
    path = path.rstrip("/") or "/"
    if path == "/api/roadmap":
        return "roadmap"
    if path.startswith("/api/matches/") and path.endswith("/gaps"):
        return "roadmap"
    if path.startswith("/api/matches/") and path.endswith("/explain"):
        return "compare"
    if path in {
        "/api/tailor/structure",
        "/api/tailor/renovate",
        "/api/tailor/bullet",
    }:
        return "resume_renovate"
    if path == "/api/chat/models":
        return "ask_ai"
    if path.startswith("/api/opportunities/") and path.endswith("/chat"):
        return "ask_ai"
    if path == "/api/opportunities/responsiveness":
        return "professor_signals"
    if path == "/api/professors/updates":
        return "professor_signals"
    if path == "/api/orders" or path.startswith("/api/orders/"):
        return "payments"
    if path == "/api/admin/orders" or path.startswith("/api/admin/orders/"):
        return "payments"
    return None


class ReleaseScopeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        feature = _release_feature_for_path(request.url.path)
        if feature is not None and not feature_enabled(feature):
            return Response(
                content='{"detail":"Not found"}',
                status_code=404,
                media_type="application/json",
            )
        return await call_next(request)


logger = logging.getLogger("ofe.main")


DEFAULT_MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024
MAX_CONFIGURABLE_REQUEST_BODY_BYTES = 16 * 1024 * 1024
_MIN_CONFIGURABLE_REQUEST_BODY_BYTES = 1024


def _request_body_limit_from_env() -> int:
    """Read a bounded positive body limit, falling back safely on bad config."""
    raw = os.environ.get("OFE_MAX_REQUEST_BODY_BYTES")
    if raw is None:
        return DEFAULT_MAX_REQUEST_BODY_BYTES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    if not _MIN_CONFIGURABLE_REQUEST_BODY_BYTES <= value <= MAX_CONFIGURABLE_REQUEST_BODY_BYTES:
        logger.warning(
            "Ignoring invalid OFE_MAX_REQUEST_BODY_BYTES=%r; using %d",
            raw,
            DEFAULT_MAX_REQUEST_BODY_BYTES,
        )
        return DEFAULT_MAX_REQUEST_BODY_BYTES
    return value


class _BodyTooLarge(StarletteHTTPException):
    """The cumulative chunked body crossed the limit.

    An HTTPException subclass on purpose: FastAPI's body-reading path
    re-raises HTTPException unchanged (any other exception type is flattened
    into a generic 400 before this middleware could see it), so Starlette's
    exception handler renders the 413. The middleware's own catch below is the
    fallback for body reads outside that machinery.
    """

    def __init__(self):
        super().__init__(status_code=413, detail="Request body too large")


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP bodies before FastAPI/Pydantic buffer them.

    Without a cap, a chunked (or dishonestly-declared) request body buffers
    unbounded inside Starlette's ``Request.body()`` on a 2 GB instance. A
    trustworthy Content-Length is rejected up front without reading a byte;
    multiple or malformed Content-Length headers are rejected as
    request-smuggling ambiguity. Everything else flows straight through to the
    app behind a counting ``receive`` wrapper — no upfront buffering — which
    trips 413 the moment the cumulative chunk size crosses the limit.
    """

    def __init__(self, app, max_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES):
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    @staticmethod
    async def _send_error(send, status: int) -> None:
        if status == 413:
            body = b'{"detail":"Request body too large"}'
        else:
            body = b'{"detail":"Invalid Content-Length"}'
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    # The body may be unread or only partially consumed. Do not
                    # reuse the HTTP/1.x connection with bytes still pending.
                    (b"connection", b"close"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value.strip() for name, value in scope.get("headers", []) if name.lower() == b"content-length"
        ]
        if content_lengths:
            # Multiple Content-Length fields are ambiguous even when their
            # values happen to match, and have a history of request-smuggling
            # discrepancies between proxies and application servers.
            if len(content_lengths) != 1:
                await self._send_error(send, 400)
                return
            raw_length = content_lengths[0]
            if not raw_length or not raw_length.isdigit() or len(raw_length) > 20:
                await self._send_error(send, 400)
                return
            if int(raw_length) > self.max_bytes:
                await self._send_error(send, 413)
                return

        received_bytes = 0
        response_started = False

        async def counting_receive():
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b"") or b"")
                if received_bytes > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                # Too late for a clean 413 — surface the abort instead of
                # corrupting an in-flight response.
                raise
            await self._send_error(send, 413)


def _warmup() -> None:
    """Load the opportunity corpus + fit the TF-IDF vectorizer. Without this the
    first user request after a cold start pays the ~1-2s data-load + fit cost."""
    import gc

    from backend.data_loader import load_opportunities_by_id
    load_opportunities_by_id()
    # The corpus (~1GB of objects at 126k records) is immutable after load.
    # Freezing moves it to a permanent generation the GC never scans again —
    # cuts every later gen-2 collection from ~1M-object scans to the small
    # per-request population, and keeps the collector from dirtying pages.
    gc.collect()
    gc.freeze()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        await asyncio.to_thread(_warmup)
    except Exception as exc:  # never let a warmup hiccup block boot
        logger.warning("Startup warmup failed (will load lazily): %s", exc)
    yield


app = FastAPI(
    title="JoinALab API",
    description="Personalized research & internship matching for UIUC undergrads",
    version=API_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)

app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=_request_body_limit_from_env(),
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ReleaseScopeMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    # Whitelist first-party origins only — NO .vercel.app regex. Every real
    # deploy (production on joinalab.com, and *.vercel.app previews) reaches
    # the API same-origin through the Next.js `/api` rewrite proxy, so the
    # browser never makes a cross-origin call to this backend and no
    # .vercel.app origin needs a CORS grant. A regex on .vercel.app would be
    # squattable anyway: Vercel project names are free-form, so an attacker
    # can register a project whose auto-assigned production domain matches
    # any pattern we could write (incl. one carrying our team slug).
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://joinalab.com",
        "https://www.joinalab.com",
    ],
    allow_credentials=True,
    # PATCH is here for the admin ticket-lifecycle route (W15). Without it a
    # cross-origin admin call from a first-party origin fails preflight, so the
    # route would look broken in exactly the NEXT_PUBLIC_API_URL → Render
    # configuration the X-Admin-Token grant below already anticipates.
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    # X-Admin-Actor is the self-declared operator label (see admin.require_admin).
    allow_headers=["Content-Type", "Authorization", "X-Admin-Token", "X-Admin-Actor"],
)

app.include_router(matches.router, prefix="/api", tags=["matches"])
app.include_router(roadmap.router, prefix="/api", tags=["roadmap"])
# Before opportunities: its static /opportunities/responsiveness path would
# otherwise be swallowed by the dynamic /opportunities/{opportunity_id} route.
app.include_router(responsiveness.router, prefix="/api", tags=["responsiveness"])
app.include_router(opportunities.router, prefix="/api", tags=["opportunities"])
app.include_router(cold_email.router, prefix="/api", tags=["cold-email"])
app.include_router(tailor.router, prefix="/api", tags=["tailor"])
app.include_router(resume.router, prefix="/api", tags=["resume"])
app.include_router(push.router, prefix="/api", tags=["push"])
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(email_routes.router, prefix="/api", tags=["email"])
app.include_router(import_url.router, prefix="/api", tags=["import-url"])
app.include_router(import_text.router, prefix="/api", tags=["import-text"])
app.include_router(saved_searches.router, prefix="/api", tags=["saved-searches"])
app.include_router(orders.router, prefix="/api", tags=["orders"])
app.include_router(professors.router, prefix="/api", tags=["professors"])
app.include_router(ops.router, prefix="/api", tags=["ops"])
app.include_router(readiness.router, prefix="/api", tags=["readiness"])


# LIVENESS, unchanged and deliberately unconditional: "this process is answering
# HTTP". Three consumers depend on exactly this shape and on it never failing for
# a data reason — the frontend's wakeBackend, playwright.config's webServer gate,
# and test_async_route_isolation (which asserts it answers while a blocking call
# holds the bounded executor). READINESS — corpus loaded, matcher artifacts bound
# to the current generation, refresh not stale — is /api/ready, which returns 503
# when any of that is false. Do not merge the two.
@app.get("/api/health")
async def health_check():
    # "status" and "version" are load-bearing for three existing consumers
    # (frontend wakeBackend, the Playwright webServer readiness gate, and
    # tests/test_async_route_isolation) — their shape stays exactly as it was.
    # The added keys answer "what SHA is actually serving this?", which
    # API_VERSION never could: it is a hand-maintained string. Build metadata
    # only (commit, host label, process start) — no secrets, no env inventory.
    return {"status": "ok", "version": API_VERSION, **health_build_fields()}
