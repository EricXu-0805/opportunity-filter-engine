import os

os.environ.setdefault("OFE_DISABLE_RATE_LIMIT", "1")
# Snapshot reuse off by default in tests: suites monkeypatch corpora and
# rerankers per test, and a cross-test snapshot hit would serve the previous
# test's conclusions. The dedicated snapshot tests opt back in by setting
# backend.routes.matches._SNAPSHOT_TTL_SECONDS directly.
os.environ.setdefault("OFE_MATCH_SNAPSHOT_TTL", "0")
