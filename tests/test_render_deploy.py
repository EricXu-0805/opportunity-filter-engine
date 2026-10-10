"""How the backend is started and deployed on Render."""
from __future__ import annotations

import shlex
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]


def _web_service() -> dict:
    blueprint = yaml.safe_load((_REPO / "render.yaml").read_text(encoding="utf-8"))
    (service,) = (s for s in blueprint["services"] if s.get("type") == "web")
    return service


def test_the_backend_starts_exactly_one_uvicorn_worker():
    """uvicorn's --workers defaults to $WEB_CONCURRENCY when that is set.

    Each worker loads the whole corpus, about 1.3-1.5 GB, on a 2 GB plan, so
    a WEB_CONCURRENCY of 2 or more appearing in the service environment would
    start more copies than the instance can hold. Naming the count in the
    start command makes the environment irrelevant.
    """
    argv = shlex.split(_web_service()["startCommand"])
    assert argv[0] == "uvicorn", argv
    assert argv.count("--workers") == 1, argv
    assert argv[argv.index("--workers") + 1] == "1", argv
    assert not any(arg.startswith("--workers=") for arg in argv), argv
