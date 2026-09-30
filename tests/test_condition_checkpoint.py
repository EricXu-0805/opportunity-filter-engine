"""Small-file checks for bounded full-corpus checkpointing and recovery."""

import json
from copy import deepcopy

import pytest

from src.collectors import refresh_all
from tests.test_refresh_all import _stub_with_processed_file


def test_hundred_changes_make_five_full_snapshots_and_clean_flush_is_noop(monkeypatch, tmp_path):
    path = tmp_path / "opportunities.json"
    records = [{"id": "target", "value": 0}, {"id": "untouched", "value": "original"}]
    writes = []
    real_write = refresh_all.atomic_write_json

    def write(target, payload):
        writes.append(deepcopy(payload))
        real_write(target, payload)

    monkeypatch.setattr(refresh_all, "atomic_write_json", write)
    checkpoint = refresh_all._ConditionCheckpoint(path, records, clock=lambda: 0)
    for value in range(1, 101):
        records[0]["value"] = value
        checkpoint()
    checkpoint.flush()
    assert [snapshot[0]["value"] for snapshot in writes] == [20, 40, 60, 80, 100]
    assert all(snapshot[1] == records[1] for snapshot in writes)
    assert json.loads(path.read_text()) == records
    assert checkpoint.pending == 0


def test_unchanged_checkpoint_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(refresh_all, "atomic_write_json", lambda *a: pytest.fail("No changes to write"))
    checkpoint = refresh_all._ConditionCheckpoint(tmp_path / "unused.json", [], clock=lambda: 0)
    checkpoint.flush()
    assert checkpoint.pending == 0


def test_elapsed_interval_flushes_before_page_batch_threshold(monkeypatch, tmp_path):
    now = [0]
    writes = []
    records = [{"id": "target", "value": 0}]
    monkeypatch.setattr(refresh_all, "atomic_write_json", lambda path, payload: writes.append(deepcopy(payload)))
    checkpoint = refresh_all._ConditionCheckpoint(tmp_path / "opportunities.json", records, clock=lambda: now[0])
    checkpoint()
    now[0] = 59
    checkpoint()
    assert writes == [] and checkpoint.pending == 2
    now[0] = 60
    records[0]["value"] = 3
    checkpoint()
    assert writes == [records] and checkpoint.pending == 0
    now[0] = 119
    checkpoint()
    assert len(writes) == 1
    now[0] = 120
    checkpoint()
    assert len(writes) == 2


def test_failed_batch_preserves_pending_retry_and_original_exception_after_current_page_rollback(monkeypatch, tmp_path):
    path = tmp_path / "opportunities.json"
    records = [{"id": "target", "value": 0}, {"id": "untouched", "value": "original"}]
    path.write_text(json.dumps(records))
    calls = []
    real_write = refresh_all.atomic_write_json

    def write(target, payload):
        calls.append(deepcopy(payload))
        if len(calls) == 1:
            raise OSError("synthetic disk failure")
        real_write(target, payload)

    monkeypatch.setattr(refresh_all, "atomic_write_json", write)
    checkpoint = refresh_all._ConditionCheckpoint(path, records, clock=lambda: 0)
    with pytest.raises(OSError, match="synthetic disk failure"):
        try:
            for value in range(1, 21):
                before = records[0]["value"]
                records[0]["value"] = value
                try:
                    checkpoint()
                except Exception:
                    assert checkpoint.pending == 20
                    # The real runner rolls back its current page on persist failure.
                    records[0]["value"] = before
                    raise
        finally:
            checkpoint.flush()
    assert [snapshot[0]["value"] for snapshot in calls] == [20, 19]
    assert json.loads(path.read_text()) == records
    assert records[0]["value"] == 19
    assert checkpoint.pending == 0


def test_failed_explicit_flush_keeps_prior_disk_and_pending_state(monkeypatch, tmp_path):
    path = tmp_path / "opportunities.json"
    path.write_text('[{"id":"old"}]')
    checkpoint = refresh_all._ConditionCheckpoint(path, [{"id": "new"}], clock=lambda: 0)
    checkpoint()

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(refresh_all, "atomic_write_json", fail)
    with pytest.raises(OSError):
        checkpoint.flush()
    assert checkpoint.pending == 1
    assert json.loads(path.read_text()) == [{"id": "old"}]


def test_actual_refresh_finally_flushes_buffered_changes_on_runner_failure(monkeypatch, tmp_path):
    selected = {
        "id": "target",
        "school": "uw",
        "source": "uw_faculty",
        "source_type": "faculty_research",
        "metadata": {"is_active": True, "value": 0},
    }
    untouched = {
        "id": "other",
        "school": "uiuc",
        "source": "uiuc_faculty",
        "source_type": "faculty_research",
        "metadata": {"is_active": True, "value": "original"},
    }
    path = _stub_with_processed_file(monkeypatch, tmp_path, [selected, untouched])

    def runner(records, *, persist, **kwargs):
        assert [record["id"] for record in records] == ["target"]
        for value in range(1, 20):
            records[0]["metadata"]["value"] = value
            persist()
        # Before the forced-finally flush there has been no full file write.
        assert json.loads(path.read_text())[0]["metadata"]["value"] == 0
        raise RuntimeError("synthetic runner failure")

    monkeypatch.setattr(refresh_all, "refresh_faculty_condition_sources", runner)
    with pytest.raises(RuntimeError, match="synthetic runner failure"):
        refresh_all.refresh_all(deep=True, schools={"uw"})
    stored = json.loads(path.read_text())
    assert stored[0]["metadata"]["value"] == 19
    assert stored[1] == untouched
