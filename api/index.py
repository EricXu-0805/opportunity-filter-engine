import sys
from pathlib import Path
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

app = FastAPI()

try:
    from backend.main import app  # noqa: F811
except Exception:
    import traceback
    _err = traceback.format_exc()

    @app.get("/api/health")
    async def health_fallback():
        return {"status": "import_error", "detail": _err}

    @app.get("/api/{path:path}")
    async def catch_all(path: str):
        return {"status": "import_error", "detail": _err}
