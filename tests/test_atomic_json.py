from __future__ import annotations

import json
import os
import re
import stat
from datetime import date
from pathlib import Path

import pytest

from src.collectors import atomic_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Every corpus/shard writer converted to the atomic layer. A refresh killed
# mid-write once truncated opportunities.json 293MB -> 106MB; this list keeps
# any of these paths from quietly regressing to an in-place open("w") dump.
_AUTOMATIC_CORPUS_WRITERS = (
    "scripts/minify_corpus.py",
    "scripts/shard_corpus.py",
    "src/collectors/campus_graph.py",
    "src/collectors/email_backfill.py",
    "src/collectors/refresh_all.py",
    "src/collectors/ucb_campus.py",
    "src/collectors/ucb_common.py",
    "src/collectors/uiuc_our_rss.py",
)

_UNSAFE_CORPUS_DUMP = re.compile(
    r"json\.dump\(\s*(?:all_opps|existing|opps|corpus|records|recs)\b"
)


def _temporary_files(destination: Path) -> list[Path]:
    return list(destination.parent.glob(f".{destination.name}.*.tmp"))


@pytest.mark.parametrize("relative_path", _AUTOMATIC_CORPUS_WRITERS)
def test_automatic_refresh_writer_uses_atomic_replace(relative_path: str) -> None:
    source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")

    assert "atomic_write_json(" in source
    assert _UNSAFE_CORPUS_DUMP.search(source) is None


def test_atomic_write_exposes_old_or_complete_new_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "opportunities.json"
    old_bytes = '[{"id":"old"}]'
    destination.write_text(old_bytes, encoding="utf-8")
    destination.chmod(0o640)
    payload = [{"id": "new", "title": "研究", "seen": date(2026, 7, 22)}]

    real_replace = os.replace
    observed_temporary: Path | None = None

    def checked_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        nonlocal observed_temporary
        source_path = Path(source)
        target_path = Path(target)
        observed_temporary = source_path
        assert source_path.parent == destination.parent
        assert target_path == destination
        assert destination.read_text(encoding="utf-8") == old_bytes
        assert json.loads(source_path.read_text(encoding="utf-8")) == [
            {"id": "new", "title": "研究", "seen": "2026-07-22"}
        ]
        real_replace(source_path, target_path)

    monkeypatch.setattr(atomic_json.os, "replace", checked_replace)

    atomic_json.atomic_write_json(destination, payload)

    assert observed_temporary is not None
    assert json.loads(destination.read_text(encoding="utf-8")) == [
        {"id": "new", "title": "研究", "seen": "2026-07-22"}
    ]
    assert destination.read_text(encoding="utf-8") == json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        default=str,
    )
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640
    assert _temporary_files(destination) == []


def test_atomic_write_flushes_file_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "opportunities.json"
    destination.write_text("[]", encoding="utf-8")
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def observed_fsync(descriptor: int) -> None:
        events.append("fsync")
        real_fsync(descriptor)

    def observed_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        events.append("replace")
        real_replace(source, target)

    monkeypatch.setattr(atomic_json.os, "fsync", observed_fsync)
    monkeypatch.setattr(atomic_json.os, "replace", observed_replace)

    atomic_json.atomic_write_json(destination, [{"id": "new"}])

    assert events[0:2] == ["fsync", "replace"]
    assert events[-1] == "fsync"  # directory durability after the rename


def test_serialization_failure_keeps_old_file_and_cleans_temporary(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "opportunities.json"
    old_bytes = '[{"id":"old"}]'
    destination.write_text(old_bytes, encoding="utf-8")

    with pytest.raises(TypeError):
        atomic_json.atomic_write_json(
            destination,
            [{"id": "new", "bad": object()}],
            default=None,
        )

    assert destination.read_text(encoding="utf-8") == old_bytes
    assert _temporary_files(destination) == []


def test_replace_failure_keeps_old_file_and_cleans_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "opportunities.json"
    old_bytes = '[{"id":"old"}]'
    destination.write_text(old_bytes, encoding="utf-8")

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(atomic_json.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        atomic_json.atomic_write_json(destination, [{"id": "new"}])

    assert destination.read_text(encoding="utf-8") == old_bytes
    assert _temporary_files(destination) == []


def test_atomic_copy_exposes_old_or_complete_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "refresh-artifact.json"
    destination = tmp_path / "opportunities.json"
    source_bytes = b'[{"id":"new"},{"id":"new-2"}]'
    old_bytes = b'[{"id":"old"}]'
    source.write_bytes(source_bytes)
    destination.write_bytes(old_bytes)
    real_replace = os.replace

    def checked_replace(source_path: object, destination_path: object) -> None:
        assert destination.read_bytes() == old_bytes
        assert Path(source_path).parent == destination.parent
        assert Path(source_path).read_bytes() == source_bytes
        real_replace(source_path, destination_path)

    monkeypatch.setattr(atomic_json.os, "replace", checked_replace)

    atomic_json.atomic_copy_file(source, destination)

    assert destination.read_bytes() == source_bytes
    assert _temporary_files(destination) == []


def test_atomic_copy_failure_keeps_old_file_and_cleans_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "refresh-artifact.json"
    destination = tmp_path / "opportunities.json"
    source.write_bytes(b'[{"id":"new"}]')
    destination.write_bytes(b'[{"id":"old"}]')

    def fail_copy(source_handle: object, destination_handle: object, **_kwargs: object) -> None:
        destination_handle.write(source_handle.read(3))
        raise OSError("simulated copy failure")

    monkeypatch.setattr(atomic_json.shutil, "copyfileobj", fail_copy)

    with pytest.raises(OSError, match="simulated copy failure"):
        atomic_json.atomic_copy_file(source, destination)

    assert destination.read_bytes() == b'[{"id":"old"}]'
    assert _temporary_files(destination) == []


def test_compact_format_matches_existing_shard_contract(tmp_path: Path) -> None:
    destination = tmp_path / "opportunities.json"
    payload = [{"id": "one", "title": "研究"}, {"id": "two"}]

    atomic_json.atomic_write_json(
        destination,
        payload,
        indent=None,
        separators=(",", ":"),
    )

    assert destination.read_text(encoding="utf-8") == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def test_atomic_text_write_exposes_old_or_complete_new_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "manifest.json"
    destination.write_text("old\n", encoding="utf-8")
    destination.chmod(0o640)
    real_replace = os.replace

    def checked_replace(source: object, target: object) -> None:
        assert destination.read_text(encoding="utf-8") == "old\n"
        assert Path(source).parent == destination.parent
        assert Path(source).read_text(encoding="utf-8") == "new\n"
        real_replace(source, target)

    monkeypatch.setattr(atomic_json.os, "replace", checked_replace)

    atomic_json.atomic_write_text(destination, "new\n")

    assert destination.read_text(encoding="utf-8") == "new\n"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640
    assert _temporary_files(destination) == []
