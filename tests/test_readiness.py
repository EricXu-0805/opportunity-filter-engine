"""``/api/ready`` — the probe that actually checks something.

``/api/health`` returns a literal ``{"status":"ok"}`` and ``_lifespan`` swallows
every warmup exception, so a process whose corpus load failed boots green and
answers matches from an empty universe. These tests pin the readiness contract
that closes that gap:

* the five REQUIRED checks each independently produce a 503 with a coarse reason
  code (never a 200 carrying ``ok: false``, which no infra probe can consume);
* unknown freshness is a FAILURE, not a pass — "no signal" is exactly what a dead
  cron produces;
* the OPTIONAL provider inventory never gates, because degrading cleanly is the
  designed behavior and a 503 there would be a self-inflicted outage;
* the two disclosure tiers stay separate (no corpus counts or provider inventory
  without the admin token);
* the probe never scores anything, so a busy instance cannot look broken;
* ``/api/health`` keeps its unconditional liveness shape for its three consumers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.lib.corpus_freshness import corpus_freshness_thresholds
from backend.main import app
from backend.routes import readiness

client = TestClient(app)

ADMIN_TOKEN = "ready-probe-test-token"
ADMIN_HEADERS = {"X-Admin-Token": ADMIN_TOKEN}


def _hours_ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


class _Vectorizer:
    """Stand-in for a fitted TfidfVectorizer — presence is all that is read."""


@pytest.fixture
def ready_state(monkeypatch):
    """Every required invariant satisfied, with nothing depending on local data.

    Returned so a test can mutate one axis at a time; the corpus list is held by
    the fixture so its ``id()`` cannot be recycled mid-test.
    """
    corpus = [{"id": "opp-1"}, {"id": "opp-2"}]
    monkeypatch.setattr(readiness, "load_opportunities", lambda: corpus)
    monkeypatch.setattr(readiness, "corpus_version", lambda: "1754000000.000000")
    monkeypatch.setattr(readiness.embeddings, "_tfidf_fitted", True)
    monkeypatch.setattr(readiness.embeddings, "_tfidf_vectorizer", _Vectorizer())
    monkeypatch.setattr(readiness.ranker, "_sim_matrix", object())
    monkeypatch.setattr(
        readiness.ranker, "registered_corpus_identity_nowait", lambda: id(corpus)
    )
    monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: _hours_ago(2))
    monkeypatch.delenv("OFE_CORPUS_WARN_HOURS", raising=False)
    monkeypatch.delenv("OFE_CORPUS_STALE_HOURS", raising=False)
    return corpus


@pytest.fixture
def admin_enabled(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)


class TestReadyPath:
    def test_ready_when_every_required_check_holds(self, ready_state):
        r = client.get("/api/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is True
        assert body["reasons"] == []
        assert body["warnings"] == []

    def test_ready_response_carries_build_identity(self, ready_state, monkeypatch):
        from backend.lib.build_info import BUILD_VERSION

        monkeypatch.setenv("RENDER_GIT_COMMIT", "deadbeefcafe")
        body = client.get("/api/ready").json()
        assert body["release_sha"] == "deadbeefcafe"
        assert body["api_version"] == BUILD_VERSION

    def test_release_sha_is_null_rather_than_a_placeholder_when_unknown(
        self, ready_state, monkeypatch
    ):
        # Shared resolver with /api/health: unknown stays null rather than
        # becoming a fabricated "dev"/"unknown" SHA.
        monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
        monkeypatch.delenv("OFE_RELEASE_SHA", raising=False)
        assert client.get("/api/ready").json()["release_sha"] is None


class TestCorpusGating:
    def test_empty_corpus_is_not_ready(self, ready_state, monkeypatch):
        # The failure _lifespan hides: warmup raised (or produced nothing) and
        # /api/health still says ok.
        monkeypatch.setattr(readiness, "load_opportunities", list)
        r = client.get("/api/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["ready"] is False
        assert readiness.REASON_CORPUS_EMPTY in body["reasons"]

    def test_cold_version_sentinel_is_not_ready(self, ready_state, monkeypatch):
        # A non-empty list with the sentinel version means no generation was
        # ever published in this process — data_loader already distinguishes it.
        monkeypatch.setattr(
            readiness, "corpus_version", lambda: readiness.COLD_CORPUS_VERSION
        )
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_CORPUS_UNPUBLISHED]


class TestMatcherArtifactGating:
    def test_unfitted_tfidf_is_not_ready(self, ready_state, monkeypatch):
        monkeypatch.setattr(readiness.embeddings, "_tfidf_fitted", False)
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_MATCHER_UNFITTED]

    def test_missing_vectorizer_is_not_ready(self, ready_state, monkeypatch):
        # _tfidf_fitted True with no vectorizer object is an inconsistent state
        # that must not read as fitted.
        monkeypatch.setattr(readiness.embeddings, "_tfidf_vectorizer", None)
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_MATCHER_UNFITTED]

    def test_missing_similarity_matrix_is_not_ready(self, ready_state, monkeypatch):
        monkeypatch.setattr(readiness.ranker, "_sim_matrix", None)
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_SIM_MATRIX_MISSING]


class TestRankerBindingGating:
    def test_ranker_bound_to_a_different_generation_is_not_ready(
        self, ready_state, monkeypatch
    ):
        # Artifacts exist but describe a corpus this process no longer serves:
        # every score would be computed against the wrong rows.
        stale_generation = [{"id": "old-opp"}]
        monkeypatch.setattr(
            readiness.ranker,
            "registered_corpus_identity_nowait",
            lambda: id(stale_generation),
        )
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_RANKER_GENERATION_MISMATCH]

    def test_unregistered_ranker_is_not_ready(self, ready_state, monkeypatch):
        monkeypatch.setattr(
            readiness.ranker, "registered_corpus_identity_nowait", lambda: None
        )
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_RANKER_GENERATION_MISMATCH]

    def test_binding_uses_the_non_blocking_probe(self, ready_state, monkeypatch):
        # The locking variant would queue behind an in-flight scorer (the match
        # executor is one worker / two pending), so a busy instance would report
        # itself unready purely for being busy.
        def _must_not_be_called():
            raise AssertionError("readiness took the locking identity probe")

        monkeypatch.setattr(
            readiness.ranker, "registered_corpus_identity", _must_not_be_called
        )
        assert client.get("/api/ready").status_code == 200


class TestFreshnessGating:
    def test_unknown_freshness_is_not_ready(self, ready_state, monkeypatch):
        # None means no snapshot, no work file and no shard mtime — the state a
        # dead cron plus a clean deploy produces. Unknown is never a pass.
        monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: None)
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_FRESHNESS_UNKNOWN]

    def test_unparseable_timestamp_is_treated_as_unknown(self, ready_state, monkeypatch):
        monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: "whenever")
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_FRESHNESS_UNKNOWN]

    def test_age_past_the_stale_bound_is_not_ready(self, ready_state, monkeypatch):
        monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: _hours_ago(200))
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_CORPUS_STALE]

    def test_warn_band_stays_ready_but_is_flagged(self, ready_state, monkeypatch):
        # 80h is past the 72h warn bound and short of the 96h stale bound: the
        # data is aging, the API is still correct to serve.
        monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: _hours_ago(80))
        r = client.get("/api/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is True
        assert body["warnings"] == [readiness.WARNING_CORPUS_AGING]

    def test_admin_detail_reports_the_freshness_level_and_bounds(
        self, ready_state, admin_enabled, monkeypatch
    ):
        monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: _hours_ago(80))
        body = client.get("/api/ready", headers=ADMIN_HEADERS).json()
        freshness = body["checks"]["corpus_freshness"]
        assert freshness["level"] == "warn"
        assert freshness["ok"] is True
        assert freshness["warn_hours"] == 72
        assert freshness["stale_hours"] == 96
        assert 79 <= freshness["age_hours"] <= 81


class TestThresholdConsolidation:
    def test_defaults_are_the_documented_boundary(self, monkeypatch):
        monkeypatch.delenv("OFE_CORPUS_WARN_HOURS", raising=False)
        monkeypatch.delenv("OFE_CORPUS_STALE_HOURS", raising=False)
        assert corpus_freshness_thresholds() == (72.0, 96.0)

    def test_admin_health_check_uses_the_shared_bounds(self):
        # admin.py used to carry a local 96/192 while the docs and the admin
        # dashboard's own banner said 72/96 — the alert that pages a human fired
        # a full extra cron cycle after the UI turned red.
        from backend.routes.admin import _HEALTH_THRESHOLDS

        assert _HEALTH_THRESHOLDS["data_age_warn_hours"] == 72.0
        assert _HEALTH_THRESHOLDS["data_age_alert_hours"] == 96.0

    def test_env_overrides_are_honored(self, monkeypatch):
        monkeypatch.setenv("OFE_CORPUS_WARN_HOURS", "6")
        monkeypatch.setenv("OFE_CORPUS_STALE_HOURS", "12")
        assert corpus_freshness_thresholds() == (6.0, 12.0)

    def test_invalid_override_falls_back_instead_of_disabling_the_check(
        self, monkeypatch
    ):
        monkeypatch.setenv("OFE_CORPUS_STALE_HOURS", "not-a-number")
        monkeypatch.setenv("OFE_CORPUS_WARN_HOURS", "-3")
        assert corpus_freshness_thresholds() == (72.0, 96.0)

    def test_warn_is_clamped_to_stale_when_misordered(self, monkeypatch):
        monkeypatch.setenv("OFE_CORPUS_WARN_HOURS", "120")
        monkeypatch.setenv("OFE_CORPUS_STALE_HOURS", "48")
        assert corpus_freshness_thresholds() == (48.0, 48.0)

    def test_tightened_stale_bound_makes_the_probe_fail(self, ready_state, monkeypatch):
        monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: _hours_ago(12))
        monkeypatch.setenv("OFE_CORPUS_STALE_HOURS", "10")
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_CORPUS_STALE]

    def test_tightened_warn_bound_flags_without_failing(self, ready_state, monkeypatch):
        monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: _hours_ago(12))
        monkeypatch.setenv("OFE_CORPUS_WARN_HOURS", "6")
        r = client.get("/api/ready")
        assert r.status_code == 200
        assert r.json()["warnings"] == [readiness.WARNING_CORPUS_AGING]


class TestProvidersNeverGate:
    def test_missing_optional_providers_stay_ready(self, ready_state, monkeypatch):
        # The product degrades by design without any of these; a 503 here would
        # take every read out of rotation to protect a feature that already
        # fails cleanly on its own.
        for key in (
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
            "RESEND_API_KEY",
            "RESEND_FROM_EMAIL",
            "VAPID_PUBLIC_KEY",
            "VAPID_PRIVATE_KEY",
            "VAPID_SUBJECT",
            "SENTRY_DSN",
            "CRON_SECRET",
        ):
            monkeypatch.delenv(key, raising=False)
        r = client.get("/api/ready")
        assert r.status_code == 200
        assert r.json()["ready"] is True

    def test_admin_detail_labels_every_provider_optional(
        self, ready_state, admin_enabled, monkeypatch
    ):
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)
        monkeypatch.setenv("SENTRY_DSN", "https://key@example.ingest.sentry.io/1")
        providers = client.get("/api/ready", headers=ADMIN_HEADERS).json()["reported"][
            "providers"
        ]
        assert providers["resend_email"]["status"] == "missing"
        assert providers["resend_email"]["missing_env"] == [
            "RESEND_API_KEY",
            "RESEND_FROM_EMAIL",
        ]
        assert providers["sentry"]["status"] == "configured"
        assert providers["admin_surface"]["status"] == "configured"
        assert all(p["requirement"] == "optional" for p in providers.values())
        assert all(p["probe"] == "env_presence" for p in providers.values())

    def test_provider_report_never_echoes_a_secret_value(
        self, ready_state, admin_enabled, monkeypatch
    ):
        secret = "super-secret-service-role-key"
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", secret)
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        raw = client.get("/api/ready", headers=ADMIN_HEADERS).text
        assert secret not in raw
        assert "example.supabase.co" not in raw
        assert ADMIN_TOKEN not in raw

    def test_llm_status_is_env_presence_only(
        self, ready_state, admin_enabled, monkeypatch
    ):
        # A probe that bills a completion is a probe nobody can afford to poll.
        def _must_not_be_called(*args, **kwargs):
            raise AssertionError("readiness contacted an LLM provider")

        monkeypatch.setattr(readiness, "llm_is_configured", lambda: True)
        import backend.lib.llm as llm_mod

        monkeypatch.setattr(llm_mod, "chat", _must_not_be_called, raising=False)
        llm = client.get("/api/ready", headers=ADMIN_HEADERS).json()["reported"][
            "providers"
        ]["llm"]
        assert llm["status"] == "configured"
        assert llm["requirement"] == "optional"


class TestMatcherIdentityIsReportedNotValidated:
    def test_versions_are_reported_as_unvalidated_data(
        self, ready_state, admin_enabled
    ):
        from backend.routes.matches import MATCH_CONTRACT_VERSION
        from src.matcher.config import MATCHER_VERSION

        identity = client.get("/api/ready", headers=ADMIN_HEADERS).json()["reported"][
            "matcher_identity"
        ]
        assert identity["active_matcher_version"] == MATCHER_VERSION
        assert identity["active_match_contract_version"] == MATCH_CONTRACT_VERSION
        # No expected version is recorded anywhere in the repo, so the payload
        # must not imply one was compared.
        assert identity["expected_matcher_version"] is None
        assert identity["matcher_version_validated"] is False
        assert identity["gates_readiness"] is False


class TestProfessorTrackingReport:
    _FULL_CHECKS = {name: True for name in readiness._REQUIRED_TRACKING_CHECKS}

    def test_stale_check_set_reports_not_release_ready_despite_the_true_flag(
        self, ready_state, admin_enabled, monkeypatch
    ):
        # The committed artifact's shape: release_ready true carrying only the
        # five checks that existed when it was produced. The strict contract is
        # False and the strict view is what gets reported.
        block = {
            "release_ready": True,
            "checks": {
                "schema_v2": True,
                "events_valid": True,
                "freshness_min_pct": True,
                "no_fully_stale_school": True,
                "refresh_ok": True,
            },
            "computed_at": "2026-08-06T11:02:08+00:00",
        }
        monkeypatch.setattr(readiness, "_read_release_block", lambda _path: (block, None))
        r = client.get("/api/ready", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        report = r.json()["reported"]["professor_tracking_release"]
        assert report["artifact_release_ready_flag"] is True
        assert report["strict_release_ready"] is False
        assert report["verdict"] == "not_release_ready"
        assert set(report["missing_checks"]) == {
            "all_active_professors_identifiable",
            "all_active_schools_tracked",
            "active_professor_coverage_min_pct",
            "active_professor_denominator_present",
        }
        assert report["failing_checks"] == []
        assert report["gates_readiness"] is False

    def test_failing_checks_are_named(self, ready_state, admin_enabled, monkeypatch):
        checks = dict(self._FULL_CHECKS)
        checks["refresh_ok"] = False
        checks["events_valid"] = False
        monkeypatch.setattr(
            readiness,
            "_read_release_block",
            lambda _path: ({"release_ready": False, "checks": checks}, None),
        )
        report = client.get("/api/ready", headers=ADMIN_HEADERS).json()["reported"][
            "professor_tracking_release"
        ]
        assert report["failing_checks"] == ["events_valid", "refresh_ok"]
        assert report["strict_release_ready"] is False

    def test_complete_passing_block_reports_release_ready(
        self, ready_state, admin_enabled, monkeypatch
    ):
        monkeypatch.setattr(
            readiness,
            "_read_release_block",
            lambda _path: (
                {"release_ready": True, "checks": dict(self._FULL_CHECKS)},
                None,
            ),
        )
        report = client.get("/api/ready", headers=ADMIN_HEADERS).json()["reported"][
            "professor_tracking_release"
        ]
        assert report["strict_release_ready"] is True
        assert report["verdict"] == "release_ready"
        # Even a pass here is an upper bound: the real consumer also validates
        # schema_version and the freshness expiry, which a tail read cannot see.
        assert report["strict_view_is_upper_bound"] is True

    def test_unreadable_artifact_reports_unknown_and_still_does_not_gate(
        self, ready_state, admin_enabled, monkeypatch
    ):
        monkeypatch.setattr(
            readiness, "_read_release_block", lambda _path: (None, "artifact not present")
        )
        r = client.get("/api/ready", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        report = r.json()["reported"]["professor_tracking_release"]
        assert report["verdict"] == "unknown"
        assert report["read_error"] == "artifact not present"

    def test_unauthenticated_probe_reads_no_artifact(self, ready_state, monkeypatch):
        # The 31MB artifact must not be touched at all by an anonymous poll.
        def _must_not_be_called(_path):
            raise AssertionError("unauthenticated probe read the tracking artifact")

        monkeypatch.setattr(readiness, "_read_release_block", _must_not_be_called)
        assert client.get("/api/ready").status_code == 200


class TestDisclosureTiers:
    _PUBLIC_KEYS = {
        "ready",
        "checked_at",
        "api_version",
        "release_sha",
        "reasons",
        "warnings",
    }

    def test_unauthenticated_payload_is_verdict_only(self, ready_state):
        r = client.get("/api/ready")
        body = r.json()
        assert set(body) == self._PUBLIC_KEYS
        assert "checks" not in body
        assert "reported" not in body

    def test_unauthenticated_payload_leaks_no_counts_or_inventory(
        self, ready_state, admin_enabled
    ):
        raw = client.get("/api/ready").text
        for leak in (
            "opportunity_count",
            "providers",
            "supabase",
            "resend",
            "vapid",
            "corpus_version",
            "matcher_version",
        ):
            assert leak not in raw.lower()

    def test_unauthenticated_failure_gives_codes_without_detail(
        self, ready_state, monkeypatch
    ):
        monkeypatch.setattr(readiness, "load_opportunities", list)
        r = client.get("/api/ready")
        assert r.status_code == 503
        body = r.json()
        assert set(body) == self._PUBLIC_KEYS
        assert body["reasons"]
        assert "opportunity_count" not in r.text

    def test_admin_token_unlocks_the_full_detail(self, ready_state, admin_enabled):
        body = client.get("/api/ready", headers=ADMIN_HEADERS).json()
        assert body["checks"]["corpus_loaded"]["opportunity_count"] == 2
        assert body["checks"]["corpus_generation_published"]["corpus_version"]
        assert body["checks"]["matcher_artifacts"]["tfidf_fitted"] is True
        assert body["checks"]["ranker_corpus_binding"]["bound_to_current_generation"]
        assert set(body["reported"]) == {
            "matcher_identity",
            "providers",
            "professor_tracking_release",
        }

    def test_admin_detail_never_exposes_heap_addresses(self, ready_state, admin_enabled):
        binding = client.get("/api/ready", headers=ADMIN_HEADERS).json()["checks"][
            "ranker_corpus_binding"
        ]
        assert str(id(ready_state)) not in str(binding)
        assert binding["probe"] == "registered_corpus_identity_nowait"

    def test_wrong_token_is_rejected_rather_than_downgraded(
        self, ready_state, admin_enabled
    ):
        # Silently serving the coarse tier would hide a misconfigured ops script.
        r = client.get("/api/ready", headers={"X-Admin-Token": "wrong"})
        assert r.status_code == 401

    def test_token_with_admin_disabled_follows_admin_semantics(
        self, ready_state, monkeypatch
    ):
        # Documented footgun: infra probes must send NO token, because with
        # ADMIN_TOKEN unset a token-bearing request 503s for an auth reason.
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        r = client.get("/api/ready", headers=ADMIN_HEADERS)
        assert r.status_code == 503
        assert "ADMIN_TOKEN" in r.json()["detail"]


class TestProbeDoesNoScoring:
    def test_probe_never_calls_a_ranking_function(self, ready_state, monkeypatch):
        def _must_not_be_called(*args, **kwargs):
            raise AssertionError("readiness invoked the ranker")

        monkeypatch.setattr(readiness.ranker, "rank_all", _must_not_be_called)
        monkeypatch.setattr(readiness.ranker, "rank_opportunity", _must_not_be_called)
        monkeypatch.setattr(
            readiness.ranker, "rank_visible_universe", _must_not_be_called
        )
        assert client.get("/api/ready").status_code == 200

    def test_probe_error_fails_closed_as_503(self, ready_state, monkeypatch):
        def _boom():
            raise RuntimeError("corpus read exploded")

        monkeypatch.setattr(readiness, "load_opportunities", _boom)
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["reasons"] == [readiness.REASON_PROBE_ERROR]


class TestMiddlewareWiring:
    def test_ready_is_not_cacheable(self, ready_state):
        # A cached "ready" keeps a dead instance in rotation; a cached 503 keeps
        # a recovered one out.
        r = client.get("/api/ready")
        assert "no-store" in r.headers["Cache-Control"]
        assert r.headers["Pragma"] == "no-cache"

    def test_ready_has_its_own_rate_bucket(self):
        from backend.main import DEFAULT_RATE, RATE_LIMITS, _rate_limit_key

        assert _rate_limit_key("/api/ready") == "/api/ready"
        assert RATE_LIMITS["/api/ready"] != DEFAULT_RATE

    def test_ready_bucket_does_not_capture_other_paths(self):
        from backend.main import _rate_limit_key

        assert _rate_limit_key("/api/health") != "/api/ready"
        assert _rate_limit_key("/api/matches") != "/api/ready"


class TestHealthStaysLiveness:
    """Regression guard for /api/health's three consumers: the frontend's
    wakeBackend, playwright.config's webServer gate, and
    test_async_route_isolation. It must stay unconditional."""

    def test_health_keeps_its_load_bearing_fields(self):
        from backend.main import API_VERSION

        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        # status + version are what the three consumers read; readiness must
        # never have made them conditional on any data signal.
        assert body["status"] == "ok"
        assert body["version"] == API_VERSION
        assert "ready" not in body
        assert "reasons" not in body

    def test_health_stays_200_while_readiness_reports_503(
        self, ready_state, monkeypatch
    ):
        monkeypatch.setattr(readiness, "load_opportunities", list)
        monkeypatch.setattr(readiness, "corpus_last_updated_at", lambda: None)
        assert client.get("/api/ready").status_code == 503
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

    def test_health_is_still_cacheable_unlike_ready(self):
        r = client.get("/api/health")
        assert "no-store" not in r.headers.get("Cache-Control", "")
