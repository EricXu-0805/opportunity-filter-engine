import json

import pytest

from scripts.verify_refresh_pr import REQUIRED_CHECKS, main, verify_snapshot

HEAD = "a" * 40
BASE = "b" * 40


def _snapshot(*, head=HEAD, base=BASE, checks=None):
    if checks is None:
        checks = [
            {"name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}
            for name in REQUIRED_CHECKS
        ]
    return {
        "headRefOid": head,
        "baseRefOid": base,
        "statusCheckRollup": checks,
    }


def test_exact_candidate_with_four_green_checks_passes():
    result = verify_snapshot(
        _snapshot(),
        expected_head=HEAD,
        expected_base=BASE,
    )
    assert result == {name: "SUCCESS" for name in REQUIRED_CHECKS}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("head", "c" * 40, "head SHA"),
        ("base", "d" * 40, "base SHA"),
    ],
)
def test_commit_binding_is_fail_closed(field, value, message):
    snapshot = _snapshot(**{field: value})
    with pytest.raises(ValueError, match=message):
        verify_snapshot(snapshot, expected_head=HEAD, expected_base=BASE)


def test_missing_or_duplicate_required_check_is_rejected():
    checks = [
        {"name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}
        for name in REQUIRED_CHECKS[:-1]
    ]
    checks.append(dict(checks[0]))
    with pytest.raises(ValueError, match="registration mismatch"):
        verify_snapshot(
            _snapshot(checks=checks),
            expected_head=HEAD,
            expected_base=BASE,
        )


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [
        ("IN_PROGRESS", ""),
        ("COMPLETED", "FAILURE"),
        ("COMPLETED", "CANCELLED"),
        ("COMPLETED", "SKIPPED"),
    ],
)
def test_only_completed_success_is_merge_evidence(status, conclusion):
    checks = [
        {"name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}
        for name in REQUIRED_CHECKS
    ]
    checks[2] = {
        "name": REQUIRED_CHECKS[2],
        "status": status,
        "conclusion": conclusion,
    }
    with pytest.raises(ValueError, match="not a completed success"):
        verify_snapshot(
            _snapshot(checks=checks),
            expected_head=HEAD,
            expected_base=BASE,
        )


def test_default_mode_rejects_pending_checks():
    checks = [
        {"name": name, "status": "QUEUED", "conclusion": ""}
        for name in REQUIRED_CHECKS
    ]
    with pytest.raises(ValueError, match="not a completed success"):
        verify_snapshot(
            _snapshot(checks=checks),
            expected_head=HEAD,
            expected_base=BASE,
        )


def test_explicit_registration_mode_allows_pending_but_not_wrong_commits():
    checks = [
        {"name": name, "status": "QUEUED", "conclusion": ""}
        for name in REQUIRED_CHECKS
    ]
    verify_snapshot(
        _snapshot(checks=checks),
        expected_head=HEAD,
        expected_base=BASE,
        require_success=False,
    )
    with pytest.raises(ValueError, match="head SHA"):
        verify_snapshot(
            _snapshot(head="c" * 40, checks=checks),
            expected_head=HEAD,
            expected_base=BASE,
            require_success=False,
        )


def test_cli_defaults_to_merge_safe_success_requirement(tmp_path):
    checks = [
        {"name": name, "status": "QUEUED", "conclusion": ""}
        for name in REQUIRED_CHECKS
    ]
    snapshot = tmp_path / "pr.json"
    snapshot.write_text(json.dumps(_snapshot(checks=checks)), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main([
            "--snapshot", str(snapshot),
            "--head", HEAD,
            "--base", BASE,
        ])
    assert exc.value.code == 2
    assert main([
        "--snapshot", str(snapshot),
        "--head", HEAD,
        "--base", BASE,
        "--registration-only",
    ]) == 0
