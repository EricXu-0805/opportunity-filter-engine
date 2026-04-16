import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from backend.main import app  # noqa: F811
except Exception:
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/api/health")
    async def health_fallback():
        return {"status": "error", "detail": "Backend failed to initialize"}

    @app.get("/api/{path:path}")
    async def catch_all(path: str):
        return {"status": "error", "detail": "Service unavailable"}
