"""The alert drill: one labelled alert down the path every failure alert takes.

Every scheduled workflow ends in an "Alert operator" step that mails
OPERATOR_EMAIL through Resend and ends in `|| true`, so a failed send cannot
hide the failure being reported. The cost is that nothing ever shows an
alert arriving. The drill sends one on demand and fails when Resend refuses it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
_DRILL = "alert-drill.yml"
_ENDPOINT = "https://api.resend.com/emails"
_KEY = "re_fake_key_for_the_drill_test"
_OPERATOR = "operator@example.com"
_SENDER = "JoinALab <alerts@example.com>"


def _load(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(doc: dict) -> dict:
    # PyYAML resolves the bare key `on` to the boolean True.
    block = doc.get("on", doc.get(True))
    return block if isinstance(block, dict) else {block: None}


def _drill_step() -> dict:
    (job,) = _load(_DRILL)["jobs"].values()
    (step,) = job["steps"]
    return step


def _operator_alert_steps() -> dict[str, dict]:
    found = {}
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        for job in _load(path.name)["jobs"].values():
            for step in job["steps"]:
                if str(step.get("name", "")).startswith("Alert operator"):
                    found[path.name] = step
    return found


def test_the_drill_runs_only_when_someone_starts_it():
    """A schedule would mail the operator a drill on repeat, and push would
    send one on every merge."""
    assert set(_triggers(_load(_DRILL))) == {"workflow_dispatch"}


def test_the_drill_does_not_check_in_to_the_dead_mans_switch():
    """Only scheduled workflows have heartbeat rows; an unregistered name is
    answered 404, which would fail the drill for a reason unrelated to mail."""
    assert "/api/cron/heartbeat" not in (_WORKFLOWS / _DRILL).read_text(encoding="utf-8")


def test_the_drill_uses_the_same_secrets_sender_and_endpoint_as_the_alerts():
    alerts = _operator_alert_steps()
    assert len(alerts) >= 6, sorted(alerts)
    senders = set()
    for name, step in alerts.items():
        assert step["env"]["RESEND_API_KEY"] == "${{ secrets.RESEND_API_KEY }}", name
        assert step["env"]["OPERATOR_EMAIL"] == "${{ secrets.OPERATOR_EMAIL }}", name
        assert _ENDPOINT in step["run"], name
        senders.update(re.findall(r"\$\{\{ vars\.RESEND_FROM_EMAIL \|\| '[^']*' \}\}", step["run"]))
    (sender,) = senders

    drill = _drill_step()
    assert drill["env"]["RESEND_API_KEY"] == "${{ secrets.RESEND_API_KEY }}"
    assert drill["env"]["OPERATOR_EMAIL"] == "${{ secrets.OPERATOR_EMAIL }}"
    assert drill["env"]["MAIL_FROM"] == sender
    assert _ENDPOINT in drill["run"]
    assert "${{" not in drill["run"]


def _run_drill(tmp_path: Path, *, key: str = _KEY, operator: str = _OPERATOR,
               status: str = "200", curl_exit: int = 0,
               body: str = '{"id":"fake-email-id"}') -> tuple[subprocess.CompletedProcess, list]:
    """Run the step's script as GitHub runs it, against a curl that records
    its arguments, writes ``body`` to its -o file and answers ``status``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "curl.log"
    fake = bin_dir / "curl"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['FAKE_CURL_LOG'], 'a') as f:\n"
        "    f.write(json.dumps(args) + '\\n')\n"
        "if '-o' in args:\n"
        "    with open(args[args.index('-o') + 1], 'w') as f:\n"
        "        f.write(os.environ['FAKE_CURL_BODY'])\n"
        "if '-w' in args:\n"
        "    sys.stdout.write(os.environ['FAKE_CURL_STATUS'])\n"
        "sys.exit(int(os.environ['FAKE_CURL_EXIT']))\n"
    )
    fake.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "FAKE_CURL_LOG": str(log),
        "FAKE_CURL_STATUS": status,
        "FAKE_CURL_EXIT": str(curl_exit),
        "FAKE_CURL_BODY": body,
        "RESEND_API_KEY": key,
        "OPERATOR_EMAIL": operator,
        "MAIL_FROM": _SENDER,
        "RUN_URL": "https://github.com/owner/repo/actions/runs/1",
        "TRIGGERED_BY": "someone",
    }
    assert set(_drill_step()["env"]) <= set(env)
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _drill_step()["run"]],
        env=env, capture_output=True, text=True,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def _printed(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


def test_one_labelled_drill_alert_goes_to_the_operator(tmp_path):
    result, calls = _run_drill(tmp_path)
    assert result.returncode == 0, _printed(result)
    (argv,) = calls
    assert _ENDPOINT in argv
    assert argv[argv.index("-X") + 1] == "POST"
    assert f"Authorization: Bearer {_KEY}" in argv
    payload = json.loads(argv[argv.index("-d") + 1])
    assert payload["to"] == [_OPERATOR]
    assert payload["from"] == _SENDER
    assert payload["subject"].startswith("[DRILL] ")
    assert payload["text"].startswith("[DRILL] ")
    assert "Nothing failed" in payload["text"]
    assert "https://github.com/owner/repo/actions/runs/1" in payload["text"]
    # Resend accepting it is not the operator receiving it.
    assert "inbox" in result.stdout
    assert "fake-email-id" in result.stdout
    assert _KEY not in _printed(result)


def test_a_missing_secret_fails_the_drill_before_sending(tmp_path):
    for missing in ("RESEND_API_KEY", "OPERATOR_EMAIL"):
        run_dir = tmp_path / missing
        run_dir.mkdir()
        kwargs = {"key": ""} if missing == "RESEND_API_KEY" else {"operator": ""}
        result, calls = _run_drill(run_dir, **kwargs)
        assert result.returncode != 0, missing
        assert "::error::" in result.stdout and missing in result.stdout
        assert calls == []


def test_a_refused_send_fails_the_drill(tmp_path):
    result, _ = _run_drill(
        tmp_path, status="403",
        body='{"statusCode":403,"message":"The from domain is not verified"}')
    assert result.returncode != 0
    assert "::error::" in result.stdout and "403" in result.stdout
    assert "not verified" in result.stdout
    assert _KEY not in _printed(result)


def test_an_unreachable_resend_fails_the_drill(tmp_path):
    result, _ = _run_drill(tmp_path, status="000", curl_exit=6)
    assert result.returncode != 0
    assert "::error::" in result.stdout
