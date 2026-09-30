"""Bind legacy writing work to one detached anonymous public target snapshot."""
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.lib.target_actionability import assert_target_actionable, prework_refusal


@dataclass(frozen=True)
class WritingTargetSnapshot:
    # Source is retained only for trusted contact/freshness decisions. Never
    # pass it to a generator; public is exactly the anonymous detail material.
    source: dict
    public: dict
    version: str


def prepare_writing_snapshot(
    record: dict, expected_version: str | None, *,
    source_guard: Callable[[dict], None] | None = None,
) -> WritingTargetSnapshot:
    source = deepcopy(record)
    assert_target_actionable(source)
    if source_guard is not None:
        source_guard(source)
    public = project_public_detail(source)
    version = writing_target_version(public)
    if expected_version is not None and expected_version != version:
        raise prework_refusal(409, {
            "code": "WRITING_TARGET_CHANGED",
            "message": "This opportunity changed. Check it again before continuing.",
            "retryable": False,
        })
    return WritingTargetSnapshot(source, public, version)
