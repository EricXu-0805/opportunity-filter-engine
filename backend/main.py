"""FastAPI application — wraps existing Python matching engine as a REST API."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import matches, opportunities, cold_email, resume

app = FastAPI(
    title="Opportunity Filter Engine API",
    description="Personalized research & internship matching for UIUC undergrads",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://*.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(matches.router, prefix="/api", tags=["matches"])
app.include_router(opportunities.router, prefix="/api", tags=["opportunities"])
app.include_router(cold_email.router, prefix="/api", tags=["cold-email"])
app.include_router(resume.router, prefix="/api", tags=["resume"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0"}
