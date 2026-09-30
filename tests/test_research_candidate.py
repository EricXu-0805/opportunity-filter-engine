"""Synthetic Git repositories only: no live corpus, API, model, or mail."""
from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import refresh_artifact as artifacts
from scripts import research_candidate as candidate
from src.collectors import openalex_enrich as oa
from src.collectors.research_queue import canonical_sha256, research_binding_key, run_refresh

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
STAMP = NOW.isoformat().replace("+00:00", "Z")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def record(rid="uiuc-one", school="uiuc", aid="https://openalex.org/A123", name="Pat Lee"):
    return {"id": rid, "school": school, "pi_name": name, "source_type": "faculty_research",
            "source_url": "https://example.edu/people/" + rid, "department": "Computer Science",
            "title": "Unchanged professor title", "description": "Keep duplicate text.",
            "metadata": {"publication_author_id": aid, "publication_attribution_status": "verified_author_id",
                         "works_gate": 3, "recent_works": [{"title": "Legacy original", "year": 2025}],
                         "description_raw": "Keep duplicate text.", "custom": {"unchanged": ["研究", "🧪"]}}}


def snapshot(rec, empty=False):
    works = [] if empty else [{"work_id": "https://openalex.org/W123", "title": "Complete study 研究 🧪",
                              "year": 2026, "publication_date": "2026-08-01", "source_url": "https://doi.org/10.1234/study",
                              "doi": "https://doi.org/10.1234/study", "abstract": "Complete original abstract.",
                              "abstract_status": "present", "updated_date": "2026-09-01"}]
    return {"version": 1, "source": "openalex", **oa._research_binding(rec), "checked_at": STAMP, "works": works}


def target(rec, outcome="success_nonempty", reason=None):
    patch = None
    if outcome not in ("deferred", "conflict"):
        status = "success" if outcome.startswith("success_") else "incomplete" if outcome == "incomplete" else "failed"
        entry = {"binding": oa._research_binding(rec), "research_refresh": {"checked_at": STAMP, "status": status, "reason": reason}}
        if status == "success":
            entry["research_snapshot"] = snapshot(rec, empty=outcome == "success_empty")
        patch = {oa._person_key(rec): entry}
    return {"record_id": rec["id"], "school": rec["school"], "binding_key": research_binding_key(rec),
            "before_sha256": canonical_sha256(rec), "outcome": outcome, "reason": reason,
            "attempted": outcome not in ("deferred", "conflict", "identity_revoked"), "patch": patch}


def envelope(base, records, targets=None):
    targets = [target(records[0])] if targets is None else targets
    counts = dict.fromkeys(candidate._OUTCOMES, 0)
    for item in targets:
        counts[item["outcome"]] += 1
    return {"version": 1, "run_id": "local-research-47", "base_sha": base, "corpus_sha256": canonical_sha256(records),
            "settings": {"schools": sorted({r["school"] for r in records}), "limit": 25, "max_requests": 50,
                         "max_seconds": 120, "min_remaining": 0},
            "started_at": STAMP, "finished_at": (NOW + timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
            "status": "deferred" if counts["deferred"] else "completed", "request_count": 2 * sum(t["attempted"] for t in targets),
            "unknown_request_count": 0, "credits_observed": 0, "credit_accounting_complete": False, "cooldown_until": None,
            "counts": counts, "targets": targets}


def setup(tmp_path, records=None, other=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    records = records or [record()]
    by_school = {}
    for rec in [*records, *(other or [record("mit-other", "mit", "https://openalex.org/A999", "Morgan White")])]:
        by_school.setdefault(rec["school"], []).append(rec)
    for school, rows in by_school.items():
        write(repo / f"data/processed/shards/{school}.json", rows)
    git(repo, "init", "-q"); git(repo, "config", "user.name", "Candidate Test")
    git(repo, "config", "user.email", "candidate@fixture.invalid"); git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    run = envelope(git(repo, "rev-parse", "HEAD"), records)
    return repo, run, tmp_path / "candidate"


def build(repo, run, output):
    return candidate.build_candidate(run, repository_root=repo, output=output)


def verify(repo, output):
    return candidate.validate_candidate(output, repository_root=repo, expected_run_id="local-research-47")


def promote(repo, output):
    return candidate.promote_candidate(output, repository_root=repo, expected_run_id="local-research-47")


def test_build_validate_promote_and_exact_duplicate_preserve_unrelated_values(tmp_path):
    repo, run, output = setup(tmp_path)
    before = (repo / "data/processed/shards/uiuc.json").read_bytes()
    other = (repo / "data/processed/shards/mit.json").read_bytes()
    source = deepcopy(run)
    manifest = build(repo, run, output)
    assert run == source and (repo / "data/processed/shards/uiuc.json").read_bytes() == before
    assert verify(repo, output) == manifest
    assert not (output / artifacts.STATUS_RELATIVE).exists()
    assert promote(repo, output)["status"] == "applied"
    after = (repo / "data/processed/shards/uiuc.json").read_bytes()
    row = json.loads(after)[0]
    assert row["metadata"]["research_snapshot"]["works"][0]["abstract"] == "Complete original abstract."
    assert row["metadata"]["description_raw"] == "Keep duplicate text."
    assert row["metadata"]["custom"] == {"unchanged": ["研究", "🧪"]}
    assert (repo / "data/processed/shards/mit.json").read_bytes() == other
    assert promote(repo, output)["status"] == "already_applied"
    assert (repo / "data/processed/shards/uiuc.json").read_bytes() == after
    assert git(repo, "rev-parse", "HEAD") == run["base_sha"]


def test_same_person_key_does_not_authorize_unselected_sibling(tmp_path):
    first = record(); sibling = deepcopy(first); sibling["id"] = "uiuc-sibling"
    repo, run, output = setup(tmp_path, [first, sibling])
    build(repo, run, output); promote(repo, output)
    result = json.loads((repo / "data/processed/shards/uiuc.json").read_text())
    assert "research_snapshot" in result[0]["metadata"]
    assert result[1] == sibling


@pytest.mark.parametrize(("outcome", "reason"), [("failed", "request_failed"), ("incomplete", "round_limit"),
                                                   ("needs_review", "invalid_response"), ("identity_revoked", "identity_revoked")])
def test_non_success_retains_last_success_without_renewal(tmp_path, outcome, reason):
    rec = record(); old = snapshot(rec); old["checked_at"] = "2026-09-01T00:00:00Z"
    rec["metadata"]["research_snapshot"] = old
    repo, run, output = setup(tmp_path, [rec])
    run = envelope(run["base_sha"], [rec], [target(rec, outcome, reason)])
    build(repo, run, output); promote(repo, output)
    md = json.loads((repo / "data/processed/shards/uiuc.json").read_text())[0]["metadata"]
    assert md["research_snapshot"] == old and md["recent_works"] == rec["metadata"]["recent_works"]
    assert md["research_refresh"]["reason"] == reason
    assert ("publication_attribution_status" in md) == (outcome != "identity_revoked")


def test_success_empty_clears_legacy_titles_without_erasing_other_fields(tmp_path):
    rec = record(); repo, run, output = setup(tmp_path, [rec])
    run = envelope(run["base_sha"], [rec], [target(rec, "success_empty")])
    build(repo, run, output); promote(repo, output)
    row = json.loads((repo / "data/processed/shards/uiuc.json").read_text())[0]
    assert row["metadata"]["research_snapshot"]["works"] == row["metadata"]["recent_works"] == []
    assert row["description"] == rec["description"]


def test_mixed_run_only_changes_records_with_valid_patches(tmp_path):
    first = record(); second = record("uiuc-two", aid="https://openalex.org/A124", name="Riley White")
    repo, run, output = setup(tmp_path, [first, second])
    run = envelope(run["base_sha"], [first, second], [target(first), target(second, "deferred", "request_budget")])
    build(repo, run, output); promote(repo, output)
    assert json.loads((repo / "data/processed/shards/uiuc.json").read_text())[1] == second


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(version=True), lambda r: r.update(extra="not accepted"),
    lambda r: r.update(status="running", finished_at=None), lambda r: r.update(status="deferred"), lambda r: r.update(base_sha="A" * 40),
    lambda r: r.update(corpus_sha256="bad"), lambda r: r.update(request_count=0),
    lambda r: r.update(unknown_request_count=True),
    lambda r: r.update(unknown_request_count=1, credit_accounting_complete=True),
    lambda r: r.update(unknown_request_count=3),
    lambda r: r.update(credits_observed=float("nan")), lambda r: r["counts"].update(success_nonempty=2),
    lambda r: r["settings"].update(limit=True), lambda r: r["targets"].append(deepcopy(r["targets"][0])),
    lambda r: r["targets"][0].update(school="mit"), lambda r: r["targets"][0].update(before_sha256="0" * 64),
    lambda r: r["targets"][0].update(binding_key="0" * 64), lambda r: r["targets"][0].update(outcome="deferred"),
    lambda r: r["targets"][0].update(patch=None), lambda r: r["targets"][0].update(attempted=False),
])
def test_invalid_envelopes_refuse_before_output_or_repository_write(tmp_path, mutation):
    repo, run, output = setup(tmp_path)
    before = git(repo, "status", "--porcelain")
    mutation(run)
    with pytest.raises(ValueError): build(repo, run, output)
    assert not output.exists() and git(repo, "status", "--porcelain") == before


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(extra="forbidden"), lambda p: p["binding"].update(author_id="https://openalex.org/A8"),
    lambda p: p["research_snapshot"].update(identity_name="Someone Else"),
    lambda p: p["research_snapshot"].update(works=[]),
    lambda p: p["research_refresh"].update(status="failed", reason="request_failed"),
    lambda p: p["research_refresh"].update(checked_at="2026-09-19T00:00:00Z"),
    lambda p: p["research_snapshot"]["works"][0].update(abstract="x" * 12001),
])
def test_invalid_patch_contract_refuses_without_partial_candidate(tmp_path, mutation):
    repo, run, output = setup(tmp_path)
    mutation(next(iter(run["targets"][0]["patch"].values())))
    with pytest.raises(ValueError): build(repo, run, output)
    assert not output.exists() and not git(repo, "status", "--porcelain")


@pytest.mark.parametrize("where", ["build", "verify", "promote"])
def test_target_shard_change_cannot_be_overwritten(tmp_path, where):
    repo, run, output = setup(tmp_path)
    if where != "build": build(repo, run, output)
    path = repo / "data/processed/shards/uiuc.json"
    rows = json.loads(path.read_text()); rows[0]["department"] = "Different Department"; write(path, rows)
    changed = path.read_bytes()
    with pytest.raises(ValueError, match="destination_changed"):
        if where == "build": build(repo, run, output)
        elif where == "verify": verify(repo, output)
        else: promote(repo, output)
    assert path.read_bytes() == changed


def test_new_unrelated_shard_update_and_descendant_commit_are_preserved(tmp_path):
    repo, run, output = setup(tmp_path); build(repo, run, output)
    path = repo / "data/processed/shards/mit.json"
    rows = json.loads(path.read_text()); rows[0]["title"] = "Latest unrelated work"; write(path, rows)
    git(repo, "add", "."); git(repo, "commit", "-qm", "unrelated update")
    unrelated = path.read_bytes()
    verify(repo, output); promote(repo, output)
    assert path.read_bytes() == unrelated


def test_new_cross_school_author_collision_blocks_current_candidate(tmp_path):
    repo, run, output = setup(tmp_path); build(repo, run, output)
    path = repo / "data/processed/shards/mit.json"
    rows = json.loads(path.read_text()); rows[0]["metadata"]["publication_author_id"] = "https://openalex.org/A123"
    write(path, rows)
    with pytest.raises(ValueError, match="author_collision"): promote(repo, output)
    assert not json.loads((repo / "data/processed/shards/uiuc.json").read_text())[0]["metadata"].get("research_snapshot")


def test_revocation_can_remove_trust_for_known_colliding_author(tmp_path):
    first, other = record(), record("mit-two", "mit", "https://openalex.org/A123", "Morgan White")
    repo, run, output = setup(tmp_path, [first], [other])
    run = envelope(run["base_sha"], [first], [target(first, "identity_revoked", "identity_revoked")])
    build(repo, run, output); promote(repo, output)
    assert "publication_attribution_status" not in json.loads((repo / "data/processed/shards/uiuc.json").read_text())[0]["metadata"]


@pytest.mark.parametrize("mode", ["shard", "shard_and_hash", "run", "extra", "symlink", "duplicate_json_key"])
def test_artifact_tampering_fails_closed(tmp_path, mode):
    repo, run, output = setup(tmp_path); build(repo, run, output)
    path = output / "data/processed/shards/uiuc.json"
    if mode in ("shard", "shard_and_hash"):
        rows = json.loads(path.read_text()); rows[0]["title"] = "Unrelated forged title"; write(path, rows)
        if mode == "shard_and_hash":
            manifest = json.loads((output / candidate.MANIFEST).read_text())
            manifest["shards"]["data/processed/shards/uiuc.json"]["after"].update(candidate._digest(path.read_bytes()))
            write(output / candidate.MANIFEST, manifest)
    elif mode == "run":
        altered = json.loads((output / candidate.RUN_FILE).read_text()); altered["run_id"] = "other-run"; write(output / candidate.RUN_FILE, altered)
    elif mode == "extra": (output / "unexpected.txt").write_text("no")
    elif mode == "symlink": path.unlink(); path.symlink_to(repo / "data/processed/shards/uiuc.json")
    else:
        raw = (output / candidate.RUN_FILE).read_text()
        (output / candidate.RUN_FILE).write_text('{"version":1,' + raw[1:])
    with pytest.raises(ValueError): promote(repo, output)
    assert not git(repo, "status", "--porcelain")


def test_run_id_and_existing_output_are_not_guessed_or_overwritten(tmp_path):
    repo, run, output = setup(tmp_path); build(repo, run, output)
    original = (output / candidate.MANIFEST).read_bytes()
    with pytest.raises(ValueError): build(repo, run, output)
    with pytest.raises(ValueError): candidate.validate_candidate(output, repository_root=repo, expected_run_id="wrong")
    assert (output / candidate.MANIFEST).read_bytes() == original


def test_only_deferred_is_no_candidate_not_a_successful_empty_publication(tmp_path):
    rec = record(); repo, run, output = setup(tmp_path, [rec])
    run = envelope(run["base_sha"], [rec], [target(rec, "deferred", "time_budget")])
    with pytest.raises(ValueError, match="no_changes"): build(repo, run, output)
    assert not output.exists()


def test_newer_success_rejects_old_attempt_without_renewing(tmp_path):
    rec = record(); rec["metadata"]["research_snapshot"] = snapshot(rec)
    rec["metadata"]["research_snapshot"]["checked_at"] = "2026-09-21T00:00:00Z"
    repo, run, output = setup(tmp_path, [rec])
    with pytest.raises(ValueError, match="patch_refused"): build(repo, run, output)


def test_staged_source_swap_is_rejected(tmp_path, monkeypatch):
    repo, run, output = setup(tmp_path); build(repo, run, output)
    original = artifacts._stage_copy
    def changed(source, destination):
        staged = original(source, destination)
        rows = json.loads(staged.read_text()); rows[0]["title"] = "Staging race"; write(staged, rows)
        return staged
    monkeypatch.setattr(artifacts, "_stage_copy", changed)
    with pytest.raises(ValueError, match="staged_content_changed"): promote(repo, output)
    assert not git(repo, "status", "--porcelain")


def test_target_change_during_staging_is_rejected(tmp_path, monkeypatch):
    repo, run, output = setup(tmp_path); build(repo, run, output)
    original = artifacts._stage_copy
    def changed(source, destination):
        staged = original(source, destination)
        rows = json.loads(destination.read_text()); rows[0]["title"] = "Concurrent new input"; write(destination, rows)
        return staged
    monkeypatch.setattr(artifacts, "_stage_copy", changed)
    with pytest.raises(ValueError, match="destination_changed"): promote(repo, output)
    assert json.loads((repo / "data/processed/shards/uiuc.json").read_text())[0]["title"] == "Concurrent new input"


def test_install_failure_rolls_back_all_shards(tmp_path, monkeypatch):
    first, second = record(), record("mit-two", "mit", "https://openalex.org/A125", "Riley White")
    repo, run, output = setup(tmp_path, [first, second], [])
    run = envelope(run["base_sha"], [first, second], [target(first), target(second)])
    build(repo, run, output)
    original = artifacts.os.replace
    failed = False
    def failure(source, destination):
        nonlocal failed
        if not failed and Path(source).name.endswith(".tmp") and Path(destination).name == "uiuc.json":
            failed = True
            raise OSError("controlled fixture failure")
        return original(source, destination)
    monkeypatch.setattr(artifacts.os, "replace", failure)
    with pytest.raises(OSError): promote(repo, output)
    assert failed and not git(repo, "status", "--porcelain")


def test_publication_lock_refuses_competing_writer(tmp_path):
    repo, run, output = setup(tmp_path); build(repo, run, output)
    _, common = artifacts._validate_apply_repository(repo, run["base_sha"])
    with artifacts._publication_lock(common), pytest.raises(ValueError, match="in progress"):
        promote(repo, output)
    assert not git(repo, "status", "--porcelain")


def test_real_runner_fixture_envelope_builds_and_promotes_without_network(tmp_path):
    rec = record(); repo, initial, output = setup(tmp_path, [rec])
    calls = []
    def transport(params, *, url, timeout):
        calls.append(url)
        if "/authors/" in url:
            data = {"id": "https://openalex.org/A123", "display_name": "Pat Lee",
                    "affiliations": [{"institution": {"id": "https://openalex.org/I157725225"}}],
                    "topics": [{"field": {"display_name": "Computer Science"}}]}
        else:
            data = {"results": [], "meta": {"count": 0}}
        return data, None, {"http_status": 200, "retry_after_seconds": None, "credits_used": 1,
                            "remaining": 100, "reset_seconds": None}
    run = run_refresh([rec], state_path=tmp_path / "state.sqlite", run_id="local-research-47",
                      base_sha=initial["base_sha"], schools=["uiuc"], now=NOW,
                      clock=lambda: NOW.timestamp(), transport=transport)
    assert len(calls) == 2 and run["targets"][0]["outcome"] == "success_empty"
    build(repo, run, output); verify(repo, output); promote(repo, output)
    assert len(calls) == 2
    assert json.loads((repo / "data/processed/shards/uiuc.json").read_text())[0]["metadata"]["recent_works"] == []


def test_review_reason_must_match_the_actual_patch_reason(tmp_path):
    rec = record(); repo, run, output = setup(tmp_path, [rec])
    run = envelope(run["base_sha"], [rec], [target(rec, "needs_review", "invalid_response")])
    run["targets"][0]["reason"] = "client_error"
    with pytest.raises(ValueError, match="outcome_mismatch"): build(repo, run, output)
    assert not output.exists()


@pytest.mark.parametrize("field,value", [("pi_name", None), ("source_url", "not-a-url")])
def test_even_failure_patch_requires_a_currently_eligible_selected_record(tmp_path, field, value):
    rec = record(); rec[field] = value
    repo, run, output = setup(tmp_path, [rec])
    run = envelope(run["base_sha"], [rec], [target(rec, "needs_review", "identity_unavailable")])
    with pytest.raises(ValueError): build(repo, run, output)
    assert not output.exists() and not git(repo, "status", "--porcelain")


def test_known_lost_request_count_is_preserved_as_incomplete_accounting(tmp_path):
    repo, run, output = setup(tmp_path)
    run["unknown_request_count"] = 1
    run["credit_accounting_complete"] = False
    build(repo, run, output)
    stored = json.loads((output / candidate.RUN_FILE).read_text())
    assert stored["unknown_request_count"] == 1 and stored["credit_accounting_complete"] is False
    assert verify(repo, output)["run_id"] == run["run_id"]


def test_mixed_review_only_bad_source_retains_original_record(tmp_path):
    first = record(); second = record("uiuc-two", aid="https://openalex.org/A124", name="Riley White")
    second["source_url"] = "bad legacy source"
    repo, run, output = setup(tmp_path, [first, second])
    review = target(second, "deferred", "invalid_source_url")
    review.update(outcome="needs_review")
    run = envelope(run["base_sha"], [first, second], [target(first), review])
    build(repo, run, output); promote(repo, output)
    rows = json.loads((repo / "data/processed/shards/uiuc.json").read_text())
    assert rows[1] == second and rows[0]["metadata"]["research_snapshot"]["works"]
