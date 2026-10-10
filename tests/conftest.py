import os

import pytest

os.environ.setdefault("OFE_DISABLE_RATE_LIMIT", "1")
# Snapshot reuse off by default in tests: suites monkeypatch corpora and
# rerankers per test, and a cross-test snapshot hit would serve the previous
# test's conclusions. The dedicated snapshot tests opt back in by setting
# backend.routes.matches._SNAPSHOT_TTL_SECONDS directly.
os.environ.setdefault("OFE_MATCH_SNAPSHOT_TTL", "0")


@pytest.fixture(autouse=True)
def _enable_legacy_feature_implementation_tests(monkeypatch, request):
    """Keep dormant implementation suites useful without a runtime escape.

    Only test code patches the imported release checks. The contract test module
    opts out and therefore exercises the exact source-controlled production
    behavior.
    """
    if getattr(request.module, "RELEASE_CONTRACT_TESTS", False):
        return

    from backend import main as main_module
    from backend.lib import payments as payments_module
    from backend.lib import release_scope as release_scope_module
    from backend.routes import matches as matches_module
    from backend.routes import ops as ops_module

    monkeypatch.setattr(main_module, "feature_enabled", lambda _feature: True)
    monkeypatch.setattr(matches_module, "feature_enabled", lambda _feature: True)
    monkeypatch.setattr(payments_module, "feature_enabled", lambda _feature: True)
    monkeypatch.setattr(ops_module, "feature_enabled", lambda _feature: True)
    monkeypatch.setattr(
        release_scope_module,
        "feature_enabled",
        lambda _feature: True,
    )


@pytest.fixture(autouse=True)
def unbounded_body_reads(monkeypatch):
    """Every route of the app that reads its request body, in its endpoint, a dependency or a helper,
    declares the structural bounds of that body (backend/lib/request_body.py json_body_bounds).

    Each read of a body by a backend route that declares none is recorded, and fails the test that
    made it. Starlette's json() reads the body through body(); a multipart form reads its stream.
    """
    from starlette.requests import Request

    from backend.lib.request_body import declared_bounds

    unbounded, real = [], Request.body

    async def body(self):
        route = self.scope.get("route")
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and getattr(endpoint, "__module__", "").startswith("backend.") \
                and declared_bounds(route) is None:
            unbounded.append(f"{self.method} {route.path}")
        return await real(self)

    monkeypatch.setattr(Request, "body", body)
    yield unbounded
    assert not unbounded, f"routes read a request body without declaring its bounds: {sorted(set(unbounded))}"
