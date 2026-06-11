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

from backend.lib.observability import init_sentry

init_sentry()

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from backend.routes import (
    admin,
    cold_email,
    import_text,
    import_url,
    matches,
    opportunities,
    push,
    resume,
    roadmap,
    saved_searches,
    tailor,
)
from backend.routes import email as email_routes

API_VERSION = "2.7.0"

_rate_buckets: dict[str, list[float]] = defaultdict(list)

RATE_LIMITS: dict[str, tuple[int, int]] = {
    "/api/matches": (10, 60),
    "/api/cold-email": (15, 60),
    "/api/cold-email/refine": (20, 60),
    "/api/cold-email/variants": (15, 60),
    # Status probe is a cheap GET the modal fires on every open — its generous
    # budget is preserved by longest-prefix matching below (a more specific key
    # always wins over "/api/tailor").
    "/api/tailor/status": (60, 60),
    "/api/tailor": (10, 60),
    "/api/resume/upload": (5, 60),
    "/api/resume/github": (10, 60),
    "/api/email/send-matches": (3, 3600),
    "/api/email/send-favorites": (3, 3600),
    "/api/email/restore-link": (3, 3600),
    "/api/import-url": (5, 60),
    "/api/import-text": (5, 60),
    # SEC-2: the opportunity chat endpoint issues a paid LLM completion per call
    # but is under /api/opportunities/{id}/chat with no dedicated key, so it used
    # to inherit the loose 60/60 default — an unauthenticated paid-LLM
    # cost/quota-exhaustion vector. The trailing slash scopes this to the
    # detail + chat sub-routes (cheap detail GETs share it, which 20/min easily
    # covers) while leaving the bare /api/opportunities list/stats on the default.
    "/api/opportunities/": (20, 60),
}
DEFAULT_RATE = (60, 60)

# SEC-4: resolve the rate bucket by LONGEST matching prefix, not insertion order.
# First-match-wins let "/api/cold-email" shadow "/api/cold-email/refine" (and
# /variants), making those dedicated buckets dead config. Longest-prefix is
# order-independent and removes that footgun.
_RATE_LIMIT_PREFIXES_BY_LEN = sorted(RATE_LIMITS, key=len, reverse=True)


def _rate_limit_key(path: str) -> str:
    """The RATE_LIMITS key governing ``path`` by longest matching prefix, or the
    path itself (→ DEFAULT_RATE) when none match."""
    for prefix in _RATE_LIMIT_PREFIXES_BY_LEN:
        if path.startswith(prefix):
            return prefix
    return path


_last_purge = 0.0


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("x-real-ip", "")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


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
            stale = [k for k, ts in _rate_buckets.items() if not ts or ts[-1] < now - 120]
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
            return Response(
                content='{"detail":"Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(window)},
            )

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
        return response


logger = logging.getLogger("ofe.main")


def _warmup() -> None:
    """Load the opportunity corpus + fit the TF-IDF vectorizer. Without this the
    first user request after a cold start pays the ~1-2s data-load + fit cost."""
    from backend.data_loader import load_opportunities_by_id
    load_opportunities_by_id()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        await asyncio.to_thread(_warmup)
    except Exception as exc:  # never let a warmup hiccup block boot
        logger.warning("Startup warmup failed (will load lazily): %s", exc)
    yield


app = FastAPI(
    title="Opportunity Filter Engine API",
    description="Personalized research & internship matching for UIUC undergrads",
    version=API_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^https://opportunity-filter-engine(-[a-z0-9-]+)?\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(matches.router, prefix="/api", tags=["matches"])
app.include_router(roadmap.router, prefix="/api", tags=["roadmap"])
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


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": API_VERSION}
