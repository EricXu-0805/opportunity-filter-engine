"""FastAPI application — wraps existing Python matching engine as a REST API."""

from __future__ import annotations

import os
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from backend.routes import matches, opportunities, cold_email, resume, push, admin

API_VERSION = "2.6.0"

_rate_buckets: dict[str, list[float]] = defaultdict(list)

RATE_LIMITS: dict[str, tuple[int, int]] = {
    "/api/matches": (10, 60),
    "/api/cold-email": (15, 60),
    "/api/cold-email/refine": (20, 60),
    "/api/cold-email/variants": (15, 60),
    "/api/resume/upload": (5, 60),
    "/api/resume/github": (10, 60),
}
DEFAULT_RATE = (60, 60)


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

        limit_key = path
        for prefix in RATE_LIMITS:
            if path.startswith(prefix):
                limit_key = prefix
                break

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
        return response


app = FastAPI(
    title="Opportunity Filter Engine API",
    description="Personalized research & internship matching for UIUC undergrads",
    version=API_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^https://([a-z0-9-]+\.)*vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(matches.router, prefix="/api", tags=["matches"])
app.include_router(opportunities.router, prefix="/api", tags=["opportunities"])
app.include_router(cold_email.router, prefix="/api", tags=["cold-email"])
app.include_router(resume.router, prefix="/api", tags=["resume"])
app.include_router(push.router, prefix="/api", tags=["push"])
app.include_router(admin.router, prefix="/api", tags=["admin"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": API_VERSION}
