"""Read-only contact evidence corpus canary tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from backend.lib.contact_visibility import build_identity_bound_contact_evidence
from scripts import contact_evidence_canary as canary
from scripts.contact_evidence_canary import audit_records, load_records, main

NOW = datetime.now(UTC).replace(microsecond=0)


def _record(
    record_id: str,
    email: str,
    *,
    verified_at: datetime = NOW,
    pi_name: str = "Ada Lovelace",
) -> dict:
    evidence = build_identity_bound_contact_evidence(
        email=email,
        email_source="bound_directory_card",
        contact_source_url="https://directory.berkeley.edu/faculty",
        contact_verified_at=verified_at,
    )
    assert evidence is not None
    return {
        "id": record_id,
        "pi_name": pi_name,
        "contact_email": email,
        "metadata": evidence,
    }


def test_audit_separates_fresh_stale_partial_mismatch_and_legacy():
    fresh = _record("fresh", "ada@berkeley.edu")
    stale = _record(
        "stale",
        "grace@berkeley.edu",
        verified_at=NOW - timedelta(days=61),
    )
    partial = _record("partial", "barbara@berkeley.edu")
    partial["metadata"].pop("contact_source_url")
    mismatch = _record("mismatch", "katherine@berkeley.edu")
    mismatch["metadata"]["contact_verified_email"] = "other@berkeley.edu"
    invalid = _record("invalid", "margaret@berkeley.edu")
    invalid["metadata"]["contact_source_url"] = "http://localhost/person"
    legacy = {
        "id": "legacy",
        "contact_email": "legacy@berkeley.edu",
        "metadata": {"email_source": "profile_page"},
    }

    report = audit_records(
        [fresh, stale, partial, mismatch, invalid, legacy],
        now=NOW,
    )
    assert report["records"] == 6
    assert report["records_with_email"] == 6
    assert report["legacy_email_source"] == 1
    assert report["evidence_status"] == {
        "fresh": 1,
        "stale": 1,
        "partial": 1,
        "mismatch": 1,
        "invalid": 1,
        "none": 1,
    }
    assert report["fresh_by_source"] == {"bound_directory_card": 1}


def test_audit_flags_one_fresh_email_bound_to_two_record_identities():
    report = audit_records(
        [
            _record("ada-one", "ada@berkeley.edu", pi_name="Ada Lovelace"),
            _record("ada-two", "ada@berkeley.edu", pi_name="Grace Hopper"),
        ],
        now=NOW,
    )
    assert report["evidence_status"]["fresh"] == 2
    assert report["duplicate_fresh_emails"] == [{
        "email": "ada@berkeley.edu",
        "identities": ["ada lovelace", "grace hopper"],
    }]
    assert report["duplicate_record_ids"] == []


def test_duplicate_id_and_person_identity_are_audited_independently():
    same_person = [
        _record("ada-one", "ada@berkeley.edu", pi_name="Ada Lovelace"),
        _record("ada-two", "ada@berkeley.edu", pi_name="Ada Lovelace"),
    ]
    report = audit_records(same_person, now=NOW)
    assert report["duplicate_fresh_emails"] == []
    assert report["duplicate_record_ids"] == []

    duplicate_id = [
        _record("shared-id", "ada@berkeley.edu", pi_name="Ada Lovelace"),
        _record("shared-id", "grace@berkeley.edu", pi_name="Grace Hopper"),
    ]
    report = audit_records(duplicate_id, now=NOW)
    assert report["duplicate_record_ids"] == ["shared-id"]


def test_load_and_cli_are_read_only_and_enforce_thresholds(tmp_path, capsys):
    corpus = tmp_path / "fixture.json"
    payload = [_record("fresh", "ada@berkeley.edu")]
    corpus.write_text(json.dumps(payload), encoding="utf-8")
    before = corpus.read_bytes()

    assert load_records([corpus]) == payload
    assert main([str(corpus), "--json", "--min-fresh", "1"]) == 0
    assert main([str(corpus), "--min-fresh", "2"]) == 1
    assert corpus.read_bytes() == before
    assert '"fresh": 1' in capsys.readouterr().out


def test_cli_fail_on_invalid(tmp_path):
    corpus = tmp_path / "fixture.json"
    partial = _record("partial", "ada@berkeley.edu")
    partial["metadata"].pop("contact_verified_at")
    corpus.write_text(json.dumps([partial]), encoding="utf-8")
    assert main([str(corpus), "--fail-on-invalid"]) == 1

    stale = _record(
        "stale",
        "ada@berkeley.edu",
        verified_at=NOW - timedelta(days=61),
    )
    corpus.write_text(json.dumps([stale]), encoding="utf-8")
    assert main([str(corpus), "--fail-on-invalid"]) == 1


def test_bound_source_without_rest_of_bundle_is_partial():
    report = audit_records([{
        "id": "partial",
        "contact_email": "ada@berkeley.edu",
        "metadata": {"email_source": "bound_directory_card"},
    }], now=NOW)
    assert report["evidence_status"]["partial"] == 1
    assert report["legacy_email_source"] == 0


def test_default_path_mirrors_runtime_assembled_precedence(tmp_path, monkeypatch):
    assembled = tmp_path / "opportunities.json"
    shards = tmp_path / "shards"
    shards.mkdir()
    monkeypatch.setattr(canary, "DEFAULT_ASSEMBLED_CORPUS", assembled)
    monkeypatch.setattr(canary, "DEFAULT_SHARD_CORPUS", shards)

    assert canary.default_runtime_corpus_path() == shards
    assembled.write_text("[]", encoding="utf-8")
    assert canary.default_runtime_corpus_path() == assembled
