"""Release provenance: what SHA is actually deployed?

Before this, the answer was unobtainable. ``API_VERSION = "2.7.0"`` was a
hand-maintained constant that had never been bumped since the commit that
introduced it, and its only test asserted the constant equals itself
(``tests/test_backend_api.py::TestHealthEndpoint``) — tautological, so it
would keep passing for years while the string described nothing. The real
commit existed in exactly one place, a Sentry release tag, which is DSN-gated
and therefore usually unset.

This file pins the contract the version test never had: ``/api/health``
reports the commit resolved from the environment, reports honest unknown when
the environment does not supply one, and never invents a value. It also pins
the Vercel deploy gate, whose asymmetry with Render (``checksPass``) is the
other half of "we cannot prove what is deployed".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.lib import build_info as build_info_module
from backend.main import API_VERSION, app

_REPO = Path(__file__).resolve().parents[1]
_VERCEL_JSON = _REPO / "frontend" / "vercel.json"
_IGNORE_SCRIPT = _REPO / "frontend" / "scripts" / "vercel-ignore-build.mjs"

client = TestClient(app)

_BUILD_ENV_VARS = ("RENDER_GIT_COMMIT", "OFE_RELEASE_SHA", "RENDER", "OFE_ENVIRONMENT")

SHA_A = "0123456789abcdef0123456789abcdef01234567"
SHA_B = "fedcba9876543210fedcba9876543210fedcba98"


@pytest.fixture
def clean_build_env(monkeypatch):
    """Start every case from "the host told us nothing"."""
    for name in _BUILD_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _local_git_sha() -> str | None:
    """The developer's checkout — the value that must NEVER be published."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


class TestShaResolution:
    def test_render_git_commit_is_the_first_source(self, clean_build_env):
        clean_build_env.setenv("RENDER_GIT_COMMIT", SHA_A)
        assert build_info_module.release_sha() == SHA_A

    def test_render_git_commit_outranks_the_explicit_override(self, clean_build_env):
        # The host's own statement about what it checked out beats an operator
        # variable that may be a leftover from another deploy.
        clean_build_env.setenv("RENDER_GIT_COMMIT", SHA_A)
        clean_build_env.setenv("OFE_RELEASE_SHA", SHA_B)
        assert build_info_module.release_sha() == SHA_A

    def test_ofe_release_sha_is_the_fallback(self, clean_build_env):
        clean_build_env.setenv("OFE_RELEASE_SHA", SHA_B)
        assert build_info_module.release_sha() == SHA_B

    def test_empty_render_var_falls_through_to_the_override(self, clean_build_env):
        # Render sets the variable empty rather than absent in some contexts.
        clean_build_env.setenv("RENDER_GIT_COMMIT", "   ")
        clean_build_env.setenv("OFE_RELEASE_SHA", SHA_B)
        assert build_info_module.release_sha() == SHA_B

    def test_unknown_when_nothing_is_provided(self, clean_build_env):
        assert build_info_module.release_sha() is None
        assert build_info_module.release_sha_short() is None

    @pytest.mark.parametrize(
        "garbage",
        [
            "",
            "   ",
            "unknown",
            "dev",
            "local",
            "$RENDER_GIT_COMMIT",
            "${VERCEL_GIT_COMMIT_SHA}",
            "main",
            "HEAD",
            "abc",  # too short to identify a commit
            "z" * 40,  # not hex
            "0" * 41,  # longer than a SHA
        ],
    )
    def test_non_sha_values_are_unknown_not_published(self, clean_build_env, garbage):
        # A placeholder that reaches the wire looks like provenance and proves
        # nothing, so anything not shaped like a commit is treated as absent.
        clean_build_env.setenv("RENDER_GIT_COMMIT", garbage)
        assert build_info_module.release_sha() is None

    def test_short_sha_is_seven_lowercase_hex(self, clean_build_env):
        clean_build_env.setenv("RENDER_GIT_COMMIT", SHA_A.upper())
        assert build_info_module.release_sha() == SHA_A
        assert build_info_module.release_sha_short() == SHA_A[:7]

    def test_does_not_invent_a_sha_from_the_local_checkout(self, clean_build_env):
        # The deployed artifact has no .git dir; a locally computed SHA would
        # describe the machine running the test, not the running build.
        local = _local_git_sha()
        assert local is not None, "test setup: expected a git checkout here"
        assert build_info_module.release_sha() is None
        assert build_info_module.release_sha() != local

    def test_module_never_shells_out_for_a_sha(self):
        source = Path(build_info_module.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith(("#", "*"))
        )
        for forbidden in ("rev-parse", "subprocess", "os.popen", "check_output"):
            assert forbidden not in code, f"build_info must not compute the SHA ({forbidden})"


class TestEnvironmentLabel:
    def test_unknown_by_default(self, clean_build_env):
        assert build_info_module.environment() == "unknown"

    def test_render_runtime_identifies_itself(self, clean_build_env):
        clean_build_env.setenv("RENDER", "true")
        assert build_info_module.environment() == "render"

    def test_explicit_label_for_hosts_that_do_not(self, clean_build_env):
        clean_build_env.setenv("OFE_ENVIRONMENT", "staging")
        assert build_info_module.environment() == "staging"

    def test_never_infers_production(self, clean_build_env):
        clean_build_env.setenv("RENDER", "false")
        assert build_info_module.environment() == "unknown"


class TestStartedAt:
    def test_is_timezone_aware_iso(self):
        parsed = datetime.fromisoformat(build_info_module.started_at())
        assert parsed.tzinfo is not None

    def test_is_process_start_not_now(self):
        # Two reads must agree: a per-call now() would hide whether a deploy
        # actually restarted the instance.
        assert build_info_module.started_at() == build_info_module.started_at()


class TestHealthReportsTheBuild:
    def test_reports_the_sha_render_deployed(self, clean_build_env):
        clean_build_env.setenv("RENDER_GIT_COMMIT", SHA_A)
        body = client.get("/api/health").json()
        assert body["release_sha"] == SHA_A

    def test_reports_the_explicit_override(self, clean_build_env):
        clean_build_env.setenv("OFE_RELEASE_SHA", SHA_B)
        body = client.get("/api/health").json()
        assert body["release_sha"] == SHA_B

    def test_reports_null_when_nothing_is_known(self, clean_build_env):
        body = client.get("/api/health").json()
        assert body["release_sha"] is None
        assert body["environment"] == "unknown"

    def test_does_not_invent_a_sha_on_the_wire(self, clean_build_env):
        local = _local_git_sha()
        raw = client.get("/api/health").text
        assert '"release_sha":null' in raw.replace(" ", "")
        if local:
            assert local not in raw
            assert local[:7] not in raw

    def test_existing_shape_is_untouched(self, clean_build_env):
        # Three consumers depend on these two keys: the frontend wakeBackend
        # probe, the Playwright webServer readiness gate, and
        # tests/test_async_route_isolation.
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["version"] == API_VERSION == "2.7.0"

    def test_payload_is_exactly_build_metadata(self, clean_build_env):
        clean_build_env.setenv("RENDER_GIT_COMMIT", SHA_A)
        body = client.get("/api/health").json()
        assert set(body) == {"status", "version", "release_sha", "environment", "started_at"}

    def test_leaks_no_other_environment_variable(self, clean_build_env):
        # /api/health is unauthenticated: it may carry build identity and
        # nothing else, so a sentinel planted in the process environment must
        # not appear in the response by any route.
        sentinels = {
            "SUPABASE_SERVICE_ROLE_KEY": "sentinel-service-role-key",
            "OPENAI_API_KEY": "sentinel-openai-key",
            "ADMIN_TOKEN": "sentinel-admin-token",
            "RENDER_SERVICE_NAME": "sentinel-service-name",
            "RENDER_EXTERNAL_URL": "https://sentinel.example.com",
            "DATABASE_URL": "postgres://sentinel",
        }
        for name, value in sentinels.items():
            clean_build_env.setenv(name, value)
        clean_build_env.setenv("RENDER_GIT_COMMIT", SHA_A)

        raw = client.get("/api/health").text
        for value in sentinels.values():
            assert value not in raw
        for key in client.get("/api/health").json():
            assert not any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))

    def test_environment_is_reported_when_the_host_says_so(self, clean_build_env):
        clean_build_env.setenv("RENDER", "true")
        clean_build_env.setenv("RENDER_GIT_COMMIT", SHA_A)
        body = client.get("/api/health").json()
        assert body["environment"] == "render"


class TestBuildInfoRecord:
    def test_carries_every_field_including_unknowns(self, clean_build_env):
        record = build_info_module.build_info()
        assert record == {
            "release_sha": None,
            "release_sha_short": None,
            "build_version": "2.7.0",
            "environment": "unknown",
            "started_at": build_info_module.started_at(),
        }

    def test_build_version_is_the_api_version(self):
        assert build_info_module.build_version() == API_VERSION


# ---------------------------------------------------------------------------
# Vercel deploy gate
# ---------------------------------------------------------------------------


def _vercel_config() -> dict:
    return json.loads(_VERCEL_JSON.read_text(encoding="utf-8"))


class TestVercelInstallIsLockfileExact:
    def test_installs_from_the_lockfile_like_ci(self):
        # CI runs `npm ci`. With `npm install`, Vercel re-resolved the 33 caret
        # ranges in package.json at deploy time, so production could run
        # dependency versions no CI job ever tested.
        assert _vercel_config()["installCommand"] == "npm ci"

    def test_lockfile_exists_for_npm_ci_to_use(self):
        assert (_REPO / "frontend" / "package-lock.json").is_file()

    def test_build_command_unchanged(self):
        assert _vercel_config()["buildCommand"] == "npm run build"


class TestVercelCiGate:
    def test_an_ignore_command_is_configured(self):
        # Render waits for checks (render.yaml autoDeployTrigger: checksPass);
        # Vercel had no gate at all.
        assert "ignoreCommand" in _vercel_config()

    def test_ignore_command_points_at_a_script_that_exists(self):
        command = _vercel_config()["ignoreCommand"]
        assert command == "node scripts/vercel-ignore-build.mjs"
        # Resolved relative to the Vercel project root (frontend/).
        assert _IGNORE_SCRIPT.is_file()


_CHECK_NAMES = [
    "Backend (lint + pytest)",
    "Frontend (typecheck + build)",
    "Migrations (Flow B merge + CLI replay)",
    "E2E (Playwright)",
]


class _StubGitHub:
    """Serves one canned check-runs payload for the ignore script to read."""

    def __init__(self, payload: dict):
        body = json.dumps(payload).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    def __enter__(self) -> str:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def _checks(conclusion: str, status: str = "completed") -> dict:
    return {
        "total_count": len(_CHECK_NAMES),
        "check_runs": [
            {"name": name, "status": status, "conclusion": conclusion}
            for name in _CHECK_NAMES
        ],
    }


def _run_gate(env: dict) -> subprocess.CompletedProcess:
    base = {
        "PATH": os.environ.get("PATH", ""),
        "VERCEL_ENV": "production",
        "VERCEL_GIT_REPO_OWNER": "EricXu-0805",
        "VERCEL_GIT_REPO_SLUG": "opportunity-filter-engine",
        "VERCEL_GIT_COMMIT_SHA": SHA_A,
        "OFE_VERCEL_CI_WAIT_SECONDS": "0",
    }
    base.update(env)
    return subprocess.run(
        ["node", str(_IGNORE_SCRIPT)],
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the gate")
class TestVercelCiGateBehaviour:
    """Exit codes are inverted (0 = skip, 1 = build), so pin both directions:
    a gate that always exits 1 is the bug it was written to fix, and one that
    always exits 0 silently stops all deploys."""

    def test_skips_the_production_build_when_required_checks_are_red(self):
        with _StubGitHub(_checks("failure")) as api:
            result = _run_gate({"OFE_GITHUB_API_BASE": api})
        assert result.returncode == 0, result.stdout + result.stderr
        assert "SKIP" in result.stdout

    def test_builds_when_every_required_check_passed(self):
        with _StubGitHub(_checks("success")) as api:
            result = _run_gate({"OFE_GITHUB_API_BASE": api})
        assert result.returncode == 1, result.stdout + result.stderr
        assert "BUILD" in result.stdout

    def test_one_red_check_among_greens_still_skips(self):
        payload = _checks("success")
        payload["check_runs"][2] = {
            "name": _CHECK_NAMES[2],
            "status": "completed",
            "conclusion": "failure",
        }
        with _StubGitHub(payload) as api:
            result = _run_gate({"OFE_GITHUB_API_BASE": api})
        assert result.returncode == 0
        assert _CHECK_NAMES[2] in result.stdout

    def test_pending_checks_fall_open_and_say_so(self):
        # The honest limitation: the ignore step runs seconds after the push
        # while CI (~20-35 min) is queued, and is never re-evaluated. Failing
        # closed here would freeze production deploys permanently.
        with _StubGitHub(_checks(None, status="in_progress")) as api:
            result = _run_gate({"OFE_GITHUB_API_BASE": api})
        assert result.returncode == 1
        assert "UNGATED" in result.stdout

    def test_missing_required_check_is_not_treated_as_green(self):
        payload = _checks("success")
        payload["check_runs"] = payload["check_runs"][:2]
        with _StubGitHub(payload) as api:
            result = _run_gate({"OFE_GITHUB_API_BASE": api})
        assert result.returncode == 1
        assert "UNGATED" in result.stdout

    def test_unrelated_green_checks_cannot_stand_in_for_the_required_ones(self):
        payload = {
            "total_count": 2,
            "check_runs": [
                {"name": "refresh", "status": "completed", "conclusion": "success"},
                {"name": "ping", "status": "completed", "conclusion": "success"},
            ],
        }
        with _StubGitHub(payload) as api:
            result = _run_gate({"OFE_GITHUB_API_BASE": api})
        assert result.returncode == 1
        assert "UNGATED" in result.stdout

    def test_preview_deployments_are_left_alone(self):
        result = _run_gate({"VERCEL_ENV": "preview", "OFE_GITHUB_API_BASE": "http://127.0.0.1:1"})
        assert result.returncode == 1
        assert "production only" in result.stdout

    def test_unreachable_check_api_falls_open_loudly(self):
        result = _run_gate({"OFE_GITHUB_API_BASE": "http://127.0.0.1:1"})
        assert result.returncode == 1
        assert "unavailable" in result.stdout

    def test_unidentifiable_commit_falls_open_loudly(self):
        result = _run_gate({"VERCEL_GIT_COMMIT_SHA": ""})
        assert result.returncode == 1
        assert "cannot identify the commit" in result.stdout


class TestFrontendBuildPlumbing:
    """The client SHA only reaches the bundle if next.config.js inlines it —
    not something the frontend unit tests can observe after the fact."""

    def test_next_config_inlines_the_vercel_commit(self):
        source = (_REPO / "frontend" / "next.config.js").read_text(encoding="utf-8")
        assert "VERCEL_GIT_COMMIT_SHA" in source
        assert "OFE_RELEASE_SHA" in source
        assert "NEXT_PUBLIC_RELEASE_SHA" in source

    def test_root_layout_publishes_the_sha(self):
        source = (_REPO / "frontend" / "src" / "app" / "layout.tsx").read_text(encoding="utf-8")
        assert "data-release-sha" in source
