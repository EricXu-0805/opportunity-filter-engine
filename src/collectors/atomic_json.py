"""Crash-safe JSON writes for collector-owned artifacts.

Collector refreshes replace the assembled corpus while the API and local
tools may be reading it.  Writing the destination in place exposes a window
where those readers can observe an empty or half-written JSON document.  This
module renders into a uniquely named file in the destination directory,
flushes it to disk, and atomically swaps it into place.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _sync_directory(directory: Path) -> None:
    """Persist the rename when the platform supports directory fsync."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EINVAL, errno.ENOTSUP}:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in {errno.EBADF, errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(descriptor)


def atomic_write_json(
    path: str | os.PathLike[str],
    payload: Any,
    *,
    indent: int | str | None = 2,
    ensure_ascii: bool = False,
    default: Callable[[Any], Any] | None = str,
    sort_keys: bool = False,
    separators: tuple[str, str] | None = None,
) -> None:
    """Serialize ``payload`` and atomically replace ``path``.

    The temporary file always lives beside the destination, which is required
    for ``os.replace`` to be atomic.  If serialization, flushing, or the rename
    fails, the prior destination remains untouched and the temporary file is
    removed.  Existing file permissions are retained.
    """

    destination = Path(path)
    previous_mode: int | None = None
    try:
        previous_mode = stat.S_IMODE(destination.stat().st_mode)
    except FileNotFoundError:
        pass

    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    replaced = False
    try:
        if previous_mode is not None:
            os.fchmod(descriptor, previous_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor_open = False
            json.dump(
                payload,
                handle,
                indent=indent,
                ensure_ascii=ensure_ascii,
                default=default,
                sort_keys=sort_keys,
                separators=separators,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        replaced = True
        _sync_directory(destination.parent)
    finally:
        if descriptor_open:
            os.close(descriptor)
        if not replaced:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def atomic_copy_file(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
) -> None:
    """Atomically install an already-serialized artifact without reformatting it."""

    source_path = Path(source)
    destination_path = Path(destination)
    try:
        replacement_mode = stat.S_IMODE(destination_path.stat().st_mode)
    except FileNotFoundError:
        replacement_mode = stat.S_IMODE(source_path.stat().st_mode)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination_path.parent,
        prefix=f".{destination_path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    replaced = False
    try:
        os.fchmod(descriptor, replacement_mode)
        with source_path.open("rb") as source_handle:
            with os.fdopen(descriptor, "wb") as destination_handle:
                descriptor_open = False
                shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
        os.replace(temporary, destination_path)
        replaced = True
        _sync_directory(destination_path.parent)
    finally:
        if descriptor_open:
            os.close(descriptor)
        if not replaced:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def atomic_write_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically replace a text artifact with durable complete contents."""

    destination = Path(path)
    previous_mode: int | None = None
    try:
        previous_mode = stat.S_IMODE(destination.stat().st_mode)
    except FileNotFoundError:
        pass

    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    replaced = False
    try:
        if previous_mode is not None:
            os.fchmod(descriptor, previous_mode)
        with os.fdopen(descriptor, "w", encoding=encoding) as handle:
            descriptor_open = False
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        replaced = True
        _sync_directory(destination.parent)
    finally:
        if descriptor_open:
            os.close(descriptor)
        if not replaced:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
