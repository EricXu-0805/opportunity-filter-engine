"""Dump the FastAPI OpenAPI schema to a file without booting a real server.

Used by `make openapi-types` to regenerate the TypeScript types the
frontend uses (`frontend/src/lib/api-types.gen.ts`). Production never
serves /openapi.json — see backend/main.py where openapi_url=None.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main(out_path: Path) -> int:
    from backend.main import app

    schema = app.openapi()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    routes = len(schema.get("paths", {}))
    print(f"wrote {out_path} ({routes} routes, {out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "frontend" / "src" / "lib" / "openapi.json"
    sys.exit(main(out))
