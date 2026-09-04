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
